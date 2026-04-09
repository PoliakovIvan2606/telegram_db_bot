"""Chunk text, embed, store in DB."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from config import Settings

if TYPE_CHECKING:
    from db.repo import Database
    from services.openrouter import OpenRouterClient


def chunk_text(text: str, max_chars: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    start = 0
    overlap = min(100, max_chars // 10)
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            cut = text.rfind("\n\n", start, end)
            if cut == -1 or cut < start + max_chars // 2:
                cut = text.rfind(" ", start, end)
            if cut > start:
                end = cut
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks


async def index_text(
    db: Database,
    or_client: OpenRouterClient,
    settings: Settings,
    *,
    user_id: int,
    source_type: str,
    source_ref: str,
    title: str | None,
    body: str,
) -> int:
    """Split body into chunks, embed, insert. Returns number of chunks inserted."""
    parts = chunk_text(body, settings.chunk_max_chars)
    if not parts:
        return 0
    embeddings = await or_client.embed_batch(parts)
    n = 0
    for content, emb in zip(parts, embeddings, strict=True):
        await db.insert_chunk(
            user_id=user_id,
            source_type=source_type,
            source_ref=source_ref,
            title=title,
            content=content,
            embedding=emb,
        )
        n += 1
    return n


def disk_path_for_youtube(user_id: int, video_id: str, suffix: str = "md") -> str:
    today = date.today().isoformat()
    return f"knowledge/{user_id}/{today}_{video_id}.{suffix}"


def disk_path_for_manual(user_id: int, slug: str, suffix: str = "md") -> str:
    today = date.today().isoformat()
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in slug[:40])
    return f"knowledge/{user_id}/{today}_{safe}.{suffix}"
