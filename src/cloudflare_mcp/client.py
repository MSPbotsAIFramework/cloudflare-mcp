"""Thin async wrapper around the Cloudflare REST API v4.

The token is never read at construction time or cached on the instance
across requests -- callers pass the token (read fresh from the per-request
ContextVar by the tool layer) into every call. This keeps the client safe to
reuse across concurrent requests carrying different tenants' tokens, and
keeps the credential out of any long-lived object.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from .errors import ToolError
from .settings import settings

CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 30.0
MAX_RETRIES = 3
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
# Hard ceiling on total time spent on one tool call including retries
# (Section 5: "single tool call total duration, including retries, must be
# under 120s").
MAX_TOTAL_RETRY_SECONDS = 100.0


def _invalid_request_code(errors: list[dict[str, Any]]) -> bool:
    """Cloudflare's own "invalid request" error codes live in the 9xxx
    family; HTTP status is also 400 in that case, so this is a secondary
    signal, not the primary one."""
    for err in errors:
        code = err.get("code")
        if isinstance(code, int) and 9000 <= code < 10000:
            return True
    return False


class CloudflareClient:
    """One instance is created per request (see tools/*.py); it never
    outlives the request that constructed it with a given token."""

    def __init__(self, token: str, http_client: httpx.AsyncClient | None = None):
        self._token = token
        # Allow test injection of a client (respx); production always builds
        # its own so each request gets its own connection pool scope.
        self._client = http_client or httpx.AsyncClient(
            base_url=settings.cloudflare_base_url,
            timeout=httpx.Timeout(connect=CONNECT_TIMEOUT, read=READ_TIMEOUT, write=READ_TIMEOUT, pool=READ_TIMEOUT),
        )
        self._owns_client = http_client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    async def _request(
        self, method: str, path: str, *, params: dict[str, Any] | None = None, json_body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Issue one Cloudflare API call, retrying 429/5xx with backoff that
        honors Retry-After, and map the result into this service's own
        structured error vocabulary. Raises ToolError on any failure; never
        raises a bare httpx/network exception past this method.
        """
        attempt = 0
        elapsed = 0.0
        last_exc: Exception | None = None

        while attempt <= MAX_RETRIES:
            try:
                response = await self._client.request(
                    method,
                    path,
                    params=params,
                    json=json_body,
                    headers=self._headers(),
                )
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt == MAX_RETRIES or elapsed >= MAX_TOTAL_RETRY_SECONDS:
                    raise ToolError("upstream_error", f"Network error calling Cloudflare: {exc}") from exc
                sleep_for = min(2**attempt, 10)
                await asyncio.sleep(sleep_for)
                elapsed += sleep_for
                attempt += 1
                continue

            if response.status_code in RETRY_STATUS_CODES and attempt < MAX_RETRIES and elapsed < MAX_TOTAL_RETRY_SECONDS:
                retry_after = response.headers.get("Retry-After")
                try:
                    sleep_for = float(retry_after) if retry_after else min(2**attempt, 10)
                except ValueError:
                    sleep_for = min(2**attempt, 10)
                await asyncio.sleep(sleep_for)
                elapsed += sleep_for
                attempt += 1
                continue

            return self._parse(response)

        # Exhausted retries without a usable response.
        raise ToolError("upstream_error", f"Cloudflare request failed after retries: {last_exc}")

    def _parse(self, response: httpx.Response) -> dict[str, Any]:
        status = response.status_code

        try:
            body = response.json()
        except ValueError:
            body = {}

        errors = body.get("errors") or []

        if status in (401, 403):
            # Cloudflare rejected the token itself (revoked/invalid/insufficient
            # scope). The header was present (middleware already checked
            # that) -- this is the upstream's own authorization decision.
            raise ToolError("unauthorized", _first_message(errors) or "Cloudflare rejected the supplied API token")
        if status == 404:
            raise ToolError("not_found", _first_message(errors) or "Resource not found")
        if status == 429:
            raise ToolError("rate_limited", _first_message(errors) or "Cloudflare rate limit exceeded")
        if status == 400 or _invalid_request_code(errors):
            raise ToolError("invalid_argument", _first_message(errors) or "Cloudflare rejected the request arguments")
        if status >= 500:
            raise ToolError("upstream_error", _first_message(errors) or f"Cloudflare returned HTTP {status}")
        if status >= 400:
            raise ToolError("upstream_error", _first_message(errors) or f"Cloudflare returned HTTP {status}")

        if body.get("success") is False:
            raise ToolError("upstream_error", _first_message(errors) or "Cloudflare reported success=false")

        return body

    # -- Zones ------------------------------------------------------------

    async def list_zones(self, *, name: str | None, status: str | None, page: int, per_page: int) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if name:
            params["name"] = name
        if status:
            params["status"] = status
        return await self._request("GET", "/zones", params=params)

    async def get_zone(self, zone_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/zones/{zone_id}")

    # -- DNS records --------------------------------------------------------

    async def list_dns_records(
        self, *, zone_id: str, type_: str | None, name: str | None, page: int, per_page: int
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if type_:
            params["type"] = type_
        if name:
            params["name"] = name
        return await self._request("GET", f"/zones/{zone_id}/dns_records", params=params)

    async def create_dns_record(self, *, zone_id: str, record: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", f"/zones/{zone_id}/dns_records", json_body=record)

    async def update_dns_record(self, *, zone_id: str, record_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        return await self._request("PATCH", f"/zones/{zone_id}/dns_records/{record_id}", json_body=fields)

    async def delete_dns_record(self, *, zone_id: str, record_id: str) -> dict[str, Any]:
        return await self._request("DELETE", f"/zones/{zone_id}/dns_records/{record_id}")

    # -- Cache purge --------------------------------------------------------

    async def purge_everything(self, zone_id: str) -> dict[str, Any]:
        return await self._request(
            "POST", f"/zones/{zone_id}/purge_cache", json_body={"purge_everything": True}
        )

    async def purge_scoped(self, *, zone_id: str, key: str, targets: list[str]) -> dict[str, Any]:
        # Design doc note: the tech design names a separate `invalidate_cache`
        # endpoint for scoped purges. Cloudflare's real v4 API has no such
        # endpoint -- `purge_cache` is the single endpoint for every purge
        # mode, distinguished only by the request body key
        # (`purge_everything` / `files` / `tags` / `hosts`). Corrected here;
        # see docs/tickets/PRD-21323.md Self-test for the note. This does not
        # change the MCP tool surface (params/returns are unaffected).
        return await self._request(
            "POST", f"/zones/{zone_id}/purge_cache", json_body={key: targets}
        )


def _first_message(errors: list[dict[str, Any]]) -> str | None:
    if not errors:
        return None
    message = errors[0].get("message")
    return str(message) if message is not None else None
