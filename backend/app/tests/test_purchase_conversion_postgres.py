"""Conversion on an owned migrated PostgreSQL target; requires the 7587 guard.

Never point this fixture at an existing application database. Root must first
authorize the exact instance and set the guard's required-mode configuration.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event
from time import monotonic
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.libs.dto.purchasing.purchase_order_output import PurchaseOrderCreationOut, PurchaseOrderOut
from app.libs.dto.purchasing.purchase_request_input import PurchaseRequestOrderIn
from app.libs.enums.purchasing import PurchaseOrderStatus
from app.models import audit_service, purchasing_service as core
from app.models.purchasing import requests_service
from app.schemas import (
    AuditLog, Department, Item, Notification, PurchaseOrder, PurchaseOrderLine,
    PurchaseRequest, PurchaseRequestLine, Supplier, User,
)
from app.tests.pg_approved_instance import (
    ApprovedInstanceUnavailable, create_target_database, finalize_target,
    load_approved_instance, require_or_skip, target_engine,
)

Sessions = sessionmaker(autoflush=False, expire_on_commit=False)
EXPECTED = datetime(2026, 11, 1, 16, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))


@pytest.fixture(scope="module")
def conversion_pg_engine():
    try:
        instance = load_approved_instance()
    except ApprovedInstanceUnavailable as error:
        require_or_skip(error)
    target = create_target_database(instance)
    engine = None
    try:
        engine = target_engine(target, options="-cstatement_timeout=20000 -clock_timeout=10000")
        # Alembic must use the same guarded engine, including its connect preflight.
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(settings, "DATABASE_URL",
                          engine.url.render_as_string(hide_password=False).replace("%", "%%"))
            patch.setattr(sa, "engine_from_config", lambda *args, **kwargs: engine)
            config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
            command.upgrade(config, "head")
        Sessions.configure(bind=engine)
        yield engine
    finally:
        try:
            Sessions.configure(bind=None)
        finally:
            finalize_target(target, engine)


@pytest.fixture
def pg_case(conversion_pg_engine):
    token = uuid4().hex
    with Sessions.begin() as db:
        store = db.query(Department).filter_by(code="STR").first()
        if store is None:
            store = Department(code="STR", name="Store")
            db.add(store)
            db.flush()
        actor = User(name="Conversion actor", email=token + "@example.invalid",
                     password_hash="unused", department_id=store.id, is_active=True,
                     extra_permissions=["purchasing.order"])
        recipient = User(name="Store recipient", email=token + "r@example.invalid",
                         password_hash="unused", department_id=store.id, is_active=True)
        db.add_all([actor, recipient])
        db.flush()
        request = PurchaseRequest(request_no="CONV-" + token, status="approved", requested_by=actor.id)
        db.add(request)
        db.flush()
        lines, items, suppliers = [], [], []
        for i in range(2):
            item = Item(sku=token + str(i), name="Fabric", category="fabric", unit="m")
            supplier = Supplier(name=token + str(i))
            db.add_all([item, supplier])
            db.flush()
            line = PurchaseRequestLine(purchase_request_id=request.id, item_id=item.id, unit="m",
                                       requested_quantity=10, preferred_supplier_id=supplier.id,
                                       material_name="Approved " + str(i), photo_url="/photo.jpg")
            db.add(line)
            db.flush()
            lines.append({"purchase_request_line_id": line.id, "ordered_quantity": 10 + i})
            items.append(item.id)
            suppliers.append(supplier.id)
        return {"id": request.id, "number": request.request_no, "actor": actor.id,
                "recipient": recipient.id, "lines": lines, "items": items, "suppliers": suppliers}


def _convert(case):
    with Sessions() as db:
        return requests_service.convert_purchase_request_to_order(
            db, request_id=case["id"], current=db.get(User, case["actor"]),
            payload=PurchaseRequestOrderIn.model_validate(
                {"expected_date": EXPECTED, "lines": case["lines"]}),
        )


def _participant_counts(db):
    return tuple(db.query(cls).count() for cls in
                 (PurchaseOrder, PurchaseOrderLine, AuditLog, Notification))


def test_pg_conversion_typed_snapshot_matches_persisted_and_timezone(pg_case):
    result = _convert(pg_case)
    assert isinstance(result, PurchaseOrderCreationOut)
    assert result.status is PurchaseOrderStatus.SENT
    assert result.expected_date.tzinfo is not None
    assert result.expected_date.astimezone(timezone.utc) == EXPECTED.astimezone(timezone.utc)
    with Sessions() as db:
        stored = db.get(PurchaseOrder, result.id)
        actual = result.model_dump(mode="json")
        fresh = PurchaseOrderOut.model_validate(stored).model_dump(mode="json")
        # Compare instants while retaining an aware offset in both projections.
        assert stored.expected_date.tzinfo is not None
        assert stored.expected_date.astimezone(timezone.utc) == EXPECTED.astimezone(timezone.utc)
        actual.pop("expected_date")
        fresh.pop("expected_date")
        assert actual == fresh
        assert db.get(PurchaseRequest, pg_case["id"]).status == "converted"
        audits = db.query(AuditLog).filter(
            sa.or_(sa.and_(AuditLog.entity_type == "PurchaseOrder", AuditLog.entity_id == result.id),
                   sa.and_(AuditLog.entity_type == "PurchaseRequest", AuditLog.entity_id == pg_case["id"])),
        ).all()
        assert {a.action for a in audits} == {"create", "convert_to_order"}
        assert all(a.entry_hash for a in audits)
        notices = db.query(Notification).filter_by(
            title="Purchase order ready for receiving: " + result.po_no).all()
        assert pg_case["recipient"] in {n.user_id for n in notices}
        assert pg_case["actor"] not in {n.user_id for n in notices}


def test_pg_deferred_audit_failure_rolls_back_every_participant_then_retry(pg_case, monkeypatch):
    with Sessions() as db:
        baseline = _participant_counts(db)
    original = audit_service._finalize_postgres_audits
    captured = {}

    def fail_after_finalization(db):
        original(db)
        db.flush()
        order = db.query(PurchaseOrder).filter_by(purchase_request_id=pg_case["id"]).one()
        captured.update(id=order.id, title="Purchase order ready for receiving: " + order.po_no)
        assert db.get(PurchaseRequest, pg_case["id"]).status == "converted"
        assert db.query(PurchaseOrderLine).filter_by(purchase_order_id=order.id).count() == 2
        assert db.query(AuditLog).filter_by(entity_type="PurchaseOrder", entity_id=order.id).one().entry_hash
        assert db.query(AuditLog).filter_by(entity_type="PurchaseRequest", entity_id=pg_case["id"]).one().entry_hash
        assert db.query(Notification).filter_by(title=captured["title"]).count() >= 1
        raise RuntimeError("after actual PostgreSQL audit finalization")

    with monkeypatch.context() as patch:
        patch.setattr(audit_service, "_finalize_postgres_audits", fail_after_finalization)
        with pytest.raises(RuntimeError, match="after actual PostgreSQL audit"):
            _convert(pg_case)
    assert captured
    with Sessions() as db:
        assert _participant_counts(db) == baseline
        assert db.get(PurchaseRequest, pg_case["id"]).status == "approved"
        assert db.get(PurchaseOrder, captured["id"]) is None
        assert db.query(PurchaseOrderLine).filter_by(purchase_order_id=captured["id"]).count() == 0
        assert db.query(AuditLog).filter_by(entity_type="PurchaseOrder", entity_id=captured["id"]).count() == 0
        assert db.query(AuditLog).filter_by(entity_type="PurchaseRequest", entity_id=pg_case["id"]).count() == 0
        assert db.query(Notification).filter_by(title=captured["title"]).count() == 0
    result = _convert(pg_case)
    assert result.status is PurchaseOrderStatus.SENT
    with Sessions() as db:
        assert db.query(PurchaseOrder).filter_by(purchase_request_id=pg_case["id"]).count() == 1


def test_pg_materials_only_late_refusal_rolls_back_and_retry(pg_case):
    with Sessions.begin() as db:
        db.get(User, pg_case["actor"]).extra_permissions = ["purchasing.order", "inventory.materials_only"]
        db.get(Item, pg_case["items"][1]).category = "accessory"
    with Sessions() as db:
        before = _participant_counts(db)
    with pytest.raises(HTTPException) as error:
        _convert(pg_case)
    assert error.value.status_code == 403
    with Sessions.begin() as db:
        assert _participant_counts(db) == before
        assert db.get(PurchaseRequest, pg_case["id"]).status == "approved"
        db.get(User, pg_case["actor"]).extra_permissions = ["purchasing.order"]
    assert _convert(pg_case).status is PurchaseOrderStatus.SENT


def test_pg_foreign_line_is_refused_without_effects(pg_case):
    with Sessions.begin() as db:
        other = PurchaseRequest(request_no="OTHER-" + uuid4().hex, status="approved")
        db.add(other)
        db.flush()
        line = PurchaseRequestLine(purchase_request_id=other.id, item_id=pg_case["items"][0],
                                   unit="m", requested_quantity=1)
        db.add(line)
        db.flush()
        foreign_id = line.id
    with Sessions() as db:
        before = _participant_counts(db)
        lines = [pg_case["lines"][0], {"purchase_request_line_id": foreign_id, "ordered_quantity": 1}]
        with pytest.raises(HTTPException) as error:
            requests_service.convert_purchase_request_to_order(
                db, request_id=pg_case["id"], current=db.get(User, pg_case["actor"]),
                payload=PurchaseRequestOrderIn.model_validate({"expected_date": EXPECTED, "lines": lines}))
        assert error.value.status_code == 400
        db.rollback()
    with Sessions() as db:
        assert _participant_counts(db) == before
        assert db.get(PurchaseRequest, pg_case["id"]).status == "approved"


@pytest.mark.parametrize("missing", ["item", "supplier"])
def test_pg_late_missing_reference_rolls_back(pg_case, monkeypatch, missing):
    with Sessions() as db:
        before = _participant_counts(db)
    original = core._reference_map
    def omit_second(db, model, ids):
        result = original(db, model, ids)
        if (missing == "item" and model is Item):
            result[pg_case["items"][1]] = None
        if (missing == "supplier" and model is Supplier):
            result[pg_case["suppliers"][1]] = None
        return result
    with monkeypatch.context() as patch:
        patch.setattr(core, "_reference_map", omit_second)
        with pytest.raises(HTTPException) as error:
            _convert(pg_case)
        assert error.value.status_code == 404
    with Sessions() as db:
        assert _participant_counts(db) == before
        assert db.get(PurchaseRequest, pg_case["id"]).status == "approved"


class _GateSession(Session):
    def __init__(self, *args, reached, release, **kwargs):
        super().__init__(*args, **kwargs)
        self.reached, self.release = reached, release

    def commit(self):
        self.reached.set()
        assert self.release.wait(15), "first conversion commit gate timed out"
        return super().commit()


def _wait_for_block(sessions, waiter, holder, contender, *, timeout=5):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if contender.done():
            raise AssertionError("contender finished without waiting on the first conversion")
        with sessions() as observer:
            blockers = observer.execute(
                sa.text("SELECT pg_blocking_pids(:pid)"), {"pid": waiter}
            ).scalar_one()
        if holder in blockers:
            return
        Event().wait(0.02)
    raise AssertionError("contender did not wait on the first conversion backend")


def test_pg_concurrent_conversion_serializes_and_refuses_second(pg_case):
    reached, release, second_ready = Event(), Event(), Event()
    pids = {}
    def worker(role):
        if role == "first":
            db = _GateSession(bind=Sessions.kw["bind"], autoflush=False,
                              expire_on_commit=False, reached=reached, release=release)
        else:
            db = Sessions()
        with db:
            pids[role] = db.execute(sa.text("SELECT pg_backend_pid()")).scalar_one()
            if role == "second":
                second_ready.set()
            return requests_service.convert_purchase_request_to_order(
                db, request_id=pg_case["id"], current=db.get(User, pg_case["actor"]),
                payload=PurchaseRequestOrderIn.model_validate(
                    {"expected_date": EXPECTED, "lines": pg_case["lines"]}),
            )
    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(worker, "first")
        second_future = None
        try:
            assert reached.wait(8), "first conversion did not reach its commit gate"
            second_future = pool.submit(worker, "second")
            assert second_ready.wait(8), "second conversion did not obtain a backend"
            assert pids["first"] != pids["second"]
            _wait_for_block(Sessions, pids["second"], pids["first"], second_future)
        finally:
            release.set()
        result = first_future.result(timeout=15)
        assert result.status is PurchaseOrderStatus.SENT
        assert second_future is not None
        with pytest.raises(HTTPException) as error:
            second_future.result(timeout=15)
        assert error.value.status_code == 409
    with Sessions() as db:
        assert db.get(PurchaseRequest, pg_case["id"]).status == "converted"
        orders = db.query(PurchaseOrder).filter_by(purchase_request_id=pg_case["id"]).all()
        assert len(orders) == 1 and orders[0].id == result.id
        lines = db.query(PurchaseOrderLine).filter_by(purchase_order_id=result.id).all()
        assert len(lines) == 2
        assert sorted(float(line.ordered_quantity) for line in lines) == [10, 11]
        order_audits = db.query(AuditLog).filter_by(entity_type="PurchaseOrder", entity_id=result.id).all()
        request_audits = db.query(AuditLog).filter_by(entity_type="PurchaseRequest", entity_id=pg_case["id"]).all()
        assert len(order_audits) == len(request_audits) == 1
        assert order_audits[0].action == "create" and request_audits[0].action == "convert_to_order"
        assert order_audits[0].entry_hash and request_audits[0].entry_hash
        notices = db.query(Notification).filter_by(
            title="Purchase order ready for receiving: " + result.po_no).all()
        recipients = db.query(User.id).join(Department, User.department_id == Department.id).filter(
            Department.code == "STR", User.is_active.is_(True), User.id != pg_case["actor"]).all()
        assert {row.user_id for row in notices} == {row[0] for row in recipients}
        assert len(notices) == len(recipients)
