from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker, Session

from app.core.config import settings

def _engine_options(database_url: str, pool_size: int | None, max_overflow: int | None,
                    incident_read_only: bool = False) -> dict[str, object]:
    options: dict[str, object] = {"pool_pre_ping": True, "future": True}
    postgres = make_url(database_url).get_backend_name() == "postgresql"
    if incident_read_only and not postgres:
        raise RuntimeError("INCIDENT_READ_ONLY requires PostgreSQL transaction enforcement")
    if postgres:
        if pool_size is not None:
            options["pool_size"] = pool_size
        if max_overflow is not None:
            options["max_overflow"] = max_overflow
        if incident_read_only:
            options["connect_args"] = {"options": "-c default_transaction_read_only=on"}
    return options


def create_database_engine(database_url: str, pool_size: int | None = None,
                           max_overflow: int | None = None, *, incident_read_only: bool = False):
    database_engine = create_engine(database_url, **_engine_options(
        database_url, pool_size, max_overflow, incident_read_only))
    if incident_read_only:
        @event.listens_for(database_engine, "begin")
        def _read_only_transaction(connection):
            # Covers raw SQL/hidden GET writes as well as normal ORM sessions.
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
    return database_engine


engine = create_database_engine(settings.DATABASE_URL, settings.DB_POOL_SIZE,
    settings.DB_MAX_OVERFLOW, incident_read_only=settings.INCIDENT_READ_ONLY)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
