from uuid import uuid4

import pytest
from sqlalchemy import event

from app.models import (
    AuditLog, IdempotencyRecord, Item, ManualAccessoryIssue, Model, ModelBOM,
    ProductionOrder, StockBatch, StockMovement, Warehouse,
)
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


def test_accessory_issue_summary_projects_only_fields_used_from_movements_and_items(accessory_case):
    with TestSessionLocal() as db:
        _seed_issues(db, accessory_case, manual=(), returned=0)
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if (
                normalized.startswith("select")
                and " from stock_movements " in normalized
                and " join items " in normalized
            ):
                statements.append(normalized)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            rows = accessory_issue_summary(db, production_order_id=accessory_case["po_id"])
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert len(rows) == 1
    assert len(statements) == 1
    selected = statements[0].split(" from stock_movements", 1)[0]
    assert "stock_movements.quantity" in selected
    assert "stock_movements.reference_type" in selected
    assert "items.sku" in selected
    assert "items.category" in selected
    assert "stock_movements.note" not in selected
    assert "items.composition_json" not in selected


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
