"""Aiogram bot: polling entry."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parent.parent
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from aiogram import Bot, Dispatcher

from bot.handlers.commands import router as commands_router
from bot.handlers.messages import router as messages_router
from bot.middlewares.access import AppMiddleware
from config import get_settings
from db.repo import Database
from services.openrouter import OpenRouterClient
from services.yandex_webdav import YandexWebDAV

logger = logging.getLogger(__name__)


async def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = get_settings()
    db = await Database.connect(settings)
    or_client = OpenRouterClient(settings)
    yandex = YandexWebDAV(settings)
    bot = Bot(settings.telegram_bot_token)
    dp = Dispatcher()
    dp.message.middleware(AppMiddleware(db, settings, or_client, yandex))
    dp.include_router(commands_router)
    dp.include_router(messages_router)
    logger.info("Starting polling…")
    try:
        await dp.start_polling(bot)
    finally:
        await or_client.aclose()
        await yandex.aclose()
        await db.close()
        logger.info("Shutdown complete.")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
