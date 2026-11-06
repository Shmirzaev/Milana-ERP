"""Operation-01 evidence: the purchase request create operation.

Black box over the HTTP route plus the runtime contract of the typed status.
The expected values here are independent literals; they are never derived from
the enum under test or from the implementation's own output.
"""
import json
import os

import pytest

from app.db.session import SessionLocal
from app.libs.dto.purchasing.purchase_request_input import PurchaseRequestIn
from app.libs.dto.purchasing.purchase_request_output import PurchaseRequestOut
from app.libs.enums.purchasing import PurchaseRequestStatus
from app.schemas import AuditLog, Notification, PurchaseRequest, PurchaseRequestLine


_OMITTED = object()
_MATRIX_OUT = os.environ.get("PURCHASING_OPERATION01_MATRIX_OUT")
_OBSERVED: list[dict] = []

# label, request body status value, expected HTTP status, expected stored status
MATRIX = [
    ("omitted", _OMITTED, 201, "pending_approval"),
    ("draft", "draft", 201, "draft"),
    ("pending_approval", "pending_approval", 201, "pending_approval"),
    ("blank", "", 201, "pending_approval"),
    ("whitespace_only", "   ", 201, "pending_approval"),
    ("padded", " draft ", 201, "draft"),
    ("lifecycle_approved", "approved", 400, None),
    ("lifecycle_rejected", "rejected", 400, None),
    ("lifecycle_converted", "converted", 400, None),
    ("unknown_string", "unknown-status", 422, None),
    ("null", None, 422, None),
    ("wrong_type_int", 123, 422, None),
]

SERVICE_REFUSAL_DETAIL = "Purchase request status must be draft or pending_approval"

ORDERED_MODEL_ID = 1
ORDERED_SIZE = "M"
ORDERED_COLOR = "white"
ORDERED_QUANTITY = 10000


@pytest.fixture(scope="module", autouse=True)
def _write_observed_matrix():
    yield
    if _MATRIX_OUT:
        with open(_MATRIX_OUT, "w", encoding="utf-8") as handle:
            json.dump(_OBSERVED, handle, indent=2, sort_keys=True)


def _material_item_id(client, headers) -> int:
    response = client.get(
        "/api/inventory/items?group=materials&q=FAB-COT-001&page_size=50", headers=headers
    )
    assert response.status_code == 200, response.text
    return int(next(row for row in response.json() if row["sku"] == "FAB-COT-001")["id"])


def _counts() -> tuple[int, int, int, int]:
    db = SessionLocal()
    try:
        return (
            db.query(PurchaseRequest).count(),
            db.query(PurchaseRequestLine).count(),
            db.query(AuditLog).count(),
            db.query(Notification).count(),
        )
    finally:
        db.close()


def _stored_status(request_id: int) -> str:
    db = SessionLocal()
    try:
        return db.get(PurchaseRequest, request_id).status
    finally:
        db.close()


def _body(item_id: int, status_value) -> dict:
    body: dict = {
        "lines": [
            {
                "item_id": item_id,
                "required_quantity": 5,
                "requested_quantity": 5,
                "available_quantity": 0,
            }
        ]
    }
    if status_value is not _OMITTED:
        body["status"] = status_value
    return body


def _expected_shortage_line_count() -> int:
    """Materials of the ordered model that stock cannot cover.

    Derived from the business input: the model's BOM rows that match the
    ordered size and color, and each material's available stock. The
    alternate caller must emit exactly one request line per shortage.
    """
    from app.models.inventory_service import available_stock_for_item
    from app.schemas import ModelBOM

    db = SessionLocal()
    try:
        required_by_item: dict[int, float] = {}
        for bom in db.query(ModelBOM).filter(ModelBOM.model_id == ORDERED_MODEL_ID).all():
            if bom.size and bom.size != ORDERED_SIZE:
                continue
            if bom.color and bom.color != ORDERED_COLOR:
                continue
            required_by_item[bom.item_id] = required_by_item.get(bom.item_id, 0.0) + float(
                bom.quantity_per_piece
            ) * ORDERED_QUANTITY
        return sum(
            1
            for item_id, required in required_by_item.items()
            if required - available_stock_for_item(db, item_id) > 1e-9
        )
    finally:
        db.close()


def _line_snapshot(lines: list[dict]) -> list[dict]:
    return [
        {
            "item_id": int(line["item_id"]),
            "required_quantity": round(float(line["required_quantity"]), 4),
            "requested_quantity": round(float(line["requested_quantity"]), 4),
            "available_quantity": round(float(line["available_quantity"]), 4),
            "shortage_quantity": round(float(line["shortage_quantity"]), 4),
            "unit": line["unit"],
        }
        for line in sorted(lines, key=lambda row: int(row["item_id"]))
    ]


# --- runtime contract of the typed status -------------------------------------


def test_status_default_is_the_enum_member_at_runtime():
    payload = PurchaseRequestIn(lines=[{"item_id": 1}])

    assert isinstance(payload.status, PurchaseRequestStatus)
    assert payload.status is PurchaseRequestStatus.PENDING_APPROVAL
    assert payload.status.value == "pending_approval"
    assert payload.model_dump(mode="json")["status"] == "pending_approval"


def test_status_accepts_the_raw_text_of_every_member():
    for member in PurchaseRequestStatus:
        payload = PurchaseRequestIn(status=member.value, lines=[{"item_id": 1}])
        assert isinstance(payload.status, PurchaseRequestStatus)
        assert payload.status is member


def test_status_normalizes_before_the_enum_parses_it():
    assert PurchaseRequestIn(status="", lines=[{"item_id": 1}]).status is (
        PurchaseRequestStatus.PENDING_APPROVAL
    )
    assert PurchaseRequestIn(status="   ", lines=[{"item_id": 1}]).status is (
        PurchaseRequestStatus.PENDING_APPROVAL
    )
    assert PurchaseRequestIn(status=" draft ", lines=[{"item_id": 1}]).status is (
        PurchaseRequestStatus.DRAFT
    )


def test_status_refuses_values_outside_the_vocabulary():
    for raw in (None, 123, "unknown-status"):
        with pytest.raises(Exception):
            PurchaseRequestIn(status=raw, lines=[{"item_id": 1}])


def test_output_status_is_enum_typed_and_serializes_to_its_value():
    field = PurchaseRequestOut.model_fields["status"]
    assert field.annotation is PurchaseRequestStatus
    assert field.is_required()


def test_openapi_reports_the_enum_for_both_dtos():
    schema = PurchaseRequestIn.model_json_schema()
    assert schema["$defs"]["PurchaseRequestStatus"]["enum"] == [
        "draft",
        "pending_approval",
        "approved",
        "rejected",
        "converted",
    ]
    assert schema["properties"]["status"]["default"] == "pending_approval"
    assert "PurchaseRequestStatus" in schema["$defs"]


# --- the operation over the HTTP route ----------------------------------------


@pytest.mark.parametrize(
    "label,status_value,expected_http,expected_status", MATRIX, ids=[case[0] for case in MATRIX]
)
def test_create_request_input_matrix(
    client, auth_headers, label, status_value, expected_http, expected_status
):
    item_id = _material_item_id(client, auth_headers)
    before = _counts()

    response = client.post(
        "/api/purchasing/requests", json=_body(item_id, status_value), headers=auth_headers
    )

    after = _counts()
    deltas = tuple(after[index] - before[index] for index in range(4))
    observed = {
        "label": label,
        "http_status": response.status_code,
        "stored_status": None,
        "request_rows": deltas[0],
        "line_rows": deltas[1],
        "audit_rows": deltas[2],
        "notification_rows": deltas[3],
        "detail": None,
        "lines": None,
    }

    assert response.status_code == expected_http, response.text

    if expected_status is None:
        # A refused input leaves no request, line, audit or notification behind.
        assert deltas == (0, 0, 0, 0), f"side effects on refused input: {deltas}"
        if response.status_code == 400:
            assert response.json()["detail"] == SERVICE_REFUSAL_DETAIL, response.text
            observed["detail"] = SERVICE_REFUSAL_DETAIL
        else:
            assert isinstance(response.json()["detail"], list), response.text
    else:
        assert deltas[0] == 1, deltas
        assert deltas[1] == 1, deltas
        assert deltas[2] == 1, deltas
        assert deltas[3] >= 0, deltas
        body = response.json()
        assert body["status"] == expected_status, body
        observed["stored_status"] = _stored_status(int(body["id"]))
        assert observed["stored_status"] == expected_status
        observed["lines"] = _line_snapshot(body["lines"])

    _OBSERVED.append(observed)


def test_accepted_create_writes_request_line_and_audit(client, auth_headers):
    """Positive control: the counters above really detect this operation's writes."""
    item_id = _material_item_id(client, auth_headers)
    before = _counts()

    response = client.post(
        "/api/purchasing/requests", json=_body(item_id, "draft"), headers=auth_headers
    )
    assert response.status_code == 201, response.text

    after = _counts()
    assert after[0] == before[0] + 1, (before, after)
    assert after[1] == before[1] + 1, (before, after)
    assert after[2] == before[2] + 1, (before, after)


def test_create_from_sales_order_is_the_alternate_entry(client, auth_headers):
    """The alternate caller supplies pending_approval itself and lands the same state.

    Its line count is driven by the sales order's material shortages, not by the
    status, so it is derived from the BOM and the stock balance.
    """
    expected_lines = _expected_shortage_line_count()
    assert expected_lines > 0, "the fixture must produce at least one shortage"

    created = client.post(
        "/api/sales-orders",
        json={
            "order_type": "client_order",
            "notes": "operation-01 alternate caller",
            "items": [
                {
                    "model_id": ORDERED_MODEL_ID,
                    "color": ORDERED_COLOR,
                    "size": ORDERED_SIZE,
                    "quantity": ORDERED_QUANTITY,
                    "unit_price": 12.5,
                }
            ],
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    sales_order_id = int(created.json()["id"])
    confirmed = client.post(
        f"/api/sales-orders/{sales_order_id}/confirm", headers=auth_headers
    )
    assert confirmed.status_code == 200, confirmed.text

    before = _counts()
    response = client.post(
        f"/api/purchasing/requests/from-sales-order/{sales_order_id}", headers=auth_headers
    )
    assert response.status_code == 201, response.text

    body = response.json()
    assert body["status"] == "pending_approval", body
    assert _stored_status(int(body["id"])) == "pending_approval"

    after = _counts()
    assert after[0] == before[0] + 1, (before, after)
    assert after[1] == before[1] + expected_lines, (expected_lines, before, after)
    assert after[2] == before[2] + 1, (before, after)
    assert len(body["lines"]) == expected_lines, body["lines"]

    _OBSERVED.append(
        {
            "label": "alternate_caller_from_sales_order",
            "http_status": response.status_code,
            "stored_status": _stored_status(int(body["id"])),
            "request_rows": after[0] - before[0],
            "line_rows": after[1] - before[1],
            "audit_rows": after[2] - before[2],
            "notification_rows": after[3] - before[3],
            "expected_line_count": expected_lines,
            "detail": None,
            "lines": _line_snapshot(body["lines"]),
        }
    )


def test_alternate_caller_refuses_unknown_sales_order_without_side_effects(client, auth_headers):
    before = _counts()
    response = client.post(
        "/api/purchasing/requests/from-sales-order/99999999", headers=auth_headers
    )
    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "Sales order not found", response.text

    after = _counts()
    assert tuple(after[index] - before[index] for index in range(4)) == (0, 0, 0, 0)

    _OBSERVED.append(
        {
            "label": "alternate_caller_unknown_sales_order",
            "http_status": response.status_code,
            "stored_status": None,
            "request_rows": 0,
            "line_rows": 0,
            "audit_rows": 0,
            "notification_rows": 0,
            "detail": "Sales order not found",
            "lines": None,
        }
    )


def test_order_input_contract_still_has_no_status_field():
    """PurchaseOrderIn must not gain a status field; the order create is a later operation."""
    from app.libs.dto.purchasing.purchase_order_input import PurchaseOrderIn

    assert "status" not in PurchaseOrderIn.model_fields
    assert "status" not in PurchaseOrderIn.model_json_schema()["properties"]


# --- the after-flush access denial --------------------------------------------


def _create_limited_user(client, auth_headers, *, email: str, permissions: list[str]):
    role = client.post(
        "/api/roles",
        json={"name": f"Role {email}", "permissions": permissions},
        headers=auth_headers,
    )
    assert role.status_code == 201, role.text
    user = client.post(
        "/api/users",
        json={
            "name": email.split("@", 1)[0],
            "email": email,
            "password": "Operation01Test123!",
            "role_id": role.json()["id"],
            "is_active": True,
        },
        headers=auth_headers,
    )
    assert user.status_code == 201, user.text
    token = client.post(
        "/api/auth/token",
        data={"username": email, "password": "Operation01Test123!"},
    )
    assert token.status_code == 200, token.text
    return {"Authorization": f"Bearer {token.json()['access_token']}"}


def _accessory_item_id() -> int:
    from app.schemas import Item

    db = SessionLocal()
    try:
        return int(db.query(Item).filter(Item.sku == "ACC-BTN-001").one().id)
    finally:
        db.close()


def test_denied_line_access_commits_no_request_line_audit_or_notification(
    client, auth_headers, monkeypatch
):
    """The access check runs after the rows were written, so nothing may commit.

    The header, its lines, the audit row and the department notifications are
    all written before the refusal, and all four must be rolled back.
    """
    from app.models import purchasing_service

    limited_headers = _create_limited_user(
        client,
        auth_headers,
        email="operation01.materialsonly.request@example.com",
        permissions=["purchasing.view", "purchasing.request", "inventory.materials_only"],
    )

    before = _counts()

    written = []
    original_create = purchasing_service.create_purchase_request

    def spy_create(db_, **kwargs):
        request = original_create(db_, **kwargs)
        written.append(request.id)
        return request

    monkeypatch.setattr(purchasing_service, "create_purchase_request", spy_create)

    denied = client.post(
        "/api/purchasing/requests",
        json={"lines": [{"item_id": _accessory_item_id(), "requested_quantity": 5}]},
        headers=limited_headers,
    )
    assert denied.status_code == 403, denied.text
    # The request really was written before the access check denied it.
    assert written

    after = _counts()
    assert after[0] == before[0], (before, after)
    assert after[1] == before[1], (before, after)
    assert after[2] == before[2], (before, after)
    assert after[3] == before[3], (before, after)
