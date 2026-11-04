from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.libs.dto.inventory.warehouse_stocktake_input import CreateCount
from app.models import stocktake_service as service
from app.schemas.inventory.stocktake import WarehouseStocktake, WarehouseStocktakeRow


def test_create_adds_snapshot_after_flush_before_audit_and_commit(monkeypatch):
    db = Mock()
    db.query.return_value.filter_by.return_value.first.return_value = None
    events = []
    def add(row):
        events.append(row)
        if isinstance(row, WarehouseStocktake):
            row.id = 31
    db.add.side_effect = add
    db.flush.side_effect = lambda: events.append('flush')
    db.commit.side_effect = lambda: events.append('commit')
    monkeypatch.setattr(service, 'package_snapshots', lambda session, **kw: (events.append(('snapshot', kw)) or {7: {'quantity': 4}}))
    monkeypatch.setattr(service, 'log_action', lambda *a, **kw: events.append('audit'))
    monkeypatch.setattr(service, 'count_info', lambda count: {'id': count.id})
    key = uuid4()
    assert service.create_count(db, CreateCount(request_key=key, title='  Count  '), SimpleNamespace(id=9)) == {'id': 31}
    parent, flush, snapshot_call, row, audit, commit = events
    assert (parent.request_key, parent.title, parent.created_by) == (str(key), 'Count', 9)
    assert (flush, snapshot_call, audit, commit) == ('flush', ('snapshot', {'expected_only': True}), 'audit', 'commit')
    assert isinstance(row, WarehouseStocktakeRow)
    assert (row.stocktake_id, row.identity, row.package_id, row.expected, row.category, row.snapshot) == (31, 'package:7', 7, True, 'expected', {'quantity': 4})


def test_create_integrity_collision_rolls_back_then_requeries(monkeypatch):
    db = Mock()
    winner = object()
    db.query.return_value.filter_by.return_value.first.side_effect = [None, winner]
    db.flush.side_effect = IntegrityError('insert', {}, Exception())
    monkeypatch.setattr(service, 'count_info', lambda count: count)
    snapshots = Mock()
    monkeypatch.setattr(service, 'package_snapshots', snapshots)
    assert service.create_count(db, CreateCount(request_key=uuid4(), title='count'), SimpleNamespace(id=1)) is winner
    db.rollback.assert_called_once_with()
    snapshots.assert_not_called()
    db.commit.assert_not_called()


def test_create_integrity_error_without_winner_is_propagated(monkeypatch):
    db = Mock()
    db.query.return_value.filter_by.return_value.first.return_value = None
    db.flush.side_effect = IntegrityError('insert', {}, Exception())
    with pytest.raises(IntegrityError):
        service.create_count(db, CreateCount(request_key=uuid4(), title='count'), SimpleNamespace(id=1))
    db.rollback.assert_called_once_with()
    db.commit.assert_not_called()


@pytest.fixture
def sqlite_sessions():
    """Only stocktake tables are needed; package reads and audit are isolated below."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine('sqlite:///:memory:')
    WarehouseStocktake.__table__.create(engine)
    WarehouseStocktakeRow.__table__.create(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield sessions
    engine.dispose()


def test_create_and_retry_persist_one_snapshot_set(sqlite_sessions, monkeypatch):
    snapshots = Mock(return_value={7: {'quantity': 4}, 9: {'quantity': 2}})
    audit = Mock()
    monkeypatch.setattr(service, 'package_snapshots', snapshots)
    monkeypatch.setattr(service, 'log_action', audit)
    key = uuid4()
    actor = SimpleNamespace(id=9)
    with sqlite_sessions() as db:
        created = service.create_count(db, CreateCount(request_key=key, title='  Count  '), actor)
    with sqlite_sessions() as db:
        # A retry returns the original record, even if its title differs.
        retried = service.create_count(db, CreateCount(request_key=key, title='Other'), actor)
        assert retried == created
        assert db.query(WarehouseStocktake).count() == 1
        rows = db.query(WarehouseStocktakeRow).order_by(WarehouseStocktakeRow.package_id).all()
        assert [(r.stocktake_id, r.identity, r.expected, r.category, r.snapshot) for r in rows] == [
            (created['id'], 'package:7', True, 'expected', {'quantity': 4}),
            (created['id'], 'package:9', True, 'expected', {'quantity': 2}),
        ]
        assert created['title'] == 'Count'
    snapshots.assert_called_once()
    audit.assert_called_once()


def test_failure_before_commit_rolls_back_parent_and_rows_then_retry(sqlite_sessions, monkeypatch):
    monkeypatch.setattr(service, 'package_snapshots', lambda db, **kw: {7: {'quantity': 4}})
    key = uuid4()
    body = CreateCount(request_key=key, title='Count')
    actor = SimpleNamespace(id=9)

    def fail_after_flush(db, *args, **kwargs):
        db.flush()  # Force both parent and expected row into the database transaction.
        raise RuntimeError('audit failure')

    monkeypatch.setattr(service, 'log_action', fail_after_flush)
    with sqlite_sessions() as db:
        with pytest.raises(RuntimeError, match='audit failure'):
            service.create_count(db, body, actor)
        # The real request dependency closes the session after an exception.
    with sqlite_sessions() as db:
        assert db.query(WarehouseStocktake).count() == 0
        assert db.query(WarehouseStocktakeRow).count() == 0
        monkeypatch.setattr(service, 'log_action', lambda *args, **kwargs: None)
        created = service.create_count(db, body, actor)
    with sqlite_sessions() as db:
        assert db.query(WarehouseStocktake).one().id == created['id']
        assert db.query(WarehouseStocktakeRow).one().stocktake_id == created['id']
