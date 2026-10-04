"""PERF03: reservation planning must not re-read stock, claims and candidates per row.

`reservation_plan_for_production_order` walked its requirement rows and asked the
database the same questions over and over: a candidate-batch query per row, one
`reserved_stock_for_batch` aggregate per candidate batch inside that loop, and a
separate current/available/reserved pair per row. Reads therefore grew with
rows *times* candidates, and the two coverage maps read the same reservations
rows twice.

The invariant here is deliberately *not* a hardcoded statement total. What is
asserted is that the three read classes this row is about - candidate reads,
claim reads against `material_reservations`, and batchless-ledger reads - do not
scale with the number of requirement rows, measured on a real PostgreSQL server
because SQLite does not report a row count for SELECT.

Four business rules are compared against a transcription of the
pre-fix planner, adjusted only for the explicit D4a archive eligibility fix (`_pre_fix_plan` below), which is the strongest available
oracle: it calls the same untouched leaf helpers (`current_stock_for_item`,
`reserved_stock_for_batch`, `_bom_requirement_rows`, ...) and the same SQL, so
only the orchestration differs.

* FIFO - candidates are still consumed oldest `received_date` first, `id`
  breaking ties, and the two plans must offer the same batches in the same
  order;
* eligibility - a pinned requirement still sees only its own batch and only
  when that batch belongs to the item; archived batches are now excluded
  explicitly under D4a, while QC eligibility and positive-quantity checks
  retain their existing rules;
* units - the candidate unit test is still a stripped string comparison and the
  suggested batch still echoes the batch's own raw unit string;
* coverage - consumed + open arithmetic per status, summed per item/unit and per
  item/unit/batch, must be bit-identical, not approximately equal.

PostgreSQL cases skip loudly when STABILIZATION_POSTGRES_URL is unset.
"""

import os
import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import (
    Item,
    MaterialReservation,
    Model,
    ModelBOM,
    ProductionOrder,
    ProductionOrderItem,
    ProductionOrderMaterial,
    StockBatch,
    StockMovement,
    Warehouse,
)
from app.services.inventory import (
    ACTIVE_RESERVATION_STATUSES,
    EPSILON,
    RESERVABLE_CATEGORIES,
    _bom_requirement_rows,
    _covered_reservation_quantity,
    _model_label_fields,
    available_stock_for_batch,
    available_stock_for_item,
    current_stock_for_batch,
    current_stock_for_item,
    reservation_plan_for_production_order,
    reserved_stock_for_batch,
    reserved_stock_for_item,
)

# The three read classes this row is about. `items` is deliberately absent: a
# plan row never reads a candidate's item, and ST03's warehouse-scoped ledger
# aggregation is not on this path.
CANDIDATE_TABLE = "stock_batches"
CLAIM_TABLE = "material_reservations"
MOVEMENT_TABLE = "stock_movements"
TRACKED_TABLES = (CANDIDATE_TABLE, CLAIM_TABLE, MOVEMENT_TABLE)
_TABLE_READ = re.compile(
    r"\b(?:from|join)\s+(" + "|".join(TRACKED_TABLES) + r")\b",
    re.IGNORECASE,
)

SMALL_ITEMS = 4
LARGE_ITEMS = 16
# Every item is planned on two units and owns one batch population, so each
# item contributes two requirement rows over a single set of candidates.
MAIN_BATCHES_PER_ITEM = 5
SECOND_UNIT_BATCHES_PER_ITEM = 1
CANDIDATES_PER_ITEM = MAIN_BATCHES_PER_ITEM + SECOND_UNIT_BATCHES_PER_ITEM
BATCH_QUANTITY = 5
NEED_PER_ITEM = 100  # larger than every item's stock, so all candidates are walked
# Correct batching leaves each read class constant, so a 4x wider plan must stay
# far inside a 2x + constant envelope. Unfixed code scales 1:1 with row count.
GROWTH_SLACK = 2
GROWTH_CONSTANT = 4


def _read_class(statement: str) -> str | None:
    if not statement.lstrip().upper().startswith("SELECT"):
        return None
    match = _TABLE_READ.search(statement)
    return match.group(1).lower() if match else None


class ReadCounter:
    """Count statements and rows fetched on one engine for the life of a block.

    `cursor.rowcount` is read in `after_cursor_execute` because psycopg2 does not
    expose it earlier, and it is meaningful for SELECT on PostgreSQL, which is
    why these cases require a real server.
    """

    def __init__(self, engine):
        self.engine = engine
        self.pairs: list[tuple[str, int]] = []
        self._pending: list[str] = []
        # Keep one bound-method object each: event.remove matches on identity.
        self._on_execute = self._record
        self._record_rows = self._record_result

    def _record(self, conn, cursor, statement, parameters, context, executemany):
        self._pending.append(statement)

    def _record_result(self, conn, cursor, statement, parameters, context, executemany):
        # Paired here rather than from two independent lists: a statement that
        # raises never fires `after_cursor_execute`, which would shift the two
        # lists against each other.
        try:
            rows = int(cursor.rowcount or 0)
        except Exception:  # pragma: no cover - driver without rowcount
            rows = 0
        self.pairs.append((self._pending.pop() if self._pending else statement, rows))

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._on_execute)
        event.listen(self.engine, "after_cursor_execute", self._record_result)
        return self

    def __exit__(self, *exc):
        event.remove(self.engine, "before_cursor_execute", self._on_execute)
        event.remove(self.engine, "after_cursor_execute", self._record_result)
        return False

    @property
    def statements(self) -> list[str]:
        return [statement for statement, _rows in self.pairs]

    def _count(self, table: str) -> int:
        return sum(1 for statement, _rows in self.pairs if _read_class(statement) == table)

    @property
    def candidate_reads(self) -> int:
        """Candidate-list reads on `stock_batches`.

        Identified by the statement shape rather than by table alone: the BOM
        query joins `stock_batches` for each BOM line's pinned batch, and the
        per-item balance read is grouped, so neither is a candidate read.
        """
        return sum(
            1
            for statement, _rows in self.pairs
            if _read_class(statement) == CANDIDATE_TABLE
            and "order by" in statement.lower()
            and "group by" not in statement.lower()
        )

    @property
    def claim_reads(self) -> int:
        return self._count(CLAIM_TABLE)

    @property
    def movement_reads(self) -> int:
        return self._count(MOVEMENT_TABLE)

    @property
    def candidate_rows(self) -> int:
        """Rows returned by the candidate-list read on `stock_batches`.

        Distinguished from the per-item balance aggregate on the same table by
        the statement itself, not by a row-count threshold: the balance query is
        a GROUP BY and legitimately returns one row per item.
        """
        return sum(
            rows
            for statement, rows in self.pairs
            if _read_class(statement) == CANDIDATE_TABLE
            and "order by" in statement.lower()
            and "group by" not in statement.lower()
        )

    @property
    def total_statements(self) -> int:
        return len(self.pairs)

    @property
    def rows_fetched(self) -> int:
        return sum(rows for _statement, rows in self.pairs)


# --------------------------------------------------------------------------
# Pre-fix oracle: a verbatim transcription of the planner as it read the
# database before PERF03, built on the leaf helpers this row does not touch.
# --------------------------------------------------------------------------


def _pre_fix_coverage_by_item_unit(db, production_order_id):
    reservations = (
        db.query(MaterialReservation)
        .filter(MaterialReservation.production_order_id == production_order_id)
        .all()
    )
    coverage = {}
    for reservation in reservations:
        key = (int(reservation.item_id), str(reservation.unit or ""))
        coverage[key] = coverage.get(key, 0.0) + _covered_reservation_quantity(reservation)
    return coverage


def _pre_fix_coverage_by_item_unit_batch(db, production_order_id):
    reservations = (
        db.query(MaterialReservation)
        .filter(MaterialReservation.production_order_id == production_order_id)
        .filter(MaterialReservation.stock_batch_id.isnot(None))
        .all()
    )
    coverage = {}
    for reservation in reservations:
        key = (int(reservation.item_id), str(reservation.unit or ""), int(reservation.stock_batch_id))
        coverage[key] = coverage.get(key, 0.0) + _covered_reservation_quantity(reservation)
    return coverage


def _pre_fix_suggest_batches(db, *, item_id, unit, quantity, stock_batch_id=None):
    left = max(0.0, float(quantity or 0))
    if left <= EPSILON:
        return []
    # Independent per-row oracle: only the documented D4a predicate changes.
    qry = db.query(StockBatch).filter(
        StockBatch.item_id == item_id, StockBatch.quantity > 0, StockBatch.archived_at.is_(None),
    )
    if stock_batch_id is not None:
        qry = qry.filter(StockBatch.id == stock_batch_id)
    batches = qry.order_by(StockBatch.received_date.asc(), StockBatch.id.asc()).all()
    out = []
    for batch in batches:
        if left <= EPSILON:
            break
        if str(batch.unit or "").strip() != str(unit or "").strip():
            continue
        reserved = reserved_stock_for_batch(db, int(batch.id))
        available = max(0.0, float(batch.quantity or 0) - reserved)
        if available <= EPSILON:
            continue
        suggested = min(left, available)
        out.append({
            "stock_batch_id": int(batch.id),
            "batch_no": batch.batch_no,
            "warehouse_id": int(batch.warehouse_id),
            "received_date": batch.received_date,
            "current_quantity": float(batch.quantity or 0),
            "reserved_quantity": reserved,
            "available_quantity": available,
            "suggested_quantity": suggested,
            "unit": batch.unit,
        })
        left -= suggested
    return out


def _pre_fix_plan(db, production_order_id, categories=None):
    """The pre-PERF03 planner with D4a archive exclusion for oracle comparison."""
    po = db.get(ProductionOrder, production_order_id)
    if not po:
        raise HTTPException(404, "Production order not found")

    model_code, model_name = _model_label_fields(db, po.model_id)
    coverage = _pre_fix_coverage_by_item_unit(db, int(po.id))
    batch_coverage = _pre_fix_coverage_by_item_unit_batch(db, int(po.id))
    rows = []
    for row in _bom_requirement_rows(db, po, categories or RESERVABLE_CATEGORIES):
        stock_batch_id = int(row["stock_batch_id"]) if row.get("stock_batch_id") else None
        if stock_batch_id is not None:
            coverage_key = (int(row["item_id"]), str(row["unit"]), stock_batch_id)
            already_reserved = float(batch_coverage.get(coverage_key, 0.0))
        else:
            coverage_key = (int(row["item_id"]), str(row["unit"]))
            already_reserved = float(coverage.get(coverage_key, 0.0))
        required = float(row["required_quantity"] or 0)
        remaining = max(0.0, required - already_reserved)
        if stock_batch_id is not None:
            current = current_stock_for_batch(db, stock_batch_id)
            available = available_stock_for_batch(db, stock_batch_id)
        else:
            current = current_stock_for_item(db, int(row["item_id"]))
            available = available_stock_for_item(db, int(row["item_id"]))
        shortage = max(0.0, remaining - max(0.0, available))
        suggested_batches = _pre_fix_suggest_batches(
            db,
            item_id=int(row["item_id"]),
            unit=str(row["unit"]),
            quantity=remaining,
            stock_batch_id=stock_batch_id,
        )
        if remaining <= EPSILON:
            status = "ready"
        elif shortage > EPSILON:
            status = "shortage"
        else:
            status = "partial"
        rows.append({
            **row,
            "required_quantity": required,
            "already_reserved_quantity": already_reserved,
            "remaining_to_reserve": remaining,
            "current_stock": current,
            "reserved_stock": reserved_stock_for_batch(db, stock_batch_id)
            if stock_batch_id is not None
            else reserved_stock_for_item(db, int(row["item_id"])),
            "available_stock": available,
            "shortage": shortage,
            "suggested_batches": suggested_batches,
            "status": status,
        })

    total_required = sum(float(row["required_quantity"] or 0) for row in rows)
    total_reserved = sum(float(row["already_reserved_quantity"] or 0) for row in rows)
    total_remaining = sum(float(row["remaining_to_reserve"] or 0) for row in rows)
    total_shortage = sum(float(row["shortage"] or 0) for row in rows)
    if not rows:
        readiness_status = "no_bom"
    elif total_remaining <= EPSILON:
        readiness_status = "ready"
    elif total_shortage > EPSILON:
        readiness_status = "shortage"
    else:
        readiness_status = "partial"

    return {
        "production_order_id": int(po.id),
        "production_no": po.production_no,
        "order_no": po.order_no,
        "sales_order_id": int(po.sales_order_id) if po.sales_order_id else None,
        "model_id": int(po.model_id),
        "model_code": model_code,
        "model_name": model_name,
        "planned_quantity": int(po.planned_quantity or 0),
        "status": readiness_status,
        "is_complete": total_remaining <= EPSILON,
        "warning": None if total_remaining <= EPSILON else "Material reservation is incomplete before cutting.",
        "summary": {
            "required_quantity": total_required,
            "already_reserved_quantity": total_reserved,
            "remaining_to_reserve": total_remaining,
            "shortage": total_shortage,
            "line_count": len(rows),
            "ready_line_count": sum(1 for row in rows if row["status"] == "ready"),
            "shortage_line_count": sum(1 for row in rows if row["status"] == "shortage"),
        },
        "rows": rows,
    }


# --------------------------------------------------------------------------
# PostgreSQL fixture
# --------------------------------------------------------------------------


def _table_closure(seeds):
    """`seeds` plus every table their foreign keys point at."""
    pending = list(seeds)
    seen: set = set()
    while pending:
        table = pending.pop()
        if table.name in seen:
            continue
        seen.add(table.name)
        for column in table.columns:
            for fk in column.foreign_keys:
                target = fk.column.table
                if target.name not in seen:
                    pending.append(target)
    return {t for t in Base.metadata.tables.values() if t.name in seen}


@pytest.fixture(scope="module")
def postgres_session_factory():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip(
            "Set STABILIZATION_POSTGRES_URL to run PERF03 reservation-plan read-growth "
            "coverage (SQLite reports no row count for SELECT)"
        )
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("PERF03 read-growth tests require a loopback PostgreSQL URL without connection overrides")
    schema = f"perf03_reservation_plan_{uuid4().hex}"
    engine = create_engine(
        url,
        connect_args={"options": f"-csearch_path={schema}"},
        pool_size=4,
        max_overflow=0,
    )
    assert engine.dialect.name == "postgresql"
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        tables = _table_closure([
            ProductionOrder.__table__,
            ProductionOrderItem.__table__,
            ProductionOrderMaterial.__table__,
            Model.__table__,
            ModelBOM.__table__,
            Item.__table__,
            Warehouse.__table__,
            StockBatch.__table__,
            StockMovement.__table__,
            MaterialReservation.__table__,
        ])
        Base.metadata.create_all(engine, tables=sorted(tables, key=lambda t: t.name))
        yield sessionmaker(bind=engine, expire_on_commit=False)
    finally:
        engine.dispose()
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


# --------------------------------------------------------------------------
# Fixture data
# --------------------------------------------------------------------------

BASE_DATE = datetime(2026, 3, 1, tzinfo=timezone.utc)


def _base_rows(session_factory, marker):
    """Shared catalog rows: one warehouse, one model, one user-free PO skeleton."""
    with session_factory.begin() as db:
        warehouse = Warehouse(name=f"PERF03-{marker}-wh", type="fabric_storage")
        model = Model(
            code=f"PERF03-{marker}",
            name=f"PERF03 model {marker}",
            catalog_scope="standard",
            status="approved",
            sam_minutes=10,
        )
        db.add_all([warehouse, model])
        db.flush()
        return {"warehouse_id": warehouse.id, "model_id": model.id}


def _new_item(db, marker, index, *, category="fabric", unit="kg"):
    item = Item(
        sku=f"PERF03-{marker}-{index}",
        name=f"PERF03 item {index}",
        category=category,
        unit=unit,
        default_cost=0,
        reorder_level=0,
        track_batch=True,
        is_active=True,
        composition_json=[],
    )
    db.add(item)
    db.flush()
    return item


def _new_batch(db, *, item_id, warehouse_id, marker, index, quantity, unit, day_offset,
               archived=False, qc_status="passed"):
    batch = StockBatch(
        item_id=item_id,
        batch_no=f"PERF03-{marker}-b{index}",
        quantity=quantity,
        unit=unit,
        warehouse_id=warehouse_id,
        received_date=BASE_DATE + timedelta(days=day_offset),
        qc_status=qc_status,
        archived_at=(BASE_DATE + timedelta(days=90)) if archived else None,
    )
    db.add(batch)
    db.flush()
    return batch


def _new_order(db, *, model_id, planned_quantity=10):
    order = ProductionOrder(
        production_no=f"PERF03-{uuid4().hex[:10]}",
        production_type="branded_stock",
        source_type="standard",
        model_id=model_id,
        status="planned",
        planned_quantity=planned_quantity,
    )
    db.add(order)
    db.flush()
    return order


def _reserve(db, *, order, item_id, unit, reserved, consumed=0, released=0, status="reserved",
             batch_id=None, seq=0):
    row = MaterialReservation(
        reservation_no=f"PERF03-{uuid4().hex[:14]}",
        production_order_id=order.id,
        item_id=item_id,
        stock_batch_id=batch_id,
        warehouse_id=None,
        reserved_quantity=reserved,
        consumed_quantity=consumed,
        released_quantity=released,
        unit=unit,
        status=status,
        reservation_type="material",
        source="manual",
    )
    db.add(row)
    db.flush()
    return row


def _seed_growth_case(session_factory, marker, item_count):
    """A wide plan: two requirement rows per item over one candidate population.

    Every item is planned on two different units, so every item produces two
    requirement rows that share one set of batches. Each batch holds a small
    quantity against a much larger need, so the planner walks all of them, and
    the oldest batch of each item already carries a competing active claim.
    """
    catalog = _base_rows(session_factory, marker)
    with session_factory.begin() as db:
        order = _new_order(db, model_id=catalog["model_id"])
        item_ids = []
        for index in range(item_count):
            main_unit = ("kg", "m", "pcs")[index % 3]
            second_unit = ("pcs", "kg", "m")[index % 3]
            item = _new_item(db, marker, index, category="fabric", unit=main_unit)
            for bom_unit in (main_unit, second_unit):
                db.add(ModelBOM(
                    model_id=catalog["model_id"],
                    item_id=item.id,
                    material_name=f"PERF03 bom {index}",
                    material_role="main",
                    quantity_per_piece=1,
                    unit=bom_unit,
                    waste_percent=0,
                ))
            # Deliberately inserted newest-first so FIFO cannot be satisfied by
            # insertion order; only received_date decides.
            for position in range(MAIN_BATCHES_PER_ITEM):
                _new_batch(
                    db, item_id=item.id, warehouse_id=catalog["warehouse_id"], marker=f"{marker}-{index}",
                    index=position, quantity=BATCH_QUANTITY, unit=main_unit,
                    day_offset=MAIN_BATCHES_PER_ITEM - position,
                )
            _new_batch(
                db, item_id=item.id, warehouse_id=catalog["warehouse_id"], marker=f"{marker}-{index}",
                index=90, quantity=BATCH_QUANTITY, unit=second_unit, day_offset=1,
            )
            # A batchless ledger movement so the movement aggregate has data.
            db.add(StockMovement(
                movement_type="produce",
                item_id=item.id,
                batch_id=None,
                quantity=2,
                unit=main_unit,
            ))
            _reserve(db, order=order, item_id=item.id, unit=main_unit, reserved=3, status="reserved")
            item_ids.append(item.id)
        db.commit()
        return {"order_id": order.id, "item_ids": item_ids}


def _seed_tricky_case(session_factory, marker="tricky"):
    """One hand-built plan covering every rule this row could plausibly break.

    Includes: two BOM lines for the same item in different units; a BOM line
    whose unit only matches after stripping; a batch whose unit string carries
    padding; an archived Eco-custody batch that still holds quantity; a QC-hold
    batch; a depleted batch; a unit-mismatched batch; a requirement pinned to a
    batch; a requirement pinned to a batch belonging to another item; a pinned
    batch with no quantity left; and one reservation per status.
    """
    catalog = _base_rows(session_factory, marker)
    with session_factory.begin() as db:
        order = _new_order(db, model_id=catalog["model_id"])
        wh = catalog["warehouse_id"]
        model_id = catalog["model_id"]

        fabric = _new_item(db, marker, 0, category="fabric", unit="kg")
        trim = _new_item(db, marker, 1, category="fabric", unit="m")
        button = _new_item(db, marker, 2, category="accessory", unit="pcs")

        # FIFO ladder for the fabric item: inserted newest first, plus the
        # awkward cases that must still be filtered exactly as before.
        fabric_archived = _new_batch(
            db, item_id=fabric.id, warehouse_id=wh, marker=f"{marker}-0", index=90,
            quantity=7, unit="kg", day_offset=1, archived=True,
        )
        fabric_oldest = _new_batch(
            db, item_id=fabric.id, warehouse_id=wh, marker=f"{marker}-0", index=91,
            quantity=6, unit="kg", day_offset=2,
        )
        fabric_padded_unit = _new_batch(
            db, item_id=fabric.id, warehouse_id=wh, marker=f"{marker}-0", index=92,
            quantity=4, unit=" kg", day_offset=3,
        )
        fabric_qc_hold = _new_batch(
            db, item_id=fabric.id, warehouse_id=wh, marker=f"{marker}-0", index=93,
            quantity=5, unit="kg", day_offset=4, qc_status="hold",
        )
        fabric_depleted = _new_batch(
            db, item_id=fabric.id, warehouse_id=wh, marker=f"{marker}-0", index=94,
            quantity=0, unit="kg", day_offset=5,
        )
        fabric_wrong_unit = _new_batch(
            db, item_id=fabric.id, warehouse_id=wh, marker=f"{marker}-0", index=95,
            quantity=50, unit="pcs", day_offset=6,
        )
        fabric_newest = _new_batch(
            db, item_id=fabric.id, warehouse_id=wh, marker=f"{marker}-0", index=96,
            quantity=8, unit="kg", day_offset=7,
        )

        # Trim item: the requirement's unit only matches after stripping, and
        # the pinned batches live here.
        trim_pinned = _new_batch(
            db, item_id=trim.id, warehouse_id=wh, marker=f"{marker}-1", index=80,
            quantity=9, unit="m", day_offset=4,
        )
        trim_depleted = _new_batch(
            db, item_id=trim.id, warehouse_id=wh, marker=f"{marker}-1", index=81,
            quantity=0, unit="m", day_offset=2,
        )
        trim_other = _new_batch(
            db, item_id=trim.id, warehouse_id=wh, marker=f"{marker}-1", index=82,
            quantity=11, unit="m", day_offset=6,
        )

        button_batches = [
            _new_batch(
                db, item_id=button.id, warehouse_id=wh, marker=f"{marker}-2", index=70 + position,
                quantity=3, unit="pcs", day_offset=5 - position,
            )
            for position in range(3)
        ]

        db.add_all([
            # The same item planned on two different units produces two
            # requirement rows over one shared candidate population - the case
            # that made the per-row re-read visible in the first place. The
            # "pcs" row must be served by the pcs batch and never by the kg
            # batches, and vice versa.
            ModelBOM(model_id=model_id, item_id=fabric.id, material_name="fabric kg",
                     material_role="main", quantity_per_piece=4, unit="kg", waste_percent=0),
            ModelBOM(model_id=model_id, item_id=fabric.id, material_name="fabric pcs",
                     material_role="main", quantity_per_piece=1, unit="pcs", waste_percent=0),
            # Pinned to a batch of its own item, to a batch of another item, and
            # to a batch that no longer holds quantity.
            ModelBOM(model_id=model_id, item_id=trim.id, material_name="trim pinned",
                     material_role="main", quantity_per_piece=3, unit=" m ", waste_percent=0,
                     stock_batch_id=trim_pinned.id),
            ModelBOM(model_id=model_id, item_id=trim.id, material_name="trim foreign pin",
                     material_role="main", quantity_per_piece=1, unit="m", waste_percent=0,
                     stock_batch_id=fabric_oldest.id),
            ModelBOM(model_id=model_id, item_id=trim.id, material_name="trim depleted pin",
                     material_role="main", quantity_per_piece=1, unit="m", waste_percent=0,
                     stock_batch_id=trim_depleted.id),
            ModelBOM(model_id=model_id, item_id=button.id, material_name="buttons",
                     material_role="trim", quantity_per_piece=2, unit="pcs", waste_percent=0),
        ])
        db.flush()

        # One reservation per status, on the same item/unit/batch so the coverage
        # arithmetic is summed across competing claims.
        _reserve(db, order=order, item_id=fabric.id, unit="kg", reserved=10, batch_id=fabric_oldest.id,
                 status="reserved")
        _reserve(db, order=order, item_id=fabric.id, unit="kg", reserved=8, consumed=3,
                 batch_id=fabric_oldest.id, status="partially_consumed")
        _reserve(db, order=order, item_id=fabric.id, unit="kg", reserved=5, consumed=5,
                 batch_id=fabric_oldest.id, status="consumed")
        _reserve(db, order=order, item_id=fabric.id, unit="kg", reserved=7, released=7,
                 batch_id=fabric_oldest.id, status="released")
        _reserve(db, order=order, item_id=fabric.id, unit="kg", reserved=9,
                 batch_id=fabric_oldest.id, status="cancelled")
        # An unbatched claim on the same item/unit: it must not leak into the
        # item/unit/batch map, and it must count in the item/unit map.
        _reserve(db, order=order, item_id=fabric.id, unit="kg", reserved=4, status="reserved")
        # A claim whose unit string is merely padded. The coverage key is the raw
        # stored unit, so it must not be folded into the "kg" key.
        _reserve(db, order=order, item_id=fabric.id, unit="  kg  ", reserved=6, batch_id=fabric_newest.id,
                 status="reserved")
        # A competing active claim on a trim batch that is not pinned.
        _reserve(db, order=order, item_id=trim.id, unit="m", reserved=2, batch_id=trim_other.id,
                 status="reserved")
        # Batchless ledger movements, so the item balance is not just the batch sum.
        db.add(StockMovement(movement_type="adjustment", item_id=fabric.id, batch_id=None,
                             quantity=4, unit="kg"))
        db.add(StockMovement(movement_type="waste", item_id=fabric.id, batch_id=None,
                             quantity=1, unit="kg"))
        db.commit()
        return {
            "order_id": order.id,
            "fabric_id": fabric.id,
            "trim_id": trim.id,
            "button_id": button.id,
            "fabric_archived": fabric_archived.id,
            "fabric_oldest": fabric_oldest.id,
            "fabric_padded_unit": fabric_padded_unit.id,
            "fabric_qc_hold": fabric_qc_hold.id,
            "fabric_depleted": fabric_depleted.id,
            "fabric_wrong_unit": fabric_wrong_unit.id,
            "fabric_newest": fabric_newest.id,
            "trim_pinned": trim_pinned.id,
            "trim_depleted": trim_depleted.id,
            "trim_other": trim_other.id,
            "button_batches": [b.id for b in button_batches],
        }


@pytest.fixture
def tricky_case(postgres_session_factory):
    """A freshly seeded tricky plan per test, so markers stay unique."""
    return _seed_tricky_case(postgres_session_factory, marker=f"tricky-{uuid4().hex[:6]}")


def _row_for(plan, *, item_id, unit, stock_batch_id=None):
    for row in plan["rows"]:
        if int(row["item_id"]) != int(item_id) or str(row["unit"]) != str(unit):
            continue
        if (row.get("stock_batch_id") or None) == (stock_batch_id or None):
            return row
    raise AssertionError(f"no plan row for item={item_id} unit={unit!r} batch={stock_batch_id}")


# --------------------------------------------------------------------------
# Oracle equivalence: FIFO, eligibility, units, coverage
# --------------------------------------------------------------------------


def test_plan_matches_pre_fix_oracle_over_tricky_candidates(tricky_case, postgres_session_factory):
    """The whole payload, not a summary, must equal the pre-fix planner."""
    case = tricky_case
    with postgres_session_factory() as db:
        expected = _pre_fix_plan(db, case["order_id"])
        actual = reservation_plan_for_production_order(db, case["order_id"])
    assert actual == expected
    assert len(actual["rows"]) == 6

    with postgres_session_factory() as db:
        narrowed = reservation_plan_for_production_order(db, case["order_id"], categories=("accessory",))
        narrowed_expected = _pre_fix_plan(db, case["order_id"], categories=("accessory",))
    assert narrowed == narrowed_expected
    assert [r["item_id"] for r in narrowed["rows"]] == [case["button_id"]]


def test_fifo_order_of_candidates_is_preserved(tricky_case, postgres_session_factory):
    """Oldest receipt first, id breaking ties, unaffected by insert order."""
    case = tricky_case
    with postgres_session_factory() as db:
        plan = reservation_plan_for_production_order(db, case["order_id"])
    row = _row_for(plan, item_id=case["fabric_id"], unit="kg")
    offered = [b["stock_batch_id"] for b in row["suggested_batches"]]

    # Eligible receipt order is day 3, 4, 7 (day 1 is archived and day 2 fully claimed)
    # (day 5 is depleted, day 6 is the pcs batch). Batches were inserted newest
    # first, so insertion order would give the reverse of the first three.
    assert offered == [
        case["fabric_padded_unit"],   # day 3 - unit matches only after stripping
        case["fabric_qc_hold"],       # day 4 - QC hold, still a candidate
        case["fabric_newest"],        # day 7 - backfills the archived batch
    ]
    quantities = [b["suggested_quantity"] for b in row["suggested_batches"]]
    # Archived day 1 and fully claimed day 2 are skipped.
    assert quantities == [4.0, 5.0, 2.0]  # 13 needed; only 11 eligible, spread FIFO


def test_fifo_ties_on_received_date_break_on_batch_id(postgres_session_factory):
    """Same receipt date: the lower id must be offered first."""
    catalog = _base_rows(postgres_session_factory, f"fifo-tie-{uuid4().hex[:6]}")
    with postgres_session_factory.begin() as db:
        order = _new_order(db, model_id=catalog["model_id"])
        item = _new_item(db, "fifo-tie", 0, category="fabric", unit="kg")
        db.add(ModelBOM(model_id=catalog["model_id"], item_id=item.id, material_name="tie",
                        material_role="main", quantity_per_piece=20, unit="kg", waste_percent=0))
        db.flush()
        # Inserted in descending id order, all on the same receipt date.
        ids = [
            _new_batch(db, item_id=item.id, warehouse_id=catalog["warehouse_id"],
                       marker="fifo-tie", index=100 - position, quantity=4, unit="kg",
                       day_offset=0).id
            for position in range(4)
        ]
        db.commit()
        expected_first = sorted(ids)
        item_id = item.id
        order_id = order.id
    with postgres_session_factory() as db:
        row = _row_for(reservation_plan_for_production_order(db, order_id), item_id=item_id, unit="kg")
    assert [b["stock_batch_id"] for b in row["suggested_batches"]] == expected_first


def test_archive_exclusion_preserves_other_eligibility_rules(tricky_case, postgres_session_factory):
    """D4a excludes archived stock; QC policy and other checks stay unchanged."""
    case = tricky_case
    with postgres_session_factory() as db:
        plan = reservation_plan_for_production_order(db, case["order_id"])
    row = _row_for(plan, item_id=case["fabric_id"], unit="kg")
    offered = {b["stock_batch_id"] for b in row["suggested_batches"]}
    # Archived Eco custody is ineligible; QC policy still awaits D4b.
    assert case["fabric_archived"] not in offered
    assert case["fabric_qc_hold"] in offered
    # Still excluded, for the same reasons as before: no quantity, wrong unit,
    # or fully claimed.
    assert case["fabric_depleted"] not in offered      # quantity == 0
    assert case["fabric_wrong_unit"] not in offered    # unit mismatch
    assert case["fabric_oldest"] not in offered        # 6 on hand, 15 already claimed
    assert offered == {
        case["fabric_padded_unit"],
        case["fabric_qc_hold"],
        case["fabric_newest"],
    }


def test_pinned_requirement_only_sees_its_own_batch(tricky_case, postgres_session_factory):
    """A pinned row offers that batch only - and nothing if it cannot serve."""
    case = tricky_case
    with postgres_session_factory() as db:
        plan = reservation_plan_for_production_order(db, case["order_id"])

    pinned = _row_for(plan, item_id=case["trim_id"], unit="m", stock_batch_id=case["trim_pinned"])
    assert [b["stock_batch_id"] for b in pinned["suggested_batches"]] == [case["trim_pinned"]]
    assert pinned["current_stock"] == 9.0
    assert pinned["shortage"] == 21.0
    assert pinned["status"] == "shortage"

    # Pinned to a batch of another item: no candidates, same as before, but the
    # pinned batch is still read for its balance.
    foreign = _row_for(plan, item_id=case["trim_id"], unit="m", stock_batch_id=case["fabric_oldest"])
    assert foreign["suggested_batches"] == []
    assert foreign["current_stock"] == 6.0
    assert foreign["reserved_stock"] == 15.0
    assert foreign["available_stock"] == -9.0  # over-claimed, left unclamped
    assert foreign["status"] == "shortage"

    # Pinned to a depleted batch: still read for balance, but offers nothing.
    depleted = _row_for(plan, item_id=case["trim_id"], unit="m", stock_batch_id=case["trim_depleted"])
    assert depleted["suggested_batches"] == []
    assert depleted["current_stock"] == 0.0
    assert depleted["status"] == "shortage"


def test_pinned_requirement_for_a_missing_batch_still_raises_404(tricky_case, postgres_session_factory):
    """The exact-batch index must not swallow the pre-fix 404.

    The stale pointer is unreachable through the model layer - `model_bom` has a
    foreign key to the batch - so the constraint is dropped in this throwaway
    schema to reproduce the legacy dangling row the 404 guard exists for.
    """
    case = tricky_case
    with postgres_session_factory() as db:
        db.execute(text("ALTER TABLE model_bom DROP CONSTRAINT IF EXISTS model_bom_stock_batch_id_fkey"))
        db.commit()
    with postgres_session_factory() as db:
        order = db.get(ProductionOrder, case["order_id"])
        item = _new_item(db, "missing-pin", 0, category="fabric", unit="kg")
        db.add(ModelBOM(model_id=order.model_id, item_id=item.id, material_name="ghost",
                        material_role="main", quantity_per_piece=1, unit="kg", waste_percent=0,
                        stock_batch_id=987654321))
        db.commit()
        with pytest.raises(HTTPException) as current:
            reservation_plan_for_production_order(db, case["order_id"])
        with pytest.raises(HTTPException) as pre_fix:
            _pre_fix_plan(db, case["order_id"])
    assert current.value.status_code == 404
    assert pre_fix.value.status_code == 404


def test_units_are_neither_coerced_nor_converted(tricky_case, postgres_session_factory):
    """The candidate test stays a stripped string compare; units stay separate keys."""
    case = tricky_case
    with postgres_session_factory() as db:
        plan = reservation_plan_for_production_order(db, case["order_id"])

    kg_row = _row_for(plan, item_id=case["fabric_id"], unit="kg")
    pcs_row = _row_for(plan, item_id=case["fabric_id"], unit="pcs")

    # Two units on one item are two independent requirement rows, each needing
    # its own amount: 4 * 10 pieces and 1 * 10 pieces.
    assert kg_row["required_quantity"] == 40.0
    assert pcs_row["required_quantity"] == 10.0
    # Neither row is satisfied by the other's batches.
    assert {b["stock_batch_id"] for b in kg_row["suggested_batches"]}.isdisjoint(
        {b["stock_batch_id"] for b in pcs_row["suggested_batches"]})
    assert [b["stock_batch_id"] for b in pcs_row["suggested_batches"]] == [case["fabric_wrong_unit"]]

    # The padded batch unit matches "kg" only after stripping, and the raw batch
    # unit is reported unchanged rather than normalised.
    padded = next(b for b in kg_row["suggested_batches"] if b["stock_batch_id"] == case["fabric_padded_unit"])
    assert padded["unit"] == " kg"
    assert padded["current_quantity"] == 4.0

    # The item balance is unit-blind by design and stays that way: every batch of
    # the item counts, whatever its unit, plus the batchless ledger.
    assert kg_row["current_stock"] == pcs_row["current_stock"] == 83.0
    assert kg_row["reserved_stock"] == pcs_row["reserved_stock"] == 25.0


def test_coverage_arithmetic_is_identical_across_every_status(tricky_case, postgres_session_factory):
    """consumed + open per status, summed per item/unit and per item/unit/batch."""
    case = tricky_case
    with postgres_session_factory() as db:
        plan = reservation_plan_for_production_order(db, case["order_id"])
    kg_row = _row_for(plan, item_id=case["fabric_id"], unit="kg")

    # Per item/unit/batch on the pinned batch: reserved 10, partially_consumed
    # 3 + (8-3) = 8, consumed 5, released 0, cancelled 0.
    already = 10 + 8 + 5
    assert already == 23
    # Per item/unit adds the unbatched claim of 4; the padded-unit claim of 6 is
    # a different key and must not be folded in.
    assert kg_row["already_reserved_quantity"] == 27.0
    assert kg_row["remaining_to_reserve"] == 13.0
    assert kg_row["status"] == "partial"

    # Claimed totals use the open quantity of active statuses only:
    # 10 + (8-3) + 6 + 4, with consumed/released/cancelled excluded.
    assert kg_row["reserved_stock"] == 25.0
    assert kg_row["current_stock"] == 83.0  # 80 in batches + 4 produced - 1 waste
    assert kg_row["available_stock"] == 58.0
    assert kg_row["shortage"] == 0.0

    # An unbatched-only item's requirement sees no coverage at all.
    button_row = _row_for(plan, item_id=case["button_id"], unit="pcs")
    assert button_row["already_reserved_quantity"] == 0.0
    assert button_row["current_stock"] == 9.0
    assert button_row["shortage"] == 11.0
    assert button_row["status"] == "shortage"

    # active status list still drives the claim totals.
    assert ACTIVE_RESERVATION_STATUSES == ("reserved", "partially_consumed")


# --------------------------------------------------------------------------
# Read growth
# --------------------------------------------------------------------------


def _measure(session_factory, item_count, marker):
    case = _seed_growth_case(session_factory, marker, item_count)
    with session_factory() as db:
        with ReadCounter(db.get_bind()) as counter:
            plan = reservation_plan_for_production_order(db, case["order_id"])
    assert plan["summary"]["line_count"] >= item_count
    return counter


def test_candidate_claim_and_ledger_reads_do_not_scale_with_rows(postgres_session_factory):
    small = _measure(postgres_session_factory, SMALL_ITEMS, f"small-{uuid4().hex[:6]}")
    large = _measure(postgres_session_factory, LARGE_ITEMS, f"large-{uuid4().hex[:6]}")
    print(
        f"\nPERF03 plan reads: small({SMALL_ITEMS} items) candidates={small.candidate_reads}"
        f" claims={small.claim_reads} movements={small.movement_reads}"
        f" | large({LARGE_ITEMS} items) candidates={large.candidate_reads}"
        f" claims={large.claim_reads} movements={large.movement_reads}"
        f" | rows fetched small={small.rows_fetched} large={large.rows_fetched}"
        f" | statements small={small.total_statements} large={large.total_statements}"
    )
    for label, before, after in (
        ("candidate", small.candidate_reads, large.candidate_reads),
        ("claim", small.claim_reads, large.claim_reads),
        ("movement", small.movement_reads, large.movement_reads),
    ):
        assert after <= before * GROWTH_SLACK + GROWTH_CONSTANT, (
            f"{label} reads grew with requirement rows: "
            f"small({SMALL_ITEMS})={before} large({LARGE_ITEMS})={after}"
        )


def test_each_candidate_batch_is_fetched_once_not_once_per_row(postgres_session_factory):
    """Rows, not statements: a batch is read once per plan, not once per row.

    Total rows fetched legitimately grow with the number of items - every item
    owns its own candidates - so "rows must not scale" is the wrong invariant
    here. The exact invariant is that the candidate population is read *once*:
    the seeded batch count is known, and a re-read per requirement row would
    exceed it, because a quarter of the items here are planned on two units and
    therefore have two requirement rows over one candidate set.
    """
    small = _measure(postgres_session_factory, SMALL_ITEMS, f"rows-small-{uuid4().hex[:6]}")
    large = _measure(postgres_session_factory, LARGE_ITEMS, f"rows-large-{uuid4().hex[:6]}")
    small_candidates = SMALL_ITEMS * CANDIDATES_PER_ITEM
    large_candidates = LARGE_ITEMS * CANDIDATES_PER_ITEM
    print(
        f"\nPERF03 candidate rows fetched: small={small.candidate_rows} of {small_candidates} seeded"
        f" | large={large.candidate_rows} of {large_candidates} seeded"
        f" | total rows fetched small={small.rows_fetched} large={large.rows_fetched}"
    )
    assert small.candidate_rows == small_candidates
    assert large.candidate_rows == large_candidates


def test_archived_batches_are_not_suggested_for_unpinned_requirements(tricky_case, postgres_session_factory):
    with postgres_session_factory() as db:
        plan = reservation_plan_for_production_order(db, tricky_case["order_id"])
    row = _row_for(plan, item_id=tricky_case["fabric_id"], unit="kg")
    offered = {batch["stock_batch_id"] for batch in row["suggested_batches"]}
    assert tricky_case["fabric_archived"] not in offered
    # QC policy is still a separate decision: do not tighten it here.
    assert tricky_case["fabric_qc_hold"] in offered


def test_archived_pinned_batch_is_not_suggested(tricky_case, postgres_session_factory):
    with postgres_session_factory.begin() as db:
        db.get(StockBatch, tricky_case["trim_pinned"]).archived_at = BASE_DATE
        _reserve(db, order=db.get(ProductionOrder, tricky_case["order_id"]),
            item_id=tricky_case["trim_id"], unit="m", reserved=2,
            batch_id=tricky_case["trim_pinned"])
    with postgres_session_factory() as db:
        plan = reservation_plan_for_production_order(db, tricky_case["order_id"])
    row = _row_for(plan, item_id=tricky_case["trim_id"], unit="m", stock_batch_id=tricky_case["trim_pinned"])
    assert row["suggested_batches"] == []
    # The ledger balance is retained for traceability; archive eligibility is separate.
    assert row["current_stock"] == 9.0
    assert row["reserved_stock"] == 2.0
    assert row["available_stock"] == 7.0
