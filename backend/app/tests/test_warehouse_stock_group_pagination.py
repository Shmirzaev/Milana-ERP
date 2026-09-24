from hashlib import sha256
from uuid import uuid4

import pytest

from app.api.routes.packages import warehouse_stock_page
from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import LegacyStockReceipt, Model, Package, ProductionOrder, Role, User
from app.tests.conftest import TestSessionLocal


def _seed_stock_groups(count: int) -> tuple[str, int]:
    marker = uuid4().hex[:12]
    with TestSessionLocal() as db:
        model = Model(code=f"WH-STOCK-{marker}", name=f"Warehouse stock {marker}", status="approved")
        db.add(model)
        db.flush()
        order = ProductionOrder(
            production_no=f"WH-STOCK-{marker}",
            production_type="branded_stock",
            model_id=model.id,
            planned_quantity=count,
        )
        db.add(order)
        db.flush()
        packages = []
        for index in range(count):
            cell = "A-01" if index < 3 else f"A-{index:02d}"
            packages.append(Package(
                package_no=f"WH-STOCK-PKG-{marker}-{index:04d}",
                barcode=f"WH-STOCK-BC-{marker}-{index:04d}",
                production_order_id=order.id,
                model_id=model.id,
                color="Blue",
                package_type="box",
                total_quantity=index + 1,
                capacity=60,
                status="received_in_storage",
                storage_cell=cell,
                storage_shelf="S1",
            ))
        db.add_all(packages)
        db.commit()
        return marker, int(model.id)


def _read_stock(**params):
    with TestSessionLocal() as db:
        return warehouse_stock_page(db, None, **params)


@pytest.mark.parametrize("package_count", [1, 50, 401])
def test_warehouse_stock_pages_complete_groups_and_keeps_global_totals(package_count):
    marker, model_id = _seed_stock_groups(package_count)

    first = _read_stock(page_size=10)
    assert len(first["rows"]) == min(10, first["total"])
    assert first["total"] == max(1, package_count - 2)
    assert first["summary"] == {
        "models": 1,
        "packages": package_count,
        "quantity": package_count * (package_count + 1) // 2,
        "sections": 1,
    }
    assert first["model_groups"][0]["model_id"] == model_id
    assert first["model_groups"][0]["package_count"] == package_count
    assert first["model_groups"][0]["total_quantity"] == package_count * (package_count + 1) // 2
    assert first["rows"][0]["packages"][:3] == sorted(
        first["rows"][0]["packages"], key=lambda row: row["id"], reverse=True
    )
    if package_count >= 50:
        second = _read_stock(offset=10, page_size=10)
        assert first["rows"][0]["key"] != second["rows"][0]["key"]
        assert first["has_more"] is True
        assert second["has_more"] is (second["offset"] + len(second["rows"]) < second["total"])
    assert all(marker in row["model_code"] for row in first["rows"])


def test_warehouse_stock_search_and_unplaced_legacy_aggregate_match_screen_rules():
    marker, model_id = _seed_stock_groups(2)
    with TestSessionLocal() as db:
        for index in range(2):
            receipt = LegacyStockReceipt(
                source_system="PERF35",
                source_warehouse_id="WH-STOCK",
                source_record_id=f"{marker}-legacy-{index}",
                source_checksum=sha256(f"{marker}-legacy-{index}".encode()).hexdigest(),
                source_payload={"index": index},
            )
            db.add(receipt)
            db.flush()
            db.add(Package(
                package_no=f"WH-STOCK-LEGACY-{marker}-{index}",
                barcode=f"WH-STOCK-LEGACY-BC-{marker}-{index}",
                legacy_receipt_id=receipt.id,
                model_id=model_id,
                color="Red",
                package_type="legacy_stock",
                total_quantity=7,
                capacity=60,
                status="received_in_storage",
            ))
        db.commit()

    placed_only = _read_stock(include_unplaced=False)
    with_unplaced = _read_stock(include_unplaced=True)
    assert placed_only["summary"]["packages"] == 2
    assert with_unplaced["summary"]["packages"] == 4
    legacy_rows = [row for row in with_unplaced["rows"] if row["section"] == "-"]
    assert len(legacy_rows) == 1
    assert legacy_rows[0]["package_count"] == 2
    assert legacy_rows[0]["total_quantity"] == 14
    assert len(legacy_rows[0]["packages"]) == 1
    representative_label = legacy_rows[0]["packages"][0]["package_no"]
    representative_search = _read_stock(include_unplaced=True, query_text=representative_label)
    assert representative_search["summary"]["packages"] == 2
    assert representative_search["rows"][0]["package_count"] == 2
    color_search = _read_stock(include_unplaced=True, query_text="red")
    assert color_search["summary"]["packages"] == 2
    assert all(row["color"] == "Red" for row in color_search["rows"])
    placeholder_search = _read_stock(include_unplaced=True, query_text="S1")
    assert placeholder_search["summary"]["packages"] == 2
    assert all(row["section"] != "-" for row in placeholder_search["rows"])
    order_placeholder_search = _read_stock(include_unplaced=True, query_text="#")
    assert order_placeholder_search["summary"]["packages"] == 0


def test_warehouse_stock_endpoint_requires_login_and_bounds_page_size(client):
    marker, _ = _seed_stock_groups(1)
    with SessionLocal() as db:
        role = Role(name=f"Warehouse stock reader {uuid4().hex}", permissions=[])
        db.add(role)
        db.flush()
        reader = User(
            name="Warehouse stock reader",
            email=f"warehouse-stock-{uuid4().hex}@example.invalid",
            password_hash="unused-warehouse-stock-pagination-hash",
            role_id=role.id,
            factory_code="MIL",
            extra_permissions=[],
            is_active=True,
        )
        db.add(reader)
        db.commit()
        headers = {"Authorization": f"Bearer {create_access_token(reader.id)}"}

    assert client.get("/api/packages/warehouse-stock").status_code == 401
    response = client.get(
        "/api/packages/warehouse-stock",
        params={"query": marker, "page_size": 1},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["summary"]["packages"] == 1
    assert client.get(
        "/api/packages/warehouse-stock",
        params={"page_size": 101},
        headers=headers,
    ).status_code == 422

