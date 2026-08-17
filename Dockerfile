FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/data \
    TEXTFORGE_HOST=0.0.0.0 \
    TEXTFORGE_PORT=5000 \
    TEXTFORGE_MCP_HOST=0.0.0.0 \
    TEXTFORGE_MCP_PORT=8000

WORKDIR /app

# ffmpeg is required by yt-dlp and Whisper. curl is used by the container health check.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /data/textforge /data/cookie /data/textforge_logs

COPY requirements.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY . .

VOLUME ["/data"]
EXPOSE 5000 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl --fail --silent http://127.0.0.1:5000/status || exit 1

CMD ["sh", "docker-entrypoint.sh"]
