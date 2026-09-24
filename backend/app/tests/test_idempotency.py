from uuid import uuid4

from sqlalchemy import event

from app.db.session import SessionLocal
from app.models import IdempotencyRecord, PackagingRecord, PackageScanLog, Payment, ShipmentScanLog, User, WorkOrder
from app.services.idempotency import replay_idempotent_response, request_fingerprint


def test_idempotency_replay_projects_only_response_validation_columns():
    key = f"projection-{uuid4().hex}"
    payload = {"amount": 12, "method": "cash"}
    response = {"id": 47, "ok": True}
    statements = []
    with SessionLocal() as db:
        user = db.query(User).first()
        assert user is not None
        db.add(IdempotencyRecord(
            scope="test.projection",
            key=key,
            request_hash=request_fingerprint(payload),
            response_json=response,
            status_code=201,
            user_id=user.id,
        ))
        db.commit()
        user_id = user.id
        legacy_sql = str(
            db.query(IdempotencyRecord)
            .filter(IdempotencyRecord.scope == "test.projection", IdempotencyRecord.key == key)
            .statement.compile(dialect=db.bind.dialect)
        ).lower()
        bind = db.get_bind()

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().lower().startswith("select"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(bind, "before_cursor_execute", capture)
    try:
        with SessionLocal() as db:
            user = db.get(User, user_id)
            result = replay_idempotent_response(
                db,
                user=user,
                scope="test.projection",
                key=key,
                payload=payload,
            )
            assert result == response
    finally:
        event.remove(bind, "before_cursor_execute", capture)

    record_read = next(statement for statement in statements if " from idempotency_records " in statement)
    assert "idempotency_records.user_id" in record_read
    assert "idempotency_records.request_hash" in record_read
    assert "idempotency_records.response_json" in record_read
    assert "idempotency_records.status_code" not in record_read
    assert "idempotency_records.status_code" in legacy_sql


def _model_id(client, headers) -> int:
    r = client.get("/api/models", headers=headers)
    assert r.status_code == 200, r.text
    rows = r.json()
    approved = next((row for row in rows if row.get("status") == "approved"), None)
    if approved:
        return int(approved["id"])
    suffix = uuid4().hex[:8].upper()
    r = client.post(
        "/api/models",
        json={"code": f"IDEMP-{suffix}", "name": "Idempotency model", "status": "approved"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def _create_customer(client, headers) -> int:
    suffix = uuid4().hex[:8]
    r = client.post(
        "/api/customers",
        json={
            "name": f"Idempotent Customer {suffix}",
            "phone": "+998900000001",
            "email": f"idempotent-{suffix}@example.com",
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def _create_order_and_invoice(client, headers) -> dict:
    model_id = _model_id(client, headers)
    customer_id = _create_customer(client, headers)
    r = client.post(
        "/api/sales-orders",
        json={
            "customer_id": customer_id,
            "order_type": "client_order",
            "items": [{"model_id": model_id, "color": "black", "size": "M", "quantity": 1, "unit_price": 125}],
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    sales_order_id = int(r.json()["id"])
    r = client.post("/api/finance/invoices", json={"sales_order_id": sales_order_id}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _create_package(client, headers) -> dict:
    suffix = uuid4().hex[:8]
    color = f"idemp-{suffix}"
    model_id = _model_id(client, headers)
    r = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": model_id,
            "planned_quantity": 12,
            "items": [{"model_id": model_id, "color": color, "size": "M", "planned_quantity": 12}],
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    production_order_id = int(r.json()["id"])
    with SessionLocal() as db:
        work_order = db.query(WorkOrder).filter_by(
            production_order_id=production_order_id,
            operation="packaging",
        ).one()
        db.add(PackagingRecord(work_order_id=work_order.id, input_qty=12, packed_qty=12, damaged_qty=0))
        db.commit()
    r = client.post(
        "/api/packages",
        json={
            "production_order_id": production_order_id,
            "model_id": model_id,
            "color": color,
            "capacity": 60,
            "items": [{"model_id": model_id, "color": color, "size": "M", "quantity": 12}],
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_finance_payment_idempotency_key_prevents_duplicate_payment(client, auth_headers):
    invoice = _create_order_and_invoice(client, auth_headers)
    key = f"pay-{uuid4().hex}"
    headers = {**auth_headers, "Idempotency-Key": key}
    payload = {"invoice_id": invoice["id"], "amount": 25, "payment_method": "cash"}

    first = client.post("/api/finance/payments", json=payload, headers=headers)
    second = client.post("/api/finance/payments", json={**payload, "amount": "25.00"}, headers=headers)

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json()["id"] == first.json()["id"]

    db = SessionLocal()
    try:
        count = db.query(Payment).filter(Payment.invoice_id == invoice["id"], Payment.amount == 25).count()
    finally:
        db.close()
    assert count == 1


def test_package_receive_idempotency_key_prevents_duplicate_scan_log(client, auth_headers):
    package = _create_package(client, auth_headers)
    key = f"receive-{uuid4().hex}"
    headers = {**auth_headers, "Idempotency-Key": key}
    payload = {"storage_cell": "A-01", "storage_shelf": "S1"}

    first = client.post(f"/api/packages/{package['id']}/receive-storage", json=payload, headers=headers)
    second = client.post(f"/api/packages/{package['id']}/receive-storage", json=payload, headers=headers)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first.json()["id"]

    db = SessionLocal()
    try:
        count = (
            db.query(PackageScanLog)
            .filter(PackageScanLog.package_id == package["id"], PackageScanLog.scan_type == "received_storage")
            .count()
        )
    finally:
        db.close()
    assert count == 1


def test_shipment_scan_idempotency_key_replays_first_scan(client, auth_headers):
    package = _create_package(client, auth_headers)
    receive = client.post(f"/api/packages/{package['id']}/receive-storage", headers=auth_headers)
    assert receive.status_code == 200, receive.text
    package = receive.json()

    shipment = client.post("/api/shipments", json={"notes": "idempotent scan"}, headers=auth_headers)
    assert shipment.status_code == 201, shipment.text
    shipment_id = int(shipment.json()["id"])
    added = client.post(f"/api/shipments/{shipment_id}/add-package?package_id={package['id']}", headers=auth_headers)
    assert added.status_code == 200, added.text

    key = f"scan-{uuid4().hex}"
    headers = {**auth_headers, "Idempotency-Key": key}
    payload = {"code": package["package_no"]}

    first = client.post(f"/api/shipments/{shipment_id}/scan-package", json=payload, headers=headers)
    second = client.post(f"/api/shipments/{shipment_id}/scan-package", json=payload, headers=headers)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["sign"] == "success"
    assert second.json() == first.json()

    db = SessionLocal()
    try:
        count = (
            db.query(ShipmentScanLog)
            .filter(
                ShipmentScanLog.shipment_id == shipment_id,
                ShipmentScanLog.package_id == package["id"],
                ShipmentScanLog.scan_result == "matched",
            )
            .count()
        )
    finally:
        db.close()
    assert count == 1
