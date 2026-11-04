"""Zone listing tools (AC1)."""

from __future__ import annotations

from typing import Any

from mcp.types import ToolAnnotations

from . import ClientFactory, run_tool

DEFAULT_PER_PAGE = 50
MAX_PER_PAGE = 200


def _clamp_per_page(per_page: int) -> int:
    return max(1, min(per_page, MAX_PER_PAGE))


def _zone_summary(zone: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": zone.get("id"),
        "name": zone.get("name"),
        "status": zone.get("status"),
        "plan": (zone.get("plan") or {}).get("name"),
    }


def register(mcp, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True))
    async def cloudflare_list_zones(
        name: str | None = None,
        status: str | None = None,
        page: int = 1,
        per_page: int = DEFAULT_PER_PAGE,
    ) -> str:
        """List the Cloudflare zones reachable by the supplied API token.

        Args:
            name: Exact zone name to filter by, e.g. "example.com".
            status: Zone status to filter by, e.g. "active".
            page: Page number, starting at 1.
            per_page: Results per page, default 50, max 200.
        """
        per_page = _clamp_per_page(per_page)

        async def body(client):
            data = await client.list_zones(name=name, status=status, page=page, per_page=per_page)
            zones = [_zone_summary(z) for z in data.get("result") or []]
            info = data.get("result_info") or {}
            total_pages = info.get("total_pages", page)
            return {
                "zones": zones,
                "page": info.get("page", page),
                "has_more": info.get("page", page) < total_pages,
            }

        return await run_tool(client_factory, body)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True))
    async def cloudflare_get_zone(zone_id: str) -> str:
        """Get a single Cloudflare zone's details by its id.

        Args:
            zone_id: The Cloudflare zone id.
        """

        async def body(client):
            data = await client.get_zone(zone_id)
            zone = data.get("result") or {}
            return {
                "id": zone.get("id"),
                "name": zone.get("name"),
                "status": zone.get("status"),
                "plan": (zone.get("plan") or {}).get("name"),
                "name_servers": zone.get("name_servers") or [],
            }

        return await run_tool(client_factory, body)
