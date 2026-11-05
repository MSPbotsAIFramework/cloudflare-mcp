"""Per-request credential isolation.

The Cloudflare API token travels only in the `X-Cloudflare-Api-Token` header
of each incoming request. It is read into a `contextvars.ContextVar` for the
lifetime of that request only, and reset in a `finally` block so it can never
leak into a concurrent request handled by the same process (Section 3.3).

There is no environment-variable fallback: a request without the header is
rejected with 401 before it reaches any tool.
"""

from __future__ import annotations

import contextvars
import json

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .errors import error_envelope

CREDENTIAL_HEADER = "X-Cloudflare-Api-Token"

_token_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "cloudflare_api_token", default=None
)


def current_token() -> str | None:
    """The Cloudflare API token for the request currently being handled, or
    None if called outside a request scope."""
    return _token_var.get()


class CredentialMiddleware(BaseHTTPMiddleware):
    """Reads the Cloudflare credential header for `/mcp` requests, rejects
    requests missing it with 401, and guarantees the token never outlives the
    request it was read from."""

    def __init__(self, app, protected_path: str = "/mcp"):
        super().__init__(app)
        self._protected_path = protected_path

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if not request.url.path.startswith(self._protected_path):
            return await call_next(request)

        token = request.headers.get(CREDENTIAL_HEADER)
        if not token:
            body = json.loads(
                error_envelope(
                    "unauthorized", f"Missing required header: {CREDENTIAL_HEADER}"
                )
            )
            body["required_headers"] = [CREDENTIAL_HEADER]
            return JSONResponse(body, status_code=401)

        reset_token = _token_var.set(token)
        try:
            return await call_next(request)
        finally:
            _token_var.reset(reset_token)
