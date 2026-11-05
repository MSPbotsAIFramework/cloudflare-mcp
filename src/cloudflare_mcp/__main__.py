"""Entry point: run the Cloudflare MCP server over Streamable HTTP."""

from __future__ import annotations

import uvicorn

from .server import build_app
from .settings import settings


def main() -> None:
    app = build_app()
    uvicorn.run(app, host=settings.mcp_http_host, port=settings.mcp_http_port)


if __name__ == "__main__":
    main()
