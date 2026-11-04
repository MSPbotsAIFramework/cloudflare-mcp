"""Cache purge tool (AC8-AC9)."""

from __future__ import annotations

from typing import Literal

from mcp.types import ToolAnnotations

from ..errors import ToolError
from . import ClientFactory, run_tool

PurgeMode = Literal["everything", "files", "tags", "hosts"]

_SCOPED_KEYS: dict[str, str] = {"files": "files", "tags": "tags", "hosts": "hosts"}


def register(mcp, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=ToolAnnotations(destructiveHint=True, idempotentHint=True))
    async def cloudflare_purge_cache(
        zone_id: str,
        mode: PurgeMode,
        targets: list[str] | None = None,
    ) -> str:
        """Purge a zone's cache, either entirely or scoped to specific
        files, tags, or hosts.

        Args:
            zone_id: The Cloudflare zone id to purge cache for.
            mode: "everything" to purge the whole zone, or "files"/"tags"/"hosts"
                to purge only the items listed in targets.
            targets: URLs, cache-tags, or hostnames to purge; required and
                non-empty when mode is not "everything".
        """

        async def body(client):
            if mode == "everything":
                await client.purge_everything(zone_id)
                return {"purged": True, "mode": mode}

            key = _SCOPED_KEYS.get(mode)
            if key is None:
                raise ToolError("invalid_argument", f"Unknown purge mode: {mode}")
            if not targets:
                raise ToolError(
                    "invalid_argument",
                    f'targets is required and must be non-empty when mode="{mode}"',
                )
            await client.purge_scoped(zone_id=zone_id, key=key, targets=targets)
            return {"purged": True, "mode": mode}

        return await run_tool(client_factory, body)
