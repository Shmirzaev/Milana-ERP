"""Focused SQLite contract tests for schema-owned Catalog BOM deletion."""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.catalog import router as catalog_router
from app.api.routes.usluga import router as usluga_router
from app.core.deps import get_current_user
from app.db.base import Base
from app.db.session import get_db
from app.libs.enums.inventory import WarehouseType
from app.models.catalog import models_service
from app.schemas import (
    AuditLog,
    CuttingRecord,
    Department,
    Item,
    Model,
    ModelBOM,
    ProductionOrder,
    Role,
    StockBatch,
    User,
    Warehouse,
    WorkOrder,
)
from app.schemas.catalog import bom_persistence


@pytest.fixture
def database() -> Iterator[dict]:
    # A single in-memory connection supports TestClient's worker thread while
    # avoiding pytest's Windows mode-0700 tmp_path directory creation.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(engine, "connect", lambda connection, _record: connection.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with sessions.begin() as db:
        role = Role(name="BOM delete permission", permissions=["modeling.bom", "usluga.manage"])
        denied_role = Role(name="No BOM delete permission", permissions=[])
        warehouse = Warehouse(name="BOM delete fixture", type=WarehouseType.FABRIC_STORAGE.value)
        cutting_department = Department(name="BOM delete cutting fixture", code="CUT")
        db.add_all([role, denied_role, warehouse, cutting_department])
        db.flush()
        actors = {
            "standard": User(name="Standard actor", email="bom-standard@example.invalid", password_hash="unused", role_id=role.id, factory_code="MIL"),
            "usluga": User(name="Usluga actor", email="bom-usluga@example.invalid", password_hash="unused", role_id=role.id, factory_code="ECO"),
            "wrong_factory": User(name="Wrong factory actor", email="bom-wrong-factory@example.invalid", password_hash="unused", role_id=role.id, factory_code="MIL"),
            "denied": User(name="Denied actor", email="bom-denied@example.invalid", password_hash="unused", role_id=denied_role.id, factory_code="MIL"),
        }
        models = {
            "standard": Model(code="BOM-DELETE-STANDARD", name="Standard", catalog_scope="standard", factory_code="MIL"),
            "standard_other": Model(code="BOM-DELETE-OTHER", name="Standard other", catalog_scope="standard", factory_code="MIL"),
            "usluga": Model(code="BOM-DELETE-USLUGA", name="Usluga", catalog_scope="usluga", factory_code="ECO"),
        }
        item = Item(sku="BOM-DELETE-ITEM", name="Fabric", category="fabric", unit="kg")
        db.add_all([*actors.values(), *models.values(), item])
        db.flush()
        batch = StockBatch(
            item_id=item.id,
            batch_no="BOM-DELETE-BATCH",
            quantity=12,
            unit="kg",
            warehouse_id=warehouse.id,
        )
        db.add(batch)
        db.flush()
        boms = {
            scope: ModelBOM(
                model_id=models[scope].id,
                item_id=item.id,
                stock_batch_id=batch.id,
                quantity_per_piece=1,
                unit="kg",
                size="M",
                color="Blue",
            )
            for scope in ("standard", "usluga")
        }
        db.add_all(boms.values())
        db.flush()
        production_order = ProductionOrder(
            production_no="BOM-DELETE-PRODUCTION",
            production_type="client_order",
            model_id=models["standard"].id,
        )
        db.add(production_order)
        db.flush()
        work_order = WorkOrder(
            production_order_id=production_order.id,
            department_id=cutting_department.id,
            operation="cutting",
        )
        db.add(work_order)
        db.flush()
        ids = {
            "actors": {key: row.id for key, row in actors.items()},
            "models": {key: row.id for key, row in models.items()},
            "item": item.id,
            "batch": batch.id,
            "work_order": work_order.id,
            "boms": {key: row.id for key, row in boms.items()},
        }

    try:
        yield {"engine": engine, "sessions": sessions, "ids": ids}
    finally:
        engine.dispose()


@pytest.fixture
def client(database) -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(catalog_router, prefix="/api")
    app.include_router(usluga_router, prefix="/api")

    def db_override():
        with database["sessions"]() as db:
            yield db

    def actor_override(request: Request):
        actor_name = request.headers.get("X-BOM-Actor", "standard")
        with database["sessions"]() as db:
            actor = db.get(User, database["ids"]["actors"][actor_name])
            _ = actor.role, actor.department
            db.expunge_all()
            return actor

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_current_user] = actor_override
    try:
        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


def _path(ids: dict, scope: str, model_key: str | None = None, bom_key: str | None = None) -> str:
    model_id = ids["models"][model_key or scope]
    bom_id = ids["boms"][bom_key or scope]
    prefix = "/api/usluga/models" if scope == "usluga" else "/api/models"
    return f"{prefix}/{model_id}/bom/{bom_id}"


def _counts(database) -> tuple[int, int]:
    with database["sessions"]() as db:
        return db.query(ModelBOM).count(), db.query(AuditLog).count()


@pytest.mark.parametrize("scope", ["standard", "usluga"])
def test_delete_route_returns_empty_204_and_audits_exact_old_values(database, client, scope):
    response = client.delete(_path(database["ids"], scope), headers={"X-BOM-Actor": scope})
    assert response.status_code == 204
    assert response.content == b""
    ids = database["ids"]
    with database["sessions"]() as db:
        assert db.get(ModelBOM, ids["boms"][scope]) is None
        assert db.get(Item, ids["item"]) is not None
        assert db.get(StockBatch, ids["batch"]) is not None
        audit = db.query(AuditLog).one()
        assert audit.user_id == ids["actors"][scope]
        assert (audit.action, audit.entity_type, audit.entity_id) == ("delete", "ModelBOM", ids["boms"][scope])
        assert audit.old_value_json is None
        assert audit.new_value_json == {
            "model_id": ids["models"][scope],
            "item_id": ids["item"],
            "stock_batch_id": ids["batch"],
            "size": "M",
            "color": "Blue",
        }


def test_route_permission_denial_preserves_bom_and_audit(database, client):
    before = _counts(database)
    response = client.delete(_path(database["ids"], "standard"), headers={"X-BOM-Actor": "denied"})
    assert response.status_code == 403
    assert _counts(database) == before


@pytest.mark.parametrize(
    ("scope", "model_key", "bom_key", "actor", "expected", "detail"),
    [
        ("standard", "missing", "standard", "standard", 404, "Model not found"),
        ("standard", "standard", "missing", "standard", 404, "BOM row not found"),
        ("standard", "standard_other", "standard", "standard", 404, "BOM row not found"),
        ("standard", "usluga", "usluga", "standard", 404, "Model not found"),
        ("usluga", "missing", "usluga", "wrong_factory", 403, "Eco Cotton"),
        ("usluga", "missing", "usluga", "usluga", 404, "Model not found"),
    ],
)
def test_missing_cross_model_and_scope_refusal_order(database, client, scope, model_key, bom_key, actor, expected, detail):
    ids = database["ids"]
    if model_key == "missing":
        prefix = "/api/usluga/models" if scope == "usluga" else "/api/models"
        path = f"{prefix}/999999/bom/{ids['boms'][bom_key]}"
    elif bom_key == "missing":
        prefix = "/api/usluga/models" if scope == "usluga" else "/api/models"
        path = f"{prefix}/{ids['models'][model_key]}/bom/999999"
    else:
        path = _path(ids, scope, model_key, bom_key)
    before = _counts(database)
    response = client.delete(path, headers={"X-BOM-Actor": actor})
    assert response.status_code == expected
    assert detail in response.json()["detail"]
    assert _counts(database) == before


def test_cutting_link_refuses_delete_without_audit_or_row_loss(database, client):
    ids = database["ids"]
    with database["sessions"].begin() as db:
        db.add(CuttingRecord(work_order_id=ids["work_order"], model_bom_id=ids["boms"]["standard"]))
    before = _counts(database)
    response = client.delete(_path(ids, "standard"))
    assert response.status_code == 409
    assert response.json()["detail"] == "Fabric cannot be deleted after a cutting batch has used it"
    assert _counts(database) == before


def test_schema_delete_uses_attached_row_and_does_not_flush_or_commit(database, monkeypatch):
    ids = database["ids"]
    with database["sessions"]() as db:
        row = db.get(ModelBOM, ids["boms"]["standard"])
        flushes: list[object] = []
        deletions: list[tuple[object, object]] = []
        event.listen(db, "before_flush", lambda session, _context, _instances: flushes.append(session))
        original_delete = db.delete
        monkeypatch.setattr(db, "delete", lambda candidate: (deletions.append((db, candidate)), original_delete(candidate))[1])
        monkeypatch.setattr(db, "commit", lambda: pytest.fail("schema-owned delete must not commit"))
        bom_persistence.delete_model_bom(db, row)
        assert deletions == [(db, row)]
        assert row in db.deleted
        assert flushes == []
        db.rollback()


def test_service_deletes_through_schema_helper_in_same_session_once(database, monkeypatch):
    ids = database["ids"]
    with database["sessions"]() as db:
        actor = db.get(User, ids["actors"]["standard"])
        row = db.get(ModelBOM, ids["boms"]["standard"])
        original_delete = models_service.delete_model_bom
        calls: list[tuple[object, object]] = []

        def observed_delete(session, candidate):
            calls.append((session, candidate))
            return original_delete(session, candidate)

        monkeypatch.setattr(models_service, "delete_model_bom", observed_delete)
        original_commit = db.commit
        commits: list[object] = []

        def observed_commit():
            commits.append(db)
            return original_commit()

        monkeypatch.setattr(db, "commit", observed_commit)
        assert models_service.delete_bom(actor, db, ids["models"]["standard"], ids["boms"]["standard"]) is None
        assert calls == [(db, row)]
        assert commits == [db]


@pytest.mark.parametrize("failure", ["late_audit", "commit"])
def test_late_audit_or_commit_failure_rolls_back_and_retry_succeeds(database, monkeypatch, failure):
    ids = database["ids"]
    with database["sessions"]() as db:
        actor = db.get(User, ids["actors"]["standard"])
        if failure == "late_audit":
            original_log = models_service.log_action

            def audit_then_fail(*args, **kwargs):
                original_log(*args, **kwargs)
                raise RuntimeError("late audit failure")

            monkeypatch.setattr(models_service, "log_action", audit_then_fail)
        else:
            monkeypatch.setattr(db, "commit", lambda: (_ for _ in ()).throw(RuntimeError("commit failure")))
        with pytest.raises(RuntimeError):
            models_service.delete_bom(actor, db, ids["models"]["standard"], ids["boms"]["standard"])
        db.rollback()
    assert _counts(database) == (2, 0)
    monkeypatch.undo()
    with database["sessions"]() as db:
        actor = db.get(User, ids["actors"]["standard"])
        models_service.delete_bom(actor, db, ids["models"]["standard"], ids["boms"]["standard"])
    with database["sessions"]() as db:
        assert db.get(ModelBOM, ids["boms"]["standard"]) is None
        audit = db.query(AuditLog).one()
        assert audit.new_value_json == {
            "model_id": ids["models"]["standard"],
            "item_id": ids["item"],
            "stock_batch_id": ids["batch"],
            "size": "M",
            "color": "Blue",
        }


def test_repeated_missing_api_deletes_do_not_append_audits(database, client):
    ids = database["ids"]
    before = _counts(database)
    for scope in ("standard", "usluga", "standard"):
        prefix = "/api/usluga/models" if scope == "usluga" else "/api/models"
        response = client.delete(f"{prefix}/{ids['models'][scope]}/bom/999999", headers={"X-BOM-Actor": scope})
        assert response.status_code == 404
        assert response.json()["detail"] == "BOM row not found"
    assert _counts(database) == before
