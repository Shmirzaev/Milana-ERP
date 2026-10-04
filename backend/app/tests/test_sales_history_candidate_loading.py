"""PERF25: sales history hydrated and sorted the whole candidate set before paging.

`GET /sales-orders/history` merges sales orders and Planning-created stock
production orders. The endpoint built that candidate set in SQL but then
`.all()`-ed every branch as full ORM entities, sorted the two lists in Python
and only afterwards cut the requested page. Every caller therefore paid for
hydrating — and for `joinedload`ing the production children of — the entire
history, no matter how small the page was.

The fix counts, orders and pages the candidate set in SQL and hydrates only the
selected ids. That makes the SQL ordering load-bearing: it has to reproduce the
old Python sort exactly, including

* ties on the `(created_at, id)` key, which the old `list.sort(reverse=True)`
  resolved by *stability* (a sales row preceded a production row when both the
  timestamp and the numeric id were identical, because the sales list was built
  first), and
* NULL `created_at`, which the old key mapped to `""` and therefore sorted
  **last** under `reverse=True` — PostgreSQL would have needed
  `NULLS FIRST` for an ascending sort, and `NULLS LAST` for this descending one.

So the test keeps the pre-fix algorithm as an oracle, and additionally pins a
hand-derived expected order so a faithful-but-wrong reference cannot hide a
wrong SQL ordering.

PostgreSQL only, because SQLite has neither `timestamptz` union typing nor
PostgreSQL's NULL ordering defaults. Set STABILIZATION_POSTGRES_URL to run it.
"""

import os
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, or_, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import joinedload, sessionmaker
from sqlalchemy import inspect as sa_inspect

from app.api.routes import sales as sales_routes
from app.core.dt import date_filter_bounds
from app.core.model_search import normalized_model_code_column, normalized_model_code_pattern
from app.core.order_reference import order_reference_contains
from app.db.base import Base
from app.models import (
    BrandedPlanningOrder,
    Customer,
    Model,
    ProductionOrder,
    SalesOrder,
    SalesOrderItem,
)
import app.models  # noqa: F401  (register every table in Base.metadata)

# One fixed instant so the whole fixture is reproducible.
BASE_TS = datetime(2024, 5, 1, 10, 0, tzinfo=timezone.utc)

# (offset from BASE_TS, sales status, sales order_type, production status)
# Offset None means the row's created_at is forced to SQL NULL. Sales and
# production statuses match so the status filter selects both branches.
ROWS = [
    # index: 0    1              2                3
    (5, "draft", "client_order", "draft"),
    (4, "confirmed", "client_order", "confirmed"),
    (3, "draft", "branded_stock_sale", "draft"),
    (3, "confirmed", "branded_stock_sale", "confirmed"),
    (1, "draft", "client_order", "draft"),
    (None, "confirmed", "branded_stock_sale", "confirmed"),
]

SALES_BASE = "PERF25-SO"
PROD_BASE = "PERF25-PO"
GROUP_NO = "PERF25-GROUP"


# --------------------------------------------------------------------------- #
# PostgreSQL fixture
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def sales_history_postgres_sessions():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip(
            "Set STABILIZATION_POSTGRES_URL for real PostgreSQL sales-history paging coverage"
        )
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Sales-history paging tests require a loopback PostgreSQL URL without connection overrides")
    schema = f"sales_history_candidates_{uuid4().hex}"
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    assert engine.dialect.name == "postgresql"
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        Base.metadata.create_all(engine)
        # `created_at` is NOT NULL in production, but the old Python sort carried
        # a defensive `if entry[0] else ""` null branch, so the ordering of a
        # null sort key has to be pinned. Relax the constraint in this
        # throwaway schema only.
        with engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE sales_orders ALTER COLUMN created_at DROP NOT NULL")
            connection.exec_driver_sql("ALTER TABLE production_orders ALTER COLUMN created_at DROP NOT NULL")
        yield engine, sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    finally:
        engine.dispose()
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')


def _seed(session_factory, rows=ROWS, prefix=""):
    """Create `rows` interleaved sales/production candidates.

    Sales and production rows are inserted in lockstep so their numeric ids
    line up, which is what makes the cross-kind tie case reachable: a sales
    order and a stock production order with the same created_at *and* the same
    id. The old stable sort put the sales row first; SQL has to be told.
    """
    with session_factory.begin() as db:
        customer = Customer(name=f"PERF25 customer{prefix}")
        other_customer = Customer(name=f"PERF25 other customer{prefix}")
        model = Model(code=f"PERF25-MODEL{prefix}", name=f"PERF25 model{prefix}", status="approved")
        group = BrandedPlanningOrder(
            order_no=f"{GROUP_NO}{prefix}", ordered_for_type="milana", ordered_for_name="Milana",
        )
        db.add_all([customer, other_customer, model, group])
        db.flush()

        sales_ids, production_ids = [], []
        for index, (offset, sales_status, order_type, prod_status) in enumerate(rows, start=1):
            so = SalesOrder(
                order_no=f"{SALES_BASE}{prefix}-{index}",
                status=sales_status,
                order_type=order_type,
                customer_id=customer.id,
                total_amount=100 + index,
            )
            po = ProductionOrder(
                production_no=f"{PROD_BASE}{prefix}-{index}",
                production_type="branded_stock",
                model_id=model.id,
                status=prod_status,
                planned_quantity=10 + index,
                planning_order_id=group.id,
            )
            db.add_all([so, po])
            db.flush()
            created_at = None if offset is None else BASE_TS + timedelta(minutes=offset)
            db.execute(
                text("UPDATE sales_orders SET created_at = :ts WHERE id = :id"),
                {"ts": created_at, "id": so.id},
            )
            db.execute(
                text("UPDATE production_orders SET created_at = :ts WHERE id = :id"),
                {"ts": created_at, "id": po.id},
            )
            sales_ids.append(int(so.id))
            production_ids.append(int(po.id))

        # One item so the sales branch has a child row and the history payload
        # is not trivially empty.
        db.add(SalesOrderItem(
            sales_order_id=sales_ids[0], model_id=model.id, quantity=5,
            size="M", color="white",
        ))
        return {
            "customer_id": int(customer.id),
            "other_customer_id": int(other_customer.id),
            "model_id": int(model.id),
            "group_no": GROUP_NO,
            "sales_ids": sales_ids,
            "production_ids": production_ids,
        }


@pytest.fixture()
def pg(sales_history_postgres_sessions):
    engine, session_factory = sales_history_postgres_sessions
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "TRUNCATE sales_orders, production_orders, customers, models, "
            "branded_planning_orders RESTART IDENTITY CASCADE"
        )
    return engine, session_factory


@pytest.fixture()
def seeded(pg):
    engine, session_factory = pg
    return engine, session_factory, _seed(session_factory)


# --------------------------------------------------------------------------- #
# Hydration measurement
# --------------------------------------------------------------------------- #
class _HydrationProbe:
    """Rows actually pulled by statements that materialise the two entities.

    A statement counts as hydration when its compiled `Select` reports
    `SalesOrder` or `ProductionOrder` in `column_descriptions`, i.e. when the
    ORM built entity instances for it. The candidate-key statements report plain
    columns and are deliberately excluded, so the number measures entity rows,
    not statements, and not result rows that were never turned into objects.
    """

    def __init__(self, engine):
        self.engine = engine
        self.entity_rows = 0
        self.entity_statements = 0
        self.all_statements = 0

    def _hook(self, conn, cursor, statement, parameters, context, executemany):
        self.all_statements += 1
        compiled = getattr(context, "compiled", None)
        element = getattr(compiled, "statement", None)
        descriptions = getattr(element, "column_descriptions", None) or []
        if not any(row.get("entity") in (SalesOrder, ProductionOrder) for row in descriptions):
            return
        self.entity_statements += 1
        self.entity_rows += max(0, cursor.rowcount or 0)

    @contextmanager
    def measure(self):
        event.listen(self.engine, "after_cursor_execute", self._hook)
        # Counters describe this measurement only, never an earlier one.
        self.entity_rows = 0
        self.entity_statements = 0
        self.all_statements = 0
        try:
            yield self
        finally:
            event.remove(self.engine, "after_cursor_execute", self._hook)


def _call(session, *, page=1, page_size=50, include_total=True, **filters):
    return sales_routes.list_sales_order_history(
        session, None, page=page, page_size=page_size, include_total=include_total, **filters
    )


def _keys(payload):
    return [(row["record_type"], int(row["id"])) for row in payload]


def _sales_key(index):
    return ("sales_order", index)


def _production_key(index):
    return ("production_order", index)


# --------------------------------------------------------------------------- #
# The pre-fix algorithm, kept as the ordering oracle
# --------------------------------------------------------------------------- #
def _reference_page(db, *, page=1, page_size=50, status=None, order_type=None,
                    customer_id=None, q=None, created_from=None, created_to=None):
    """`list_sales_order_history` exactly as it read before PERF25.

    Every candidate is loaded, the two lists are concatenated with the sales
    branch first, and one stable `list.sort(..., reverse=True)` orders them.
    Returns `(total, ordered_keys, sliced_keys)`.
    """
    qry = db.query(SalesOrder).outerjoin(Customer, Customer.id == SalesOrder.customer_id)
    stock_qry = (
        db.query(ProductionOrder)
        .options(
            joinedload(ProductionOrder.planning_order),
            joinedload(ProductionOrder.items),
            joinedload(ProductionOrder.batches),
            joinedload(ProductionOrder.work_orders),
        )
        .outerjoin(Model, Model.id == ProductionOrder.model_id)
        .outerjoin(BrandedPlanningOrder, BrandedPlanningOrder.id == ProductionOrder.planning_order_id)
        .filter(ProductionOrder.sales_order_id.is_(None), ProductionOrder.production_type == "branded_stock")
    )
    if status:
        qry = qry.filter(SalesOrder.status == status)
        stock_qry = stock_qry.filter(ProductionOrder.status == status)
    if order_type:
        qry = qry.filter(SalesOrder.order_type == order_type)
        stock_qry = stock_qry.filter(ProductionOrder.production_type == order_type)
    if customer_id:
        qry = qry.filter(SalesOrder.customer_id == customer_id)
        stock_qry = stock_qry.filter(False)
    start, end = date_filter_bounds(created_from, created_to)
    if start:
        qry = qry.filter(SalesOrder.created_at >= start)
        stock_qry = stock_qry.filter(ProductionOrder.created_at >= start)
    if end:
        qry = qry.filter(SalesOrder.created_at <= end)
        stock_qry = stock_qry.filter(ProductionOrder.created_at <= end)
    if q:
        term = q.strip()
        exact_branded_group = (
            db.query(BrandedPlanningOrder.id)
            .filter(BrandedPlanningOrder.order_no == term)
            .first()
        )
        if exact_branded_group:
            qry = qry.filter(False)
            stock_qry = stock_qry.filter(BrandedPlanningOrder.order_no == term)
        else:
            like = f"%{term}%"
            model_code_like = normalized_model_code_pattern(term)
            sales_model_match = (
                db.query(SalesOrderItem.id)
                .join(Model, Model.id == SalesOrderItem.model_id)
                .filter(
                    SalesOrderItem.sales_order_id == SalesOrder.id,
                    (
                        normalized_model_code_column(Model.code).ilike(model_code_like)
                        | Model.name.ilike(like)
                    ),
                )
                .exists()
            )
            qry = qry.filter(
                or_(
                    order_reference_contains(SalesOrder.order_no, like),
                    SalesOrder.status.ilike(like),
                    SalesOrder.order_type.ilike(like),
                    Customer.name.ilike(like),
                    sales_model_match,
                )
            )
            stock_qry = stock_qry.filter(
                or_(
                    order_reference_contains(ProductionOrder.production_no, like),
                    ProductionOrder.status.ilike(like),
                    ProductionOrder.production_type.ilike(like),
                    normalized_model_code_column(Model.code).ilike(model_code_like),
                    Model.name.ilike(like),
                    order_reference_contains(BrandedPlanningOrder.order_no, like),
                    BrandedPlanningOrder.ordered_for_name.ilike(like),
                )
            )
    safe_page = max(1, page)
    safe_size = max(1, min(page_size, 200))

    candidates = (
        [(so.created_at, "sales", int(so.id)) for so in qry.all()]
        + [(po.created_at, "production", int(po.id)) for po in stock_qry.all()]
    )
    candidates.sort(
        key=lambda entry: ((entry[0].isoformat() if entry[0] else ""), int(entry[2])),
        reverse=True,
    )
    total = len(candidates)
    start_index = (safe_page - 1) * safe_size
    sliced = candidates[start_index:start_index + safe_size]
    ordered_keys = [
        _sales_key(row_id) if kind == "sales" else _production_key(row_id)
        for _, kind, row_id in candidates
    ]
    sliced_keys = [
        _sales_key(row_id) if kind == "sales" else _production_key(row_id)
        for _, kind, row_id in sliced
    ]
    return total, ordered_keys, sliced_keys


# --------------------------------------------------------------------------- #
# 1. Hydration must not grow with the candidate set
# --------------------------------------------------------------------------- #
def test_hydration_is_bounded_by_the_page_not_the_candidate_set(seeded):
    engine, session_factory, case = seeded
    page_size = 5
    probe = _HydrationProbe(engine)

    with session_factory() as db:
        with probe.measure() as measured:
            first = _call(db, page=1, page_size=page_size)
        small = (measured.entity_rows, measured.entity_statements, measured.all_statements)
        small_keys = _keys(first["rows"])
        small_total = first["total"]

    # Same page, five times the candidate set: the extra candidates are all
    # older, so the first page must stay byte-identical.
    filler = [(offset, "draft", "client_order", "draft") for offset in (-5, -10, -15, -20, -25)]
    _seed(session_factory, rows=filler * 6, prefix="-FILL")
    assert small_total == 12
    with session_factory() as db:
        with probe.measure() as measured:
            grown = _call(db, page=1, page_size=page_size)
        large = (measured.entity_rows, measured.entity_statements, measured.all_statements)

    assert _keys(grown["rows"]) == small_keys, "paging must not depend on the size of the candidate set"
    assert grown["total"] == small_total + len(filler) * 6 * 2, "the candidate set really did grow"

    print(
        f"\nPERF25 hydration rows={small[0]}->{large[0]} "
        f"entity statements={small[1]}->{large[1]} all statements={small[2]}->{large[2]}"
    )
    # Bounded by the page, identical before and after the candidate set grew.
    assert large[0] == small[0]
    assert large[0] <= page_size, f"hydrated {large[0]} rows for a {page_size}-row page"


def test_growth_never_hydrates_more_than_the_page(seeded):
    """Same invariant across page sizes, including pages that exhaust the set."""
    engine, session_factory, _ = seeded
    probe = _HydrationProbe(engine)
    for page_size in (1, 2, 3, 4, 5, 6, 7):
        with session_factory() as db:
            with probe.measure() as measured:
                _call(db, page=1, page_size=page_size)
            assert measured.entity_rows <= page_size, (
                f"page_size={page_size} hydrated {measured.entity_rows} entity rows"
            )
            # One hydration statement per selected row, plus the production-order
            # lookup `_sales_order_history` itself issues for each selected sales
            # row. That second statement is pre-existing and page-bounded, so it
            # is asserted separately rather than folded into the row count.
            assert measured.entity_statements <= 2 * page_size, (
                f"page_size={page_size} ran {measured.entity_statements} entity statements"
            )


# --------------------------------------------------------------------------- #
# 2. Ordering must be byte-identical to the old Python sort
# --------------------------------------------------------------------------- #
EXPECTED_ORDER = [
    # T+5 — tie on (created_at, id=1): stable sort kept the sales row first.
    _sales_key(1), _production_key(1),
    # T+4 — tie on (created_at, id=2).
    _sales_key(2), _production_key(2),
    # T+3 — two ties, on id=4 and on id=3. The second key sorts descending, so
    # id=4 precedes id=3; within one id the sales row still comes first.
    _sales_key(4), _production_key(4), _sales_key(3), _production_key(3),
    # T+1
    _sales_key(5), _production_key(5),
    # created_at IS NULL — the old key mapped it to "" and sorted it last.
    _sales_key(6), _production_key(6),
]


def test_tie_and_null_ordering_matches_the_pre_fix_sort(seeded):
    engine, session_factory, case = seeded
    # The fixture is only meaningful if the cross-kind id tie really exists.
    assert case["sales_ids"] == case["production_ids"] == [1, 2, 3, 4, 5, 6]

    with session_factory() as db:
        _, reference_order, _ = _reference_page(db)
    assert reference_order == EXPECTED_ORDER, "the oracle itself must match the hand-derived order"

    # Compare page by page against the oracle, across page sizes and pages.
    with session_factory() as db:
        for page_size in (1, 2, 3, 4, 5, 6, 7, 12, 13):
            for page in (1, 2, 3):
                expected_total, expected_order, expected_slice = _reference_page(
                    db, page=page, page_size=page_size
                )
                payload = _call(db, page=page, page_size=page_size, include_total=True)
                assert _keys(payload["rows"]) == expected_slice, (
                    f"page_size={page_size} page={page} order changed"
                )
                assert payload["total"] == expected_total
    # Paging the whole set must reproduce the oracle exactly, with no row
    # dropped and none duplicated.
    with session_factory() as db:
        _, expected_order, _ = _reference_page(db)
        paged = []
        for page in range(1, 6):
            payload = _call(db, page=page, page_size=5)
            if not payload["rows"]:
                break
            paged.extend(_keys(payload["rows"]))
    assert paged == expected_order == EXPECTED_ORDER
    assert len(set(paged)) == len(paged) == 12


def test_full_payload_is_identical_to_the_pre_fix_payload(seeded):
    """Not just the ids: the rendered rows must match too."""
    engine, session_factory, _ = seeded
    with session_factory() as db:
        for page_size in (2, 5):
            for page in (1, 2):
                payload = _call(db, page=page, page_size=page_size)
                _, _, expected_keys = _reference_page(db, page=page, page_size=page_size)
                assert _keys(payload["rows"]) == expected_keys
                # Re-derive the same rows through the single-record endpoints'
                # builders and compare field by field.
                for row, (record_type, row_id) in zip(payload["rows"], expected_keys):
                    if record_type == "sales_order":
                        entity = db.get(SalesOrder, row_id)
                        expected = sales_routes._sales_order_history(db, entity, include_detail=False)
                    else:
                        entity = db.get(ProductionOrder, row_id)
                        expected = sales_routes._stock_production_history(db, entity, include_detail=False)
                    assert row == expected, f"{record_type} {row_id} payload drifted"


# --------------------------------------------------------------------------- #
# 3. Totals describe the whole candidate set
# --------------------------------------------------------------------------- #
def test_total_counts_the_whole_candidate_set(seeded):
    engine, session_factory, case = seeded
    with session_factory() as db:
        for page_size in (1, 3, 5, 12, 50):
            payload = _call(db, page=1, page_size=page_size)
            assert payload["total"] == 12, payload["total"]
            assert len(payload["rows"]) == min(page_size, 12)
            assert payload["page"] == 1
            assert payload["page_size"] == page_size
        last = _call(db, page=3, page_size=5)
        assert last["total"] == 12, "total must not describe the page"
        assert len(last["rows"]) == 2
        # Past the end: empty page, unchanged total.
        beyond = _call(db, page=99, page_size=5)
        assert beyond["rows"] == []
        assert beyond["total"] == 12
    assert case["sales_ids"] and case["production_ids"]


def test_include_total_false_still_returns_a_bare_page(seeded):
    engine, session_factory, _ = seeded
    with session_factory() as db:
        payload = _call(db, page=2, page_size=4, include_total=False)
        assert isinstance(payload, list)
        assert len(payload) == 4
        assert [row["record_type"] for row in payload] == [
            "sales_order", "production_order", "sales_order", "production_order",
        ]


# --------------------------------------------------------------------------- #
# 4. Every existing filter must survive the rewrite
# --------------------------------------------------------------------------- #
def test_filters_are_preserved(seeded):
    engine, session_factory, case = seeded
    customer_id = case["customer_id"]
    other_customer_id = case["other_customer_id"]

    filter_cases = [
        {},
        {"status": "confirmed"},
        {"status": "draft"},
        {"status": "new"},
        {"order_type": "client_order"},
        {"order_type": "branded_stock_sale"},
        {"order_type": "branded_stock"},
        {"customer_id": customer_id},
        {"customer_id": other_customer_id},
        {"q": f"{SALES_BASE}-3"},
        {"q": f"{PROD_BASE}-2"},
        {"q": case["group_no"]},
        {"q": "PERF25-MODEL"},
        {"q": "no-such-reference"},
        {"created_from": date(2024, 5, 1)},
        {"created_to": date(2024, 5, 1)},
        {"created_from": date(2024, 5, 1), "created_to": date(2024, 5, 1)},
        {"created_from": date(2024, 4, 30)},
        {"status": "confirmed", "q": f"{SALES_BASE}-2"},
    ]
    with session_factory() as db:
        for filters in filter_cases:
            for page_size in (2, 5, 12):
                for page in (1, 2):
                    expected_total, expected_order, expected_slice = _reference_page(
                        db, page=page, page_size=page_size, **filters
                    )
                    payload = _call(db, page=page, page_size=page_size, **filters)
                    assert _keys(payload["rows"]) == expected_slice, (filters, page_size, page)
                    assert payload["total"] == expected_total, (filters, page_size, page)


def test_filter_results_match_hand_derived_expectations(seeded):
    """The oracle is only trusted where it can be checked by hand too."""
    engine, session_factory, case = seeded
    customer_id = case["customer_id"]
    other_customer_id = case["other_customer_id"]

    def whole(**filters):
        with session_factory() as db:
            collected = []
            page = 1
            while True:
                payload = _call(db, page=page, page_size=5, **filters)
                if not payload["rows"]:
                    break
                collected.extend(_keys(payload["rows"]))
                page += 1
            return collected, payload["total"]

    # status=confirmed -> sales 2,4,6 and production 2,4,6.
    assert whole(status="confirmed") == ([
        _sales_key(2), _production_key(2), _sales_key(4), _production_key(4),
        _sales_key(6), _production_key(6),
    ], 6)
    # status=draft -> sales 1,3,5 and production 1,3,5.
    assert whole(status="draft") == ([
        _sales_key(1), _production_key(1), _sales_key(3), _production_key(3),
        _sales_key(5), _production_key(5),
    ], 6)
    # order_type=client_order keeps only the sales branch (a stock production
    # order's production_type can never be a sales order_type). Rows 1, 2 and 5
    # are client orders.
    assert whole(order_type="client_order") == (
        [_sales_key(1), _sales_key(2), _sales_key(5)], 3,
    )
    # order_type=branded_stock_sale keeps rows 3, 4 and 6 of the sales branch.
    # Orders 3 and 4 share T+3 and the id tie-break is descending.
    assert whole(order_type="branded_stock_sale") == (
        [_sales_key(4), _sales_key(3), _sales_key(6)], 3,
    )
    # A customer filter zeroes the stock-production branch entirely.
    assert whole(customer_id=customer_id) == (
        [_sales_key(1), _sales_key(2), _sales_key(4), _sales_key(3),
         _sales_key(5), _sales_key(6)], 6,
    )
    assert whole(customer_id=other_customer_id) == ([], 0)
    # An exact branded-planning-group reference keeps the stock branch only.
    assert whole(q=case["group_no"]) == (
        [_production_key(1), _production_key(2), _production_key(4),
         _production_key(3), _production_key(5), _production_key(6)], 6,
    )
    # A plain sales-order reference keeps the sales branch only.
    assert whole(q=f"{SALES_BASE}-3") == ([_sales_key(3)], 1)
    # A date filter drops the NULL created_at rows entirely.
    keys, total = whole(created_from=date(2024, 5, 1), created_to=date(2024, 5, 1))
    assert keys == EXPECTED_ORDER[:10]
    assert total == 10
    # A date range before every candidate finds nothing.
    assert whole(created_from=date(2024, 4, 30), created_to=date(2024, 4, 30)) == ([], 0)


# --------------------------------------------------------------------------- #
# 5. The stock branch's eager-loading contract is unchanged
# --------------------------------------------------------------------------- #
def test_selected_production_rows_keep_their_eager_loaded_children(seeded, monkeypatch):
    """A contract, not a perf assertion: it must hold before and after the fix.

    `_stock_production_history` reads `po.work_orders`, `po.batches`,
    `po.items` and `po.planning_order` without querying. If the hydration lost
    the route's `joinedload` options those reads would silently become one
    extra query per selected row, so the entities the builder is handed have
    to arrive with those attributes already loaded.
    """
    engine, session_factory, _ = seeded
    captured = []
    original = sales_routes._stock_production_history

    def recording(db, po, *, include_detail=False):
        captured.append(po)
        return original(db, po, include_detail=include_detail)

    monkeypatch.setattr(sales_routes, "_stock_production_history", recording)
    with session_factory() as db:
        payload = _call(db, page=1, page_size=6)
    assert captured, "no stock production row was hydrated"
    for po in captured:
        unloaded = sa_inspect(po).unloaded
        for attribute in ("work_orders", "batches", "items", "planning_order"):
            assert attribute not in unloaded, (
                f"production order {po.id} lazy-loads {attribute}"
            )
    assert len(payload["rows"]) == 6
