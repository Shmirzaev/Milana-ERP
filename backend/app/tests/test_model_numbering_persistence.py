"""Model-number reservation: real SQLite storage, caller transaction and boundary.

These tests also run with --noconftest: they own their engine and need no app,
HTTP server, shared database or seeded production fixture.
"""
from copy import deepcopy
import inspect

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, object_session

from app.core import model_search  # noqa: F401 - register SQLite identity normalizer
from app.db.base import Base
from app.libs.dto.catalog.model_input import PaidOperationIn
from app.libs.enums.catalog import CatalogScope, PaidProcessSection
from app.libs.types.catalog import ModelCreateDetails, ModelInsert
from app.models import numbering_service as numbering
from app.schemas import Model, SystemSetting
from app.schemas.catalog.model_persistence import insert_model


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        yield session
        session.rollback()
    engine.dispose()


def setting(db):
    return db.query(SystemSetting).filter_by(key="model_numbering").one_or_none()


def test_model_create_schema_insert_flushes_typed_rows_without_committing(db):
    flushes = []
    commits = []
    before_flush = lambda *args: flushes.append(True)
    after_commit = lambda *args: commits.append(True)
    event.listen(db, "before_flush", before_flush)
    event.listen(db, "after_commit", after_commit)
    try:
        row = insert_model(
            db,
            ModelInsert(
                code="SCHEMA-CREATE-1",
                name="Schema create contract",
                catalog_scope=CatalogScope.STANDARD,
                factory_code=None,
                category=None,
                description=None,
                brand_id=None,
                collection_id=None,
                product_type=None,
                season=None,
                constructor_employee_id=None,
                designer_employee_id=None,
                details_json=ModelCreateDetails(
                    metadata={"general": {"model_no": "SCHEMA-CREATE-1"}, "extension": {"keep": True}},
                    has_paid_operations=True,
                    paid_operations=[PaidOperationIn(section=PaidProcessSection.SEWING, rate="2.75")],
                    has_paid_operations_alias=False,
                    paidOperations=None,
                ),
                status="draft",
                sam_minutes=0,
                created_by=None,
            ),
        )
        assert object_session(row) is db
        assert row.id is not None
        assert flushes == [True]
        assert commits == []
        assert row.details_json == {
            "general": {"model_no": "SCHEMA-CREATE-1"},
            "extension": {"keep": True},
            "paid_operations": [{"section": "sewing", "rate": "2.75"}],
        }
    finally:
        event.remove(db, "before_flush", before_flush)
        event.remove(db, "after_commit", after_commit)
        db.rollback()


def test_reserved_insert_and_update_use_schema_method_same_session_one_flush(db, monkeypatch):
    calls, flushes, commits = [], [], []
    original = SystemSetting.write_model_numbering.__func__

    def observe(cls, supplied, *, setting, value_json):
        calls.append((supplied, setting, deepcopy(value_json)))
        return original(cls, supplied, setting=setting, value_json=value_json)

    monkeypatch.setattr(SystemSetting, "write_model_numbering", classmethod(observe))
    event.listen(db, "before_flush", lambda *args: flushes.append(True))
    event.listen(db, "after_commit", lambda *args: commits.append(True))
    assert numbering.next_model_no(db, "XJ", reserve=True) == "XJ3201"
    row = setting(db)
    assert row.id is not None
    assert numbering.next_model_no(db, "PJ", reserve=True) == "PJ1253"
    assert len(calls) == len(flushes) == 2 and not commits
    assert calls[0][0] is calls[1][0] is db
    assert calls[0][1] is None and calls[1][1] is row
    assert row.value_json == {"last_assigned": {"XJ": 3201, "PJ": 1253}}
    assert db.query(SystemSetting).count() == 1
    db.commit()
    assert commits == [True]
    db.expire_all()
    assert setting(db).value_json == {"last_assigned": {"XJ": 3201, "PJ": 1253}}


@pytest.mark.parametrize("existing", [False, True])
def test_outer_rollback_restores_counter_and_other_pending_participants(db, existing):
    prior = {"last_assigned": {"XJ": 3500, "PJ": 1700}, "note": {"keep": [1, 2]}}
    if existing:
        db.add(SystemSetting(key="model_numbering", value_json=deepcopy(prior)))
        db.commit()
    before = deepcopy(setting(db).value_json) if existing else None
    db.add(Model(code="ROLLBACK-PARTICIPANT", name="Synthetic pending model"))
    expected = "XJ3501" if existing else "XJ3201"
    assert numbering.next_model_no(db, "XJ", reserve=True) == expected
    assert db.query(Model).filter_by(code="ROLLBACK-PARTICIPANT").count() == 1
    db.rollback()
    assert db.query(Model).filter_by(code="ROLLBACK-PARTICIPANT").count() == 0
    assert (setting(db).value_json if setting(db) else None) == before
    assert numbering.next_model_no(db, "XJ", reserve=True) == expected


@pytest.mark.parametrize("value,expected", [
    (None, 3201), ([], 3201), ({}, 3201),
    ({"last_assigned": "legacy"}, 3201),
    ({"last_assigned": {"XJ": "bad", "PJ": 1700}, "custom": [1, 2]}, 3201),
    ({"last_assigned": {"XJ": "3500", "PJ": 1700}, "custom": {"v": True}}, 3501),
])
def test_legacy_json_fallback_and_unrelated_keys_are_preserved(db, value, expected):
    db.add(SystemSetting(key="model_numbering", value_json=deepcopy(value)))
    db.commit()
    assert numbering.next_model_no(db, " x-j ", reserve=True) == f"XJ{expected}"
    actual = setting(db).value_json
    before = value if isinstance(value, dict) else {}
    assigned = before.get("last_assigned") if isinstance(before.get("last_assigned"), dict) else {}
    assert actual == {**before, "last_assigned": {**assigned, "XJ": expected}}


def test_occupied_legacy_family_metadata_and_outlier_semantics(db):
    db.add_all([
        Model(code="ХJ-3201-123", name="Legacy Cyrillic family"),
        Model(code="SPECIAL", name="Explicit family", details_json={"general": {"modelNo": "XJ3202"}}),
        Model(code="XJ7641", name="Historical outlier"),
    ])
    db.commit()
    assert numbering.next_model_no(db, "XJ") == "XJ3203"
    assert setting(db) is None
    assert numbering.next_model_no(db, "XJ", reserve=True) == "XJ3203"
    assert numbering.next_model_no(db, "XJ", reserve=True) == "XJ3204"


def test_preview_and_invalid_prefix_never_enter_persistence_or_lock(db, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("read-only/invalid path reached writer or lock")
    monkeypatch.setattr(SystemSetting, "write_model_numbering", forbidden)
    monkeypatch.setattr(numbering, "_acquire_numbering_lock", forbidden)
    assert numbering.next_model_no(db, "xj") == "XJ3201"
    assert numbering.next_model_no(db, "Х-J") == "XJ3201"
    with pytest.raises(HTTPException) as err:
        numbering.next_model_no(db, "ZZ", reserve=True)
    assert (err.value.status_code, err.value.detail) == (400, "Select a supported model prefix")
    assert setting(db) is None


def test_lock_precedes_lookup_and_writer_and_owns_no_transaction(db, monkeypatch):
    sequence = []
    original = SystemSetting.write_model_numbering.__func__
    monkeypatch.setattr(numbering, "_acquire_numbering_lock", lambda supplied, resource: sequence.append(("lock", supplied, resource)))
    def before_execute(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT") and "system_settings" in statement:
            sequence.append(("lookup", db, None))
    event.listen(db.bind, "before_cursor_execute", before_execute)
    def write(cls, supplied, **kwargs):
        sequence.append(("writer", supplied, None))
        return original(cls, supplied, **kwargs)
    monkeypatch.setattr(SystemSetting, "write_model_numbering", classmethod(write))
    numbering.next_model_no(db, "XJ", reserve=True)
    assert [x[0] for x in sequence] == ["lock", "lookup", "writer"]
    assert all(x[1] is db for x in sequence)
    assert sequence[0][2] == "model_numbering" and db.in_transaction()


def test_mapped_json_events_and_flush_originate_in_schema_method(db):
    stacks = []
    def observe(*args):
        stacks.append({frame.function for frame in inspect.stack()})
    event.listen(SystemSetting.value_json, "set", observe)
    event.listen(db, "before_flush", observe)
    try:
        numbering.next_model_no(db, "XJ", reserve=True)
        numbering.next_model_no(db, "PJ", reserve=True)
    finally:
        event.remove(SystemSetting.value_json, "set", observe)
        event.remove(db, "before_flush", observe)
    assert len(stacks) == 4
    assert all("write_model_numbering" in stack for stack in stacks)


@pytest.mark.parametrize("scope", ["standard", "usluga"])
def test_actual_catalog_caller_shares_counter_and_audit_transaction(db, scope):
    from app.libs.dto.catalog.model_input import ModelCreateIn
    from app.models.catalog import models_service
    from app.schemas import AuditLog, Role, User

    role = Role(name="admin", permissions=["*"])
    actor = User(email="numbering@example.invalid", name="Synthetic numbering", password_hash="unused", role=role)
    db.add_all([role, actor]); db.commit()
    commits = []
    event.listen(db, "after_commit", lambda *args: commits.append(True))
    payload = ModelCreateIn(code="ignored-preview", name="Synthetic auto number", automatic_model_prefix="XJ")
    first = models_service.create_model(actor, db, payload, scope)
    second = models_service.create_model(actor, db, payload, scope)
    assert first["code"] == "XJ3201" and second["code"] == "XJ3202"
    assert setting(db).value_json == {"last_assigned": {"XJ": 3202}}
    assert db.query(Model).filter_by(catalog_scope=scope).count() == 2
    assert db.query(AuditLog).filter_by(action="create", entity_type="Model").count() == 2
    assert commits == [True, True]


def test_actual_catalog_late_audit_failure_rolls_back_number_and_model(db, monkeypatch):
    from app.libs.dto.catalog.model_input import ModelCreateIn
    from app.models.catalog import models_service
    from app.schemas import Role, User

    actor = User(email="rollback@example.invalid", name="Synthetic rollback", password_hash="unused", role=Role(name="admin", permissions=["*"]))
    db.add(actor); db.commit()
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic audit failure after model/counter flush")
    with monkeypatch.context() as patch:
        patch.setattr(models_service, "log_action", fail)
        with pytest.raises(RuntimeError, match="synthetic audit failure"):
            models_service.create_model(actor, db, ModelCreateIn(code="preview", name="Synthetic failure", automatic_model_prefix="XJ"))
    db.rollback()  # Existing outer operation/session owns failure rollback.
    assert setting(db) is None and db.query(Model).count() == 0
    assert numbering.next_model_no(db, "XJ") == "XJ3201"
