"""Non-command text: ingest (YouTube / заметка) или chat (RAG)."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message

from bot.pipelines import process_manual, process_youtube
from config import Settings
from db.repo import Database
from services.openrouter import OpenRouterClient, rag_answer
from services.youtube_subs import extract_youtube_url
from services.yandex_webdav import YandexWebDAV

router = Router(name="messages")


def _split_reply(text: str, limit: int = 4000) -> list[str]:
    if len(text) <= limit:
        return [text]
    return [text[i : i + limit] for i in range(0, len(text), limit)]


@router.message(F.text, ~F.text.startswith("/"))
async def on_plain_text(
    message: Message,
    db: Database,
    settings: Settings,
    or_client: OpenRouterClient,
    yandex: YandexWebDAV,
) -> None:
    text = (message.text or "").strip()
    if not text:
        return
    mode = await db.get_mode(message.from_user.id)
    if mode == "ingest":
        url = extract_youtube_url(text)
        if url:
            await process_youtube(message, url, db, settings, or_client, yandex)
        else:
            await process_manual(message, text, db, settings, or_client, yandex)
        return
    await message.answer("Ищу в базе и отвечаю…")
    try:
        emb = await or_client.embed_one(text)
        rows = await db.search_similar(
            message.from_user.id, emb, limit=settings.rag_top_k
        )
        answer = await rag_answer(or_client, settings, text, rows)
    except Exception as e:
        await message.answer(f"Ошибка: {e}")
        return
    for chunk in _split_reply(answer):
        await message.answer(chunk)
