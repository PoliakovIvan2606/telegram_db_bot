"""Inject app dependencies and optional allowlist."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

from config import Settings
from db.repo import Database
from services.openrouter import OpenRouterClient
from services.yandex_webdav import YandexWebDAV


class AppMiddleware(BaseMiddleware):
    def __init__(
        self,
        db: Database,
        settings: Settings,
        or_client: OpenRouterClient,
        yandex: YandexWebDAV,
    ) -> None:
        self.db = db
        self.settings = settings
        self.or_client = or_client
        self.yandex = yandex

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        data["db"] = self.db
        data["settings"] = self.settings
        data["or_client"] = self.or_client
        data["yandex"] = self.yandex

        uid: int | None = None
        if isinstance(event, Message) and event.from_user:
            uid = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            uid = event.from_user.id
        elif isinstance(event, Update):
            if event.message and event.message.from_user:
                uid = event.message.from_user.id
            elif event.callback_query and event.callback_query.from_user:
                uid = event.callback_query.from_user.id
        if uid is None:
            return await handler(event, data)

        allowed = self.settings.allowed_user_ids
        if allowed and uid not in allowed:
            if isinstance(event, Message):
                await event.answer("Доступ запрещён.")
            elif isinstance(event, CallbackQuery) and event.message:
                await event.message.answer("Доступ запрещён.")
            return None

        return await handler(event, data)
