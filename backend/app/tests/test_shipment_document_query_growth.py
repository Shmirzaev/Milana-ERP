"""PERF34: a shipment document must not rescan its package, price and receipt lists.

``shipment_document`` used to re-search the same small lists once per row:

* every package re-scanned all of ``contents`` to find its own items;
* every package item re-scanned all of ``order_items`` three times - once for
  candidates, once for exact matches and once for wildcard matches;
* every ``mixed`` item re-read its manual receipt;
* and ``post_manual_shipment_invoice`` re-scanned the whole frozen line list for
  every content group.

So a document cost O(packages x contents) + O(items x order lines) instead of
one pass each. This module pins the four indexes that replace them.

The honest metric here is *element inspections*, not statement counts: the number
of SQL statements was already constant while the work behind it grew quadratically.
``CountingList`` counts elements actually visited, and the data is grown *between*
the two measurements, so a bounded and an unbounded implementation cannot measure
the same thing.

What must not regress:

* exact price beats wildcard, wildcard is only consulted when no exact line
  matches, and a genuinely ambiguous price still yields ``None`` and marks the
  document ``pricing_complete=False``;
* an order line that is never selected is never coerced, so a model that is fully
  covered by exact matches behaves exactly as before;
* a frozen document still renders from its snapshot, byte for byte, after the live
  order prices change;
* package order, per-package line order, and the empty-package placeholder row.

The PostgreSQL cases need a real server, so they skip loudly when
STABILIZATION_POSTGRES_URL is unset.
"""

import os
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Query as SAQuery

from app.db import session as session_module
from app.db.base import Base
from app.models import (
    LegacyStockReceipt,
    ManualPackageReceipt,
    Model,
    Package,
    PackageItem,
    SalesOrder,
    SalesOrderItem,
    Shipment,
    ShipmentPackage,
    User,
)
from app.services.shipment_invoice import build_invoice_rows
from app.services.shipment_review import OrderPriceIndex, shipment_document

SMALL_PACKAGES = 3
LARGE_PACKAGES = 30
# A correctly indexed list is walked a small constant number of times: twice for
# the content list (model ids, then the package-content index) and twice for the
# price list (grouping, then the exact groups of the models actually present).
# The old code multiplied that by the package and item counts.
MAX_VISITS_PER_ROW = 3
VISIT_CONSTANT = 8


# --------------------------------------------------------------------------- #
# Inspection counting
# --------------------------------------------------------------------------- #
class CountingList(list):
    """A list that records how many of its elements were actually visited.

    Subclassing keeps every other list behaviour (``len``, indexing, ``in``), so
    the code under test is unchanged; only ``__iter__`` is instrumented.
    """

    def __init__(self, values=(), counter=None, key=None):
        super().__init__(values)
        self._counter = counter
        self._key = key

    def __iter__(self):
        for item in list.__iter__(self):
            if self._counter is not None:
                self._counter[self._key] += 1
            yield item


class InspectionProbe:
    """Count element visits inside ``shipment_document`` only.

    ``Query.all`` is the single point where the two loaded lists materialise, so
    patching it for the duration of the measured call is enough - and it leaves
    the production code untouched.
    """

    def __init__(self):
        self.inspections = {"contents": 0, "order_items": 0}
        self._original_all = SAQuery.all

    def __enter__(self):
        inspections = self.inspections
        original_all = self._original_all

        def counting_all(query):
            result = original_all(query)
            key = {PackageItem: "contents", SalesOrderItem: "order_items"}.get(
                query.column_descriptions[0].get("entity")
            )
            return CountingList(result, counter=inspections, key=key) if key else result

        SAQuery.all = counting_all
        return self

    def __exit__(self, *exc):
        SAQuery.all = self._original_all
        return False


def _inspections_for(shipment_id):
    with session_module.SessionLocal() as db:
        shipment = db.get(Shipment, shipment_id)
        with InspectionProbe() as probe:
            document = shipment_document(db, shipment)
        return probe.inspections, document


# --------------------------------------------------------------------------- #
# Pure pricing semantics - no database, so these can never pass by skipping
# --------------------------------------------------------------------------- #
def _original_prices(order_items, model_id, color, size):
    """The pre-PERF34 expression, verbatim, as the behavioural reference."""
    candidates = [line for line in order_items if line.model_id == model_id]
    exact = [line for line in candidates if line.color == color and line.size == size]
    wildcard = [line for line in candidates
                if (line.color.lower() in {"mixed", "any", "*", ""})
                and (line.size.lower() in {"any", "mixed", "*", "", "bag"}
                     or line.size.lower().startswith("pack"))]
    return {Decimal(str(line.unit_price)) for line in (exact or wildcard)}


def _line(model_id, color, size, price):
    return SimpleNamespace(model_id=model_id, color=color, size=size, unit_price=price)


# colour x size x price, for both wildcard and exact spellings.
PRICE_CASES = [
    ("navy", "M", 20),
    ("navy", "L", 21),
    ("red", "M", 22),
    ("mixed", "any", 10),
    ("any", "mixed", 11),
    ("*", "bag", 12),
    ("", "", 13),
    ("MIXED", "pack1", 14),
    ("mixed", "pack-12", 15),
]
QUERIES = [("navy", "M"), ("navy", "L"), ("red", "M"), ("black", "XL"), ("", ""), ("mixed", "any")]


@pytest.mark.parametrize("model_id", [7])
def test_order_price_index_matches_the_original_expression_on_every_combination(model_id):
    """Differential check: index output == the expression it replaced."""
    for lines in ([], [_line(model_id, c, s, p) for c, s, p in PRICE_CASES],
                  [_line(model_id, c, s, p) for c, s, p in PRICE_CASES] * 3):
        index = OrderPriceIndex(lines)
        for color, size in QUERIES:
            assert index.prices(model_id, color, size) == _original_prices(lines, model_id, color, size), (
                f"color={color!r} size={size!r} lines={lines}"
            )


def test_order_price_index_separates_models():
    index = OrderPriceIndex([
        _line(1, "navy", "M", 20), _line(1, "mixed", "any", 10),
        _line(2, "navy", "M", 99), _line(2, "*", "bag", 98),
    ])
    assert index.prices(1, "navy", "M") == {Decimal("20")}
    assert index.prices(1, "black", "XL") == {Decimal("10")}
    assert index.prices(2, "navy", "M") == {Decimal("99")}
    assert index.prices(2, "black", "XL") == {Decimal("98")}
    assert index.prices(3, "navy", "M") == set()


def test_exact_beats_wildcard_even_when_wildcard_is_unambiguous():
    index = OrderPriceIndex([_line(1, "navy", "M", 20), _line(1, "mixed", "any", 10)])
    assert index.prices(1, "navy", "M") == {Decimal("20")}


def test_ambiguous_exact_price_is_reported_as_ambiguous_not_picked():
    index = OrderPriceIndex([_line(1, "navy", "M", 20), _line(1, "navy", "M", 21)])
    assert index.prices(1, "navy", "M") == {Decimal("20"), Decimal("21")}


def test_duplicate_order_lines_with_one_price_are_not_ambiguous():
    index = OrderPriceIndex([_line(1, "navy", "M", 20), _line(1, "navy", "M", 20)])
    assert index.prices(1, "navy", "M") == {Decimal("20")}


def test_unselected_order_lines_are_never_coerced():
    """A line the lookup never selects must not be touched at all.

    The eager alternative raised ``InvalidOperation`` here, because it coerced
    every order line up front instead of only the selected candidates.
    """
    lines = [
        _line(1, "navy", "M", 20),          # exact, selected
        _line(1, "red", "L", None),         # not selected for ("navy", "M")
    ]
    assert OrderPriceIndex(lines).prices(1, "navy", "M") == _original_prices(lines, 1, "navy", "M")
    with pytest.raises(Exception):
        _original_prices(lines, 1, "red", "L")  # documents the uncoercible value


def test_wildcard_derivation_is_lazy_per_model():
    """A model with a ``None`` colour must not break another model's document.

    Only the queried model reaches the wildcard predicate, exactly as when the
    two comprehensions were written inline.
    """
    broken = _line(2, None, "any", 5)      # wildcard predicate would raise here
    exact_only = _line(1, "navy", "M", 20)  # this model never needs a wildcard
    lines = [broken, exact_only]
    index = OrderPriceIndex(lines)
    assert index.prices(1, "navy", "M") == {Decimal("20")}
    # Asking model 2 for a non-exact colour does reach the wildcard, as before.
    with pytest.raises(AttributeError):
        index.prices(2, "black", "XL")
    with pytest.raises(AttributeError):
        _original_prices(lines, 2, "black", "XL")


# --------------------------------------------------------------------------- #
# build_invoice_rows: package-content index
# --------------------------------------------------------------------------- #
def _invoice_lines(count, packages):
    return CountingList([
        {
            "package_no": packages[index % len(packages)], "model_code": f"M-{index % 3}",
            "quantity": 1 + index % 4, "size": "L", "color": "red",
            "unit_price": "3.00", "amount": f"{3 * (1 + index % 4):.2f}",
        }
        for index in range(count)
    ], counter={"lines": 0}, key="lines")


def test_invoice_rows_visit_every_line_once_regardless_of_package_count():
    packages = [f"P{index}" for index in range(LARGE_PACKAGES)]
    lines = _invoice_lines(LARGE_PACKAGES * 3, packages)
    counters = lines._counter
    rows = build_invoice_rows(lines, [{"package_no": name, "quantity": 3, "weight_kg": "1.0"} for name in packages])

    assert len(rows) > 0
    # One pass to index, and the per-package lookups never re-walk the list.
    assert counters["lines"] <= len(lines) + VISIT_CONSTANT, (
        f"invoice rows visited {counters['lines']} of {len(lines)} lines for "
        f"{len(packages)} packages - the content index is not in use"
    )


def test_invoice_rows_preserve_package_order_line_order_and_the_empty_placeholder():
    lines = [
        {"package_no": "P2", "model_code": "M-2", "quantity": 2, "size": "L", "color": "red",
         "unit_price": "3", "amount": "6"},
        {"package_no": "P1", "model_code": "M-1", "quantity": 1, "size": "S", "color": "navy",
         "unit_price": "2", "amount": "2"},
        {"package_no": "P1", "model_code": "M-1", "quantity": 3, "size": "M", "color": "navy",
         "unit_price": "2", "amount": "6"},
    ]
    packages = [
        {"package_no": "P1", "quantity": 4, "weight_kg": "1.5"},
        {"package_no": "EMPTY", "quantity": 7, "weight_kg": None},
        {"package_no": "P2", "quantity": 2, "weight_kg": "2.0"},
    ]
    rows = build_invoice_rows(lines, packages)

    assert [row["package_no"] for row in rows] == ["P1", "EMPTY", "P2"]
    assert [(row["quantity"], row["amount"]) for row in rows] == [(4, "8.00"), (7, None), (2, "6.00")]
    assert [item["size"] for item in rows[0]["sizes"]] == ["S", "M"]
    assert [row["package_rowspan"] for row in rows] == [1, 1, 1]
    # A line for a package nobody asked about must not leak into the output.
    assert all(row["package_no"] != "P2" or row["quantity"] == 2 for row in rows)


# --------------------------------------------------------------------------- #
# shipment_document growth on real rows
# --------------------------------------------------------------------------- #
def _first_user_id(db):
    user_id = db.query(User.id).order_by(User.id).first()
    if user_id is None:
        user = User(name="PERF34", email=f"perf34-{uuid4().hex}@example.invalid",
                    password_hash="unused", factory_code="MIL", extra_permissions=[], is_active=True)
        db.add(user)
        db.flush()
        return user.id
    return user_id[0]


def _add_manual_packages(db, shipment, model, count, marker, start=0):
    user_id = _first_user_id(db)
    for number in range(start, start + count):
        receipt = ManualPackageReceipt(
            receipt_no=f"PERF34-R-{marker}-{number}", created_by=user_id,
            evidence={"configured_sizes": ["S", "M", "S"]}, evidence_hash="a" * 64,
        )
        db.add(receipt)
        db.flush()
        package = Package(
            package_no=f"PERF34-P-{marker}-{number}", barcode=f"PERF34-B-{marker}-{number}",
            model_id=model.id, color="navy", total_quantity=1, capacity=1,
            manual_receipt_id=receipt.id, status="received_in_storage",
        )
        db.add(package)
        db.flush()
        db.add_all([
            PackageItem(package_id=package.id, model_id=model.id, color="navy",
                        size="mixed", quantity=1),
            ShipmentPackage(shipment_id=shipment.id, package_id=package.id, quantity=1),
        ])
    db.flush()


def _seed_manual_shipment(package_count, marker):
    """Create a manual shipment with ``package_count`` packages, committed."""
    with session_module.SessionLocal.begin() as db:
        model = Model(code=f"PERF34-{marker}", name="PERF34 manual", status="approved", selling_price=2.5)
        shipment = Shipment(shipment_no=f"PERF34-SH-{marker}", status="created",
                            dispatch_snapshot={"manual": True})
        db.add_all([model, shipment])
        db.flush()
        _add_manual_packages(db, shipment, model, package_count, marker)
        return shipment.id, model.id


# Order lines priced for the growth shipment: one wildcard that prices every
# item, plus exact lines for other colour/size pairs of the same model.
GROWTH_ORDER_LINES = [
    ("mixed", "any"), ("any", "mixed"), ("*", "bag"), ("", ""),
    ("navy", "M"), ("navy", "L"), ("red", "M"), ("black", "XL"),
]


def _seed_growth_shipment(package_count, marker):
    """A priced shipment with ``package_count`` packages and 8 order lines.

    The order lines are deliberately a fixed, non-trivial list: the defect was
    ``items x order lines``, so the bound that matters is how often the price
    list is visited, not how that count scales with the item count.
    """
    with session_module.SessionLocal.begin() as db:
        model = Model(code=f"PERF34-G-{marker}", name="PERF34 growth", status="approved")
        order = SalesOrder(order_no=f"PERF34-GO-{marker}", status="reserved", total_amount=0)
        shipment = Shipment(shipment_no=f"PERF34-GSH-{marker}", status="created",
                            dispatch_snapshot={"manual": True})
        db.add_all([model, order, shipment])
        db.flush()
        shipment.sales_order_id = order.id
        db.add_all([
            SalesOrderItem(sales_order_id=order.id, model_id=model.id, color=color, size=size,
                           quantity=1, unit_price=Decimal("7.00"))
            for color, size in GROWTH_ORDER_LINES
        ])
        db.flush()
        _add_manual_packages(db, shipment, model, package_count, marker)
        return shipment.id, model.id, len(GROWTH_ORDER_LINES)


def test_document_lookups_visit_each_row_only_a_few_times():
    """Grow the shipment between the two measurements, then bound the work.

    Correct indexing visits the content list about twice and the price list about
    twice, whatever the package count. The old code visited contents once per
    package and order lines once per package item, so a 10x larger document cost
    ~100x the work. Measuring visits per row separates the two without depending
    on a statement count that was already constant.
    """
    marker = uuid4().hex[:8]
    shipment_id, model_id, order_line_count = _seed_growth_shipment(SMALL_PACKAGES, marker)

    small, small_document = _inspections_for(shipment_id)
    assert small_document["packages_count"] == SMALL_PACKAGES
    assert len(small_document["lines"]) == SMALL_PACKAGES

    # Grow the same shipment; the second measurement has real extra data behind it.
    with session_module.SessionLocal.begin() as db:
        shipment = db.get(Shipment, shipment_id)
        model = db.get(Model, model_id)
        _add_manual_packages(db, shipment, model, LARGE_PACKAGES - SMALL_PACKAGES, marker,
                             start=SMALL_PACKAGES)

    large, large_document = _inspections_for(shipment_id)
    assert large_document["packages_count"] == LARGE_PACKAGES
    assert len(large_document["lines"]) == LARGE_PACKAGES

    # The seeded order prices every item through the wildcard line, so the price
    # index is genuinely exercised rather than short-circuited by an exact hit.
    assert {line["unit_price"] for line in large_document["lines"]} == {"7.00"}

    print(
        f"\nPERF34 document inspections: small({SMALL_PACKAGES} pkgs)"
        f" contents={small['contents']} order_items={small['order_items']}"
        f" | large({LARGE_PACKAGES} pkgs)"
        f" contents={large['contents']} order_items={large['order_items']}"
    )
    assert small["order_items"] > 0, "the price list must be loaded to be measured"

    # Per-row visit bounds. contents is walked once for the model ids and once
    # for the content index; order lines are walked once to group and once to
    # build the exact groups of the single model present.
    item_count = LARGE_PACKAGES  # one PackageItem per package in this seed
    assert large["contents"] <= item_count * MAX_VISITS_PER_ROW + VISIT_CONSTANT, (
        f"contents visited {large['contents']} times over {item_count} rows "
        f"({large['contents'] / item_count:.1f} per row) - the package-content "
        f"index is not in use"
    )
    assert large["order_items"] <= order_line_count * MAX_VISITS_PER_ROW + VISIT_CONSTANT, (
        f"order lines visited {large['order_items']} times over {order_line_count} rows "
        f"({large['order_items'] / order_line_count:.1f} per row) - the exact/wildcard "
        f"price index is not in use"
    )


def test_manual_document_still_reports_configured_sizes_once_per_receipt():
    marker = uuid4().hex[:8]
    shipment_id, _model_id = _seed_manual_shipment(3, marker)
    _inspections, document = _inspections_for(shipment_id)

    assert len(document["lines"]) == 3
    assert {line["size_display"] for line in document["lines"]} == {"S, M"}
    assert document["pricing_complete"] is True
    assert document["amount"] == "7.50"  # 3 x 1 piece x 2.50 model selling price


# --------------------------------------------------------------------------- #
# Ambiguity, precedence and the frozen snapshot
# --------------------------------------------------------------------------- #
def _seed_priced_shipment(marker):
    with session_module.SessionLocal.begin() as db:
        exact_model = Model(code=f"PERF34-EXACT-{marker}", name="Exact", status="approved")
        ambiguous_model = Model(code=f"PERF34-AMB-{marker}", name="Ambiguous", status="approved")
        order = SalesOrder(order_no=f"PERF34-ORDER-{marker}", status="reserved", total_amount=0)
        db.add_all([exact_model, ambiguous_model, order])
        db.flush()
        db.add_all([
            # Wildcard priced 10, exact priced 20 -> exact must win.
            SalesOrderItem(sales_order_id=order.id, model_id=exact_model.id, color="mixed",
                           size="any", quantity=2, unit_price=10),
            SalesOrderItem(sales_order_id=order.id, model_id=exact_model.id, color="navy",
                           size="M", quantity=1, unit_price=20),
            # Same model, same colour/size, two prices -> ambiguous.
            SalesOrderItem(sales_order_id=order.id, model_id=ambiguous_model.id, color="mixed",
                           size="any", quantity=1, unit_price=5),
            SalesOrderItem(sales_order_id=order.id, model_id=ambiguous_model.id, color="*",
                           size="bag", quantity=1, unit_price=6),
        ])
        shipment = Shipment(shipment_no=f"PERF34-ORDERSH-{marker}", sales_order_id=order.id,
                            status="created")
        db.add(shipment)
        db.flush()
        variants = [
            (exact_model, "navy", "M", f"PERF34-P-EX-{marker}"),
            (exact_model, "red", "L", f"PERF34-P-WILD-{marker}"),
            (ambiguous_model, "black", "XL", f"PERF34-P-AMB-{marker}"),
        ]
        for number, (model, color, size, package_no) in enumerate(variants):
            receipt = LegacyStockReceipt(
                source_system="TEST", source_warehouse_id=f"PERF34-{marker}",
                source_record_id=str(number), source_checksum=str(number + 1) * 64,
                source_payload={"quantity": 1},
            )
            db.add(receipt)
            db.flush()
            package = Package(
                package_no=package_no, barcode=f"{package_no}-B", model_id=model.id,
                color=color, total_quantity=1, capacity=1, legacy_receipt_id=receipt.id,
                status="reserved",
            )
            db.add(package)
            db.flush()
            db.add_all([
                PackageItem(package_id=package.id, model_id=model.id, color=color,
                            size=size, quantity=1),
                ShipmentPackage(shipment_id=shipment.id, package_id=package.id, quantity=1),
            ])
        db.flush()
        return shipment.id


def test_exact_wildcard_precedence_ambiguity_and_order_are_preserved():
    marker = uuid4().hex[:8]
    shipment_id = _seed_priced_shipment(marker)
    with session_module.SessionLocal() as db:
        document = shipment_document(db, db.get(Shipment, shipment_id))

    assert [line["package_no"] for line in document["lines"]] == [
        f"PERF34-P-EX-{marker}", f"PERF34-P-WILD-{marker}", f"PERF34-P-AMB-{marker}",
    ]
    # exact 20 beats wildcard 10; wildcard 10 resolves the unmatched colour/size;
    # the ambiguous model stays unpriced and is reported, not guessed.
    assert [line["unit_price"] for line in document["lines"]] == ["20.00", "10.00", None]
    assert [line["amount"] for line in document["lines"]] == ["20.00", "10.00", None]
    assert document["pricing_complete"] is False
    assert document["amount"] is None
    assert document["basis"]


def test_frozen_document_is_never_rebuilt_from_live_rows():
    """Freeze, then change every live price and the shipment's contents."""
    marker = uuid4().hex[:8]
    shipment_id = _seed_priced_shipment(marker)
    with session_module.SessionLocal.begin() as db:
        shipment = db.get(Shipment, shipment_id)
        frozen = shipment_document(db, shipment)
        shipment.status = "shipped"
        shipment.dispatch_snapshot = {"document": frozen}
        db.query(SalesOrderItem).filter_by(sales_order_id=shipment.sales_order_id).update(
            {"unit_price": 999})
        db.query(PackageItem).filter(PackageItem.model_id.isnot(None)).update({"quantity": 7})

    with session_module.SessionLocal() as db:
        assert shipment_document(db, db.get(Shipment, shipment_id)) == frozen


# --------------------------------------------------------------------------- #
# The migration declares exactly the ORM's two indexes (no database needed)
# --------------------------------------------------------------------------- #
def _load_migration_module():
    import importlib.util

    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "alembic", "versions", "0137_perf34_shipment_indexes.py",
    )
    spec = importlib.util.spec_from_file_location("perf34_migration_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_creates_exactly_the_two_orm_indexes():
    """Record the migration's create_index calls; never touch a database.

    ``test_sales_orm_matches_migrations`` already fails if a migrated index is
    missing from the ORM; this is the mirror check, so the ORM cannot grow an
    index the migration never creates either.
    """
    import app.models  # noqa: F401 - register ORM metadata
    from alembic import op as alembic_op

    created: list = []
    original = alembic_op.create_index
    alembic_op.create_index = lambda name, table, columns, *a, **k: created.append(
        (name, table, tuple(columns))
    )
    try:
        _load_migration_module().upgrade()
    finally:
        alembic_op.create_index = original

    expected = {
        (index.name, table.name, tuple(column.name for column in index.columns))
        for table in Base.metadata.tables.values()
        for index in table.indexes
        if index.name in {"ix_package_items_package_id", "ix_sales_order_items_sales_order_id"}
    }
    assert set(created) == expected, (
        "migration and ORM disagree on the PERF34 indexes: "
        f"migration={sorted(created)} orm={sorted(expected)}"
    )


def test_migration_is_based_on_the_real_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    backend = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    scripts = ScriptDirectory.from_config(Config(os.path.join(backend, "alembic.ini")))
    module = _load_migration_module()
    revisions = {rev.revision for rev in scripts.walk_revisions()}
    assert module.revision in revisions
    assert module.down_revision in revisions
    assert module.down_revision == "0136_employee_salary_precision"
    heads = scripts.get_heads()
    assert len(heads) == 1, f"migration chain forks: {heads}"
    ancestry = {rev.revision for rev in scripts.iterate_revisions(heads[0], "base")}
    assert module.revision in ancestry, "PERF34 must remain in the current head's ancestry"
    # alembic_version.version_num is varchar(32); a longer id fails only at
    # upgrade time, on a real server.
    assert len(module.revision) <= 32, f"revision id too long: {module.revision!r}"


# --------------------------------------------------------------------------- #
# PostgreSQL: the planner must actually choose each index
# --------------------------------------------------------------------------- #
DOCUMENT_QUERIES = {
    "package_items": "SELECT id, package_id, model_id, color, size, quantity "
                     "FROM package_items WHERE package_id = ANY(:ids) ORDER BY id",
    "sales_order_items": "SELECT id, sales_order_id, model_id, color, size, quantity, unit_price "
                         "FROM sales_order_items WHERE sales_order_id = :order_id",
}

# A production-shaped data set: 40k packages and 240k content rows, so a document
# query touching 40 packages is a genuine slice rather than most of the table.
SEED_STATEMENTS = (
    "INSERT INTO models (id, code, name, status, sam_minutes) "
    "SELECT g, 'PERF34-M-' || g, 'm', 'approved', 0 FROM generate_series(1, 40) g",
    "INSERT INTO production_orders (id, production_no, production_type, model_id, status, "
    "planned_quantity, created_at) "
    "SELECT g, 'PERF34-PR-' || g, 'standard', ((g % 40) + 1), 'new', 0, now() "
    "FROM generate_series(1, 5) g",
    "INSERT INTO sales_orders (id, order_no, order_type, status, total_amount, created_at) "
    "SELECT g, 'PERF34-O-' || g, 'client_order', 'reserved', 0, now() "
    "FROM generate_series(1, 60) g",
    "INSERT INTO packages (id, package_no, barcode, packaging_department_code, stock_kind, "
    "model_id, color, package_type, total_quantity, quantity_shortfall, capacity, status, "
    "production_order_id, created_at) "
    "SELECT g, 'PERF34-P-' || g, 'PERF34-B-' || g, 'PKG', 'standard', "
    "((g % 40) + 1), 'navy', 'bag', 6, 0, 6, 'reserved', ((g % 5) + 1), now() "
    "FROM generate_series(1, 40000) g",
    "INSERT INTO package_items (id, package_id, model_id, color, size, quantity, created_at) "
    "SELECT g, ((g - 1) / 6) + 1, ((g % 40) + 1), 'navy', 'M', 1, now() "
    "FROM generate_series(1, 240000) g",
    # 60 orders x 50 lines = 3000 rows: the queried order is a small slice.
    "INSERT INTO sales_order_items (id, sales_order_id, model_id, color, size, quantity, "
    "unit_price, printing_required, source_type, created_at) "
    "SELECT g, ((g - 1) / 50) + 1, ((g % 40) + 1), 'navy', 'M', 1, 5.00, false, "
    "'produce_new', now() FROM generate_series(1, 3000) g",
)


@pytest.fixture(scope="module")
def perf34_postgres():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL for the real PostgreSQL index-plan coverage")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("PERF34 PostgreSQL coverage requires a loopback PostgreSQL URL without connection overrides")
    schema = f"perf34_{uuid4().hex}"
    engine = create_engine(
        url,
        connect_args={"options": f"-csearch_path={schema} -cstatement_timeout=25000"},
        pool_size=4, max_overflow=0, isolation_level="READ COMMITTED",
    )
    assert engine.dialect.name == "postgresql"
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        # Built from ORM metadata on a disposable schema. No migration is executed
        # anywhere, and no production or shared database is touched.
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            # sa.text, not exec_driver_sql: the driver-level path mis-handles the
            # "%" modulo operator under pyformat and raises "immutabledict is not
            # a sequence" on this SQLAlchemy/psycopg2 pair.
            for statement in SEED_STATEMENTS:
                connection.execute(sa.text(statement))
            connection.execute(sa.text("ANALYZE"))
        yield engine
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def _plan_rows_examined(engine, sql, params):
    with engine.connect() as connection:
        rows = connection.execute(
            sa.text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql), params
        ).scalar()
    return rows[0]["Plan"]


def _scan_nodes(node):
    yield node
    for child in node.get("Plans", ()):
        yield from _scan_nodes(child)


def _uses_index(plan, index_name):
    return any(
        node.get("Node Type") in {"Index Scan", "Index Only Scan", "Bitmap Index Scan"}
        and index_name in node.get("Index Name", "")
        for node in _scan_nodes(plan)
    )


@pytest.mark.parametrize(
    "table,index_name,params",
    [
        ("package_items", "ix_package_items_package_id",
         {"ids": list(range(1, 41))}),
        ("sales_order_items", "ix_sales_order_items_sales_order_id",
         {"order_id": 7}),
    ],
)
def test_postgres_planner_chooses_the_document_index(perf34_postgres, table, index_name, params):
    """Plan-level evidence: the index is used and the scan stays narrow.

    Rows are grown between the two measurements - the fixture holds 240k content
    rows and 3k order lines while each query touches 40 packages or one order -
    so a plan that degrades to a sequential scan is visible here.
    """
    sql = DOCUMENT_QUERIES[table]
    with perf34_postgres.connect() as connection:
        total_rows = connection.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar()
    assert total_rows > 2000, "the table must be realistically sized for the plan to mean anything"

    plan = _plan_rows_examined(perf34_postgres, sql, params)
    assert _uses_index(plan, index_name), (
        f"{table}: planner did not choose {index_name}: "
        f"{[node.get('Node Type') for node in _scan_nodes(plan)]}"
    )
    index_scan_rows = next(
        node["Actual Rows"] for node in _scan_nodes(plan)
        if index_name in node.get("Index Name", "")
    )
    print(
        f"\nPERF34 {table}: {total_rows} rows, plan="
        f"{[node.get('Node Type') for node in _scan_nodes(plan)]}, "
        f"index rows={index_scan_rows}"
    )
    assert index_scan_rows < total_rows / 10, (
        f"{table}: index scan read {index_scan_rows} of {total_rows} rows"
    )

    # Dropping the index must change the plan, which is what makes the index
    # necessary rather than decorative. The schema is disposable, so this is safe.
    with perf34_postgres.begin() as connection:
        connection.exec_driver_sql(f"DROP INDEX {index_name}")
    try:
        without = _plan_rows_examined(perf34_postgres, sql, params)
        assert not _uses_index(without, index_name)
        assert any(node.get("Node Type") == "Seq Scan" for node in _scan_nodes(without)), (
            f"{table}: expected a sequential scan without {index_name}, got "
            f"{[node.get('Node Type') for node in _scan_nodes(without)]}"
        )
    finally:
        with perf34_postgres.begin() as connection:
            connection.exec_driver_sql(
                f"CREATE INDEX {index_name} ON {table} "
                f"({'package_id' if table == 'package_items' else 'sales_order_id'})"
            )


def test_postgres_coverage_is_not_silently_green(perf34_postgres):
    with perf34_postgres.connect() as connection:
        assert connection.execute(sa.text("SELECT version()")).scalar().startswith("PostgreSQL")
        assert connection.exec_driver_sql("SELECT current_schema()").scalar() != "public"
