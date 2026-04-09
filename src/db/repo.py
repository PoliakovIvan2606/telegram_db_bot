"""Asyncpg pool and knowledge / settings repository."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import asyncpg
from pgvector.asyncpg import register_vector

from config import Settings, get_settings

_schema_path = Path(__file__).resolve().parent / "schema.sql"

# region agent log
_AGENT_DEBUG_LOG = "/Users/ivanpolakov/code/AI_Telegram_bots/.cursor/debug-16da42.log"


def _agent_dbg(
    message: str,
    data: dict[str, Any],
    *,
    hypothesis_id: str,
    run_id: str = "pre-fix",
    location: str = "db/repo.py",
) -> None:
    try:
        line = json.dumps(
            {
                "sessionId": "16da42",
                "timestamp": int(time.time() * 1000),
                "location": location,
                "message": message,
                "data": data,
                "runId": run_id,
                "hypothesisId": hypothesis_id,
            },
            ensure_ascii=False,
        )
        with open(_AGENT_DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


# endregion


class Database:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, settings: Settings | None = None) -> Database:
        s = settings or get_settings()
        raw = s.database_url
        parsed = urlparse(raw)
        db_name = (parsed.path or "").lstrip("/").split("?")[0] or ""
        user_q = unquote(parsed.username or "")
        _agent_dbg(
            "dsn_before_pool",
            {
                "url_len": len(raw),
                "scheme": parsed.scheme or "",
                "user": user_q,
                "host": parsed.hostname,
                "port": parsed.port,
                "database": db_name,
                "has_password": bool(parsed.password),
            },
            hypothesis_id="H1",
        )
        if not raw:
            _agent_dbg("empty_database_url", {}, hypothesis_id="H4")
        try:
            # Apply schema (incl. CREATE EXTENSION vector) before create_pool: pool init
            # calls register_vector(), which requires type public.vector to exist.
            await _bootstrap_schema(raw, s)
            pool = await asyncpg.create_pool(
                raw,
                min_size=1,
                max_size=10,
                init=_init_connection,
            )
        except asyncpg.InvalidPasswordError as e:
            _agent_dbg(
                "pool_failed",
                {"exc_type": type(e).__name__, "pgcode": getattr(e, "sqlstate", None)},
                hypothesis_id="H5",
            )
            raise RuntimeError(
                "PostgreSQL rejected the password in DATABASE_URL (user "
                f"{user_q!r} at {parsed.hostname!r}). "
                "Update DATABASE_URL so the password matches your server's role, "
                "or set the role password to match, e.g. "
                "`ALTER USER postgres WITH PASSWORD '...';`"
            ) from e
        _agent_dbg(
            "pool_ok",
            {"user": user_q, "host": parsed.hostname, "database": db_name},
            hypothesis_id="H1",
            run_id="success",
        )
        return cls(pool)

    async def close(self) -> None:
        await self._pool.close()

    async def get_mode(self, user_id: int) -> str:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT mode FROM user_settings WHERE user_id = $1", user_id
            )
            if row is None:
                return "ingest"
            return str(row["mode"])

    async def set_mode(self, user_id: int, mode: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO user_settings (user_id, mode, updated_at)
                VALUES ($1, $2, now())
                ON CONFLICT (user_id) DO UPDATE SET mode = $2, updated_at = now()
                """,
                user_id,
                mode,
            )

    async def toggle_mode(self, user_id: int) -> str:
        current = await self.get_mode(user_id)
        new_mode = "chat" if current == "ingest" else "ingest"
        await self.set_mode(user_id, new_mode)
        return new_mode

    async def insert_chunk(
        self,
        user_id: int,
        source_type: str,
        source_ref: str,
        title: str | None,
        content: str,
        embedding: list[float],
    ) -> int:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO knowledge_chunks
                    (user_id, source_type, source_ref, title, content, embedding)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
                """,
                user_id,
                source_type,
                source_ref,
                title,
                content,
                embedding,
            )
            assert row is not None
            return int(row["id"])

    async def search_similar(
        self,
        user_id: int,
        embedding: list[float],
        limit: int,
    ) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, source_type, source_ref, title, content,
                       (embedding <=> $2::vector) AS distance
                FROM knowledge_chunks
                WHERE user_id = $1
                ORDER BY embedding <=> $2::vector
                LIMIT $3
                """,
                user_id,
                embedding,
                limit,
            )
            return [dict(r) for r in rows]


async def _bootstrap_schema(dsn: str, settings: Settings) -> None:
    if settings.embedding_dim != 1536:
        raise ValueError(
            "Update src/db/schema.sql vector(N) to match EMBEDDING_DIM "
            f"(currently {settings.embedding_dim})"
        )
    sql = _schema_path.read_text(encoding="utf-8")
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


async def _init_connection(conn: asyncpg.Connection) -> None:
    await register_vector(conn)
