import os

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "Milana ERP"
    ENV: str = "development"
    DEBUG: bool = False
    DATABASE_URL: str = "postgresql+psycopg2://erp:erp@db:5432/erp"
    JWT_SECRET: str = "dev-secret"
    FILE_SIGNING_SECRET: str = ""
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRES_MINUTES: int = 480
    AUTH_COOKIE_NAME: str = "erp_access_token"
    INITIAL_ADMIN_EMAIL: str = "admin@example.com"
    INITIAL_ADMIN_PASSWORD: str = ""
    AI_MONITOR_EMAIL: str = "ai.monitor@erp.milanapremium.uz"
    AI_MONITOR_PASSWORD: str = ""
    SEED_DEMO_USERS: bool = False
    SEED_SAMPLE_DATA: bool = False
    IMPORT_LEGACY_MODELS: bool = False
    BACKFILL_EMPLOYEES_FROM_USERS: bool = False
    PASSWORD_MIN_LENGTH: int = 12
    AUTH_MAX_FAILED_ATTEMPTS: int = 5
    AUTH_WINDOW_SECONDS: int = 15 * 60
    AUTH_LOCKOUT_SECONDS: int = 15 * 60
    GLOBAL_RATE_LIMIT_ENABLED: bool = True
    GLOBAL_RATE_LIMIT_PER_MINUTE: int = 1200
    GLOBAL_RATE_LIMIT_WINDOW_SECONDS: int = 60
    SHARED_STORE_URL: str = ""
    REDIS_URL: str = ""
    SHARED_STORE_KEY_PREFIX: str = "milana-erp"
    ALLOW_INSECURE_DEFAULT_ADMIN_LOGIN: bool = False
    ALLOW_DEMO_RESET: bool = False
    FRONTEND_BASE_URL: str = "https://erp.milanapremium.uz"
    ERP_PUBLIC_BASE_URL: str = "https://erp.milanapremium.uz"
    PASSWORD_RESET_TOKEN_MINUTES: int = 60
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = ""
    SMTP_FROM_NAME: str = "Milana ERP"
    SMTP_USE_TLS: bool = True
    SMTP_USE_SSL: bool = False
    SMTP_TIMEOUT_SECONDS: int = 8
    RESEND_API_KEY: str = ""
    RESEND_FROM_EMAIL: str = ""
    CORS_ORIGINS: str = "http://localhost:3000"
    BARCODE_STORAGE_DIR: str = "/app/storage/barcodes"
    MODEL_FILES_DIR: str = "/app/storage/model_files"
    SALES_ORDER_FILES_DIR: str = "/app/storage/sales_order_files"
    INTEGRATION_1C_TOKEN: str = ""
    STARTUP_SCHEMA_SYNC: bool = False

    @field_validator("DEBUG", mode="before")
    @classmethod
    def parse_debug_bool(cls, value):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "t", "yes", "y", "on"}:
                return True
            if normalized in {"0", "false", "f", "no", "n", "off", "falce", "fasle", "flase"}:
                return False
        return value

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.ENV.strip().lower() in {"prod", "production", "staging"}

    @property
    def is_public_deployment(self) -> bool:
        """Detect hosted/public runtime even when ENV was left at development."""
        public_markers = (
            "SPACE_ID",
            "SPACE_HOST",
            "HF_SPACE_ID",
            "HF_SPACE_HOST",
            "RENDER",
            "RENDER_EXTERNAL_HOSTNAME",
            "VERCEL",
            "PUBLIC_DEPLOYMENT",
        )
        return any(str(os.environ.get(name, "")).strip() for name in public_markers)

    @property
    def strict_security_required(self) -> bool:
        return self.is_production or self.is_public_deployment

    @property
    def shared_store_url(self) -> str:
        return (self.SHARED_STORE_URL or self.REDIS_URL or "").strip()

    @property
    def active_file_signing_secret(self) -> str:
        # Development/test fallback preserves local ergonomics; production/public
        # deployments must set FILE_SIGNING_SECRET explicitly (validated below).
        return self.FILE_SIGNING_SECRET.strip() or self.JWT_SECRET.strip()

    def validate_runtime_security(self) -> None:
        if not self.strict_security_required:
            return
        errors: list[str] = []
        if self.DEBUG:
            errors.append("DEBUG must be false")
        jwt_secret = self.JWT_SECRET.strip()
        file_secret = self.FILE_SIGNING_SECRET.strip()
        if jwt_secret in {"", "dev-secret", "test-secret"} or len(jwt_secret) < 32:
            errors.append("JWT_SECRET must be a unique high-entropy value")
        if file_secret in {"", "dev-secret", "test-secret"} or len(file_secret) < 32:
            errors.append("FILE_SIGNING_SECRET must be a unique high-entropy value")
        if file_secret and file_secret == jwt_secret:
            errors.append("FILE_SIGNING_SECRET must be different from JWT_SECRET")
        if "://erp:erp@" in self.DATABASE_URL:
            errors.append("DATABASE_URL must not use default development credentials")
        if "*" in self.cors_origins_list:
            errors.append("CORS_ORIGINS must list explicit trusted origins")
        if self.GLOBAL_RATE_LIMIT_ENABLED and self.GLOBAL_RATE_LIMIT_PER_MINUTE <= 0:
            errors.append("GLOBAL_RATE_LIMIT_PER_MINUTE must be positive when global rate limiting is enabled")
        if self.GLOBAL_RATE_LIMIT_ENABLED and self.GLOBAL_RATE_LIMIT_WINDOW_SECONDS <= 0:
            errors.append("GLOBAL_RATE_LIMIT_WINDOW_SECONDS must be positive when global rate limiting is enabled")
        shared_store_required = (
            self.GLOBAL_RATE_LIMIT_ENABLED
            or self.AUTH_MAX_FAILED_ATTEMPTS > 0
            or self.AUTH_LOCKOUT_SECONDS > 0
        )
        if shared_store_required and not self.shared_store_url:
            errors.append("SHARED_STORE_URL or REDIS_URL must be configured for production/public rate limits and auth lockouts")
        if self.ALLOW_INSECURE_DEFAULT_ADMIN_LOGIN:
            errors.append("ALLOW_INSECURE_DEFAULT_ADMIN_LOGIN must be false")
        if self.ALLOW_DEMO_RESET:
            errors.append("ALLOW_DEMO_RESET must be false")
        if errors:
            raise RuntimeError("Unsafe production/public configuration: " + "; ".join(errors))


settings = Settings()
