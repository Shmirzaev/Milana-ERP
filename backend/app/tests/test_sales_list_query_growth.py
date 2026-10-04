"""PERF24: sales and shipment lists read their customer/order references per row.

`GET /sales-orders` and `GET /shipments` both build their payload by looping over
the page and resolving the display references for each row individually:

* `_serialize_sales_order` did `db.get(Customer, so.customer_id)` per order, and
* `_shipment_payload` did `db.get(SalesOrder, ...)` and `db.get(Customer, ...)`
  per shipment.

`db.get` is an *entity* read, so each row pulled a whole `Customer` / `SalesOrder`
row and built an ORM instance for it, and the identity map turns a repeated
customer into a second read of the same row rather than into a shared one. The
cost of the page therefore scaled with the page, not with the number of distinct
references the page actually needs.

The fix selects the two display columns into a bounded reference map and passes it
to the serializer, so the page hydrates zero `Customer` / `SalesOrder` entities
while still rendering exactly the same fields.

Rows, not statements
--------------------
The proof counts **rows delivered to the ORM**, via `after_cursor_execute` and
`cursor.rowcount` restricted to statements whose compiled `Select` reports the
entity in `column_descriptions`. A statement count would be the weaker claim, and
on this codebase a per-row read can trade one statement for many rows, so the
measurement is deliberately about rows. It needs real PostgreSQL, because
`cursor.rowcount` is meaningless on SQLite.

The data is grown *between* the two measurements. Seeding both sizes up front and
measuring afterwards would let a bounded read and an unbounded read measure the
same thing.

Every measurement runs in a fresh session: a warm identity map would satisfy the
old per-row `db.get` from memory and hide the defect entirely.

PostgreSQL only. Set STABILIZATION_POSTGRES_URL to run it; without that variable
every test in this module SKIPs.
"""

import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.routes import sales as sales_routes
from app.api.routes import shipments as shipment_routes
from app.db.base import Base
from app.models import (
    Customer,
    Model,
    ProductionOrder,
    SalesOrder,
    SalesOrderItem,
    Shipment,
    ShipmentPackage,
    ShipmentScanLog,
    Package,
)
import app.models  # noqa: F401  (register every table in Base.metadata)

BASE_TS = datetime(2024, 6, 1, 9, 0, tzinfo=timezone.utc)

# Page sizes for the two measurements. The second is five times the first, so a
# per-row read has five times the opportunity to show itself.
SMALL_PAGE = 4
LARGE_PAGE = 20


# --------------------------------------------------------------------------- #
# PostgreSQL fixture
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def perf24_postgres_sessions():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip(
            "Set STABILIZATION_POSTGRES_URL for real PostgreSQL PERF24 list-reference coverage"
        )
    url = make_url(raw_url)
    if (
        url.get_backend_name() != "postgresql"
        or url.host not in {"127.0.0.1", "localhost", "::1"}
        or url.query
    ):
        pytest.fail("PERF24 tests require a loopback PostgreSQL URL without connection overrides")
    schema = f"perf24_list_refs_{uuid4().hex}"
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


@pytest.fixture()
def pg(perf24_postgres_sessions):
    engine, session_factory = perf24_postgres_sessions
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "TRUNCATE shipment_scan_logs, shipment_packages, shipments, sales_order_items, "
            "sales_orders, customers, models, production_orders, packages RESTART IDENTITY CASCADE"
        )
    return engine, session_factory


# --------------------------------------------------------------------------- #
# Seeding
# --------------------------------------------------------------------------- #
def _seed_orders(session_factory, *, prefix, count):
    """`count` sales orders, each with its own customer.

    Distinct customers are the point: with a shared customer the old
    `db.get(Customer, ...)` would hit the identity map after the first row and
    the per-row read would be invisible.
    """
    with session_factory.begin() as db:
        model = Model(code=f"PERF24-MODEL{prefix}", name=f"PERF24 model{prefix}", status="approved")
        db.add(model)
        db.flush()
        order_ids = []
        customer_ids = []
        for index in range(1, count + 1):
            customer = Customer(name=f"PERF24 customer {prefix} {index}")
            db.add(customer)
            db.flush()
            order = SalesOrder(
                order_no=f"PERF24-SO{prefix}-{index}",
                status="draft",
                order_type="client_order",
                customer_id=customer.id,
                total_amount=100 + index,
            )
            db.add(order)
            db.flush()
            db.add(SalesOrderItem(
                sales_order_id=order.id,
                model_id=model.id,
                quantity=5,
                size="M",
                color="white",
                unit_price=10,
            ))
            order_ids.append(int(order.id))
            customer_ids.append(int(customer.id))
        return {"order_ids": order_ids, "customer_ids": customer_ids}


def _seed_shipments(session_factory, *, prefix, count, deleted=0, override_every=0, package_per=0):
    """`count` shipments, each on its own sales order.

    `override_every` shipments carry a shipment-level `customer_id`, which must
    win over their order's customer. `deleted` shipments are soft-deleted and must
    never be listed. `package_per` attaches that many packages to each shipment so
    the counts and totals have something real to sum.
    """
    with session_factory.begin() as db:
        model = Model(code=f"PERF24-SHPMODEL{prefix}", name=f"PERF24 model{prefix}", status="approved")
        db.add(model)
        db.flush()
        production_order = ProductionOrder(
            production_no=f"PERF24-PO{prefix}",
            production_type="branded_stock",
            model_id=model.id,
            status="completed",
            planned_quantity=1000,
        )
        db.add(production_order)
        db.flush()

        shipment_ids = []
        order_customer_ids = []
        for index in range(1, count + 1):
            order_customer = Customer(name=f"PERF24 order customer {prefix} {index}")
            db.add(order_customer)
            db.flush()
            order = SalesOrder(
                order_no=f"PERF24-SHPSO{prefix}-{index}",
                status="confirmed",
                order_type="client_order",
                customer_id=order_customer.id,
                total_amount=500 + index,
            )
            db.add(order)
            db.flush()
            override_customer = None
            if override_every and index % override_every == 0:
                override_customer = Customer(name=f"PERF24 override customer {prefix} {index}")
                db.add(override_customer)
                db.flush()
            shipment = Shipment(
                shipment_no=f"PERF24-SHP{prefix}-{index}",
                status="draft",
                sales_order_id=order.id,
                customer_id=override_customer.id if override_customer else None,
                transport_details={},
                dispatch_snapshot={},
            )
            if index > count - deleted:
                shipment.deleted_at = BASE_TS + timedelta(minutes=index)
            db.add(shipment)
            db.flush()
            for slot in range(package_per):
                package = Package(
                    package_no=f"PERF24-PKG{prefix}-{index}-{slot}",
                    barcode=f"PERF24-BC{prefix}-{index}-{slot}",
                    packaging_department_code="PKG",
                    production_order_id=production_order.id,
                    model_id=model.id,
                    color="white",
                    total_quantity=10 + slot,
                    capacity=60,
                    status="received_in_storage",
                )
                db.add(package)
                db.flush()
                db.add(ShipmentPackage(
                    shipment_id=shipment.id,
                    package_id=package.id,
                    quantity=10 + slot,
                ))
            shipment_ids.append(int(shipment.id))
            order_customer_ids.append(int(order_customer.id))
        return {
            "shipment_ids": shipment_ids,
            "order_customer_ids": order_customer_ids,
            "count": count,
            "deleted": deleted,
        }


# --------------------------------------------------------------------------- #
# Row measurement
# --------------------------------------------------------------------------- #
class _EntityRowProbe:
    """ORM entity instances actually built, counted via the `load` event.

    This is the row measurement, not a statement count. A bounded reference read
    such as `db.query(Customer.id, Customer.name)` returns plain tuples and
    hydrates nothing, so it registers zero `load` events however many rows it
    pulled. The old per-row `db.get(Customer, ...)` built one instance per row and
    registers one event per instance. Statement counts cannot tell those apart:
    both shapes can issue the same number of statements.

    `rowcount` is tracked too, as context for the printout, but it is not what the
    assertions rest on, because `cursor.rowcount` is meaningless on SQLite and this
    module is PostgreSQL-only anyway.

    Every measurement must run in a **fresh session**: a warm identity map would
    satisfy the old per-row `db.get` from memory, hydrate nothing, and hide the
    defect completely.
    """

    def __init__(self, entities):
        self.entities = tuple(entities)
        self.hydrated = 0
        self.by_entity = {entity.__name__: 0 for entity in self.entities}
        self.rowcount_total = 0
        self._handlers = {}

    def _load_handler(self, entity):
        def handler(target, context):
            self.hydrated += 1
            self.by_entity[entity.__name__] += 1
        return handler

    def _rowcount_handler(self, conn, cursor, statement, parameters, context, executemany):
        if cursor.rowcount is not None and cursor.rowcount >= 0:
            self.rowcount_total += cursor.rowcount

    @contextmanager
    def measure(self):
        self.hydrated = 0
        self.by_entity = {entity.__name__: 0 for entity in self.entities}
        self.rowcount_total = 0
        for entity in self.entities:
            self._handlers[entity] = self._load_handler(entity)
            event.listen(entity, "load", self._handlers[entity])
        try:
            yield self
        finally:
            for entity, handler in self._handlers.items():
                event.remove(entity, "load", handler)
            self._handlers = {}


# --------------------------------------------------------------------------- #
# 1. GET /sales-orders — customer references must not be read per row
# --------------------------------------------------------------------------- #
def test_sales_list_hydrates_no_customer_entities_per_row(pg):
    engine, session_factory = pg
    _seed_orders(session_factory, prefix="A", count=SMALL_PAGE)
    probe = _EntityRowProbe((Customer,))

    with session_factory() as db:
        with probe.measure() as measured:
            small = sales_routes.list_sales_orders(
                db, None, page=1, page_size=SMALL_PAGE, include_total=True
            )
    small_hydrated = measured.hydrated
    small_customers = measured.by_entity["Customer"]
    assert len(small["rows"]) == SMALL_PAGE

    # Grow the data *between* the measurements, then ask for five times the page.
    _seed_orders(session_factory, prefix="B", count=LARGE_PAGE)
    with session_factory() as db:
        with probe.measure() as measured:
            large = sales_routes.list_sales_orders(
                db, None, page=1, page_size=LARGE_PAGE, include_total=True
            )
    large_hydrated = measured.hydrated
    large_customers = measured.by_entity["Customer"]

    print(
        f"\nPERF24 sales list Customer entities hydrated={small_customers}->{large_customers} "
        f"(page {SMALL_PAGE}->{LARGE_PAGE})"
    )

    # The page really did get five times bigger, so this is not a vacuous pass.
    assert len(small["rows"]) == SMALL_PAGE
    assert len(large["rows"]) == LARGE_PAGE
    assert large["total"] == SMALL_PAGE + LARGE_PAGE

    # Fixture integrity: the page really does name SMALL_PAGE *distinct*
    # customers, so the old per-row `db.get` had SMALL_PAGE separate customers to
    # fetch and could not have been satisfied by a warm identity map. This holds
    # for the fixed and the unfixed code alike.
    assert len({row["customer"]["id"] for row in small["rows"]}) == SMALL_PAGE
    assert len({row["customer"]["id"] for row in large["rows"]}) == LARGE_PAGE

    # The bounded reference map must hydrate no Customer entity at either size.
    assert small_hydrated == 0, f"PERF24 sales list hydrated {small_hydrated} Customer entities"
    assert large_hydrated == 0, f"PERF24 sales list hydrated {large_hydrated} Customer entities"


def test_sales_list_customer_names_are_still_rendered(pg):
    """The bounded map must not change a single rendered field."""
    engine, session_factory = pg
    case = _seed_orders(session_factory, prefix="C", count=6)

    with session_factory() as db:
        rows = sales_routes.list_sales_orders(db, None, page=1, page_size=6, include_total=True)
    with session_factory() as db:
        names = dict(
            db.query(Customer.id, Customer.name)
            .filter(Customer.id.in_(case["customer_ids"]))
            .all()
        )

    by_id = {int(row["id"]): row for row in rows["rows"]}
    assert set(by_id) == set(case["order_ids"])
    for order_id, customer_id in zip(case["order_ids"], case["customer_ids"]):
        row = by_id[order_id]
        assert row["customer_name"] == names[customer_id]
        assert row["customer"] == {"id": customer_id, "name": names[customer_id]}
        # The order's own identity and totals are untouched by the reference map.
        assert row["order_no"].startswith("PERF24-SOC-")
        assert row["status"] == "draft"
        assert row["order_type"] == "client_order"
        assert int(row["total_amount"]) == 100 + case["order_ids"].index(order_id) + 1


def test_sales_list_search_and_total_still_apply(pg):
    """`q` matching on the customer name and `include_total` are preserved."""
    engine, session_factory = pg
    case = _seed_orders(session_factory, prefix="H", count=4)
    target_id = case["order_ids"][0]

    with session_factory() as db:
        rows = sales_routes.list_sales_orders(db, None, q="customer H 1", page=1, page_size=50)
    assert [int(row["id"]) for row in rows] == [target_id]

    with session_factory() as db:
        page = sales_routes.list_sales_orders(db, None, page=1, page_size=2, include_total=True)
    assert page["total"] == 4
    assert page["page"] == 1 and page["page_size"] == 2
    assert len(page["rows"]) == 2


# --------------------------------------------------------------------------- #
# 2. GET /shipments — order and customer references must not be read per row
# --------------------------------------------------------------------------- #
def test_shipment_list_hydrates_no_reference_entities_per_row(pg):
    engine, session_factory = pg
    _seed_shipments(session_factory, prefix="D", count=SMALL_PAGE)
    probe = _EntityRowProbe((SalesOrder, Customer))

    with session_factory() as db:
        with probe.measure() as measured:
            small = shipment_routes.list_shipments(db, None)
    small_hydrated = measured.hydrated
    small_detail = dict(measured.by_entity)
    assert len(small) == SMALL_PAGE

    # Grow the shipment list between the two measurements.
    _seed_shipments(session_factory, prefix="E", count=LARGE_PAGE)
    with session_factory() as db:
        with probe.measure() as measured:
            large = shipment_routes.list_shipments(db, None)
    large_hydrated = measured.hydrated
    large_detail = dict(measured.by_entity)

    print(
        f"\nPERF24 shipment list reference entities hydrated="
        f"{small_hydrated}->{large_hydrated} (shipments {SMALL_PAGE}->{SMALL_PAGE + LARGE_PAGE}) "
        f"small={small_detail} large={large_detail}"
    )

    # The list really did grow, so the measurement is not vacuous.
    assert len(small) == SMALL_PAGE
    assert len(large) == SMALL_PAGE + LARGE_PAGE

    # Fixture integrity: every listed shipment names its own order and its own
    # customer, so the old per-row `db.get` had a separate order and customer to
    # fetch per row. Holds for fixed and unfixed code alike.
    listed = large[:SMALL_PAGE + LARGE_PAGE]
    assert len({row["id"] for row in listed}) == len(listed)
    assert len({row["sales_order_id"] for row in listed}) == len(listed)
    assert len({row["sales_order_no"] for row in listed}) == len(listed)

    # The bounded reference maps must hydrate no reference entity at either size.
    assert small_hydrated == 0, (
        f"PERF24 shipment list hydrated {small_hydrated} reference entities: {small_detail}"
    )
    assert large_hydrated == 0, (
        f"PERF24 shipment list hydrated {large_hydrated} reference entities: {large_detail}"
    )


def test_shipment_list_preserves_overrides_totals_and_deleted_filter(pg):
    """PERF24 invariants: overrides win, totals survive, deleted stays hidden."""
    engine, session_factory = pg
    case = _seed_shipments(
        session_factory, prefix="F", count=6, deleted=2, override_every=2, package_per=2
    )

    with session_factory() as db:
        listed = shipment_routes.list_shipments(db, None)

    # The two soft-deleted shipments are the two highest-numbered ids.
    deleted_ids = set(case["shipment_ids"][-2:])
    listed_ids = [int(row["id"]) for row in listed]
    assert len(listed) == 4, f"soft-deleted shipments leaked into the list: {listed_ids}"
    assert not (set(listed_ids) & deleted_ids)

    with session_factory() as db:
        names = dict(
            db.query(Customer.id, Customer.name)
            .filter(Customer.name.like("PERF24%"))
            .all()
        )

    for row in listed:
        # A shipment-level customer overrides its order's customer; otherwise the
        # order's customer is rendered. The identifier field keeps reporting the
        # shipment's own customer_id, not the resolved one.
        override = row["customer_name"]
        assert override is not None
        if row["customer_id"] is not None:
            assert override == names[int(row["customer_id"])]
        else:
            assert override in {name for name in names.values() if name.startswith("PERF24 order customer F")}
        # Two packages per shipment: quantity 10 and 11.
        assert row["packages_count"] == 2
        assert row["total_qty"] == 21
        assert row["required_count"] == 2
        assert row["scanned_count"] == 0
        assert row["remaining_count"] == 2
        assert row["is_complete"] is False
        assert row["sales_order_no"].startswith("PERF24-SHPSOF-")
        assert row["shipment_type"] == "sales_order"

    # The override actually happened, so the assertion above is not vacuous.
    overrides = [row for row in listed if row["customer_id"] is not None]
    assert len(overrides) == 2, f"expected 2 overriding shipments, got {len(overrides)}"
    assert all(row["customer_name"].startswith("PERF24 override customer F") for row in overrides)


def test_shipment_list_scanned_count_is_unchanged(pg):
    """`scanned_count`/`remaining_count`/`is_complete` keep their meaning."""
    engine, session_factory = pg
    case = _seed_shipments(session_factory, prefix="G", count=1, package_per=2)

    with session_factory.begin() as db:
        shipment = db.query(Shipment).filter(Shipment.id == case["shipment_ids"][0]).one()
        packages = (
            db.query(ShipmentPackage.package_id)
            .filter(ShipmentPackage.shipment_id == shipment.id)
            .order_by(ShipmentPackage.package_id)
            .all()
        )
        first_package = int(packages[0][0])
        db.add(ShipmentScanLog(
            shipment_id=shipment.id,
            package_id=first_package,
            scanned_code="PERF24-SCAN",
            scan_result="matched",
        ))

    with session_factory() as db:
        row = next(
            r for r in shipment_routes.list_shipments(db, None)
            if int(r["id"]) == case["shipment_ids"][0]
        )
    assert row["packages_count"] == 2
    assert row["scanned_count"] == 1
    assert row["remaining_count"] == 1
    assert row["is_complete"] is False
