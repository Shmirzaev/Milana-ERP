import base64
from math import ceil
from uuid import uuid4

import pytest
from fastapi.encoders import jsonable_encoder
from sqlalchemy import event
from sqlalchemy.orm import selectinload

from app.api.routes import packages as package_routes
from app.db.session import SessionLocal
from app.models import (
    Customer,
    Item,
    LegacyStockReceipt,
    ManualPackageReceipt,
    Model,
    ModelBOM,
    ModelImage,
    Package,
    PackageBatchAllocation,
    PackageItem,
    PackagePrintRun,
    PackagePrintRunMember,
    PackageScanLog,
    ProductionBatch,
    ProductionOrder,
    SalesOrder,
    StockBatch,
    User,
    Warehouse,
)


def _select_trace(bind, callback):
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(bind, "before_cursor_execute", capture)
    try:
        result = callback()
    finally:
        event.remove(bind, "before_cursor_execute", capture)
    return result, statements


def _table_selects(statements, table):
    return sum(f" from {table} " in statement for statement in statements)


def _receiving_queue_case(package_count: int) -> list[int]:
    marker = uuid4().hex[:8].upper()
    with SessionLocal() as db:
        actor_id = db.query(User.id).order_by(User.id).first()[0]
        customers = [Customer(name=f"PERF08 customer {marker} {number}") for number in range(package_count)]
        models = [
            Model(
                code=f"PERF08-M-{marker}-{number:04d}",
                name=f"PERF08 model {number}",
                product_type="shirt",
            )
            for number in range(package_count)
        ]
        db.add_all([*customers, *models])
        db.flush()
        db.add_all([
            ModelImage(
                model_id=model.id,
                file_url=f"https://example.test/{marker}/{number}.png",
                file_name=f"{number}.png",
                content_type="image/png",
                file_data=b"unused-image-blob",
                image_type="model",
                is_primary=True,
            )
            for number, model in enumerate(models)
        ])
        sales_orders = [
            SalesOrder(
                order_no=f"PERF08-SO-{marker}-{number:04d}",
                customer_id=customer.id,
                status="confirmed",
            )
            for number, customer in enumerate(customers)
        ]
        db.add_all(sales_orders)
        db.flush()
        production_orders = [
            ProductionOrder(
                production_no=f"PERF08-PO-{marker}-{number:04d}",
                production_type="client_order",
                sales_order_id=sales_order.id,
                model_id=model.id,
                status="packaging",
                planned_quantity=1,
            )
            for number, (sales_order, model) in enumerate(zip(sales_orders, models, strict=True))
        ]
        db.add_all(production_orders)
        db.flush()
        batches = [
            ProductionBatch(
                production_order_id=production_order.id,
                batch_no=f"PERF08-B-{marker}-{number:04d}",
                batch_index=1,
                planned_quantity=1,
            )
            for number, production_order in enumerate(production_orders)
        ]
        db.add_all(batches)
        db.flush()
        packages = [
            Package(
                package_no=f"PERF08-PKG-{marker}-{number:04d}",
                barcode=f"PERF08-BC-{marker}-{number:04d}",
                production_order_id=production_order.id,
                production_batch_id=batch.id,
                sales_order_id=sales_order.id,
                model_id=model.id,
                color="blue",
                total_quantity=1,
                capacity=1,
                status="packed",
            )
            for number, (production_order, batch, sales_order, model) in enumerate(
                zip(production_orders, batches, sales_orders, models, strict=True)
            )
        ]
        db.add_all(packages)
        db.flush()
        db.add_all([
            PackageItem(
                package_id=package.id,
                model_id=package.model_id,
                color=package.color,
                size="M",
                quantity=1,
            )
            for package in packages
        ])
        db.add_all([
            PackageBatchAllocation(
                package_id=package.id,
                production_batch_id=package.production_batch_id,
                quantity=1,
            )
            for package in packages
        ])
        print_run = PackagePrintRun(
            run_no=f"PERF08-RUN-{marker}",
            code=f"PERF08-CODE-{marker}",
            packaging_department_code="PKG",
            package_ids=[package.id for package in packages],
            created_by=actor_id,
        )
        db.add(print_run)
        db.flush()
        db.add_all([
            PackagePrintRunMember(run_id=print_run.id, package_id=package.id, snapshot={})
            for package in packages
        ])
        for package in packages:
            db.add(PackageScanLog(package_id=package.id, scanned_by=actor_id, scan_type="removed_storage_queue"))
            db.flush()
            db.add(PackageScanLog(package_id=package.id, scanned_by=actor_id, scan_type="queued_storage"))
        db.commit()
        return [int(package.id) for package in packages]


@pytest.mark.parametrize("package_count,expected_selects", [(1, 14), (50, 14), (401, 22)])
def test_receiving_queue_batches_full_detail_payload(client, auth_headers, package_count, expected_selects):
    package_ids = _receiving_queue_case(package_count)
    with SessionLocal() as db:
        bind = db.bind

    response, statements = _select_trace(
        bind,
        lambda: client.get("/api/packages/receiving-queue", headers=auth_headers),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert [row["id"] for row in payload] == list(reversed(package_ids))
    assert all(len(row["items"]) == 1 for row in payload)
    assert all(len(row["batch_allocations"]) == 1 for row in payload)
    assert all(len(row["scan_logs"]) == 2 for row in payload)
    expected_chunks = ceil(package_count / 400)
    assert _table_selects(statements, "models") == expected_chunks
    assert _table_selects(statements, "production_orders") == expected_chunks
    assert _table_selects(statements, "sales_orders") == expected_chunks
    assert _table_selects(statements, "customers") == expected_chunks
    assert _table_selects(statements, "package_print_run_members") == expected_chunks
    assert len(statements) == expected_selects, statements
    image_selects = [statement for statement in statements if " from model_images " in statement]
    assert len(image_selects) == expected_chunks
    assert all("file_data" not in statement for statement in image_selects)


def test_receiving_queue_preserves_scalar_payload_and_event_membership(client, auth_headers):
    package_ids = _receiving_queue_case(5)
    with SessionLocal() as db:
        actor_id = db.query(User.id).order_by(User.id).first()[0]
        packages = db.query(Package).filter(Package.id.in_(package_ids)).order_by(Package.id).all()
        db.add(PackageScanLog(
            package_id=packages[0].id,
            scanned_by=actor_id,
            scan_type="removed_storage_queue",
        ))
        db.add(PackageScanLog(
            package_id=packages[1].id,
            scanned_by=actor_id,
            scan_type="received_storage",
        ))
        packages[2].status = "received_in_storage"
        production_order = db.get(ProductionOrder, packages[3].production_order_id)
        fallback_order_no = db.get(SalesOrder, production_order.sales_order_id).order_no
        packages[3].sales_order_id = None
        manual_receipt_no = f"PERF08-MR-{uuid4().hex}"
        manual = ManualPackageReceipt(
            receipt_no=manual_receipt_no,
            created_by=actor_id,
            evidence={"configured_sizes": ["S", "M"], "pack_quantities": [1, 1]},
            evidence_hash="a" * 64,
        )
        legacy = LegacyStockReceipt(
            source_system="UZERP",
            source_warehouse_id=f"PERF08-W-{uuid4().hex}",
            source_warehouse_name="Legacy receiving",
            source_record_id=f"PERF08-R-{uuid4().hex}",
            source_checksum="b" * 64,
            source_payload={"legacy": True},
            imported_by=actor_id,
        )
        db.add_all([manual, legacy])
        db.flush()
        packages[4].legacy_receipt_id = legacy.id
        manual_package = Package(
            package_no=f"PERF08-MPKG-{uuid4().hex}",
            barcode=f"PERF08-MBC-{uuid4().hex}",
            manual_receipt_id=manual.id,
            model_id=packages[3].model_id,
            color="white",
            total_quantity=1,
            capacity=1,
            status="packed",
        )
        db.add(manual_package)
        db.flush()
        db.add(PackageScanLog(
            package_id=manual_package.id,
            scanned_by=actor_id,
            scan_type="queued_storage",
        ))
        manual_package_id = int(manual_package.id)
        db.commit()

    with SessionLocal() as db:
        scalar_packages = package_routes._receiving_queue_packages(db)
        scalar_payload = [package_routes._package_detail_payload(db, package) for package in scalar_packages]
    with SessionLocal() as db:
        batched_packages = package_routes._receiving_queue_packages(db)
        batched_payload = package_routes._package_detail_payloads(db, batched_packages)

    response = client.get("/api/packages/receiving-queue", headers=auth_headers)
    assert response.status_code == 200, response.text
    actual = response.json()
    assert batched_payload == scalar_payload
    assert actual == jsonable_encoder(scalar_payload)
    assert [row["id"] for row in actual] == [manual_package_id, package_ids[4], package_ids[3]]
    assert actual[0]["manual_source"]["receipt_no"] == manual_receipt_no
    assert actual[1]["legacy_source"]["legacy"] is True
    assert actual[2]["order_no"] == fallback_order_no
    assert actual[2]["sales_order_no"] is None
    assert actual[2]["customer_name"] is None

    unauthorized = client.get("/api/packages/receiving-queue")
    assert unauthorized.status_code in {401, 403}
    login = client.post(
        "/api/auth/token",
        data={"username": "planning@example.com", "password": "demo12345"},
    )
    assert login.status_code == 200, login.text
    planning_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get("/api/packages/receiving-queue", headers=planning_headers).status_code == 403


def test_receiving_queue_bounds_page_and_reports_total(client, auth_headers):
    package_ids = _receiving_queue_case(5)

    response = client.get(
        "/api/packages/receiving-queue?offset=1&limit=2",
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    assert [row["id"] for row in response.json()] == list(reversed(package_ids))[1:3]
    assert response.headers["x-total-count"] == "5"
    assert response.headers["x-page-offset"] == "1"
    assert response.headers["x-page-limit"] == "2"


def test_receiving_queue_remove_returns_same_batched_list_contract(client, auth_headers):
    package_ids = _receiving_queue_case(3)

    removed = client.post(
        "/api/packages/receiving-queue/remove",
        headers=auth_headers,
        json={"package_ids": [package_ids[1]]},
    )
    assert removed.status_code == 200, removed.text
    payload = removed.json()
    assert payload["count"] == 1
    assert [row["id"] for row in payload["packages"]] == [package_ids[2], package_ids[0]]
    assert all(len(row["items"]) == 1 for row in payload["packages"])

    current = client.get("/api/packages/receiving-queue", headers=auth_headers)
    assert current.status_code == 200, current.text
    assert current.json() == payload["packages"]

    unchanged = client.post(
        "/api/packages/receiving-queue/remove",
        headers=auth_headers,
        json={"package_ids": []},
    )
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json() == {"count": 0, "packages": payload["packages"]}


def test_shared_model_context_preserves_bom_stock_batch_image_fallback(client, auth_headers, monkeypatch):
    package_ids = _receiving_queue_case(2)
    image_urls = [
        "https://example.test/perf08-batch-first.png",
        "https://example.test/perf08-batch-second.png",
    ]
    with SessionLocal() as db:
        packages = db.query(Package).filter(Package.id.in_(package_ids)).order_by(Package.id).all()
        model_ids = [int(package.model_id) for package in packages]
        db.query(ModelImage).filter(ModelImage.model_id.in_(model_ids)).delete(synchronize_session=False)
        item = Item(
            sku=f"PERF08-FAB-{uuid4().hex}",
            name="PERF08 fallback fabric",
            category="fabric",
            unit="kg",
        )
        warehouse = Warehouse(name=f"PERF08 warehouse {uuid4().hex}", type="fabric_storage")
        db.add_all([item, warehouse])
        db.flush()
        batches = [
            StockBatch(
                item_id=item.id,
                batch_no=f"PERF08-FB-{uuid4().hex}",
                quantity=1,
                unit="kg",
                cost_per_unit=1,
                image_url=image_url,
                warehouse_id=warehouse.id,
                qc_status="passed",
            )
            for image_url in image_urls
        ]
        db.add_all(batches)
        db.flush()
        db.add_all([
            ModelBOM(
                model_id=model_id,
                item_id=item.id,
                stock_batch_id=batch.id,
                material_role="main",
                quantity_per_piece=1,
                unit="kg",
            )
            for model_id, batch in zip(model_ids, batches, strict=True)
        ])
        db.commit()
        bind = db.bind

    response, queue_statements = _select_trace(
        bind,
        lambda: client.get("/api/packages/receiving-queue", headers=auth_headers),
    )
    assert response.status_code == 200, response.text
    assert [row["model_image_url"] for row in response.json()] == list(reversed(image_urls))
    assert _table_selects(queue_statements, "stock_batches") == 0

    monkeypatch.setattr(
        package_routes,
        "_qr_data_uri_for_package",
        lambda _db, _package: "data:image/png;base64,AA==",
    )
    with SessionLocal() as db:
        packages = (
            db.query(Package)
            .options(selectinload(Package.items))
            .filter(Package.id.in_(package_ids))
            .order_by(Package.id)
            .all()
        )

        def render_labels():
            context = package_routes._package_label_reference_context(db, packages)
            return [
                package_routes._package_label_card_html(
                    db,
                    package,
                    context=context,
                    active_label_checked=True,
                )
                for package in packages
            ]

        cards, label_statements = _select_trace(db.bind, render_labels)

    assert all(image_url in card for image_url, card in zip(image_urls, cards, strict=True))
    assert _table_selects(label_statements, "stock_batches") == 0


def test_label_context_eagerly_loads_distinct_embedded_model_images(monkeypatch):
    package_ids = _receiving_queue_case(50)
    monkeypatch.setattr(
        package_routes,
        "_qr_data_uri_for_package",
        lambda _db, _package: "data:image/png;base64,AA==",
    )
    with SessionLocal() as db:
        packages = (
            db.query(Package)
            .options(selectinload(Package.items))
            .filter(Package.id.in_(package_ids))
            .order_by(Package.id)
            .all()
        )

        def render_labels():
            context = package_routes._package_label_reference_context(db, packages)
            return [
                package_routes._package_label_card_html(
                    db,
                    package,
                    context=context,
                    active_label_checked=True,
                )
                for package in packages
            ]

        cards, statements = _select_trace(db.bind, render_labels)

    embedded = "data:image/png;base64," + base64.b64encode(b"unused-image-blob").decode("ascii")
    assert all(embedded in card for card in cards)
    image_selects = [statement for statement in statements if " from model_images " in statement]
    assert len(image_selects) == 1
    assert "file_data" in image_selects[0]
