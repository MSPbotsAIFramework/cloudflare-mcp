"""The structured error envelope every tool returns on failure.

Fixed, limited vocabulary (SOP Section 4.2) -- never invent new codes.
"""

from __future__ import annotations

import json
from typing import Literal

ErrorCode = Literal[
    "not_configured",
    "unauthorized",
    "not_found",
    "invalid_argument",
    "rate_limited",
    "upstream_error",
]

# Codes that are safe to retry (429 / 5xx / network-level failures).
RETRYABLE_CODES: frozenset[ErrorCode] = frozenset({"rate_limited", "upstream_error"})


class ToolError(Exception):
    """Raised inside a tool implementation, caught at the tool boundary and
    turned into the JSON error envelope. Never allowed to escape to the MCP
    protocol layer as an unhandled exception."""

    def __init__(self, code: ErrorCode, message: str):
        super().__init__(message)
        self.code: ErrorCode = code
        self.message = message


def error_envelope(code: ErrorCode, message: str) -> str:
    """Serialize the fixed error shape as a compact JSON string."""
    body = {
        "error": {
            "code": code,
            "message": message,
            "retryable": code in RETRYABLE_CODES,
        }
    }
    return json.dumps(body, separators=(",", ":"), ensure_ascii=False)


def error_envelope_from(exc: ToolError) -> str:
    return error_envelope(exc.code, exc.message)
