"""tools/list snapshot (Section 13: a signature change should show up here as
a diff) plus one test per AC1, AC3-AC10 against a mocked Cloudflare API."""

from __future__ import annotations

import httpx
import pytest
import respx

from cloudflare_mcp.settings import settings
from tests.conftest import call_tool

BASE = settings.cloudflare_base_url


def cf_envelope(result, *, result_info=None):
    body = {"success": True, "errors": [], "messages": [], "result": result}
    if result_info is not None:
        body["result_info"] = result_info
    return body


def cf_error(code: int, message: str):
    return {"success": False, "errors": [{"code": code, "message": message}], "messages": [], "result": None}


# ---------------------------------------------------------------------------
# tools/list snapshot (Section 13)
# ---------------------------------------------------------------------------


async def test_tools_list_snapshot(mcp):
    tools = await mcp.get_tools()
    assert set(tools.keys()) == {
        "cloudflare_list_zones",
        "cloudflare_get_zone",
        "cloudflare_list_dns_records",
        "cloudflare_create_dns_record",
        "cloudflare_update_dns_record",
        "cloudflare_delete_dns_record",
        "cloudflare_purge_cache",
    }

    required_by_tool = {
        name: set(tool.parameters.get("required", [])) for name, tool in tools.items()
    }
    assert required_by_tool == {
        "cloudflare_list_zones": set(),
        "cloudflare_get_zone": {"zone_id"},
        "cloudflare_list_dns_records": {"zone_id"},
        "cloudflare_create_dns_record": {"zone_id", "type", "name", "content"},
        "cloudflare_update_dns_record": {"zone_id", "record_id"},
        "cloudflare_delete_dns_record": {"zone_id", "record_id"},
        "cloudflare_purge_cache": {"zone_id", "mode"},
    }


# ---------------------------------------------------------------------------
# AC1 / TC1
# ---------------------------------------------------------------------------


@respx.mock
async def test_list_zones_returns_paginated_zones_for_token(mcp):
    respx.get(f"{BASE}/zones").mock(
        return_value=httpx.Response(
            200,
            json=cf_envelope(
                [{"id": "z1", "name": "example.com", "status": "active", "plan": {"name": "Free"}}],
                result_info={"page": 1, "per_page": 50, "total_pages": 2, "count": 1, "total_count": 51},
            ),
        )
    )
    out = await call_tool(mcp, "cloudflare_list_zones", {})
    assert out == {
        "zones": [{"id": "z1", "name": "example.com", "status": "active", "plan": "Free"}],
        "page": 1,
        "has_more": True,
    }


# ---------------------------------------------------------------------------
# AC3 / TC3
# ---------------------------------------------------------------------------


@respx.mock
async def test_list_dns_records_filters_by_type_and_name(mcp):
    route = respx.get(f"{BASE}/zones/z1/dns_records").mock(
        return_value=httpx.Response(
            200,
            json=cf_envelope(
                [{"id": "r1", "type": "A", "name": "www.example.com", "content": "1.2.3.4", "ttl": 300, "proxied": True}],
                result_info={"page": 1, "per_page": 50, "total_pages": 1, "count": 1, "total_count": 1},
            ),
        )
    )
    out = await call_tool(
        mcp, "cloudflare_list_dns_records", {"zone_id": "z1", "type": "A", "name": "www.example.com"}
    )
    assert out["records"] == [
        {"id": "r1", "type": "A", "name": "www.example.com", "content": "1.2.3.4", "ttl": 300, "proxied": True}
    ]
    assert out["has_more"] is False
    assert route.calls.last.request.url.params["type"] == "A"
    assert route.calls.last.request.url.params["name"] == "www.example.com"


# ---------------------------------------------------------------------------
# AC4 / TC4
# ---------------------------------------------------------------------------


@respx.mock
async def test_create_dns_record_returns_created_record_with_id(mcp):
    respx.post(f"{BASE}/zones/z1/dns_records").mock(
        return_value=httpx.Response(
            200,
            json=cf_envelope(
                {"id": "new-id", "type": "TXT", "name": "_verify.example.com", "content": "abc", "ttl": 1, "proxied": False}
            ),
        )
    )
    out = await call_tool(
        mcp,
        "cloudflare_create_dns_record",
        {"zone_id": "z1", "type": "TXT", "name": "_verify.example.com", "content": "abc"},
    )
    assert out["id"] == "new-id"
    assert out["type"] == "TXT"


# ---------------------------------------------------------------------------
# AC5 / TC5
# ---------------------------------------------------------------------------


@respx.mock
async def test_update_dns_record_preserves_unspecified_fields(mcp):
    route = respx.patch(f"{BASE}/zones/z1/dns_records/r1").mock(
        return_value=httpx.Response(
            200,
            json=cf_envelope({"id": "r1", "type": "A", "name": "www.example.com", "content": "1.2.3.4", "ttl": 60, "proxied": True}),
        )
    )
    out = await call_tool(mcp, "cloudflare_update_dns_record", {"zone_id": "z1", "record_id": "r1", "ttl": 60})

    # Only `ttl` was given; the request body must carry only that field --
    # not a full re-send of name/content/proxied -- so Cloudflare's own
    # partial-update semantics (PATCH) are actually exercised, not papered
    # over by a read-then-merge-then-write in this service.
    sent_body = respx.calls.last.request.content
    import json as _json

    assert _json.loads(sent_body) == {"ttl": 60}
    assert out["ttl"] == 60
    assert out["content"] == "1.2.3.4"
    assert route.called


# ---------------------------------------------------------------------------
# AC6 / TC6
# ---------------------------------------------------------------------------


@respx.mock
async def test_delete_dns_record_sends_delete_and_returns_confirmation(mcp):
    route = respx.delete(f"{BASE}/zones/z1/dns_records/r1").mock(
        return_value=httpx.Response(200, json=cf_envelope({"id": "r1"}))
    )
    out = await call_tool(mcp, "cloudflare_delete_dns_record", {"zone_id": "z1", "record_id": "r1"})
    assert out == {"id": "r1", "deleted": True}
    assert route.called


# ---------------------------------------------------------------------------
# AC7 / TC7
# ---------------------------------------------------------------------------


@respx.mock
async def test_update_and_delete_missing_record_return_not_found(mcp):
    respx.patch(f"{BASE}/zones/z1/dns_records/missing").mock(
        return_value=httpx.Response(404, json=cf_error(81044, "Record does not exist"))
    )
    respx.delete(f"{BASE}/zones/z1/dns_records/missing").mock(
        return_value=httpx.Response(404, json=cf_error(81044, "Record does not exist"))
    )

    update_out = await call_tool(
        mcp, "cloudflare_update_dns_record", {"zone_id": "z1", "record_id": "missing", "ttl": 60}
    )
    delete_out = await call_tool(mcp, "cloudflare_delete_dns_record", {"zone_id": "z1", "record_id": "missing"})

    for out in (update_out, delete_out):
        assert out["error"]["code"] == "not_found"
        assert out["error"]["retryable"] is False


# ---------------------------------------------------------------------------
# AC8 / TC8
# ---------------------------------------------------------------------------


@respx.mock
async def test_purge_cache_everything_calls_purge_cache_endpoint(mcp):
    route = respx.post(f"{BASE}/zones/z1/purge_cache").mock(
        return_value=httpx.Response(200, json=cf_envelope({"id": "z1"}))
    )
    out = await call_tool(mcp, "cloudflare_purge_cache", {"zone_id": "z1", "mode": "everything"})
    assert out == {"purged": True, "mode": "everything"}
    import json as _json

    assert _json.loads(route.calls.last.request.content) == {"purge_everything": True}


# ---------------------------------------------------------------------------
# AC9 / TC9
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.parametrize(
    ("mode", "targets", "body_key"),
    [
        ("files", ["https://example.com/a.css"], "files"),
        ("tags", ["tag-a"], "tags"),
        ("hosts", ["www.example.com"], "hosts"),
    ],
)
async def test_purge_cache_files_tags_hosts_sends_targeted_request(mcp, mode, targets, body_key):
    route = respx.post(f"{BASE}/zones/z1/purge_cache").mock(
        return_value=httpx.Response(200, json=cf_envelope({"id": "z1"}))
    )
    out = await call_tool(mcp, "cloudflare_purge_cache", {"zone_id": "z1", "mode": mode, "targets": targets})
    assert out == {"purged": True, "mode": mode}
    import json as _json

    sent = _json.loads(route.calls.last.request.content)
    assert sent == {body_key: targets}
    assert "purge_everything" not in sent


async def test_purge_cache_scoped_mode_without_targets_is_invalid_argument(mcp):
    out = await call_tool(mcp, "cloudflare_purge_cache", {"zone_id": "z1", "mode": "files"})
    assert out["error"]["code"] == "invalid_argument"


# ---------------------------------------------------------------------------
# AC10 / TC10
# ---------------------------------------------------------------------------


@respx.mock
async def test_upstream_429_and_5xx_return_structured_errors_not_exceptions(mcp):
    respx.get(f"{BASE}/zones/z1/dns_records").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "1"}, json=cf_error(10000, "Rate limited"))
    )
    rate_limited = await call_tool(mcp, "cloudflare_list_dns_records", {"zone_id": "z1"})
    assert rate_limited["error"]["code"] == "rate_limited"
    assert rate_limited["error"]["retryable"] is True

    respx.get(f"{BASE}/zones/z2/dns_records").mock(
        return_value=httpx.Response(502, json=cf_error(10001, "Bad gateway"))
    )
    upstream = await call_tool(mcp, "cloudflare_list_dns_records", {"zone_id": "z2"})
    assert upstream["error"]["code"] == "upstream_error"
    assert upstream["error"]["retryable"] is True


@respx.mock
async def test_upstream_401_maps_to_unauthorized_not_a_crash(mcp):
    respx.get(f"{BASE}/zones").mock(
        return_value=httpx.Response(403, json=cf_error(9109, "Invalid API Token"))
    )
    out = await call_tool(mcp, "cloudflare_list_zones", {})
    assert out["error"]["code"] == "unauthorized"
    assert out["error"]["retryable"] is False
