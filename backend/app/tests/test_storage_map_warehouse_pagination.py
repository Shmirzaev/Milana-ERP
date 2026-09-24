from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import event

from app.api.routes.packages import (
    storage_map_cell_packages,
    storage_map_page_overview,
    storage_map_rack_preview,
)
from app.db.session import SessionLocal
from app.models import Model, Package, PackageScanLog, ProductionOrder


def _seed_cell_packages(count: int) -> tuple[int, str, int]:
    marker = uuid4().hex[:10].upper()
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        model = Model(code=f"MAP-{marker}", name=f"Map model {marker}", product_type="shirt")
        db.add(model)
        db.flush()
        order = ProductionOrder(
            production_no=f"MAP-PO-{marker}",
            production_type="branded_stock",
            model_id=model.id,
            planned_quantity=count,
        )
        db.add(order)
        db.flush()
        packages = [
            Package(
                package_no=f"MAP-PKG-{marker}-{index:04d}",
                barcode=f"MAP-BC-{marker}-{index:04d}",
                production_order_id=order.id,
                model_id=model.id,
                color="Blue",
                total_quantity=index + 1,
                capacity=60,
                status="received_in_storage",
                storage_cell="A-01",
                storage_shelf="S1",
                storage_placed_at=now,
            )
            for index in range(count)
        ]
        db.add_all(packages)
        db.commit()
        return int(model.id), marker, int(packages[-1].id)


def test_warehouse_overview_and_rack_preview_are_exact_and_bounded():
    model_id, marker, newest_package_id = _seed_cell_packages(401)
    today_from = datetime.now(timezone.utc) - timedelta(hours=1)
    today_to = datetime.now(timezone.utc) + timedelta(hours=1)
    with SessionLocal() as db:
        statements: list[str] = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().lower().startswith("select"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            overview = storage_map_page_overview(
                db,
                None,
                today_from=today_from,
                today_to=today_to,
            )
            page_one = storage_map_cell_packages("A-01", "S1", db, None)
            page_two = storage_map_cell_packages("A-01", "S1", db, None, page=2)
            previews = storage_map_rack_preview("A", db, None)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    cell = next(row for row in overview["cells"] if row["code"] == "A-01")
    zone = next(row for row in overview["zones"] if row["id"] == "A")
    assert overview["summary"]["packages_on_map"] == 401
    assert overview["summary"]["total_qty"] == sum(range(1, 402))
    assert cell["count"] == 401
    assert cell["quantity"] == sum(range(1, 402))
    assert zone["sku_count"] == 1
    assert zone["moves_today"] == 401
    assert page_one["total"] == 401
    assert page_one["total_quantity"] == sum(range(1, 402))
    assert len(page_one["rows"]) == 50
    assert page_one["has_more"] is True
    assert page_two["page"] == 2
    assert len(page_two["rows"]) == 50
    assert {row["id"] for row in page_one["rows"]}.isdisjoint(row["id"] for row in page_two["rows"])
    assert len(previews) <= 24
    assert len(previews) == 1
    assert previews[0]["id"] == newest_package_id
    assert all(" limit " in statement for statement in statements if " offset " in statement)
    assert not any("model_images" in statement or "model_boms" in statement for statement in statements)
    assert model_id > 0 and marker


def test_warehouse_cell_package_search_and_auth_are_scoped(client, auth_headers):
    model_id, marker, _newest = _seed_cell_packages(3)
    assert client.get("/api/packages/storage-map/overview").status_code == 401
    assert client.get("/api/packages/storage-map/rack-preview", params={"zone": "A"}).status_code == 401
    assert client.get(
        "/api/packages/storage-map/cell-packages",
        params={"cell": "A-01", "shelf": "S1"},
    ).status_code == 401

    overview = client.get(
        "/api/packages/storage-map/overview",
        params={
            "today_from": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
            "today_to": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        },
        headers=auth_headers,
    )
    assert overview.status_code == 200, overview.text
    assert overview.json()["summary"]["total_qty"] >= 6
    assert next(cell for cell in overview.json()["cells"] if cell["code"] == "A-01")["quantity"] >= 6
    matched_overview = client.get(
        "/api/packages/storage-map/overview",
        params={"model_query": marker},
        headers=auth_headers,
    )
    assert matched_overview.status_code == 200, matched_overview.text
    matched_cell = next(cell for cell in matched_overview.json()["cells"] if cell["code"] == "A-01")
    assert matched_cell["count"] == 3
    assert matched_cell["matched_count"] == 3
    assert matched_overview.json()["summary"]["packages_on_map"] >= 3
    assert matched_overview.json()["summary"]["matched_packages"] == 3
    rack_preview = client.get(
        "/api/packages/storage-map/rack-preview",
        params={"zone": "A"},
        headers=auth_headers,
    )
    assert rack_preview.status_code == 200, rack_preview.text
    assert len(rack_preview.json()) == 1
    assert rack_preview.json()[0]["model_id"] == model_id

    response = client.get(
        "/api/packages/storage-map/cell-packages",
        params={"cell": "A-01", "shelf": "S1", "page_size": 2},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] == 3
    assert payload["shelf_total"] == 3
    assert payload["total_quantity"] == 6
    assert len(payload["rows"]) == 2
    assert payload["has_more"] is True
    assert {row["model_id"] for row in payload["rows"]} == {model_id}
    fallback_page = client.get(
        "/api/packages/storage-map/cell-packages",
        params={"cell": "A-01", "shelf": "S2", "page_size": 2},
        headers=auth_headers,
    )
    assert fallback_page.status_code == 200, fallback_page.text
    assert fallback_page.json()["total"] == 3
    assert fallback_page.json()["shelf_total"] == 0
    assert {row["storage_shelf"] for row in fallback_page.json()["rows"]} == {"S1"}

    invalid_cell = client.get(
        "/api/packages/storage-map/cell-packages",
        params={"cell": "A-99", "shelf": "S1"},
        headers=auth_headers,
    )
    assert invalid_cell.status_code == 422


def _seed_mixed_model_move() -> int:
    marker = uuid4().hex[:10].upper()
    with SessionLocal() as db:
        models = [
            Model(code=f"MOVE-{marker}-{index}", name=f"Move model {index}", product_type="shirt")
            for index in (1, 2)
        ]
        db.add_all(models)
        db.flush()
        orders = [
            ProductionOrder(
                production_no=f"MOVE-PO-{marker}-{index}",
                production_type="branded_stock",
                model_id=model.id,
                planned_quantity=1,
            )
            for index, model in enumerate(models, start=1)
        ]
        db.add_all(orders)
        db.flush()
        packages = [
            Package(
                package_no=f"MOVE-PKG-{marker}-{index}",
                barcode=f"MOVE-BC-{marker}-{index}",
                production_order_id=order.id,
                model_id=model.id,
                color="Blue",
                total_quantity=1,
                capacity=60,
                status="received_in_storage",
                storage_cell=cell,
                storage_shelf="S1",
            )
            for index, (model, order, cell) in enumerate(
                ((models[0], orders[0], "B-01"), (models[1], orders[1], "A-01")),
                start=1,
            )
        ]
        db.add_all(packages)
        db.commit()
        return int(packages[1].id)


def test_server_rejects_mixed_model_move_without_explicit_opt_in(client, auth_headers):
    incoming_id = _seed_mixed_model_move()
    rejected = client.post(
        f"/api/packages/{incoming_id}/place-on-map",
        json={"storage_cell": "B-01", "storage_shelf": "S1", "enforce_model_guard": True},
        headers=auth_headers,
    )
    assert rejected.status_code == 400
    assert "different model" in rejected.json()["detail"]
    with SessionLocal() as db:
        incoming = db.get(Package, incoming_id)
        assert (incoming.storage_cell, incoming.storage_shelf) == ("A-01", "S1")
        assert db.query(PackageScanLog).filter_by(package_id=incoming_id).count() == 0

    allowed = client.post(
        f"/api/packages/{incoming_id}/place-on-map",
        json={"storage_cell": "B-01", "storage_shelf": "S1", "allow_mixed_models": True, "enforce_model_guard": True},
        headers=auth_headers,
    )
    assert allowed.status_code == 200, allowed.text
    with SessionLocal() as db:
        incoming = db.get(Package, incoming_id)
        assert (incoming.storage_cell, incoming.storage_shelf) == ("B-01", "S1")
        assert db.query(PackageScanLog).filter_by(package_id=incoming_id).count() == 1


def test_legacy_map_move_clients_keep_existing_mixed_cell_behavior(client, auth_headers):
    incoming_id = _seed_mixed_model_move()
    legacy = client.post(
        f"/api/packages/{incoming_id}/place-on-map",
        json={"storage_cell": "B-01", "storage_shelf": "S1"},
        headers=auth_headers,
    )
    assert legacy.status_code == 200, legacy.text
    with SessionLocal() as db:
        incoming = db.get(Package, incoming_id)
        assert (incoming.storage_cell, incoming.storage_shelf) == ("B-01", "S1")

