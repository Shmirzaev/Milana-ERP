from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "Milana ERP"
    ENV: str = "development"
    DEBUG: bool = True
    DATABASE_URL: str = "postgresql+psycopg2://erp:erp@db:5432/erp"
    JWT_SECRET: str = "dev-secret"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRES_MINUTES: int = 480
    INITIAL_ADMIN_EMAIL: str = "admin@example.com"
    INITIAL_ADMIN_PASSWORD: str = ""
    SEED_DEMO_USERS: bool = False
    PASSWORD_MIN_LENGTH: int = 12
    AUTH_MAX_FAILED_ATTEMPTS: int = 5
    AUTH_WINDOW_SECONDS: int = 15 * 60
    AUTH_LOCKOUT_SECONDS: int = 15 * 60
    ALLOW_INSECURE_DEFAULT_ADMIN_LOGIN: bool = False
    ALLOW_DEMO_RESET: bool = False
    FRONTEND_BASE_URL: str = "https://milana-erp-web.vercel.app"
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

    def validate_runtime_security(self) -> None:
        if not self.is_production:
            return
        errors: list[str] = []
        if self.DEBUG:
            errors.append("DEBUG must be false")
        if self.JWT_SECRET.strip() in {"", "dev-secret", "test-secret"} or len(self.JWT_SECRET.strip()) < 32:
            errors.append("JWT_SECRET must be a unique high-entropy value")
        if "://erp:erp@" in self.DATABASE_URL:
            errors.append("DATABASE_URL must not use default development credentials")
        if "*" in self.cors_origins_list:
            errors.append("CORS_ORIGINS must list explicit trusted origins")
        if self.ALLOW_INSECURE_DEFAULT_ADMIN_LOGIN:
            errors.append("ALLOW_INSECURE_DEFAULT_ADMIN_LOGIN must be false")
        if self.ALLOW_DEMO_RESET:
            errors.append("ALLOW_DEMO_RESET must be false")
        if errors:
            raise RuntimeError("Unsafe production configuration: " + "; ".join(errors))


settings = Settings()
