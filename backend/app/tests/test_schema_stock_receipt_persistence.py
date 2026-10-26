"""INV-OP-01: the stock batch receipt writes through the schema-owned persistence.

Two things are checked here and both are executed, not asserted from prose:

1. The boundary. `receive_stock` must not build or add a mapped row itself, and
   the schema helper must not commit. This is a source-level assertion on the
   two functions, because the boundary is a property of the code shape.
2. The behaviour. The receipt must still persist the same batch, the same
   ledger movement, the same audit entry and the same idempotency record.

The expected vocabulary is written as independent literals. It is not derived
from the enum under test, so a missing or misspelled member cannot become its
own expected answer.
"""

import ast
import inspect
import re
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.db.session import SessionLocal
from app.libs.dto.inventory.stock_batch_input import StockBatchIn
from app.libs.dto.inventory.stock_batch_update import StockBatchUpdate
from app.libs.enums.inventory import StockBatchQcStatus, StockMovementType
from app.models.idempotency_service import request_fingerprint
from app.models.inventory import stock_service
from app.models.inventory.stock_service import receive_stock
from app.schemas import AuditLog, IdempotencyRecord, Item, StockBatch, StockMovement, Warehouse
from app.schemas.inventory import stock_receipt_persistence
from app.schemas.inventory.inventory import MOVEMENT_TYPE_CHECK, QC_STATUS_CHECK

# Independent expected values, taken from the 8749978 ORM CHECK constraints.
EXPECTED_QC_STATUSES = ("pending", "passed", "failed", "rejected", "hold")
EXPECTED_MOVEMENT_TYPES = (
    "receive", "transfer", "issue", "consume", "adjustment",
    "return", "produce", "waste", "shipment",
)


# ===== Boundary =====

def test_receive_stock_does_not_write_mapped_rows_itself():
    source = inspect.getsource(receive_stock)
    assert "db.add(" not in source
    assert "StockBatch(" not in source
    assert "StockMovement(" not in source
    assert "stock_receipt_persistence.add_stock_batch(" in source
    assert "stock_receipt_persistence.add_receive_movement(" in source


def test_receive_stock_still_owns_the_single_transaction():
    source = inspect.getsource(receive_stock)
    assert source.count("db.commit()") == 1
    assert "db.rollback(" not in source


def test_schema_persistence_helper_never_commits_or_rolls_back():
    source = inspect.getsource(stock_receipt_persistence)
    assert "db.commit(" not in source
    assert "db.rollback(" not in source
    assert "db.begin(" not in source


def test_schema_persistence_helper_does_not_import_the_service_layer():
    """The schema layer must not reach back into the service layer."""
    tree = ast.parse(inspect.getsource(stock_receipt_persistence))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
    assert not [name for name in imported if name == "app.models" or name.startswith("app.models.")]
    assert not [name for name in imported if name == "app.api.routes" or name.startswith("app.api.routes.")]


# ===== Vocabulary =====

def test_check_constraint_text_is_unchanged():
    assert QC_STATUS_CHECK == "qc_status IN ('pending', 'passed', 'failed', 'rejected', 'hold')"
    assert MOVEMENT_TYPE_CHECK == (
        "movement_type IN ('receive', 'transfer', 'issue', 'consume', "
        "'adjustment', 'return', 'produce', 'waste', 'shipment')"
    )


def test_enum_members_match_the_stored_vocabulary():
    assert tuple(status.value for status in StockBatchQcStatus) == EXPECTED_QC_STATUSES
    assert tuple(kind.value for kind in StockMovementType) == EXPECTED_MOVEMENT_TYPES


def test_service_accepts_exactly_the_qc_vocabulary():
    assert stock_service._STOCK_BATCH_QC_STATUSES == frozenset(EXPECTED_QC_STATUSES)


def test_request_contract_is_really_enum_typed():
    """The field annotation IS the canonical enum class, not a str alias."""
    field = StockBatchIn.model_fields["qc_status"]
    assert field.annotation is StockBatchQcStatus


def test_omitted_qc_keeps_the_canonical_member():
    payload = StockBatchIn(item_id=1, batch_no="OP01", quantity=1, unit="kg", warehouse_id=1)
    assert payload.qc_status is StockBatchQcStatus.PENDING


@pytest.mark.parametrize("value", EXPECTED_QC_STATUSES)
def test_supplied_qc_becomes_the_same_canonical_member(value):
    payload = StockBatchIn(
        item_id=1, batch_no="OP01", quantity=1, unit="kg", warehouse_id=1, qc_status=value,
    )
    assert payload.qc_status is StockBatchQcStatus(value)


def test_raw_qc_input_is_normalized_before_enum_parsing():
    payload = StockBatchIn(
        item_id=1, batch_no="OP01", quantity=1, unit="kg", warehouse_id=1, qc_status="  PASSED  ",
    )
    assert payload.qc_status is StockBatchQcStatus.PASSED


def test_invalid_qc_is_rejected_by_the_request_contract():
    with pytest.raises(ValidationError):
        StockBatchIn(
            item_id=1, batch_no="OP01", quantity=1, unit="kg", warehouse_id=1, qc_status="released",
        )


def test_null_qc_is_rejected_by_the_request_contract():
    with pytest.raises(ValidationError):
        StockBatchIn(
            item_id=1, batch_no="OP01", quantity=1, unit="kg", warehouse_id=1, qc_status=None,
        )


def test_serialized_json_keeps_the_public_value():
    payload = StockBatchIn(item_id=1, batch_no="OP01", quantity=1, unit="kg", warehouse_id=1)
    assert payload.model_dump(mode="json")["qc_status"] == "pending"
    assert payload.model_dump()["qc_status"] is StockBatchQcStatus.PENDING


def test_openapi_schema_exposes_the_closed_vocabulary():
    schema = StockBatchIn.model_json_schema()
    field = schema["properties"]["qc_status"]
    if "$ref" in field:
        target = schema
        for component in field["$ref"].removeprefix("#/").split("/"):
            target = target[component]
        field = target
    assert field.get("enum") == list(EXPECTED_QC_STATUSES)


def test_update_contract_keeps_omitted_and_null_semantics():
    omitted = StockBatchUpdate(item_id=1)
    assert omitted.qc_status is None
    assert "qc_status" not in omitted.model_dump(exclude_unset=True)

    explicit_null = StockBatchUpdate(item_id=1, qc_status=None)
    assert explicit_null.qc_status is None
    assert explicit_null.model_dump(exclude_unset=True)["qc_status"] is None

    supplied = StockBatchUpdate(item_id=1, qc_status="failed")
    assert supplied.qc_status is StockBatchQcStatus.FAILED

    raw = StockBatchUpdate(item_id=1, qc_status=" HOLD ")
    assert raw.qc_status is StockBatchQcStatus.HOLD


def test_update_contract_rejects_an_unsupported_value():
    with pytest.raises(ValidationError):
        StockBatchUpdate(item_id=1, qc_status="released")


# ===== Behaviour =====

def _receipt_payload(**overrides) -> dict:
    with SessionLocal() as db:
        item_id = db.query(Item.id).filter(
            Item.category == "fabric", Item.is_active.is_(True),
        ).order_by(Item.id).first()[0]
        unit = db.query(Item.unit).filter(Item.id == item_id).scalar() or "kg"
        warehouse_id = db.query(Warehouse.id).filter(
            Warehouse.type == "fabric_storage",
        ).order_by(Warehouse.id).first()[0]
    payload = {
        "item_id": item_id,
        "batch_no": f"OP01-SCHEMA-{uuid4().hex}",
        "quantity": 3,
        "unit": unit,
        "cost_per_unit": 1.25,
        "warehouse_id": warehouse_id,
    }
    payload.update(overrides)
    return payload


def test_receipt_persists_the_batch_and_the_receive_movement(client, auth_headers):
    payload = _receipt_payload()
    response = client.post("/api/inventory/receive", headers=auth_headers, json=payload)
    assert response.status_code == 201, response.text
    body = response.json()

    with SessionLocal() as db:
        batch = db.get(StockBatch, body["id"])
        assert batch is not None
        assert batch.batch_no == payload["batch_no"]
        assert batch.item_id == payload["item_id"]
        assert batch.warehouse_id == payload["warehouse_id"]
        assert float(batch.quantity) == 3
        assert batch.unit == payload["unit"]
        assert float(batch.cost_per_unit) == 1.25
        assert batch.qc_status == "pending"
        # Untouched columns keep their column defaults.
        assert batch.internal_batch_no is None
        assert batch.archived_at is None
        assert batch.archived_by is None
        assert batch.received_date is not None

        movements = db.query(StockMovement).filter(
            StockMovement.batch_id == batch.id,
            StockMovement.reference_type == "StockBatch",
        ).all()
        assert len(movements) == 1
        movement = movements[0]
        assert movement.movement_type == "receive"
        assert movement.item_id == payload["item_id"]
        assert movement.to_warehouse_id == payload["warehouse_id"]
        assert movement.from_warehouse_id is None
        assert float(movement.quantity) == 3
        assert movement.unit == payload["unit"]
        assert movement.reference_id == batch.id
        assert movement.created_by is not None


def test_receipt_writes_the_audit_entry_in_the_same_transaction(client, auth_headers):
    payload = _receipt_payload()
    response = client.post("/api/inventory/receive", headers=auth_headers, json=payload)
    assert response.status_code == 201, response.text
    batch_id = response.json()["id"]

    with SessionLocal() as db:
        audits = db.query(AuditLog).filter(
            AuditLog.entity_type == "StockBatch",
            AuditLog.entity_id == batch_id,
            AuditLog.action == "receive",
        ).all()
        assert len(audits) == 1
        assert audits[0].new_value_json["batch_no"] == payload["batch_no"]
        assert float(audits[0].new_value_json["qty"]) == 3


def test_receipt_stores_the_idempotency_record(client, auth_headers):
    payload = _receipt_payload()
    key = f"op01-{uuid4().hex}"
    response = client.post(
        "/api/inventory/receive",
        headers={**auth_headers, "Idempotency-Key": key},
        json=payload,
    )
    assert response.status_code == 201, response.text

    with SessionLocal() as db:
        records = db.query(IdempotencyRecord).filter(
            IdempotencyRecord.key == key,
        ).all()
        assert len(records) == 1
        # The stored scope is identity-scoped: "<scope>:v2:<64-hex>".
        scope = records[0].scope
        assert scope.startswith("inventory.receive:v2:")
        assert re.fullmatch(r"inventory\.receive:v2:[0-9a-f]{64}", scope), scope
        assert records[0].status_code == 201


def test_receipt_rejects_an_unknown_qc_status_without_writing(client, auth_headers):
    """Deliberate change: the typed request contract answers 422, not 400.

    The guard that matters is unchanged - an unsupported QC value writes
    nothing. The status code moved because the request is now validated
    against the canonical enum before the service runs.
    """
    with SessionLocal() as db:
        before = (
            db.query(StockBatch).count(),
            db.query(StockMovement).count(),
            db.query(AuditLog).count(),
        )

    response = client.post(
        "/api/inventory/receive",
        headers=auth_headers,
        json=_receipt_payload(qc_status="released"),
    )
    assert response.status_code == 422, response.text
    errors = response.json()["detail"]
    assert errors[0]["loc"][-1] == "qc_status"

    with SessionLocal() as db:
        assert (
            db.query(StockBatch).count(),
            db.query(StockMovement).count(),
            db.query(AuditLog).count(),
        ) == before


def test_receipt_keeps_the_missing_warehouse_precedence(client, auth_headers):
    response = client.post(
        "/api/inventory/receive",
        headers=auth_headers,
        json=_receipt_payload(warehouse_id=2_147_483_647),
    )
    assert response.status_code == 404, response.text
    assert response.json() == {"detail": "Warehouse not found"}


@pytest.mark.parametrize("qc_status", EXPECTED_QC_STATUSES)
def test_receipt_still_accepts_every_qc_state(client, auth_headers, qc_status):
    response = client.post(
        "/api/inventory/receive",
        headers=auth_headers,
        json=_receipt_payload(qc_status=qc_status),
    )
    assert response.status_code == 201, response.text
    assert response.json()["qc_status"] == qc_status
    with SessionLocal() as db:
        assert db.get(StockBatch, response.json()["id"]).qc_status == qc_status


# ===== Idempotency fingerprint =====

def _pre_enum_fingerprint_payload(body: dict) -> dict:
    """The payload the request contract hashed before `qc_status` became an enum.

    The pre-enum contract was this same model with a free-form string
    `qc_status`, so every other field is hashed exactly as it is now and only
    the QC text differs: the text the client sent, not the normalized member.
    """
    payload = StockBatchIn.model_validate(body).model_dump(mode="json")
    payload["qc_status"] = body.get("qc_status", "pending")
    if payload.get("length_m") is None:
        payload.pop("length_m", None)
    if not payload.get("roll_lengths_m"):
        payload.pop("roll_lengths_m", None)
    return payload


def test_fingerprint_payload_keeps_the_request_text_of_qc_status():
    payload = StockBatchIn(
        item_id=1, batch_no="OP01", quantity=1, unit="kg", warehouse_id=1, qc_status="  PASSED  ",
    )
    fingerprint_payload = stock_service._stock_batch_fingerprint_payload(payload)
    assert fingerprint_payload["qc_status"] == "  PASSED  "
    # The contract still exposes the canonical value.
    assert payload.model_dump(mode="json")["qc_status"] == "passed"


def test_fingerprint_payload_of_an_omitted_qc_status_is_the_canonical_default():
    payload = StockBatchIn(item_id=1, batch_no="OP01", quantity=1, unit="kg", warehouse_id=1)
    fingerprint_payload = stock_service._stock_batch_fingerprint_payload(payload)
    assert fingerprint_payload["qc_status"] == "pending"


@pytest.mark.parametrize("raw_qc", ["passed", "  PASSED  ", "Passed"])
def test_receipt_hash_keeps_the_pre_enum_request_representation(client, auth_headers, raw_qc):
    body = _receipt_payload(qc_status=raw_qc)
    key = f"op01-fingerprint-{uuid4().hex}"
    response = client.post(
        "/api/inventory/receive",
        headers={**auth_headers, "Idempotency-Key": key},
        json=body,
    )
    assert response.status_code == 201, response.text

    with SessionLocal() as db:
        record = db.query(IdempotencyRecord).filter_by(key=key).one()
        assert record.request_hash == request_fingerprint(_pre_enum_fingerprint_payload(body))


def test_receipt_retry_replays_the_saved_result_of_a_padded_qc_status(client, auth_headers):
    body = _receipt_payload(qc_status="  PASSED  ")
    key = f"op01-replay-{uuid4().hex}"
    headers = {**auth_headers, "Idempotency-Key": key}
    created = client.post("/api/inventory/receive", headers=headers, json=body)
    assert created.status_code == 201, created.text

    with SessionLocal() as db:
        before = (
            db.query(StockBatch).count(),
            db.query(StockMovement).count(),
            db.query(AuditLog).count(),
        )

    replay = client.post("/api/inventory/receive", headers=headers, json=body)
    assert replay.status_code == 201, replay.text
    assert replay.json() == created.json()

    with SessionLocal() as db:
        assert (
            db.query(StockBatch).count(),
            db.query(StockMovement).count(),
            db.query(AuditLog).count(),
        ) == before

    changed = client.post(
        "/api/inventory/receive",
        headers=headers,
        json={**body, "quantity": body["quantity"] + 1},
    )
    assert changed.status_code == 409, changed.text
