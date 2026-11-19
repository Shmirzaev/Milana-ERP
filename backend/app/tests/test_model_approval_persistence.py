"""Focused family approval persistence and rollback checks on isolated SQLite."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.catalog import models_service
from app.schemas import AuditLog, Item, Model, ModelBOM, StockBatch


@pytest.fixture
def factory():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[Model.__table__, ModelBOM.__table__, Item.__table__, StockBatch.__table__, AuditLog.__table__])
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


def seed(factory, scope='standard'):
    with factory() as db:
        rows = [Model(code='FAM' + suffix, name='Family', status='draft', catalog_scope=scope,
                      factory_code='ECO' if scope == 'usluga' else None,
                      details_json={'general': {'model_no': 'FAM', 'variant_no': suffix}})
                for suffix in ('', 'V1', 'V2')]
        other = Model(code='OTHER', name='Other', status='draft')
        db.add_all(rows + [other])
        db.commit()
        return [r.id for r in rows], other.id


def test_family_repeat_and_audit_order(factory, monkeypatch):
    ids, other = seed(factory)
    events = []
    def audit(db, actor, action, entity, entity_id, **kwargs):
        row = db.get(Model, entity_id)
        events.append((entity_id, row.status, row.approved_by, row.approved_at, kwargs['new_value']))
        db.flush()
    monkeypatch.setattr(models_service, 'log_action', audit)
    monkeypatch.setattr(models_service, '_model_out_payload', lambda row, scope: {'id': row.id})
    monkeypatch.setattr(models_service, '_catalog_paid_operation_factory_scope', lambda *args: None)
    with factory() as db:
        models_service.approve_model(SimpleNamespace(id=7), db, ids[1])
        models_service.approve_model(SimpleNamespace(id=8), db, ids[0])
        assert db.get(Model, other).status == 'draft'
        assert [e[0] for e in events] == ids
        assert all(e[1:3] == ('approved', 7) for e in events)
        assert len({e[3] for e in events}) == 1
        assert all(e[4] == {'approval_scope': 'model_family', 'requested_model_id': ids[1]} for e in events)


def test_audit_failure_rolls_back_prior_flushed_rows(factory, monkeypatch):
    ids, _ = seed(factory)
    calls = []
    def audit(db, actor, action, entity, entity_id, **kwargs):
        db.add(AuditLog(user_id=None, action=action, entity_type=entity, entity_id=entity_id))
        db.flush()
        calls.append(entity_id)
        if len(calls) == 2:
            raise RuntimeError('injected audit failure')
    monkeypatch.setattr(models_service, 'log_action', audit)
    with factory() as db:
        with pytest.raises(RuntimeError):
            models_service.approve_model(SimpleNamespace(id=7), db, ids[0])
        db.rollback()
    with factory() as db:
        assert [db.get(Model, mid).status for mid in ids] == ['draft'] * 3
        assert db.query(AuditLog).count() == 0
    assert calls == ids[:2]


def test_usluga_rejects_missing_fabric_before_writes(factory, monkeypatch):
    ids, _ = seed(factory, 'usluga')
    calls = []
    monkeypatch.setattr(models_service, 'log_action', lambda *a, **kw: calls.append(a))
    with factory() as db:
        with pytest.raises(HTTPException) as exc:
            models_service.approve_model(SimpleNamespace(id=7), db, ids[0], 'usluga')
        assert exc.value.status_code == 409
        assert [db.get(Model, mid).status for mid in ids] == ['draft'] * 3
        assert not calls
