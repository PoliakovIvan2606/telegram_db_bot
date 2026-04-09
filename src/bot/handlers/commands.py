"""Command handlers: /start /mode /save /search /chat."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.pipelines import process_manual, process_youtube
from config import Settings
from db.repo import Database
from services.openrouter import OpenRouterClient, rag_answer
from services.youtube_subs import extract_youtube_url
from services.yandex_webdav import YandexWebDAV

router = Router(name="commands")

HELP_TEXT = (
    "Команды:\n"
    "/start — эта справка\n"
    "/mode — переключить режим: **ingest** (сохранение) / **chat** (вопросы к базе)\n"
    "/save <текст> — сохранить заметку вручную\n"
    "/search <запрос> — поиск по базе (без ИИ)\n"
    "/chat <вопрос> — ответ ИИ с опорой на базу\n\n"
    "**Режим ingest:** ссылка на YouTube, текст или **голосовое сообщение** — "
    "материал будет обработан и добавлен в базу.\n"
    "**Режим chat:** обычное сообщение — то же, что /chat.\n"
)


def _split_reply(text: str, limit: int = 4000) -> list[str]:
    if len(text) <= limit:
        return [text]
    return [text[i : i + limit] for i in range(0, len(text), limit)]


@router.message(Command("start"))
async def cmd_start(message: Message, db: Database) -> None:
    mode = await db.get_mode(message.from_user.id)
    await message.answer(
        HELP_TEXT + f"\nТекущий режим: **{mode}**",
        parse_mode="Markdown",
    )


@router.message(Command("mode"))
async def cmd_mode(message: Message, db: Database) -> None:
    new_mode = await db.toggle_mode(message.from_user.id)
    await message.answer(f"Режим: **{new_mode}**", parse_mode="Markdown")


@router.message(Command("save"))
async def cmd_save(
    message: Message,
    command: CommandObject,
    db: Database,
    settings: Settings,
    or_client: OpenRouterClient,
    yandex: YandexWebDAV,
) -> None:
    text = (command.args or "").strip()
    url = extract_youtube_url(text) if text else None
    if url:
        await process_youtube(message, url, db, settings, or_client, yandex)
        return
    await process_manual(message, text, db, settings, or_client, yandex)


@router.message(Command("search"))
async def cmd_search(
    message: Message,
    command: CommandObject,
    db: Database,
    settings: Settings,
    or_client: OpenRouterClient,
) -> None:
    q = (command.args or "").strip()
    if not q:
        await message.answer("Укажите запрос: /search что искать")
        return
    await message.answer("Ищу…")
    try:
        emb = await or_client.embed_one(q)
        rows = await db.search_similar(
            message.from_user.id, emb, limit=settings.rag_top_k
        )
    except Exception as e:
        await message.answer(f"Ошибка: {e}")
        return
    if not rows:
        await message.answer("Ничего не найдено.")
        return
    lines: list[str] = []
    for i, r in enumerate(rows, start=1):
        title = r.get("title") or ""
        ref = r.get("source_ref") or ""
        body = (r.get("content") or "")[:500]
        dist = r.get("distance")
        lines.append(
            f"**{i}.** {title}\n`{ref}`\n{body}…\n_расстояние: {float(dist):.4f} (меньше — ближе)_\n"
        )
    out = "\n".join(lines)
    for chunk in _split_reply(out):
        await message.answer(chunk, parse_mode="Markdown")


@router.message(Command("chat"))
async def cmd_chat(
    message: Message,
    command: CommandObject,
    db: Database,
    settings: Settings,
    or_client: OpenRouterClient,
) -> None:
    q = (command.args or "").strip()
    if not q:
        await message.answer("Задайте вопрос: /chat ваш вопрос")
        return
    await message.answer("Думаю…")
    try:
        emb = await or_client.embed_one(q)
        rows = await db.search_similar(
            message.from_user.id, emb, limit=settings.rag_top_k
        )
        answer = await rag_answer(or_client, settings, q, rows)
    except Exception as e:
        await message.answer(f"Ошибка: {e}")
        return
    for chunk in _split_reply(answer):
        await message.answer(chunk)
