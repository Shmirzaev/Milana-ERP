"""PERF28: purchasing must not read item/supplier/warehouse rows per line.

Purchasing resolved every order line's item, supplier and warehouse reference
with its own ``db.get`` call, so the number of reference reads grew with the
number of lines. The invariant is not a hardcoded statement total - writes and
audit appends are genuinely per line - but that *reference reads* do not scale
with line count.

Three behaviors are protected and must not regress:

* unit costs keep rounding HALF_UP to four decimals before storage, and are
  compared here as ``Decimal`` text so a scale or exponent change is caught;
* a material repeated on several lines still resolves each line independently,
  and a line repeated inside one receipt keeps its preceding explicit price;
* audit-head finalization on PostgreSQL still produces one linked hash chain.

The PostgreSQL cases need a real server, so they skip loudly when
STABILIZATION_POSTGRES_URL is unset.
"""

import os
import re
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.costs import round_unit_cost
from app.db import session as session_module
from app.db.base import Base
from app.models import (
    AuditLog,
    IdempotencyRecord,
    Item,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseRequest,
    PurchaseRequestLine,
    StockBatch,
    StockMovement,
    Supplier,
    User,
    Warehouse,
)
from app.services.audit import verify_audit_hash_chain
from app.services.purchasing import (
    approve_purchase_request,
    create_purchase_order,
    create_purchase_request,
    receive_purchase_order,
)

# The three reference tables this row is about. Every other statement in a
# purchase write (order/line/batch/movement inserts, audit appends, number
# generation) is genuinely per line and is deliberately not counted.
REFERENCE_TABLES = ("items", "suppliers", "warehouses")
_REFERENCE_READ = re.compile(
    r"\b(?:from|join)\s+(" + "|".join(REFERENCE_TABLES) + r")\b",
    re.IGNORECASE,
)

SMALL_LINES = 3
LARGE_LINES = 25
# Correct batching leaves the reference reads constant, so a 8x larger payload
# must stay far inside a 2x + constant envelope. Unfixed code scales 1:1.
GROWTH_SLACK = 2
GROWTH_CONSTANT = 4


def _is_reference_read(statement: str) -> bool:
    if not statement.lstrip().upper().startswith("SELECT"):
        return False
    return _REFERENCE_READ.search(statement) is not None


class StatementCounter:
    """Count statements executed on one engine for the life of the block."""

    def __init__(self, engine):
        self.engine = engine
        self.statements: list[str] = []
        # Keep one bound-method object: event.remove matches on identity.
        self._on_execute = self._record

    def _record(self, conn, cursor, statement, parameters, context, executemany):
        self.statements.append(statement)

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._on_execute)
        return self

    def __exit__(self, *exc):
        event.remove(self.engine, "before_cursor_execute", self._on_execute)
        return False

    @property
    def reference_reads(self) -> int:
        return sum(1 for s in self.statements if _is_reference_read(s))

    @property
    def total(self) -> int:
        return len(self.statements)


def _new_user(db, marker):
    user = User(
        name=f"PERF28 {marker}",
        email=f"perf28-{marker}@example.invalid",
        password_hash="unused",
        factory_code="MIL",
        extra_permissions=[],
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def _seed_reference_rows(session_factory, marker, *, count):
    """Create `count` distinct items/suppliers/warehouses in their own session.

    Seeding through a separate session matters: an object already present in
    the session identity map is returned by ``db.get`` without any SQL, which
    would hide the per-line read this row is about.
    """
    with session_factory.begin() as db:
        items, suppliers, warehouses = [], [], []
        for index in range(count):
            item = Item(
                sku=f"PERF28-{marker}-{index}",
                name=f"PERF28 item {index}",
                category="fabric",
                unit="m",
            )
            supplier = Supplier(
                name=f"PERF28 supplier {marker} {index}",
                email=f"perf28-supplier-{marker}-{index}@example.invalid",
                phone=None,
            )
            warehouse = Warehouse(name=f"PERF28 warehouse {marker} {index}", type="fabric_storage")
            items.append(item)
            suppliers.append(supplier)
            warehouses.append(warehouse)
        db.add_all(items + suppliers + warehouses)
        db.flush()
        return {
            "items": [(item.id, item.sku) for item in items],
            "suppliers": [supplier.id for supplier in suppliers],
            "warehouses": [warehouse.id for warehouse in warehouses],
        }


def _receive_lines(reference, line_count):
    return [
        {
            "item_id": item_id,
            "ordered_quantity": 10,
            "warehouse_id": reference["warehouses"][index % len(reference["warehouses"])],
            "supplier_id": reference["suppliers"][index % len(reference["suppliers"])],
        }
        for index, (item_id, _sku) in enumerate(reference["items"][:line_count])
    ]


def _seed_sent_order(session_factory, reference, line_count, *, unit_cost=Decimal("1.5")):
    with session_factory.begin() as db:
        order = PurchaseOrder(po_no=f"PERF28-PO-{uuid4().hex}", status="sent")
        db.add(order)
        db.flush()
        lines = []
        for index, (item_id, _sku) in enumerate(reference["items"][:line_count]):
            line = PurchaseOrderLine(
                purchase_order_id=order.id,
                item_id=item_id,
                ordered_quantity=1000,
                received_quantity=0,
                unit="m",
                unit_cost=unit_cost,
                warehouse_id=reference["warehouses"][index % len(reference["warehouses"])],
                supplier_id=reference["suppliers"][index % len(reference["suppliers"])],
            )
            lines.append(line)
        db.add_all(lines)
        db.commit()
        return {
            "order_id": order.id,
            "line_ids": [line.id for line in lines],
            "item_ids": [line.item_id for line in lines],
        }


def _seed_approved_request(session_factory, reference, line_count):
    with session_factory.begin() as db:
        request = PurchaseRequest(
            request_no=f"PERF28-PR-{uuid4().hex}",
            status="approved",
            requested_by=None,
        )
        db.add(request)
        db.flush()
        lines = []
        for index, (item_id, _sku) in enumerate(reference["items"][:line_count]):
            line = PurchaseRequestLine(
                purchase_request_id=request.id,
                item_id=item_id,
                required_quantity=10,
                requested_quantity=10,
                unit="m",
                available_quantity=0,
                shortage_quantity=10,
                preferred_supplier_id=reference["suppliers"][index % len(reference["suppliers"])],
            )
            lines.append(line)
        db.add_all(lines)
        db.commit()
        return {"request_id": request.id, "line_ids": [line.id for line in lines]}


def _measure_receipt(session_factory, line_count, marker):
    """Receive `line_count` lines and report the reference reads it cost."""
    reference = _seed_reference_rows(session_factory, f"{marker}-{line_count}", count=line_count)
    order = _seed_sent_order(session_factory, reference, line_count)
    payload = {
        "lines": [
            {
                "purchase_order_line_id": order["line_ids"][index],
                "received_quantity": 5,
                "batch_no": f"PERF28-B-{marker}-{line_count}-{index}",
            }
            for index in range(line_count)
        ]
    }
    with session_factory() as db:
        with StatementCounter(db.get_bind()) as counter:
            user = _new_user(db, f"{marker}-{line_count}")
            receive_purchase_order(db, order_id=order["order_id"], data=payload, current=user)
            db.commit()
    return counter


def test_receive_reference_reads_do_not_scale_with_line_count():
    small = _measure_receipt(session_module.SessionLocal, SMALL_LINES, "small")
    large = _measure_receipt(session_module.SessionLocal, LARGE_LINES, "large")
    print(
        f"\nPERF28 receive reference reads: small({SMALL_LINES} lines)={small.reference_reads}"
        f" large({LARGE_LINES} lines)={large.reference_reads}"
        f" | total statements small={small.total} large={large.total}"
    )
    assert large.reference_reads <= small.reference_reads * GROWTH_SLACK + GROWTH_CONSTANT, (
        f"reference reads grew with line count: small={small.reference_reads} "
        f"large={large.reference_reads}"
    )


def _measure_create_order(session_factory, line_count, marker):
    reference = _seed_reference_rows(session_factory, f"co-{marker}-{line_count}", count=line_count)
    with session_factory() as db:
        with StatementCounter(db.get_bind()) as counter:
            user = _new_user(db, f"co-{marker}-{line_count}")
            create_purchase_order(
                db,
                data={
                    "supplier_id": reference["suppliers"][0],
                    "status": "sent",
                    "lines": _receive_lines(reference, line_count),
                },
                current=user,
            )
            db.commit()
    return counter


def test_create_order_reference_reads_do_not_scale_with_line_count():
    small = _measure_create_order(session_module.SessionLocal, SMALL_LINES, "small")
    large = _measure_create_order(session_module.SessionLocal, LARGE_LINES, "large")
    print(
        f"\nPERF28 create-order reference reads: small={small.reference_reads}"
        f" large={large.reference_reads} | total statements small={small.total} large={large.total}"
    )
    assert large.reference_reads <= small.reference_reads * GROWTH_SLACK + GROWTH_CONSTANT, (
        f"reference reads grew with line count: small={small.reference_reads} "
        f"large={large.reference_reads}"
    )


def _measure_create_request(session_factory, line_count, marker):
    reference = _seed_reference_rows(session_factory, f"cr-{marker}-{line_count}", count=line_count)
    payload = {
        "status": "draft",
        "lines": [
            {
                "item_id": item_id,
                "required_quantity": 10,
                "requested_quantity": 10,
                "preferred_supplier_id": reference["suppliers"][index % line_count],
            }
            for index, (item_id, _sku) in enumerate(reference["items"][:line_count])
        ],
    }
    with session_factory() as db:
        with StatementCounter(db.get_bind()) as counter:
            user = _new_user(db, f"cr-{marker}-{line_count}")
            create_purchase_request(db, data=payload, current=user)
            db.commit()
    return counter


def test_create_request_reference_reads_do_not_scale_with_line_count():
    small = _measure_create_request(session_module.SessionLocal, SMALL_LINES, "small")
    large = _measure_create_request(session_module.SessionLocal, LARGE_LINES, "large")
    print(
        f"\nPERF28 create-request reference reads: small={small.reference_reads}"
        f" large={large.reference_reads} | total statements small={small.total} large={large.total}"
    )
    assert large.reference_reads <= small.reference_reads * GROWTH_SLACK + GROWTH_CONSTANT, (
        f"reference reads grew with line count: small={small.reference_reads} "
        f"large={large.reference_reads}"
    )


def _measure_approve_request(session_factory, line_count, marker):
    reference = _seed_reference_rows(session_factory, f"ap-{marker}-{line_count}", count=line_count)
    seeded = _seed_approved_request(session_factory, reference, line_count)
    approval = {
        "lines": [
            {
                "purchase_request_line_id": seeded["line_ids"][index],
                "material_name": f"PERF28 material {index}",
                "photo_url": f"/files/perf28-{marker}-{index}.jpg",
                "preferred_supplier_id": reference["suppliers"][index % line_count],
            }
            for index in range(line_count)
        ]
    }
    with session_factory() as db:
        with StatementCounter(db.get_bind()) as counter:
            user = _new_user(db, f"ap-{marker}-{line_count}")
            approve_purchase_request(
                db, request_id=seeded["request_id"], data=approval, current=user
            )
            db.commit()
    return counter


def test_approve_request_reference_reads_do_not_scale_with_line_count():
    small = _measure_approve_request(session_module.SessionLocal, SMALL_LINES, "small")
    large = _measure_approve_request(session_module.SessionLocal, LARGE_LINES, "large")
    print(
        f"\nPERF28 approve-request reference reads: small={small.reference_reads}"
        f" large={large.reference_reads} | total statements small={small.total} large={large.total}"
    )
    assert large.reference_reads <= small.reference_reads * GROWTH_SLACK + GROWTH_CONSTANT, (
        f"reference reads grew with line count: small={small.reference_reads} "
        f"large={large.reference_reads}"
    )


def _stored_batch_costs(session_factory, po_no):
    with session_factory() as db:
        return [
            (row.batch_no, str(row.cost_per_unit), str(Decimal(str(row.quantity))))
            for row in db.query(StockBatch)
            .filter(StockBatch.internal_batch_no == po_no)
            .order_by(StockBatch.id)
            .all()
        ]


def test_rounded_costs_match_the_half_up_four_decimal_policy_as_decimal_text():
    """Storage must equal the policy output exactly, as Decimal text.

    Inputs are chosen so a float round-trip would show up: 1.23455 and
    0.00005 both round up at the fifth decimal, and 2.5 is exact.
    """
    marker = uuid4().hex[:8]
    costs = ["1.23455", "0.00005", "2.5", "99999999.99985", "0.12345"]
    reference = _seed_reference_rows(session_module.SessionLocal, marker, count=len(costs))
    with session_module.SessionLocal.begin() as db:
        order = PurchaseOrder(po_no=f"PERF28-COST-{marker}", status="sent")
        db.add(order)
        db.flush()
        lines = [
            PurchaseOrderLine(
                purchase_order_id=order.id,
                item_id=reference["items"][index][0],
                ordered_quantity=100,
                received_quantity=0,
                unit="m",
                unit_cost=Decimal("0"),
                warehouse_id=reference["warehouses"][0],
            )
            for index in range(len(costs))
        ]
        db.add_all(lines)
        db.commit()
        line_ids = [line.id for line in lines]
        order_id = order.id

    payload = {
        "lines": [
            {
                "purchase_order_line_id": line_ids[index],
                "received_quantity": 2,
                "cost_per_unit": costs[index],
                "batch_no": f"PERF28-C-{marker}-{index}",
            }
            for index in range(len(costs))
        ]
    }
    with session_module.SessionLocal() as db:
        user = _new_user(db, f"cost-{marker}")
        receive_purchase_order(db, order_id=order_id, data=payload, current=user)
        db.commit()

    stored = _stored_batch_costs(session_module.SessionLocal, f"PERF28-COST-{marker}")
    assert len(stored) == len(costs)
    for index, (_batch_no, stored_text, _quantity) in enumerate(stored):
        expected = round_unit_cost(costs[index])
        assert stored_text == str(expected), (
            f"line {index}: stored {stored_text!r} != policy {str(expected)!r}"
        )


def test_repeated_material_and_repeated_line_each_keep_their_own_cost():
    """A material repeated across lines, and a line repeated in one receipt.

    The first payload line sets an explicit price; the repeat omits it and must
    fall back to the *preceding explicit* price for that line, not to the
    original order price and not to another line's price.
    """
    marker = uuid4().hex[:8]
    with session_module.SessionLocal.begin() as db:
        item = Item(sku=f"PERF28-REP-{marker}", name="PERF28 repeated item", category="fabric", unit="m")
        supplier = Supplier(
            name=f"PERF28 rep supplier {marker}",
            email=f"perf28-rep-{marker}@example.invalid",
            phone=None,
        )
        warehouse = Warehouse(name=f"PERF28 rep warehouse {marker}", type="fabric_storage")
        db.add_all([item, supplier, warehouse])
        db.flush()
        order = PurchaseOrder(po_no=f"PERF28-REP-{marker}", status="sent")
        db.add(order)
        db.flush()
        lines = [
            PurchaseOrderLine(
                purchase_order_id=order.id,
                item_id=item.id,
                ordered_quantity=1000,
                received_quantity=0,
                unit="m",
                unit_cost=Decimal("9.99995"),
                warehouse_id=warehouse.id,
                supplier_id=supplier.id,
            )
            for _ in range(2)
        ]
        db.add_all(lines)
        db.commit()
        first_line, second_line = lines[0].id, lines[1].id
        order_id = order.id
        item_id = item.id
        warehouse_id = warehouse.id
        supplier_id = supplier.id

    # 0.00005 -> 0.0001 (rounds up, so a float round-trip would show as 0.0001
    # only by luck) and 3.33335 -> 3.3334.
    payload = {
        "lines": [
            {
                "purchase_order_line_id": first_line,
                "received_quantity": 1,
                "cost_per_unit": "0.00005",
                "batch_no": f"PERF28-R-{marker}-a",
            },
            {
                # Same line, no explicit cost: keeps the preceding explicit price.
                "purchase_order_line_id": first_line,
                "received_quantity": 2,
                "batch_no": f"PERF28-R-{marker}-b",
            },
            {
                # Same material, different line and warehouse, own explicit price.
                "purchase_order_line_id": second_line,
                "received_quantity": 3,
                "cost_per_unit": "3.33335",
                "batch_no": f"PERF28-R-{marker}-c",
            },
        ]
    }
    with session_module.SessionLocal() as db:
        user = _new_user(db, f"rep-{marker}")
        receive_purchase_order(db, order_id=order_id, data=payload, current=user)
        db.commit()

    stored = _stored_batch_costs(session_module.SessionLocal, f"PERF28-REP-{marker}")
    assert [batch_no for batch_no, _cost, _qty in stored] == [
        f"PERF28-R-{marker}-a",
        f"PERF28-R-{marker}-b",
        f"PERF28-R-{marker}-c",
    ]
    assert [cost for _batch_no, cost, _qty in stored] == [
        str(round_unit_cost("0.00005")),
        str(round_unit_cost("0.00005")),
        str(round_unit_cost("3.33335")),
    ]
    assert [Decimal(qty) for _batch_no, _cost, qty in stored] == [
        Decimal(1),
        Decimal(2),
        Decimal(3),
    ]

    # The repeated receipt lines accumulate onto their own order line.
    with session_module.SessionLocal() as db:
        assert db.get(PurchaseOrderLine, first_line).received_quantity == 3
        assert db.get(PurchaseOrderLine, second_line).received_quantity == 3
        batches = db.query(StockBatch).filter(StockBatch.item_id == item_id).all()
        assert {batch.warehouse_id for batch in batches} == {warehouse_id}
        assert {batch.supplier_id for batch in batches} == {supplier_id}


def test_repeated_material_on_many_lines_reads_each_reference_once():
    """Same material everywhere: the read must not repeat with the line count."""
    marker = uuid4().hex[:8]
    with session_module.SessionLocal.begin() as db:
        item = Item(sku=f"PERF28-ONE-{marker}", name="PERF28 single item", category="fabric", unit="m")
        supplier = Supplier(
            name=f"PERF28 one supplier {marker}",
            email=f"perf28-one-{marker}@example.invalid",
            phone=None,
        )
        warehouse = Warehouse(name=f"PERF28 one warehouse {marker}", type="fabric_storage")
        db.add_all([item, supplier, warehouse])
        db.flush()
        order = PurchaseOrder(po_no=f"PERF28-ONE-{marker}", status="sent")
        db.add(order)
        db.flush()
        lines = [
            PurchaseOrderLine(
                purchase_order_id=order.id,
                item_id=item.id,
                ordered_quantity=1000,
                received_quantity=0,
                unit="m",
                unit_cost=Decimal("1.5"),
                warehouse_id=warehouse.id,
                supplier_id=supplier.id,
            )
            for _ in range(LARGE_LINES)
        ]
        db.add_all(lines)
        db.commit()
        line_ids = [line.id for line in lines]
        order_id = order.id

    payload = {
        "lines": [
            {
                "purchase_order_line_id": line_ids[index],
                "received_quantity": 1,
                "batch_no": f"PERF28-O-{marker}-{index}",
            }
            for index in range(LARGE_LINES)
        ]
    }
    with session_module.SessionLocal() as db:
        with StatementCounter(db.get_bind()) as counter:
            user = _new_user(db, f"one-{marker}")
            receive_purchase_order(db, order_id=order_id, data=payload, current=user)
            db.commit()
    print(f"\nPERF28 one material / {LARGE_LINES} lines: reference reads={counter.reference_reads}")
    # Three reference rows total, so a correct implementation needs at most one
    # statement per table no matter how many lines share them.
    assert counter.reference_reads <= len(REFERENCE_TABLES) + GROWTH_CONSTANT


def _seed_route_order(marker, categories):
    """A sent order whose lines carry the given item categories, in order."""
    with session_module.SessionLocal.begin() as db:
        warehouse = Warehouse(name=f"PERF28 route wh {marker}", type="fabric_storage")
        items = [
            Item(
                sku=f"PERF28-ROUTE-{marker}-{index}",
                name=f"PERF28 route item {index}",
                category=category,
                unit="m",
            )
            for index, category in enumerate(categories)
        ]
        db.add(warehouse)
        db.add_all(items)
        db.flush()
        order = PurchaseOrder(po_no=f"PERF28-ROUTE-{marker}", status="sent")
        db.add(order)
        db.flush()
        lines = [
            PurchaseOrderLine(
                purchase_order_id=order.id,
                item_id=item.id,
                ordered_quantity=100,
                received_quantity=0,
                unit="m",
                unit_cost=Decimal("1.5"),
                warehouse_id=warehouse.id,
            )
            for item in items
        ]
        db.add_all(lines)
        db.commit()
        return {
            "order_id": order.id,
            "po_no": order.po_no,
            "line_ids": [line.id for line in lines],
            "item_ids": [item.id for item in items],
        }


def _receive_payload(order, marker):
    return {
        "lines": [
            {
                "purchase_order_line_id": order["line_ids"][index],
                "received_quantity": 2,
                "batch_no": f"PERF28-RT-{marker}-{index}",
            }
            for index in range(len(order["line_ids"]))
        ]
    }


def _make_admin_materials_only():
    with session_module.SessionLocal() as db:
        admin = db.query(User).filter_by(email="admin@example.com").one()
        admin.extra_permissions = [*(admin.extra_permissions or []), "inventory.materials_only"]
        db.commit()


def test_receive_route_still_authorizes_every_line_after_dropping_the_repeat(
    client, auth_headers, monkeypatch
):
    """A materials-only caller must be refused for a later line too.

    The route used to walk the order's lines a second time after the receipt.
    That repeat was provably redundant, so it is gone; this pins the part that
    must stay: every line is authorized before any stock is written, not just
    the first one.
    """
    from app.services import inventory_access

    marker = uuid4().hex[:8]
    _make_admin_materials_only()
    # The only non-material line is the last one, so a check that stopped early
    # would let it through.
    order = _seed_route_order(marker, ["fabric", "fabric", "accessory"])
    checked: list[int] = []
    original = inventory_access.require_item

    def spy(db, user, item_id):
        checked.append(item_id)
        return original(db, user, item_id)

    monkeypatch.setattr(inventory_access, "require_item", spy)
    response = client.post(
        f"/api/purchasing/orders/{order['order_id']}/receive",
        headers={**auth_headers, "Idempotency-Key": f"perf28-{marker}"},
        json=_receive_payload(order, marker),
    )
    assert response.status_code == 403, response.text
    # Every line was authorized, and the repeat is gone: one check per line.
    assert set(checked) == set(order["item_ids"])
    assert len(checked) == len(order["item_ids"])
    # Refusal happened before any stock was written.
    with session_module.SessionLocal() as db:
        assert db.query(StockBatch).filter_by(internal_batch_no=order["po_no"]).count() == 0
        assert db.get(PurchaseOrderLine, order["line_ids"][0]).received_quantity == 0


def test_receive_route_all_materials_lines_are_still_received(client, auth_headers):
    """The same route still authorizes a fully material order and receives it."""
    marker = uuid4().hex[:8]
    _make_admin_materials_only()
    order = _seed_route_order(marker, ["fabric", "fabric", "semi_finished"])
    response = client.post(
        f"/api/purchasing/orders/{order['order_id']}/receive",
        headers={**auth_headers, "Idempotency-Key": f"perf28-ok-{marker}"},
        json=_receive_payload(order, marker),
    )
    assert response.status_code == 200, response.text
    with session_module.SessionLocal() as db:
        batches = (
            db.query(StockBatch)
            .filter_by(internal_batch_no=order["po_no"])
            .order_by(StockBatch.id)
            .all()
        )
        assert [batch.cost_per_unit for batch in batches] == [
            Decimal("1.5000"),
            Decimal("1.5000"),
            Decimal("1.5000"),
        ]


@pytest.fixture(scope="module")
def purchasing_postgres_sessions():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip(
            "Set STABILIZATION_POSTGRES_URL for the real PostgreSQL PERF28 audit-head coverage"
        )
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("PERF28 PostgreSQL coverage requires a loopback PostgreSQL URL without connection overrides")
    schema = f"perf28_{uuid4().hex}"
    engine = create_engine(
        url,
        connect_args={"options": f"-csearch_path={schema} -clock_timeout=20000 -cstatement_timeout=25000"},
        pool_size=4,
        max_overflow=0,
        isolation_level="READ COMMITTED",
    )
    assert engine.dialect.name == "postgresql"
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        tables = {
            AuditLog.__table__,
            IdempotencyRecord.__table__,
            Item.__table__,
            PurchaseOrder.__table__,
            PurchaseOrderLine.__table__,
            PurchaseRequest.__table__,
            PurchaseRequestLine.__table__,
            StockBatch.__table__,
            StockMovement.__table__,
            User.__table__,
            Warehouse.__table__,
        }
        pending = list(tables)
        while pending:
            for foreign_key in pending.pop().foreign_keys:
                target = foreign_key.column.table
                if target not in tables:
                    tables.add(target)
                    pending.append(target)
        Base.metadata.create_all(engine, tables=list(tables))
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def test_postgres_receipt_reference_batching_still_finalizes_the_audit_head(
    purchasing_postgres_sessions,
):
    """Batched reference reads must not hold a cursor or a second session.

    On PostgreSQL the audit head is finalized during ``before_commit``; a
    leftover result or a stray session there would leave the chain unfinalized,
    so this asserts real hashes, not just row counts.
    """
    factory = purchasing_postgres_sessions
    marker = uuid4().hex[:8]
    with factory.begin() as db:
        assert db.bind.dialect.name == "postgresql"
        item = Item(sku=f"PERF28-PG-{marker}", name="PERF28 pg item", category="fabric", unit="m")
        supplier = Supplier(
            name=f"PERF28 pg supplier {marker}",
            email=f"perf28-pg-{marker}@example.invalid",
            phone=None,
        )
        warehouse = Warehouse(name=f"PERF28 pg warehouse {marker}", type="fabric_storage")
        user = User(
            name=f"PERF28 pg {marker}",
            email=f"perf28-pg-user-{marker}@example.invalid",
            password_hash="unused",
            factory_code="MIL",
            extra_permissions=[],
            is_active=True,
        )
        db.add_all([item, supplier, warehouse, user])
        db.flush()
        order = PurchaseOrder(po_no=f"PERF28-PG-{marker}", status="sent")
        db.add(order)
        db.flush()
        lines = [
            PurchaseOrderLine(
                purchase_order_id=order.id,
                item_id=item.id,
                ordered_quantity=1000,
                received_quantity=0,
                unit="m",
                unit_cost=Decimal("1.5"),
                warehouse_id=warehouse.id,
                supplier_id=supplier.id,
            )
            for _ in range(4)
        ]
        db.add_all(lines)
        db.commit()
        order_id = order.id
        line_ids = [line.id for line in lines]

    payload = {
        "lines": [
            {
                "purchase_order_line_id": line_ids[index],
                "received_quantity": 5,
                "cost_per_unit": "1.23455" if index == 0 else None,
                "batch_no": f"PERF28-PG-B-{marker}-{index}",
            }
            for index in range(4)
        ]
    }
    with factory() as db:
        assert db.bind.dialect.name == "postgresql"
        with StatementCounter(db.get_bind()) as counter:
            user = db.query(User).filter(User.email == f"perf28-pg-user-{marker}@example.invalid").one()
            receive_purchase_order(db, order_id=order_id, data=payload, current=user)
            db.commit()
    print(f"\nPERF28 postgres reference reads={counter.reference_reads} total={counter.total}")

    with factory() as db:
        report = verify_audit_hash_chain(db)
        assert report["ok"], report
        assert report["checked"] > 0
        entries = db.query(AuditLog).order_by(AuditLog.id).all()
        assert entries, "receipt must record audit entries"
        assert all(entry.entry_hash for entry in entries)
        first = entries[0]
        assert first.prev_hash is None or isinstance(first.prev_hash, str)
        for previous, current in zip(entries, entries[1:]):
            assert current.prev_hash == previous.entry_hash
        costs = [
            str(row.cost_per_unit)
            for row in db.query(StockBatch)
            .filter(StockBatch.internal_batch_no == f"PERF28-PG-{marker}")
            .order_by(StockBatch.id)
            .all()
        ]
        assert costs == [
            str(round_unit_cost("1.23455")),
            str(round_unit_cost("1.5")),
            str(round_unit_cost("1.5")),
            str(round_unit_cost("1.5")),
        ]


def test_postgres_coverage_is_not_silently_green(purchasing_postgres_sessions):
    """A PG run must actually be on PostgreSQL, not an implicit SQLite pass."""
    with purchasing_postgres_sessions() as db:
        assert db.bind.dialect.name == "postgresql"
        assert db.execute(text("SELECT version()")).scalar().startswith("PostgreSQL")
