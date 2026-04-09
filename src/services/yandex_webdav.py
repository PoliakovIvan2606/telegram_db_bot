"""Upload files to Yandex Disk via WebDAV."""

from __future__ import annotations

from urllib.parse import quote

import httpx

from config import Settings


class YandexWebDAV:
    def __init__(self, settings: Settings) -> None:
        self._user = settings.yandex_webdav_user
        self._password = settings.yandex_webdav_password
        self._base = "https://webdav.yandex.ru"
        self._client = httpx.AsyncClient(
            auth=(self._user, self._password),
            timeout=httpx.Timeout(120.0, connect=30.0),
        )

    @property
    def enabled(self) -> bool:
        return bool(self._user and self._password)

    async def aclose(self) -> None:
        await self._client.aclose()

    def _path_url(self, remote_path: str) -> str:
        # remote_path like knowledge/123/file.md — encode segments
        parts = [p for p in remote_path.strip("/").split("/") if p]
        encoded = "/".join(quote(p, safe="") for p in parts)
        return f"{self._base}/{encoded}"

    async def mkdir_p(self, remote_dir: str) -> None:
        """Create folder and parents (MKCOL)."""
        if not self.enabled:
            return
        remote_dir = remote_dir.strip("/")
        if not remote_dir:
            return
        segments = remote_dir.split("/")
        cur: list[str] = []
        for seg in segments:
            if not seg:
                continue
            cur.append(seg)
            url = self._path_url("/".join(cur))
            r = await self._client.request("MKCOL", url)
            if r.status_code in (201, 405, 409):
                # 405/409 often means exists
                continue
            r.raise_for_status()

    async def put_bytes(self, remote_path: str, body: bytes, content_type: str) -> None:
        if not self.enabled:
            return
        remote_path = remote_path.lstrip("/")
        parent = "/".join(remote_path.split("/")[:-1])
        if parent:
            await self.mkdir_p(parent)
        url = self._path_url(remote_path)
        r = await self._client.put(
            url,
            content=body,
            headers={"Content-Type": content_type},
        )
        r.raise_for_status()

    async def put_text(self, remote_path: str, text: str, encoding: str = "utf-8") -> None:
        await self.put_bytes(remote_path, text.encode(encoding), "text/markdown; charset=utf-8")
