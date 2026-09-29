"""Read-only health probes for the local MCP HTTP service."""

import os

import anyio
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def check_mcp_health() -> tuple[dict, int]:
    """Require a successful MCP handshake and ping, without invoking tools."""
    try:
        host = os.environ.get("TEXTFORGE_MCP_HOST", "127.0.0.1")
        if host == "0.0.0.0":
            host = "127.0.0.1"
        elif host == "::":
            host = "::1"
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        port = int(os.environ.get("TEXTFORGE_MCP_PORT", "8000"))
        url = f"http://{host}:{port}/textforge/mcp"
        with anyio.fail_after(3):
            async with httpx.AsyncClient(timeout=1, trust_env=False) as client:
                async with streamable_http_client(url, http_client=client) as (reader, writer, _):
                    async with ClientSession(reader, writer) as session:
                        await session.initialize()
                        await session.send_ping()
    except Exception:
        return {"status": "error", "mcp": "error"}, 503
    return {"status": "ok", "mcp": "ok"}, 200
