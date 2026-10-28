"""Focused rejection tests with an owned in-memory SQLite database.

Run explicitly with pytest --noconftest. These tests do not depend on the
shared suite database or its global fixtures.
"""
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, object_session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.core.deps import get_current_user, get_db
from app.libs.enums.purchasing import PurchaseRequestStatus
from app.models import purchasing_service as core
from app.models.purchasing import requests_service as public
from app.api.routes.purchasing import router as purchasing_router
from app.schemas import AuditLog, Department, Item, PurchaseRequest, PurchaseRequestLine, User
from app.schemas.purchasing import purchase_request_persistence as persistence


@pytest.fixture
def reject_case():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    token = uuid4().hex
    with factory() as db:
        dept = Department(code="PRJ" + token[:8], name="Reject test " + token)
        actor = User(name="Reject actor", email=token + "@reject.invalid", password_hash="unused",
                     extra_permissions=[])
        item = Item(sku="reject-" + token, name="Test accessory", category="accessory", unit="pc")
        db.add_all([dept, actor, item])
        db.flush()
        request = PurchaseRequest(request_no="REJ-" + token, status="pending_approval", requested_by=actor.id)
        db.add(request)
        db.flush()
        line = PurchaseRequestLine(purchase_request_id=request.id, item_id=item.id, unit="pc",
                                   requested_quantity=1)
        db.add(line)
        db.commit()
        yield {"engine": engine, "factory": factory, "request_id": request.id,
               "actor_id": actor.id, "request_no": request.request_no}
    engine.dispose()


def state(case):
    with case["factory"]() as db:
        request = db.get(PurchaseRequest, case["request_id"])
        audits = db.query(AuditLog).filter_by(entity_type="PurchaseRequest", entity_id=request.id).all()
        return request.status, [(row.action, row.old_value_json, row.new_value_json) for row in audits]


@pytest.mark.parametrize("initial", [
    PurchaseRequestStatus.DRAFT,
    PurchaseRequestStatus.PENDING_APPROVAL,
    PurchaseRequestStatus.APPROVED,
])
def test_public_rejection_commits_real_audit_in_one_session(reject_case, monkeypatch, initial):
    with reject_case["factory"]() as db:
        request = db.get(PurchaseRequest, reject_case["request_id"])
        request.status = initial.value
        db.commit()

    seen = []
    original_writer = persistence.apply_purchase_request_rejection
    def writer(db, request, **fields):
        assert object_session(request) is db
        assert fields["status"] is PurchaseRequestStatus.REJECTED
        seen.append(("writer", db))
        return original_writer(db, request, **fields)
    monkeypatch.setattr(core, "apply_purchase_request_rejection", writer)
    original_access = core.require_purchase_item_access
    def access(db, user, lines):
        seen.append(("access", db))
        return original_access(db, user, lines)
    monkeypatch.setattr(core, "require_purchase_item_access", access)
    original_commit = Session.commit
    original_refresh = Session.refresh
    def commit(db):
        seen.append(("commit", db))
        return original_commit(db)
    def refresh(db, instance, *args, **kwargs):
        seen.append(("refresh", db))
        return original_refresh(db, instance, *args, **kwargs)
    monkeypatch.setattr(Session, "commit", commit)
    monkeypatch.setattr(Session, "refresh", refresh)

    with reject_case["factory"]() as db:
        actor = db.get(User, reject_case["actor_id"])
        result = public.reject_purchase_request(db, request_id=reject_case["request_id"], current=actor)
        assert result.status == "rejected"
        assert seen == [("writer", db), ("access", db), ("commit", db), ("refresh", db)]
        assert db.query(AuditLog).filter_by(entity_type="PurchaseRequest", entity_id=result.id).count() == 1
    assert state(reject_case) == (
        "rejected", [("reject", {"status": initial.value},
                      {"status": "rejected", "request_no": reject_case["request_no"]})]
    )


def test_invalid_transition_and_missing_request_refuse_without_writes(reject_case):
    with reject_case["factory"]() as db:
        actor = db.get(User, reject_case["actor_id"])
        request = db.get(PurchaseRequest, reject_case["request_id"])
        request.status = "converted"
        db.commit()
        with pytest.raises(HTTPException) as invalid:
            core.reject_purchase_request(db, request_id=request.id, current=actor)
        assert invalid.value.status_code == 409
        db.rollback()
        assert db.get(PurchaseRequest, request.id).status == "converted"
        with pytest.raises(HTTPException) as missing:
            core.reject_purchase_request(db, request_id=-1, current=actor)
        assert missing.value.status_code == 404
        db.rollback()
    assert state(reject_case) == ("converted", [])


def test_unknown_locked_status_is_409_before_enum_parsing(monkeypatch, reject_case):
    class LockedRow:
        id = 91
        request_no = "LEGACY-UNKNOWN"
        status = "legacy_unknown"
    monkeypatch.setattr(core, "_locked_purchase_request", lambda db, request_id: LockedRow())
    with reject_case["factory"]() as db:
        actor = db.get(User, reject_case["actor_id"])
        with pytest.raises(HTTPException) as error:
            core.reject_purchase_request(db, request_id=91, current=actor)
    assert error.value.status_code == 409
    assert error.value.detail == "Cannot reject purchase request in status 'legacy_unknown'"


def test_late_real_item_access_denial_rolls_back_audit_then_retry_succeeds(reject_case):
    before = state(reject_case)
    with reject_case["factory"]() as db:
        actor = db.get(User, reject_case["actor_id"])
        actor.extra_permissions = ["inventory.materials_only"]
        db.commit()
        with pytest.raises(HTTPException) as denied:
            public.reject_purchase_request(db, request_id=reject_case["request_id"], current=actor)
        assert denied.value.status_code == 403
        db.rollback()
    with reject_case["factory"]() as db:
        actor = db.get(User, reject_case["actor_id"])
        actor.extra_permissions = []
        db.commit()
    assert state(reject_case) == before
    with reject_case["factory"]() as db:
        actor = db.get(User, reject_case["actor_id"])
        public.reject_purchase_request(db, request_id=reject_case["request_id"], current=actor)
    assert state(reject_case)[0] == "rejected" and len(state(reject_case)[1]) == 1


def test_late_audit_failure_requires_caller_rollback_then_retry(reject_case, monkeypatch):
    before = state(reject_case)
    original = core.log_action
    def fail_after_real_audit(db, *args, **kwargs):
        original(db, *args, **kwargs)
        raise RuntimeError("injected after audit append")
    with reject_case["factory"]() as db:
        actor = db.get(User, reject_case["actor_id"])
        monkeypatch.setattr(core, "log_action", fail_after_real_audit)
        with pytest.raises(RuntimeError, match="after audit append"):
            core.reject_purchase_request(db, request_id=reject_case["request_id"], current=actor)
        db.rollback()  # Core and schema helpers leave rollback to the outer owner.
        monkeypatch.setattr(core, "log_action", original)
    assert state(reject_case) == before
    with reject_case["factory"]() as db:
        actor = db.get(User, reject_case["actor_id"])
        public.reject_purchase_request(db, request_id=reject_case["request_id"], current=actor)
    assert state(reject_case)[0] == "rejected" and len(state(reject_case)[1]) == 1


def test_schema_writer_failure_does_not_append_audit_or_commit(reject_case, monkeypatch):
    def fail_writer(*args, **kwargs):
        raise RuntimeError("injected schema writer failure")
    monkeypatch.setattr(core, "apply_purchase_request_rejection", fail_writer)
    before = state(reject_case)
    with reject_case["factory"]() as db:
        actor = db.get(User, reject_case["actor_id"])
        with pytest.raises(RuntimeError, match="schema writer failure"):
            core.reject_purchase_request(db, request_id=reject_case["request_id"], current=actor)
        db.rollback()
    assert state(reject_case) == before


def test_schema_writer_only_mutates_attached_row_without_transaction_actions(reject_case):
    with reject_case["factory"]() as db:
        request = db.get(PurchaseRequest, reject_case["request_id"])
        def unexpected(*args, **kwargs):
            pytest.fail("schema rejection writer must not manage Session operations")
        with pytest.MonkeyPatch.context() as patch:
            for name in ("add", "begin", "begin_nested", "flush", "commit", "rollback"):
                patch.setattr(db, name, unexpected)
            persistence.apply_purchase_request_rejection(
                db, request, status=PurchaseRequestStatus.REJECTED
            )
            assert object_session(request) is db and request.status == "rejected"


def test_repeated_rejection_refusals_leave_one_audit(reject_case):
    with reject_case["factory"]() as db:
        actor = db.get(User, reject_case["actor_id"])
        public.reject_purchase_request(db, request_id=reject_case["request_id"], current=actor)

    for _ in range(3):
        with reject_case["factory"]() as db:
            actor = db.get(User, reject_case["actor_id"])
            with pytest.raises(HTTPException) as error:
                public.reject_purchase_request(db, request_id=reject_case["request_id"], current=actor)
            assert error.value.status_code == 409
            assert error.value.detail == "Cannot reject purchase request in status 'rejected'"
            db.rollback()
            request = db.get(PurchaseRequest, reject_case["request_id"])
            assert request.status == "rejected"
            assert db.query(AuditLog).filter_by(
                entity_type="PurchaseRequest", entity_id=request.id
            ).count() == 1
    assert state(reject_case) == (
        "rejected", [("reject", {"status": "pending_approval"},
                      {"status": "rejected", "request_no": reject_case["request_no"]})]
    )


def _reject_route_app(reject_case, actor):
    app = FastAPI()
    app.include_router(purchasing_router)
    def isolated_db():
        with reject_case["factory"]() as db:
            yield db
    app.dependency_overrides[get_db] = isolated_db
    app.dependency_overrides[get_current_user] = lambda: actor
    return app


def test_reject_route_keeps_real_permission_dependency(reject_case):
    with reject_case["factory"]() as db:
        actor = db.get(User, reject_case["actor_id"])
        db.expunge(actor)
    app = _reject_route_app(reject_case, actor)
    with TestClient(app) as client:
        response = client.post(f"/purchasing/requests/{reject_case['request_id']}/reject")
    assert response.status_code == 403
    assert state(reject_case)[0] == "pending_approval"
    assert state(reject_case)[1] == []


def test_authorized_reject_route_returns_canonical_status_and_persists_audit(reject_case):
    with reject_case["factory"]() as db:
        actor = db.get(User, reject_case["actor_id"])
        actor.extra_permissions = ["purchasing.approve"]
        db.commit()
        db.expunge(actor)
    app = _reject_route_app(reject_case, actor)
    with TestClient(app) as client:
        response = client.post(f"/purchasing/requests/{reject_case['request_id']}/reject")
    assert response.status_code == 200
    assert response.json()["status"] == PurchaseRequestStatus.REJECTED.value
    assert state(reject_case) == (
        "rejected", [("reject", {"status": "pending_approval"},
                      {"status": "rejected", "request_no": reject_case["request_no"]})]
    )
