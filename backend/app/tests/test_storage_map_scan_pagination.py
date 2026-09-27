from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.packages import storage_map, storage_map_model_packages, storage_map_summary
from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import AuditLog, Model, Package, ProductionOrder, Role, User


def _seed(count: int) -> int:
    marker = uuid4().hex
    with SessionLocal() as db:
        model = Model(code=f"SCAN-{marker}", name=f"Scan {marker}")
        db.add(model)
        db.flush()
        order = ProductionOrder(
            production_no=f"SCAN-{marker}",
            production_type="branded_stock",
            model_id=model.id,
            planned_quantity=count,
        )
        db.add(order)
        db.flush()
        db.add_all([
            Package(
                package_no=f"SCAN-{marker}-{index:04d}",
                barcode=f"SCAN-BC-{marker}-{index:04d}",
                production_order_id=order.id,
                model_id=model.id,
                color="Blue",
                total_quantity=index + 1,
                capacity=60,
                status="received_in_storage",
                storage_cell="A-01",
                storage_shelf="1",
            )
            for index in range(count)
        ])
        db.commit()
        return int(model.id)


@pytest.mark.parametrize("count", [1, 50, 401])
def test_scan_model_page_is_bounded_with_exact_total(count):
    model_id = _seed(count)
    with SessionLocal() as db:
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().lower().startswith("select"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            first = storage_map_model_packages(model_id, db, None)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

        assert first["total"] == count
        assert len(first["rows"]) == min(count, 50)
        assert first["has_more"] is (count > 50)
        assert first["rows"][0].model_id == model_id
        assert len(statements) == 2, statements
        assert any(" limit ? offset ?" in statement for statement in statements)
        if count > 50:
            second = storage_map_model_packages(model_id, db, None, page=2)
            assert len(second["rows"]) == min(count - 50, 50)
            assert {row.id for row in first["rows"]}.isdisjoint(row.id for row in second["rows"])


def test_scan_summary_counts_match_legacy_and_auth_is_read_only(client):
    model_id = _seed(3)
    with SessionLocal() as db:
        role = Role(name=f"Scan map reader {uuid4().hex}", permissions=[])
        db.add(role)
        db.flush()
        reader = User(
            name="Scan map reader",
            email=f"scan-map-reader-{uuid4().hex}@example.com",
            password_hash="unused-pagination-hash",
            role_id=role.id,
            factory_code="MIL",
            extra_permissions=[],
            is_active=True,
        )
        db.add(reader)
        db.commit()
        headers = {"Authorization": f"Bearer {create_access_token(reader.id)}"}
        before = (db.query(Package).count(), db.query(AuditLog).count())

    assert client.get("/api/packages/storage-map/summary").status_code == 401
    assert client.get(f"/api/packages/storage-map/models/{model_id}").status_code == 401
    summary_response = client.get("/api/packages/storage-map/summary", headers=headers)
    assert summary_response.status_code == 200, summary_response.text
    summary = summary_response.json()
    with SessionLocal() as db:
        legacy = storage_map(db, None)
    assert summary["summary"] == legacy["summary"]
    assert [(cell["code"], cell["count"], cell["status"]) for cell in summary["cells"]] == [
        (cell["code"], cell["count"], cell["status"]) for cell in legacy["cells"]
    ]
    assert next(cell for cell in summary["cells"] if cell["code"] == "A-01")["count"] >= 3
    assert "placements" not in summary
    page_response = client.get(
        f"/api/packages/storage-map/models/{model_id}",
        params={"page_size": 2},
        headers=headers,
    )
    assert page_response.status_code == 200, page_response.text
    assert page_response.json()["total"] == 3
    assert len(page_response.json()["rows"]) == 2
    assert page_response.json()["has_more"] is True
    assert client.get(
        f"/api/packages/storage-map/models/{model_id}",
        params={"page_size": 101},
        headers=headers,
    ).status_code == 422

    with SessionLocal() as db:
        after = (db.query(Package).count(), db.query(AuditLog).count())
    assert after == before


def test_scan_summary_uses_one_grouped_query():
    _seed(1)
    with SessionLocal() as db:
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().lower().startswith("select"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            payload = storage_map_summary(db, None)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
    assert payload["summary"]["cells_total"] == len(payload["cells"])
    assert len(statements) == 1, statements
    assert "group by case when" in statements[0]
