import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import QueuePool

from app.core.config import Settings
from app.db.session import _engine_options


def test_pool_settings_are_applied_only_to_postgres():
    assert _engine_options("postgresql://user:pass@localhost/db", 8, 4) == {
        "pool_pre_ping": True, "future": True, "pool_size": 8, "max_overflow": 4,
    }
    assert _engine_options("postgresql://user:pass@localhost/db", None, None) == {
        "pool_pre_ping": True, "future": True,
    }
def test_settings_read_explicit_environment_values(monkeypatch):
    monkeypatch.setenv("DB_POOL_SIZE", "8")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "4")
    settings = Settings(_env_file=None)
    assert settings.DB_POOL_SIZE == 8
    assert settings.DB_MAX_OVERFLOW == 4


def test_unset_pool_settings_preserve_sqlalchemy_defaults(monkeypatch):
    monkeypatch.delenv("DB_POOL_SIZE", raising=False)
    monkeypatch.delenv("DB_MAX_OVERFLOW", raising=False)
    settings = Settings(_env_file=None)
    assert settings.DB_POOL_SIZE is None
    assert settings.DB_MAX_OVERFLOW is None

    engine = create_engine("postgresql+psycopg2://user:pass@localhost/db", **_engine_options(
        "postgresql+psycopg2://user:pass@localhost/db", settings.DB_POOL_SIZE, settings.DB_MAX_OVERFLOW,
    ))
    try:
        assert isinstance(engine.pool, QueuePool)
        assert engine.pool.size() == 5
        assert engine.pool._max_overflow == 10
    finally:
        engine.dispose()


def test_configured_postgres_pool_limits_without_connecting():
    url = "postgresql+psycopg2://user:pass@localhost/db"
    engine = create_engine(url, **_engine_options(url, 8, 4))
    try:
        assert isinstance(engine.pool, QueuePool)
        assert engine.pool.size() == 8
        assert engine.pool._max_overflow == 4
    finally:
        engine.dispose()


def test_configured_zero_postgres_overflow_without_connecting():
    url = "postgresql+psycopg2://user:pass@localhost/db"
    engine = create_engine(url, **_engine_options(url, 8, 0))
    try:
        assert engine.pool.size() == 8
        assert engine.pool._max_overflow == 0
    finally:
        engine.dispose()


def test_sqlite_does_not_receive_postgres_pool_options():
    options = _engine_options("sqlite://", 8, 4)
    assert options == {"pool_pre_ping": True, "future": True}
    engine = create_engine("sqlite://", **options)
    try:
        with engine.connect() as connection:
            assert connection.closed is False
        assert not isinstance(engine.pool, QueuePool)
    finally:
        engine.dispose()


@pytest.mark.parametrize(("field", "value"), [("DB_POOL_SIZE", 0), ("DB_POOL_SIZE", -1), ("DB_MAX_OVERFLOW", -1)])
def test_pool_settings_require_safe_values(field, value):
    with pytest.raises(ValueError, match="must be"):
        Settings(**{field: value})
