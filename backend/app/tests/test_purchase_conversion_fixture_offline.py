"""Offline fixture lifecycle checks; never creates a PostgreSQL engine."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url

from app.tests import test_purchase_conversion_postgres as subject


@pytest.mark.parametrize("failure", [None, "engine", "migration"])
def test_conversion_fixture_guarded_migration_and_finalization(monkeypatch, failure):
    calls = []
    target = object()
    engine = SimpleNamespace(url=make_url("postgresql+psycopg2://u:p%25x@127.0.0.1:5432/owned"))
    monkeypatch.setattr(subject, "load_approved_instance", lambda: calls.append("load") or object())
    monkeypatch.setattr(subject, "create_target_database", lambda instance: calls.append("create") or target)
    def make_engine(owned, *, options):
        assert owned is target
        assert "statement_timeout" in options and "lock_timeout" in options
        calls.append("guarded_engine")
        if failure == "engine":
            raise RuntimeError("engine failure")
        return engine
    monkeypatch.setattr(subject, "target_engine", make_engine)
    def upgrade(config, revision):
        calls.append("migrate")
        assert revision == "head"
        assert sa.engine_from_config({}) is engine
        assert "%%" in subject.settings.DATABASE_URL
        if failure == "migration":
            raise RuntimeError("migration failure")
    monkeypatch.setattr(subject.command, "upgrade", upgrade)
    sessions = Mock()
    monkeypatch.setattr(subject, "Sessions", sessions)
    monkeypatch.setattr(subject, "finalize_target",
                        lambda owned, actual: calls.append(("finalize", owned, actual)))
    fixture = subject.conversion_pg_engine.__wrapped__()
    if failure:
        with pytest.raises(RuntimeError, match=failure):
            next(fixture)
    else:
        assert next(fixture) is engine
        with pytest.raises(StopIteration):
            next(fixture)
        sessions.configure.assert_any_call(bind=engine)
    assert calls[:2] == ["load", "create"]
    assert calls[2] == "guarded_engine"
    if failure != "engine":
        assert calls[3] == "migrate"
    assert calls[-1] == ("finalize", target, None if failure == "engine" else engine)
    sessions.configure.assert_any_call(bind=None)
