"""Contract for the branded planning order operation.

Covers the enum-typed input contract, the typed output contract, the persisted
effect, the refusals and the input normalization of
``POST /api/planning/branded-orders``.

The status list filter keeps the old query semantics: an omitted parameter
selects ``open``, an explicit empty parameter selects every status, and a
noncanonical value is refused instead of becoming a new matching alias.

The alternate writer ``POST /api/planning/create-branded-production`` is not
migrated in this operation: it still writes the row itself with plain strings.
Its test here is a regression guard on the stored vocabulary only, so the
operation does not claim the alternate writer as a migrated consumer.

Expected values are written out independently of the implementation's vocabulary
definitions.
"""
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from types import SimpleNamespace
from typing import get_type_hints
from uuid import uuid4

from app.libs.dto.planning.branded_planning_order_input import BrandedPlanningOrderIn
from app.libs.dto.planning.branded_planning_order_output import (
    BrandedPlanningOrderOut,
    BrandedProductionOut,
)
from app.libs.enums.planning import (
    BrandedCuttingProgress,
    BrandedPlanningOrderStatus,
    BrandedPlanningOrderType,
)
from app.models.planning import branded_orders_service
from app.schemas import (
    AuditLog,
    BrandedPlanningOrder,
    Customer,
    Department,
    Model,
    ProductionOrder,
    User,
    WorkOrder,
)
from app.tests.conftest import TestSessionLocal


def _customer(name: str) -> int:
    with TestSessionLocal() as db:
        customer = Customer(name=name)
        db.add(customer)
        db.commit()
        return int(customer.id)


def _actor():
    with TestSessionLocal() as db:
        return db.query(User).filter_by(email="admin@example.com").one()


def _order_count() -> int:
    with TestSessionLocal() as db:
        return db.query(BrandedPlanningOrder).count()


def _audit_count() -> int:
    with TestSessionLocal() as db:
        return db.query(AuditLog).filter(
            AuditLog.entity_type == "BrandedPlanningOrder",
            AuditLog.action == "create",
        ).count()


def _stored_order(order_id: int) -> BrandedPlanningOrder:
    with TestSessionLocal() as db:
        return db.get(BrandedPlanningOrder, order_id)


def _planning_orders() -> list[BrandedPlanningOrder]:
    with TestSessionLocal() as db:
        return db.query(BrandedPlanningOrder).order_by(BrandedPlanningOrder.id).all()


# --- the input contract is enum typed ---------------------------------------


def test_omitted_ordered_for_type_is_the_enum_member():
    payload = BrandedPlanningOrderIn()

    assert isinstance(payload.ordered_for_type, BrandedPlanningOrderType)
    assert payload.ordered_for_type is BrandedPlanningOrderType.MILANA
    assert payload.ordered_for_type.value == "milana"


@pytest.mark.parametrize(
    "supplied, expected",
    [
        ("milana", "milana"),
        ("MILANA", "milana"),
        ("  Eco_Cotton  ", "eco_cotton"),
        ("Besttex", "besttex"),
        ("customer", "customer"),
    ],
)
def test_supplied_ordered_for_type_becomes_the_enum_member(supplied, expected):
    payload = BrandedPlanningOrderIn(ordered_for_type=supplied)

    assert isinstance(payload.ordered_for_type, BrandedPlanningOrderType)
    assert payload.ordered_for_type.value == expected


@pytest.mark.parametrize("supplied", [None, "", "   ", "not-a-party", 7])
def test_null_empty_and_unknown_ordered_for_type_are_refused(supplied):
    with pytest.raises(ValidationError):
        BrandedPlanningOrderIn(ordered_for_type=supplied)


def test_json_serialization_keeps_the_stored_value():
    assert BrandedPlanningOrderIn().model_dump(mode="json") == {
        "ordered_for_type": "milana",
        "customer_id": None,
        "notes": None,
    }


def test_openapi_declares_the_enum_for_the_ordered_for_type_and_the_status_filter():
    from app.main import app

    schema = app.openapi()

    body = schema["components"]["schemas"]["BrandedPlanningOrderIn"]["properties"]["ordered_for_type"]
    assert body["$ref"] == "#/components/schemas/BrandedPlanningOrderType"
    assert body["default"] == "milana"
    assert schema["components"]["schemas"]["BrandedPlanningOrderType"]["enum"] == [
        "customer",
        "milana",
        "eco_cotton",
        "besttex",
    ]

    status_param = next(
        param
        for param in schema["paths"]["/api/planning/branded-orders"]["get"]["parameters"]
        if param["name"] == "status"
    )
    assert status_param["schema"]["anyOf"][0]["$ref"] == "#/components/schemas/BrandedPlanningOrderStatus"
    assert status_param["schema"]["default"] == "open"
    assert schema["components"]["schemas"]["BrandedPlanningOrderStatus"]["enum"] == [
        "open",
        "closed",
        "cancelled",
    ]


# --- the output contract is enum typed --------------------------------------


def test_http_responses_publish_the_used_nested_enum_contract():
    from app.api.routes import planning
    from app.main import app

    schema = app.openapi()
    operation = schema["paths"]["/api/planning/branded-orders"]
    expected_ref = {"$ref": "#/components/schemas/BrandedPlanningOrderOut"}
    assert operation["post"]["responses"]["201"]["content"]["application/json"]["schema"] == expected_ref
    listed = operation["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert listed["type"] == "array"
    assert listed["items"] == expected_ref
    assert get_type_hints(planning.create_branded_order)["return"] is BrandedPlanningOrderOut
    assert get_type_hints(planning.list_branded_orders)["return"] == list[BrandedPlanningOrderOut]
    for name in ("BrandedPlanningOrderOut", "BrandedProductionOut"):
        assert schema["components"]["schemas"][name]["properties"]["cutting_status"] == {
            "$ref": "#/components/schemas/BrandedCuttingProgress"
        }
    assert schema["components"]["schemas"]["BrandedCuttingProgress"]["enum"] == [
        "not_started", "partial", "completed"
    ]


def test_http_response_validation_rejects_invalid_fixed_vocabulary(client, auth_headers, monkeypatch):
    from fastapi.exceptions import ResponseValidationError

    created = client.post("/api/planning/branded-orders", json={}, headers=auth_headers)
    assert created.status_code == 201
    invalid_output = created.json()
    invalid_output["status"] = "production-only-state"
    monkeypatch.setattr(branded_orders_service, "list_branded_orders", lambda *args: [invalid_output])
    with pytest.raises(ResponseValidationError):
        client.get("/api/planning/branded-orders", headers=auth_headers)


def test_the_operation_output_declares_the_canonical_enums():
    """The create and list routes share this payload, so it is part of the contract."""
    result_type = get_type_hints(branded_orders_service.branded_order_payload)["return"]

    assert result_type is not dict
    assert result_type is BrandedPlanningOrderOut

    hints = get_type_hints(result_type)
    assert hints["status"] is BrandedPlanningOrderStatus
    assert hints["ordered_for_type"] is BrandedPlanningOrderType


def test_the_output_contract_builds_enum_members_before_wire_serialization():
    row = SimpleNamespace(
        id=1,
        order_no="CONTRACT-1",
        ordered_for_type="milana",
        customer_id=None,
        ordered_for_name="Milana",
        status="open",
        notes=None,
        created_by=None,
        created_at=None,
        updated_at=None,
        production_orders=[],
    )

    result = branded_orders_service.branded_order_payload(row)

    assert result.status is BrandedPlanningOrderStatus.OPEN
    assert result.ordered_for_type is BrandedPlanningOrderType.MILANA
    assert result.cutting_status is BrandedCuttingProgress.NOT_STARTED
    assert result.productions == []
    assert result.production_count == 0
    assert result.total_quantity == 0
    assert result.cutting_status == "not_started"


def test_the_output_contract_keeps_the_wire_payload_keys():
    """The fourteen wire keys and their order are unchanged."""
    row = SimpleNamespace(
        id=1,
        order_no="CONTRACT-2",
        ordered_for_type="eco_cotton",
        customer_id=7,
        ordered_for_name="Eco Cotton",
        status="closed",
        notes="hello",
        created_by=3,
        created_at=None,
        updated_at=None,
        production_orders=[],
    )

    payload = branded_orders_service.branded_order_payload(row).model_dump(mode="json")

    assert list(payload.keys()) == [
        "id",
        "order_no",
        "ordered_for_type",
        "customer_id",
        "ordered_for_name",
        "status",
        "notes",
        "created_by",
        "created_at",
        "updated_at",
        "production_count",
        "total_quantity",
        "cutting_status",
        "productions",
    ]
    assert payload["ordered_for_type"] == "eco_cotton"
    assert payload["status"] == "closed"
    assert payload["customer_id"] == 7


# --- the used return contracts state what the functions actually return -----


def test_create_branded_order_declares_the_dto_it_actually_returns():
    """The declared contract must match the used result, not reshape it."""
    assert get_type_hints(branded_orders_service.create_branded_order)["return"] is (
        BrandedPlanningOrderOut
    )


def test_list_branded_orders_declares_the_list_of_dtos_it_actually_returns():
    assert get_type_hints(branded_orders_service.list_branded_orders)["return"] == (
        list[BrandedPlanningOrderOut]
    )


def test_the_create_operation_really_returns_the_declared_dto(client, auth_headers):
    response = client.post("/api/planning/branded-orders", json={}, headers=auth_headers)

    assert response.status_code == 201, response.text
    assert response.json()["status"] == "open"


# --- the derived cutting progress has its own canonical vocabulary ----------


def test_the_derived_cutting_progress_has_exactly_three_members():
    assert [member.value for member in BrandedCuttingProgress] == [
        "not_started",
        "partial",
        "completed",
    ]


def test_both_output_fields_declare_the_derived_cutting_progress_enum():
    parent_hints = get_type_hints(BrandedPlanningOrderOut)
    child_hints = get_type_hints(BrandedProductionOut)

    assert parent_hints["cutting_status"] is BrandedCuttingProgress
    assert child_hints["cutting_status"] is BrandedCuttingProgress


def _order_with_productions(count: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        order_no="CUT-1",
        ordered_for_type="milana",
        customer_id=None,
        ordered_for_name="Milana",
        status="open",
        notes=None,
        created_by=None,
        created_at=None,
        updated_at=None,
        production_orders=[
            SimpleNamespace(
                id=index + 1,
                order_no="CUT-1",
                production_no=f"PO-{index + 1}",
                model_id=1,
                planned_quantity=1,
                status="new",
            )
            for index in range(count)
        ],
    )


@pytest.mark.parametrize(
    "states, expected_parent",
    [
        ([], BrandedCuttingProgress.NOT_STARTED),
        ([BrandedCuttingProgress.NOT_STARTED], BrandedCuttingProgress.NOT_STARTED),
        ([BrandedCuttingProgress.PARTIAL], BrandedCuttingProgress.PARTIAL),
        ([BrandedCuttingProgress.COMPLETED], BrandedCuttingProgress.COMPLETED),
        (
            [BrandedCuttingProgress.COMPLETED, BrandedCuttingProgress.NOT_STARTED],
            BrandedCuttingProgress.PARTIAL,
        ),
        (
            [BrandedCuttingProgress.COMPLETED, BrandedCuttingProgress.COMPLETED],
            BrandedCuttingProgress.COMPLETED,
        ),
    ],
)
def test_the_cutting_projection_carries_enum_members(states, expected_parent):
    """The projection, the default branches and the aggregation all carry members."""
    order = _order_with_productions(len(states))
    cutting_by_id = {index + 1: state for index, state in enumerate(states)}

    result = branded_orders_service.branded_order_payload(order, {}, cutting_by_id, {})

    assert result.cutting_status is expected_parent
    assert [production.cutting_status for production in result.productions] == states
    assert result.model_dump(mode="json")["cutting_status"] == expected_parent.value


def test_a_production_without_a_cutting_entry_falls_back_to_the_member():
    order = _order_with_productions(1)

    result = branded_orders_service.branded_order_payload(order, {}, {}, {})

    assert result.productions[0].cutting_status is BrandedCuttingProgress.NOT_STARTED
    assert result.cutting_status is BrandedCuttingProgress.NOT_STARTED


def _cutting_fixture(states: list[str]) -> int:
    """One branded planning order whose productions carry the given cutting states."""
    with TestSessionLocal() as db:
        model = Model(code=f"CUT-{uuid4().hex[:8]}", name="Cutting Model", details_json={})
        db.add(model)
        db.flush()
        department = db.query(Department).filter_by(code="CUT").first()
        if department is None:
            department = Department(code="CUT", name="Cutting")
            db.add(department)
            db.flush()
        order = BrandedPlanningOrder(
            order_no=f"CUT-ORDER-{uuid4().hex[:8]}",
            ordered_for_type="milana",
            ordered_for_name="Milana",
            status="open",
        )
        db.add(order)
        db.flush()
        for index, state in enumerate(states):
            production = ProductionOrder(
                production_no=f"CUT-PROD-{uuid4().hex[:8]}-{index}",
                production_type="branded_stock",
                planning_order_id=order.id,
                model_id=model.id,
                planned_quantity=1,
                status="new",
            )
            db.add(production)
            db.flush()
            if state == "not_started":
                continue
            db.add(
                WorkOrder(
                    production_order_id=production.id,
                    department_id=department.id,
                    operation="cutting",
                    status="completed" if state == "completed" else "in_progress",
                    actual_output_qty=1 if state == "completed" else 0,
                )
            )
        db.commit()
        return order.id


def test_the_real_cutting_aggregation_produces_enum_members(client, auth_headers):
    """The stored-work-order aggregation keeps its rules and now yields members."""
    order_id = _cutting_fixture(["completed", "not_started"])

    response = client.get("/api/planning/branded-orders", headers=auth_headers)

    assert response.status_code == 200, response.text
    row = next(item for item in response.json() if item["id"] == order_id)
    assert row["cutting_status"] == "partial"
    assert sorted(production["cutting_status"] for production in row["productions"]) == [
        "completed",
        "not_started",
    ]


def test_the_mapped_class_keeps_its_stored_types_values_and_constraints():
    """The CHECK vocabulary is derived from the canonical enum, byte for byte."""
    from app.db.base import Base

    table = Base.metadata.tables["branded_planning_orders"]
    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in table.constraints
        if getattr(constraint, "sqltext", None) is not None
    }

    assert checks["ck_branded_planning_orders_ordered_for_type"] == (
        "ordered_for_type IN ('customer', 'milana', 'eco_cotton', 'besttex')"
    )
    assert checks["ck_branded_planning_orders_status"] == "status IN ('open', 'closed', 'cancelled')"
    assert str(table.c.ordered_for_type.type) == "VARCHAR(32)"
    assert str(table.c.status.type) == "VARCHAR(32)"
    assert str(table.c.status.default.arg) == "open"
    assert table.c.ordered_for_type.nullable is False
    assert table.c.status.nullable is False


# --- the persisted effect ---------------------------------------------------


def test_create_branded_order_defaults_to_milana_and_open(client, auth_headers):
    before_orders = _order_count()
    before_audits = _audit_count()

    response = client.post("/api/planning/branded-orders", json={}, headers=auth_headers)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["ordered_for_type"] == "milana"
    assert body["ordered_for_name"] == "Milana"
    assert body["status"] == "open"
    assert body["customer_id"] is None
    assert body["notes"] is None

    stored = _stored_order(int(body["id"]))
    assert stored is not None
    assert stored.ordered_for_type == "milana"
    assert stored.ordered_for_name == "Milana"
    assert stored.status == "open"
    assert stored.customer_id is None
    assert stored.notes is None
    assert stored.order_no == body["order_no"]
    assert _order_count() == before_orders + 1
    assert _audit_count() == before_audits + 1


def test_create_branded_order_normalizes_party_case_and_whitespace(client, auth_headers):
    response = client.post(
        "/api/planning/branded-orders",
        json={"ordered_for_type": "  Eco_Cotton  "},
        headers=auth_headers,
    )

    assert response.status_code == 201, response.text
    stored = _stored_order(int(response.json()["id"]))
    assert stored.ordered_for_type == "eco_cotton"
    assert stored.ordered_for_name == "Eco Cotton"


def test_create_branded_order_accepts_a_customer(client, auth_headers):
    customer_id = _customer("Branded Order Customer")

    response = client.post(
        "/api/planning/branded-orders",
        json={"ordered_for_type": "customer", "customer_id": customer_id},
        headers=auth_headers,
    )

    assert response.status_code == 201, response.text
    stored = _stored_order(int(response.json()["id"]))
    assert stored.ordered_for_type == "customer"
    assert stored.ordered_for_name == "Branded Order Customer"
    assert stored.customer_id == customer_id


def test_create_branded_order_ignores_a_customer_id_for_a_company_party(client, auth_headers):
    customer_id = _customer("Ignored For A Party")

    response = client.post(
        "/api/planning/branded-orders",
        json={"ordered_for_type": "besttex", "customer_id": customer_id},
        headers=auth_headers,
    )

    assert response.status_code == 201, response.text
    stored = _stored_order(int(response.json()["id"]))
    assert stored.ordered_for_type == "besttex"
    assert stored.ordered_for_name == "Besttex"
    assert stored.customer_id is None


def test_create_branded_order_normalizes_notes(client, auth_headers):
    response = client.post(
        "/api/planning/branded-orders",
        json={"notes": "  call the factory  "},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    stored = _stored_order(int(response.json()["id"]))
    assert stored.notes == "call the factory"

    blank = client.post(
        "/api/planning/branded-orders",
        json={"notes": "   "},
        headers=auth_headers,
    )
    assert blank.status_code == 201, blank.text
    stored_blank = _stored_order(int(blank.json()["id"]))
    assert stored_blank.notes is None


def test_create_branded_order_writes_one_create_audit_row(client, auth_headers):
    response = client.post("/api/planning/branded-orders", json={}, headers=auth_headers)
    assert response.status_code == 201, response.text
    order_id = int(response.json()["id"])

    with TestSessionLocal() as db:
        audits = db.query(AuditLog).filter(
            AuditLog.entity_type == "BrandedPlanningOrder",
            AuditLog.action == "create",
            AuditLog.entity_id == order_id,
        ).all()

    assert len(audits) == 1
    assert audits[0].new_value_json == {
        "order_no": response.json()["order_no"],
        "ordered_for": "Milana",
    }


def test_list_branded_orders_serves_a_model_without_images(client, auth_headers):
    """A model with no image yields null URLs, not a failed response."""
    with TestSessionLocal() as db:
        model = Model(code=f"NOIMG-{uuid4().hex[:8]}", name="No Image Model", details_json={})
        db.add(model)
        db.flush()
        order = BrandedPlanningOrder(
            order_no=f"NOIMG-ORDER-{uuid4().hex[:8]}",
            ordered_for_type="milana",
            ordered_for_name="Milana",
            status="open",
        )
        db.add(order)
        db.flush()
        production = ProductionOrder(
            production_no=f"NOIMG-PROD-{uuid4().hex[:8]}",
            production_type="branded_stock",
            planning_order_id=order.id,
            model_id=model.id,
            planned_quantity=12,
            status="new",
        )
        db.add(production)
        db.commit()
        order_id = order.id

    response = client.get("/api/planning/branded-orders", headers=auth_headers)

    assert response.status_code == 200, response.text
    row = next(item for item in response.json() if item["id"] == order_id)
    assert len(row["productions"]) == 1
    nested = row["productions"][0]
    assert nested["model"]["primary_image_url"] is None
    assert nested["model"]["fabric_image_url"] is None
    assert nested["model"]["variant_fabric"] is None
    assert nested["cutting_status"] == "not_started"
    assert nested["cutting_quantity"] == 0
    assert nested["cutting_departments"] == []


# --- refusals ---------------------------------------------------------------


@pytest.mark.parametrize("supplied", ["not-a-party", "", "   ", None])
def test_create_branded_order_refuses_an_unsupported_party_without_writing(
    client, auth_headers, supplied
):
    before_orders = _order_count()
    before_audits = _audit_count()

    response = client.post(
        "/api/planning/branded-orders",
        json={"ordered_for_type": supplied},
        headers=auth_headers,
    )

    assert response.status_code == 422, response.text
    assert _order_count() == before_orders
    assert _audit_count() == before_audits


def test_create_branded_order_refuses_a_missing_customer_without_writing(client, auth_headers):
    before_orders = _order_count()
    before_audits = _audit_count()

    response = client.post(
        "/api/planning/branded-orders",
        json={"ordered_for_type": "customer"},
        headers=auth_headers,
    )

    assert response.status_code == 404, response.text
    assert response.json() == {"detail": "Customer not found"}
    assert _order_count() == before_orders
    assert _audit_count() == before_audits


def test_create_branded_order_refuses_an_unknown_customer_without_writing(client, auth_headers):
    before_orders = _order_count()
    before_audits = _audit_count()

    response = client.post(
        "/api/planning/branded-orders",
        json={"ordered_for_type": "customer", "customer_id": 2147483647},
        headers=auth_headers,
    )

    assert response.status_code == 404, response.text
    assert response.json() == {"detail": "Customer not found"}
    assert _order_count() == before_orders
    assert _audit_count() == before_audits


def test_the_service_still_refuses_a_non_member_ordered_for_type():
    """The business guard stays for callers that bypass the input contract."""
    payload = BrandedPlanningOrderIn.model_construct(
        ordered_for_type="not-a-party", customer_id=None, notes=None
    )

    with TestSessionLocal() as db:
        actor = db.query(User).filter_by(email="admin@example.com").one()
        with pytest.raises(HTTPException) as refusal:
            branded_orders_service.create_branded_order(db, payload, actor)

    assert refusal.value.status_code == 400
    assert refusal.value.detail == "Choose Milana, Eco Cotton, Besttex, or a customer"


def test_create_branded_order_requires_authentication(client):
    assert client.post("/api/planning/branded-orders", json={}).status_code == 401


# --- the list filter and the alternate writer -------------------------------


def test_list_branded_orders_defaults_to_the_open_status(client, auth_headers):
    created = client.post("/api/planning/branded-orders", json={}, headers=auth_headers)
    assert created.status_code == 201, created.text

    default_list = client.get("/api/planning/branded-orders", headers=auth_headers)
    assert default_list.status_code == 200, default_list.text
    assert int(created.json()["id"]) in [row["id"] for row in default_list.json()]

    explicit = client.get(
        "/api/planning/branded-orders?status=open", headers=auth_headers
    )
    assert explicit.status_code == 200, explicit.text
    assert int(created.json()["id"]) in [row["id"] for row in explicit.json()]

    closed = client.get("/api/planning/branded-orders?status=closed", headers=auth_headers)
    assert closed.status_code == 200, closed.text
    assert int(created.json()["id"]) not in [row["id"] for row in closed.json()]


def test_list_branded_orders_service_accepts_the_status_member():
    """The service is given the enum member, not a raw string."""
    _orders_by_status()

    with TestSessionLocal() as db:
        rows = branded_orders_service.list_branded_orders(db, BrandedPlanningOrderStatus.OPEN)

    assert isinstance(rows, list)
    assert rows, "the seeded open orders must be returned"
    assert all(isinstance(row, BrandedPlanningOrderOut) for row in rows)
    assert all(row.status is BrandedPlanningOrderStatus.OPEN for row in rows)


def test_list_branded_orders_refuses_an_unsupported_status(client, auth_headers):
    response = client.get("/api/planning/branded-orders?status=not-a-status", headers=auth_headers)

    assert response.status_code == 422, response.text


def _orders_by_status() -> dict[str, int]:
    """One branded planning order per stored status."""
    created = {}
    with TestSessionLocal() as db:
        for status in ("open", "closed", "cancelled"):
            row = BrandedPlanningOrder(
                order_no=f"FILTER-{status}-{uuid4().hex[:8]}",
                ordered_for_type="milana",
                ordered_for_name="Milana",
                status=status,
            )
            db.add(row)
            db.flush()
            created[status] = row.id
        db.commit()
    return created


def test_list_branded_orders_with_an_explicit_empty_status_selects_every_status(
    client, auth_headers
):
    """`?status=` was the old no-filter sentinel, so it must keep selecting all."""
    created = _orders_by_status()

    response = client.get("/api/planning/branded-orders", params={"status": ""}, headers=auth_headers)

    assert response.status_code == 200, response.text
    returned = {row["id"] for row in response.json()}
    assert set(created.values()) <= returned


@pytest.mark.parametrize("supplied", ["OPEN", " open "])
def test_list_branded_orders_refuses_a_noncanonical_status(client, auth_headers, supplied):
    """The old query matched no row for these, so they must not become an alias."""
    response = client.get(
        "/api/planning/branded-orders", params={"status": supplied}, headers=auth_headers
    )

    assert response.status_code == 422, response.text


def test_create_branded_stock_production_stores_the_same_ordered_for_contract(client, auth_headers):
    """The alternate writer of the same row keeps the same stored vocabulary."""
    before_orders = _order_count()

    response = client.post(
        "/api/planning/create-branded-production",
        headers=auth_headers,
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "planned_quantity": 20,
            "items": [{"model_id": 1, "color": "white", "size": "M", "planned_quantity": 20}],
        },
    )

    assert response.status_code == 201, response.text
    assert _order_count() == before_orders + 1
    created = _planning_orders()[-1]
    assert created.ordered_for_type == "milana"
    assert created.ordered_for_name == "Milana"
    assert created.status == "open"
    assert created.customer_id is None


def test_branded_order_parties_still_serializes_plain_strings(client, auth_headers):
    response = client.get("/api/planning/branded-order-parties", headers=auth_headers)

    assert response.status_code == 200, response.text
    types = [row["type"] for row in response.json()["companies"]]
    assert types == ["milana", "eco_cotton", "besttex"]
    assert all(isinstance(value, str) and not isinstance(value, BrandedPlanningOrderType) for value in types)


# --- a failure after a real write leaves no partial effect -------------------


def _participant_counts() -> tuple[int, int]:
    with TestSessionLocal() as db:
        return (
            db.query(BrandedPlanningOrder).count(),
            db.query(AuditLog).filter(
                AuditLog.entity_type == "BrandedPlanningOrder",
                AuditLog.action == "create",
            ).count(),
        )


@pytest.mark.parametrize("hook", ["insert_branded_planning_order", "log_action"])
def test_a_failure_after_a_write_rolls_back_every_participant(
    client, auth_headers, monkeypatch, hook
):
    before = _participant_counts()
    original = getattr(branded_orders_service, hook)

    def fail_after_write(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected failure after the participant write")

    monkeypatch.setattr(branded_orders_service, hook, fail_after_write)
    with pytest.raises(RuntimeError, match="injected failure"):
        client.post(
            "/api/planning/branded-orders", headers=auth_headers, json={"notes": "rollback"}
        )

    assert _participant_counts() == before

    monkeypatch.setattr(branded_orders_service, hook, original)
    response = client.post(
        "/api/planning/branded-orders", headers=auth_headers, json={"notes": "rollback"}
    )

    assert response.status_code == 201, response.text
    assert _participant_counts() == (before[0] + 1, before[1] + 1)
