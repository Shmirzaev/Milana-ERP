import asyncio
import os
from pathlib import Path
import subprocess
import sys
import textwrap
from types import SimpleNamespace

import pytest

from app.core import runtime_metadata


class Collector:
    def __init__(self, calls, *, enabled=True, frozen=0):
        self.calls = calls
        self.enabled = enabled
        self.frozen = frozen
        self.thresholds = (700, 10, 10)

    def isenabled(self):
        return self.enabled

    def get_freeze_count(self):
        return self.frozen

    def collect(self):
        self.calls.append("collect")

    def freeze(self):
        self.calls.append("freeze")
        self.frozen = 123

    def unfreeze(self):
        self.calls.append("unfreeze")
        self.frozen = 0


def test_strict_lifespan_prepares_after_startup_and_thaws(monkeypatch):
    from app import main

    calls = []
    collector = Collector(calls)
    monkeypatch.setattr(runtime_metadata, "gc", collector)
    monkeypatch.setattr(main, "_run_startup", lambda: calls.append("startup"))
    monkeypatch.setattr(main, "settings", SimpleNamespace(strict_security_required=True))
    app = SimpleNamespace(openapi=lambda: calls.append("metadata"))

    async def serve():
        async with main.lifespan(app):
            calls.append("serve")
            assert collector.frozen == 123

    asyncio.run(serve())
    assert calls == ["startup", "metadata", "collect", "freeze", "serve", "unfreeze"]
    assert collector.enabled and collector.thresholds == (700, 10, 10)


@pytest.mark.parametrize("enabled,gc_enabled,frozen", [(False, True, 0), (True, False, 0), (True, True, 456)])
def test_preserves_external_gc_ownership(monkeypatch, enabled, gc_enabled, frozen):
    calls = []
    collector = Collector(calls, enabled=gc_enabled, frozen=frozen)
    monkeypatch.setattr(runtime_metadata, "gc", collector)
    app = SimpleNamespace(openapi=lambda: calls.append("metadata"))

    with runtime_metadata.startup_metadata(app, enabled=enabled):
        calls.append("serve")

    assert calls == ["serve"]
    assert collector.enabled == gc_enabled and collector.frozen == frozen
    assert collector.thresholds == (700, 10, 10)


@pytest.mark.parametrize("error", [RuntimeError("serve failed"), asyncio.CancelledError()])
def test_thaws_on_error_or_cancellation(monkeypatch, error):
    calls = []
    collector = Collector(calls)
    monkeypatch.setattr(runtime_metadata, "gc", collector)
    app = SimpleNamespace(openapi=lambda: calls.append("metadata"))

    with pytest.raises(type(error)):
        with runtime_metadata.startup_metadata(app, enabled=True):
            raise error

    assert calls == ["metadata", "collect", "freeze", "unfreeze"]
    assert collector.frozen == 0 and collector.enabled


def test_metadata_failure_does_not_freeze(monkeypatch):
    calls = []
    collector = Collector(calls)
    monkeypatch.setattr(runtime_metadata, "gc", collector)

    def broken_schema():
        raise ValueError("invalid schema")

    with pytest.raises(ValueError, match="invalid schema"):
        with runtime_metadata.startup_metadata(SimpleNamespace(openapi=broken_schema), enabled=True):
            pytest.fail("must not serve")
    assert calls == [] and collector.frozen == 0


def test_nested_lifespan_does_not_thaw_outer_owner(monkeypatch):
    calls = []
    collector = Collector(calls)
    monkeypatch.setattr(runtime_metadata, "gc", collector)
    app = SimpleNamespace(openapi=lambda: calls.append("metadata"))
    with runtime_metadata.startup_metadata(app, enabled=True):
        with runtime_metadata.startup_metadata(app, enabled=True):
            assert collector.frozen == 123
        assert collector.frozen == 123
    assert calls == ["metadata", "collect", "freeze", "unfreeze"]


def test_real_gc_collects_new_cycles_and_releases_frozen_cycles_on_exit():
    # Isolate the process-global policy from pytest and its plugins.
    code = textwrap.dedent("""
        import gc
        import weakref
        from types import SimpleNamespace
        from app.core.runtime_metadata import startup_metadata

        class Cycle:
            pass

        thresholds = gc.get_threshold()
        persistent = Cycle()
        persistent.self = persistent
        held = weakref.ref(persistent)
        with startup_metadata(SimpleNamespace(openapi=lambda: {}), enabled=True):
            assert gc.isenabled() and gc.get_threshold() == thresholds
            assert gc.get_freeze_count() > 0
            del persistent
            refs = []
            for _ in range(600):
                item = Cycle()
                item.self = item
                refs.append(weakref.ref(item))
            del item
            for _ in range(250000):
                item = Cycle()
                item.self = item
            del item
            assert all(ref() is None for ref in refs)
            assert held() is not None
        assert gc.get_freeze_count() == 0
        assert gc.isenabled() and gc.get_threshold() == thresholds
        gc.collect()
        assert held() is None
    """)
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2]))
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_startup_failure_does_not_prepare_or_freeze(monkeypatch):
    from app import main

    calls = []
    monkeypatch.setattr(runtime_metadata, "gc", Collector(calls))

    def fail_startup():
        raise RuntimeError("schema verification failed")

    monkeypatch.setattr(main, "_run_startup", fail_startup)

    async def start():
        async with main.lifespan(SimpleNamespace(openapi=lambda: calls.append("metadata"))):
            pytest.fail("must not serve")

    with pytest.raises(RuntimeError, match="schema verification failed"):
        asyncio.run(start())
    assert calls == []


def test_metadata_warmup_keeps_schema_and_dependencies_unchanged(monkeypatch):
    from fastapi import APIRouter, Depends, FastAPI
    from fastapi.testclient import TestClient

    calls = []
    monkeypatch.setattr(runtime_metadata, "gc", Collector(calls))
    dependencies = []

    def actor():
        dependencies.append("actor")
        return "factory"

    router = APIRouter()

    @router.get("/record")
    def record(user=Depends(actor)):
        return {"user": user, "quantity": 7}

    nested = APIRouter()
    nested.include_router(router, prefix="/nested")
    app = FastAPI()
    app.include_router(nested, prefix="/api")
    assert app.openapi_schema is None
    with runtime_metadata.startup_metadata(app, enabled=True):
        schema = app.openapi_schema
        assert schema is not None and "/api/nested/record" in schema["paths"]
        assert dependencies == []
        with TestClient(app) as client:
            assert client.get("/api/nested/record").json() == {"user": "factory", "quantity": 7}
        assert app.openapi() is schema
    assert dependencies == ["actor"]
    assert calls == ["collect", "freeze", "unfreeze"]
