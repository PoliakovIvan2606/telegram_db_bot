"""OpenRouter: embeddings and chat completions via HTTPX."""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
from typing import Any

import httpx

from config import Settings


def _ogg_to_wav_via_ffmpeg(ogg_bytes: bytes) -> bytes:
    """Telegram voice is OGG Opus; OpenAI audio input accepts only wav/mp3 (see API error)."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError(
            "Нужен ffmpeg в PATH: голос Telegram — это OGG, а выбранная модель принимает только WAV/MP3. "
            "Установите ffmpeg (brew install ffmpeg) или смените VOICE_TRANSCRIPTION_MODEL на модель с поддержкой ogg."
        )
    proc = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "pipe:0",
            "-f",
            "wav",
            "-acodec",
            "pcm_s16le",
            "pipe:1",
        ],
        input=ogg_bytes,
        capture_output=True,
        timeout=120,
    )
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", errors="replace")[:800]
        raise RuntimeError(f"ffmpeg не смог конвертировать OGG→WAV: {err or proc.returncode}")
    out = proc.stdout or b""
    if len(out) < 100:
        raise RuntimeError("ffmpeg вернул слишком короткий WAV; проверьте входное аудио.")
    return out


def _raise_for_openrouter_status(r: httpx.Response) -> None:
    """Map common OpenRouter HTTP errors to clear messages (no secrets)."""
    if r.status_code == 401:
        raise RuntimeError(
            "OpenRouter: неверный или отозванный API-ключ (401). "
            "Создайте ключ на https://openrouter.ai/keys и пропишите OPENROUTER_API_KEY в .env"
        ) from None
    if r.status_code == 402:
        raise RuntimeError(
            "OpenRouter: недостаточно кредитов или требуется оплата (402). "
            "Проверьте баланс на https://openrouter.ai/"
        ) from None
    r.raise_for_status()


class OpenRouterClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.openrouter_base_url,
            headers={
                "Authorization": f"Bearer {settings.openrouter_api_key}",
                "HTTP-Referer": "https://github.com/local/knowledge-bot",
                "X-Title": "Knowledge Telegram Bot",
            },
            timeout=httpx.Timeout(120.0, connect=30.0),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        r = await self._client.post(
            "/embeddings",
            json={
                "model": self._settings.embedding_model,
                "input": texts,
            },
        )
        _raise_for_openrouter_status(r)
        data = r.json()
        items = data.get("data") or []
        # OpenAI-style: sort by index
        items.sort(key=lambda x: x.get("index", 0))
        return [list(map(float, it["embedding"])) for it in items]

    async def embed_one(self, text: str) -> list[float]:
        vecs = await self.embed_batch([text])
        return vecs[0]

    async def chat(
        self,
        *,
        model: str,
        system: str,
        user: str,
        temperature: float = 0.3,
    ) -> str:
        r = await self._client.post(
            "/chat/completions",
            json={
                "model": model,
                "temperature": temperature,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        _raise_for_openrouter_status(r)
        data = r.json()
        try:
            return str(data["choices"][0]["message"]["content"]).strip()
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError(f"Unexpected OpenRouter response: {json.dumps(data)[:500]}") from e

    async def transcribe_audio(
        self,
        *,
        model: str,
        audio_bytes: bytes,
        audio_format: str = "ogg",
    ) -> str:
        """Speech-to-text via multimodal chat (OpenRouter input_audio)."""
        payload_bytes = audio_bytes
        fmt = audio_format
        if audio_format.lower() == "ogg":
            payload_bytes = _ogg_to_wav_via_ffmpeg(audio_bytes)
            fmt = "wav"
        b64 = base64.b64encode(payload_bytes).decode("ascii")
        r = await self._client.post(
            "/chat/completions",
            json={
                "model": model,
                "temperature": 0,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    "Дословно расшифруй речь в этом аудио. "
                                    "Сохраняй язык оригинала. Без перевода, без комментариев и вступлений — только текст."
                                ),
                            },
                            {
                                "type": "input_audio",
                                "input_audio": {
                                    "data": b64,
                                    "format": fmt,
                                },
                            },
                        ],
                    }
                ],
            },
        )
        _raise_for_openrouter_status(r)
        data = r.json()
        try:
            return str(data["choices"][0]["message"]["content"]).strip()
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError(f"Unexpected OpenRouter response: {json.dumps(data)[:500]}") from e


def split_for_map(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            cut = text.rfind("\n\n", start, end)
            if cut == -1 or cut < start + max_chars // 2:
                cut = text.rfind(" ", start, end)
            if cut > start:
                end = cut
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end
    return chunks or [text]


async def summarize_long_transcript(
    client: OpenRouterClient,
    settings: Settings,
    transcript: str,
) -> str:
    """Map-reduce summarization for long subtitles."""
    model = settings.summary_model
    chunks = split_for_map(transcript, settings.map_chunk_chars)
    system_map = (
        "Ты помощник для извлечения смысла из транскрипта видео. "
        "Дай только маркированный список ключевых тезисов, без вводных фраз. "
        "Язык ответа — как в исходном тексте."
    )
    partials: list[str] = []
    for i, ch in enumerate(chunks):
        user = f"Фрагмент {i + 1}/{len(chunks)}:\n\n{ch}"
        partials.append(
            await client.chat(
                model=model,
                system=system_map,
                user=user,
                temperature=0.2,
            )
        )
    combined = "\n\n".join(partials)
    if len(combined) < settings.map_chunk_chars:
        system_reduce = (
            "Объедини тезисы в структурированную выжимку: "
            "краткое введение (1–2 предложения), раздел «Главные идеи», "
            "раздел «Факты и цифры» (если есть), раздел «Действия / выводы». "
            "Без воды, без повторов."
        )
        return await client.chat(
            model=model,
            system=system_reduce,
            user=combined,
            temperature=0.3,
        )
    # second map on combined bullets
    subchunks = split_for_map(combined, settings.map_chunk_chars)
    merged: list[str] = []
    for i, ch in enumerate(subchunks):
        merged.append(
            await client.chat(
                model=model,
                system=system_map,
                user=f"Часть {i + 1}/{len(subchunks)}:\n\n{ch}",
                temperature=0.2,
            )
        )
    combined2 = "\n\n".join(merged)
    system_reduce = (
        "Объедини в одну связную выжимку с заголовками уровня ## в Markdown."
    )
    return await client.chat(
        model=model,
        system=system_reduce,
        user=combined2,
        temperature=0.3,
    )


async def summarize_short_text(
    client: OpenRouterClient,
    settings: Settings,
    text: str,
) -> str:
    """Normalize / lightly structure short manual notes."""
    return await client.chat(
        model=settings.summary_model,
        system=(
            "Сохрани смысл заметки пользователя. "
            "Оформи кратко в Markdown: заголовок ## и список или абзацы. "
            "Не выдумывай факты."
        ),
        user=text,
        temperature=0.2,
    )


async def rag_answer(
    client: OpenRouterClient,
    settings: Settings,
    question: str,
    context_chunks: list[dict[str, Any]],
) -> str:
    parts: list[str] = []
    for i, row in enumerate(context_chunks, start=1):
        ref = row.get("source_ref") or ""
        title = row.get("title") or ""
        body = row.get("content") or ""
        parts.append(f"[Источник {i}] {title}\n{ref}\n{body}")
    ctx = "\n\n---\n\n".join(parts)
    system = (
        "Ты ассистент с доступом к фрагментам личной базы знаний пользователя. "
        "Отвечай по-русски, опираясь только на контекст. "
        "Если в контексте нет ответа — так и скажи. "
        "В конце перечисли номера использованных источников [Источник n], если они были релевантны."
    )
    user = f"Контекст:\n\n{ctx}\n\nВопрос:\n{question}"
    return await client.chat(
        model=settings.chat_model,
        system=system,
        user=user,
        temperature=0.4,
    )
