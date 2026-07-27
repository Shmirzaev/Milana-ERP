from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    erp_api_base_url: str = Field(default="http://localhost:8000", alias="ERP_API_BASE_URL")
    auth_mode: Literal["bearer"] = Field(default="bearer", alias="ERP_MCP_AUTH_MODE")
    bearer_token: SecretStr | None = Field(default=None, alias="ERP_MCP_BEARER_TOKEN")
    require_confirmation: bool = Field(default=True, alias="ERP_MCP_REQUIRE_CONFIRMATION")
    max_bulk_recipients: int = Field(default=25, ge=1, le=250, alias="ERP_MCP_MAX_BULK_RECIPIENTS")
    http_timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0, alias="ERP_MCP_HTTP_TIMEOUT_SECONDS")
    notification_send_path: str = Field(default="/api/notifications/send", alias="ERP_MCP_NOTIFICATION_SEND_PATH")

    @field_validator("erp_api_base_url")
    @classmethod
    def normalize_base_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if not normalized:
            raise ValueError("ERP_API_BASE_URL cannot be empty")
        return normalized

    @field_validator("notification_send_path")
    @classmethod
    def normalize_api_path(cls, value: str) -> str:
        path = value.strip()
        if not path.startswith("/"):
            path = f"/{path}"
        return path

    @property
    def bearer_token_value(self) -> str | None:
        if self.bearer_token is None:
            return None
        token = self.bearer_token.get_secret_value().strip()
        return token or None


@lru_cache
def get_settings() -> Settings:
    return Settings()
