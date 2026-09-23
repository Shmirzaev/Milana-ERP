from math import ceil
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.orm import selectinload

from app.api.routes import packages as package_routes
from app.db.session import SessionLocal
from app.models import (
    Customer,
    Item,
    ManualPackageReceipt,
    Model,
    ModelBOM,
    ModelImage,
    Package,
    PackageBatchAllocation,
    PackageItem,
    PackagePrintRun,
    PackagePrintRunMember,
    ProductionBatch,
    ProductionOrder,
    SalesOrder,
    StockBatch,
    User,
    Warehouse,
)


def _select_trace(bind, callback):
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().lower().startswith("select"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(bind, "before_cursor_execute", capture)
    try:
        result = callback()
    finally:
        event.remove(bind, "before_cursor_execute", capture)
    return result, statements


def _table_selects(statements, table):
    return sum(f" from {table} " in statement for statement in statements)


def _package_case(db, package_count):
    suffix = uuid4().hex[:8].upper()
    model = Model(
        code=f"PERF12-M-{suffix}",
        name=f"PERF12 model {suffix}",
        product_type="shirt",
        details_json={"general": {"model_no": f"M-{suffix}", "variant_no": f"A-{suffix}"}},
    )
    db.add(model)
    db.flush()
    db.add(ModelImage(
        model_id=model.id,
        file_url=f"/storage/model-files/PERF12-{suffix}.png",
        file_name=f"PERF12-{suffix}.png",
        content_type="image/png",
        image_type="model",
        is_primary=True,
        file_data=b"PERF12 package label image bytes",
    ))
    db.add_all([
        ModelImage(
            model_id=model.id,
            file_url=f"/storage/model-files/PERF12-material-{suffix}-{number}.png",
            file_name=f"PERF12-material-{suffix}-{number}.png",
            content_type="image/png",
            image_type="material",
            is_primary=False,
            file_data=f"PERF12 material image {number}".encode(),
        )
        for number in range(3)
    ])
    db.flush()
    order = ProductionOrder(
        production_no=f"PERF12-PO-{suffix}",
        production_type="branded_stock",
        model_id=model.id,
        status="packaging",
        planned_quantity=package_count,
    )
    db.add(order)
    db.flush()
    batch = ProductionBatch(
        production_order_id=order.id,
        batch_no=f"PERF12-PB-{suffix}",
        batch_index=1,
        name="Sheet batch",
        planned_quantity=package_count,
    )
    db.add(batch)
    db.flush()
    packages = [
        Package(
            package_no=f"PERF12-PKG-{suffix}-{number:04d}",
            barcode=f"PERF12-BC-{suffix}-{number:04d}",
            production_order_id=order.id,
            production_batch_id=batch.id,
            model_id=model.id,
            color=f"color-{number}",
            total_quantity=1,
            capacity=1,
            status="packed",
        )
        for number in range(package_count)
    ]
    db.add_all(packages)
    db.commit()
    return [row.id for row in packages], [row.package_no for row in packages]


def _distinct_reference_package_case(db, package_count):
    suffix = uuid4().hex[:8].upper()
    models = [
        Model(
            code=f"PERF12-DM-{suffix}-{number:04d}",
            name=f"PERF12 distinct model {number}",
            product_type="shirt",
        )
        for number in range(package_count)
    ]
    db.add_all(models)
    db.flush()
    orders = [
        ProductionOrder(
            production_no=f"PERF12-DPO-{suffix}-{number:04d}",
            production_type="branded_stock",
            model_id=model.id,
            status="packaging",
            planned_quantity=1,
        )
        for number, model in enumerate(models)
    ]
    db.add_all(orders)
    db.flush()
    packages = [
        Package(
            package_no=f"PERF12-DPKG-{suffix}-{number:04d}",
            barcode=f"PERF12-DBC-{suffix}-{number:04d}",
            production_order_id=order.id,
            model_id=model.id,
            color="blue",
            total_quantity=1,
            capacity=1,
            status="packed",
        )
        for number, (model, order) in enumerate(zip(models, orders, strict=True))
    ]
    db.add_all(packages)
    db.commit()
    return [package.id for package in packages]


def _rich_package_case(db):
    suffix = uuid4().hex[:8].upper()
    actor_id = db.query(User.id).order_by(User.id).first()[0]
    direct_customer = Customer(name=f"PERF12 direct customer {suffix}")
    fallback_customer = Customer(name=f"PERF12 fallback customer {suffix}")
    fabric_item = Item(
        sku=f"PERF12-FAB-{suffix}",
        name=f"PERF12 cotton {suffix}",
        category="fabric",
        unit="kg",
        composition_json=[{"name": "Cotton", "percentage": 95}, {"name": "Elastane", "percentage": 5}],
        image_url="https://example.test/fabric.png",
    )
    warehouse = Warehouse(name=f"PERF12 warehouse {suffix}", type="fabric_storage")
    models = [
        Model(
            code=f"PERF12-RM-{suffix}-{number}",
            name=f"PERF12 rich model {number}",
            product_type=f"product-{number}",
            details_json={"general": {"model_no": f"MODEL-{number}", "variant_no": f"ARTICLE-{number}"}},
        )
        for number in range(2)
    ]
    db.add_all([direct_customer, fallback_customer, fabric_item, warehouse, *models])
    db.flush()
    db.add(
        ModelImage(
            model_id=models[0].id,
            file_url="https://example.test/model.png",
            content_type="image/png",
            image_type="model",
            is_primary=True,
        )
    )
    db.add(
        ModelBOM(
            model_id=models[1].id,
            item_id=fabric_item.id,
            material_role="main",
            quantity_per_piece=1,
            unit="kg",
        )
    )
    orders = [
        SalesOrder(
            order_no=f"PERF12-RSO-{suffix}-{number}",
            customer_id=customer.id,
            status="confirmed",
        )
        for number, customer in enumerate((direct_customer, fallback_customer))
    ]
    db.add_all(orders)
    db.flush()
    fabric_batch = StockBatch(
        item_id=fabric_item.id,
        batch_no=f"PERF12-FB-{suffix}",
        quantity=10,
        unit="kg",
        cost_per_unit=1,
        warehouse_id=warehouse.id,
        qc_status="passed",
    )
    db.add(fabric_batch)
    db.flush()
    production_orders = [
        ProductionOrder(
            production_no=f"PERF12-RPO-{suffix}-{number}",
            production_type="client_order",
            sales_order_id=orders[0].id,
            model_id=model.id,
            fabric_batch_id=fabric_batch.id if number == 0 else None,
            status="packaging",
            planned_quantity=2,
        )
        for number, model in enumerate(models)
    ]
    db.add_all(production_orders)
    db.flush()
    batches = [
        ProductionBatch(
            production_order_id=production_order.id,
            batch_no=f"PERF12-RPB-{suffix}-{number}",
            batch_index=1,
            name=f"Rich batch {number}",
            planned_quantity=2,
        )
        for number, production_order in enumerate(production_orders)
    ]
    receipt = ManualPackageReceipt(
        receipt_no=f"PERF12-MR-{suffix}",
        created_by=actor_id,
        evidence={"pack_quantities": [1, 1], "configured_sizes": ["XS", "XL"]},
        evidence_hash="a" * 64,
    )
    db.add_all([*batches, receipt])
    db.flush()
    packages = [
        Package(
            package_no=f"PERF12-RPKG-{suffix}-0",
            barcode=f"PERF12-RBC-{suffix}-0",
            production_order_id=production_orders[0].id,
            production_batch_id=batches[0].id,
            sales_order_id=orders[1].id,
            model_id=models[0].id,
            color="navy",
            total_quantity=2,
            capacity=2,
            status="packed",
        ),
        Package(
            package_no=f"PERF12-RPKG-{suffix}-1",
            barcode=f"PERF12-RBC-{suffix}-1",
            production_order_id=production_orders[1].id,
            production_batch_id=batches[1].id,
            model_id=models[1].id,
            color="white",
            total_quantity=2,
            capacity=2,
            status="packed",
        ),
        Package(
            package_no=f"PERF12-RPKG-{suffix}-2",
            barcode=f"PERF12-RBC-{suffix}-2",
            manual_receipt_id=receipt.id,
            model_id=models[0].id,
            color="black",
            total_quantity=2,
            capacity=2,
            status="packed",
        ),
    ]
    db.add_all(packages)
    db.flush()
    db.add_all([
        PackageItem(package_id=package.id, model_id=package.model_id, color=package.color, size="M", quantity=2)
        for package in packages
    ])
    db.add(
        PackageBatchAllocation(
            package_id=packages[0].id,
            production_batch_id=batches[1].id,
            quantity=2,
        )
    )
    db.commit()
    return {
        "package_ids": [package.id for package in packages],
        "package_nos": [package.package_no for package in packages],
        "direct_customer": direct_customer.name,
        "fallback_customer": fallback_customer.name,
        "fabric_name": fabric_item.name,
    }


@pytest.mark.parametrize("package_count", [1, 50, 401, 500])
def test_package_label_sheet_batches_reference_context(client, auth_headers, monkeypatch, package_count):
    with SessionLocal() as db:
        package_ids, package_nos = _package_case(db, package_count)
        bind = db.bind

    monkeypatch.setattr(
        package_routes,
        "_qr_data_uri_for_package",
        lambda _db, _package: "data:image/png;base64,AA==",
    )
    response, statements = _select_trace(
        bind,
        lambda: client.get(
            "/api/packages/label-sheet/by-ids",
            params={"ids": ",".join(str(row_id) for row_id in reversed(package_ids))},
            headers=auth_headers,
        ),
    )

    assert response.status_code == 200, response.text
    expected_chunks = ceil(package_count / 400)
    counts = {
        "members": _table_selects(statements, "package_print_run_members"),
        "models": _table_selects(statements, "models"),
        "images": _table_selects(statements, "model_images"),
        "bom": _table_selects(statements, "model_bom"),
        "orders": _table_selects(statements, "production_orders"),
        "allocations": _table_selects(statements, "package_batch_allocations"),
        "batches": _table_selects(statements, "production_batches"),
    }
    assert counts == {
        "members": expected_chunks,
        "models": 1,
        "images": 2,
        "bom": 1,
        "orders": 1,
        "allocations": expected_chunks,
        "batches": 1,
    }
    image_reads = [statement for statement in statements if " from model_images " in statement]
    assert any("file_data" not in statement for statement in image_reads), image_reads
    blob_reads = [statement for statement in image_reads if "file_data" in statement]
    assert len(blob_reads) == 1, blob_reads
    assert "model_images.id in (?, ?)" in blob_reads[0], blob_reads
    assert len(statements) == 10 + (2 * expected_chunks), statements
    positions = [response.text.index(package_no) for package_no in package_nos]
    assert positions == sorted(positions)


def test_package_label_sheet_rejects_over_limit_before_package_reads_or_rendering(
    client, auth_headers, monkeypatch
):
    with SessionLocal() as db:
        bind = db.bind

    def fail_render(*_args, **_kwargs):
        pytest.fail("over-limit label sheet must not render package labels")

    monkeypatch.setattr(package_routes, "_package_label_card_html", fail_render)
    ids = ",".join(str(package_id) for package_id in range(1, 502))
    response, statements = _select_trace(
        bind,
        lambda: client.get(
            "/api/packages/label-sheet/by-ids",
            params={"ids": ids},
            headers=auth_headers,
        ),
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "A label sheet may contain at most 500 packages"
    assert _table_selects(statements, "packages") == 0
    assert _table_selects(statements, "package_items") == 0


def test_package_label_context_chunks_distinct_models_and_orders(monkeypatch):
    with SessionLocal() as db:
        package_ids = _distinct_reference_package_case(db, 401)
        packages = (
            db.query(Package)
            .options(selectinload(Package.items))
            .filter(Package.id.in_(package_ids))
            .order_by(Package.id)
            .all()
        )

        monkeypatch.setattr(
            package_routes,
            "_qr_data_uri_for_package",
            lambda _db, _package: "data:image/png;base64,AA==",
        )

        def render_cards():
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

        cards, statements = _select_trace(db.bind, render_cards)

    assert len(cards) == 401
    assert _table_selects(statements, "models") == 2
    assert _table_selects(statements, "model_images") == 2
    assert _table_selects(statements, "model_bom") == 2
    assert _table_selects(statements, "production_orders") == 2
    assert _table_selects(statements, "package_batch_allocations") == 2
    assert len(statements) == 12, statements


def test_package_label_sheet_rejects_deleted_label_before_qr_side_effect(client, auth_headers, monkeypatch):
    with SessionLocal() as db:
        package_ids, _ = _package_case(db, 2)
        actor_id = db.query(User.id).order_by(User.id).first()[0]
        run = PackagePrintRun(
            run_no=f"PERF12-RUN-{uuid4().hex}",
            code=f"PERF12-CODE-{uuid4().hex}",
            packaging_department_code="PKG",
            package_ids=package_ids,
            created_by=actor_id,
            deleted_package_ids=[package_ids[1]],
        )
        db.add(run)
        db.flush()
        db.add_all([
            PackagePrintRunMember(run_id=run.id, package_id=package_id, snapshot={})
            for package_id in package_ids
        ])
        db.commit()

    qr_calls = []

    def record_qr(_db, package):
        qr_calls.append(package.id)
        return "data:image/png;base64,AA=="

    monkeypatch.setattr(package_routes, "_qr_data_uri_for_package", record_qr)
    response = client.get(
        "/api/packages/label-sheet/by-ids",
        params={"ids": ",".join(str(row_id) for row_id in package_ids)},
        headers=auth_headers,
    )

    assert response.status_code == 410
    assert qr_calls == []


def test_package_label_sheet_context_matches_scalar_cards(monkeypatch):
    with SessionLocal() as db:
        case = _rich_package_case(db)

    monkeypatch.setattr(
        package_routes,
        "_qr_data_uri_for_package",
        lambda _db, _package: "data:image/png;base64,AA==",
    )
    with SessionLocal() as db:
        packages = (
            db.query(Package)
            .options(selectinload(Package.items))
            .filter(Package.id.in_(case["package_ids"]))
            .order_by(Package.id)
            .all()
        )
        scalar_cards = [package_routes._package_label_card_html(db, package) for package in packages]
    with SessionLocal() as db:
        packages = (
            db.query(Package)
            .options(selectinload(Package.items))
            .filter(Package.id.in_(case["package_ids"]))
            .order_by(Package.id)
            .all()
        )
        context = package_routes._package_label_reference_context(db, packages)
        batched_cards = [
            package_routes._package_label_card_html(
                db,
                package,
                context=context,
                active_label_checked=True,
            )
            for package in packages
        ]

    assert batched_cards == scalar_cards
    assert all(
        package_no in card
        for package_no, card in zip(case["package_nos"], batched_cards, strict=True)
    )
    assert case["fallback_customer"] in batched_cards[0]
    assert case["direct_customer"] in batched_cards[1]
    assert case["fabric_name"] in batched_cards[0]
    assert case["fabric_name"] in batched_cards[1]
    assert "https://example.test/model.png" in batched_cards[0]
    assert "https://example.test/fabric.png" in batched_cards[1]
    assert "Rich batch 1" in batched_cards[0]
    assert "XS" in batched_cards[2] and "XL" in batched_cards[2]
