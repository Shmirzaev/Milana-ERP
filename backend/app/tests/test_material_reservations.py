from uuid import uuid4


def _planning_headers(client) -> dict[str, str]:
    r = None
    for password in ("demo12345", "PlanningResetPassword123!"):
        r = client.post(
            "/api/auth/token",
            data={"username": "planning@example.com", "password": password},
        )
        if r.status_code == 200:
            break
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _create_branded_po(client, headers, qty: int = 100, model_id: int = 1) -> dict:
    r = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": model_id,
            "planned_quantity": qty,
            "items": [],
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _warehouse(client, headers, warehouse_type: str) -> dict:
    r = client.get("/api/inventory/warehouses", headers=headers)
    assert r.status_code == 200, r.text
    return next(row for row in r.json() if row["type"] == warehouse_type)


def _create_accessory_item(client, headers, unit: str = "pcs") -> dict:
    suffix = uuid4().hex[:8].upper()
    r = client.post(
        "/api/inventory/items",
        json={
            "sku": f"ACC-RES-{suffix}",
            "name": f"Reservation Test {suffix}",
            "category": "accessory",
            "unit": unit,
            "track_batch": True,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _receive_batch(client, headers, *, item_id: int, warehouse_id: int, quantity: float, unit: str, batch_no: str | None = None) -> dict:
    r = client.post(
        "/api/inventory/receive",
        json={
            "item_id": item_id,
            "batch_no": batch_no or f"B-RES-{uuid4().hex[:10].upper()}",
            "quantity": quantity,
            "unit": unit,
            "cost_per_unit": 1,
            "warehouse_id": warehouse_id,
            "qc_status": "passed",
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _fabric_item(client, headers) -> dict:
    r = client.get("/api/inventory/items?group=materials&q=FAB-COT-001", headers=headers)
    assert r.status_code == 200, r.text
    return next(row for row in r.json() if row["sku"] == "FAB-COT-001")


def _cutting_work_order(client, headers, production_order_id: int) -> dict:
    r = client.get(f"/api/work-orders?production_order_id={production_order_id}", headers=headers)
    assert r.status_code == 200, r.text
    return next(row for row in r.json() if row["operation"] == "cutting")


def _set_strict_material_reservation(value: bool) -> None:
    from app.db.session import SessionLocal
    from app.models import SystemSetting

    db = SessionLocal()
    try:
        row = db.query(SystemSetting).filter(SystemSetting.key == "preferences").first()
        if not row:
            row = SystemSetting(key="preferences", value_json={})
            db.add(row)
            db.flush()
        row.value_json = {
            **(row.value_json or {}),
            "require_material_reservation_before_cutting": value,
        }
        db.commit()
    finally:
        db.close()


def _create_material_reservation(
    client,
    headers,
    *,
    production_order_id: int,
    item_id: int,
    stock_batch_id: int,
    warehouse_id: int,
    quantity: float,
    unit: str = "kg",
) -> dict:
    r = client.post(
        "/api/inventory/reservations",
        json={
            "production_order_id": production_order_id,
            "item_id": item_id,
            "stock_batch_id": stock_batch_id,
            "warehouse_id": warehouse_id,
            "reserved_quantity": quantity,
            "unit": unit,
            "reservation_type": "material",
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _submit_cutting(client, headers, *, work_order_id: int, fabric_batch_id: int, input_quantity: float):
    return client.post(
        "/api/cutting/records",
        json={
            "work_order_id": work_order_id,
            "fabric_batch_id": fabric_batch_id,
            "input_quantity": input_quantity,
            "input_unit": "kg",
            "cut_pieces": 10,
            "passed_pieces": 10,
            "defective_pieces": 0,
            "waste_quantity": 0,
            "waste_unit": "kg",
            "bundles": [],
        },
        headers=headers,
    )


def test_reservation_plan_applies_bom_waste_percent(client, auth_headers):
    po = _create_branded_po(client, auth_headers, qty=100)

    r = client.get(
        f"/api/inventory/reservations/plan?production_order_id={po['id']}",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    fabric = next(row for row in r.json()["rows"] if row["item_sku"] == "FAB-COT-001")
    assert round(float(fabric["required_quantity"]), 2) == 151.20


def test_planning_fabric_batch_drives_material_reservation_plan(client, auth_headers):
    item = _fabric_item(client, auth_headers)
    warehouse = _warehouse(client, auth_headers, "fabric_storage")
    batch = _receive_batch(
        client,
        auth_headers,
        item_id=item["id"],
        warehouse_id=warehouse["id"],
        quantity=1000,
        unit="kg",
        batch_no=f"PLAN-FAB-{uuid4().hex[:8].upper()}",
    )

    response = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "planned_quantity": 10,
            "fabric_batch_id": batch["id"],
            "estimated_material_amount": 15,
            "estimated_material_unit": "kg",
            "items": [],
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    production_order = response.json()
    assert production_order["fabric_batch_id"] == batch["id"]
    assert production_order["estimated_material_code"] == item["sku"]

    plan = client.get(
        f"/api/inventory/reservations/plan?production_order_id={production_order['id']}",
        headers=auth_headers,
    )
    assert plan.status_code == 200, plan.text
    fabric = next(row for row in plan.json()["rows"] if row["item_id"] == item["id"])
    assert fabric["stock_batch_id"] == batch["id"]
    assert fabric["stock_batch_no"] == batch["batch_no"]
    assert {row["stock_batch_id"] for row in fabric["suggested_batches"]} == {batch["id"]}


def test_planning_accepts_available_fabric_batch_outside_model_bom(client, auth_headers):
    suffix = uuid4().hex[:8].upper()
    item_response = client.post(
        "/api/inventory/items",
        json={
            "sku": f"FAB-OVERRIDE-{suffix}",
            "name": f"Planning Fabric Override {suffix}",
            "category": "fabric",
            "unit": "kg",
            "track_batch": True,
        },
        headers=auth_headers,
    )
    assert item_response.status_code == 201, item_response.text
    item = item_response.json()
    warehouse = _warehouse(client, auth_headers, "fabric_storage")
    batch = _receive_batch(
        client,
        auth_headers,
        item_id=item["id"],
        warehouse_id=warehouse["id"],
        quantity=100,
        unit="kg",
        batch_no=f"PLAN-OVERRIDE-{suffix}",
    )

    response = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "planned_quantity": 10,
            "fabric_batch_id": batch["id"],
            "estimated_material_amount": 15,
            "estimated_material_unit": "kg",
            "items": [],
        },
        headers=auth_headers,
    )

    assert response.status_code == 201, response.text
    production_order = response.json()
    assert production_order["fabric_batch_id"] == batch["id"]
    assert production_order["estimated_material_code"] == item["sku"]


def test_multi_fabric_planning_flows_to_atomic_cutting_and_bundles(client, auth_headers):
    from app.db.session import SessionLocal
    from app.models import Bundle, CuttingMaterialUsage, CuttingRecord, StockMovement

    warehouse = _warehouse(client, auth_headers, "fabric_storage")
    first_item = _fabric_item(client, auth_headers)
    suffix = uuid4().hex[:8].upper()
    item_response = client.post(
        "/api/inventory/items",
        json={
            "sku": f"FAB-MULTI-{suffix}",
            "name": f"Secondary fabric {suffix}",
            "category": "fabric",
            "unit": "kg",
            "track_batch": True,
        },
        headers=auth_headers,
    )
    assert item_response.status_code == 201, item_response.text
    second_item = item_response.json()
    first_batch = _receive_batch(
        client,
        auth_headers,
        item_id=first_item["id"],
        warehouse_id=warehouse["id"],
        quantity=100,
        unit="kg",
        batch_no=f"MULTI-A-{suffix}",
    )
    second_batch = _receive_batch(
        client,
        auth_headers,
        item_id=second_item["id"],
        warehouse_id=warehouse["id"],
        quantity=100,
        unit="kg",
        batch_no=f"MULTI-B-{suffix}",
    )

    duplicate_response = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "planned_quantity": 10,
            "materials": [
                {"stock_batch_id": first_batch["id"], "estimated_quantity": 10, "unit": "kg"},
                {"stock_batch_id": first_batch["id"], "estimated_quantity": 2, "unit": "kg"},
            ],
            "items": [],
        },
        headers=auth_headers,
    )
    assert duplicate_response.status_code == 400, duplicate_response.text
    assert "same fabric batch" in duplicate_response.text.lower()

    create_response = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "planned_quantity": 10,
            "materials": [
                {"stock_batch_id": first_batch["id"], "estimated_quantity": 12, "unit": "kg"},
                {"stock_batch_id": second_batch["id"], "estimated_quantity": 4.5, "unit": "kg"},
            ],
            "items": [
                {
                    "model_id": 1,
                    "color": "white",
                    "size": "46",
                    "planned_quantity": 10,
                    "printing_required": False,
                },
            ],
        },
        headers=auth_headers,
    )
    assert create_response.status_code == 201, create_response.text
    production_order = create_response.json()
    assert production_order["fabric_batch_id"] == first_batch["id"]
    assert float(production_order["estimated_material_amount"]) == 12
    assert [row["stock_batch_id"] for row in production_order["materials"]] == [
        first_batch["id"],
        second_batch["id"],
    ]

    plan_response = client.get(
        f"/api/inventory/reservations/plan?production_order_id={production_order['id']}",
        headers=auth_headers,
    )
    assert plan_response.status_code == 200, plan_response.text
    planned_by_batch = {
        int(row["stock_batch_id"]): float(row["required_quantity"])
        for row in plan_response.json()["rows"]
        if row["stock_batch_id"] in {first_batch["id"], second_batch["id"]}
    }
    assert planned_by_batch == {first_batch["id"]: 12.0, second_batch["id"]: 4.5}

    cutting_work_order = _cutting_work_order(client, auth_headers, production_order["id"])
    cutting_payload = {
        "work_order_id": cutting_work_order["id"],
        "fabric_batch_id": first_batch["id"],
        "input_quantity": 11,
        "input_unit": "kg",
        "cut_pieces": 10,
        "passed_pieces": 10,
        "defective_pieces": 0,
        "waste_quantity": 0,
        "waste_unit": "kg",
        "bundles": [
            {
                "color": "white",
                "size": "46",
                "quantity": 10,
                "count": 1,
                "next": "sewing",
                "sewing_factory": "milana",
            },
        ],
    }
    incomplete_response = client.post(
        "/api/cutting/records",
        json={
            **cutting_payload,
            "materials": [
                {"stock_batch_id": first_batch["id"], "quantity": 11, "unit": "kg"},
            ],
        },
        headers=auth_headers,
    )
    assert incomplete_response.status_code == 400, incomplete_response.text

    db = SessionLocal()
    try:
        assert db.query(CuttingRecord.id).filter(
            CuttingRecord.work_order_id == cutting_work_order["id"],
        ).count() == 0
        assert db.query(Bundle.id).filter(
            Bundle.production_order_id == production_order["id"],
        ).count() == 0
    finally:
        db.close()

    cutting_response = client.post(
        "/api/cutting/records",
        json={
            **cutting_payload,
            "materials": [
                {"stock_batch_id": first_batch["id"], "quantity": 11, "unit": "kg"},
                {"stock_batch_id": second_batch["id"], "quantity": 4, "unit": "kg"},
            ],
        },
        headers=auth_headers,
    )
    assert cutting_response.status_code == 201, cutting_response.text
    cutting_record_id = cutting_response.json()["id"]
    assert len(cutting_response.json()["bundles"]) == 1
    assert [row["stock_batch_id"] for row in cutting_response.json()["materials"]] == [
        first_batch["id"],
        second_batch["id"],
    ]

    db = SessionLocal()
    try:
        usages = db.query(CuttingMaterialUsage).filter(
            CuttingMaterialUsage.cutting_record_id == cutting_record_id,
        ).order_by(CuttingMaterialUsage.position.asc()).all()
        assert [(row.stock_batch_id, float(row.quantity)) for row in usages] == [
            (first_batch["id"], 11.0),
            (second_batch["id"], 4.0),
        ]
        consumed_batch_ids = {
            row.batch_id
            for row in db.query(StockMovement).filter(
                StockMovement.reference_type == "CuttingRecord",
                StockMovement.reference_id == cutting_record_id,
            ).all()
        }
        assert {first_batch["id"], second_batch["id"]}.issubset(consumed_batch_ids)
    finally:
        db.close()


def test_reservation_plan_reports_no_bom_instead_of_ready(client, auth_headers):
    from app.db.session import SessionLocal
    from app.models import Model

    suffix = uuid4().hex[:8].upper()
    db = SessionLocal()
    try:
        model = Model(code=f"NO-BOM-{suffix}", name=f"No BOM {suffix}", status="approved")
        db.add(model)
        db.commit()
        db.refresh(model)
        model_id = int(model.id)
    finally:
        db.close()

    po = _create_branded_po(client, auth_headers, qty=10, model_id=model_id)

    r = client.get(
        f"/api/inventory/reservations/plan?production_order_id={po['id']}",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["status"] == "no_bom"
    assert payload["is_complete"] is True
    assert payload["rows"] == []
    assert payload["summary"]["line_count"] == 0

    status = client.get(
        f"/api/production-orders/{po['id']}/material-reservation-status",
        headers=auth_headers,
    )
    assert status.status_code == 200, status.text
    assert status.json()["plan"]["status"] == "no_bom"


def test_auto_reservation_uses_fifo_batches(client, auth_headers):
    item = _create_accessory_item(client, auth_headers, unit="roll")
    suffix = uuid4().hex[:8].upper()
    from app.db.session import SessionLocal
    from app.models import Model, ModelBOM

    db = SessionLocal()
    try:
        model = Model(code=f"RES-FIFO-{suffix}", name=f"Reservation FIFO {suffix}", status="approved")
        db.add(model)
        db.flush()
        db.add(ModelBOM(model_id=model.id, item_id=item["id"], quantity_per_piece=0.021, unit="roll", waste_percent=0))
        db.commit()
        model_id = int(model.id)
    finally:
        db.close()

    po = _create_branded_po(client, auth_headers, qty=100, model_id=model_id)
    warehouse = _warehouse(client, auth_headers, "accessory_storage")
    first = _receive_batch(client, auth_headers, item_id=item["id"], warehouse_id=warehouse["id"], quantity=1, unit="roll")
    second = _receive_batch(client, auth_headers, item_id=item["id"], warehouse_id=warehouse["id"], quantity=5, unit="roll")

    plan = client.get(
        f"/api/inventory/reservations/plan?production_order_id={po['id']}",
        headers=auth_headers,
    )
    assert plan.status_code == 200, plan.text
    thread_row = next(row for row in plan.json()["rows"] if row["item_id"] == item["id"])
    suggestions = thread_row["suggested_batches"]
    assert [row["stock_batch_id"] for row in suggestions[:2]] == [first["id"], second["id"]]
    assert round(float(suggestions[0]["suggested_quantity"]), 2) == 1.00
    assert round(float(suggestions[1]["suggested_quantity"]), 2) == 1.10

    auto = client.post(
        f"/api/production-orders/{po['id']}/reserve-materials",
        json={"mode": "full_remaining", "reserve_materials": False, "reserve_accessories": True, "reserve_packaging": False},
        headers=auth_headers,
    )
    assert auto.status_code == 201, auto.text
    reservations = [row for row in auto.json()["reservations"] if row["item_id"] == item["id"]]
    assert [row["stock_batch_id"] for row in reservations[:2]] == [first["id"], second["id"]]


def test_reservation_plan_respects_exact_bom_stock_batch(client, auth_headers):
    suffix = uuid4().hex[:8].upper()
    item = client.post(
        "/api/inventory/items",
        json={
            "sku": f"FAB-EXACT-{suffix}",
            "name": f"Exact Batch Fabric {suffix}",
            "category": "fabric",
            "unit": "kg",
            "track_batch": True,
        },
        headers=auth_headers,
    )
    assert item.status_code == 201, item.text
    item_body = item.json()
    warehouse = _warehouse(client, auth_headers, "fabric_storage")
    selected = _receive_batch(
        client,
        auth_headers,
        item_id=item_body["id"],
        warehouse_id=warehouse["id"],
        quantity=1,
        unit="kg",
        batch_no=f"EXACT-SELECTED-{suffix}",
    )
    other = _receive_batch(
        client,
        auth_headers,
        item_id=item_body["id"],
        warehouse_id=warehouse["id"],
        quantity=10,
        unit="kg",
        batch_no=f"EXACT-OTHER-{suffix}",
    )

    from app.db.session import SessionLocal
    from app.models import Model, ModelBOM

    db = SessionLocal()
    try:
        model = Model(code=f"EXACT-BATCH-{suffix}", name=f"Exact Batch {suffix}", status="approved")
        db.add(model)
        db.flush()
        db.add(
            ModelBOM(
                model_id=model.id,
                item_id=item_body["id"],
                stock_batch_id=selected["id"],
                quantity_per_piece=0.02,
                unit="kg",
                waste_percent=0,
            )
        )
        db.commit()
        model_id = int(model.id)
    finally:
        db.close()

    po = _create_branded_po(client, auth_headers, qty=100, model_id=model_id)
    plan = client.get(
        f"/api/inventory/reservations/plan?production_order_id={po['id']}",
        headers=auth_headers,
    )
    assert plan.status_code == 200, plan.text
    row = next(row for row in plan.json()["rows"] if row["item_id"] == item_body["id"])
    assert row["stock_batch_id"] == selected["id"]
    assert row["stock_batch_no"] == selected["batch_no"]
    assert round(float(row["required_quantity"]), 2) == 2.00
    assert round(float(row["available_stock"]), 2) == 1.00
    assert round(float(row["shortage"]), 2) == 1.00
    assert [batch["stock_batch_id"] for batch in row["suggested_batches"]] == [selected["id"]]
    assert other["id"] not in [batch["stock_batch_id"] for batch in row["suggested_batches"]]


def test_reservation_availability_release_and_over_reservation(client, auth_headers):
    po = _create_branded_po(client, auth_headers, qty=10)
    item = _create_accessory_item(client, auth_headers)
    warehouse = _warehouse(client, auth_headers, "accessory_storage")
    batch = _receive_batch(client, auth_headers, item_id=item["id"], warehouse_id=warehouse["id"], quantity=10, unit=item["unit"])

    create = client.post(
        "/api/inventory/reservations",
        json={
            "production_order_id": po["id"],
            "item_id": item["id"],
            "stock_batch_id": batch["id"],
            "warehouse_id": warehouse["id"],
            "reserved_quantity": 8,
            "unit": item["unit"],
            "reservation_type": "accessory",
        },
        headers=auth_headers,
    )
    assert create.status_code == 201, create.text
    reservation = create.json()

    stock = client.get(f"/api/inventory/stock?group=accessories&q={item['sku']}", headers=auth_headers)
    assert stock.status_code == 200, stock.text
    stock_row = next(row for row in stock.json() if row["item_sku"] == item["sku"])
    assert round(float(stock_row["quantity"]), 2) == 10.00
    assert round(float(stock_row["reserved_quantity"]), 2) == 8.00
    assert round(float(stock_row["available_quantity"]), 2) == 2.00

    over = client.post(
        "/api/inventory/reservations",
        json={
            "production_order_id": po["id"],
            "item_id": item["id"],
            "stock_batch_id": batch["id"],
            "warehouse_id": warehouse["id"],
            "reserved_quantity": 3,
            "unit": item["unit"],
            "reservation_type": "accessory",
        },
        headers=auth_headers,
    )
    assert over.status_code == 409, over.text

    release = client.post(f"/api/inventory/reservations/{reservation['id']}/release", headers=auth_headers)
    assert release.status_code == 200, release.text
    stock = client.get(f"/api/inventory/stock?group=accessories&q={item['sku']}", headers=auth_headers)
    stock_row = next(row for row in stock.json() if row["item_sku"] == item["sku"])
    assert round(float(stock_row["available_quantity"]), 2) == 10.00


def test_consume_reservation_creates_stock_movement(client, auth_headers):
    po = _create_branded_po(client, auth_headers, qty=10)
    item = _create_accessory_item(client, auth_headers)
    warehouse = _warehouse(client, auth_headers, "accessory_storage")
    batch = _receive_batch(client, auth_headers, item_id=item["id"], warehouse_id=warehouse["id"], quantity=5, unit=item["unit"])
    reservation = client.post(
        "/api/inventory/reservations",
        json={
            "production_order_id": po["id"],
            "item_id": item["id"],
            "stock_batch_id": batch["id"],
            "warehouse_id": warehouse["id"],
            "reserved_quantity": 2,
            "unit": item["unit"],
            "reservation_type": "accessory",
        },
        headers=auth_headers,
    ).json()

    consumed = client.post(
        f"/api/inventory/reservations/{reservation['id']}/consume",
        json={"quantity": 0.75},
        headers=auth_headers,
    )
    assert consumed.status_code == 200, consumed.text
    assert consumed.json()["status"] == "partially_consumed"
    assert round(float(consumed.json()["consumed_quantity"]), 2) == 0.75

    from app.db.session import SessionLocal
    from app.models import StockMovement

    db = SessionLocal()
    try:
        movement = (
            db.query(StockMovement)
            .filter(
                StockMovement.reference_type == "MaterialReservation",
                StockMovement.reference_id == reservation["id"],
                StockMovement.movement_type == "consume",
            )
            .first()
        )
        assert movement is not None
        assert round(float(movement.quantity or 0), 2) == 0.75
    finally:
        db.close()


def test_cutting_consumes_matching_reservations_fifo_without_double_deducting_stock(client, auth_headers):
    _set_strict_material_reservation(False)
    po = _create_branded_po(client, auth_headers, qty=10)
    cutting = _cutting_work_order(client, auth_headers, po["id"])
    item = _fabric_item(client, auth_headers)
    warehouse = _warehouse(client, auth_headers, "fabric_storage")
    batch = _receive_batch(
        client,
        auth_headers,
        item_id=item["id"],
        warehouse_id=warehouse["id"],
        quantity=20,
        unit="kg",
    )
    first = _create_material_reservation(
        client,
        auth_headers,
        production_order_id=po["id"],
        item_id=item["id"],
        stock_batch_id=batch["id"],
        warehouse_id=warehouse["id"],
        quantity=3,
    )
    second = _create_material_reservation(
        client,
        auth_headers,
        production_order_id=po["id"],
        item_id=item["id"],
        stock_batch_id=batch["id"],
        warehouse_id=warehouse["id"],
        quantity=4,
    )

    created = _submit_cutting(
        client,
        auth_headers,
        work_order_id=cutting["id"],
        fabric_batch_id=batch["id"],
        input_quantity=5,
    )
    assert created.status_code == 201, created.text
    cutting_record_id = created.json()["id"]

    from app.db.session import SessionLocal
    from app.models import MaterialReservation, StockBatch, StockMovement

    db = SessionLocal()
    try:
        refreshed_batch = db.get(StockBatch, batch["id"])
        assert round(float(refreshed_batch.quantity or 0), 2) == 15.00

        first_row = db.get(MaterialReservation, first["id"])
        second_row = db.get(MaterialReservation, second["id"])
        assert first_row.status == "consumed"
        assert round(float(first_row.consumed_quantity or 0), 2) == 3.00
        assert second_row.status == "partially_consumed"
        assert round(float(second_row.consumed_quantity or 0), 2) == 2.00

        cutting_movements = (
            db.query(StockMovement)
            .filter(
                StockMovement.reference_type == "CuttingRecord",
                StockMovement.reference_id == cutting_record_id,
                StockMovement.batch_id == batch["id"],
                StockMovement.movement_type == "consume",
            )
            .all()
        )
        assert round(sum(float(row.quantity or 0) for row in cutting_movements), 2) == 5.00
        reservation_movements = (
            db.query(StockMovement)
            .filter(
                StockMovement.reference_type == "MaterialReservation",
                StockMovement.reference_id.in_([first["id"], second["id"]]),
                StockMovement.movement_type == "consume",
            )
            .count()
        )
        assert reservation_movements == 0
    finally:
        db.close()


def test_cutting_nonstrict_consumes_reserved_part_then_direct_remainder(client, auth_headers):
    _set_strict_material_reservation(False)
    po = _create_branded_po(client, auth_headers, qty=10)
    cutting = _cutting_work_order(client, auth_headers, po["id"])
    item = _fabric_item(client, auth_headers)
    warehouse = _warehouse(client, auth_headers, "fabric_storage")
    batch = _receive_batch(
        client,
        auth_headers,
        item_id=item["id"],
        warehouse_id=warehouse["id"],
        quantity=10,
        unit="kg",
    )
    reservation = _create_material_reservation(
        client,
        auth_headers,
        production_order_id=po["id"],
        item_id=item["id"],
        stock_batch_id=batch["id"],
        warehouse_id=warehouse["id"],
        quantity=2,
    )

    created = _submit_cutting(
        client,
        auth_headers,
        work_order_id=cutting["id"],
        fabric_batch_id=batch["id"],
        input_quantity=5,
    )
    assert created.status_code == 201, created.text
    cutting_record_id = created.json()["id"]

    from app.db.session import SessionLocal
    from app.models import MaterialReservation, StockBatch, StockMovement

    db = SessionLocal()
    try:
        refreshed_batch = db.get(StockBatch, batch["id"])
        assert round(float(refreshed_batch.quantity or 0), 2) == 5.00
        refreshed_reservation = db.get(MaterialReservation, reservation["id"])
        assert refreshed_reservation.status == "consumed"
        assert round(float(refreshed_reservation.consumed_quantity or 0), 2) == 2.00

        cutting_total = (
            db.query(StockMovement)
            .filter(
                StockMovement.reference_type == "CuttingRecord",
                StockMovement.reference_id == cutting_record_id,
                StockMovement.batch_id == batch["id"],
                StockMovement.movement_type == "consume",
            )
            .all()
        )
        assert round(sum(float(row.quantity or 0) for row in cutting_total), 2) == 5.00
    finally:
        db.close()


def test_cutting_strict_blocks_missing_or_insufficient_matching_reservation(client, auth_headers):
    _set_strict_material_reservation(True)
    try:
        item = _fabric_item(client, auth_headers)
        warehouse = _warehouse(client, auth_headers, "fabric_storage")

        missing_po = _create_branded_po(client, auth_headers, qty=10)
        missing_cutting = _cutting_work_order(client, auth_headers, missing_po["id"])
        missing_batch = _receive_batch(
            client,
            auth_headers,
            item_id=item["id"],
            warehouse_id=warehouse["id"],
            quantity=10,
            unit="kg",
        )
        missing = _submit_cutting(
            client,
            auth_headers,
            work_order_id=missing_cutting["id"],
            fabric_batch_id=missing_batch["id"],
            input_quantity=3,
        )
        assert missing.status_code == 409, missing.text
        assert "Insufficient material reservation for cutting" in missing.text

        insufficient_po = _create_branded_po(client, auth_headers, qty=10)
        insufficient_cutting = _cutting_work_order(client, auth_headers, insufficient_po["id"])
        insufficient_batch = _receive_batch(
            client,
            auth_headers,
            item_id=item["id"],
            warehouse_id=warehouse["id"],
            quantity=10,
            unit="kg",
        )
        reservation = _create_material_reservation(
            client,
            auth_headers,
            production_order_id=insufficient_po["id"],
            item_id=item["id"],
            stock_batch_id=insufficient_batch["id"],
            warehouse_id=warehouse["id"],
            quantity=1,
        )
        insufficient = _submit_cutting(
            client,
            auth_headers,
            work_order_id=insufficient_cutting["id"],
            fabric_batch_id=insufficient_batch["id"],
            input_quantity=3,
        )
        assert insufficient.status_code == 409, insufficient.text
        assert "Insufficient material reservation for cutting" in insufficient.text

        from app.db.session import SessionLocal
        from app.models import MaterialReservation, StockBatch

        db = SessionLocal()
        try:
            unchanged_batch = db.get(StockBatch, insufficient_batch["id"])
            unchanged_reservation = db.get(MaterialReservation, reservation["id"])
            assert round(float(unchanged_batch.quantity or 0), 2) == 10.00
            assert unchanged_reservation.status == "reserved"
            assert round(float(unchanged_reservation.consumed_quantity or 0), 2) == 0.00
        finally:
            db.close()
    finally:
        _set_strict_material_reservation(False)


def test_cutting_nonstrict_allows_direct_batch_consumption_without_reservation(client, auth_headers):
    _set_strict_material_reservation(False)
    po = _create_branded_po(client, auth_headers, qty=10)
    cutting = _cutting_work_order(client, auth_headers, po["id"])
    item = _fabric_item(client, auth_headers)
    warehouse = _warehouse(client, auth_headers, "fabric_storage")
    batch = _receive_batch(
        client,
        auth_headers,
        item_id=item["id"],
        warehouse_id=warehouse["id"],
        quantity=10,
        unit="kg",
    )

    created = _submit_cutting(
        client,
        auth_headers,
        work_order_id=cutting["id"],
        fabric_batch_id=batch["id"],
        input_quantity=4,
    )
    assert created.status_code == 201, created.text
    cutting_record_id = created.json()["id"]

    from app.db.session import SessionLocal
    from app.models import StockBatch, StockMovement

    db = SessionLocal()
    try:
        refreshed_batch = db.get(StockBatch, batch["id"])
        assert round(float(refreshed_batch.quantity or 0), 2) == 6.00
        movement = (
            db.query(StockMovement)
            .filter(
                StockMovement.reference_type == "CuttingRecord",
                StockMovement.reference_id == cutting_record_id,
                StockMovement.batch_id == batch["id"],
                StockMovement.movement_type == "consume",
            )
            .one()
        )
        assert round(float(movement.quantity or 0), 2) == 4.00
    finally:
        db.close()


def test_cutting_start_guard_respects_setting(client, auth_headers):
    po = _create_branded_po(client, auth_headers, qty=25)
    wos = client.get(f"/api/work-orders?production_order_id={po['id']}", headers=auth_headers).json()
    cutting = next(row for row in wos if row["operation"] == "cutting")

    allowed = client.post(f"/api/work-orders/{cutting['id']}/start", headers=auth_headers)
    assert allowed.status_code == 200, allowed.text

    from app.db.session import SessionLocal
    from app.models import SystemSetting

    db = SessionLocal()
    try:
        row = db.query(SystemSetting).filter(SystemSetting.key == "preferences").first()
        if not row:
            row = SystemSetting(key="preferences", value_json={})
            db.add(row)
            db.flush()
        row.value_json = {
            **(row.value_json or {}),
            "require_material_reservation_before_cutting": True,
        }
        db.commit()
    finally:
        db.close()

    blocked_po = _create_branded_po(client, auth_headers, qty=25)
    wos = client.get(f"/api/work-orders?production_order_id={blocked_po['id']}", headers=auth_headers).json()
    blocked_cutting = next(row for row in wos if row["operation"] == "cutting")
    blocked = client.post(f"/api/work-orders/{blocked_cutting['id']}/start", headers=auth_headers)
    assert blocked.status_code == 400, blocked.text
    assert "Material reservation is incomplete" in blocked.text

    db = SessionLocal()
    try:
        row = db.query(SystemSetting).filter(SystemSetting.key == "preferences").first()
        row.value_json = {
            **(row.value_json or {}),
            "require_material_reservation_before_cutting": False,
        }
        db.commit()
    finally:
        db.close()


def test_reservation_permission_denied_for_consume(client, auth_headers):
    po = _create_branded_po(client, auth_headers, qty=10)
    item = _create_accessory_item(client, auth_headers)
    warehouse = _warehouse(client, auth_headers, "accessory_storage")
    batch = _receive_batch(client, auth_headers, item_id=item["id"], warehouse_id=warehouse["id"], quantity=5, unit=item["unit"])
    reservation = client.post(
        "/api/inventory/reservations",
        json={
            "production_order_id": po["id"],
            "item_id": item["id"],
            "stock_batch_id": batch["id"],
            "warehouse_id": warehouse["id"],
            "reserved_quantity": 1,
            "unit": item["unit"],
            "reservation_type": "accessory",
        },
        headers=auth_headers,
    ).json()

    denied = client.post(
        f"/api/inventory/reservations/{reservation['id']}/consume",
        json={"quantity": 0.5},
        headers=_planning_headers(client),
    )
    assert denied.status_code == 403, denied.text
