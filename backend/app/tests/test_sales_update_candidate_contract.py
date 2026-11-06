"""Candidate contract for the sales-order header edit.

The frozen baseline assertions stay untouched in `test_sales_update_old_behavior.py`
and `test_sales_status_patch_guard.py`. This file states the candidate contract:
the canonical status vocabulary, the deliberate validation delta and the typed
service result.
"""
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.core.signing import verify_path
from app.db.session import SessionLocal, engine
from app.libs.dto.sales.sales_order_output import SalesOrderOut
from app.libs.dto.sales.sales_order_update import SalesOrderUpdate
from app.libs.enums.sales import SalesOrderStatus
from app.models.sales import orders_service as sales
from app.schemas import AuditLog, SalesOrder, User
from app.tests.test_sales_update_old_behavior import assert_physical_unchanged, seed


def _refs(node):
    """Every $ref target reachable from an OpenAPI schema node."""
    found = set()
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            found.add(ref)
        for value in node.values():
            found |= _refs(value)
    elif isinstance(node, list):
        for value in node:
            found |= _refs(value)
    return found


def test_the_service_returns_a_typed_sales_order_out():
    ids = seed(SessionLocal)
    with SessionLocal() as db:
        actor = db.get(User, ids[1])
        result = sales.update_sales_order(ids[0], SalesOrderUpdate(notes="typed"), db, actor)
    assert isinstance(result, SalesOrderOut)
    assert result.status is SalesOrderStatus.RESERVED
    assert result.notes == "typed"
    assert not hasattr(result, "items")


@pytest.mark.parametrize("value", ["bogus", "", "DRAFT", "in production"])
def test_an_unknown_status_value_is_a_validation_error(client, auth_headers, value):
    """The one deliberate delta: an unknown status is refused by the DTO, not by the service."""
    ids = seed(SessionLocal)
    with SessionLocal() as db:
        audit_count = db.query(AuditLog).count()
    response = client.patch(
        f"/api/sales-orders/{ids[0]}", headers=auth_headers,
        json={"status": value, "notes": "must not save"},
    )
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert any(d.get("loc", [])[-1:] == ["status"] for d in detail), detail
    with SessionLocal() as db:
        row = db.get(SalesOrder, ids[0])
        assert row.notes == "old notes"
        assert row.status == "reserved"
        assert db.query(AuditLog).count() == audit_count


def test_a_valid_but_different_status_is_still_refused(client, auth_headers):
    ids = seed(SessionLocal)
    with SessionLocal() as db:
        audit_count = db.query(AuditLog).count()
    response = client.patch(
        f"/api/sales-orders/{ids[0]}", headers=auth_headers,
        json={"status": "confirmed", "notes": "must not save"},
    )
    assert response.status_code == 409, response.text
    with SessionLocal() as db:
        row = db.get(SalesOrder, ids[0])
        assert row.notes == "old notes"
        assert row.status == "reserved"
        assert db.query(AuditLog).count() == audit_count


def test_an_explicit_null_status_is_still_refused(client, auth_headers):
    ids = seed(SessionLocal)
    with SessionLocal() as db:
        audit_count = db.query(AuditLog).count()
    response = client.patch(
        f"/api/sales-orders/{ids[0]}", headers=auth_headers,
        json={"status": None, "notes": "must not save"},
    )
    assert response.status_code == 409, response.text
    with SessionLocal() as db:
        row = db.get(SalesOrder, ids[0])
        assert row.notes == "old notes"
        assert db.query(AuditLog).count() == audit_count


def test_the_unchanged_status_is_accepted_and_never_written_back(client, auth_headers):
    ids = seed(SessionLocal)
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())

    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = client.patch(
            f"/api/sales-orders/{ids[0]}", headers=auth_headers,
            json={"status": "reserved", "notes": "edited"},
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "reserved"
    writes = [s for s in statements if s.startswith("update sales_orders")]
    assert len(writes) == 1, writes
    assert "status=" not in writes[0].replace(" ", "")
    with SessionLocal() as db:
        row = db.get(SalesOrder, ids[0])
        assert row.status == "reserved"
        assert row.notes == "edited"


def test_omitted_fields_stay_untouched(client, auth_headers):
    ids = seed(SessionLocal)
    response = client.patch(
        f"/api/sales-orders/{ids[0]}", headers=auth_headers, json={"notes": "only notes"},
    )
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        row = db.get(SalesOrder, ids[0])
        assert row.notes == "only notes"
        assert row.customer_id == ids[2]
        assert row.deadline is not None
        assert row.printing_instructions == "old instructions"
        assert row.printing_attachments[0]["file_url"] == "/storage/sales-order-files/old.png"


def test_an_explicit_null_clears_the_nullable_headers(client, auth_headers):
    ids = seed(SessionLocal)
    response = client.patch(
        f"/api/sales-orders/{ids[0]}", headers=auth_headers,
        json={"customer_id": None, "deadline": None, "printing_instructions": None,
              "printing_attachments": None, "notes": None},
    )
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        row = db.get(SalesOrder, ids[0])
        assert row.customer_id is None
        assert row.deadline is None
        assert row.printing_instructions is None
        assert row.printing_attachments == []
        assert row.notes is None


def test_unknown_fields_are_ignored(client, auth_headers):
    ids = seed(SessionLocal)
    response = client.patch(
        f"/api/sales-orders/{ids[0]}", headers=auth_headers,
        json={"notes": "edited", "items": [{"quantity": 99}], "total_amount": 999,
              "order_type": "client_order", "id": 4242},
    )
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        row = db.get(SalesOrder, ids[0])
        assert row.notes == "edited"
        assert row.total_amount == Decimal("40.00")
        assert row.order_type == "branded_stock_sale"
        assert row.id == ids[0]
        assert_physical_unchanged(db, ids)


def test_the_response_keeps_the_wire_shape_and_has_no_items(client, auth_headers):
    ids = seed(SessionLocal)
    response = client.patch(
        f"/api/sales-orders/{ids[0]}", headers=auth_headers, json={"notes": "edited"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "items" not in body
    assert body["customer"] == {"id": ids[2], "name": "Original edit customer"}
    assert body["status"] == "reserved"
    assert body["order_type"] == "branded_stock_sale"
    url = urlsplit(body["printing_attachments"][0]["file_url"])
    query = parse_qs(url.query)
    assert verify_path(url.path, query["exp"][0], query["sig"][0])


def test_header_edits_stay_allowed_for_a_shipped_order(client, auth_headers):
    ids = seed(SessionLocal, status="shipped")
    response = client.patch(
        f"/api/sales-orders/{ids[0]}", headers=auth_headers, json={"notes": "after delivery"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "shipped"
    with SessionLocal() as db:
        assert db.get(SalesOrder, ids[0]).notes == "after delivery"


def test_the_openapi_status_field_is_the_canonical_enum(client):
    spec = client.get("/openapi.json").json()
    status_schema = spec["components"]["schemas"]["SalesOrderUpdate"]["properties"]["status"]
    assert "#/components/schemas/SalesOrderStatus" in _refs(status_schema)
    values = spec["components"]["schemas"]["SalesOrderStatus"]["enum"]
    assert "draft" in values and "reserved" in values and "shipped" in values
    assert "bogus" not in values


def test_the_confirmation_command_is_still_separate(client, auth_headers):
    ids = seed(SessionLocal, status="draft")
    response = client.post(f"/api/sales-orders/{ids[0]}/confirm", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "confirmed"


def test_a_missing_order_is_404(client, auth_headers):
    response = client.patch(f"/api/sales-orders/{uuid4().int % 10 ** 9}", headers=auth_headers,
                            json={"notes": "edited"})
    assert response.status_code == 404, response.text
