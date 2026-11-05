# cloudflare-mcp

MCP server that gives an AI agent access to a Cloudflare account: list zones,
manage DNS records, and purge zone cache. Built for the MSPbots Agent
platform.

- **Transport**: MCP Streamable HTTP (`POST /mcp`), stateless, no server-side
  session state.
- **Tech stack**: Python 3.12, [FastMCP](https://gofastmcp.com), `httpx`.
- **Credentials**: never stored. Every request carries its own Cloudflare API
  Token in an HTTP header (see below); this service never writes a token to
  disk, a log, or an environment variable.
- **License**: Apache-2.0. Copyright MSPbots.ai.

<div align="center">

## MSPbots Connector

**The MCP Gateway built for MSPs: visible, controlled, and your data stays where it belongs.**

[**Get started at connect.mspbots.ai →**](https://connect.mspbots.ai)

</div>

---

MSPbots Connector gives your AI clients one MCP URL to reach your entire MSP stack (RMM, PSA, documentation, security, finance), and gives you control over who can call which tool and a record of everything that was called.

**Hosted service: [connect.mspbots.ai](https://connect.mspbots.ai)** · Free to use.

### Why Connector

![MSPbots Connector](https://stgoss.mspbots.ai/files/mcp/mspbots-mcp.png)

| | |
|---|---|
| **Visible** | Every tool call is logged: who, which vendor, when. Usage dashboard, CSV export, SIEM streaming. |
| **Controlled** | Role-based, per-tool allowlist. Deny by default. |
| **Protected** | Credentials encrypted per record. AI clients never see your vendor passwords or tokens. |
| **MSP-native** | Built for the MSP stack only: RMM, PSA, documentation, security, finance. |

### Quick start

1. **Sign up** at [connect.mspbots.ai](https://connect.mspbots.ai).
2. **Connect your vendors.** Pick from 150+ connectors and authorize each one on the vendor's own page, or bring your own API keys. No extra vendor accounts needed.
3. **Set access.** Create roles and decide which tools each role may call. Nothing is allowed until you allow it.
4. **Add your MCP URL to your AI client.** Copy the URL from your Connector dashboard into Claude, ChatGPT, Cursor, VS Code, Gemini, Codex, or any MCP-capable client.
5. **Ask your AI to do real work**, and watch every call appear in the audit log.

### Features

**Unified gateway**
- One MCP URL for all your AI clients
- 150+ connectors across the MSP stack
- Custom MCP servers supported, free
- Authorization happens on each vendor's own page; the AI never sees passwords or tokens
- Bring your own credentials: use the vendor API keys you already have
- Multiple accounts per app; connect once, reuse across AI clients
- Tool search: finds the right action for the task
- One sign-in; vendor credentials are injected behind the scenes and OAuth tokens refresh automatically

**Visibility**
- Audit log for every tool call (who, which vendor, when)
- Usage dashboard: call volume, top vendors, error rate, per-user activity
- Export audit logs to CSV, or stream to Loki, Graylog, or LogScale (SIEM)
- Optional recording of tool arguments and result summaries (off by default, enabled per organization)

**Control**
- Per-role, per-tool allowlist, deny by default
- owner / admin / member roles
- SCIM provisioning with Entra ID, Okta, JumpCloud, and Google Workspace

**Security**
- Credentials encrypted one record at a time (AES-256-GCM, per-record key)
- AI clients authenticate with OAuth 2.1 + PKCE
- Vendor responses are scanned for prompt-injection patterns and returned as structured data. This is one layer of defense, not a guarantee against every attack.
- Static egress IP for customer firewall and API allowlisting

### Pricing

**Free.**

Links: [connect.mspbots.ai](https://connect.mspbots.ai) · [mspbots.ai](https://mspbots.ai)

---

## Authentication headers

Every `/mcp` request must carry the caller's own Cloudflare credential in this
header. There is no environment-variable fallback: a request without it is
rejected with 401 before any Cloudflare API call is made.

| Header | Required | Meaning | Where to get it |
|---|---|---|---|
| `X-Cloudflare-Api-Token` | Yes | A Cloudflare API Token (not the legacy Global API Key) scoped to the zones this connector should manage | Cloudflare dashboard → **My Profile** → **API Tokens** → **Create Token**. Grant it `Zone.DNS` (Edit) and `Zone.Cache Purge` (Purge) permissions, scoped to the zone(s) you want this connector to reach. |

The token's own Cloudflare-side scope is this connector's entire authorization
boundary: it does not add or remove permissions beyond what the token already
grants.

## Tools

| Tool | What it does |
|---|---|
| `cloudflare_list_zones` | List the zones (domains) reachable by the supplied token, paginated. |
| `cloudflare_get_zone` | Get one zone's details by id. |
| `cloudflare_list_dns_records` | List DNS records in a zone, optionally filtered by type/name. |
| `cloudflare_create_dns_record` | Create a DNS record. |
| `cloudflare_update_dns_record` | Partially update a DNS record (only the given fields change). |
| `cloudflare_delete_dns_record` | Delete a DNS record by id. |
| `cloudflare_purge_cache` | Purge a zone's cache, entirely or scoped to files/tags/hosts. |

Scope for this first version: zone listing, DNS record management, and cache
purge. Zone lifecycle (create/delete a zone), WAF/firewall rules, Workers,
Load Balancers, Access/Zero Trust, and account/member management are out of
scope -- see `docs/tickets/PRD-21323.md` for the full product design and the
reasoning behind what is and isn't included.

## Error format

Every tool returns a JSON string. On failure it is a structured envelope
instead of a raised exception:

```json
{"error": {"code": "not_found", "message": "...", "retryable": false}}
```

`code` is one of a fixed vocabulary: `not_configured`, `unauthorized`,
`not_found`, `invalid_argument`, `rate_limited`, `upstream_error`.
`retryable` tells the caller whether retrying the same call might succeed.

## Local development

Requires Python 3.12 and [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync
uv run pytest
```

Run the server locally:

```bash
uv run python -m cloudflare_mcp
# Streamable HTTP endpoint: POST http://localhost:8080/mcp
# Health probe:             GET  http://localhost:8080/health
```

Exercise it with a real (or scoped-down test) Cloudflare API Token:

```bash
curl -s http://localhost:8080/health

curl -s -X POST http://localhost:8080/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'X-Cloudflare-Api-Token: <your token>' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Build the container image (the MSPbots runtime is `linux/amd64`):

```bash
docker build --platform linux/amd64 -t cloudflare-mcp:dev .
```
