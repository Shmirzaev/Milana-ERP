"""Real PostgreSQL failure and lock observers for the explicit pricing workflow."""

from contextlib import contextmanager
from threading import Event, Thread
import sys
import time
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event, text

from app.models import audit_service
from app.models.planning import costing_service, variant_pricing_service as workflow
from app.schemas import AuditLog, PriceCalculationRequest


@contextmanager
def draft_failure(sessions, monkeypatch, request_id, fault):
    """Inject after staged write, finalized audit, or a real deferred PG constraint."""
    observed = []
    attempted = []
    engine = sessions.kw["bind"]
    guard = "pricing_guard_" + uuid4().hex[:12]
    original_log = costing_service.log_action
    original_finalize = audit_service._finalize_postgres_audits

    def fail_write(db, *args, **kwargs):
        original_log(db, *args, **kwargs)
        db.flush()
        assert db.get(PriceCalculationRequest, request_id).revision > 1
        observed.append("write")
        raise RuntimeError("injected after staged pricing write")

    def finalize(db):
        original_finalize(db)
        audits = db.query(AuditLog).filter_by(entity_type="PriceCalculationRequest", entity_id=request_id).all()
        assert audits and all(row.entry_hash for row in audits)
        attempted.extend(row.id for row in audits)
        observed.append("audit")
        if fault == "audit":
            raise RuntimeError("injected after finalized pricing audit")

    def capture(context):
        error = context.original_exception
        if getattr(error, "pgcode", None) == "23514":
            assert error.diag.constraint_name == guard
            observed.append("commit")

    if fault == "commit":
        with engine.begin() as connection:
            connection.exec_driver_sql(
                f"CREATE FUNCTION {guard}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'fixture commit failure' USING ERRCODE='23514', CONSTRAINT='{guard}'; END; $$"
            )
            connection.exec_driver_sql(
                f"CREATE CONSTRAINT TRIGGER {guard} AFTER UPDATE ON price_calculation_requests DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.id={int(request_id)}) EXECUTE FUNCTION {guard}()"
            )
        event.listen(engine, "handle_error", capture)
    try:
        with monkeypatch.context() as patch:
            if fault == "write":
                patch.setattr(costing_service, "log_action", fail_write)
            else:
                patch.setattr(audit_service, "_finalize_postgres_audits", finalize)
            yield attempted
        assert observed == (["write"] if fault == "write" else ["audit"] if fault == "audit" else ["audit", "commit"])
    finally:
        if fault == "commit":
            event.remove(engine, "handle_error", capture)
            with engine.begin() as connection:
                connection.exec_driver_sql(f"DROP TRIGGER {guard} ON price_calculation_requests")
                connection.exec_driver_sql(f"DROP FUNCTION {guard}()")


def versioned_draft_race(sessions, monkeypatch, case, department, payloads):
    """Observe actual model-row waiting; stale second draft must receive 409."""
    from app.tests.test_price_calculation_status_postgres import app_for, auth
    from app.tests.pg_approved_instance import _park

    held, release = Event(), Event()
    pids, responses, failures = {}, {}, []
    request_id = case["request_id"]
    with sessions() as db:
        revision = db.get(PriceCalculationRequest, request_id).revision
    original = workflow.locked_request

    def coordinate(db, rid, actor, expected_revision=None):
        name = "first" if not pids else "second"
        pids[name] = db.scalar(text("select pg_backend_pid()"))
        result = original(db, rid, actor, expected_revision)
        if name == "first":
            held.set()
            if not release.wait(20):
                raise RuntimeError("model lock observer did not release writer")
        return result

    def send(name, payload):
        try:
            with TestClient(app_for(sessions), raise_server_exceptions=False) as client:
                responses[name] = client.patch(
                    f"/api/price-calculation/requests/{request_id}/{department}",
                    headers=auth(case["wildcard_id"]),
                    json={**payload, "expected_revision": revision},
                )
        except BaseException as error:
            failures.append(error)

    monkeypatch.setattr(workflow, "locked_request", coordinate)
    first = Thread(target=send, name="first", args=("first", payloads[0]), daemon=True)
    second = Thread(target=send, name="second", args=("second", payloads[1]), daemon=True)
    first.start()
    try:
        assert held.wait(10)
        second.start()
        deadline = time.monotonic() + 10
        blocked = False
        with sessions() as observer:
            while time.monotonic() < deadline:
                if pids.get("second") and observer.scalar(
                    text("select :holder=any(pg_blocking_pids(:waiter))"),
                    {"holder": pids["first"], "waiter": pids["second"]},
                ):
                    blocked = True
                    break
                time.sleep(0.05)
        assert blocked, pids
    finally:
        release.set()
        first.join(25)
        if second.ident is not None:
            second.join(25)
        if first.is_alive() or second.is_alive():
            current = sys.exc_info()[1]
            _park(
                "PRICING_DRAFT_WRITERS_UNKNOWN",
                (sessions, first, second, release, pids, responses),
                ([current] if current else []) + failures,
            )
            raise RuntimeError("HOLD observer unexpectedly returned")
    assert not failures, failures
    assert responses["first"].status_code == 200, responses["first"].text
    assert responses["second"].status_code == 409, responses["second"].text
    return responses["first"].json()
