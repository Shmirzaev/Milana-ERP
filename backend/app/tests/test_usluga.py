from __future__ import annotations

from uuid import uuid4

from app.models import (
    AuditLog,
    Department,
    Bundle,
    BundleScanLog,
    CuttingRecord,
    FinishedGoodsStock,
    Item,
    MaterialReservation,
    Model,
    Package,
    PackagingRecord,
    ProductionOrder,
    ProductionBatch,
    Role,
    StockMovement,
    WorkOrder,
    User,
)
from app.core.security import hash_password
from app.services.production import expand_production_size_range_items
from app.tests.conftest import TestSessionLocal


def _login_eco(client) -> None:
    response = client.post(
        "/api/auth/login-json",
        json={
            "email": "admin@example.com",
            "password": "test-admin-password-123!",
            "factory_code": "ECO",
        },
    )
    assert response.status_code == 200, response.text


def _create_usluga_order(client, *, quantity: int = 12, size: str = "M") -> tuple[dict, dict]:
    suffix = uuid4().hex[:8].upper()
    model_response = client.post(
        "/api/usluga/models",
        json={
            "code": f"USVC-{suffix}",
            "name": f"Outside service model {suffix}",
            "category": "T-shirt",
            "details_json": {"general": {"model_no": f"USVC-{suffix}", "source": "usluga"}},
            "status": "draft",
        },
    )
    assert model_response.status_code == 201, model_response.text
    model = model_response.json()
    size_response = client.post(f"/api/usluga/models/{model['id']}/sizes", json={"size": size})
    assert size_response.status_code == 201, size_response.text
    color_response = client.post(f"/api/usluga/models/{model['id']}/colors", json={"color_name": "Natural"})
    assert color_response.status_code == 201, color_response.text
    fabric_response = client.post(
        f"/api/usluga/models/{model['id']}/bom",
        json={
            "material_name": "Customer-owned main cotton",
            "material_role": "main",
            "quantity_per_piece": 0.65,
            "unit": "kg",
            "waste_percent": 3,
        },
    )
    assert fabric_response.status_code == 201, fabric_response.text
    model["main_bom_id"] = fabric_response.json()["id"]
    secondary_response = client.post(
        f"/api/usluga/models/{model['id']}/bom",
        json={
            "material_name": "Customer-owned secondary ribana",
            "material_role": "secondary",
            "quantity_per_piece": 0.08,
            "unit": "kg",
            "waste_percent": 2,
        },
    )
    assert secondary_response.status_code == 201, secondary_response.text
    model["secondary_bom_id"] = secondary_response.json()["id"]
    approve_response = client.post(f"/api/usluga/models/{model['id']}/approve")
    assert approve_response.status_code == 200, approve_response.text
    order_response = client.post(
        "/api/usluga/orders",
        json={
            "customer_name": "Outside Customer LLC",
            "customer_reference": f"EXT-{suffix}",
            "model_id": model["id"],
            "color": "Natural",
            "sizes": [{"size": size, "quantity": quantity}],
            "material_description": "Customer-owned cotton fabric",
            "material_usage_kg": 8.75,
            "material_notes": "Received directly by cutting; not warehouse stock.",
        },
    )
    assert order_response.status_code == 201, order_response.text
    return model, order_response.json()


def test_usluga_combined_model_size_remains_one_cutting_size(client):
    _login_eco(client)
    _, order = _create_usluga_order(client, quantity=360, size="40-42")

    assert order["planned_quantity"] == 360
    assert [
        (row["color"], row["size"], row["planned_quantity"])
        for row in order["items"]
    ] == [("Natural", "40-42", 360)]

    # The pre-existing standard-production behavior remains deliberately
    # separate: its numeric range shorthand still expands per garment size.
    assert expand_production_size_range_items([
        {"color": "Natural", "size": "40-42", "planned_quantity": 360}
    ]) == [
        {"color": "Natural", "size": "40", "planned_quantity": 180},
        {"color": "Natural", "size": "42", "planned_quantity": 180},
    ]


def test_usluga_main_batch_size_counts_update_existing_bundles_only(client):
    _login_eco(client)
    model, order = _create_usluga_order(client, quantity=12, size="M")
    cutting = next(row for row in order["work_orders"] if row["operation"] == "cutting")
    recorded = client.post(
        "/api/cutting/records",
        json={
            "work_order_id": cutting["id"],
            "model_bom_id": model["main_bom_id"],
            "input_quantity": 6.5,
            "input_unit": "kg",
            "cut_pieces": 12,
            "passed_pieces": 12,
            "defective_pieces": 0,
            "waste_quantity": 0,
            "waste_unit": "kg",
            "bundles": [
                {"color": "серый", "size": "M", "quantity": 3, "count": 2, "next": "sewing"},
                {"color": "серый", "size": "L", "quantity": 3, "count": 2, "next": "sewing"},
            ],
        },
    )
    assert recorded.status_code == 201, recorded.text
    record_id = int(recorded.json()["id"])
    bundle_ids = [int(row["id"]) for row in recorded.json()["bundles"]]

    approved = client.post(f"/api/cutting/records/{record_id}/approve-usluga-batch", json={})
    assert approved.status_code == 200, approved.text
    for bundle_id in bundle_ids:
        received = client.post(f"/api/bundles/{bundle_id}/receive-sewing")
        assert received.status_code == 200, received.text

    before = client.get(f"/api/work-orders/{cutting['id']}/usluga-cutting-batches")
    assert before.status_code == 200, before.text
    before_row = next(row for row in before.json()["items"] if int(row["id"]) == record_id)
    assert {(row["size"], row["quantity"]) for row in before_row["size_counts"]} == {("M", 6), ("L", 6)}

    changed = client.patch(
        f"/api/cutting/records/{record_id}/usluga-size-counts",
        json={
            "sizes": [
                {"color": "серый", "size": "M", "quantity": 8},
                {"color": "серый", "size": "L", "quantity": 4},
            ]
        },
    )
    assert changed.status_code == 200, changed.text
    assert {(row["size"], row["quantity"]) for row in changed.json()["size_counts"]} == {("M", 8), ("L", 4)}

    with TestSessionLocal() as db:
        stored_record = db.get(CuttingRecord, record_id)
        stored_bundles = db.query(Bundle).filter(Bundle.id.in_(bundle_ids)).order_by(Bundle.id).all()
        assert stored_record.cut_pieces == 12
        assert stored_record.passed_pieces == 12
        assert stored_record.approval_status == "approved"
        assert [row.quantity for row in stored_bundles] == [4, 4, 2, 2]
        assert all(row.status == "received_sewing" for row in stored_bundles)
        assert all(
            [scan.scan_type for scan in row.scan_logs] == ["created", "received_sewing"]
            for row in stored_bundles
        )

    for endpoint in (
        f"/api/bundles/{bundle_ids[0]}/label",
        f"/api/bundles/label-sheet/by-ids?ids={bundle_ids[0]}",
    ):
        label = client.get(endpoint)
        assert label.status_code == 200, label.text
        assert "<meta charset='utf-8'>" in label.text
        assert "Milana Label Unicode" in label.text
        assert "data:font/ttf;base64," in label.text
        assert "серый / M" in label.text

    invalid_total = client.patch(
        f"/api/cutting/records/{record_id}/usluga-size-counts",
        json={
            "sizes": [
                {"color": "серый", "size": "M", "quantity": 9},
                {"color": "серый", "size": "L", "quantity": 4},
            ]
        },
    )
    assert invalid_total.status_code == 400, invalid_total.text
    with TestSessionLocal() as db:
        assert [row.quantity for row in db.query(Bundle).filter(Bundle.id.in_(bundle_ids)).order_by(Bundle.id)] == [4, 4, 2, 2]


def test_ect_inbox_keeps_open_usluga_cutting_visible_after_partial_sewing_handoff(client):
    _login_eco(client)
    _, order = _create_usluga_order(client, quantity=12)
    production_order_id = int(order["id"])

    db = TestSessionLocal()
    try:
        stored_order = db.get(ProductionOrder, production_order_id)
        cutting = db.query(WorkOrder).filter(
            WorkOrder.production_order_id == production_order_id,
            WorkOrder.operation == "cutting",
        ).one()
        sewing = db.query(WorkOrder).filter(
            WorkOrder.production_order_id == production_order_id,
            WorkOrder.operation == "sewing",
        ).one()

        stored_order.status = "sewing"
        cutting.status = "in_progress"
        sewing.status = "in_progress"
        sewing.actual_input_qty = 5
        cutting_id = int(cutting.id)
        db.commit()
    finally:
        db.close()

    inbox = client.get("/api/inbox?dept=ECT")
    assert inbox.status_code == 200, inbox.text
    payload = inbox.json()
    visible_ids = {
        int(row["id"])
        for key in ("pending_work_orders", "in_progress_work_orders", "active_work_orders")
        for row in payload[key]
    }
    assert cutting_id in visible_ids


def test_reject_usluga_cutting_batch_permanently_deletes_unused_record_and_bundles(client):
    _login_eco(client)
    model, order = _create_usluga_order(client, quantity=12)
    cutting = next(row for row in order["work_orders"] if row["operation"] == "cutting")
    split = client.post(
        f"/api/work-orders/{cutting['id']}/split-batches",
        json={"batches": [{"name": "Replacement-ready batch", "planned_quantity": 12}]},
    )
    assert split.status_code == 200, split.text
    progress = client.get(f"/api/work-orders/{cutting['id']}/cutting-batch-progress")
    assert progress.status_code == 200, progress.text
    production_batch_id = int(progress.json()["items"][0]["id"])

    created = client.post(
        "/api/cutting/records",
        json={
            "work_order_id": cutting["id"],
            "production_batch_id": production_batch_id,
            "model_bom_id": model["main_bom_id"],
            "input_quantity": 6.5,
            "input_unit": "kg",
            "cut_pieces": 12,
            "passed_pieces": 12,
            "defective_pieces": 0,
            "waste_quantity": 0.4,
            "waste_unit": "kg",
            "bundles": [{
                "color": "Natural",
                "size": "M",
                "quantity": 6,
                "count": 2,
                "next": "sewing",
                "sewing_factory": "eco_cotton",
            }],
        },
    )
    assert created.status_code == 201, created.text
    record_id = int(created.json()["id"])
    bundle_ids = [int(row["id"]) for row in created.json()["bundles"]]
    assert len(bundle_ids) == 2

    rejected = client.post(
        f"/api/cutting/records/{record_id}/reject-usluga-batch",
        json={"reason": "Wrong Cutting attempt"},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json() == {
        "id": record_id,
        "cutting_batch_no": created.json()["cutting_batch_no"],
        "deleted": True,
        "deleted_bundle_count": 2,
        "deleted_bundle_quantity": 12,
    }

    with TestSessionLocal() as db:
        assert db.get(ProductionBatch, production_batch_id) is not None
        assert db.get(CuttingRecord, record_id) is None
        assert db.query(Bundle).filter(Bundle.id.in_(bundle_ids)).count() == 0
        assert db.query(BundleScanLog).filter(BundleScanLog.bundle_id.in_(bundle_ids)).count() == 0
        audit = (
            db.query(AuditLog)
            .filter(
                AuditLog.action == "reject_and_delete_usluga_cutting_batch",
                AuditLog.entity_type == "CuttingRecord",
                AuditLog.entity_id == record_id,
            )
            .order_by(AuditLog.id.desc())
            .first()
        )
        assert audit is not None
        assert audit.old_value_json["bundle_ids"] == bundle_ids
        assert audit.old_value_json["bundled_quantity"] == 12
        assert audit.new_value_json["deleted"] is True
        assert audit.new_value_json["previously_rejected"] is False

    refreshed_progress = client.get(f"/api/work-orders/{cutting['id']}/cutting-batch-progress")
    assert refreshed_progress.status_code == 200, refreshed_progress.text
    row = refreshed_progress.json()["items"][0]
    assert row["id"] == production_batch_id
    assert row["bundle_count"] == 0
    assert row["editable"] is True


def test_previously_rejected_usluga_cutting_batch_can_be_permanently_cleaned(client):
    _login_eco(client)
    model, order = _create_usluga_order(client, quantity=6)
    cutting = next(row for row in order["work_orders"] if row["operation"] == "cutting")
    created = client.post(
        "/api/cutting/records",
        json={
            "work_order_id": cutting["id"],
            "model_bom_id": model["main_bom_id"],
            "input_quantity": 3.25,
            "input_unit": "kg",
            "cut_pieces": 6,
            "passed_pieces": 6,
            "defective_pieces": 0,
            "waste_quantity": 0.2,
            "waste_unit": "kg",
            "bundles": [{
                "color": "Natural",
                "size": "M",
                "quantity": 6,
                "count": 1,
                "next": "sewing",
                "sewing_factory": "eco_cotton",
            }],
        },
    )
    assert created.status_code == 201, created.text
    record_id = int(created.json()["id"])
    bundle_id = int(created.json()["bundles"][0]["id"])

    with TestSessionLocal() as db:
        record = db.get(CuttingRecord, record_id)
        bundle = db.get(Bundle, bundle_id)
        record.approval_status = "rejected"
        record.rejection_reason = "Legacy rejected row"
        bundle.status = "cancelled"
        db.commit()

    removed = client.post(
        f"/api/cutting/records/{record_id}/reject-usluga-batch",
        json={"reason": "Remove legacy rejected row"},
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["deleted"] is True
    with TestSessionLocal() as db:
        assert db.get(CuttingRecord, record_id) is None
        assert db.get(Bundle, bundle_id) is None
        assert db.query(BundleScanLog).filter(BundleScanLog.bundle_id == bundle_id).count() == 0
        audit = (
            db.query(AuditLog)
            .filter(
                AuditLog.action == "reject_and_delete_usluga_cutting_batch",
                AuditLog.entity_id == record_id,
            )
            .order_by(AuditLog.id.desc())
            .first()
        )
        assert audit is not None
        assert audit.old_value_json["previous_rejection_reason"] == "Legacy rejected row"
        assert audit.new_value_json["previously_rejected"] is True


def test_usluga_cutting_batch_name_remains_editable_while_quantity_locks_after_bundles(client):
    _login_eco(client)
    model, order = _create_usluga_order(client, quantity=12)
    cutting = next(row for row in order["work_orders"] if row["operation"] == "cutting")

    split = client.post(
        f"/api/work-orders/{cutting['id']}/split-batches",
        json={"batches": [{"name": "Initial batch", "planned_quantity": 12}]},
    )
    assert split.status_code == 200, split.text
    progress = client.get(f"/api/work-orders/{cutting['id']}/cutting-batch-progress")
    assert progress.status_code == 200, progress.text
    initial = progress.json()["items"][0]
    batch_id = int(initial["id"])
    assert initial["editable"] is True
    assert initial["name_editable"] is True
    assert initial["quantity_editable"] is True
    assert initial["bundle_count"] == 0

    mil_login = client.post(
        "/api/auth/login-json",
        json={
            "email": "admin@example.com",
            "password": "test-admin-password-123!",
            "factory_code": "MIL",
        },
    )
    assert mil_login.status_code == 200, mil_login.text
    wrong_factory = client.patch(
        f"/api/work-orders/{cutting['id']}/batches/{batch_id}",
        json={"name": "Wrong factory edit", "planned_quantity": 14},
    )
    assert wrong_factory.status_code == 403, wrong_factory.text
    _login_eco(client)

    missing_name = client.patch(
        f"/api/work-orders/{cutting['id']}/batches/{batch_id}",
        json={"name": "   ", "planned_quantity": 14},
    )
    assert missing_name.status_code == 400, missing_name.text
    invalid_quantity = client.patch(
        f"/api/work-orders/{cutting['id']}/batches/{batch_id}",
        json={"name": "Still initial", "planned_quantity": 0},
    )
    assert invalid_quantity.status_code == 400, invalid_quantity.text

    # A report-only secondary fabric entry creates no product bundles and must
    # not lock correction of the production-batch name or piece count.
    secondary = client.post(
        "/api/cutting/records",
        json={
            "work_order_id": cutting["id"],
            "production_batch_id": batch_id,
            "model_bom_id": model["secondary_bom_id"],
            "input_quantity": 1.25,
            "input_unit": "kg",
            "cut_pieces": 0,
            "report_piece_count": 5,
            "passed_pieces": 0,
            "defective_pieces": 0,
            "waste_quantity": 0.05,
            "waste_unit": "kg",
            "bundles": [],
        },
    )
    assert secondary.status_code == 201, secondary.text

    edited = client.patch(
        f"/api/work-orders/{cutting['id']}/batches/{batch_id}",
        json={"name": "Morning cut", "planned_quantity": 15},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["name"] == "Morning cut"
    assert edited.json()["planned_quantity"] == 15
    assert edited.json()["editable"] is True

    with TestSessionLocal() as db:
        stored = db.get(ProductionBatch, batch_id)
        assert stored.name == "Morning cut"
        assert stored.planned_quantity == 15
        audit = (
            db.query(AuditLog)
            .filter(
                AuditLog.action == "edit_usluga_cutting_batch",
                AuditLog.entity_type == "ProductionBatch",
                AuditLog.entity_id == batch_id,
            )
            .order_by(AuditLog.id.desc())
            .one()
        )
        assert audit.old_value_json["name"] == "Initial batch"
        assert audit.old_value_json["planned_quantity"] == 12
        assert audit.new_value_json["name"] == "Morning cut"
        assert audit.new_value_json["planned_quantity"] == 15

    main = client.post(
        "/api/cutting/records",
        json={
            "work_order_id": cutting["id"],
            "production_batch_id": batch_id,
            "model_bom_id": model["main_bom_id"],
            "input_quantity": 6.5,
            "input_unit": "kg",
            "cut_pieces": 15,
            "passed_pieces": 15,
            "defective_pieces": 0,
            "waste_quantity": 0.4,
            "waste_unit": "kg",
            "bundles": [{
                "color": "Natural",
                "size": "M",
                "quantity": 15,
                "count": 1,
                "next": "sewing",
                "sewing_factory": "eco_cotton",
            }],
        },
    )
    assert main.status_code == 201, main.text
    assert len(main.json()["bundles"]) == 1
    bundle_id = int(main.json()["bundles"][0]["id"])

    sheet = client.get(f"/api/cutting/records/{main.json()['id']}/production-sheet")
    assert sheet.status_code == 200, sheet.text
    assert f"{initial['batch_no']} - Morning cut (1/1)" in sheet.text

    renamed = client.patch(
        f"/api/work-orders/{cutting['id']}/batches/{batch_id}",
        json={"name": "Late label correction"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "Late label correction"
    assert renamed.json()["planned_quantity"] == 15
    assert renamed.json()["bundle_count"] == 1
    assert renamed.json()["name_editable"] is True
    assert renamed.json()["quantity_editable"] is False

    locked_quantity = client.patch(
        f"/api/work-orders/{cutting['id']}/batches/{batch_id}",
        json={"name": "Must roll back", "planned_quantity": 20},
    )
    assert locked_quantity.status_code == 409, locked_quantity.text

    locked_progress = client.get(f"/api/work-orders/{cutting['id']}/cutting-batch-progress")
    assert locked_progress.status_code == 200, locked_progress.text
    locked_row = locked_progress.json()["items"][0]
    assert locked_row["name"] == "Late label correction"
    assert locked_row["planned_quantity"] == 15
    assert locked_row["bundle_count"] == 1
    assert locked_row["name_editable"] is True
    assert locked_row["quantity_editable"] is False
    assert locked_row["editable"] is False

    updated_sheet = client.get(f"/api/cutting/records/{main.json()['id']}/production-sheet")
    assert updated_sheet.status_code == 200, updated_sheet.text
    assert f"{initial['batch_no']} - Late label correction (1/1)" in updated_sheet.text

    with TestSessionLocal() as db:
        stored = db.get(ProductionBatch, batch_id)
        assert stored.name == "Late label correction"
        assert stored.planned_quantity == 15
        bundle = db.get(Bundle, bundle_id)
        assert bundle is not None
        assert bundle.production_batch_id == batch_id
        assert bundle.quantity == 15


def test_usluga_models_have_full_plm_functions_and_multicolor_planning(client):
    _login_eco(client)
    model, _ = _create_usluga_order(client, quantity=4)
    model_id = model["id"]

    detail = client.get(f"/api/usluga/models/{model_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["sizes"][0]["size"] == "M"
    assert client.get(f"/api/models/{model_id}").status_code == 404

    updated_payload = {
        "code": model["code"],
        "name": "Updated outside service model",
        "category": "T-shirt",
        "description": "Full Usluga technical card",
        "details_json": {
            "general": {"model_no": model["code"], "source": "usluga"},
            "translation": {"en": "Updated outside service model"},
            "paid_operations": [{"id": "eco-op", "name": "Eco sewing", "factory": "ECO"}],
        },
        "status": "approved",
        "sam_minutes": 12.5,
    }
    updated = client.patch(f"/api/usluga/models/{model_id}", json=updated_payload)
    assert updated.status_code == 200, updated.text
    assert updated.json()["sam_minutes"] == 12.5

    variant = client.post(
        f"/api/usluga/models/{model_id}/variants",
        json={"variant_no": "02", "color": "Black"},
    )
    assert variant.status_code == 201, variant.text
    assert variant.json()["code"].endswith("-02")
    variants = client.get(f"/api/usluga/models/{model_id}/variants")
    assert variants.status_code == 200, variants.text
    assert variants.json()[0]["color"] == "Black"

    options = client.get("/api/usluga/model-options", params={"ids": [model_id]})
    assert options.status_code == 200, options.text
    assert options.json()["items"][0]["id"] == model_id
    grouped = client.get("/api/usluga/models/variant-groups", params={"include_total": True, "compact": True})
    assert grouped.status_code == 200, grouped.text
    assert grouped.json()["total"] >= 1

    multi = client.post(
        "/api/usluga/orders",
        json={
            "customer_name": "Outside Multi Color LLC",
            "model_id": model_id,
            "lines": [
                {"color": "Natural", "size": "M", "quantity": 3},
                {"color": "Black", "size": "M", "quantity": 5},
            ],
            "material_usage_kg": 4.25,
        },
    )
    assert multi.status_code == 201, multi.text
    assert multi.json()["planned_quantity"] == 8
    assert {(row["color"], row["size"], row["planned_quantity"]) for row in multi.json()["items"]} == {
        ("Natural", "M", 3),
        ("Black", "M", 5),
    }


def test_usluga_model_fabric_name_is_manual_and_inventory_independent(client):
    _login_eco(client)
    suffix = uuid4().hex[:8].upper()
    model_response = client.post(
        "/api/usluga/models",
        json={
            "code": f"USL-MANUAL-{suffix}",
            "name": "Manual fabric service model",
            "category": "hoodie",
            "status": "draft",
        },
    )
    assert model_response.status_code == 201, model_response.text
    model_id = model_response.json()["id"]

    fabric_response = client.post(
        f"/api/usluga/models/{model_id}/bom",
        json={
            "material_name": "Customer graphite compact cotton",
            "material_role": "main",
            "color": "Graphite",
            "quantity_per_piece": 0.64,
            "unit": "kg",
            "waste_percent": 3,
        },
    )
    assert fabric_response.status_code == 201, fabric_response.text
    bom_id = fabric_response.json()["id"]

    detail = client.get(f"/api/usluga/models/{model_id}")
    assert detail.status_code == 200, detail.text
    manual_row = detail.json()["bom"][0]
    assert manual_row["material_name"] == "Customer graphite compact cotton"
    assert manual_row["material_role"] == "main"
    assert manual_row["item_id"] is None
    assert manual_row["item"] is None
    assert manual_row["stock_batch_id"] is None

    updated = client.patch(
        f"/api/usluga/models/{model_id}/bom/{bom_id}",
        json={"material_name": "Customer-owned brushed fleece", "quantity_per_piece": 0.7},
    )
    assert updated.status_code == 200, updated.text
    updated_row = client.get(f"/api/usluga/models/{model_id}").json()["bom"][0]
    assert updated_row["material_name"] == "Customer-owned brushed fleece"
    assert updated_row["item_id"] is None

    variant = client.post(
        f"/api/usluga/models/{model_id}/variants",
        json={"variant_no": f"V{suffix[:4]}", "color": "Black"},
    )
    assert variant.status_code == 201, variant.text
    variant_detail = client.get(f"/api/usluga/models/{variant.json()['id']}")
    assert variant_detail.status_code == 200, variant_detail.text
    assert variant_detail.json()["bom"][0]["material_name"] == "Customer-owned brushed fleece"
    assert variant_detail.json()["bom"][0]["item_id"] is None

    with TestSessionLocal() as db:
        inventory_fabric = db.query(Item).filter(Item.category.in_(["fabric", "semi_finished"])).first()
        accessory = db.query(Item).filter(Item.category.in_(["accessory", "packaging"])).first()
        assert inventory_fabric is not None
        assert accessory is not None
        inventory_fabric_id = inventory_fabric.id
        accessory_id = accessory.id
        accessory_unit = accessory.unit

    rejected_inventory_fabric = client.post(
        f"/api/usluga/models/{model_id}/bom",
        json={"item_id": inventory_fabric_id, "quantity_per_piece": 0.5, "unit": "kg"},
    )
    assert rejected_inventory_fabric.status_code == 400, rejected_inventory_fabric.text

    duplicate_main = client.post(
        f"/api/usluga/models/{model_id}/bom",
        json={"material_name": "Another main", "material_role": "main", "quantity_per_piece": 0.4, "unit": "kg"},
    )
    assert duplicate_main.status_code == 409, duplicate_main.text

    accessory_response = client.post(
        f"/api/usluga/models/{model_id}/bom",
        json={"item_id": accessory_id, "quantity_per_piece": 1, "unit": accessory_unit},
    )
    assert accessory_response.status_code == 201, accessory_response.text


def test_usluga_variant_uses_main_fabric_for_color_and_variant_summary(client):
    _login_eco(client)
    suffix = uuid4().hex[:8].upper()
    model = client.post(
        "/api/usluga/models",
        json={
            "code": f"USL-MAIN-{suffix}",
            "name": "Main fabric variant model",
            "category": "hoodie",
            "status": "draft",
        },
    )
    assert model.status_code == 201, model.text
    model_id = model.json()["id"]

    secondary = client.post(
        f"/api/usluga/models/{model_id}/bom",
        json={
            "material_name": "Rib trim",
            "material_role": "secondary",
            "color": "Red",
            "quantity_per_piece": 0.08,
            "unit": "kg",
        },
    )
    assert secondary.status_code == 201, secondary.text
    main = client.post(
        f"/api/usluga/models/{model_id}/bom",
        json={
            "material_name": "Customer fleece",
            "material_role": "main",
            "color": "Red",
            "quantity_per_piece": 0.7,
            "unit": "kg",
        },
    )
    assert main.status_code == 201, main.text

    created = client.post(
        f"/api/usluga/models/{model_id}/variants",
        json={"variant_no": "GRAY", "color": "Gray"},
    )
    assert created.status_code == 201, created.text
    variant_id = created.json()["id"]

    variant_detail = client.get(f"/api/usluga/models/{variant_id}")
    assert variant_detail.status_code == 200, variant_detail.text
    rows_by_role = {row["material_role"]: row for row in variant_detail.json()["bom"]}
    assert rows_by_role["main"]["material_name"] == "Customer fleece"
    assert rows_by_role["main"]["color"] == "Gray"
    assert rows_by_role["secondary"]["material_name"] == "Rib trim"
    assert rows_by_role["secondary"]["color"] == "Red"

    listed = client.get(f"/api/usluga/models/{model_id}/variants")
    assert listed.status_code == 200, listed.text
    variant_row = next(row for row in listed.json() if row["model_id"] == variant_id)
    assert variant_row["color"] == "Gray"
    assert variant_row["fabric"] == "Customer fleece / Gray"

    edited = client.patch(
        f"/api/usluga/models/{model_id}/variants/{variant_id}",
        json={"variant_no": "GRAY", "color": "Silver"},
    )
    assert edited.status_code == 200, edited.text
    edited_detail = client.get(f"/api/usluga/models/{variant_id}").json()
    edited_by_role = {row["material_role"]: row for row in edited_detail["bom"]}
    assert edited_by_role["main"]["color"] == "Silver"
    assert edited_by_role["secondary"]["color"] == "Red"


def test_usluga_order_is_eco_only_and_has_no_inventory_or_storage_stage(client):
    # The default super-admin session is Milana and cannot cross into ECT Usluga.
    milana_login = client.post(
        "/api/auth/login-json",
        json={
            "email": "admin@example.com",
            "password": "test-admin-password-123!",
            "factory_code": "MIL",
        },
    )
    assert milana_login.status_code == 200, milana_login.text
    denied = client.get("/api/usluga/orders")
    assert denied.status_code == 403

    _login_eco(client)
    model, order = _create_usluga_order(client)
    assert order["order_no"].startswith("USL-")
    assert order["material_usage_kg"] == 8.75
    assert [row["operation"] for row in order["work_orders"]] == ["cutting", "sewing", "packaging"]

    with TestSessionLocal() as db:
        stored_order = db.get(ProductionOrder, order["id"])
        stored_model = db.get(Model, model["id"])
        assert stored_order.source_type == "usluga"
        assert stored_order.fabric_batch_id is None
        assert stored_order.destination_warehouse_id is None
        assert stored_model.catalog_scope == "usluga"
        assert stored_model.factory_code == "ECO"
        work_orders = (
            db.query(WorkOrder, Department.code)
            .join(Department, Department.id == WorkOrder.department_id)
            .filter(WorkOrder.production_order_id == order["id"])
            .order_by(WorkOrder.id)
            .all()
        )
        assert [(work.operation, code) for work, code in work_orders] == [
            ("cutting", "ECT"),
            ("sewing", "ECO"),
            ("packaging", "ECP"),
        ]
        assert db.query(MaterialReservation).filter(MaterialReservation.production_order_id == order["id"]).count() == 0
        assert db.query(FinishedGoodsStock).filter(FinishedGoodsStock.production_order_id == order["id"]).count() == 0

    # Service-only models never leak into the normal shared PLM catalog.
    assert client.get(f"/api/models/{model['id']}").status_code == 404
    normal_models = client.get("/api/models").json()
    assert all(row["id"] != model["id"] for row in normal_models)

    # Even a super-admin must switch into Eco Cotton; the generic Milana
    # production/process pages never expose service-only orders.
    milana_login = client.post(
        "/api/auth/login-json",
        json={
            "email": "admin@example.com",
            "password": "test-admin-password-123!",
            "factory_code": "MIL",
        },
    )
    assert milana_login.status_code == 200, milana_login.text
    work_order_id = order["work_orders"][0]["id"]
    assert client.get(f"/api/production-orders/{order['id']}").status_code == 403
    assert client.get(f"/api/work-orders/{work_order_id}").status_code == 403
    assert client.get(f"/api/work-orders?production_order_id={order['id']}").json() == []
    assert all(row["id"] != order["id"] for row in client.get("/api/production-orders").json())
    process_rows = client.get(f"/api/process-tracking?q={order['order_no']}").json()
    assert process_rows == []
    assert client.patch(f"/api/production-orders/{order['id']}", json={"fabric_batch_id": 1}).status_code == 409
    assert client.post(f"/api/production-orders/{order['id']}/create-work-orders").status_code == 409
    assert client.post(f"/api/production-orders/{order['id']}/reserve-materials", json={}).status_code == 409


def test_usluga_planning_can_edit_order_and_sync_unstarted_work_order_plans(client):
    _login_eco(client)
    model, order = _create_usluga_order(client, quantity=12)
    with TestSessionLocal() as db:
        movement_count_before = db.query(StockMovement).count()

    updated = client.patch(
        f"/api/usluga/orders/{order['id']}",
        json={
            "customer_name": "Updated Outside Customer LLC",
            "customer_reference": "UPDATED-REF",
            "model_id": model["id"],
            "lines": [
                {"color": "Natural", "size": "M", "quantity": 9},
                {"color": "Black", "size": "M", "quantity": 6},
            ],
            "deadline": "2026-09-15T18:59:59Z",
            "material_description": "Updated customer-owned cotton",
            "material_usage_kg": 11.25,
            "material_notes": "Edited by Usluga planning without inventory.",
        },
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["customer_name"] == "Updated Outside Customer LLC"
    assert body["customer_reference"] == "UPDATED-REF"
    assert body["planned_quantity"] == 15
    assert body["material_usage_kg"] == 11.25
    assert {(row["color"], row["size"], row["planned_quantity"]) for row in body["items"]} == {
        ("Natural", "M", 9),
        ("Black", "M", 6),
    }
    assert all(row["planned_quantity"] == 15 for row in body["work_orders"])

    with TestSessionLocal() as db:
        stored = db.get(ProductionOrder, order["id"])
        assert stored.model_id == model["id"]
        assert stored.planned_quantity == 15
        work_orders = db.query(WorkOrder).filter(WorkOrder.production_order_id == order["id"]).all()
        assert all(row.planned_input_qty == 15 and row.planned_output_qty == 15 for row in work_orders)
        assert all(row.deadline is not None for row in work_orders)
        assert db.query(MaterialReservation).filter(MaterialReservation.production_order_id == order["id"]).count() == 0
        assert db.query(StockMovement).count() == movement_count_before


def test_usluga_planning_keeps_metadata_editable_but_locks_plan_after_production_evidence(client):
    _login_eco(client)
    model, order = _create_usluga_order(client, quantity=12)
    with TestSessionLocal() as db:
        cutting = db.query(WorkOrder).filter(
            WorkOrder.production_order_id == order["id"],
            WorkOrder.operation == "cutting",
        ).one()
        cutting.actual_input_qty = 1
        db.commit()

    metadata_update = client.patch(
        f"/api/usluga/orders/{order['id']}",
        json={
            "customer_name": "Metadata-only update",
            "customer_reference": "META-REF",
            "model_id": model["id"],
            "lines": [{"color": "Natural", "size": "M", "quantity": 12}],
            "deadline": "2026-09-20T18:59:59Z",
            "material_description": "Customer material, revised description",
            "material_usage_kg": 9.5,
            "material_notes": "Production evidence remains untouched.",
        },
    )
    assert metadata_update.status_code == 200, metadata_update.text
    assert metadata_update.json()["customer_name"] == "Metadata-only update"
    assert metadata_update.json()["planned_quantity"] == 12

    structural_update = client.patch(
        f"/api/usluga/orders/{order['id']}",
        json={
            "customer_name": "Metadata-only update",
            "customer_reference": "META-REF",
            "model_id": model["id"],
            "lines": [{"color": "Natural", "size": "M", "quantity": 13}],
            "material_usage_kg": 9.5,
        },
    )
    assert structural_update.status_code == 409
    assert "production has started" in structural_update.json()["detail"].lower()

    refreshed = client.get(f"/api/usluga/orders/{order['id']}").json()
    assert refreshed["planned_quantity"] == 12
    assert refreshed["customer_name"] == "Metadata-only update"


def test_usluga_packages_bypass_warehouse_and_can_be_handed_directly_to_customer(client):
    _login_eco(client)
    model, order = _create_usluga_order(client, quantity=10)
    with TestSessionLocal() as db:
        packaging = db.query(WorkOrder).filter(
            WorkOrder.production_order_id == order["id"],
            WorkOrder.operation == "packaging",
        ).one()
        packaging.status = "completed"
        packaging.actual_input_qty = 10
        packaging.actual_output_qty = 10
        packaging.passed_qty = 10
        db.add(PackagingRecord(
            work_order_id=packaging.id,
            input_qty=10,
            packed_qty=10,
            damaged_qty=0,
            package_count=1,
            total_packed_quantity=10,
        ))
        db.commit()

    package_response = client.post(
        "/api/packages",
        json={
            "production_order_id": order["id"],
            "model_id": model["id"],
            "color": "Natural",
            "capacity": 60,
            "items": [{"model_id": model["id"], "color": "Natural", "size": "M", "quantity": 10}],
        },
    )
    assert package_response.status_code == 201, package_response.text
    package = package_response.json()

    with TestSessionLocal() as db:
        assert db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id == package["id"]).count() == 0

    # Every warehouse entry point rejects customer-owned Usluga goods.
    storage_response = client.post(
        f"/api/packages/{package['id']}/receive-storage",
        json={"storage_cell": "A-01", "storage_shelf": "S1"},
    )
    assert storage_response.status_code == 400

    premature_handover = client.post(
        f"/api/usluga/orders/{order['id']}/handover",
        json={"recipient": "Outside Customer LLC / Akmal"},
    )
    assert premature_handover.status_code == 409

    with TestSessionLocal() as db:
        for work_order in db.query(WorkOrder).filter(WorkOrder.production_order_id == order["id"]).all():
            work_order.status = "completed"
            work_order.actual_input_qty = 10
            work_order.actual_output_qty = 10
            work_order.passed_qty = 10
        db.commit()

    handover_response = client.post(
        f"/api/usluga/orders/{order['id']}/handover",
        json={"recipient": "Outside Customer LLC / Akmal", "notes": "Released against signed handover."},
    )
    assert handover_response.status_code == 200, handover_response.text
    handed_over = handover_response.json()
    assert handed_over["status"] == "handed_over"
    assert handed_over["handover_recipient"] == "Outside Customer LLC / Akmal"

    read_only_edit = client.patch(
        f"/api/usluga/orders/{order['id']}",
        json={
            "customer_name": "Should not change",
            "model_id": model["id"],
            "lines": [{"color": "Natural", "size": "M", "quantity": 10}],
        },
    )
    assert read_only_edit.status_code == 409

    with TestSessionLocal() as db:
        assert db.get(Package, package["id"]).status == "handed_over"
        assert db.query(FinishedGoodsStock).filter(FinishedGoodsStock.production_order_id == order["id"]).count() == 0


def test_usluga_cutting_records_kilograms_without_consuming_inventory_and_forces_eco_route(client):
    _login_eco(client)
    model, order = _create_usluga_order(client, quantity=12)
    cutting = next(row for row in order["work_orders"] if row["operation"] == "cutting")
    base_payload = {
        "work_order_id": cutting["id"],
        "model_bom_id": model["main_bom_id"],
        "input_quantity": 6.5,
        "input_unit": "kg",
        "cut_pieces": 12,
        "passed_pieces": 12,
        "defective_pieces": 0,
        "waste_quantity": 0.4,
        "waste_unit": "kg",
        "bundles": [{
            "color": "Natural",
            "size": "M",
            "quantity": 12,
            "count": 1,
            "next": "sewing",
            "sewing_factory": "besttex",
        }],
    }
    inventory_attempt = client.post(
        "/api/cutting/records",
        json={**base_payload, "fabric_batch_id": 1},
    )
    assert inventory_attempt.status_code == 400

    invalid_main_report = client.post(
        "/api/cutting/records",
        json={**base_payload, "fabric_batch_id": None, "report_piece_count": 9},
    )
    assert invalid_main_report.status_code == 400, invalid_main_report.text

    with TestSessionLocal() as db:
        movement_count_before = db.query(StockMovement).count()
    recorded = client.post(
        "/api/cutting/records",
        json={**base_payload, "fabric_batch_id": None},
    )
    assert recorded.status_code == 201, recorded.text
    assert recorded.json()["bundles"][0]["sewing_factory_code"] == "ECO"
    assert recorded.json()["approval_status"] == "pending"
    assert recorded.json()["material_role"] == "main"
    record_id = recorded.json()["id"]
    bundle_id = recorded.json()["bundles"][0]["id"]

    secondary = client.post(
        "/api/cutting/records",
        json={
            "work_order_id": cutting["id"],
            "model_bom_id": model["secondary_bom_id"],
            "input_quantity": 1.25,
            "input_unit": "kg",
            "cut_pieces": 0,
            "report_piece_count": 7,
            "passed_pieces": 0,
            "defective_pieces": 0,
            "waste_quantity": 0.05,
            "waste_unit": "kg",
            "bundles": [],
        },
    )
    assert secondary.status_code == 201, secondary.text
    assert secondary.json()["approval_status"] == "pending"
    assert secondary.json()["bundles"] == []
    assert secondary.json()["report_piece_count"] == 7
    secondary_record_id = secondary.json()["id"]
    secondary_detail = client.get(f"/api/cutting/records/{secondary_record_id}")
    assert secondary_detail.status_code == 200, secondary_detail.text
    assert secondary_detail.json()["report_piece_count"] == 7
    assert secondary_detail.json()["cut_pieces"] == 0
    assert secondary_detail.json()["passed_pieces"] == 0

    invalid_secondary = client.post(
        "/api/cutting/records",
        json={
            **base_payload,
            "model_bom_id": model["secondary_bom_id"],
            "fabric_batch_id": None,
        },
    )
    assert invalid_secondary.status_code == 400, invalid_secondary.text

    batch_list = client.get(f"/api/work-orders/{cutting['id']}/usluga-cutting-batches")
    assert batch_list.status_code == 200, batch_list.text
    assert len(batch_list.json()["items"]) == 2
    assert batch_list.json()["items"][0]["cutting_batch_no"].startswith("USL-CUT-")
    secondary_item = next(row for row in batch_list.json()["items"] if row["material_role"] == "secondary")
    assert secondary_item["report_piece_count"] == 7
    assert secondary_item["cut_pieces"] == 0

    with TestSessionLocal() as db:
        stored_secondary = db.get(CuttingRecord, secondary_record_id)
        stored_cutting = db.get(WorkOrder, cutting["id"])
        assert stored_secondary.report_piece_count == 7
        assert stored_secondary.cut_pieces == 0
        assert stored_secondary.passed_pieces == 0
        assert stored_cutting.passed_qty == 0

    # Passport printing is read-only and never approves or closes the work.
    passport = client.get(f"/api/cutting/records/{record_id}/production-sheet")
    assert passport.status_code == 200, passport.text
    with TestSessionLocal() as db:
        stored_record = db.get(CuttingRecord, record_id)
        stored_cutting = db.get(WorkOrder, cutting["id"])
        assert stored_record.approval_status == "pending"
        assert stored_cutting.passed_qty == 0
        assert stored_cutting.status != "completed"

    blocked_movement = client.post(f"/api/bundles/{bundle_id}/send-sewing")
    assert blocked_movement.status_code == 409, blocked_movement.text

    # Cutting staff can record/print batches but cannot self-approve them.
    limited_email = f"usluga-cutting-{uuid4().hex[:8]}@example.com"
    limited_password = "UslugaCuttingOnly!2026"
    with TestSessionLocal() as db:
        ect = db.query(Department).filter(Department.code == "ECT").one()
        role = Role(name=f"Usluga cutting test {uuid4().hex[:8]}", permissions=["cutting.records", "production.view"])
        db.add(role)
        db.flush()
        db.add(User(
            name="Usluga cutting tester",
            email=limited_email,
            password_hash=hash_password(limited_password),
            role_id=role.id,
            department_id=ect.id,
            factory_code="ECO",
            extra_permissions=[],
            is_active=True,
        ))
        db.commit()
    limited_login = client.post(
        "/api/auth/login-json",
        json={"email": limited_email, "password": limited_password, "factory_code": "ECO"},
    )
    assert limited_login.status_code == 200, limited_login.text
    denied_approval = client.post(f"/api/cutting/records/{record_id}/approve-usluga-batch", json={})
    assert denied_approval.status_code == 403, denied_approval.text
    _login_eco(client)
    locked_fabric_edit = client.patch(
        f"/api/usluga/models/{model['id']}/bom/{model['main_bom_id']}",
        json={"material_name": "Unsafe renamed fabric"},
    )
    assert locked_fabric_edit.status_code == 409, locked_fabric_edit.text
    locked_fabric_delete = client.delete(f"/api/usluga/models/{model['id']}/bom/{model['main_bom_id']}")
    assert locked_fabric_delete.status_code == 409, locked_fabric_delete.text

    approve_main = client.post(f"/api/cutting/records/{record_id}/approve-usluga-batch", json={})
    assert approve_main.status_code == 200, approve_main.text
    assert approve_main.json()["approval_status"] == "approved"
    with TestSessionLocal() as db:
        stored_cutting = db.get(WorkOrder, cutting["id"])
        assert stored_cutting.passed_qty == 12
        assert stored_cutting.status != "completed"
        assert db.get(Bundle, bundle_id).status == "created"

    approve_secondary = client.post(f"/api/cutting/records/{secondary_record_id}/approve-usluga-batch", json={})
    assert approve_secondary.status_code == 200, approve_secondary.text
    assert approve_secondary.json()["approval_status"] == "approved"
    updated_report_pieces = client.patch(
        f"/api/cutting/records/{secondary_record_id}/usluga-report-pieces",
        json={"report_piece_count": 8},
    )
    assert updated_report_pieces.status_code == 200, updated_report_pieces.text
    assert updated_report_pieces.json()["report_piece_count"] == 8
    invalid_main_report_edit = client.patch(
        f"/api/cutting/records/{record_id}/usluga-report-pieces",
        json={"report_piece_count": 8},
    )
    assert invalid_main_report_edit.status_code == 409, invalid_main_report_edit.text
    with TestSessionLocal() as db:
        stored_cutting = db.get(WorkOrder, cutting["id"])
        stored_secondary = db.get(CuttingRecord, secondary_record_id)
        sewing = db.query(WorkOrder).filter(
            WorkOrder.production_order_id == order["id"],
            WorkOrder.operation == "sewing",
        ).one()
        assert stored_cutting.status == "completed"
        assert stored_cutting.passed_qty == 12
        assert stored_secondary.report_piece_count == 8
        assert stored_secondary.cut_pieces == 0
        assert sewing.status == "in_progress"

    refreshed = client.get(f"/api/usluga/orders/{order['id']}")
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["material_usage_kg"] == 7.75
    with TestSessionLocal() as db:
        assert db.query(StockMovement).count() == movement_count_before
        assert db.query(MaterialReservation).filter(MaterialReservation.production_order_id == order["id"]).count() == 0
