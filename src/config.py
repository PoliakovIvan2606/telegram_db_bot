"""Load settings from environment."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


def _parse_allowed_ids(raw: str | None) -> frozenset[int]:
    if not raw or not raw.strip():
        return frozenset()
    return frozenset(int(x.strip()) for x in raw.split(",") if x.strip().isdigit())


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    database_url: str
    openrouter_api_key: str
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    embedding_model: str = "openai/text-embedding-3-small"
    embedding_dim: int = 1536
    chat_model: str = "openai/gpt-4o-mini"
    summary_model: str = "google/gemini-2.0-flash-001"
    yandex_webdav_user: str = ""
    yandex_webdav_password: str = ""
    allowed_user_ids: frozenset[int] = field(default_factory=frozenset)
    rag_top_k: int = 5
    chunk_max_chars: int = 900
    map_chunk_chars: int = 12000
    subtitle_langs: tuple[str, ...] = ("ru", "en")
    voice_transcription_model: str = "openai/gpt-4o-audio-preview"

    @classmethod
    def from_env(cls) -> Settings:
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        db = os.environ.get("DATABASE_URL", "").strip()
        or_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if not token or not db or not or_key:
            raise RuntimeError(
                "Set TELEGRAM_BOT_TOKEN, DATABASE_URL, OPENROUTER_API_KEY in environment"
            )
        return cls(
            telegram_bot_token=token,
            database_url=db,
            openrouter_api_key=or_key,
            openrouter_base_url=os.environ.get(
                "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
            ).rstrip("/"),
            embedding_model=os.environ.get(
                "EMBEDDING_MODEL", "openai/text-embedding-3-small"
            ).strip(),
            embedding_dim=int(os.environ.get("EMBEDDING_DIM", "1536")),
            chat_model=os.environ.get("CHAT_MODEL", "openai/gpt-4o-mini").strip(),
            summary_model=os.environ.get(
                "SUMMARY_MODEL", "google/gemini-2.0-flash-001"
            ).strip(),
            yandex_webdav_user=os.environ.get("YANDEX_DISK_WEBDAV_USER", "").strip(),
            yandex_webdav_password=os.environ.get(
                "YANDEX_DISK_WEBDAV_PASSWORD", ""
            ).strip(),
            allowed_user_ids=_parse_allowed_ids(os.environ.get("ALLOWED_USER_IDS")),
            rag_top_k=int(os.environ.get("RAG_TOP_K", "5")),
            chunk_max_chars=int(os.environ.get("CHUNK_MAX_CHARS", "900")),
            map_chunk_chars=int(os.environ.get("MAP_CHUNK_CHARS", "12000")),
            subtitle_langs=(
                tuple(
                    x.strip()
                    for x in os.environ.get("SUBTITLE_LANGS", "ru,en").split(",")
                    if x.strip()
                )
                or ("ru", "en")
            ),
            voice_transcription_model=os.environ.get(
                "VOICE_TRANSCRIPTION_MODEL", "openai/gpt-4o-audio-preview"
            ).strip(),
        )


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()
