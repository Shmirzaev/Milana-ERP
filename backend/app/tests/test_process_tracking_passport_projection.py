from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import event

from app.models import CuttingPassport, Model, ProductionOrder
from app.tests.conftest import TestSessionLocal, test_engine


def test_process_tracking_projects_only_cutting_passport_output_fields(client, auth_headers):
    marker = uuid4().hex[:10]
    with TestSessionLocal() as db:
        model = Model(
            code=f"PT-PASSPORT-{marker}",
            name="Passport projection model",
            status="approved",
        )
        db.add(model)
        db.flush()
        order = ProductionOrder(
            production_no=f"PT-PASSPORT-PO-{marker}",
            production_type="branded_stock",
            model_id=model.id,
            status="new",
            planned_quantity=1,
        )
        db.add(order)
        db.flush()
        db.add(CuttingPassport(
            passport_no=f"PT-PASSPORT-CP-{marker}",
            date=datetime(2026, 9, 23, tzinfo=timezone.utc),
            production_order_id=order.id,
            lot_no=f"LOT-{marker}",
            materials=[{"unused_payload": "x" * 10_000}],
        ))
        db.commit()
        production_no = order.production_no
        passport_no = f"PT-PASSPORT-CP-{marker}"

    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        response = client.get(
            "/api/process-tracking",
            params={"include_total": "true", "page_size": 1, "q": production_no},
            headers=auth_headers,
        )
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)

    assert response.status_code == 200, response.text
    row = response.json()["rows"][0]
    assert row["cutting_passport_no"] == passport_no
    assert row["cutting_passports"] == [{
        "id": row["cutting_passport_id"],
        "passport_no": passport_no,
        "lot_no": f"LOT-{marker}",
        "date": "2026-09-23T00:00:00",
    }]
    passport_reads = [statement for statement in statements if " from cutting_passports " in statement]
    assert len(passport_reads) == 1, statements
    selected_columns = passport_reads[0].split(" from ", 1)[0]
    assert "cutting_passports.passport_no" in selected_columns
    assert "cutting_passports.lot_no" in selected_columns
    assert "cutting_passports.date" in selected_columns
    assert "cutting_passports.materials" not in selected_columns
    assert "cutting_passports.notes" not in selected_columns
