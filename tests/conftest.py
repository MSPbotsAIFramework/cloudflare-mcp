from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from cloudflare_mcp.middleware import _token_var
from cloudflare_mcp.server import build_mcp


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retry backoff uses asyncio.sleep; tests must not actually wait."""
    monkeypatch.setattr("cloudflare_mcp.client.asyncio.sleep", AsyncMock(return_value=None))


@pytest.fixture
async def mcp():
    return build_mcp()


async def call_tool(mcp, name: str, arguments: dict, token: str = "test-token") -> dict:
    """Run a registered tool with a given credential token set, and parse its
    (always-JSON) text result back into a dict."""
    tools = await mcp.get_tools()
    tool = tools[name]
    reset = _token_var.set(token)
    try:
        result = await tool.run(arguments)
    finally:
        _token_var.reset(reset)
    text = result.content[0].text
    return json.loads(text)
