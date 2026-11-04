"""Non-credential runtime configuration.

Credentials are never read here -- they only ever come from a per-request
HTTP header (see middleware.py). This module must tolerate unknown
environment variables, since the runtime environment injects variables this
project does not declare.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    mcp_http_host: str = "0.0.0.0"
    mcp_http_port: int = 8080

    # Cloudflare's own API base URL. Overridable for testing only; MSPbots
    # never points this at anything other than the real Cloudflare API in
    # production.
    cloudflare_base_url: str = "https://api.cloudflare.com/client/v4"


settings = Settings()
