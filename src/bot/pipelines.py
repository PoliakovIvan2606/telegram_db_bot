"""YouTube и ручное сохранение: суммаризация → Диск → индекс."""

from __future__ import annotations

import asyncio
import hashlib
import re

from aiogram.types import Message

from config import Settings
from db.repo import Database
from services.openrouter import (
    OpenRouterClient,
    summarize_long_transcript,
    summarize_short_text,
)
from services.rag import disk_path_for_manual, disk_path_for_youtube, index_text
from services.youtube_subs import fetch_youtube_transcript
from services.yandex_webdav import YandexWebDAV


async def process_youtube(
    message: Message,
    url: str,
    db: Database,
    settings: Settings,
    or_client: OpenRouterClient,
    yandex: YandexWebDAV,
) -> None:
    if message.from_user is None:
        return
    await message.answer("Скачиваю субтитры…")
    try:
        transcript, info = await asyncio.to_thread(
            fetch_youtube_transcript, url, settings.subtitle_langs
        )
    except Exception as e:
        await message.answer(f"Ошибка YouTube: {e}")
        return
    vid = str(info.get("id") or "video")
    title = str(info.get("title") or "") or None
    await message.answer("Делаю выжимку через ИИ…")
    try:
        summary = await summarize_long_transcript(or_client, settings, transcript)
    except Exception as e:
        await message.answer(f"Ошибка OpenRouter: {e}")
        return
    disk_path = disk_path_for_youtube(message.from_user.id, vid)
    md = f"# {title or vid}\n\n**URL:** {url}\n\n{summary}\n"
    if yandex.enabled:
        try:
            await yandex.put_text(disk_path, md)
        except Exception as e:
            await message.answer(f"Яндекс.Диск: не удалось загрузить ({e})")
    else:
        disk_path = "(Yandex Disk отключён)"
    await message.answer("Индексирую в базе…")
    try:
        n = await index_text(
            db,
            or_client,
            settings,
            user_id=message.from_user.id,
            source_type="youtube",
            source_ref=url,
            title=title,
            body=summary,
        )
    except Exception as e:
        await message.answer(f"Ошибка индексации: {e}")
        return
    await message.answer(
        f"Готово. Чанков в базе: {n}. Файл: `{disk_path}`",
        parse_mode="Markdown",
    )


async def process_manual(
    message: Message,
    raw_text: str,
    db: Database,
    settings: Settings,
    or_client: OpenRouterClient,
    yandex: YandexWebDAV,
) -> None:
    if message.from_user is None:
        return
    if not raw_text.strip():
        await message.answer("Пустой текст.")
        return
    await message.answer("Обрабатываю заметку…")
    try:
        summary = await summarize_short_text(or_client, settings, raw_text.strip())
    except Exception as e:
        await message.answer(f"OpenRouter: {e}")
        return
    h = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()[:12]
    slug = re.sub(r"\s+", "-", raw_text.strip()[:30])
    disk_path = disk_path_for_manual(message.from_user.id, f"{slug}_{h}")
    md = f"# Заметка\n\n{summary}\n"
    if yandex.enabled:
        try:
            await yandex.put_text(disk_path, md)
        except Exception as e:
            await message.answer(f"Яндекс.Диск: {e}")
    else:
        disk_path = "(Yandex Disk отключён)"
    try:
        n = await index_text(
            db,
            or_client,
            settings,
            user_id=message.from_user.id,
            source_type="manual",
            source_ref=disk_path,
            title="Заметка",
            body=summary,
        )
    except Exception as e:
        await message.answer(f"Индексация: {e}")
        return
    await message.answer(
        f"Сохранено. Чанков: {n}. Файл: `{disk_path}`",
        parse_mode="Markdown",
    )
