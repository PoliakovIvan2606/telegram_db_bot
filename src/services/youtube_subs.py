"""Download YouTube subtitles via yt-dlp and parse WebVTT to plain text."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any

import yt_dlp

_TAG_RE = re.compile(r"<[^>]+>")
_TIMESTAMP_RE = re.compile(
    r"^\d{2}:\d{2}:\d{2}\.\d{3}\s+-->\s+"
)


def _vtt_to_plain(vtt_content: str) -> str:
    lines_out: list[str] = []
    for raw in vtt_content.splitlines():
        line = raw.strip()
        if not line:
            continue
        upper = line.upper()
        if upper.startswith("WEBVTT"):
            continue
        if upper.startswith("NOTE"):
            continue
        if line.startswith("STYLE") or line.startswith("REGION"):
            continue
        if "-->" in line and _TIMESTAMP_RE.match(line):
            continue
        if line.isdigit() and len(line) <= 4:
            continue
        line = _TAG_RE.sub("", line).strip()
        if not line:
            continue
        lines_out.append(line)
    # collapse consecutive duplicates (YouTube progressive cues)
    deduped: list[str] = []
    for ln in lines_out:
        if deduped and deduped[-1] == ln:
            continue
        deduped.append(ln)
    text = " ".join(deduped)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _fetch_single_language(url: str, lang: str) -> tuple[str, dict[str, Any]]:
    """One yt-dlp run with a single subtitle language (avoids multi-lang 429 bursts)."""
    info: dict[str, Any] = {}
    with tempfile.TemporaryDirectory() as tmp:
        opts: dict[str, Any] = {
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": [lang],
            "outtmpl": str(Path(tmp) / "%(id)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": False,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
        if not info:
            raise RuntimeError("Не удалось получить информацию о видео")
        vid = str(info.get("id") or "")
        if not vid:
            raise RuntimeError("Нет id видео")
        vtt_path = _pick_vtt_file(tmp, vid, (lang,))
        if vtt_path is None or not vtt_path.is_file():
            raise RuntimeError(
                "Субтитры не найдены (ролик без субтитров или язык недоступен)."
            )
        raw = vtt_path.read_text(encoding="utf-8", errors="replace")
        text = _vtt_to_plain(raw)
        if not text.strip():
            raise RuntimeError("Субтитры пусты после парсинга.")
        return text, info


def _pick_vtt_file(tmp: str, video_id: str, langs: tuple[str, ...]) -> Path | None:
    base = Path(tmp)
    vtts = sorted(base.glob("*.vtt"))
    if not vtts:
        return None
    for lang in langs:
        for p in vtts:
            name = p.name.lower()
            if f".{lang}." in name or name.endswith(f".{lang}.vtt"):
                return p
            if p.stem.endswith(f".{lang}") or p.stem.endswith(f".{lang}.orig"):
                return p
    for p in vtts:
        if video_id and video_id in p.name:
            return p
    return vtts[0]


def fetch_youtube_transcript(url: str, langs: tuple[str, ...]) -> tuple[str, dict[str, Any]]:
    """
    Returns (plain_text, info) where info has at least id, title, webpage_url.
    Runs blocking I/O; call from asyncio.to_thread.
    """
    if not langs:
        raise RuntimeError("Не заданы языки субтитров (SUBTITLE_LANGS).")
    last_err: Exception | None = None
    for idx, lang in enumerate(langs):
        try:
            return _fetch_single_language(url, lang)
        except Exception as e:
            err_s = str(e)
            retryable_429 = "429" in err_s and idx < len(langs) - 1
            retryable_missing = (
                isinstance(e, RuntimeError)
                and idx < len(langs) - 1
                and (
                    "Субтитры не найдены" in err_s or "Субтитры пусты" in err_s
                )
            )
            if retryable_429 or retryable_missing:
                last_err = e
                continue
            raise
    if last_err is not None:
        raise last_err
    raise RuntimeError("Не удалось получить субтитры ни на одном из языков.")


def extract_youtube_url(text: str) -> str | None:
    """Return first YouTube watch or youtu.be URL from text, if any."""
    patterns = [
        r"(https?://(?:www\.)?youtube\.com/watch\?[^\s]+)",
        r"(https?://(?:www\.)?youtu\.be/[^\s]+)",
        r"(https?://(?:www\.)?youtube\.com/shorts/[^\s]+)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1).split("&")[0]  # trim extra query params for cleanliness
    return None
