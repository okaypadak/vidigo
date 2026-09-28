#!/bin/sh
# Docker-native equivalents of start_web.bat and start_mcp_http.bat.
# The .bat launchers cannot run in this Linux image.
set -u

if [ ! -x "$TEXTFORGE_FFMPEG_BINARY" ]; then
    echo "Container ffmpeg binary is missing: $TEXTFORGE_FFMPEG_BINARY" >&2
    exit 1
fi

if ! command -v node >/dev/null || [ ! -f "$TEXTFORGE_BGUTIL_SERVER_HOME/build/main.js" ]; then
    echo "Container embedded BgUtil runtime is missing." >&2
    exit 1
fi

python start_web.py &
web_pid=$!

python mcp_server.py serve &
mcp_pid=$!

stop_services() {
    kill -TERM "$web_pid" "$mcp_pid" 2>/dev/null || true
    wait "$web_pid" "$mcp_pid" 2>/dev/null || true
}

trap 'stop_services; exit 0' INT TERM

# A successful web health check alone is not enough: terminate the container if
# either default service stops, so Docker can report and restart the failure.
while kill -0 "$web_pid" 2>/dev/null && kill -0 "$mcp_pid" 2>/dev/null; do
    sleep 1
done

if ! kill -0 "$web_pid" 2>/dev/null; then
    wait "$web_pid"
    exit_code=$?
else
    wait "$mcp_pid"
    exit_code=$?
fi

stop_services
exit "$exit_code"
