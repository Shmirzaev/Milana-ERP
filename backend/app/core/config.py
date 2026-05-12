from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "Milana ERP"
    DEBUG: bool = True
    DATABASE_URL: str = "postgresql+psycopg2://erp:erp@db:5432/erp"
    JWT_SECRET: str = "dev-secret"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRES_MINUTES: int = 1440
    CORS_ORIGINS: str = "http://localhost:3000"
    BARCODE_STORAGE_DIR: str = "/app/storage/barcodes"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()
