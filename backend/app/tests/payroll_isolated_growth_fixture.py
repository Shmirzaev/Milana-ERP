"""Disposable database for payroll service tests; no application startup or seed."""
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.schemas  # noqa: F401 -- register all mapped tables
from app.db.base import Base
from app.schemas import Model


@pytest.fixture
def payroll_isolated_database():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with sessions() as db:
        db.add(Model(id=1, code="PAYROLL-TEST", name="Payroll test model"))
        db.commit()
    try:
        yield engine, sessions
    finally:
        engine.dispose()
