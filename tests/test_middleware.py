"""AC2 (missing credential header -> 401, not a 500) and AC11 (concurrent
requests carrying different tokens never see each other's credential)."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from cloudflare_mcp.middleware import CREDENTIAL_HEADER, CredentialMiddleware, current_token
from cloudflare_mcp.server import build_app


async def _echo_token(request):
    # Simulate a tiny bit of "work" so concurrent requests actually overlap
    # in time rather than running strictly sequentially.
    await asyncio.sleep(0.01)
    return JSONResponse({"token": current_token()})


def _echo_app() -> Starlette:
    """A minimal app wrapped in the real CredentialMiddleware, used to test
    the middleware's isolation behavior directly without the full FastMCP
    session-manager machinery (which needs ASGI lifespan events that
    httpx.ASGITransport does not emit)."""
    app = Starlette(routes=[Route("/mcp", _echo_token, methods=["POST"])])
    app.add_middleware(CredentialMiddleware, protected_path="/mcp")
    return app


@pytest.fixture
async def client():
    app = _echo_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# AC2 / TC2
# ---------------------------------------------------------------------------


async def test_missing_credential_header_returns_401(client):
    response = await client.post("/mcp", json={})
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "unauthorized"
    assert CREDENTIAL_HEADER in body["required_headers"]


async def test_missing_credential_header_on_the_real_app_returns_401():
    """Same check against the fully assembled app (server.build_app()), not
    just the isolated test harness -- confirms the middleware is actually
    wired in front of /mcp in production wiring, not only in this test's
    stand-in app. The middleware intercepts before the request reaches the
    MCP session manager, so this does not require ASGI lifespan events."""
    transport = httpx.ASGITransport(app=build_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.post("/mcp", json={})
    assert response.status_code == 401
    assert CREDENTIAL_HEADER in response.json()["required_headers"]


async def test_present_credential_header_reaches_the_request_context(client):
    response = await client.post("/mcp", json={}, headers={CREDENTIAL_HEADER: "tok-a"})
    assert response.status_code == 200
    assert response.json()["token"] == "tok-a"


# ---------------------------------------------------------------------------
# AC11 / TC11
# ---------------------------------------------------------------------------


async def test_concurrent_requests_with_different_tokens_do_not_leak_credentials(client):
    async def call(token: str) -> str:
        response = await client.post("/mcp", json={}, headers={CREDENTIAL_HEADER: token})
        return response.json()["token"]

    results = await asyncio.gather(*(call(f"tenant-{i}-token") for i in range(20)))

    assert results == [f"tenant-{i}-token" for i in range(20)]
