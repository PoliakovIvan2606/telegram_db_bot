# Бот: нужен ffmpeg для OGG→WAV (голос Telegram) и для yt-dlp/субтитров
FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "src.bot.main"]
