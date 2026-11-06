"""V2 real migrated-PostgreSQL follow-up coverage for request rejection.

This module owns one random database through pg_approved_instance.py. It is
intended to be run alone by the parent verification harness; it never targets
the shared suite database. Unknown status is exercised with a locked-row stub,
because the database's real status constraints are part of the migrated test.
"""
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.orm import joinedload, sessionmaker

from app.api.routes.purchasing import router as purchasing_router
from app.core.deps import get_current_user, get_db
from app.libs.enums.purchasing import PurchaseRequestStatus
from app.models import purchasing_service as core
from app.models import audit_service
from app.models.purchasing import requests_service as public
from app.schemas import AuditLog, Item, PurchaseRequest, PurchaseRequestLine, User
from app.tests.pg_approved_instance import (
    ApprovedInstanceUnavailable,
    create_target_database,
    finalize_target,
    load_approved_instance,
    require_or_skip,
    target_engine,
    verify_approved_instance,
)


@pytest.fixture(scope="module")
def reject_postgres_sessions():
    try:
        instance = load_approved_instance()
        verify_approved_instance(instance)
    except ApprovedInstanceUnavailable as error:
        require_or_skip(error)

    target = create_target_database(instance)
    engine = None
    try:
        engine = target_engine(target, options="-cstatement_timeout=20000 -clock_timeout=10000")
        assert engine.dialect.name == "postgresql"
        # Exercise the repository's actual migrated constraints, including the
        # persisted request-status contract, rather than metadata-only DDL.
        from app.core.config import settings

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(
                settings,
                "DATABASE_URL",
                engine.url.render_as_string(hide_password=False).replace("%", "%%"),
            )
            patch.setattr(sa, "engine_from_config", lambda *args, **kwargs: engine)
            config = Config(
                str(Path(__file__).resolve().parents[2] / "alembic.ini")
            )
            command.upgrade(config, "head")
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    finally:
        finalize_target(target, engine)


def _new_case(sessions, status: str = "pending_approval"):
    marker = uuid4().hex
    with sessions.begin() as db:
        actor = User(
            name="Reject PostgreSQL actor",
            email=f"reject-{marker}@example.invalid",
            password_hash="unused",
            factory_code="MIL",
            extra_permissions=["purchasing.approve"],
            is_active=True,
        )
        item = Item(
            sku=f"REJ-{marker}", name="Reject fixture item", category="accessory", unit="pc"
        )
        db.add_all([actor, item])
        db.flush()
        request = PurchaseRequest(
            request_no=f"REJ-{marker}", status=status, requested_by=actor.id
        )
        db.add(request)
        db.flush()
        line = PurchaseRequestLine(
            purchase_request_id=request.id,
            item_id=item.id,
            unit="pc",
            requested_quantity=1,
        )
        db.add(line)
        db.flush()
        result = {
            "request_id": request.id,
            "request_no": request.request_no,
            "actor_id": actor.id,
        }
    return result


def _state(sessions, request_id: int):
    with sessions() as db:
        request = db.get(PurchaseRequest, request_id)
        audits = (
            db.query(AuditLog)
            .filter_by(entity_type="PurchaseRequest", entity_id=request_id)
            .order_by(AuditLog.id)
            .all()
        )
        return request.status, [
            (row.action, row.user_id, row.old_value_json, row.new_value_json) for row in audits
        ]


@pytest.mark.parametrize(
    "initial",
    [
        pytest.param(PurchaseRequestStatus.DRAFT, id="draft"),
        pytest.param(PurchaseRequestStatus.PENDING_APPROVAL, id="pending_approval"),
        pytest.param(PurchaseRequestStatus.APPROVED, id="approved"),
    ],
)
def test_real_postgres_reject_commits_one_canonical_audit(reject_postgres_sessions, initial):
    case = _new_case(reject_postgres_sessions, initial.value)
    commits = []
    with reject_postgres_sessions() as db:
        actor = db.get(User, case["actor_id"])
        event.listen(db, "after_commit", lambda _session: commits.append(True))
        result = public.reject_purchase_request(
            db, request_id=case["request_id"], current=actor
        )
        assert result.status == PurchaseRequestStatus.REJECTED.value
        assert commits == [True]

    assert _state(reject_postgres_sessions, case["request_id"]) == (
        "rejected",
        [
            (
                "reject",
                case["actor_id"],
                {"status": initial.value},
                {"status": "rejected", "request_no": case["request_no"]},
            )
        ],
    )


def test_real_postgres_converted_and_missing_requests_refuse_without_effects(
    reject_postgres_sessions,
):
    case = _new_case(reject_postgres_sessions, "converted")
    with reject_postgres_sessions() as db:
        actor = db.get(User, case["actor_id"])
        with pytest.raises(HTTPException) as converted:
            public.reject_purchase_request(db, request_id=case["request_id"], current=actor)
        assert converted.value.status_code == 409
        db.rollback()
        with pytest.raises(HTTPException) as missing:
            public.reject_purchase_request(db, request_id=-987654321, current=actor)
        assert missing.value.status_code == 404
        db.rollback()
    assert _state(reject_postgres_sessions, case["request_id"]) == ("converted", [])


def test_unknown_locked_status_refuses_before_enum_conversion(reject_postgres_sessions, monkeypatch):
    case = _new_case(reject_postgres_sessions)
    with reject_postgres_sessions() as db:
        actor = db.get(User, case["actor_id"])
        monkeypatch.setattr(
            core,
            "_locked_purchase_request",
            lambda session, request_id: type("LockedRequestStatus", (), {"status": "legacy_unknown"})(),
        )
        with pytest.raises(HTTPException) as unknown:
            core.reject_purchase_request(db, request_id=case["request_id"], current=actor)
        assert unknown.value.status_code == 409
        assert unknown.value.detail == "Cannot reject purchase request in status 'legacy_unknown'"
        db.rollback()
    assert _state(reject_postgres_sessions, case["request_id"]) == ("pending_approval", [])


def test_real_route_permission_denial_preserves_postgres_state(reject_postgres_sessions):
    case = _new_case(reject_postgres_sessions)
    with reject_postgres_sessions() as auth_db:
        actor = (
            auth_db.query(User)
            .options(joinedload(User.role))
            .filter(User.id == case["actor_id"])
            .one()
        )
        actor.extra_permissions = ["purchasing.view"]
        auth_db.commit()
        # Permission evaluation reads user.role. Keep the actor's relationship
        # explicitly loaded before detaching it from this fixture-only session.
        auth_db.expunge(actor)

    app = FastAPI()
    app.include_router(purchasing_router)

    def isolated_db():
        with reject_postgres_sessions() as db:
            yield db

    app.dependency_overrides[get_db] = isolated_db
    app.dependency_overrides[get_current_user] = lambda: actor
    with TestClient(app) as client:
        response = client.post(f"/purchasing/requests/{case['request_id']}/reject")
    assert response.status_code == 403
    assert _state(reject_postgres_sessions, case["request_id"]) == ("pending_approval", [])


def test_queued_real_audit_failure_rolls_back_then_retry_has_one_audit(
    reject_postgres_sessions, monkeypatch
):
    case = _new_case(reject_postgres_sessions)
    original_hash = audit_service._audit_entry_hash

    def fail_during_finalize(**kwargs):
        raise RuntimeError("injected during PostgreSQL audit finalization")

    with reject_postgres_sessions() as db:
        actor = db.get(User, case["actor_id"])
        monkeypatch.setattr(audit_service, "_audit_entry_hash", fail_during_finalize)
        with pytest.raises(RuntimeError, match="during PostgreSQL audit finalization"):
            public.reject_purchase_request(db, request_id=case["request_id"], current=actor)
        # The queued audit and business update share the public caller's rollback.
        db.rollback()
    assert _state(reject_postgres_sessions, case["request_id"]) == ("pending_approval", [])

    with reject_postgres_sessions() as db:
        actor = db.get(User, case["actor_id"])
        monkeypatch.setattr(audit_service, "_audit_entry_hash", original_hash)
        result = public.reject_purchase_request(db, request_id=case["request_id"], current=actor)
        assert result.status == "rejected"
    assert _state(reject_postgres_sessions, case["request_id"]) == (
        "rejected",
        [
            (
                "reject",
                case["actor_id"],
                {"status": "pending_approval"},
                {"status": "rejected", "request_no": case["request_no"]},
            )
        ],
    )
