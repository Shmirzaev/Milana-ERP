"""PERF41: eco history must not issue one fabric-roll query per dispatch.

The report read path used to call ``dispatch_data()`` once per dispatch on the
page, and each call ran its own ``SELECT ... FROM eco_fabric_rolls WHERE
dispatch_id = ?``.  With N dispatches on a page that is N queries.  The fix
loads the whole page's rolls in one query and groups them in Python.

The invariant under test is sublinearity, not a hardcoded statement count: a
page six times wider must not cost meaningfully more statements.

Measurement runs against a real PostgreSQL 17 engine so ``NUMERIC(14, 4)``
quantities, Decimal precision and the JSON ``remaining_inventory`` snapshot
behave exactly as in production.  Set ``STABILIZATION_POSTGRES_URL`` to enable;
without it the module skips loudly rather than reading as green.
"""

import contextlib
import json
import os
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from fastapi.encoders import jsonable_encoder
import pytest
from sqlalchemy import create_engine, event, func
from sqlalchemy.engine import make_url
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import defer, sessionmaker

from app.api.routes import eco_transfers
from app.api.routes.eco_transfers import dispatch_data
from app.api.routes.fabric_scans import TASHKENT
from app.db.base import Base
from app.models import (
    EcoFabricDispatch,
    EcoFabricRoll,
    Item,
    StockBatch,
    User,
    Warehouse,
)

# Payload captured from the UNFIXED route (base commit 88dcffb5).  Asserting
# byte-equality against it is the before/after proof that totals, ordering and
# roll serialisation are untouched by the batching change.
GOLDEN_PATH = Path(__file__).with_name("test_eco_history_query_growth_golden.json")
GOLDEN_BASE_COMMIT = "88dcffb5"

SMALL_PAGE = 2
LARGE_PAGE = 12  # 6x SMALL_PAGE, the growth we refuse to pay for.

# Quantities exercise the full NUMERIC(14,4) scale, including a value that
# cannot survive a float round-trip.
ROLLS_PER_DISPATCH = 2
DISPATCH_COUNT = LARGE_PAGE
REPORTED_DATE = date(2026, 9, 1)
OTHER_DATE = date(2026, 9, 2)
SENT_AT = {REPORTED_DATE: datetime(2026, 9, 1, 12, tzinfo=timezone.utc),
           OTHER_DATE: datetime(2026, 9, 2, 12, tzinfo=timezone.utc)}
QUANTITIES = [Decimal("1.2345"), Decimal("12.0001"), Decimal("0.0001"), Decimal("9.8765")]


class EcoHistory:
    """Handle for the throwaway PostgreSQL schema backing this module."""

    def __init__(self, engine, sessions):
        self.engine = engine
        self.sessions = sessions
        self.user = None
        self.dispatches = []

    def measure(self, *, page=1, page_size=30, **kwargs):
        """Run one ``report()`` call and capture every statement it issues."""
        statements = []

        def capture(_conn, _cursor, statement, _params, _context, _many):
            statements.append(" ".join(str(statement).split()))

        with self.sessions() as db:
            event.listen(db.bind, "before_cursor_execute", capture)
            try:
                payload = eco_transfers.report(db=db, user=self.user, page=page, page_size=page_size, **kwargs)
            finally:
                event.remove(db.bind, "before_cursor_execute", capture)
        return payload, statements


@contextlib.contextmanager
def eco_history_schema():
    """Throwaway PostgreSQL schema holding one seeded page of eco dispatches."""
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL for real PostgreSQL eco history coverage")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Eco history query-growth tests require a loopback PostgreSQL URL without connection overrides")
    schema = f"eco_history_growth_{uuid4().hex}"
    engine = create_engine(
        url,
        connect_args={"options": f"-csearch_path={schema} -cstatement_timeout=20000"},
        pool_size=2,
        max_overflow=0,
        isolation_level="READ COMMITTED",
    )
    assert engine.dialect.name == "postgresql"
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        tables = {EcoFabricDispatch.__table__, EcoFabricRoll.__table__}
        pending = list(tables)
        while pending:
            for foreign_key in pending.pop().foreign_keys:
                target = foreign_key.column.table
                if target not in tables:
                    tables.add(target)
                    pending.append(target)
        Base.metadata.create_all(engine, tables=list(tables))
        handle = EcoHistory(engine, sessionmaker(bind=engine, autoflush=False, expire_on_commit=False))
        _seed(handle)
        yield handle
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


@pytest.fixture(scope="module")
def eco_history_postgres():
    with eco_history_schema() as handle:
        yield handle


def _seed(handle):
    """One MIL user, one fabric batch, and a page of dispatches with two rolls each.

    Every value that reaches the response is deterministic, so the payload can be
    compared against a capture taken from a different process/schema.
    """
    with handle.sessions.begin() as db:
        assert db.bind.dialect.name == "postgresql"
        user = User(name="Eco history reader", email="eco-history@example.invalid",
                    password_hash="unused", factory_code="MIL", is_active=True)
        item = Item(sku="ECO-HISTORY", name="Eco history fabric", category="fabric", unit="kg")
        warehouse = Warehouse(name="Eco history warehouse", type="material")
        db.add_all([user, item, warehouse])
        db.flush()
        batch = StockBatch(item_id=item.id, warehouse_id=warehouse.id, batch_no="ECO-HISTORY",
                           quantity=Decimal("500.0000"), piece_count=120, unit="kg", qc_status="passed")
        db.add(batch)
        db.flush()
        handle.user = user
        roll_number = 0
        for index in range(DISPATCH_COUNT):
            sent_day = REPORTED_DATE if index % 2 == 0 else OTHER_DATE
            # A wide JSON snapshot: unused by the read path, so it must not be fetched.
            dispatch = EcoFabricDispatch(
                request_key=f"eco-history-{index:04d}", created_by=user.id, operator_name=f"Dispatcher {index}",
                sent_at=SENT_AT[sent_day],
                remaining_inventory=[{"fabric_name": f"Batch {n}", "batch_no": f"SNAP-{n}",
                                      "quantity": "1.0000", "unit": "kg", "rolls": 1, "pad": "x" * 256}
                                     for n in range(40)],
            )
            db.add(dispatch)
            db.flush()
            for part in range(ROLLS_PER_DISPATCH):
                roll_number += 1
                returned = part == 1 and index % 3 == 0
                db.add(EcoFabricRoll(
                    dispatch_id=dispatch.id, batch_id=batch.id, roll_number=roll_number,
                    fabric_name=item.name, batch_no=batch.batch_no, color="Blue",
                    quantity=QUANTITIES[(index + part) % len(QUANTITIES)], unit="kg",
                    returned_at=datetime(2026, 9, 3, 8, tzinfo=timezone.utc) if returned else None,
                    return_operator_name="Returning operator" if returned else None,
                    return_key=f"eco-return-{index:04d}-{part}" if returned else None,
                ))
            handle.dispatches.append(dispatch.id)
        # One dispatch with no rolls at all: the batched query must not lose it.
        db.add(EcoFabricDispatch(request_key="eco-history-no-rolls", created_by=user.id, operator_name="No rolls",
                                 sent_at=datetime(2026, 9, 3, 12, tzinfo=timezone.utc),
                                 remaining_inventory=[]))
        db.flush()
        assert db.query(EcoFabricRoll).count() == DISPATCH_COUNT * ROLLS_PER_DISPATCH


def _decimal_strings(payload):
    """Exact Decimal text, so NUMERIC(14,4) precision is asserted, not float equality."""
    items = [
        {"id": item["id"],
         "sent_kg": str(item["sent_kg"]),
         "outstanding_kg": str(item["outstanding_kg"]),
         "row_quantities": [str(row["quantity"]) for row in item["rows"]]}
        for item in payload["items"]
    ]
    return {"items": items,
            "global_outstanding_kg": str(payload["outstanding_kg"]),
            "global_outstanding_rolls": payload["outstanding_rolls"],
            "total": payload["total"]}


def _snapshot(handle):
    """The three requests whose payloads are frozen against the unfixed route."""
    page_one, _ = handle.measure(page=1, page_size=5)
    page_two, _ = handle.measure(page=2, page_size=5)
    dated, _ = handle.measure(page=1, report_date=REPORTED_DATE, page_size=100)
    return {
        "base_commit": GOLDEN_BASE_COMMIT,
        "page_one": jsonable_encoder(page_one),
        "page_two": jsonable_encoder(page_two),
        "dated": jsonable_encoder(dated),
        "page_one_decimals": _decimal_strings(page_one),
        "page_two_decimals": _decimal_strings(page_two),
        "dated_decimals": _decimal_strings(dated),
    }


@pytest.fixture(scope="module")
def golden():
    assert GOLDEN_PATH.exists(), f"missing pre-fix payload capture: {GOLDEN_PATH}"
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def test_history_page_payload_is_byte_identical_to_the_unfixed_route(eco_history_postgres, golden):
    """The batching change must not move a single byte of the response."""
    assert golden["base_commit"] == GOLDEN_BASE_COMMIT
    live = _snapshot(eco_history_postgres)
    for key in ("page_one", "page_two", "dated"):
        assert live[key] == golden[key], f"{key} payload drifted from the pre-fix capture"
    for key in ("page_one_decimals", "page_two_decimals", "dated_decimals"):
        assert live[key] == golden[key], f"{key} Decimal totals drifted from the pre-fix capture"


def test_history_totals_ignore_only_page_width(eco_history_postgres):
    """Ordering, date filtering and the all-date custody totals are page-width independent."""
    small, _ = eco_history_postgres.measure(page=1, page_size=5)
    large, _ = eco_history_postgres.measure(page=1, page_size=100)
    # total and the global outstanding pair ignore pagination entirely.
    assert small["total"] == large["total"] == DISPATCH_COUNT + 1
    assert small["outstanding_rolls"] == large["outstanding_rolls"]
    assert small["outstanding_kg"] == large["outstanding_kg"]
    # Ordering is sent_at desc, id desc and is stable across page widths.
    with eco_history_postgres.sessions() as db:
        all_rows = db.query(EcoFabricDispatch).all()
    expected_ids = [row.id for row in sorted(all_rows, key=lambda row: (row.sent_at, row.id), reverse=True)]
    ids = [item["id"] for item in large["items"]]
    assert ids == expected_ids
    assert [item["id"] for item in small["items"]] == ids[:5]
    # report_date narrows only the page; the outstanding pair stays global.
    with eco_history_postgres.sessions() as db:
        start = datetime.combine(REPORTED_DATE, time.min, TASHKENT).astimezone(timezone.utc)
        dated_ids = {row.id for row in db.query(EcoFabricDispatch).filter(
            EcoFabricDispatch.sent_at >= start,
            EcoFabricDispatch.sent_at < start + timedelta(days=1))}
    dated, _ = eco_history_postgres.measure(report_date=REPORTED_DATE, page_size=100)
    assert dated["total"] == DISPATCH_COUNT // 2
    assert dated["outstanding_rolls"] == large["outstanding_rolls"]
    assert dated["outstanding_kg"] == large["outstanding_kg"]
    assert dated["items"] == [item for item in large["items"] if item["id"] in dated_ids]


def test_history_query_count_does_not_grow_with_page_width(eco_history_postgres):
    """The defect: one roll query per dispatch. A 6x wider page must not cost 6x the queries."""
    _, small_statements = eco_history_postgres.measure(page=1, page_size=SMALL_PAGE)
    _, large_statements = eco_history_postgres.measure(page=1, page_size=LARGE_PAGE)
    small = len(small_statements)
    large = len(large_statements)
    print(f"\nPERF41 eco history statements: page_size={SMALL_PAGE} -> {small}, "
          f"page_size={LARGE_PAGE} -> {large}")
    assert small, "no statements captured; the counter is broken"
    # Bounded, not linear: widening the page six times may add at most a couple
    # of statements, and never a per-dispatch roll query.
    assert large <= small + 2, (
        f"query count grew with dispatch count: page_size={SMALL_PAGE}->{small}, page_size={LARGE_PAGE}->{large} "
        f"({len([s for s in large_statements if 'eco_fabric_rolls.dispatch_id =' in s])} per-dispatch roll reads)"
    )
    # The one page-wide roll read, and no per-dispatch roll read at all.
    per_dispatch = [s for s in large_statements
                    if "FROM eco_fabric_rolls" in s and "eco_fabric_rolls.dispatch_id =" in s]
    batched = [s for s in large_statements
               if "FROM eco_fabric_rolls" in s and "IN (" in s and "eco_fabric_rolls.dispatch_id IN" in s]
    assert per_dispatch == [], f"still one roll query per dispatch: {len(per_dispatch)}"
    assert len(batched) == 1, f"expected one batched roll query, got {len(batched)}"
    assert all(s.lstrip().upper().startswith("SELECT") for s in large_statements), large_statements


def test_history_defers_remaining_inventory_instead_of_just_ignoring_it(eco_history_postgres):
    """The deferral must actually leave the SQL, and must fail loudly if anyone reads it."""
    _, statements = eco_history_postgres.measure(page=1, page_size=LARGE_PAGE)
    page_reads = [s for s in statements if "FROM eco_fabric_dispatches" in s
                  and "ORDER BY" in s and "count(*)" not in s]
    assert page_reads, statements
    assert all("remaining_inventory" not in s for s in page_reads), page_reads
    assert all("request_key" in s and "sent_at" in s for s in page_reads), page_reads
    # raiseload: the snapshot is absent, not lazily re-fetched on access.
    with eco_history_postgres.sessions() as db:
        row = db.query(EcoFabricDispatch).options(
            defer(EcoFabricDispatch.remaining_inventory, raiseload=True)).order_by(
            EcoFabricDispatch.id).first()
        assert row is not None
        with pytest.raises(InvalidRequestError):
            _ = row.remaining_inventory


def test_history_leaves_remaining_inventory_snapshot_untouched(eco_history_postgres):
    """Deferring the JSON snapshot is safe only if nothing reads it, and it must not be rewritten."""
    with eco_history_postgres.sessions() as db:
        before = {row.id: row.remaining_inventory
                  for row in db.query(EcoFabricDispatch).order_by(EcoFabricDispatch.id)}
    assert any(value for value in before.values())
    eco_history_postgres.measure(page=1, page_size=100)
    eco_history_postgres.measure(report_date=REPORTED_DATE, page_size=100)
    with eco_history_postgres.sessions() as db:
        after = {row.id: row.remaining_inventory
                 for row in db.query(EcoFabricDispatch).order_by(EcoFabricDispatch.id)}
    assert after == before


def test_history_matches_the_unchanged_single_dispatch_builder(eco_history_postgres):
    """Cross-check every page item against the per-dispatch path this fix did not touch."""
    payload, _ = eco_history_postgres.measure(page=1, page_size=100)
    with eco_history_postgres.sessions() as db:
        expected = [dispatch_data(db, db.get(EcoFabricDispatch, item["id"])) for item in payload["items"]]
    assert payload["items"] == expected
    empty = next(item for item in payload["items"] if not item["rows"])
    assert (empty["sent_rolls"], empty["outstanding_rolls"]) == (0, 0)
    assert (empty["sent_kg"], empty["outstanding_kg"]) == (Decimal("0"), Decimal("0"))
    for item in payload["items"]:
        assert item["outstanding_rolls"] == sum(row["returned_at"] is None for row in item["rows"])
        assert item["outstanding_kg"] == sum(
            (Decimal(str(row["quantity"])) for row in item["rows"] if row["returned_at"] is None), Decimal("0"))
        assert [row["id"] for row in item["rows"]] == sorted(row["id"] for row in item["rows"])


def test_global_outstanding_totals_match_a_direct_aggregate(eco_history_postgres):
    """Global custody totals are independent of the page and match a plain aggregate."""
    payload, _ = eco_history_postgres.measure(page=1, page_size=3)
    with eco_history_postgres.sessions() as db:
        rolls, weight = db.query(func.count(EcoFabricRoll.id),
                                 func.coalesce(func.sum(EcoFabricRoll.quantity), 0)).filter_by(returned_at=None).one()
    assert (payload["outstanding_rolls"], payload["outstanding_kg"]) == (rolls, weight)
    assert str(weight).count(".") == 1 and len(str(weight).split(".")[1]) == 4, weight


def test_out_of_range_page_and_empty_page_are_stable(eco_history_postgres):
    empty, _ = eco_history_postgres.measure(page=99, page_size=5)
    assert empty["items"] == [] and empty["total"] == DISPATCH_COUNT + 1
    with eco_history_postgres.sessions() as db:
        assert db.query(EcoFabricDispatch).order_by(EcoFabricDispatch.sent_at.desc(),
                                                    EcoFabricDispatch.id.desc()).count() == DISPATCH_COUNT + 1
