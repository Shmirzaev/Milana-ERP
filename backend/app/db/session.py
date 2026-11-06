from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker, Session

from app.core.config import settings

def _engine_options(database_url: str, pool_size: int | None, max_overflow: int | None) -> dict[str, object]:
    options: dict[str, object] = {"pool_pre_ping": True, "future": True}
    if make_url(database_url).get_backend_name() == "postgresql":
        if pool_size is not None:
            options["pool_size"] = pool_size
        if max_overflow is not None:
            options["max_overflow"] = max_overflow
    return options


engine = create_engine(
    settings.DATABASE_URL,
    **_engine_options(settings.DATABASE_URL, settings.DB_POOL_SIZE, settings.DB_MAX_OVERFLOW),
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
