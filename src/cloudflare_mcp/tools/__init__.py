"""Shared helpers for tool modules.

Each `tools/<resource>.py` exports `register(mcp, client_factory)`.
`client_factory()` builds a `CloudflareClient` bound to the current request's
token (read from the ContextVar set by middleware.py); it returns `None` only
if called outside a request scope, which should not happen in production
since the middleware already rejects requests without the header.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from ..client import CloudflareClient
from ..errors import ToolError, error_envelope, error_envelope_from

ClientFactory = Callable[[], CloudflareClient | None]


def dumps(payload: dict[str, Any]) -> str:
    """Compact, non-ASCII-escaping JSON serialization (Section 2.5 token
    economy -- never `indent=2`, always `ensure_ascii=False`)."""
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


async def run_tool(
    client_factory: ClientFactory, body: Callable[[CloudflareClient], Awaitable[dict[str, Any]]]
) -> str:
    """Build the per-request client, run `body`, and turn any `ToolError`
    (or unexpected exception) into the structured error envelope instead of
    letting it raise past the tool boundary (Section 4.1: tools never raise).
    """
    client = client_factory()
    if client is None:
        return error_envelope("not_configured", "No Cloudflare credential available for this request")
    try:
        result = await body(client)
    except ToolError as exc:
        return error_envelope_from(exc)
    except Exception as exc:  # noqa: BLE001 -- last-resort boundary, see Section 4.2
        return error_envelope("upstream_error", f"Unexpected error calling Cloudflare: {exc}")
    return dumps(result)
