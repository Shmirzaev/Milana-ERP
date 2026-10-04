"""PERF26: branded reservation repeated variant, package and metadata reads.

`_reserve_branded_stock` used to walk the order's requested variants one at a
time. Per variant it ran its own ``SELECT ... FOR UPDATE`` over
``finished_goods_stock``, and `_package_allocation_candidates` then re-read and
re-locked the same packages twice for that variant (once for the shortage
pre-check, once for the allocation). `repair_missing_brand_metadata` did the same
in miniature: one `db.get`/metadata query per legacy stock row.

So the rows the database delivered scaled with the number of variants, and the
packages were read and locked three times over, all to answer the same question.

The fix batches the variant candidates, reuses the packages the caller has already
locked, and reads the metadata references for the whole repair batch up front.

Rows, not statements
--------------------
The proofs count **rows the database delivered**, bucketed by the table a
statement reads (`after_cursor_execute` + `cursor.rowcount`). Statement counts are
the weaker claim on this codebase: a per-row read and a batched read can issue the
same number of statements while delivering very different row counts, so the
assertion is on rows. This needs real PostgreSQL, because `cursor.rowcount` is
meaningless on SQLite.

The data is grown *between* the two measurements. Seeding both sizes up front
would let a bounded read and an unbounded read measure the same thing.

Lock order (the settled decision)
--------------------------------
`key_share=True` renders ``FOR NO KEY UPDATE`` at all four reservation lock sites,
and the package-first ordering is preserved: within a batch the packages are locked
before any stock row. Lock order has no row metric, so it is pinned on the SQL
text, and the precedent is `ALLOWANCE_LOCK` in `test_accessory_return_allowance_lock`.

PostgreSQL only. Set STABILIZATION_POSTGRES_URL to run it; without that variable
every test in this module SKIPs.
"""

import os
import re
from contextlib import contextmanager
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.routes import sales as sales_routes
from app.db.base import Base
from app.models import (
    Brand,
    Collection,
    CollectionModel,
    Customer,
    FinishedGoodsStock,
    Model,
    Package,
    ProductionOrder,
    SalesOrder,
    SalesOrderItem,
    User,
)
import app.models  # noqa: F401  (register every table in Base.metadata)

# The reservation path locks with key_share=True, i.e. FOR NO KEY UPDATE.
PACKAGE_LOCK = "FOR NO KEY UPDATE OF packages"
STOCK_LOCK = "FOR NO KEY UPDATE OF finished_goods_stock"

SMALL_VARIANTS = 1
LARGE_VARIANTS = 7

# Model grid: three colours x three sizes, one whole-bag package per cell.
COLORS = ("white", "black", "navy")
SIZES = ("S", "M", "L")
CELL_QTY = 5


# --------------------------------------------------------------------------- #
# PostgreSQL fixture
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def perf26_postgres_sessions():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip(
            "Set STABILIZATION_POSTGRES_URL for real PostgreSQL PERF26 reservation coverage"
        )
    url = make_url(raw_url)
    if (
        url.get_backend_name() != "postgresql"
        or url.host not in {"127.0.0.1", "localhost", "::1"}
        or url.query
    ):
        pytest.fail("PERF26 tests require a loopback PostgreSQL URL without connection overrides")
    schema = f"perf26_branded_{uuid4().hex}"
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    assert engine.dialect.name == "postgresql"
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        Base.metadata.create_all(engine)
        yield engine, sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    finally:
        engine.dispose()
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')


_TABLES = (
    "sales_orders", "sales_order_items", "finished_goods_stock", "packages",
    "customers", "models", "brands", "collections", "collection_models",
    "production_orders", "users",
)

_FROM_RE = re.compile(r"\bFROM\s+([a-z_]+)", re.IGNORECASE)


def _bucket(statement: str) -> str:
    """The table a statement reads rows from, or '' when it reads none."""
    for match in _FROM_RE.finditer(statement or ""):
        table = match.group(1)
        if table in _TABLES:
            return table
    return ""


class _RowProbe:
    """Rows delivered by the database, bucketed by the table each statement reads."""

    def __init__(self, engine):
        self.engine = engine
        self.rows = {}
        self.statements = []

    def _hook(self, conn, cursor, statement, parameters, context, executemany):
        rowcount = cursor.rowcount
        if rowcount is None or rowcount < 0:
            # Would make the row measurement meaningless; fail loudly instead.
            raise AssertionError(f"rowcount {rowcount} is not usable on this driver")
        bucket = _bucket(statement)
        self.statements.append((bucket, rowcount, statement))
        self.rows[bucket] = self.rows.get(bucket, 0) + rowcount

    def total(self, table: str) -> int:
        return self.rows.get(table, 0)

    def locking(self, needle: str):
        return [entry for entry in self.statements if needle in (entry[2] or "")]

    @contextmanager
    def measure(self):
        event.listen(self.engine, "after_cursor_execute", self._hook)
        self.rows = {}
        self.statements = []
        try:
            yield self
        finally:
            event.remove(self.engine, "after_cursor_execute", self._hook)


# --------------------------------------------------------------------------- #
# Seeding
# --------------------------------------------------------------------------- #
def _seed_warehouse(session_factory, *, prefix, order=True):
    """A model on a 3x3 colour/size grid, one whole-bag package per cell.

    Returns the ids the tests need. The grid is what makes the variant proofs
    meaningful: a wildcard variant and a colour/size-restricted variant resolve to
    *overlapping* sets of stock rows, so a per-variant read delivers those rows
    again and again while a batched read delivers them once.
    """
    with session_factory.begin() as db:
        customer = Customer(name=f"PERF26 customer {prefix}")
        brand = Brand(name=f"PERF26 brand {prefix}")
        db.add_all([customer, brand])
        # Flush first: Collection.brand_id is NOT NULL and needs the brand's id.
        db.flush()
        collection = Collection(
            name=f"PERF26 collection {prefix}", brand_id=brand.id, year=2026
        )
        db.add(collection)
        db.flush()
        model = Model(code=f"PERF26-MODEL{prefix}", name=f"PERF26 model{prefix}", status="approved")
        db.add(model)
        db.flush()
        db.add(CollectionModel(collection_id=collection.id, model_id=model.id))
        production_order = ProductionOrder(
            production_no=f"PERF26-PO{prefix}",
            production_type="branded_stock",
            model_id=model.id,
            status="completed",
            planned_quantity=1000,
        )
        db.add(production_order)
        db.flush()

        package_ids = []
        for color in COLORS:
            for size in SIZES:
                package = Package(
                    package_no=f"PERF26-PKG{prefix}-{color}-{size}",
                    barcode=f"PERF26-BC{prefix}-{color}-{size}",
                    packaging_department_code="PKG",
                    production_order_id=production_order.id,
                    model_id=model.id,
                    brand_id=brand.id,
                    collection_id=collection.id,
                    color=color,
                    total_quantity=CELL_QTY,
                    capacity=CELL_QTY,
                    stock_kind="standard",
                    status="received_in_storage",
                )
                db.add(package)
                db.flush()
                # One stock row per package, fully available: the whole-bag
                # eligibility test needs available == quantity and reserved == 0.
                db.add(FinishedGoodsStock(
                    production_order_id=production_order.id,
                    package_id=package.id,
                    model_id=model.id,
                    brand_id=brand.id,
                    collection_id=collection.id,
                    color=color,
                    size=size,
                    quantity=CELL_QTY,
                    available_qty=CELL_QTY,
                    reserved_qty=0,
                    sold_qty=0,
                    status="available",
                ))
                package_ids.append(int(package.id))
        db.flush()

        sales_order = None
        user = None
        if order:
            user = User(
                name=f"PERF26 user {prefix}",
                email=f"perf26-{prefix.lower()}@example.test",
                password_hash="x",
                is_active=True,
            )
            sales_order = SalesOrder(
                order_no=f"PERF26-SO{prefix}",
                status="draft",
                order_type="branded_stock_sale",
                customer_id=customer.id,
                total_amount=1000,
            )
            db.add_all([user, sales_order])
            db.flush()

        return {
            "customer_id": int(customer.id),
            "brand_id": int(brand.id),
            "collection_id": int(collection.id),
            "model_id": int(model.id),
            "production_order_id": int(production_order.id),
            "package_ids": package_ids,
            "cells": len(package_ids),
            "sales_order_id": int(sales_order.id) if sales_order else None,
            "user_id": int(user.id) if user else None,
        }


def _reserve(db, case, lines):
    """Reserve `lines` for the order, with notifications and hard failures off."""
    so = db.query(SalesOrder).filter(SalesOrder.id == case["sales_order_id"]).one()
    user = db.query(User).filter(User.id == case["user_id"]).one()
    for line in lines:
        db.add(SalesOrderItem(
            sales_order_id=so.id,
            model_id=line["model_id"],
            brand_id=line["brand_id"],
            color=line["color"],
            size=line["size"],
            quantity=line["quantity"],
            unit_price=10,
            source_type="branded_stock",
        ))
    db.flush()
    reservations, shortages = sales_routes._reserve_branded_stock(
        db,
        so=so,
        current=user,
        lines=[
            item for item in db.query(SalesOrderItem)
            .filter(SalesOrderItem.sales_order_id == so.id)
            .all()
        ],
        fail_on_shortage=False,
        notify_shortage=False,
        notify_storage_when_ready=False,
    )
    return reservations, shortages


def _line(case, color, size, quantity):
    return {
        "model_id": case["model_id"],
        "brand_id": case["brand_id"],
        "color": color,
        "size": size,
        "quantity": quantity,
    }


@pytest.fixture()
def warehouse(perf26_postgres_sessions):
    engine, session_factory = perf26_postgres_sessions
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "TRUNCATE stock_reservations, finished_goods_stock, shipment_packages, "
            "shipments, packages, sales_order_items, sales_orders, collection_models, "
            "collections, brands, customers, models, production_orders, users "
            "RESTART IDENTITY CASCADE"
        )
    return engine, session_factory


# --------------------------------------------------------------------------- #
# 1. Variant candidates are batched, so the delivered rows do not track variants
# --------------------------------------------------------------------------- #
def test_variant_candidate_rows_do_not_grow_with_the_variant_count(warehouse):
    engine, session_factory = warehouse
    probe = _RowProbe(engine)

    # Measurement 1: one wildcard variant, which matches every grid cell.
    case_a = _seed_warehouse(session_factory, prefix="A", order=True)
    with session_factory.begin() as db:
        with probe.measure() as measured:
            reservations, _ = _reserve(
                db, case_a, [_line(case_a, "*", "*", CELL_QTY * case_a["cells"])]
            )
        small_stock_rows = measured.total("finished_goods_stock")
    assert len(reservations) == case_a["cells"], "the wildcard variant must reserve every cell"

    # Grow *between* the measurements: a second, identically sized warehouse whose
    # order requests seven variants, each a subset of the same grid. A per-variant
    # read delivers the shared rows again for every variant; a batched read
    # delivers the union once. A separate warehouse keeps the second
    # measurement's eligible set the same size as the first.
    case_b = _seed_warehouse(session_factory, prefix="B", order=True)
    overlapping = [
        _line(case_b, "*", "*", CELL_QTY * case_b["cells"]),
        _line(case_b, "white", "*", CELL_QTY * len(SIZES)),
        _line(case_b, "black", "*", CELL_QTY * len(SIZES)),
        _line(case_b, "navy", "*", CELL_QTY * len(SIZES)),
        _line(case_b, "*", "S", CELL_QTY * len(COLORS)),
        _line(case_b, "*", "M", CELL_QTY * len(COLORS)),
        _line(case_b, "*", "L", CELL_QTY * len(COLORS)),
    ]
    assert len(overlapping) == LARGE_VARIANTS
    with session_factory.begin() as db:
        with probe.measure() as measured:
            reservations, _ = _reserve(db, case_b, overlapping)
        large_stock_rows = measured.total("finished_goods_stock")

    print(
        f"\nPERF26 variant candidates: finished_goods_stock rows delivered="
        f"{small_stock_rows}->{large_stock_rows} for {SMALL_VARIANTS}->{LARGE_VARIANTS} variants"
    )
    assert reservations, "the seven-variant order must still reserve stock"

    # A batched read delivers the eligible set once, whatever the variant count.
    assert small_stock_rows == case_a["cells"]
    assert large_stock_rows == small_stock_rows, (
        f"delivered stock rows grew from {small_stock_rows} to {large_stock_rows} "
        f"when the variant count grew from {SMALL_VARIANTS} to {LARGE_VARIANTS}"
    )


def test_variant_candidate_rows_are_not_a_multiple_of_the_variant_count(warehouse):
    """The delivered rows equal the eligible set, not the eligible set per variant."""
    engine, session_factory = warehouse
    case = _seed_warehouse(session_factory, prefix="B", order=True)
    probe = _RowProbe(engine)

    lines = [
        _line(case, "*", "*", CELL_QTY),
        _line(case, "white", "*", CELL_QTY),
        _line(case, "*", "S", CELL_QTY),
    ]
    with session_factory.begin() as db:
        with probe.measure() as measured:
            reservations, _ = _reserve(db, case, lines)

    stock_rows = measured.total("finished_goods_stock")
    cells = case["cells"]
    print(
        f"\nPERF26 three overlapping variants delivered {stock_rows} stock rows "
        f"for an eligible set of {cells} cells"
    )
    assert reservations
    # Three variants, each matching a subset of the same grid. Per-variant reads
    # would deliver at least `cells` again for every variant after the first.
    assert stock_rows == cells, (
        f"3 overlapping variants delivered {stock_rows} stock rows for a "
        f"{cells}-row eligible set; per-variant reads would deliver more"
    )


# --------------------------------------------------------------------------- #
# 2. Locked packages are reused, so each package row is read once
# --------------------------------------------------------------------------- #
def test_package_rows_do_not_grow_with_the_variant_count(warehouse):
    """Each package row is read once per package-lock statement, not per variant.

    The reservation takes the package-first locks in two statements: the
    order-wide pre-lock, then the batched variant lock. Re-reading the packages in
    `_package_allocation_candidates` — once for the shortage pre-check and again
    for the allocation — is what made the delivered rows scale with the variant
    count, and the `package_cache` is what removes it.
    """
    engine, session_factory = warehouse
    probe = _RowProbe(engine)

    # Measurement 1: one wildcard variant covering the whole grid.
    case_a = _seed_warehouse(session_factory, prefix="C", order=True)
    with session_factory.begin() as db:
        with probe.measure() as measured:
            reservations, _ = _reserve(
                db, case_a, [_line(case_a, "*", "*", CELL_QTY * case_a["cells"])]
            )
        small = measured.total("packages")
        small_statements = len(measured.locking(PACKAGE_LOCK))
    assert reservations

    # Measurement 2: four variants over the same grid, one wildcard plus three
    # colour subsets, on a separate identically sized warehouse.
    case_b = _seed_warehouse(session_factory, prefix="D", order=True)
    four = [_line(case_b, "*", "*", CELL_QTY * case_b["cells"])] + [
        _line(case_b, color, "*", CELL_QTY * len(SIZES)) for color in COLORS
    ]
    with session_factory.begin() as db:
        with probe.measure() as measured:
            reservations, _ = _reserve(db, case_b, four)
        large = measured.total("packages")
        large_statements = len(measured.locking(PACKAGE_LOCK))

    print(
        f"\nPERF26 package rows delivered={small}->{large} for "
        f"{case_a['cells']} packages, package-lock statements="
        f"{small_statements}->{large_statements}"
    )
    assert reservations

    # Two package-first lock statements regardless of the variant count: the
    # order-wide pre-lock and one batched variant lock.
    assert small_statements == large_statements == 2
    assert small == 2 * case_a["cells"]
    assert large == small, (
        f"delivered package rows grew from {small} to {large} when the variant "
        f"count grew; the locked packages are reused, not re-read"
    )


# --------------------------------------------------------------------------- #
# 3. Lock mode and lock order: the settled decision
# --------------------------------------------------------------------------- #
def test_reservation_locks_packages_first_with_for_no_key_update(warehouse):
    engine, session_factory = warehouse
    case = _seed_warehouse(session_factory, prefix="D", order=True)
    probe = _RowProbe(engine)

    with session_factory.begin() as db:
        with probe.measure() as measured:
            _reserve(db, case, [_line(case, "white", "*", CELL_QTY)])

    package_locks = measured.locking(PACKAGE_LOCK)
    stock_locks = measured.locking(STOCK_LOCK)
    print(
        f"\nPERF26 lock sites: {PACKAGE_LOCK} x{len(package_locks)}, "
        f"{STOCK_LOCK} x{len(stock_locks)}"
    )

    # Both lock families are exercised.
    assert package_locks, f"no {PACKAGE_LOCK} statement was issued"
    assert stock_locks, f"no {STOCK_LOCK} statement was issued"

    # No site may fall back to the broader FOR UPDATE.
    for _bucket_name, _rowcount, statement in measured.statements:
        assert "FOR UPDATE OF packages" not in statement, (
            f"a package lock regressed to FOR UPDATE: {statement}"
        )
        assert "FOR UPDATE OF finished_goods_stock" not in statement, (
            f"a stock lock regressed to FOR UPDATE: {statement}"
        )

    # Package-first ordering: every package lock precedes every stock lock.
    package_positions = [
        index for index, entry in enumerate(measured.statements) if PACKAGE_LOCK in (entry[2] or "")
    ]
    stock_positions = [
        index for index, entry in enumerate(measured.statements) if STOCK_LOCK in (entry[2] or "")
    ]
    assert max(package_positions) < min(stock_positions), (
        "a stock row was locked before the package locks were taken"
    )

    # Packages are locked in id order so concurrent reservations agree.
    for _bucket_name, _rowcount, statement in package_locks:
        assert re.search(r"ORDER BY\s+packages\.id", statement), (
            f"package lock is not ordered by package id: {statement}"
        )


# --------------------------------------------------------------------------- #
# 4. Mutable completeness must be recomputed, not cached
# --------------------------------------------------------------------------- #
def test_whole_bag_eligibility_is_recomputed_after_a_package_is_consumed(warehouse):
    """Only package *identity* is cacheable; eligibility reads mutable quantities.

    `_package_allocation_candidates` is called twice per variant — once for the
    shortage pre-check and once for the allocation — and the allocation mutates
    `available_qty`/`reserved_qty` in between. The whole-bag test reads those
    mutable fields, so caching its *result* would offer a consumed package for a
    second time. This pins that only the locked `Package` rows are reused.
    """
    engine, session_factory = warehouse
    case = _seed_warehouse(session_factory, prefix="E", order=True)

    with session_factory() as db:
        package_id = case["package_ids"][0]
        rows = (
            db.query(FinishedGoodsStock)
            .filter(FinishedGoodsStock.package_id == package_id)
            .all()
        )
        assert rows, "the fixture must attach a stock row to the package"
        assert {int(row.package_id) for row in rows} == {package_id}

        package_cache: dict = {}
        groups_before, partial_before = sales_routes._package_allocation_candidates(
            db, rows, package_cache=package_cache
        )
        # The package really was read once and cached.
        assert set(groups_before) == {package_id}
        assert partial_before == []
        assert set(package_cache) == {package_id}

        # Consume the package exactly the way the allocator does.
        for row in rows:
            take = int(row.available_qty or 0)
            row.available_qty = 0
            row.reserved_qty = int(row.reserved_qty or 0) + take
            row.status = "reserved"
        db.flush()

        groups_after, _partial_after = sales_routes._package_allocation_candidates(
            db, rows, package_cache=package_cache
        )

    # The cache still holds only the package identity, so nothing was re-read...
    assert set(package_cache) == {package_id}
    # ...but the package is no longer a whole-bag candidate, because the mutable
    # completeness of its stock rows was re-evaluated rather than reused.
    assert groups_after == {}, (
        "a consumed package was still offered as a whole-bag candidate; the "
        "mutable completeness check was cached instead of recomputed"
    )


# --------------------------------------------------------------------------- #
# 5. Metadata repair reads its references for the batch, not per row
# --------------------------------------------------------------------------- #
def _seed_legacy_stock(session_factory, *, prefix, with_sales_order, count):
    """`count` legacy stock rows missing both brand and collection metadata.

    With `with_sales_order` the rows resolve through their sales order's lines;
    without one they fall through to the model -> collection lookup. Both paths
    are per-row queries before the fix and one batched read after it.
    """
    with session_factory.begin() as db:
        case = _seed_warehouse(session_factory, prefix=prefix, order=False)
        customer = Customer(name=f"PERF26 legacy customer {prefix}")
        db.add(customer)
        db.flush()
        sales_order = None
        if with_sales_order:
            sales_order = SalesOrder(
                order_no=f"PERF26-LEGACY-SO{prefix}",
                status="confirmed",
                order_type="branded_stock_sale",
                customer_id=customer.id,
                total_amount=100,
            )
            db.add(sales_order)
            db.flush()
            # Exactly one line for the model, shared by every legacy row.
            db.add(SalesOrderItem(
                sales_order_id=sales_order.id,
                model_id=case["model_id"],
                brand_id=case["brand_id"],
                collection_id=case["collection_id"],
                color="white",
                size="M",
                quantity=count,
                unit_price=1,
            ))
        for index in range(count):
            db.add(FinishedGoodsStock(
                sales_order_id=sales_order.id if sales_order else None,
                model_id=case["model_id"],
                color="white",
                size="M",
                quantity=1,
                available_qty=1,
                reserved_qty=0,
                sold_qty=0,
                status="available",
            ))
        db.flush()
        case["legacy_count"] = count
        return case


def test_metadata_repair_reference_rows_do_not_grow_with_the_row_count(warehouse):
    """Sales-order and model metadata rows are read once for the whole batch."""
    engine, session_factory = warehouse
    probe = _RowProbe(engine)

    _seed_legacy_stock(session_factory, prefix="F", with_sales_order=True, count=3)
    with session_factory.begin() as db:
        with probe.measure() as measured:
            from app.services.finished_goods import repair_missing_brand_metadata
            updated = repair_missing_brand_metadata(db)
        small_items = measured.total("sales_order_items")
        small_model_meta = measured.total("collection_models")

    # Grow *between* the measurements with rows that share the same references.
    _seed_legacy_stock(session_factory, prefix="G", with_sales_order=True, count=12)
    with session_factory.begin() as db:
        with probe.measure() as measured:
            from app.services.finished_goods import repair_missing_brand_metadata
            updated = repair_missing_brand_metadata(db)
        large_items = measured.total("sales_order_items")
        large_model_meta = measured.total("collection_models")

    print(
        f"\nPERF26 metadata repair: sales_order_items rows={small_items}->{large_items} "
        f"collection_models rows={small_model_meta}->{large_model_meta}"
    )
    assert updated >= 3, "the fixture must actually repair rows"

    # The repair is not vacuous: the second batch really was larger.
    assert large_items >= small_items

    # The second batch resolves through its own sales order, so it legitimately
    # reads that order's single line. What must not happen is reading the shared
    # line once per repaired row: 12 rows must not cost 12 reads.
    assert large_items <= 2 * small_items + 2, (
        f"sales_order_items rows delivered grew {small_items}->{large_items} for "
        f"3->12 legacy rows; per-row reads would scale with the row count"
    )


def test_metadata_repair_model_fallback_rows_do_not_grow_with_the_row_count(warehouse):
    """The model -> collection fallback is batched too."""
    engine, session_factory = warehouse
    probe = _RowProbe(engine)

    _seed_legacy_stock(session_factory, prefix="H", with_sales_order=False, count=3)
    with session_factory.begin() as db:
        with probe.measure() as measured:
            from app.services.finished_goods import repair_missing_brand_metadata
            repair_missing_brand_metadata(db)
        small_model_meta = measured.total("collection_models")

    _seed_legacy_stock(session_factory, prefix="I", with_sales_order=False, count=12)
    with session_factory.begin() as db:
        with probe.measure() as measured:
            from app.services.finished_goods import repair_missing_brand_metadata
            repair_missing_brand_metadata(db)
        large_model_meta = measured.total("collection_models")

    print(
        f"\nPERF26 metadata repair model fallback: collection_models rows="
        f"{small_model_meta}->{large_model_meta} for 3->12 legacy rows"
    )

    # One model -> collection row per model, read once. Per-row reads would deliver
    # 3 then 12, i.e. scale with the row count.
    assert large_model_meta == small_model_meta, (
        f"collection_models rows delivered grew {small_model_meta}->{large_model_meta} "
        f"for 3->12 legacy rows; per-row reads would scale with the row count"
    )
    assert small_model_meta == 1, (
        f"expected exactly one model->collection row per model, saw {small_model_meta}"
    )


def test_metadata_repair_still_repairs_exactly_the_legacy_rows(warehouse):
    """Batching the reads must not widen or narrow what gets repaired."""
    engine, session_factory = warehouse
    case = _seed_legacy_stock(session_factory, prefix="J", with_sales_order=True, count=5)

    with session_factory.begin() as db:
        from app.services.finished_goods import repair_missing_brand_metadata
        before = db.query(FinishedGoodsStock).filter(
            FinishedGoodsStock.brand_id.is_(None)
            | FinishedGoodsStock.collection_id.is_(None)
        ).count()
        updated = repair_missing_brand_metadata(db)
        after = db.query(FinishedGoodsStock).filter(
            FinishedGoodsStock.brand_id.is_(None)
            | FinishedGoodsStock.collection_id.is_(None)
        ).count()

    assert before == 5
    assert updated == 5
    assert after == 0

    with session_factory() as db:
        # Only the seeded legacy rows: the warehouse rows already carry metadata.
        rows = db.query(FinishedGoodsStock).filter(
            FinishedGoodsStock.model_id == case["model_id"],
            FinishedGoodsStock.package_id.is_(None),
        ).all()
        repaired = [r for r in rows if r.brand_id is not None and r.collection_id is not None]
        assert len(rows) == 5
        assert len(repaired) == 5
        assert {int(r.brand_id) for r in repaired} == {case["brand_id"]}
        assert {int(r.collection_id) for r in repaired} == {case["collection_id"]}
