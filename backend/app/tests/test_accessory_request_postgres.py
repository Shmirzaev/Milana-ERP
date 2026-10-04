"""PERF02: the accessory issue-request queue must not compute every candidate.

`GET /api/inventory/accessory-issue-requests` is the sewing-block queue. The
Python implementation walked every candidate production order, built a full
accessory issue plan for each one (BOM read, issued/returned aggregation,
per-line available stock) and only then sliced the requested page, so the work
grew with the candidate set instead of the page.

This module needs a real PostgreSQL server because the fixed queue is one
set-based statement: a SQLite run exercises the dialect fallback and proves
nothing about the SQL path. Set STABILIZATION_POSTGRES_URL to run it; without
it every test here skips loudly instead of passing silently.

`accessory_request_golden.json` holds the payloads captured from the
unoptimized implementation on this exact fixture. Totals, units, manual-issue
aliases, return handling and row order are stock-facing, so the queue response
has to stay identical, not merely plausible.
"""

from contextlib import contextmanager
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.routes import inventory as inventory_routes
from app.db.base import Base
from app.models import (
    AuditLog,
    CuttingRecord,
    Department,
    IdempotencyRecord,
    Item,
    ManualAccessoryIssue,
    MaterialReservation,
    Model,
    ModelBOM,
    PackagingRecord,
    ProductionOrder,
    ProductionOrderItem,
    ProductionOrderMaterial,
    SalesOrder,
    SewingRecord,
    StockBatch,
    StockMovement,
    User,
    Warehouse,
    WorkOrder,
)

GOLDEN_PATH = Path(__file__).with_name("accessory_request_golden.json")
ID_TOKENS = {"production_order_id": "production_order", "item_id": "item", "model_id": "model"}

# (sku, name, unit, category) - "m" and "pcs" are both present, so a queue that
# coerced accessory units to pieces is caught by the golden payload.
SCENARIO_ITEMS = (
    ("BTN-RED", "Button red 18mm", "pcs", "accessory"),
    ("ZIP-BLK", "Zipper black 45cm", "pcs", "accessory"),
    ("TAPE-WHT", "Tape white 20m", "m", "accessory"),
    ("BAG-CLR", "Poly bag clear 30x40", "pcs", "packaging"),
    # 0.0625 and 0.3125 per piece with 25% waste land exactly on a half step at
    # four decimals for the ten-piece order line, which is where Python's
    # half-to-even rule and PostgreSQL's half-away-from-zero disagree.
    ("LBL-RED", "Label red 5x3", "pcs", "accessory"),
    ("TIE-CLN", "Tie cloth 2cm", "m", "accessory"),
    # A fifth decimal that is not a half step, so ordinary rounding is covered.
    ("TAG-BLU", "Tag blue 2x1", "pcs", "accessory"),
)
# model code -> (sku, quantity_per_piece, waste_percent, size, color, on_batch)
SCENARIO_BOM = {
    "MDL-01": (
        ("BTN-RED", 1, 0, None, None, False),
        ("ZIP-BLK", 0.5, 25, None, None, False),
        ("TAPE-WHT", 0.5, 0, None, None, False),
        ("BAG-CLR", 0.25, 0, None, None, False),
        ("LBL-RED", 0.0625, 25, None, None, False),
        ("TIE-CLN", 0.3125, 25, None, None, False),
        ("TAG-BLU", 0.3333, 7, None, None, False),
    ),
    "MDL-02": (
        ("BTN-RED", 2, 0, None, None, False),
        ("ZIP-BLK", 1, 0, None, None, False),
        # "M"/"Red" matches the order line below, "L"/"Blue" must not.
        ("TAPE-WHT", 0.25, 0, "M", "Red", False),
        ("TAPE-WHT", 0.25, 0, "L", "Blue", False),
        # Same item and unit as the next line, split by stock batch: both stay
        # separate queue rows and both read the same issued allowance.
        ("BAG-CLR", 0.25, 0, None, None, False),
        ("BAG-CLR", 0.25, 0, None, None, True),
    ),
}
# Every quantity above is a binary-exact float and every waste factor is an
# exact binary fraction, so pre-fix Python floats and PostgreSQL double
# precision arithmetic agree bit for bit.
SMALL_ORDERS = 4
LARGE_ORDERS = 40
SEED_TABLES = (
    AuditLog,
    CuttingRecord,
    IdempotencyRecord,
    Item,
    ManualAccessoryIssue,
    MaterialReservation,
    Model,
    ModelBOM,
    PackagingRecord,
    ProductionOrder,
    ProductionOrderItem,
    ProductionOrderMaterial,
    SalesOrder,
    SewingRecord,
    StockBatch,
    StockMovement,
    User,
    Warehouse,
    WorkOrder,
)


@pytest.fixture(scope="module")
def accessory_request_sessions():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip(
            "Set STABILIZATION_POSTGRES_URL for the set-based accessory request queue "
            "coverage; without it only the SQLite fallback is exercised"
        )
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Accessory request queue tests require a loopback PostgreSQL URL without connection overrides")
    schema = f"accessory_request_{uuid4().hex}"
    engine = create_engine(
        url,
        connect_args={"options": f"-csearch_path={schema} -cstatement_timeout=30000"},
        pool_size=4,
        max_overflow=0,
        isolation_level="READ COMMITTED",
    )
    assert engine.dialect.name == "postgresql"
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        tables = {table.__table__ for table in SEED_TABLES}
        pending = list(tables)
        while pending:
            for foreign_key in pending.pop().foreign_keys:
                target = foreign_key.column.table
                if target not in tables:
                    tables.add(target)
                    pending.append(target)
        Base.metadata.create_all(engine, tables=list(tables))
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False), engine
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def _seed(session_factory, *, prefix, orders):
    """Build the accessory queue fixture; return generated-id -> token maps."""
    marker = uuid4().hex
    tokens = {"production_order": {}, "item": {}, "model": {}}
    with session_factory.begin() as db:
        user = User(
            name="Accessory queue reader",
            email=f"accessory-request-{marker}@example.invalid",
            password_hash="unused",
            factory_code="MIL",
            extra_permissions=[],
            is_active=True,
        )
        department = Department(name=f"{prefix} cutting", code=f"{prefix}-CUT")
        warehouse = Warehouse(name=f"{prefix} storage", type="accessory_storage")
        sales_order = SalesOrder(order_no=f"{prefix}-SO-1", status="confirmed")
        db.add_all([user, department, warehouse, sales_order])
        db.flush()

        items = {}
        for sku, name, unit, category in SCENARIO_ITEMS:
            item = Item(
                sku=f"{prefix}-{sku}",
                name=name,
                category=category,
                unit=unit,
                image_url=f"/media/items/{sku}.png",
            )
            db.add(item)
            items[sku] = item
        models = {}
        for code in SCENARIO_BOM:
            model = Model(code=f"{prefix}-{code}", name=f"{code} model", status="approved")
            db.add(model)
            models[code] = model
        db.flush()
        for sku, item in items.items():
            tokens["item"][int(item.id)] = f"item-{sku}"
        for code, model in models.items():
            tokens["model"][int(model.id)] = f"model-{code}"

        # Only the tape item carries stock, and part of it is reserved, so the
        # queue produces ready, partial and shortage rows side by side.
        tape_batch = StockBatch(
            item_id=int(items["TAPE-WHT"].id),
            batch_no=f"{prefix}-BATCH-1",
            quantity=8,
            unit="m",
            warehouse_id=int(warehouse.id),
        )
        db.add(tape_batch)
        db.flush()

        by_index = {}
        for index in range(orders):
            code = "MDL-01" if index % 2 == 0 else "MDL-02"
            if index % 8 == 7:
                status = "finished_storage"
            elif index % 8 == 6:
                status = "cancelled"
            else:
                status = "new" if index % 2 == 0 else "in_production"
            order = ProductionOrder(
                production_no=f"{prefix}-PO-{index:03d}",
                production_type="branded_stock",
                sales_order_id=int(sales_order.id),
                model_id=int(models[code].id),
                status=status,
                planned_quantity=index % 5 + 5,
            )
            db.add(order)
            db.flush()
            by_index[index] = order
            tokens["production_order"][int(order.id)] = f"po-{index}"
            if index % 3 == 0:
                db.add(ProductionOrderItem(
                    production_order_id=int(order.id),
                    model_id=int(models[code].id),
                    color="Red",
                    size="M",
                    planned_quantity=10,
                    completed_quantity=0,
                ))
        db.flush()

        for code, lines in SCENARIO_BOM.items():
            for sku, per_piece, waste, size, color, on_batch in lines:
                db.add(ModelBOM(
                    model_id=int(models[code].id),
                    item_id=int(items[sku].id),
                    stock_batch_id=int(tape_batch.id) if on_batch else None,
                    size=size,
                    color=color,
                    quantity_per_piece=per_piece,
                    unit=items[sku].unit,
                    waste_percent=waste,
                ))
        db.flush()

        for index, order in by_index.items():
            if index == 0:
                # Direct order reference, more than required, so the row only
                # shows up with include_complete.
                db.add(StockMovement(
                    movement_type="consume",
                    item_id=int(items["BTN-RED"].id),
                    quantity=12,
                    unit="pcs",
                    reference_type="ProductionOrder",
                    reference_id=int(order.id),
                ))
                work_order = WorkOrder(
                    production_order_id=int(order.id),
                    department_id=int(department.id),
                    operation="cutting",
                    status="completed",
                )
                db.add(work_order)
                db.flush()
                cutting = CuttingRecord(
                    work_order_id=int(work_order.id),
                    input_quantity=10,
                    cut_pieces=10,
                    passed_pieces=10,
                )
                db.add(cutting)
                db.flush()
                # Issued through a work order, and through a cutting record.
                db.add(StockMovement(
                    movement_type="issue",
                    item_id=int(items["TAPE-WHT"].id),
                    quantity=1.5,
                    unit="m",
                    reference_type="WorkOrder",
                    reference_id=int(work_order.id),
                ))
                db.add(StockMovement(
                    movement_type="consume",
                    item_id=int(items["ZIP-BLK"].id),
                    quantity=0.5,
                    unit="pcs",
                    reference_type="CuttingRecord",
                    reference_id=int(cutting.id),
                ))
            if index == 1:
                # One linked manual issue plus two label-only aliases: one
                # matches a BOM line by item name in that line's own unit, the
                # other uses "set" and must not count against the piece line.
                db.add(ManualAccessoryIssue(
                    production_order_id=int(order.id),
                    item_id=int(items["BTN-RED"].id),
                    item_sku=f"{prefix}-BTN-RED",
                    item_name="Button red 18mm",
                    quantity=2,
                    unit="pcs",
                ))
                db.add(ManualAccessoryIssue(
                    production_order_id=int(order.id),
                    item_id=None,
                    item_sku=None,
                    item_name="Tape white 20m",
                    quantity=1,
                    unit="m",
                ))
                db.add(ManualAccessoryIssue(
                    production_order_id=int(order.id),
                    item_id=None,
                    item_sku=f"{prefix}-BTN-RED",
                    item_name="Button red 18mm",
                    quantity=3,
                    unit="set",
                ))
            if index == 2:
                # A recorded return must not reduce the queued remainder; it
                # only shrinks the summary's returnable allowance.
                db.add(StockMovement(
                    movement_type="return",
                    item_id=int(items["BTN-RED"].id),
                    batch_id=None,
                    quantity=1,
                    unit="pcs",
                    reference_type="ProductionOrderAccessoryReturn",
                    reference_id=int(order.id),
                ))
            if index >= 3:
                db.add(StockMovement(
                    movement_type="consume",
                    item_id=int(items["BTN-RED"].id),
                    quantity=1,
                    unit="pcs",
                    reference_type="ProductionOrder",
                    reference_id=int(order.id),
                ))

        db.add(MaterialReservation(
            reservation_no=f"{prefix}-RES-1",
            production_order_id=int(by_index[0].id),
            item_id=int(items["TAPE-WHT"].id),
            stock_batch_id=int(tape_batch.id),
            warehouse_id=int(warehouse.id),
            reserved_quantity=0.5,
            unit="m",
            status="reserved",
            reservation_type="accessory",
            source="manual",
            reserved_by=int(user.id),
        ))
        db.flush()
        return tokens


def _stable(payload, tokens, *, prefix):
    """Replace generated ids and the fixture prefix so payloads are comparable."""
    if isinstance(payload, list):
        return [_stable(entry, tokens, prefix=prefix) for entry in payload]
    if isinstance(payload, dict):
        stable = {}
        for key, value in payload.items():
            if key in ID_TOKENS and isinstance(value, int):
                stable[key] = tokens[ID_TOKENS[key]].get(value, value)
            else:
                stable[key] = _stable(value, tokens, prefix=prefix)
        return stable
    if isinstance(payload, str):
        return payload.replace(f"{prefix}-", "")
    return payload


def _queue(session_factory, tokens, *, prefix, only_prefix=True, **kwargs):
    with session_factory() as db:
        assert db.bind.dialect.name == "postgresql"
        user = db.query(User).order_by(User.id).first()
        payload = inventory_routes.list_accessory_issue_requests(db=db, _=user, **kwargs)
    if only_prefix:
        # Every test in this module shares one schema, so a scenario is only
        # ever compared against the rows of the fixture it seeded.
        if isinstance(payload, dict):
            payload = dict(payload)
            payload["rows"] = [
                row for row in payload["rows"]
                if str(row.get("production_no") or "").startswith(f"{prefix}-")
            ]
        else:
            payload = [
                row for row in payload
                if str(row.get("production_no") or "").startswith(f"{prefix}-")
            ]
    return _stable(payload, tokens, prefix=prefix)


@contextmanager
def _counted_statements(engine):
    statements: list[str] = []

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)


def _first(tokens, group, token):
    return next(key for key, value in tokens[group].items() if value == token)


@pytest.fixture(scope="module")
def golden_scenarios(accessory_request_sessions):
    sessions, engine = accessory_request_sessions
    tokens = _seed(sessions, prefix="GOLD", orders=SMALL_ORDERS)
    scenarios = {
        "default": {},
        "paged": {"page": 2, "page_size": 4},
        "include_complete": {"include_complete": True},
        "search_sku": {"q": "btn-red"},
        "search_model_code_dash": {"q": "mdl-01"},
        "search_item_name": {"q": "tape white"},
        "search_unit_only_on_manual_issue": {"q": "set"},
        "single_order": {"production_order_id": _first(tokens, "production_order", "po-0")},
        "model_filter": {"model_id": _first(tokens, "model", "model-MDL-01")},
    }
    measured = {}
    for name, kwargs in scenarios.items():
        with _counted_statements(engine) as statements:
            payload = _queue(sessions, tokens, prefix="GOLD", include_total=True, **kwargs)
        measured[name] = (payload, len(statements))
    return tokens, measured


def test_queue_payload_matches_pre_fix_capture(golden_scenarios):
    """Every scenario must return the payload the unoptimized queue returned."""
    _, measured = golden_scenarios
    expected = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert sorted(measured) == sorted(expected), "scenario list drifted from the capture"
    for name, (payload, _) in measured.items():
        assert payload == expected[name], f"payload changed for scenario {name!r}"


def test_queue_statement_count_does_not_grow_with_candidates(accessory_request_sessions):
    """Paging a 10x larger candidate set must not cost 10x the statements."""
    sessions, engine = accessory_request_sessions
    counts = {}
    totals = {}
    for name, orders in (("small", SMALL_ORDERS), ("large", LARGE_ORDERS)):
        prefix = f"GROW{name.upper()}"
        tokens = _seed(sessions, prefix=prefix, orders=orders)
        with _counted_statements(engine) as statements:
            # Every fixture in this module shares the schema, so the growth run
            # looks at the whole candidate set; only its cost is under test.
            payload = _queue(
                sessions,
                tokens,
                prefix=prefix,
                page=1,
                page_size=5,
                include_total=True,
                only_prefix=False,
            )
        assert len(payload["rows"]) == 5
        counts[name] = len(statements)
        totals[name] = payload["total"]
    assert counts["large"] <= counts["small"] * 2 + 4, counts
    # The exact total is still a set-wide count, not a page length.
    assert totals["large"] > totals["small"] > 5


def test_queue_keeps_units_aliases_and_totals(accessory_request_sessions):
    """Unit aliases, label-only manual issues and the exact total stay intact."""
    sessions, _ = accessory_request_sessions
    tokens = _seed(sessions, prefix="UNIT", orders=SMALL_ORDERS)
    payload = _queue(sessions, tokens, prefix="UNIT", include_total=True)
    # The total counts the whole candidate set, not the page that came back.
    # The exact value for an isolated fixture is pinned by the golden capture.
    assert payload["total"] >= len(payload["rows"]) > 0
    by_key = {
        (row["production_order_id"], row["item_sku"], row["unit"]): row
        for row in payload["rows"]
    }

    # Metre and piece requirements stay in their own units.
    assert by_key[("po-0", "TAPE-WHT", "m")]["unit"] == "m"
    assert by_key[("po-0", "ZIP-BLK", "pcs")]["unit"] == "pcs"

    tape = by_key[("po-0", "TAPE-WHT", "m")]
    # 0.5 * 10 required, 1.5 issued through the work order, and 8 m in stock
    # less the 0.5 m reserved against the item: partial, not shortage.
    assert tape["required_quantity"] == 5.0
    assert tape["issued_quantity"] == 1.5
    assert tape["remaining_quantity"] == 3.5
    assert tape["available_quantity"] == 6.0
    assert tape["shortage"] == 0.0
    assert tape["status"] == "partial"

    # A fully issued row is hidden by default and returns with include_complete.
    complete = _queue(sessions, tokens, prefix="UNIT", include_complete=True, include_total=True)
    ready = [
        row for row in complete["rows"]
        if row["status"] == "ready" and row["production_order_id"] == "po-0"
    ]
    assert [row["item_sku"] for row in ready] == ["BTN-RED"]
    assert ready[0]["remaining_quantity"] == 0.0
    assert complete["total"] > payload["total"]

    # The label-only manual issue in metres counts against the metre line; the
    # same label issued in "set" is not counted against the piece line.
    button = by_key[("po-1", "BTN-RED", "pcs")]
    assert button["required_quantity"] == 12.0
    assert button["issued_quantity"] == 2.0
    assert button["remaining_quantity"] == 10.0
    # The plan registered the label-only metre issue under both its stored label
    # and its name, and a stored label of "" falls back to the name, so the
    # single recorded metre reaches this line twice. That is what the
    # unoptimized queue reported, so the set-based queue reports it too.
    alias_tape = by_key[("po-1", "TAPE-WHT", "m")]
    assert alias_tape["issued_quantity"] == 2.0
    assert alias_tape["remaining_quantity"] == 1.0


def test_queue_keeps_return_out_of_remaining(accessory_request_sessions):
    """A recorded return shrinks the allowance, never the queued remainder."""
    sessions, _ = accessory_request_sessions
    tokens = _seed(sessions, prefix="RET", orders=SMALL_ORDERS)
    payload = _queue(sessions, tokens, prefix="RET", include_total=True)
    returned = [
        row for row in payload["rows"]
        if row["production_order_id"] == "po-2" and row["item_sku"] == "BTN-RED"
    ]
    assert len(returned) == 1
    # 1 pcs returned against a 7 pcs requirement leaves the queue remainder whole.
    assert returned[0]["required_quantity"] == 7.0
    assert returned[0]["issued_quantity"] == 0.0
    assert returned[0]["remaining_quantity"] == 7.0


def test_queue_keeps_half_step_remaining_rounded_half_to_even(accessory_request_sessions):
    """The ten-piece order line lands two requirements on a rounding half step.

    Python rounds the exact binary value half to even, so 0.78125 becomes
    0.7812 and 3.90625 becomes 3.9062. PostgreSQL's round(numeric, 4) rounds the
    same values away from zero, which would overstate what is still owed.
    """
    sessions, _ = accessory_request_sessions
    tokens = _seed(sessions, prefix="HALF", orders=SMALL_ORDERS)
    payload = _queue(sessions, tokens, prefix="HALF", include_total=True)
    by_key = {
        (row["production_order_id"], row["item_sku"]): row
        for row in payload["rows"]
    }
    # po-0 has an order line of 10 pieces; po-2 has none and plans 7.
    assert by_key[("po-0", "LBL-RED")]["required_quantity"] == 0.78125
    assert by_key[("po-0", "LBL-RED")]["remaining_quantity"] == 0.7812
    assert by_key[("po-0", "TIE-CLN")]["required_quantity"] == 3.90625
    assert by_key[("po-0", "TIE-CLN")]["remaining_quantity"] == 3.9062
    assert by_key[("po-2", "LBL-RED")]["remaining_quantity"] == 0.5469
    assert by_key[("po-2", "TIE-CLN")]["remaining_quantity"] == 2.7344
    # A fifth decimal that is not a half step rounds normally.
    assert by_key[("po-0", "TAG-BLU")]["required_quantity"] == 3.56631
    assert by_key[("po-0", "TAG-BLU")]["remaining_quantity"] == 3.5663


def test_queue_orders_rows_by_status_then_order(accessory_request_sessions):
    """Shortage first, then partial, then ready; ties keep their seeded order."""
    sessions, _ = accessory_request_sessions
    tokens = _seed(sessions, prefix="ORD", orders=SMALL_ORDERS)
    payload = _queue(sessions, tokens, prefix="ORD", include_complete=True, include_total=True)
    rank = {"shortage": 0, "partial": 1, "ready": 2}
    keys = [
        (rank[row["status"]], row["production_order_id"], row["item_sku"], row["unit"])
        for row in payload["rows"]
    ]
    assert keys == sorted(keys)
