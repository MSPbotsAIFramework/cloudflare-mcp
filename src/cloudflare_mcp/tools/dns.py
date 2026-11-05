"""DNS record tools (AC3-AC7)."""

from __future__ import annotations

from typing import Any

from mcp.types import ToolAnnotations

from . import ClientFactory, run_tool
from .zones import DEFAULT_PER_PAGE, _clamp_per_page


def _record_summary(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": record.get("id"),
        "type": record.get("type"),
        "name": record.get("name"),
        "content": record.get("content"),
        "ttl": record.get("ttl"),
        "proxied": record.get("proxied"),
    }


def register(mcp, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True))
    async def cloudflare_list_dns_records(
        zone_id: str,
        type: str | None = None,  # noqa: A002 -- matches Cloudflare's own field name
        name: str | None = None,
        page: int = 1,
        per_page: int = DEFAULT_PER_PAGE,
    ) -> str:
        """List DNS records in a zone, optionally filtered by type and name.

        Args:
            zone_id: The Cloudflare zone id to list records for.
            type: DNS record type to filter by, e.g. "A", "CNAME", "TXT".
            name: Exact record name to filter by.
            page: Page number, starting at 1.
            per_page: Results per page, default 50, max 200.
        """
        per_page = _clamp_per_page(per_page)

        async def body(client):
            data = await client.list_dns_records(zone_id=zone_id, type_=type, name=name, page=page, per_page=per_page)
            records = [_record_summary(r) for r in data.get("result") or []]
            info = data.get("result_info") or {}
            total_pages = info.get("total_pages", page)
            return {
                "records": records,
                "page": info.get("page", page),
                "has_more": info.get("page", page) < total_pages,
            }

        return await run_tool(client_factory, body)

    @mcp.tool(annotations=ToolAnnotations(destructiveHint=False, idempotentHint=False))
    async def cloudflare_create_dns_record(
        zone_id: str,
        type: str,  # noqa: A002
        name: str,
        content: str,
        ttl: int | None = None,
        proxied: bool | None = None,
        priority: int | None = None,
    ) -> str:
        """Create a DNS record in a zone. Not idempotent: calling this twice
        with the same fields creates two records -- list first if you need to
        avoid duplicates.

        Args:
            zone_id: The Cloudflare zone id to create the record in.
            type: DNS record type, e.g. "A", "CNAME", "TXT", "MX".
            name: The record's name (hostname).
            content: The record's value (e.g. an IP address for an A record).
            ttl: Time to live in seconds. Cloudflare default applies if omitted.
            proxied: Whether traffic is proxied through Cloudflare.
            priority: Priority, used by MX/SRV records.
        """
        payload: dict[str, Any] = {"type": type, "name": name, "content": content}
        if ttl is not None:
            payload["ttl"] = ttl
        if proxied is not None:
            payload["proxied"] = proxied
        if priority is not None:
            payload["priority"] = priority

        async def body(client):
            data = await client.create_dns_record(zone_id=zone_id, record=payload)
            return _record_summary(data.get("result") or {})

        return await run_tool(client_factory, body)

    @mcp.tool(annotations=ToolAnnotations(destructiveHint=True, idempotentHint=True))
    async def cloudflare_update_dns_record(
        zone_id: str,
        record_id: str,
        type: str | None = None,  # noqa: A002
        name: str | None = None,
        content: str | None = None,
        ttl: int | None = None,
        proxied: bool | None = None,
        priority: int | None = None,
    ) -> str:
        """Partially update a DNS record: only the fields you pass are
        changed, every other existing field on the record is preserved.

        Args:
            zone_id: The Cloudflare zone id the record belongs to.
            record_id: The DNS record id to update.
            type: New record type, if changing it.
            name: New record name, if changing it.
            content: New record value, if changing it.
            ttl: New time to live in seconds, if changing it.
            proxied: New proxied setting, if changing it.
            priority: New priority, if changing it (MX/SRV records).
        """
        fields: dict[str, Any] = {}
        if type is not None:
            fields["type"] = type
        if name is not None:
            fields["name"] = name
        if content is not None:
            fields["content"] = content
        if ttl is not None:
            fields["ttl"] = ttl
        if proxied is not None:
            fields["proxied"] = proxied
        if priority is not None:
            fields["priority"] = priority

        async def body(client):
            data = await client.update_dns_record(zone_id=zone_id, record_id=record_id, fields=fields)
            return _record_summary(data.get("result") or {})

        return await run_tool(client_factory, body)

    @mcp.tool(annotations=ToolAnnotations(destructiveHint=True, idempotentHint=True))
    async def cloudflare_delete_dns_record(zone_id: str, record_id: str) -> str:
        """Delete a DNS record by its exact id. Deleting an id that no longer
        exists returns a `not_found` error, not an exception -- safe to retry.

        Args:
            zone_id: The Cloudflare zone id the record belongs to.
            record_id: The DNS record id to delete.
        """

        async def body(client):
            data = await client.delete_dns_record(zone_id=zone_id, record_id=record_id)
            deleted_id = (data.get("result") or {}).get("id", record_id)
            return {"id": deleted_id, "deleted": True}

        return await run_tool(client_factory, body)
