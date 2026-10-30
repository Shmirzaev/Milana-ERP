"""Focused parity and transaction tests for the catalog BOM PATCH write seam.

Run in the confined environment with ``pytest --noconftest``. These tests use
only an in-memory SQLite database and do not load repository-wide conftest state.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.libs.dto.catalog.model_bom_update import ModelBOMUpdate
from app.libs.enums.catalog import BomMaterialRole
from app.libs.enums.inventory import WarehouseType
from app.libs.types.catalog import NormalizedBomCreate, NormalizedBomUpdate
from app.models.catalog import models_service
from app.schemas import (
    AuditLog, CuttingRecord, Department, Item, Model, ModelBOM,
    ProductionOrder, StockBatch, Warehouse, WorkOrder,
)
from app.schemas.catalog import bom_persistence


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        Model.__table__, ModelBOM.__table__, CuttingRecord.__table__, Item.__table__,
        Warehouse.__table__, StockBatch.__table__, AuditLog.__table__, Department.__table__,
        ProductionOrder.__table__, WorkOrder.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(engine, tables=tables)
        engine.dispose()


@pytest.fixture
def seeded(session_factory):
    with session_factory() as db:
        model = Model(code="BOM-UPDATE", name="BOM Update")
        item = Item(sku="BOM-SEED", name="Seed accessory", category="accessory", unit="pcs")
        db.add_all([model, item])
        db.flush()
        row = ModelBOM(
            model_id=model.id,
            item_id=item.id,
            material_name=None,
            material_role=None,
            stock_batch_id=None,
            size="M",
            color="Blue",
            photo_url="/storage/model-files/current.webp",
            quantity_per_piece=1.25,
            unit="kg",
            waste_percent=3,
        )
        db.add(row)
        db.commit()
        ids = model.id, row.id, item.id
    return ids


def _patch(db: Session, seeded, payload: ModelBOMUpdate, *, scope="standard"):
    model_id, bom_id, *_ = seeded
    return models_service.update_bom(
        SimpleNamespace(id=17), db, model_id, bom_id, payload, scope
    )


def _add_cutting_usage(db: Session, model_id: int, bom_id: int) -> None:
    department = Department(name="BOM Test Cutting", code="BOM-CUT")
    production_order = ProductionOrder(
        production_no="BOM-CUT-ORDER",
        production_type="client_order",
        model_id=model_id,
    )
    db.add_all([department, production_order])
    db.flush()
    work_order = WorkOrder(
        production_order_id=production_order.id,
        department_id=department.id,
        operation="cutting",
    )
    db.add(work_order)
    db.flush()
    db.add(CuttingRecord(work_order_id=work_order.id, model_bom_id=bom_id))


def _install_audit_spy(monkeypatch, events: list[tuple], *, audit_write=False):
    def log_action(db, actor, action, entity_type, entity_id, *, new_value=None, **kwargs):
        events.append(("audit", action, entity_type, entity_id, dict(new_value or {})))
        if audit_write:
            db.add(AuditLog(
                user_id=None,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                new_value_json=dict(new_value or {}),
            ))

    monkeypatch.setattr(models_service, "log_action", log_action)


def test_patch_omitted_fields_stay_and_explicit_null_clears(seeded, session_factory, monkeypatch):
    events: list[tuple] = []
    _install_audit_spy(monkeypatch, events)
    with session_factory() as db:
        _patch(db, seeded, ModelBOMUpdate(quantity_per_piece=2.5))
        row = db.get(ModelBOM, seeded[1])
        assert row.size == "M"
        assert row.color == "Blue"
        assert row.quantity_per_piece == 2.5

        _patch(db, seeded, ModelBOMUpdate(size=None))
        assert db.get(ModelBOM, seeded[1]).size is None
    assert [event[0] for event in events] == ["audit", "audit"]


def test_empty_patch_preserves_fields_and_audits_model_identity(seeded, session_factory, monkeypatch):
    events: list[tuple] = []
    _install_audit_spy(monkeypatch, events)
    with session_factory() as db:
        before = db.get(ModelBOM, seeded[1])
        before_values = (before.item_id, before.size, before.color, before.photo_url,
                         before.quantity_per_piece, before.unit, before.waste_percent)
        assert _patch(db, seeded, ModelBOMUpdate()) == {"id": seeded[1]}
        after = db.get(ModelBOM, seeded[1])
        assert (after.item_id, after.size, after.color, after.photo_url,
                after.quantity_per_piece, after.unit, after.waste_percent) == before_values
    assert events == [("audit", "update", "ModelBOM", seeded[1], {"model_id": seeded[0]})]


def test_patch_audit_commit_refresh_order_and_raw_role_value(seeded, session_factory, monkeypatch):
    events: list[tuple] = []
    _install_audit_spy(monkeypatch, events)
    with session_factory() as db:
        original_commit = db.commit
        original_refresh = db.refresh

        def commit():
            events.append(("commit",))
            original_commit()

        def refresh(instance, *args, **kwargs):
            events.append(("refresh", instance.id))
            return original_refresh(instance, *args, **kwargs)

        monkeypatch.setattr(db, "commit", commit)
        monkeypatch.setattr(db, "refresh", refresh)
        model_id, bom_id, *_ = seeded
        model = db.get(Model, model_id)
        model.catalog_scope = "usluga"
        model.factory_code = "ECO"
        db.commit()
        target = db.get(ModelBOM, bom_id)
        target.material_name = "Cotton"
        target.material_role = "main"
        db.commit()
        events.clear()

        result = _patch(db, seeded, ModelBOMUpdate(material_role="  SECONDARY "), scope="usluga")

        assert result == {"id": bom_id}
        assert target.material_role == "secondary"
        assert events[0] == ("audit", "update", "ModelBOM", bom_id, {
            "model_id": model_id,
            "item_id": None,
            "material_name": "Cotton",
            "material_role": "secondary",
            "stock_batch_id": None,
            "color": "Blue",
            "photo_url": "/storage/model-files/current.webp",
            "unit": "kg",
        })
        assert [event[0] for event in events] == ["audit", "commit", "refresh"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("MAIN", BomMaterialRole.MAIN), ("  secondary ", BomMaterialRole.SECONDARY),
     ("  SECONDARY     ", BomMaterialRole.SECONDARY)],
)
def test_update_role_accepts_supported_normalized_values_with_raw_16_char_limit(raw, expected):
    payload = ModelBOMUpdate.model_validate({"material_role": raw})
    assert payload.material_role is expected
    assert payload.model_dump(exclude_unset=True) == {"material_role": expected}


@pytest.mark.parametrize("raw", ["unknown", " main " + " " * 11, 7])
def test_update_role_rejects_invalid_or_overlong_fixed_values(raw):
    # The DTO's actual Enum contract deliberately changes invalid-role behavior:
    # the old service returned HTTP 400 for a bad manual role, and discarded a
    # bad role for inventory-linked rows; both now fail request validation (422).
    with pytest.raises(ValueError):
        ModelBOMUpdate.model_validate({"material_role": raw})


def test_update_role_null_and_unknown_extra_fields_keep_legacy_shape():
    payload = ModelBOMUpdate.model_validate({"material_role": None, "unrecognized": 3})
    assert payload.model_dump(exclude_unset=True) == {"material_role": None}
    schema = ModelBOMUpdate.model_json_schema()
    role_schema = schema["$defs"]["BomMaterialRole"]
    assert role_schema["enum"] == ["main", "secondary"]
    assert schema["properties"]["material_role"]["anyOf"] == [
        {"$ref": "#/$defs/BomMaterialRole"},
        {"type": "null"},
    ]
    assert "additionalProperties" not in schema


def test_identity_change_after_cutting_refuses_before_mutation_or_audit(
    seeded, session_factory, monkeypatch
):
    events: list[tuple] = []
    _install_audit_spy(monkeypatch, events)
    with session_factory() as db:
        _add_cutting_usage(db, seeded[0], seeded[1])
        db.commit()
        with pytest.raises(HTTPException) as error:
            _patch(db, seeded, ModelBOMUpdate(item_id=None))
        assert error.value.status_code == 409
        assert db.get(ModelBOM, seeded[1]).quantity_per_piece == 1.25
    assert events == []


def test_missing_model_and_bom_keep_404_order_for_valid_typed_payload(seeded, session_factory):
    with session_factory() as db:
        with pytest.raises(HTTPException) as error:
            _patch(db, (seeded[0] + 1000, seeded[1] + 1000), ModelBOMUpdate(material_role="MAIN"))
        assert error.value.status_code == 404
        assert error.value.detail == "Model not found"

        with pytest.raises(HTTPException) as error:
            _patch(db, (seeded[0], seeded[1] + 1000), ModelBOMUpdate(quantity_per_piece=2))
        assert error.value.status_code == 404
        assert error.value.detail == "BOM row not found"


def test_invalid_role_validation_precedes_cutting_identity_refusal(
    seeded, session_factory
):
    with session_factory() as db:
        _add_cutting_usage(db, seeded[0], seeded[1])
        db.commit()
        # The former raw-string DTO reached service policy and would return the
        # cutting-linked 409 before the invalid-role 400. The real Enum DTO now
        # rejects the request at binding (HTTP 422) before service invocation.
        with pytest.raises(ValidationError):
            ModelBOMUpdate.model_validate({"material_role": "not-a-role"})


def test_inventory_batch_and_fabric_categories_keep_existing_normalization(
    seeded, session_factory, monkeypatch
):
    events: list[tuple] = []
    _install_audit_spy(monkeypatch, events)
    with session_factory() as db:
        accessory = Item(sku="BOM-ACC", name="Button", category="accessory", unit="pcs")
        fabric = Item(sku="BOM-FAB", name="Cotton", category="fabric", unit="m")
        warehouse = Warehouse(name="BOM", type=WarehouseType.FABRIC_STORAGE.value)
        db.add_all([accessory, fabric, warehouse])
        db.flush()
        batch = StockBatch(
            item_id=accessory.id,
            batch_no="BOM-ACC-1",
            quantity=10,
            unit="pcs",
            warehouse_id=warehouse.id,
            color="Navy",
            image_url="/storage/model-files/batch.webp",
        )
        db.add(batch)
        db.commit()

        # A batch-only change keeps the row's current item identity and rejects
        # a batch owned by another item; it must not silently replace item_id.
        with pytest.raises(HTTPException) as mismatch:
            _patch(db, seeded, ModelBOMUpdate(stock_batch_id=batch.id))
        assert mismatch.value.status_code == 400
        assert db.get(ModelBOM, seeded[1]).item_id == seeded[2]
        assert events == []

        _patch(db, seeded, ModelBOMUpdate(item_id=accessory.id, stock_batch_id=batch.id))
        row = db.get(ModelBOM, seeded[1])
        assert row.item_id == accessory.id
        assert row.color == "Blue"
        assert row.photo_url == "/storage/model-files/current.webp"
        assert row.unit == "kg"

        # Batch metadata fills only values that are missing/falsy on the row.
        row.color = None
        row.photo_url = ""
        row.unit = ""
        db.commit()
        _patch(db, seeded, ModelBOMUpdate(stock_batch_id=batch.id))
        row = db.get(ModelBOM, seeded[1])
        assert row.color == "Navy"
        assert row.photo_url == "/storage/model-files/batch.webp"
        assert row.unit == ""

        _patch(db, seeded, ModelBOMUpdate(item_id=fabric.id, stock_batch_id=batch.id))
        row = db.get(ModelBOM, seeded[1])
        assert row.item_id == fabric.id
        assert row.stock_batch_id is None
        assert row.unit == "m"


def test_duplicate_usluga_main_role_refuses_before_mutation_or_audit(
    seeded, session_factory, monkeypatch
):
    events: list[tuple] = []
    _install_audit_spy(monkeypatch, events)
    with session_factory() as db:
        model = db.get(Model, seeded[0])
        model.catalog_scope = "usluga"
        model.factory_code = "ECO"
        row = db.get(ModelBOM, seeded[1])
        row.material_name = "Target"
        row.material_role = "secondary"
        db.add(ModelBOM(
            model_id=model.id,
            material_name="Existing main",
            material_role="main",
            quantity_per_piece=1,
            unit="kg",
        ))
        db.commit()
        with pytest.raises(HTTPException) as error:
            _patch(db, seeded, ModelBOMUpdate(material_role="main"), scope="usluga")
        assert error.value.status_code == 409
        assert row.material_role == "secondary"
    assert events == []


def test_manual_role_omission_preserves_value_and_explicit_null_keeps_400(
    seeded, session_factory, monkeypatch
):
    events: list[tuple] = []
    _install_audit_spy(monkeypatch, events)
    with session_factory() as db:
        model = db.get(Model, seeded[0])
        model.catalog_scope = "usluga"
        model.factory_code = "ECO"
        row = db.get(ModelBOM, seeded[1])
        row.item_id = None
        row.material_name = "Cotton"
        row.material_role = "main"
        row.stock_batch_id = None
        db.commit()

        _patch(db, seeded, ModelBOMUpdate(material_name="Cotton jersey"), scope="usluga")
        assert row.material_role == "main"

        with pytest.raises(HTTPException) as error:
            _patch(db, seeded, ModelBOMUpdate(material_role=None), scope="usluga")
        assert error.value.status_code == 400
        assert row.material_role == "main"
    assert len(events) == 1


def test_inventory_to_manual_material_without_role_keeps_400(seeded, session_factory, monkeypatch):
    events: list[tuple] = []
    _install_audit_spy(monkeypatch, events)
    with session_factory() as db:
        model = db.get(Model, seeded[0])
        model.catalog_scope = "usluga"
        model.factory_code = "ECO"
        db.commit()
        with pytest.raises(HTTPException) as error:
            _patch(db, seeded, ModelBOMUpdate(material_name="Manual fabric"), scope="usluga")
        assert error.value.status_code == 400
        assert db.get(ModelBOM, seeded[1]).item_id == seeded[2]
    assert events == []


@pytest.mark.parametrize("value", ["javascript:alert(1)", "", None])
def test_photo_validation_only_runs_for_truthy_values(seeded, session_factory, monkeypatch, value):
    events: list[tuple] = []
    _install_audit_spy(monkeypatch, events)
    with session_factory() as db:
        if value == "javascript:alert(1)":
            with pytest.raises(HTTPException) as error:
                _patch(db, seeded, ModelBOMUpdate(photo_url=value))
            assert error.value.status_code == 400
            assert events == []
            return
        _patch(db, seeded, ModelBOMUpdate(photo_url=value))
        assert db.get(ModelBOM, seeded[1]).photo_url == value
    assert len(events) == 1


@pytest.mark.parametrize("failure_point", ["audit", "commit"])
def test_late_failure_rolls_back_bom_and_audit_after_caller_cleanup(
    seeded, session_factory, monkeypatch, failure_point
):
    events: list[tuple] = []
    _install_audit_spy(monkeypatch, events, audit_write=True)
    with session_factory() as db:
        original_commit = db.commit
        if failure_point == "audit":
            def fail_after_adding_audit(db_arg, actor, action, entity_type, entity_id, *, new_value=None, **kwargs):
                db_arg.add(AuditLog(
                    user_id=None,
                    action=action,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    new_value_json=dict(new_value or {}),
                ))
                raise RuntimeError("audit write failed late")

            monkeypatch.setattr(models_service, "log_action", fail_after_adding_audit)
        else:
            def fail_during_commit():
                db.flush()
                raise RuntimeError("commit failed after flush")

            monkeypatch.setattr(db, "commit", fail_during_commit)
        with pytest.raises(RuntimeError):
            _patch(db, seeded, ModelBOMUpdate(quantity_per_piece=9))
        # The service deliberately leaves rollback/recovery to its caller.
        db.rollback()

    with session_factory() as verify:
        row = verify.get(ModelBOM, seeded[1])
        assert float(row.quantity_per_piece) == 1.25
        assert verify.scalars(select(AuditLog)).all() == []


def test_explicit_null_quantity_fails_at_outer_commit_and_rolls_back(seeded, session_factory, monkeypatch):
    events: list[tuple] = []
    _install_audit_spy(monkeypatch, events)
    with session_factory() as db:
        with pytest.raises(IntegrityError):
            _patch(db, seeded, ModelBOMUpdate(quantity_per_piece=None))
        # The old contract lets the mapped NOT NULL constraint reject null at
        # commit; the service does not pre-validate or roll back automatically.
        assert events and events[0][0] == "audit"
        db.rollback()

    with session_factory() as verify:
        assert float(verify.get(ModelBOM, seeded[1]).quantity_per_piece) == 1.25


def test_service_cannot_bypass_schema_owned_setter(seeded, session_factory, monkeypatch):
    events: list[tuple] = []
    _install_audit_spy(monkeypatch, events)

    def fail_if_not_called(*args, **kwargs):
        raise AssertionError("schema-owned BOM setter was bypassed")

    monkeypatch.setattr(models_service, "update_model_bom", fail_if_not_called)
    with session_factory() as db, pytest.raises(AssertionError, match="setter was bypassed"):
        _patch(db, seeded, ModelBOMUpdate(quantity_per_piece=5))
    assert events == []


def test_service_produces_typed_partial_update_and_canonical_role(
    seeded, session_factory, monkeypatch
):
    commands: list[NormalizedBomUpdate] = []
    original_update = bom_persistence.update_model_bom

    def capture(db, *, row, values):
        commands.append(dict(values))
        return original_update(db, row=row, values=values)

    monkeypatch.setattr(models_service, "update_model_bom", capture)
    with session_factory() as db:
        _patch(db, seeded, ModelBOMUpdate(color=None))
        assert commands[-1] == {"color": None}

        model = db.get(Model, seeded[0])
        row = db.get(ModelBOM, seeded[1])
        model.catalog_scope = "usluga"
        model.factory_code = "ECO"
        row.item_id = None
        row.material_name = "Cotton"
        row.material_role = "main"
        row.stock_batch_id = None
        db.commit()
        _patch(db, seeded, ModelBOMUpdate(material_role=" SECONDARY "), scope="usluga")

    command = commands[-1]
    assert command == {
        "item_id": None,
        "material_name": "Cotton",
        "material_role": BomMaterialRole.SECONDARY,
        "stock_batch_id": None,
        "color": None,
        "photo_url": "/storage/model-files/current.webp",
        "unit": "kg",
    }
    assert command["material_role"] is BomMaterialRole.SECONDARY


def test_normalized_update_keeps_same_value_attribute_assignments(
    seeded, session_factory
):
    with session_factory() as db:
        model = db.get(Model, seeded[0])
        row = db.get(ModelBOM, seeded[1])
        model.catalog_scope = "usluga"
        model.factory_code = "ECO"
        row.item_id = None
        row.material_name = "Cotton"
        row.material_role = "main"
        row.stock_batch_id = None
        row.color = None
        row.photo_url = None
        db.commit()

    assignments: list[tuple[str, object, object]] = []
    def capture(name):
        def on_set(_target, value, oldvalue, _initiator):
            assignments.append((name, value, oldvalue))
            return value
        return on_set

    attributes = (
        "item_id", "material_name", "material_role", "stock_batch_id",
        "color", "photo_url", "unit", "size", "quantity_per_piece",
    )
    listeners = [(getattr(ModelBOM, name), capture(name)) for name in attributes]
    for attribute, listener in listeners:
        event.listen(attribute, "set", listener, retval=True)
    try:
        with session_factory() as db:
            _patch(
                db,
                seeded,
                ModelBOMUpdate(material_role="secondary", size="M", quantity_per_piece=1.25),
                scope="usluga",
            )
    finally:
        for attribute, listener in listeners:
            event.remove(attribute, "set", listener)

    assert [name for name, _value, _oldvalue in assignments] == list(attributes)
    assert [(name, value) for name, value, oldvalue in assignments if value == oldvalue] == [
        ("item_id", None),
        ("material_name", "Cotton"),
        ("stock_batch_id", None),
        ("color", None),
        ("photo_url", None),
        ("unit", "kg"),
        ("size", "M"),
        ("quantity_per_piece", 1.25),
    ]


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"unknown": 1}, "Unknown normalized BOM update fields"),
        ({"material_role": "legacy"}, "material_role must be a BomMaterialRole"),
        ({"item_id": "3"}, "item_id must be an integer"),
    ],
)
def test_typed_update_command_rejects_unowned_or_untyped_values(values, message):
    with pytest.raises(TypeError, match=message):
        models_service._normalized_bom_update_command(values)


def test_typed_update_command_covers_every_decided_field_and_null():
    source = {
        "item_id": 11,
        "material_name": None,
        "material_role": BomMaterialRole.MAIN,
        "stock_batch_id": 12,
        "size": "M",
        "color": None,
        "photo_url": "/storage/model-files/sample.webp",
        "quantity_per_piece": 1.25,
        "unit": "kg",
        "waste_percent": 2.5,
    }
    command = models_service._normalized_bom_update_command(source)
    assert command == source
    assert command["material_role"] is BomMaterialRole.MAIN
    assert command["material_name"] is None
    assert command["color"] is None


def test_schema_setter_assigns_only_present_fields_and_serializes_enum(
    seeded, session_factory, monkeypatch
):
    _, bom_id, *_ = seeded
    with session_factory() as db:
        row = db.get(ModelBOM, bom_id)
        values: NormalizedBomUpdate = {"material_role": BomMaterialRole.SECONDARY, "color": None}
        def forbidden_transaction_operation(*args, **kwargs):
            raise AssertionError("schema setter changed transaction/flush timing")

        monkeypatch.setattr(db, "flush", forbidden_transaction_operation)
        monkeypatch.setattr(db, "commit", forbidden_transaction_operation)
        monkeypatch.setattr(db, "rollback", forbidden_transaction_operation)
        monkeypatch.setattr(db, "add", forbidden_transaction_operation)
        monkeypatch.setattr(db, "begin", forbidden_transaction_operation)
        monkeypatch.setattr(db, "begin_nested", forbidden_transaction_operation)
        assert bom_persistence.update_model_bom(db, row=row, values=values) is row
        assert row.material_role == "secondary"
        assert row.color is None
        assert row.size == "M"
        assert db.in_transaction()


def test_existing_create_insert_keeps_enum_storage_behavior(session_factory):
    with session_factory() as db:
        model = Model(code="BOM-CREATE", name="BOM Create")
        db.add(model)
        db.flush()
        create = NormalizedBomCreate(
            item_id=None,
            material_name="Cotton",
            material_role=BomMaterialRole.MAIN,
            stock_batch_id=None,
            size=None,
            color=None,
            photo_url=None,
            quantity_per_piece=1,
            unit="kg",
            waste_percent=0,
        )
        row = bom_persistence.insert_model_bom(db, model_id=model.id, create=create)
        assert row.material_role == "main"
        db.commit()
        assert db.get(ModelBOM, row.id).material_role == "main"
