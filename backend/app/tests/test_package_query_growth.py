from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.packages import _package_out_payload
from app.core.security import create_access_token
from app.models import (
    Customer, Department, Item, Model, ModelBOM, ModelImage, Package,
    ProductionOrder, Role, SalesOrder, StockBatch, User, Warehouse,
)
from app.models.tracking import LegacyStockReceipt
from app.tests.conftest import TestSessionLocal, test_engine


def _seed_packages(count, *, source="legacy", department="PKG"):
    marker = uuid4().hex[:10]
    expected = {}
    with TestSessionLocal() as db:
        warehouse = db.query(Warehouse).first()
        for index in range(count):
            suffix = f"{marker}-{index}"
            model = Model(code=f"PERF-{suffix}", name=f"Package model {index}")
            db.add(model)
            db.flush()
            image_url = None
            if source != "legacy":
                kind = index % 6
                item = Item(
                    sku=f"PERF-{suffix}", name="Test fabric", category="fabric", unit="kg",
                    image_url=f"/storage/model-files/item-{suffix}.png" if kind != 5 else None,
                )
                db.add(item)
                db.flush()
                batch = StockBatch(
                    item_id=item.id, batch_no=suffix, quantity=1, unit="kg", warehouse_id=warehouse.id,
                    image_url=f"/storage/model-files/batch-{suffix}.png" if kind < 4 else None,
                )
                db.add(batch)
                db.flush()
                bom_photo = f"/storage/model-files/bom-{suffix}.png" if kind < 3 else None
                db.add(ModelBOM(
                    model_id=model.id, item_id=item.id, stock_batch_id=batch.id,
                    quantity_per_piece=1, unit="kg", photo_url=bom_photo,
                ))
                db.add(ModelImage(model_id=model.id, file_url=f"/files/{suffix}.pdf", image_type="model"))
                if kind < 2:
                    image_url = f"/storage/model-files/image-{suffix}.png"
                    db.add(ModelImage(
                        model_id=model.id, file_url=image_url,
                        image_type="model" if kind == 0 else "material", is_primary=True,
                    ))
                elif kind == 2:
                    image_url = bom_photo
                elif kind == 3:
                    image_url = batch.image_url
                elif kind == 4:
                    image_url = item.image_url

            production_id = sales_id = legacy_id = None
            if source == "legacy":
                receipt = LegacyStockReceipt(
                    source_system="PERF", source_warehouse_id="synthetic", source_record_id=suffix,
                    source_checksum="0" * 64, source_payload={"synthetic": True},
                )
                db.add(receipt)
                db.flush()
                legacy_id = receipt.id
            else:
                customer = Customer(name=f"Customer {suffix}")
                db.add(customer)
                db.flush()
                sales = SalesOrder(order_no=f"SO-PERF-{suffix}", customer_id=customer.id)
                db.add(sales)
                db.flush()
                production = ProductionOrder(
                    production_no=f"PO-PERF-{suffix}", production_type="branded_stock",
                    sales_order_id=sales.id, model_id=model.id, planned_quantity=10,
                )
                db.add(production)
                db.flush()
                production_id = production.id
                if source == "linked":
                    sales_id = sales.id

            package = Package(
                package_no=f"PKG-PERF-{suffix}", barcode=f"BC-PERF-{suffix}",
                model_id=model.id, production_order_id=production_id, sales_order_id=sales_id,
                legacy_receipt_id=legacy_id, packaging_department_code=department,
                color="Blue", total_quantity=10, capacity=60, status="packed",
                qr_code_url=f"/synthetic-qr/{suffix}",
                created_at=datetime(2026, 9, 1 + index % 2, tzinfo=timezone.utc),
            )
            db.add(package)
            db.flush()
            expected[package.id] = {"model_image_url": image_url}
        db.commit()
    return expected


def _captured_get(client, headers, path):
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        response = client.get(path, headers=headers)
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)
    return response, statements


@pytest.mark.parametrize("source", ["legacy", "linked", "production_sales"])
def test_package_list_query_count_is_bounded(client, auth_headers, source):
    ids = _seed_packages(50, source=source)
    counts = []
    for size in (1, 10, 50):
        response, statements = _captured_get(client, auth_headers, f"/api/packages?page_size={size}")
        assert response.status_code == 200, response.text
        assert [row["id"] for row in response.json()] == sorted(ids, reverse=True)[:size]
        counts.append(len(statements))
    print(f"Package list SELECTs, {source}, 1/10/50 rows: {counts}")
    assert max(counts) <= 9, counts
    assert counts[0] == counts[1] == counts[2], counts


@pytest.mark.parametrize("source", ["legacy", "linked", "production_sales"])
def test_package_list_matches_single_package_payloads_and_images(client, auth_headers, source):
    expected_images = _seed_packages(6, source=source)
    with TestSessionLocal() as db:
        rows = db.query(Package).filter(Package.id.in_(expected_images)).order_by(Package.id.desc()).all()
        expected = [_package_out_payload(db, package) for package in rows]
    response = client.get("/api/packages?page_size=6", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json() == expected
    for row in response.json():
        assert row["model_image_url"] == expected_images[row["id"]]["model_image_url"]
        detail = client.get(f"/api/packages/{row['id']}", headers=auth_headers)
        assert detail.status_code == 200, detail.text
        assert {key: detail.json()[key] for key in row} == row
        if source == "legacy":
            assert all(row[key] is None for key in (
                "production_no", "sales_order_no", "order_no", "customer_name", "order_type",
            ))
        elif source == "production_sales":
            assert row["sales_order_no"] is None
            assert row["customer_name"] is None
            assert row["order_no"].startswith("SO-PERF-")
            assert row["order_type"] == "branded_stock"


def test_package_list_preserves_pagination_filters_and_empty_page(client, auth_headers):
    ids = sorted(_seed_packages(6, source="linked"), reverse=True)
    response = client.get("/api/packages?include_total=true&page=2&page_size=2", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["total"], body["page"], body["page_size"]) == (6, 2, 2)
    assert [row["id"] for row in body["rows"]] == ids[2:4]

    empty = client.get("/api/packages?include_total=true&page=4&page_size=2", headers=auth_headers)
    assert empty.json() == {"rows": [], "total": 6, "page": 4, "page_size": 2}
    dated = client.get(
        "/api/packages?created_from=2026-09-02&created_to=2026-09-02&include_total=true", headers=auth_headers,
    )
    assert dated.json()["total"] == 3
    assert [row["id"] for row in dated.json()["rows"]] == ids[::2]
    production_id = body["rows"][0]["production_order_id"]
    scoped = client.get(f"/api/packages?production_order_id={production_id}", headers=auth_headers)
    assert [row["id"] for row in scoped.json()] == [ids[2]]
    assert client.get("/api/packages?status=shipped", headers=auth_headers).json() == []


def test_package_list_preserves_session_and_factory_boundaries(client):
    mil_ids = _seed_packages(2)
    eco_ids = _seed_packages(1, department="ECP")
    _seed_packages(1, department="BPK")
    with TestSessionLocal() as db:
        role = Role(name="Package list reader", permissions=["storage.packages"])
        db.add(role)
        db.flush()
        headers = {}
        for factory, department_code in [("MIL", "PKG"), ("ECO", "ECP")]:
            department = db.query(Department).filter_by(code=department_code).one()
            user = User(
                name=f"Package {factory}", email=f"package-{factory.lower()}@example.com",
                password_hash="unused", role_id=role.id, department_id=department.id, factory_code=factory,
            )
            db.add(user)
            db.flush()
            headers[factory] = {"Authorization": f"Bearer {create_access_token(user.id, {'factory_code': factory})}"}
        db.commit()
    assert client.get("/api/packages").status_code == 401
    for factory, ids, forbidden in [("MIL", mil_ids, "ECP"), ("ECO", eco_ids, "PKG")]:
        response = client.get("/api/packages", headers=headers[factory])
        assert response.status_code == 200, response.text
        assert {row["id"] for row in response.json()} == set(ids)
        assert client.get(
            f"/api/packages?packaging_department_code={forbidden}", headers=headers[factory],
        ).status_code == 403


def test_package_list_still_repairs_missing_qr_url(client, auth_headers):
    package_id = next(iter(_seed_packages(1)))
    with TestSessionLocal() as db:
        db.get(Package, package_id).qr_code_url = None
        db.commit()
    response = client.get("/api/packages?page_size=1", headers=auth_headers)
    assert response.status_code == 200, response.text
    url = response.json()[0]["qr_code_url"]
    assert url.startswith("/storage/barcodes/")
    with TestSessionLocal() as db:
        assert db.get(Package, package_id).qr_code_url == url
