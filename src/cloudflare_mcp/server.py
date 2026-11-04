"""FastMCP factory: wires the credential middleware, the tool modules, and
the `/health` probe into one Starlette app.

`FastMCP.http_app()` (fastmcp 2.x) already returns a single, fully-wired
`StarletteWithLifespan` app -- its lifespan starts/stops the MCP session
manager itself, so there is no separate sub-app to `Mount()` and no lifespan
wiring pitfall to work around here (Section 7's "lifespan must be mounted to
the outer app" applies to Mount()-based layouts; this app has none).
"""

from __future__ import annotations

from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from .client import CloudflareClient
from .middleware import CredentialMiddleware, current_token
from .tools import cache, dns, zones

INSTRUCTIONS = """
Cloudflare MCP connector: list zones, manage DNS records (list/create/update/
delete), and purge zone cache (full or scoped to files/tags/hosts) for the
Cloudflare account reachable by the caller's API token.

Typical flows:
- "What domains do we have on Cloudflare?" -> cloudflare_list_zones
- "Add/change/remove a DNS record" -> cloudflare_list_dns_records to find the
  record id, then cloudflare_create_dns_record / cloudflare_update_dns_record
  / cloudflare_delete_dns_record
- "Clear the CDN cache for a zone" -> cloudflare_purge_cache

Scope: DNS records, zone listing, and cache purge only. Zone lifecycle, WAF,
Workers, Access, and billing are out of scope for this connector.
""".strip()


def _client_factory() -> CloudflareClient | None:
    """Built fresh per tool call from the request-scoped token -- never
    constructed once and reused, so it can never hold a stale or wrong
    tenant's credential (Section 3.3/3.4)."""
    token = current_token()
    if token is None:
        return None
    return CloudflareClient(token)


def build_mcp() -> FastMCP:
    # stateless_http is set on http_app() below, not here -- fastmcp
    # deprecates passing it at construction time in favor of passing it to
    # http_app()/run() (verified against the installed fastmcp version).
    mcp = FastMCP(
        name="cloudflare-mcp",
        instructions=INSTRUCTIONS,
    )

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_request: Request) -> JSONResponse:
        # Pure local probe -- never calls the Cloudflare API (Section 1.1):
        # upstream flakiness must not make this container's health check fail.
        return JSONResponse({"status": "ok"})

    zones.register(mcp, _client_factory)
    dns.register(mcp, _client_factory)
    cache.register(mcp, _client_factory)
    return mcp


def build_app() -> Starlette:
    mcp = build_mcp()
    return mcp.http_app(
        path="/mcp",
        stateless_http=True,
        middleware=[Middleware(CredentialMiddleware, protected_path="/mcp")],
    )
