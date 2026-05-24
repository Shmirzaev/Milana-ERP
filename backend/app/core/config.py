from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "Milana ERP"
    DEBUG: bool = True
    DATABASE_URL: str = "postgresql+psycopg2://erp:erp@db:5432/erp"
    JWT_SECRET: str = "dev-secret"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRES_MINUTES: int = 1440
    INITIAL_ADMIN_EMAIL: str = "admin@example.com"
    INITIAL_ADMIN_PASSWORD: str = ""
    SEED_DEMO_USERS: bool = False
    PASSWORD_MIN_LENGTH: int = 12
    AUTH_MAX_FAILED_ATTEMPTS: int = 5
    AUTH_WINDOW_SECONDS: int = 15 * 60
    AUTH_LOCKOUT_SECONDS: int = 15 * 60
    ALLOW_INSECURE_DEFAULT_ADMIN_LOGIN: bool = False
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


settings = Settings()
