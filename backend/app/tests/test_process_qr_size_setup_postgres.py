"""PostgreSQL qualification for initial process QR size setup."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.libs.dto.catalog.process_qr_sizes_input import ProcessQrSizesIn
from app.models.catalog import models_service
from app.schemas import AuditLog, ModelSize, User

pytest_plugins = ("app.tests.test_modelcolor_create_postgres",)


def _read(db, mid):
    sizes = db.scalars(select(ModelSize.size).where(ModelSize.model_id == mid).order_by(ModelSize.id)).all()
    audits = db.scalars(select(AuditLog).where(AuditLog.action == "process_qr_sizes_added", AuditLog.entity_id == mid)).all()
    return sizes, audits


def test_postgres_setup_audit_failure_rolls_back(pg_sessions, pg_case, monkeypatch):
    mid = pg_case["models"]["standard"]
    actor_id = pg_case["actors"]["standard"]
    def fail(*args, **kwargs):
        raise RuntimeError("injected audit failure")
    monkeypatch.setattr(models_service, "log_action", fail)
    with pg_sessions() as db:
        with pytest.raises(RuntimeError, match="injected audit failure"):
            models_service.add_process_qr_model_sizes(db.get(User, actor_id), db, mid, ProcessQrSizesIn(sizes=["48", "50"]))
        db.rollback()
    with pg_sessions() as db:
        assert _read(db, mid) == ([], [])


def test_postgres_simultaneous_setup_serializes(pg_sessions, pg_case):
    mid = pg_case["models"]["standard"]
    actor_id = pg_case["actors"]["standard"]
    barrier = Barrier(2, timeout=15)
    def setup(sizes):
        with pg_sessions() as db:
            actor = db.get(User, actor_id)
            barrier.wait()
            try:
                models_service.add_process_qr_model_sizes(actor, db, mid, ProcessQrSizesIn(sizes=sizes))
                return 201
            except HTTPException as exc:
                db.rollback()
                return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(setup, sizes) for sizes in (["48", "50"], ["52", "54"])]
        results = [future.result(timeout=40) for future in futures]
    assert sorted(results) == [201, 409]
    with pg_sessions() as db:
        sizes, audits = _read(db, mid)
        assert sizes in (["48", "50"], ["52", "54"])
        assert len(audits) == 1
        assert audits[0].new_value_json == {"sizes": sizes}
