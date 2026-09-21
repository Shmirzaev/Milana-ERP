from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.sales import _package_allocation_candidates
from app.db.session import SessionLocal
from app.models import Brand, Collection, FinishedGoodsStock, LegacyStockReceipt, Model, Package, ProductionOrder
from app.services import finished_goods as finished_goods_service


def _packages(package_count: int) -> tuple[list[int], int]:
    marker = uuid4().hex[:8]
    with SessionLocal() as db:
        model = Model(code=f"PERF26-M-{marker}", name=f"PERF26 model {marker}", product_type="shirt")
        db.add(model)
        db.flush()
        order = ProductionOrder(
            production_no=f"PERF26-PO-{marker}", production_type="branded_stock",
            model_id=model.id, status="packaging", planned_quantity=package_count,
        )
        db.add(order)
        db.flush()
        packages = [
            Package(
                package_no=f"PERF26-PKG-{marker}-{index:04d}",
                barcode=f"PERF26-BC-{marker}-{index:04d}",
                production_order_id=order.id, model_id=model.id, color="navy",
                total_quantity=1, capacity=1, status="received_in_storage",
            )
            for index in range(package_count)
        ]
        db.add_all(packages)
        db.commit()
        return [int(package.id) for package in packages], int(model.id)


def _stock(package_id: int | None, quantity: int = 1):
    return SimpleNamespace(
        package_id=package_id, quantity=quantity, available_qty=quantity,
        reserved_qty=0, sold_qty=0,
    )


def _package_selects(bind, callback):
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select") and " from packages " in normalized:
            statements.append(normalized)

    event.listen(bind, "before_cursor_execute", capture)
    try:
        result = callback()
    finally:
        event.remove(bind, "before_cursor_execute", capture)
    return result, statements


@pytest.mark.parametrize("package_count", [1, 50, 401])
def test_package_candidate_cache_bounds_real_reads_but_rechecks_mutated_stock(package_count):
    package_ids, _ = _packages(package_count)
    stocks = [_stock(package_id) for package_id in package_ids]
    with SessionLocal() as db:
        package_cache = {}

        def exercise():
            first = _package_allocation_candidates(db, stocks, package_cache=package_cache)
            stocks[0].available_qty = 0
            stocks[0].reserved_qty = 1
            second = _package_allocation_candidates(db, stocks, package_cache=package_cache)
            return first, second

        (result, statements) = _package_selects(db.bind, exercise)

    (first_groups, first_partial), (second_groups, second_partial) = result
    assert set(first_groups) == set(package_ids)
    assert first_partial == []
    assert set(second_groups) == set(package_ids[1:])
    assert second_partial == []
    assert len(statements) == 1


def test_package_candidate_cache_preserves_missing_and_partial_legacy_semantics():
    package_ids, model_id = _packages(1)
    marker = uuid4().hex[:8]
    with SessionLocal() as db:
        receipt = LegacyStockReceipt(
            source_system="PERF26", source_warehouse_id="test", source_record_id=marker,
            source_checksum="0" * 64, source_payload={"test": True},
        )
        db.add(receipt)
        db.flush()
        legacy_package = Package(
            package_no=f"PERF26-LEGACY-{marker}", barcode=f"PERF26-LEGACY-BC-{marker}",
            legacy_receipt_id=receipt.id, model_id=model_id, color="mixed",
            total_quantity=5, capacity=5, status="received_in_storage",
        )
        db.add(legacy_package)
        db.commit()
        legacy_package_id = int(legacy_package.id)

    rows = [_stock(package_ids[0]), _stock(legacy_package_id, 5), _stock(None, 3), _stock(2_147_483_647)]
    with SessionLocal() as db:
        uncached_groups, uncached_partial = _package_allocation_candidates(db, rows)
        cached_groups, cached_partial = _package_allocation_candidates(db, rows, package_cache={})

    assert list(cached_groups) == list(uncached_groups) == package_ids
    assert cached_partial == uncached_partial == [rows[1], rows[2]]


def test_metadata_repair_does_not_write_cached_package_eligibility_fields(monkeypatch):
    package_ids, model_id = _packages(1)
    with SessionLocal() as db:
        package = db.get(Package, package_ids[0])
        marker = uuid4().hex[:8]
        brand = Brand(name=f"PERF26 brand {marker}")
        db.add(brand)
        db.flush()
        collection = Collection(brand_id=brand.id, name=f"PERF26 collection {marker}", year=2026)
        db.add(collection)
        db.flush()
        stock = FinishedGoodsStock(
            package_id=package.id, production_order_id=package.production_order_id,
            model_id=model_id, color="navy", size="M", quantity=1,
            available_qty=1, reserved_qty=0, sold_qty=0, status="available",
        )
        db.add(stock)
        db.commit()
        before = (package.id, package.status, package.legacy_receipt_id, package.total_quantity)
        monkeypatch.setattr(
            finished_goods_service,
            "infer_brand_and_collection",
            lambda *_args, **_kwargs: (brand.id, collection.id),
        )
        assert finished_goods_service.repair_missing_brand_metadata(db, model_ids={model_id}) == 1
        after = (package.id, package.status, package.legacy_receipt_id, package.total_quantity)
        assert (stock.brand_id, stock.collection_id) == (brand.id, collection.id)
    assert after == before
