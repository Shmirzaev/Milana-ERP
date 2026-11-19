"""Offline lifecycle checks; no PostgreSQL engine or socket is created."""
import sys

import pytest

from app.tests import pg_approved_instance as guard
from app.tests import test_forecast_review_postgres as review


def test_optional_missing_config_skips_and_required_or_invalid_config_fails(monkeypatch):
    monkeypatch.delenv(guard.CONFIG_ENV, raising=False)
    monkeypatch.delenv(guard.REQUIRE_ENV, raising=False)
    with pytest.raises(guard.ApprovedInstanceUnavailable) as absent:
        guard.load_approved_instance()
    with pytest.raises(pytest.skip.Exception, match="BLOCKED"):
        guard.require_or_skip(absent.value)
    monkeypatch.setenv(guard.REQUIRE_ENV, "1")
    with pytest.raises(pytest.fail.Exception, match="BLOCKED"):
        guard.require_or_skip(absent.value)
    monkeypatch.delenv(guard.REQUIRE_ENV)
    monkeypatch.setenv(guard.CONFIG_ENV, "invalid json")
    with pytest.raises(guard.ApprovedInstanceUnavailable) as invalid:
        guard.load_approved_instance()
    with pytest.raises(pytest.fail.Exception, match="BLOCKED"):
        guard.require_or_skip(invalid.value)


@pytest.mark.parametrize("failure", ["create", "engine", "schema", "none"])
def test_fixture_finalizes_only_an_owned_target(monkeypatch, failure):
    calls = []
    instance, target = object(), object()

    class Engine:
        def dispose(self):
            calls.append("dispose")

    engine = Engine()
    monkeypatch.setattr(guard, "load_approved_instance", lambda: instance)

    def create(value):
        assert value is instance
        calls.append("create")
        if failure == "create":
            raise RuntimeError("create failed")
        return target

    def make_engine(value, *, options):
        assert value is target
        assert "statement_timeout=15000" in options and "lock_timeout=8000" in options
        calls.append("engine")
        if failure == "engine":
            raise RuntimeError("engine failed")
        return engine

    def create_all(value):
        assert value is engine
        calls.append("schema")
        if failure == "schema":
            raise RuntimeError("schema failed")

    def finalize(value, supplied_engine):
        assert value is target
        assert supplied_engine is (None if failure == "engine" else engine)
        active = sys.exception()
        if failure in ("engine", "schema"):
            assert isinstance(active, RuntimeError) and str(active) == f"{failure} failed"
        calls.append("finalize")

    monkeypatch.setattr(guard, "create_target_database", create)
    monkeypatch.setattr(guard, "target_engine", make_engine)
    monkeypatch.setattr(guard, "finalize_target", finalize)
    monkeypatch.setattr(review.Base.metadata, "create_all", create_all)
    generator = review.sessions.__wrapped__()
    if failure != "none":
        with pytest.raises(RuntimeError, match=f"{failure} failed"):
            next(generator)
    else:
        got_engine, _ = next(generator)
        assert got_engine is engine
        generator.close()
    expected = {
        "create": ["create"],
        "engine": ["create", "engine", "finalize"],
        "schema": ["create", "engine", "schema", "finalize"],
        "none": ["create", "engine", "schema", "finalize"],
    }
    assert calls == expected[failure]


def test_setup_failure_is_preserved_when_finalizer_fails(monkeypatch):
    target = object()
    calls = []
    engine = object()
    def finalize(value, supplied_engine):
        assert value is target
        assert supplied_engine is engine
        assert str(sys.exception()) == "schema failed"
        calls.append("finalize")
        raise RuntimeError("finalizer failed")
    def schema(*args):
        raise RuntimeError("schema failed")
    monkeypatch.setattr(guard, "load_approved_instance", lambda: object())
    monkeypatch.setattr(guard, "create_target_database", lambda instance: target)
    monkeypatch.setattr(guard, "target_engine", lambda *args, **kwargs: engine)
    monkeypatch.setattr(guard, "finalize_target", finalize)
    monkeypatch.setattr(review.Base.metadata, "create_all", schema)
    with pytest.raises(RuntimeError, match="finalizer failed") as error:
        next(review.sessions.__wrapped__())
    assert isinstance(error.value.__context__, RuntimeError)
    assert str(error.value.__context__) == "schema failed"
    assert calls == ["finalize"]


def test_identity_mismatch_does_not_skip_or_mutate(monkeypatch):
    calls = []
    monkeypatch.setenv(guard.REQUIRE_ENV, "1")
    monkeypatch.setattr(guard, "load_approved_instance", lambda: object())
    def reject(instance):
        calls.append("preflight")
        raise guard.ApprovedInstanceUnavailable("identity mismatch")
    monkeypatch.setattr(guard, "create_target_database", reject)
    monkeypatch.setattr(guard, "target_engine", lambda *args, **kwargs: calls.append("engine"))
    monkeypatch.setattr(guard, "finalize_target", lambda *args, **kwargs: calls.append("cleanup"))
    with pytest.raises(guard.ApprovedInstanceUnavailable, match="identity mismatch"):
        next(review.sessions.__wrapped__())
    assert calls == ["preflight"]
