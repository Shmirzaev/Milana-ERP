from datetime import datetime
from pathlib import Path
import re
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.models import (
    AuditLog, CuttingRecord, Department, IdempotencyRecord, Item, ManualAccessoryIssue, Model, ModelBOM,
    PackagingRecord, ProductionOrder, SewingRecord, StockBatch, StockMovement, Warehouse, WorkOrder,
)
from app.schemas.inventory import AccessoryReturnIn
from app.services.inventory import accessory_issue_plan, accessory_issue_summary, current_stock_for_item
from app.tests.conftest import TestSessionLocal


@pytest.fixture
def accessory_case():
    with TestSessionLocal() as db:
        item = Item(sku="RETURN-BALANCE", name="Return balance accessory", category="accessory", unit="pcs")
        other_item = Item(sku="RETURN-OTHER", name="Other accessory", category="packaging", unit="pcs")
        model = Model(code="RETURN-MODEL", name="Return balance model")
        source = Warehouse(name="Return source", type="accessory_storage")
        destination = Warehouse(name="Return destination", type="accessory_storage")
        db.add_all([item, other_item, model, source, destination])
        db.flush()
        orders = [ProductionOrder(
            production_no=f"RETURN-PO-{index}", production_type="branded_stock",
            model_id=model.id, planned_quantity=10,
        ) for index in (1, 2)]
        db.add_all(orders)
        db.commit()
        return {
            "item_id": item.id, "other_item_id": other_item.id, "model_id": model.id,
            "po_id": orders[0].id, "other_po_id": orders[1].id,
            "source_id": source.id, "destination_id": destination.id,
        }


def _seed_issues(db, case, *, stock=8, manual=(4,), returned=3, po_id=None, item_id=None, unit="pcs"):
    po_id = po_id or case["po_id"]
    item_id = item_id or case["item_id"]
    if stock:
        db.add(StockMovement(
            movement_type="consume", item_id=item_id, quantity=stock, unit=unit,
            reference_type="ProductionOrder", reference_id=po_id,
        ))
    for index, quantity in enumerate(manual):
        db.add(ManualAccessoryIssue(
            production_order_id=po_id, item_id=item_id,
            item_sku=f"Historical alias {index}", item_name=f"Manual label {index}",
            quantity=quantity, unit=unit,
        ))
    if returned:
        db.add(StockMovement(
            movement_type="return", item_id=item_id, quantity=returned, unit=unit,
            reference_type="ProductionOrderAccessoryReturn", reference_id=po_id,
        ))
    db.flush()


@pytest.mark.parametrize(("stock", "manual", "returned"), [
    (8, (4,), 3), (8, (2, 2), 3), (0, (4, 3), 2), (8, (), 3), (0, (4,), 2),
])
def test_return_is_deducted_once_per_order_item_unit(accessory_case, stock, manual, returned):
    with TestSessionLocal() as db:
        _seed_issues(db, accessory_case, stock=stock, manual=manual, returned=returned)
        rows = accessory_issue_summary(db, production_order_id=accessory_case["po_id"])
        assert len(rows) == 1
        row = rows[0]
        assert row["issued_quantity"] == stock + sum(manual)
        assert row["returned_quantity"] == returned
        assert row["returnable_quantity"] == stock + sum(manual) - returned
        assert row["movement_count"] == int(stock > 0) + len(manual)
        paged_rows, total = accessory_issue_summary(
            db,
            production_order_id=accessory_case["po_id"],
            page=1,
            page_size=50,
            include_total=True,
            returnable_only=True,
        )
        expected = [
            legacy for legacy in rows
            if legacy["item_id"] > 0 and legacy["returnable_quantity"] > 1e-9
        ]
        assert total == len(expected)
        assert len(paged_rows) == len(expected)
        for actual, legacy in zip(paged_rows, expected, strict=True):
            for field in (
                "production_order_id", "item_id", "item_sku", "item_name", "category", "unit",
                "movement_count", "first_issued_at", "last_issued_at",
            ):
                assert actual[field] == legacy[field]
            for field in ("issued_quantity", "returned_quantity", "returnable_quantity"):
                assert float(actual[field]) == pytest.approx(legacy[field])


def test_accessory_issue_summary_projects_only_fields_used_from_movements_and_items(accessory_case):
    with TestSessionLocal() as db:
        _seed_issues(db, accessory_case, manual=(), returned=0)
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select") and (
                " from production_orders " in normalized
                or " from models " in normalized
                or (" from stock_movements " in normalized and " join items " in normalized)
            ):
                statements.append(normalized)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            rows = accessory_issue_summary(db, production_order_id=accessory_case["po_id"])
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert len(rows) == 1
    movement_selects = [
        statement for statement in statements if " from stock_movements " in statement and " join items " in statement
    ]
    assert len(movement_selects) == 1
    selected = movement_selects[0].split(" from stock_movements", 1)[0]
    assert "stock_movements.quantity" in selected
    assert "stock_movements.reference_type" in selected
    assert "items.sku" in selected
    assert "items.category" in selected
    assert "stock_movements.note" not in selected
    assert "items.composition_json" not in selected
    production_order_selects = [
        statement for statement in statements if " from production_orders " in statement
    ]
    model_selects = [statement for statement in statements if " from models " in statement]
    assert len(production_order_selects) == 1
    assert len(model_selects) == 1
    production_order_columns = production_order_selects[0].split(" from production_orders", 1)[0]
    model_columns = model_selects[0].split(" from models", 1)[0]
    assert "production_orders.production_no" in production_order_columns
    assert "sales_orders_1.order_no" in production_order_columns
    assert "production_orders.printing_instructions" not in production_order_columns
    assert "models.code" in model_columns
    assert "models.name" in model_columns
    assert "models.image_url" not in model_columns


def test_sql_return_picker_preserves_all_polymorphic_movement_references(accessory_case):
    case = accessory_case
    with TestSessionLocal() as db:
        department = Department(name="Accessory SQL test", code=f"AS{case['po_id']}")
        db.add(department)
        db.flush()
        work_orders = [
            WorkOrder(
                production_order_id=case["po_id"], department_id=department.id,
                operation=f"accessory-test-{index}",
            )
            for index in range(4)
        ]
        db.add_all(work_orders)
        db.flush()
        cutting = CuttingRecord(work_order_id=work_orders[1].id)
        sewing = SewingRecord(work_order_id=work_orders[2].id)
        packaging = PackagingRecord(work_order_id=work_orders[3].id)
        db.add_all([cutting, sewing, packaging])
        db.flush()
        refs = [
            ("ProductionOrder", case["po_id"], "pcs"),
            ("ProductionOrderAccessoryIssue", case["po_id"], "pcs"),
            ("WorkOrder", work_orders[0].id, ""),
            ("CuttingRecord", cutting.id, " "),
            ("SewingRecord", sewing.id, ""),
            ("PackagingRecord", packaging.id, " "),
        ]
        db.add_all([
            StockMovement(
                movement_type="consume", item_id=case["item_id"], quantity=2, unit=unit,
                reference_type=reference_type, reference_id=reference_id,
            )
            for reference_type, reference_id, unit in refs
        ])
        db.add(StockMovement(
            movement_type="return", item_id=case["item_id"], quantity=1, unit="pcs",
            reference_type="ProductionOrderAccessoryReturn", reference_id=case["po_id"],
        ))
        db.commit()

        legacy = accessory_issue_summary(db, production_order_id=case["po_id"])
        paged, total = accessory_issue_summary(
            db, production_order_id=case["po_id"], page=1, page_size=50,
            include_total=True, returnable_only=True,
        )
        expected = next(row for row in legacy if row["item_id"] == case["item_id"])
        assert total == 1
        assert len(paged) == 1
        for field in (
            "production_order_id", "item_id", "item_sku", "item_name", "category", "unit",
            "movement_count", "first_issued_at", "last_issued_at",
        ):
            assert paged[0][field] == expected[field]
        assert float(paged[0]["issued_quantity"]) == pytest.approx(12)
        assert float(paged[0]["returned_quantity"]) == pytest.approx(1)
        assert float(paged[0]["returnable_quantity"]) == pytest.approx(11)


def test_return_picker_normalizes_units_and_hides_noncanonical_unit_groups(accessory_case, client, auth_headers):
    case = accessory_case
    timestamp = datetime(2026, 9, 25, 12, 0, 0)
    with TestSessionLocal() as db:
        db.add_all([
            StockMovement(
                movement_type="consume", item_id=case["item_id"], quantity=1,
                unit=raw_unit, reference_type=reference_type, reference_id=reference_id,
                created_at=timestamp,
            )
            for raw_unit, reference_type, reference_id in [
                ("pcs", "ProductionOrder", case["po_id"]),
            ]
        ])
        # Use real indirect source references too; their blank unit resolves to
        # Item.unit exactly as it does in the legacy Python projection.
        department = Department(name="Accessory unit test", code=f"AU{case['po_id']}")
        db.add(department)
        db.flush()
        work_order = WorkOrder(
            production_order_id=case["po_id"], department_id=department.id, operation="unit-test",
        )
        db.add(work_order)
        db.flush()
        db.add(StockMovement(
            movement_type="consume", item_id=case["item_id"], quantity=1, unit=" ",
            reference_type="WorkOrder", reference_id=work_order.id, created_at=timestamp,
        ))
        db.add_all([
            ManualAccessoryIssue(
                production_order_id=case["po_id"], item_id=case["item_id"],
                item_sku="TIE-ITEM", item_name="Tie item", quantity=1, unit=unit, created_at=timestamp,
            )
            for unit in ("box", "set")
        ])
        db.commit()

        legacy_rows = accessory_issue_summary(db, production_order_id=case["po_id"])
        assert {row["unit"] for row in legacy_rows if row["item_id"] == case["item_id"]} == {"pcs", "box", "set"}
        picker_rows, total = accessory_issue_summary(
            db, production_order_id=case["po_id"], page=1, page_size=1,
            include_total=True, returnable_only=True,
        )
        next_page, next_total = accessory_issue_summary(
            db, production_order_id=case["po_id"], page=2, page_size=1,
            include_total=True, returnable_only=True,
        )
        assert total == next_total == 1
        assert len(picker_rows) == 1
        assert next_page == []
        assert picker_rows[0]["unit"] == "pcs"
        assert float(picker_rows[0]["issued_quantity"]) == pytest.approx(2)

    before = _state(case)
    response = client.post("/api/inventory/accessory-returns", headers=auth_headers, json={
        "production_order_id": case["po_id"], "item_id": case["item_id"], "batch_no": "NONCANONICAL-UNIT",
        "quantity": 1, "unit": "box", "warehouse_id": case["destination_id"], "qc_status": "passed",
    })
    assert response.status_code == 409
    assert "Return unit must match" in response.text
    assert _state(case) == before


def test_non_accessory_manual_rows_remain_legacy_visible_but_not_returnable(accessory_case, client, auth_headers):
    case = accessory_case
    with TestSessionLocal() as db:
        item = Item(sku="NOT-RETURNABLE", name="Fabric historical item", category="fabric", unit="kg")
        db.add(item)
        db.flush()
        item_id = item.id
        db.add(ManualAccessoryIssue(
            production_order_id=case["po_id"], item_id=item_id,
            item_sku=item.sku, item_name=item.name, quantity=3, unit="kg",
        ))
        db.commit()
        legacy_rows = accessory_issue_summary(db, production_order_id=case["po_id"])
        assert any(row["item_id"] == item_id and row["returnable_quantity"] == 3 for row in legacy_rows)
        picker_rows, picker_total = accessory_issue_summary(
            db, production_order_id=case["po_id"], page=1, page_size=50,
            include_total=True, returnable_only=True,
        )
        assert picker_total == 0
        assert all(row["item_id"] != item_id for row in picker_rows)

    before = _state(case)
    response = client.post("/api/inventory/accessory-returns", headers=auth_headers, json={
        "production_order_id": case["po_id"], "item_id": item_id, "batch_no": "NON-ACCESSORY-RETURN",
        "quantity": 1, "unit": "kg", "warehouse_id": case["destination_id"], "qc_status": "passed",
    })
    assert response.status_code == 400
    assert "Only accessory or packaging" in response.text
    assert _state(case) == before


def test_return_groups_keep_other_orders_items_units_and_itemless_labels_separate(accessory_case):
    case = accessory_case
    with TestSessionLocal() as db:
        _seed_issues(db, case)
        _seed_issues(db, case, stock=5, manual=(), returned=1, po_id=case["other_po_id"])
        _seed_issues(db, case, stock=7, manual=(1,), returned=2, item_id=case["other_item_id"])
        _seed_issues(db, case, stock=4, manual=(2,), returned=1, unit="box")
        for label, quantity in [("Untracked A", 2), ("Untracked B", 5)]:
            db.add(ManualAccessoryIssue(
                production_order_id=case["po_id"], item_name=label, quantity=quantity, unit="pcs",
            ))
        db.flush()
        rows = accessory_issue_summary(db)
        linked = {
            (row["production_order_id"], row["item_id"], row["unit"]):
                (row["issued_quantity"], row["returned_quantity"], row["returnable_quantity"])
            for row in rows if row["item_id"] in {case["item_id"], case["other_item_id"]}
        }
        assert linked == {
            (case["po_id"], case["item_id"], "pcs"): (12, 3, 9),
            (case["other_po_id"], case["item_id"], "pcs"): (5, 1, 4),
            (case["po_id"], case["other_item_id"], "pcs"): (8, 2, 6),
            (case["po_id"], case["item_id"], "box"): (6, 1, 5),
        }
        untracked = [row for row in rows if row["production_order_id"] == case["po_id"] and row["item_id"] == 0]
        assert {(row["item_name"], row["issued_quantity"], row["returnable_quantity"]) for row in untracked} == {
            ("Untracked A", 2, 2), ("Untracked B", 5, 5),
        }
        assert all(row["returned_quantity"] == 0 for row in untracked)


def test_return_picker_pages_exact_returnable_groups_beyond_legacy_cap(client, auth_headers, accessory_case):
    case = accessory_case
    with TestSessionLocal() as db:
        orders = [
            ProductionOrder(
                production_no=f"RETURN-PAGE-{index:04d}", production_type="branded_stock",
                model_id=case["model_id"], planned_quantity=10,
            )
            for index in range(401)
        ]
        db.add_all(orders)
        db.flush()
        first_order_id = orders[0].id
        db.add_all([
            ManualAccessoryIssue(
                production_order_id=order.id, item_id=case["item_id"], item_sku="PAGE-ACCESSORY",
                item_name="Paged return accessory", quantity=2, unit="pcs",
            )
            for order in orders
        ])
        db.add(ManualAccessoryIssue(
            production_order_id=first_order_id, item_id=case["other_item_id"], item_sku="SECOND-PAGE-ITEM",
            item_name="Second returnable group", quantity=1, unit="pcs",
        ))
        db.add(ManualAccessoryIssue(
            production_order_id=orders[0].id, item_name="Untracked cannot-return", quantity=4, unit="pcs",
        ))
        db.commit()

    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        normalized = " ".join(statement.lower().split())
        if "accessory_return_groups" in normalized:
            statements.append(normalized)

    engine = TestSessionLocal.kw["bind"]
    event.listen(engine, "before_cursor_execute", capture)
    try:
        first = client.get("/api/inventory/accessory-issues", headers=auth_headers, params={
            "page": 1, "page_size": 50, "include_total": "true", "returnable_only": "true",
        })
        last = client.get("/api/inventory/accessory-issues", headers=auth_headers, params={
            "page": 9, "page_size": 50, "include_total": "true", "returnable_only": "true",
        })
        order_page = client.get("/api/inventory/accessory-issues", headers=auth_headers, params={
            "page": 1, "page_size": 50, "include_total": "true", "returnable_only": "true", "orders_only": "true",
        })
        final_order_page = client.get("/api/inventory/accessory-issues", headers=auth_headers, params={
            "page": 9, "page_size": 50, "include_total": "true", "returnable_only": "true", "orders_only": "true",
        })
        filtered = client.get("/api/inventory/accessory-issues", headers=auth_headers, params={
            "page": 1, "page_size": 50, "include_total": "true", "returnable_only": "true", "q": "PAGE-ACCESSORY",
        })
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert first.status_code == last.status_code == 200
    assert first.json()["total"] == 402
    assert len(first.json()["rows"]) == 50
    assert first.json()["has_more"] is True
    assert len(last.json()["rows"]) == 2
    assert last.json()["has_more"] is False
    assert not ({row["production_order_id"] for row in first.json()["rows"]}
                & {row["production_order_id"] for row in last.json()["rows"]})
    assert all(row["item_id"] > 0 and row["returnable_quantity"] > 0 for row in first.json()["rows"])

    assert order_page.status_code == final_order_page.status_code == 200
    assert order_page.json()["total"] == 401
    assert len(order_page.json()["rows"]) == 50
    assert len({row["production_order_id"] for row in order_page.json()["rows"]}) == 50
    assert len(final_order_page.json()["rows"]) == 1

    assert filtered.status_code == 200
    assert filtered.json()["total"] == 401
    assert len(filtered.json()["rows"]) == 50
    page_selects = [statement for statement in statements if " limit " in statement]
    assert len(page_selects) == 5
    assert all("group by" in statement for statement in page_selects)

    legacy = client.get("/api/inventory/accessory-issues", headers=auth_headers, params={
        "production_order_id": first_order_id,
    })
    assert legacy.status_code == 200
    assert isinstance(legacy.json(), list)
    assert any(row["item_id"] == 0 for row in legacy.json())


def test_issue_plan_keeps_gross_issue_semantics_and_combines_linked_sources(accessory_case):
    case = accessory_case
    with TestSessionLocal() as db:
        db.add(ModelBOM(model_id=case["model_id"], item_id=case["item_id"], quantity_per_piece=1.2, unit="pcs"))
        _seed_issues(db, case)
        row = accessory_issue_plan(db, case["po_id"])["rows"][0]
        # Existing readiness is based on gross issued quantity, not net returns.
        assert row["required_quantity"] == 12
        assert row["issued_quantity"] == 12
        assert row["remaining_quantity"] == 0


def _state(case):
    with TestSessionLocal() as db:
        return (
            db.query(StockBatch).count(), db.query(StockMovement).count(),
            db.query(AuditLog).count(), db.query(IdempotencyRecord).count(),
            current_stock_for_item(db, case["item_id"]),
        )


def test_partial_returns_use_combined_allowance_and_conserve_stock(client, auth_headers, accessory_case):
    case = accessory_case
    received = client.post("/api/inventory/receive", headers=auth_headers, json={
        "item_id": case["item_id"], "batch_no": "RETURN-OPENING", "quantity": 20,
        "unit": "pcs", "warehouse_id": case["source_id"], "qc_status": "passed",
    })
    assert received.status_code == 201, received.text
    for line in [
        {"item_id": case["item_id"], "quantity": 8, "unit": "pcs"},
        {"item_id": case["item_id"], "quantity": 4, "unit": "pcs", "manual": True},
    ]:
        issued = client.post("/api/inventory/accessory-issues", headers=auth_headers, json={
            "production_order_id": case["po_id"], "lines": [line],
        })
        assert issued.status_code == 201, issued.text

    total_returned = 0
    for index, quantity in enumerate((3, 6, 3)):
        payload = {
            "production_order_id": case["po_id"], "item_id": case["item_id"],
            "batch_no": f"RETURN-PART-{index}", "quantity": quantity, "unit": "pcs",
            "warehouse_id": case["destination_id"], "qc_status": "passed",
        }
        headers = {**auth_headers, "Idempotency-Key": f"return-balance-{uuid4().hex}"}
        returned = client.post("/api/inventory/accessory-returns", headers=headers, json=payload)
        assert returned.status_code == 201, returned.text
        total_returned += quantity
        before_replay = _state(case)
        replay = client.post("/api/inventory/accessory-returns", headers=headers, json=payload)
        assert replay.status_code == 201, replay.text
        assert replay.json()["id"] == returned.json()["id"]
        assert _state(case) == before_replay

        summary = client.get(
            "/api/inventory/accessory-issues", headers=auth_headers,
            params={"production_order_id": case["po_id"]},
        )
        assert summary.status_code == 200, summary.text
        rows = summary.json()
        assert sum(row["returned_quantity"] for row in rows) == total_returned
        assert sum(row["returnable_quantity"] for row in rows) == 12 - total_returned
        with TestSessionLocal() as db:
            source = current_stock_for_item(db, case["item_id"], case["source_id"])
            destination = current_stock_for_item(db, case["item_id"], case["destination_id"])
            global_stock = current_stock_for_item(db, case["item_id"])
            assert source == 12
            assert destination == total_returned
            assert global_stock == source + destination == 20 - 8 + total_returned
            # Manual issues are external to warehouse stock: conserve their four units too.
            assert global_stock + (12 - total_returned) == 20 + 4

    before_rejection = _state(case)
    rejected = client.post("/api/inventory/accessory-returns", headers=auth_headers, json={
        **payload, "batch_no": "RETURN-EXCESS", "quantity": 1,
    })
    assert rejected.status_code == 409, rejected.text
    assert _state(case) == before_rejection


def test_accessory_return_rejects_wrong_storage_and_unit_without_writes(
    client, auth_headers, accessory_case,
):
    case = accessory_case
    with TestSessionLocal() as db:
        wrong_storage = Warehouse(name="Return fabric storage", type="fabric_storage")
        db.add(wrong_storage)
        db.flush()
        _seed_issues(db, case, stock=5, manual=(), returned=0)
        wrong_storage_id = wrong_storage.id
        db.commit()

    payload = {
        "production_order_id": case["po_id"], "item_id": case["item_id"],
        "batch_no": "RETURN-WRONG-STORAGE", "quantity": 1, "unit": "pcs",
        "warehouse_id": wrong_storage_id, "qc_status": "passed",
    }
    before = _state(case)
    crossed_storage = client.post(
        "/api/inventory/accessory-returns", headers=auth_headers, json=payload,
    )
    wrong_unit = client.post(
        "/api/inventory/accessory-returns", headers=auth_headers,
        json={**payload, "batch_no": "RETURN-WRONG-UNIT", "warehouse_id": case["source_id"], "unit": "box"},
    )

    assert crossed_storage.status_code == 400, crossed_storage.text
    assert "Accessory Storage" in crossed_storage.text
    assert wrong_unit.status_code == 409, wrong_unit.text
    assert "unit" in wrong_unit.text.lower()
    assert _state(case) == before


@pytest.mark.parametrize(("submitted_condition", "canonical_condition"), [
    ("new", "new"), ("used", "used"), (" New ", "new"), (" USED ", "used"),
])
def test_accessory_return_accepts_ui_condition_codes_and_persists_label(
    client, auth_headers, accessory_case, submitted_condition, canonical_condition,
):
    case = accessory_case
    with TestSessionLocal() as db:
        _seed_issues(db, case, stock=1, manual=(), returned=0)
        db.commit()

    response = client.post("/api/inventory/accessory-returns", headers=auth_headers, json={
        "production_order_id": case["po_id"], "item_id": case["item_id"],
        "batch_no": f"RETURN-CONDITION-{canonical_condition.upper()}", "quantity": 1, "unit": "pcs",
        "warehouse_id": case["destination_id"], "qc_status": "passed",
        "return_condition": submitted_condition,
    })
    assert response.status_code == 201, response.text
    assert response.json()["processes"] == f"Accessory condition: {canonical_condition}"


def test_accessory_return_condition_keeps_none_and_default():
    base_payload = {
        "production_order_id": 1, "item_id": 1, "batch_no": "RETURN-SCHEMA",
        "quantity": 1, "unit": "pcs", "warehouse_id": 1,
    }
    assert AccessoryReturnIn.model_validate(base_payload).return_condition == "used"
    assert AccessoryReturnIn.model_validate({**base_payload, "return_condition": None}).return_condition is None


def test_accessory_return_with_none_condition_preserves_process_note(client, auth_headers, accessory_case):
    case = accessory_case
    with TestSessionLocal() as db:
        _seed_issues(db, case, stock=1, manual=(), returned=0)
        db.commit()

    response = client.post("/api/inventory/accessory-returns", headers=auth_headers, json={
        "production_order_id": case["po_id"], "item_id": case["item_id"],
        "batch_no": "RETURN-FREE-PROCESS-NOTE", "quantity": 1, "unit": "pcs",
        "warehouse_id": case["destination_id"], "qc_status": "passed",
        "return_condition": None, "processes": "Operator supplied process note",
    })
    assert response.status_code == 201, response.text
    assert response.json()["processes"] == "Operator supplied process note"


def test_accessory_return_ui_codes_match_openapi_enum(client):
    repo_root = Path(__file__).resolve().parents[3]
    ui_source = (
        repo_root / "frontend" / "src" / "app" / "(app)" / "inventory" / "receive" / "page.tsx"
    ).read_text(encoding="utf-8")
    ui_codes = set(re.findall(r'<option value="([^"]+)">\{t\("accessoryCondition\.', ui_source))

    openapi = client.get("/openapi.json")
    assert openapi.status_code == 200, openapi.text
    condition_schema = openapi.json()["components"]["schemas"]["AccessoryReturnIn"]["properties"]["return_condition"]
    schema_codes = {
        code
        for branch in condition_schema.get("anyOf", [condition_schema])
        for code in branch.get("enum", [])
    }
    assert ui_codes == schema_codes == {"new", "used"}
    assert condition_schema["default"] == "used"


def test_invalid_accessory_return_condition_rejects_without_writes_and_auth_still_precedes(
    client, auth_headers, accessory_case,
):
    case = accessory_case
    payload = {
        "production_order_id": case["po_id"], "item_id": case["item_id"],
        "batch_no": "RETURN-INVALID-CONDITION", "quantity": 1, "unit": "pcs",
        "warehouse_id": case["destination_id"], "qc_status": "passed",
        "return_condition": "damaged",
    }
    before = _state(case)
    invalid = client.post("/api/inventory/accessory-returns", headers=auth_headers, json=payload)
    assert invalid.status_code == 422, invalid.text
    assert _state(case) == before

    unauthenticated = client.post("/api/inventory/accessory-returns", json=payload)
    assert unauthenticated.status_code == 401, unauthenticated.text
    assert _state(case) == before
