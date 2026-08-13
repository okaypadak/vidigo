#!/bin/sh
set -eu

python start_web.py &
web_pid=$!
python mcp_server.py serve &
mcp_pid=$!

stop_services() {
    kill -TERM "$web_pid" "$mcp_pid" 2>/dev/null || true
    wait "$web_pid" "$mcp_pid" 2>/dev/null || true
}

trap stop_services INT TERM
wait "$web_pid"
