from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, read from environment variables or `.env`."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    keitaro_url: str = Field(default="https://tlgk.host", description="Keitaro base URL")
    keitaro_api_key: SecretStr = SecretStr("")
    keitaro_timeout: float = 20.0

    database_url: str = "sqlite+aiosqlite:///./keitaro_wrapper.db"

    # Every campaign created by this tool gets this prefix (task requirement).
    campaign_prefix: str = "test_mkrtchyan_"

    # Defaults preselected in the campaign creator, matched by name in Keitaro.
    default_domain: str = "in.posdk.xyz"
    default_group: str = "FORTESTS"
    default_traffic_source: str = "FORTESTS"

    geo_redirect_url: str = "https://google.com"

    # Sign-in (see app/auth.py). Everything empty = open app, everyone publishes.
    # Single Basic-auth user (a publisher):
    app_username: str = "admin"
    app_password: SecretStr = SecretStr("")
    # Several users with roles: "alice:pass:publisher,bob:pass:editor"
    app_users: str = ""
    # SSO through a trusted reverse proxy (e.g. oauth2-proxy) that sets this header.
    # Only enable it when the app is reachable exclusively through that proxy.
    trusted_user_header: str = ""
    # SSO users (comma-separated, case-insensitive) who may publish; others are editors.
    sso_publishers: str = ""

    # Observability
    log_format: Literal["text", "json"] = "text"
    log_level: str = "INFO"
    sentry_dsn: SecretStr = SecretStr("")
    environment: str = "development"

    # Re-fetch known campaigns from Keitaro every N seconds (0 = off).
    auto_sync_interval: float = 300.0

    # Timezone used for daily stats (Keitaro reports are bucketed by day in it).
    stats_timezone: str = "Europe/Moscow"

    # How long the Keitaro offer list is cached for autocomplete, seconds.
    offers_cache_ttl: float = 60.0

    @property
    def keitaro_api_url(self) -> str:
        return f"{self.keitaro_url.rstrip('/')}/admin_api/v1"

    @property
    def keitaro_admin_url(self) -> str:
        return f"{self.keitaro_url.rstrip('/')}/admin"


@lru_cache
def get_settings() -> Settings:
    return Settings()
