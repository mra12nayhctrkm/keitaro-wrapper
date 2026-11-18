from functools import lru_cache

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

    # Optional HTTP Basic auth for the whole app. Off when the password is empty.
    app_username: str = "admin"
    app_password: SecretStr = SecretStr("")

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
