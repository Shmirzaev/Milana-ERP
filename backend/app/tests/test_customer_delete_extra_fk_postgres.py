"""HELD source proposal: migrated-PG customer FK characterization; not yet run."""
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.models.catalog import partners_service
from app.schemas import BrandedPlanningOrder, ManualPackageReceipt, Package, Payment, WarehousePackReservation
from app.tests.test_supplier_update_postgres import role_actor
from app.tests.test_customer_create_postgres import chain, customer_pg_sessions  # noqa: F401
from app.tests.test_customer_delete_postgres import create_customer, state


@pytest.mark.parametrize("kind", ["payment", "branded_planning", "warehouse_pack_reservation"])
def test_pg_existing_customer_fk_blocks_delete_then_retry(customer_pg_sessions, monkeypatch, kind):
    """Characterize actual migrated FK and flush failure; no route status asserted."""
    sessions = customer_pg_sessions
    cid, name = create_customer(sessions)
    actor_id = role_actor(sessions, ["sales.customers"]) if kind == "warehouse_pack_reservation" else None
    with sessions.begin() as db:
        if kind == "payment":
            reference = Payment(customer_id=cid, amount=1)
        elif kind == "branded_planning":
            reference = BrandedPlanningOrder(order_no="FK-" + uuid4().hex,
                                             ordered_for_type="customer",
                                             customer_id=cid, ordered_for_name=name)
        else:
            marker = uuid4().hex
            receipt = ManualPackageReceipt(receipt_no="FK-" + marker, created_by=actor_id, evidence={}, evidence_hash="0" * 64)
            db.add(receipt)
            db.flush()
            package = Package(package_no="FK-" + marker, barcode="FK-" + marker, color="fixture", manual_receipt_id=receipt.id)
            db.add(package)
            db.flush()
            reference = WarehousePackReservation(package_id=package.id, customer_id=cid, quantity=1, reserved_by=actor_id)
        db.add(reference)
        db.flush()
        reference_id = reference.id
    table = {"payment": "payments", "branded_planning": "branded_planning_orders", "warehouse_pack_reservation": "warehouse_pack_reservations"}[kind]
    with sessions() as db:
        constraints = db.execute(text("""
            SELECT c.conname, c.confdeltype, c.condeferrable, c.condeferred
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(c.conkey)
            WHERE n.nspname = current_schema() AND t.relname = :table
              AND c.contype = 'f' AND a.attname = 'customer_id'
              AND c.confrelid = 'customers'::regclass
        """), {"table": table}).all()
        assert len(constraints) == 1
        constraint_name, delete_action, deferrable, deferred = constraints[0]
        assert delete_action == "a" and not deferrable and not deferred
    called = []
    returned = []
    original = partners_service.log_action
    def observed(db, *args, **kwargs):
        called.append(True)
        result = original(db, *args, **kwargs)
        returned.append(True)
        return result
    with monkeypatch.context() as patch:
        patch.setattr(partners_service, "log_action", observed)
        with sessions() as db:
            with pytest.raises(IntegrityError) as failure:
                partners_service.delete_customer(None, db, cid)
            assert failure.value.orig.pgcode == "23503"
            assert failure.value.orig.diag.constraint_name == constraint_name
            db.rollback()
    # log_action begins but its business flush fails before it can enqueue audit.
    assert called == [True] and returned == []
    assert state(sessions, cid) == ((name, "saved", "preserve on failure"), [])
    with sessions.begin() as db:
        cls = {"payment": Payment, "branded_planning": BrandedPlanningOrder, "warehouse_pack_reservation": WarehousePackReservation}[kind]
        reference = db.get(cls, reference_id)
        assert reference is not None and reference.customer_id == cid
        db.delete(reference)  # only the fixture-owned blocking reference
    with sessions() as db:
        partners_service.delete_customer(None, db, cid)
    assert state(sessions, cid) == (None, [(None, None, {"name": name})])
    chain(sessions)
