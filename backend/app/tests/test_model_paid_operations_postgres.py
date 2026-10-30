"""Paid-operation PATCH integration checks on the approved disposable PG target."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from queue import Queue
from threading import Barrier
from time import monotonic, sleep
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.routes.catalog import router as catalog_router
from app.api.routes.usluga import router as usluga_router
from app.core.deps import get_db
from app.core.security import create_access_token
from app.libs.dto.catalog.model_input import ModelPaidOperationsIn
from app.libs.enums.catalog import (
    PaidOperationFactory,
    PaidOperationQuantityMode,
    PaidOperationSplitMode,
    PaidProcessSection,
)
from app.models.catalog import models_service
from app.models.factory_scope_service import bind_session_factory
from app.schemas import AuditLog, Model, Role, User
from app.tests.test_customer_create_postgres import chain, customer_pg_sessions  # noqa: F401


def _actor(sessions, permissions, factory="MIL"):
    with sessions.begin() as db:
        role = Role(name=f"Paid operation PG {uuid4().hex}", permissions=permissions)
        db.add(role)
        db.flush()
        user = User(
            name="Paid operation PG actor",
            email=f"paid-operation-{uuid4().hex}@example.invalid",
            password_hash="unused",
            factory_code=factory,
            role_id=role.id,
            is_active=True,
        )
        db.add(user)
        db.flush()
        return user.id


def _client(sessions):
    app = FastAPI()
    app.include_router(catalog_router, prefix="/api")

    def isolated_db():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = isolated_db
    return TestClient(app, raise_server_exceptions=False)


def _headers(actor_id, factory=None):
    extra = {"factory_code": factory} if factory else None
    return {"Authorization": f"Bearer {create_access_token(actor_id, extra)}"}


def _family(sessions, marker, *, legacy=False):
    model_no = f"PAID-{marker}-{uuid4().hex[:8]}"
    with sessions.begin() as db:
        members = [
            Model(
                code=model_no,
                name="Paid operation family",
                details_json={"general": {"model_no": model_no}, "unrelated": {"keep": True}},
            ),
            Model(
                code=f"{model_no}-V-1",
                name="Paid operation family variant",
                details_json={"general": {"model_no": model_no, "variant_no": "1"}},
            ),
        ]
        db.add_all(members)
        if legacy:
            members.append(Model(
                code=f"{model_no}-LEGACY",
                name="Imported row",
                details_json={"general": {"model_no": model_no}, "legacy_import": True,
                              "paid_operations": [{"id": "legacy", "section": "historic"}]},
            ))
        db.flush()
        return [row.id for row in members]


def _stored(sessions, model_id):
    with sessions() as db:
        return deepcopy(db.get(Model, model_id).details_json)


def _audits(sessions, ids):
    with sessions() as db:
        return [
            (row.entity_id, row.action, row.user_id, row.new_value_json)
            for row in db.query(AuditLog).filter(
                AuditLog.entity_type == "Model", AuditLog.entity_id.in_(ids)
            ).order_by(AuditLog.id)
        ]


def _rows_for(sections, factories):
    quantities = list(PaidOperationQuantityMode)
    splits = list(PaidOperationSplitMode)
    rows = []
    for index, section in enumerate(sections):
        factory = factories[index % len(factories)]
        rows.append({
            "id": f"wire-{index}", "section": section.value,
            "sewingFactory": factory.value, "quantityMode": quantities[index % len(quantities)].value,
            "splitMode": splits[index % len(splits)].value, "rate": str(index + 1),
            "selected": True, "duration": "2.50", "currency": "UZS",
            "extension": {"retained": index},
        })
    rows.extend([
        {"id": "rate-int", "section": "sewing", "sewingFactory": "milana", "rate": 0},
        {"id": "rate-float", "section": "cutting", "sewingFactory": "besttex", "rate": 1.25},
        {"id": "aliases", "section": "sewing", "sewingFactory": "milana",
         "sourceOrder": None, "sequence": 2, "quantityMode": None, "quantity_mode": "custom",
         "splitMode": None, "split_mode": "equal", "name": "", "operation_name": "Stitch",
         "splitQuantities": None, "split_quantities": [1, "2"], "extension": {"opaque": True}},
        {"id": "company-only", "section": "sewing", "company": "MIL", "rate": "5"},
        {"id": "company-and-explicit", "section": "sewing", "company": "BST",
         "sewingFactory": "milana", "rate": "6"},
    ])
    return rows


@pytest.mark.parametrize("writer", ["dedicated", "whole-model"], ids=["dedicated-patch", "whole-model-patch"])
def test_pg_paid_operations_patch_round_trips_typed_rows_and_openapi(customer_pg_sessions, writer):
    sessions = customer_pg_sessions
    actor_id = _actor(sessions, ["*"])
    ids = _family(sessions, writer)
    rows = _rows_for(list(PaidProcessSection), list(PaidOperationFactory))
    if writer == "dedicated":
        body = {"paid_operations": rows}
    else:
        with sessions() as db:
            model = db.get(Model, ids[0])
            body = {
                "code": model.code,
                "name": model.name,
                "details_json": {
                    "general": deepcopy(model.details_json["general"]),
                    "paidOperations": rows,
                    "unrelated": {"client": "kept"},
                },
            }
    with _client(sessions) as client:
        headers = _headers(actor_id)
        schema = client.get("/openapi.json").json()["components"]["schemas"]
        nested = schema["ModelDetailsUpdateIn"]
        assert nested["additionalProperties"] is True
        for key in ("paid_operations", "paidOperations"):
            assert "PaidOperationIn" in str(nested["properties"][key])
        assert not {"factory_was_explicit", "resolved_factory_hint"}.intersection(
            schema["PaidOperationIn"]["properties"]
        )
        assert "PaidOperationIn" in str(schema["ModelPaidOperationsIn"]["properties"]["paid_operations"])
        assert set(value.value for value in PaidProcessSection) == {
            "sewing", "cutting", "packaging", "cleaning", "pressing", "control", "storage",
            "tikuv", "transfer", "snaps", "buttons", "cord", "sorting",
        }
        response = client.patch(
            f"/api/models/{ids[0]}/paid-operations" if writer == "dedicated" else f"/api/models/{ids[0]}",
            headers=headers,
            json=body,
        )
    assert response.status_code == 200, response.text
    saved = _stored(sessions, ids[0])
    paid_key = "paid_operations" if writer == "dedicated" else "paidOperations"
    persisted = saved[paid_key]
    assert {row["section"] for row in persisted} == {
        "sewing", "cutting", "packaging", "cleaning", "pressing", "control", "storage",
        "tikuv", "transfer", "snaps", "buttons", "cord", "sorting",
    }
    assert {value.value for value in PaidOperationFactory} == {"milana", "besttex", "eco_cotton"}
    assert {row["sewingFactory"] for row in persisted if row.get("id", "").startswith("wire-")} == {
        "milana", "besttex", "eco_cotton"
    }
    assert {value.value for value in PaidOperationQuantityMode} == {"batch", "custom"}
    assert {value.value for value in PaidOperationSplitMode} == {"none", "equal", "custom"}
    assert all(row.get("quantityMode") in {"batch", "custom"}
               for row in persisted if row.get("id", "").startswith("wire-"))
    assert all(row.get("splitMode") in {"none", "equal", "custom"}
               for row in persisted if row.get("id", "").startswith("wire-"))
    assert {row["quantityMode"] for row in persisted if row.get("id", "").startswith("wire-")} == {"batch", "custom"}
    assert {row["splitMode"] for row in persisted if row.get("id", "").startswith("wire-")} == {
        "none", "equal", "custom"
    }
    by_id = {row.get("id"): row for row in persisted}
    assert by_id["wire-0"]["extension"] == {"retained": 0}
    assert by_id["rate-int"]["rate"] == 0
    assert by_id["rate-float"]["rate"] == 1.25
    assert by_id["aliases"]["sourceOrder"] is None and by_id["aliases"]["sequence"] == 2
    assert by_id["aliases"]["quantityMode"] is None and by_id["aliases"]["quantity_mode"] == "custom"
    assert by_id["aliases"]["splitMode"] is None and by_id["aliases"]["split_mode"] == "equal"
    assert by_id["aliases"]["splitQuantities"] is None and by_id["aliases"]["split_quantities"] == [1, "2"]
    assert by_id["aliases"]["name"] == "" and by_id["aliases"]["operation_name"] == "Stitch"
    assert "source_order" not in by_id["aliases"] and "duration" not in by_id["aliases"]
    assert by_id["company-only"]["company"] == "MIL" and "sewingFactory" not in by_id["company-only"]
    assert by_id["company-and-explicit"]["company"] == "BST"
    assert by_id["company-and-explicit"]["sewingFactory"] == "milana"
    if writer == "whole-model":
        assert saved["unrelated"] == {"client": "kept"}
    with sessions() as db:
        assert db.get(Model, ids[0]).details_json == saved
        sibling = db.get(Model, ids[1]).details_json
        if writer == "dedicated":
            assert sibling["paid_operations"] == persisted
        else:
            assert "paid_operations" not in sibling
    assert len(_audits(sessions, ids)) == (2 if writer == "dedicated" else 1)
    chain(sessions)


def test_pg_paid_operations_invalid_and_cross_factory_patch_leave_family_and_audit_unchanged(customer_pg_sessions):
    sessions = customer_pg_sessions
    mil_id = _actor(sessions, ["payroll.manage", "modeling.models"], "MIL")
    ids = _family(sessions, "REFUSAL", legacy=True)
    before = {model_id: _stored(sessions, model_id) for model_id in ids}
    audit_before = _audits(sessions, ids)
    with _client(sessions) as client:
        headers = _headers(mil_id, "MIL")
        with sessions() as db:
            target = db.get(Model, ids[0])
            whole_base = {"code": target.code, "name": target.name}
        cases = [
            (f"/api/models/{ids[0]}/paid-operations", {"paid_operations": [
                {"id": "valid-first", "section": "sewing", "rate": "1"},
                {"id": "invalid-later", "section": "not-a-section", "rate": "2"},
            ]}),
            (f"/api/models/{ids[0]}/paid-operations", {"paid_operations": [
                {"id": "bool-rate", "section": "sewing", "rate": True},
            ]}),
            (f"/api/models/{ids[0]}/paid-operations", {"paid_operations": [
                {"id": "foreign", "section": "sewing", "sewingFactory": "besttex"},
            ]}),
            (f"/api/models/{ids[0]}", {**whole_base, "details_json": {"paid_operations": [
                {"id": "valid-first", "section": "sewing", "rate": "1"},
                {"id": "invalid-later", "section": "unknown", "rate": "2"},
            ]}}),
        ]
        expected = [422, 422, 403, 422]
        for (url, body), status in zip(cases, expected):
            response = client.patch(url, headers=headers, json=body)
            assert response.status_code == status, response.text
            assert {model_id: _stored(sessions, model_id) for model_id in ids} == before
            assert _audits(sessions, ids) == audit_before
    chain(sessions)


def test_pg_paid_operations_scoped_save_keeps_other_factory_opaque_legacy_and_other_family(customer_pg_sessions):
    sessions = customer_pg_sessions
    actor_id = _actor(sessions, ["payroll.manage"], "MIL")
    ids = _family(sessions, "OPAQUE-SCOPE", legacy=True)
    outsider = _family(sessions, "OPAQUE-OUTSIDER")[0]
    opaque_bst = {
        "id": "old-bst", "section": "historic-section", "sewingFactory": "besttex",
        "rate": True, "quantityMode": "retired", "opaque": {"keep": [1, 2]},
    }
    shared_hint = {"id": "old-shared", "section": "historic-section", "company": "MIL",
                   "rate": "legacy", "extension": {"source": "import"}}
    original_other = _stored(sessions, outsider)
    original_legacy = _stored(sessions, ids[2])
    with sessions.begin() as db:
        for model_id in ids[:2]:
            model = db.get(Model, model_id)
            model.details_json = {**model.details_json, "paid_operations": [deepcopy(opaque_bst), deepcopy(shared_hint)]}
    initial_base = _stored(sessions, ids[0])
    with _client(sessions) as client:
        response = client.patch(
            f"/api/models/{ids[0]}/paid-operations",
            headers=_headers(actor_id, "MIL"),
            json={"sewing_factory": "MIL", "paid_operations": [
                {"id": "new-mil", "section": "sewing", "rate": "9"},
            ]},
        )
    assert response.status_code == 200, response.text
    for model_id in ids[:2]:
        rows = _stored(sessions, model_id)["paid_operations"]
        assert next(row for row in rows if row["id"] == "old-bst") == opaque_bst
        assert any(row.get("company") == "MIL" and row.get("rate") == "legacy"
                   and row.get("extension") == {"source": "import"} for row in rows)
        assert any(row.get("id") == "new-mil" and row.get("sewingFactory") == "milana" for row in rows)
    assert _stored(sessions, outsider) == original_other
    assert _stored(sessions, ids[2]) == original_legacy
    assert len(_audits(sessions, ids)) == 2
    assert initial_base["paid_operations"][0] == opaque_bst
    chain(sessions)


@pytest.mark.parametrize("writer", ["dedicated", "whole-model"], ids=["usluga-dedicated-patch", "usluga-whole-model-patch"])
def test_pg_usluga_paid_operation_routes_apply_eco_factory_and_typed_sections(customer_pg_sessions, writer):
    sessions = customer_pg_sessions
    actor_id = _actor(sessions, ["usluga.manage"], "ECO")
    model_no = f"USLUGA-PAID-{uuid4().hex[:8]}"
    with sessions.begin() as db:
        model = Model(
            code=model_no, name="Usluga paid-operation model", factory_code="ECO", catalog_scope="usluga",
            details_json={"general": {"model_no": model_no}, "legacy": {"untouched": True}},
        )
        db.add(model)
        db.flush()
        model_id = model.id
        code, name = model.code, model.name
    rows = [
        {"id": f"usluga-{section.value}", "section": section.value, "rate": "3.25", "extra": {"keep": True}}
        for section in PaidProcessSection
    ]
    app = FastAPI()
    app.include_router(catalog_router, prefix="/api")
    app.include_router(usluga_router, prefix="/api")
    def isolated_db():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = isolated_db
    with TestClient(app, raise_server_exceptions=False) as client:
        url = f"/api/usluga/models/{model_id}/paid-operations" if writer == "dedicated" else f"/api/usluga/models/{model_id}"
        body = {"paid_operations": rows} if writer == "dedicated" else {
            "code": code, "name": name, "details_json": {
                "general": {"model_no": model_no},
                "paid_operations": rows,
                "legacy": {"untouched": True},
            },
        }
        response = client.patch(url, headers=_headers(actor_id, "ECO"), json=body)
    assert response.status_code == 200, response.text
    saved = _stored(sessions, model_id)
    assert saved["legacy"] == {"untouched": True}
    assert {row["section"] for row in saved["paid_operations"]} == {
        "sewing", "cutting", "packaging", "cleaning", "pressing", "control", "storage",
        "tikuv", "transfer", "snaps", "buttons", "cord", "sorting",
    }
    assert {row["sewingFactory"] for row in saved["paid_operations"]} == {"eco_cotton"}
    assert all(row["extra"] == {"keep": True} for row in saved["paid_operations"])
    assert len(_audits(sessions, [model_id])) == 1
    chain(sessions)


def test_pg_model_create_keeps_historical_paid_operation_json_opaque(customer_pg_sessions):
    sessions = customer_pg_sessions
    actor_id = _actor(sessions, ["*"])
    code = f"CREATE-OPAQUE-{uuid4().hex[:8]}"
    details = {
        "general": {"model_no": code},
        "paid_operations": [{"id": "old", "section": "historic-section", "rate": True,
                             "company": "MIL", "quantityMode": "retired", "extension": {"keep": True}}],
    }
    with _client(sessions) as client:
        response = client.post("/api/models", headers=_headers(actor_id), json={
            "code": code, "name": "Opaque historical JSON", "details_json": details,
        })
    assert response.status_code == 201, response.text
    saved = _stored(sessions, response.json()["id"])
    assert saved == details


@pytest.mark.parametrize("failure_point", ["audit", "model-flush"], ids=["audit-failure", "postflush-failure"])
def test_pg_paid_operations_failure_rolls_back_then_same_session_retry(customer_pg_sessions, monkeypatch, failure_point):
    sessions = customer_pg_sessions
    actor_id = _actor(sessions, ["payroll.manage"], "MIL")
    ids = _family(sessions, f"ROLLBACK-{failure_point}")
    before = {model_id: _stored(sessions, model_id) for model_id in ids}
    audit_before = _audits(sessions, ids)
    bound_sessions = []
    audit_sessions = []
    flushed_models = []
    flush_fault_fired = []
    expected_flush_ids = set(ids[:2])
    payload = {"paid_operations": [
        {"id": "retry", "section": "sewing", "sewingFactory": "milana", "rate": "12.50", "extension": {"ok": True}}
    ], "sewing_factory": "milana"}
    original_persist = models_service.persist_model_paid_operations
    original_audit = models_service.log_action

    def witness_persist(db, model, details):
        from sqlalchemy.orm import object_session
        assert object_session(model) is db
        bound_sessions.append(db)
        return original_persist(db, model, details)

    def witness_audit(db, *args, **kwargs):
        audit_sessions.append(db)
        original_audit(db, *args, **kwargs)
        if failure_point == "audit":
            raise RuntimeError("injected model paid-operation audit failure")

    def fail_flush(db, *args, **kwargs):
        changed_ids = tuple(row.id for row in db.dirty if isinstance(row, Model))
        if not changed_ids:
            return original_flush(*args, **kwargs)
        original_flush(*args, **kwargs)
        flushed_models.extend(changed_ids)
        if expected_flush_ids.issubset(set(flushed_models)) and not flush_fault_fired:
            flush_fault_fired.append(True)
            raise RuntimeError("injected model paid-operation postflush failure")

    with monkeypatch.context() as patch:
        patch.setattr(models_service, "persist_model_paid_operations", witness_persist)
        patch.setattr(models_service, "log_action", witness_audit)
        with sessions() as db:
            actor = db.get(User, actor_id)
            bind_session_factory(actor, "MIL")
            if failure_point == "model-flush":
                original_flush = db.flush
                db.flush = lambda *args, **kwargs: fail_flush(db, *args, **kwargs)
            with pytest.raises(RuntimeError, match="injected model paid-operation"):
                models_service.update_model_paid_operations(
                    actor, db, ids[0], ModelPaidOperationsIn.model_validate(payload)
                )
            db.rollback()
            assert {model_id: _stored(sessions, model_id) for model_id in ids} == before
            assert _audits(sessions, ids) == audit_before
            # Prove retry succeeds using the same caller-owned Session.
            if failure_point == "audit":
                patch.setattr(models_service, "log_action", original_audit)
            else:
                db.flush = original_flush
            actor = db.get(User, actor_id)
            bind_session_factory(actor, "MIL")
            models_service.update_model_paid_operations(
                actor, db, ids[0], ModelPaidOperationsIn.model_validate(payload)
            )
    assert bound_sessions and all(session is bound_sessions[0] for session in bound_sessions)
    assert audit_sessions and all(session is bound_sessions[0] for session in audit_sessions)
    if failure_point == "model-flush":
        assert expected_flush_ids.issubset(set(flushed_models))
        assert flush_fault_fired == [True]
    for model_id in ids:
        rows = _stored(sessions, model_id)["paid_operations"]
        assert rows == [{"id": "retry", "section": "sewing", "sewingFactory": "milana",
                         "rate": "12.50", "extension": {"ok": True}}]
    assert len(_audits(sessions, ids)) == 2
    chain(sessions)


def test_pg_paid_operations_concurrent_factories_serialize_same_family_and_prove_row_lock_wait(customer_pg_sessions):
    sessions = customer_pg_sessions
    mil_id = _actor(sessions, ["payroll.manage"], "MIL")
    bst_id = _actor(sessions, ["payroll.manage"], "BST")
    ids = _family(sessions, "CONCURRENT")
    outsider = _family(sessions, "OUTSIDER")[0]
    with sessions.begin() as db:
        for model_id in [*ids, outsider]:
            model = db.get(Model, model_id)
            model.details_json = {**model.details_json, "paid_operations": [
                {"id": "keep-eco", "section": "sewing", "sewingFactory": "eco_cotton", "rate": "7"},
            ]}

    def save(actor_id, factory, marker, start_barrier=None, pid_queue=None):
        with sessions() as db:
            db.execute(text("SET LOCAL lock_timeout = '9s'"))
            db.execute(text("SET LOCAL statement_timeout = '18s'"))
            actor = db.get(User, actor_id)
            bind_session_factory(actor, factory)
            if pid_queue is not None:
                pid_queue.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            if start_barrier:
                start_barrier.wait(timeout=8)
            body = ModelPaidOperationsIn.model_validate({
                "sewing_factory": factory,
                "paid_operations": [
                    {"id": f"{marker}-a", "section": "sewing", "rate": "10", "extension": {"factory": factory}},
                    {"id": f"{marker}-b", "section": "cutting", "rate": "20", "extension": {"factory": factory}},
                ],
            })
            models_service.update_model_paid_operations(actor, db, ids[0], body)

    # Hold the first family Model row so a real worker must block after its
    # family advisory lock. An independent observer verifies the PG wait chain.
    holder = sessions()
    holder_pid = holder.execute(text("SELECT pg_backend_pid()")).scalar_one()
    holder.query(Model).filter(Model.id == ids[0]).with_for_update().one()
    pool = ThreadPoolExecutor(max_workers=2)
    worker_pid = Queue()
    start = Barrier(2)
    workers = [
        pool.submit(save, actor_id, factory, prefix, start, worker_pid)
        for actor_id, factory, prefix in ((mil_id, "MIL", "mil"), (bst_id, "BST", "bst"))
    ]
    observer = sessions()
    lock_witnesses = set()
    deadline = monotonic() + 8
    try:
        blocked_pids = {worker_pid.get(timeout=5), worker_pid.get(timeout=5)}
        while monotonic() < deadline:
            observer.execute(text("SELECT pg_stat_clear_snapshot()"))
            for blocked_pid in blocked_pids:
                state = observer.execute(text("""
                    SELECT wait_event_type, query, pg_blocking_pids(pid) AS blocking_pids
                      FROM pg_stat_activity WHERE pid = :pid
                """), {"pid": blocked_pid}).one_or_none()
                if state and state.wait_event_type == "Lock" and state.blocking_pids:
                    seen = set(state.blocking_pids)
                    frontier = list(state.blocking_pids)
                    while frontier:
                        parent_pid = frontier.pop()
                        blockers = observer.execute(text("SELECT pg_blocking_pids(:pid)"), {"pid": parent_pid}).scalar_one()
                        for blocker in blockers:
                            if blocker not in seen:
                                seen.add(blocker)
                                frontier.append(blocker)
                    query = state.query.lower()
                    is_expected_lock = (
                        ("models" in query and "for update" in query)
                        or "pg_advisory_xact_lock" in query
                    )
                    if holder_pid in seen and is_expected_lock:
                        lock_witnesses.add(blocked_pid)
            if lock_witnesses == blocked_pids or all(worker.done() for worker in workers):
                break
            sleep(0.02)
    finally:
        holder.rollback()
        holder.close()
        observer.close()
        pool.shutdown(wait=True, cancel_futures=True)
    assert lock_witnesses == blocked_pids, (
        "every worker must show a PostgreSQL Model row/advisory lock wait whose blocker chain reaches the holder"
    )
    for worker in workers:
        worker.result(timeout=15)
    for model_id in ids:
        rows = _stored(sessions, model_id)["paid_operations"]
        by_factory = {row.get("sewingFactory"): row for row in rows}
        assert by_factory["eco_cotton"]["rate"] == "7"
        for factory, prefix, source_factory in (("milana", "mil", "MIL"), ("besttex", "bst", "BST")):
            selected = [row for row in rows if row.get("sewingFactory") == factory]
            assert {row["id"] for row in selected} == {f"{prefix}-a", f"{prefix}-b"}
            assert {row["extension"]["factory"] for row in selected} == {source_factory}
    outsider_details = _stored(sessions, outsider)
    assert outsider_details["paid_operations"] == [
        {"id": "keep-eco", "section": "sewing", "sewingFactory": "eco_cotton", "rate": "7"}
    ]
    assert len(_audits(sessions, ids)) == 4
    chain(sessions)
