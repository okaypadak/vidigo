FROM node:22-bookworm-slim AS bgutil_builder

ARG BGUTIL_VERSION=2.0.0

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt
RUN git clone --depth 1 --single-branch --branch "${BGUTIL_VERSION}" \
        https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git bgutil-provider

WORKDIR /opt/bgutil-provider/server
RUN npm ci \
    && npx tsc

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

# yt-dlp and the bundled BgUtil provider need Node.js 22+.
COPY --from=bgutil_builder /usr/local/bin/node /usr/local/bin/node

# ffmpeg is required by yt-dlp and Whisper. curl is used by the container health check.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /data/textforge /data/cookie /data/textforge_logs

COPY requirements.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

ENV TEXTFORGE_RUNTIME=container \
    TEXTFORGE_MEDIA_ROOT=/data/textforge \
    TEXTFORGE_COOKIE_ROOT=/data/cookie \
    TEXTFORGE_FFMPEG_BINARY=/usr/bin/ffmpeg \
    TEXTFORGE_BGUTIL_HOST=127.0.0.1 \
    TEXTFORGE_BGUTIL_PORT=4416 \
    TEXTFORGE_BGUTIL_BASE_URL=http://127.0.0.1:4416 \
    TEXTFORGE_BGUTIL_SERVER_HOME=/opt/bgutil-provider

COPY --from=bgutil_builder /opt/bgutil-provider/server/build /opt/bgutil-provider/build
COPY --from=bgutil_builder /opt/bgutil-provider/server/node_modules /opt/bgutil-provider/node_modules
COPY --from=bgutil_builder /opt/bgutil-provider/server/package.json /opt/bgutil-provider/package.json

COPY . .

VOLUME ["/data"]
EXPOSE 5000 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl --fail --silent http://127.0.0.1:5000/status || exit 1

CMD ["sh", "docker-entrypoint.sh"]
