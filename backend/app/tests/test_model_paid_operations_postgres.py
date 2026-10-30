"""Paid-operation PATCH integration checks on the approved disposable PG target."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import json
from queue import Queue
from threading import Barrier
from time import monotonic, sleep
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import object_session

from app.api.routes.catalog import router as catalog_router
from app.api.routes.usluga import router as usluga_router
from app.core.deps import get_db
from app.core.security import create_access_token
from app.libs.dto.catalog.model_input import ModelCreateIn, ModelPaidOperationsIn, PaidOperationIn
from app.libs.enums.catalog import (
    PaidOperationFactory,
    PaidOperationQuantityMode,
    PaidOperationSplitMode,
    PaidProcessSection,
)
from app.models.catalog import models_service
from app.models.factory_scope_service import bind_session_factory
from app.schemas import AuditLog, CollectionModel, Department, Model, ModelBOM, ModelColor, ModelImage, ModelSize, Role, SystemSetting, User
from app.tests.test_customer_create_postgres import chain, customer_pg_sessions  # noqa: F401


def _actor(sessions, permissions, factory="MIL", *, role_name=None, department_code=None):
    with sessions.begin() as db:
        role = Role(name=role_name or f"Paid operation PG {uuid4().hex}", permissions=permissions)
        department = None
        if department_code:
            department = db.query(Department).filter_by(code=department_code).one_or_none()
            if department is None:
                department = Department(name=f"Synthetic {department_code} {uuid4().hex}", code=department_code)
                db.add(department)
        db.add(role)
        db.flush()
        user = User(
            name="Paid operation PG actor",
            email=f"paid-operation-{uuid4().hex}@example.invalid",
            password_hash="unused",
            factory_code=factory,
            role_id=role.id,
            department_id=department.id if department else None,
            is_active=True,
        )
        db.add(user)
        db.flush()
        return user.id


def _client(sessions, *, include_usluga=False):
    app = FastAPI()
    app.include_router(catalog_router, prefix="/api")
    if include_usluga:
        app.include_router(usluga_router, prefix="/api")

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
        if legacy:
            members.append(Model(
                code=f"{model_no}-LEGACY",
                name="Imported row",
                details_json={"general": {"model_no": model_no}, "legacy_import": True,
                              "paid_operations": [{"id": "legacy", "section": "historic"}]},
            ))
        db.add_all(members)
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
            json={"sewing_factory": "milana", "paid_operations": [
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
    if writer == "dedicated":
        assert {row["sewingFactory"] for row in saved["paid_operations"]} == {"eco_cotton"}
    else:
        assert all("sewingFactory" not in row for row in saved["paid_operations"])
    assert all(row["extra"] == {"keep": True} for row in saved["paid_operations"])
    assert len(_audits(sessions, [model_id])) == 1
    chain(sessions)


@pytest.mark.parametrize("scope", ["standard", "usluga"], ids=["standard-create", "usluga-create"])
def test_pg_model_create_uses_typed_paid_operation_rows_and_keeps_open_metadata(customer_pg_sessions, monkeypatch, scope):
    sessions = customer_pg_sessions
    factory = "ECO" if scope == "usluga" else "MIL"
    actor_id = _actor(sessions, ["*"], factory)
    code = f"CREATE-TYPED-{uuid4().hex[:8]}"
    details = {
        "general": {"model_no": code},
        "paid_operations": [{
            "id": "create-row",
            "section": "sewing",
            "sewingFactory": "ECO" if scope == "usluga" else "MIL",
            "rate": "3.50",
            "quantityMode": "batch",
            "editorExtension": {"keep": True},
        }],
        "unrelated_extension": {"keep": ["historic", 0, False]},
    }
    url = "/api/usluga/models" if scope == "usluga" else "/api/models"
    invalid_code = f"CREATE-INVALID-{uuid4().hex[:8]}"
    from app.schemas.catalog.model_persistence import insert_model as actual_insert_model

    insert_witnesses = []

    def witness_insert(db, command):
        assert command.details_json.has_paid_operations
        assert isinstance(command.details_json.paid_operations[0], PaidOperationIn)
        model = actual_insert_model(db, command)
        assert object_session(model) is db
        insert_witnesses.append((db, model.id))
        return model

    with monkeypatch.context() as patch:
        patch.setattr(models_service, "insert_model", witness_insert)
        with _client(sessions, include_usluga=(scope == "usluga")) as client:
            schema = client.app.openapi()
            request_ref = schema["paths"][url]["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"]
            assert request_ref.endswith("/ModelCreateIn")
            response_ref = schema["paths"][url]["post"]["responses"]["201"]["content"]["application/json"]["schema"]["$ref"]
            assert response_ref.endswith("/ModelCreateOut")
            details_schema = schema["components"]["schemas"]["ModelCreateDetailsIn"]
            assert "PaidOperationIn" in json.dumps(details_schema["properties"]["paid_operations"])
            assert details_schema["additionalProperties"] is True
            output_details = schema["components"]["schemas"]["ModelCreateDetailsOut"]
            assert "PaidOperationOut" in json.dumps(output_details["properties"]["paid_operations"])
            assert output_details["additionalProperties"] is True
            response = client.post(url, headers=_headers(actor_id, factory), json={
                "code": code, "name": "Typed paid-operation CREATE", "details_json": details,
                "status": "legacy-review-state",
            })
    assert response.status_code == 201, response.text
    assert len(insert_witnesses) == 1 and insert_witnesses[0][1] == response.json()["id"]
    saved = _stored(sessions, response.json()["id"])
    assert saved["general"] == details["general"]
    assert saved["unrelated_extension"] == details["unrelated_extension"]
    assert response.json()["status"] == "legacy-review-state"
    assert saved["paid_operations"] == [{
        "id": "create-row",
        "section": "sewing",
        "sewingFactory": "eco_cotton" if scope == "usluga" else "milana",
        "rate": "3.50",
        "quantityMode": "batch",
        "editorExtension": {"keep": True},
    }]
    before_audits = len(_audits(sessions, [response.json()["id"]]))
    with sessions() as db:
        created = db.query(Model).filter_by(code=code).one()
        assert created.catalog_scope == scope
        assert created.factory_code == ("ECO" if scope == "usluga" else None)
        assert db.query(ModelImage).filter_by(model_id=created.id).count() == 0
        assert db.query(ModelSize).filter_by(model_id=created.id).count() == 0
        assert db.query(ModelColor).filter_by(model_id=created.id).count() == 0
        assert db.query(ModelBOM).filter_by(model_id=created.id).count() == 0
        assert db.query(CollectionModel).filter_by(model_id=created.id).count() == 0
        created_id = created.id
    with _client(sessions) as client:
        invalid = client.post(url, headers=_headers(actor_id, factory), json={
            "code": invalid_code, "name": "Invalid new row",
            "details_json": {"paid_operations": [{"section": "historic-section", "rate": True}]},
        })
    assert invalid.status_code == 422, invalid.text
    with sessions() as db:
        assert db.query(Model).filter_by(code=invalid_code).count() == 0
        assert db.get(Model, created_id) is not None
        assert len(_audits(sessions, [created_id])) == before_audits == 1
    chain(sessions)


@pytest.mark.parametrize(
    "case,scoped,details_rows,expected_rows_key,expected_rows",
    [
        ("omitted-unscoped", False, {}, None, None),
        (
            "sparse-row-explicit-null-unscoped",
            False,
            {"paid_operations": [{"section": "sewing", "rate": None, "sparseExtension": {"keep": True}}]},
            "paid_operations",
            [{"section": "sewing", "rate": None, "sparseExtension": {"keep": True}}],
        ),
        (
            "snake-scoped",
            True,
            {"paid_operations": [{"id": "snake", "section": "sewing", "sewingFactory": "MIL", "rate": "2.75", "rowExtra": {"keep": True}}]},
            "paid_operations",
            [{"id": "snake", "section": "sewing", "sewingFactory": "milana", "rate": "2.75", "rowExtra": {"keep": True}}],
        ),
        (
            "camel-scoped",
            True,
            {"paidOperations": [{"id": "camel", "section": "sewing", "sewingFactory": "MIL", "rate": "2.75"}]},
            "paid_operations",
            [{"id": "camel", "section": "sewing", "sewingFactory": "milana", "rate": "2.75"}],
        ),
        (
            "both-scoped-canonical-wins",
            True,
            {
                "paid_operations": [{"id": "canonical", "section": "sewing", "rate": "2.75"}],
                "paidOperations": [{"id": "alias", "section": "cutting", "rate": "1.25"}],
            },
            "paid_operations",
            [{"id": "canonical", "section": "sewing", "rate": "2.75"}],
        ),
        ("snake-null-scoped", True, {"paid_operations": None}, "paid_operations", []),
        ("camel-null-scoped", True, {"paidOperations": None}, "paid_operations", []),
        ("camel-null-unscoped", False, {"paidOperations": None}, "paidOperations", None),
    ],
    ids=[
        "omitted-unscoped",
        "sparse-row-explicit-null-unscoped",
        "snake-scoped",
        "camel-scoped",
        "both-scoped-canonical-wins",
        "snake-null-scoped",
        "camel-null-scoped",
        "camel-null-unscoped",
    ],
)
def test_pg_model_create_paid_operation_key_presence_and_scope_merge(
    customer_pg_sessions, case, scoped, details_rows, expected_rows_key, expected_rows
):
    sessions = customer_pg_sessions
    actor_id = (
        _actor(
            sessions,
            ["modeling.models"],
            "MIL",
            role_name=f"Synthetic Sewing Master {uuid4().hex}",
            department_code="MIL",
        )
        if scoped
        else _actor(sessions, ["*"])
    )
    code = f"CREATE-PRESENCE-{uuid4().hex[:8]}"
    details = {"general": {"model_no": code}, "open_extension": {"keep": [0, False]}, **details_rows}
    with _client(sessions) as client:
        response = client.post("/api/models", headers=_headers(actor_id, "MIL"), json={
            "code": code, "name": f"Paid-operation presence {case}", "details_json": details,
        })
    assert response.status_code == 201, response.text
    returned = response.json()["details_json"]
    saved = _stored(sessions, response.json()["id"])
    assert returned == saved
    assert returned["open_extension"] == {"keep": [0, False]}
    if expected_rows_key is None:
        assert "paid_operations" not in returned and "paidOperations" not in returned
    else:
        assert returned[expected_rows_key] == expected_rows
        other_key = "paidOperations" if expected_rows_key == "paid_operations" else "paid_operations"
        assert other_key not in returned
    chain(sessions)


def test_pg_model_create_keeps_preexisting_opaque_paid_operation_json_readable(customer_pg_sessions):
    sessions = customer_pg_sessions
    actor_id = _actor(sessions, ["*"])
    code = f"CREATE-OPAQUE-READ-{uuid4().hex[:8]}"
    historical = {
        "general": {"model_no": code},
        "paid_operations": [{"id": "old", "section": "historic-section", "rate": True,
                             "company": "MIL", "quantityMode": "retired", "extension": {"keep": True}}],
    }
    with sessions.begin() as db:
        row = Model(code=code, name="Existing opaque historical JSON", details_json=historical)
        db.add(row)
        db.flush()
        model_id = row.id
    with _client(sessions) as client:
        response = client.get(f"/api/models/{model_id}", headers=_headers(actor_id))
    assert response.status_code == 200, response.text
    assert response.json()["details_json"] == historical
    assert _stored(sessions, model_id) == historical


def test_pg_legacy_variant_create_retains_payload_approval_without_family_sibling(customer_pg_sessions):
    sessions = customer_pg_sessions
    actor_id = _actor(sessions, ["*"])
    code = f"LEGACY-CREATE-{uuid4().hex[:8]}-V1"
    with _client(sessions) as client:
        response = client.post("/api/models", headers=_headers(actor_id), json={
            "code": code,
            "name": "Legacy approved variant",
            "status": "approved",
            "details_json": {
                "legacy_import": True,
                "general": {"model_no": code.rsplit("-V1", 1)[0], "variant_no": "V1"},
            },
        })
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "approved"
    assert response.json()["approved_by"] is None
    assert response.json()["approved_at"] is None
    with sessions() as db:
        saved = db.query(Model).filter_by(code=code).one()
        assert saved.status == "approved"
        assert saved.approved_by is None and saved.approved_at is None
    chain(sessions)


def test_pg_model_create_wrong_factory_paid_operation_refuses_before_writes(customer_pg_sessions):
    sessions = customer_pg_sessions
    from app.models.numbering_service import next_model_no

    actor_id = _actor(
        sessions,
        ["modeling.models"],
        "MIL",
        role_name=f"Synthetic Sewing Master {uuid4().hex}",
        department_code="MIL",
    )
    with sessions() as db:
        audit_count_before = db.query(AuditLog).filter(AuditLog.entity_type == "Model").count()
        model_count_before = db.query(Model).count()
        setting_before = db.query(SystemSetting).filter_by(key="model_numbering").one_or_none()
        numbering_before = deepcopy(setting_before.value_json) if setting_before else None
        expected_code = next_model_no(db, "XJ")
        assert db.query(Model).filter_by(code=expected_code).count() == 0
    with _client(sessions) as client:
        response = client.post("/api/models", headers=_headers(actor_id, "MIL"), json={
            "code": "ignored-preview",
            "name": "Must not create a Besttex operation as Milana",
            "automatic_model_prefix": "XJ",
            "details_json": {"paid_operations": [{
                "id": "wrong-factory", "section": "sewing", "sewingFactory": "BST", "rate": "1.00",
            }]},
        })
    assert response.status_code == 403, response.text
    with sessions() as db:
        assert db.query(Model).count() == model_count_before
        assert db.query(Model).filter_by(code=expected_code).count() == 0
        assert db.query(AuditLog).filter(AuditLog.entity_type == "Model").count() == audit_count_before
        setting = db.query(SystemSetting).filter_by(key="model_numbering").one_or_none()
        assert (deepcopy(setting.value_json) if setting else None) == numbering_before
    chain(sessions)


def test_pg_model_create_audit_failure_rolls_back_then_same_session_retry(customer_pg_sessions, monkeypatch):
    sessions = customer_pg_sessions
    actor_id = _actor(sessions, ["*"])
    code = f"CREATE-RETRY-{uuid4().hex[:8]}"
    payload = ModelCreateIn(code=code, name="CREATE retry", details_json={"extra": {"kept": True}})
    original_audit = models_service.log_action
    failed = []

    def fail_first_audit(*args, **kwargs):
        if not failed:
            failed.append(True)
            raise RuntimeError("injected Model CREATE audit failure")
        return original_audit(*args, **kwargs)

    with sessions() as db:
        actor = db.get(User, actor_id)
        audit_count_before = db.query(AuditLog).filter(AuditLog.entity_type == "Model").count()
        with monkeypatch.context() as patch:
            patch.setattr(models_service, "log_action", fail_first_audit)
            with pytest.raises(RuntimeError, match="injected Model CREATE audit failure"):
                models_service.create_model(actor, db, payload)
            db.rollback()
            assert db.query(Model).filter_by(code=code).count() == 0
            assert db.query(AuditLog).filter(AuditLog.entity_type == "Model").count() == audit_count_before
            created = models_service.create_model(actor, db, payload)
            model_id = created["id"]
    with sessions() as db:
        assert db.get(Model, model_id).details_json == {"extra": {"kept": True}, "general": {"model_no": code}}
        assert len(_audits(sessions, [model_id])) == 1
        assert db.query(AuditLog).filter(AuditLog.entity_type == "Model").count() == audit_count_before + 1
    chain(sessions)


def test_pg_model_create_automatic_number_and_model_rollback_retry_together(customer_pg_sessions, monkeypatch):
    sessions = customer_pg_sessions
    actor_id = _actor(sessions, ["*"])
    baseline = {"last_assigned": {"XJ": 7300}, "other": {"keep": True}}
    with sessions.begin() as db:
        setting = db.query(SystemSetting).filter_by(key="model_numbering").one_or_none()
        if setting is None:
            setting = SystemSetting(key="model_numbering", value_json=deepcopy(baseline))
            db.add(setting)
        else:
            setting.value_json = deepcopy(baseline)
    original_audit = models_service.log_action
    failed = []

    def fail_first_audit(*args, **kwargs):
        if not failed:
            failed.append(True)
            raise RuntimeError("injected automatic Model CREATE audit failure")
        return original_audit(*args, **kwargs)

    with sessions() as db:
        actor = db.get(User, actor_id)
        audit_count_before = db.query(AuditLog).filter(AuditLog.entity_type == "Model").count()
        with monkeypatch.context() as patch:
            patch.setattr(models_service, "log_action", fail_first_audit)
            with pytest.raises(RuntimeError, match="injected automatic Model CREATE audit failure"):
                models_service.create_model(
                    actor,
                    db,
                    ModelCreateIn(code="ignored-preview", name="Automatic retry", automatic_model_prefix="XJ"),
                )
            db.rollback()
            assert db.query(Model).filter_by(code="XJ7301").count() == 0
            assert db.query(SystemSetting).filter_by(key="model_numbering").one().value_json == baseline
            assert db.query(AuditLog).filter(AuditLog.entity_type == "Model").count() == audit_count_before
            created = models_service.create_model(
                actor,
                db,
                ModelCreateIn(code="ignored-preview", name="Automatic retry", automatic_model_prefix="XJ"),
            )
    assert created["code"] == "XJ7301"
    with sessions() as db:
        assert db.query(SystemSetting).filter_by(key="model_numbering").one().value_json == {
            "last_assigned": {"XJ": 7301}, "other": {"keep": True},
        }
        assert db.query(Model).filter_by(code="XJ7301").count() == 1
        assert db.query(AuditLog).filter(AuditLog.entity_type == "Model").count() == audit_count_before + 1
    chain(sessions)


def test_pg_model_create_variant_waits_for_family_approval_lock(customer_pg_sessions, record_property):
    sessions = customer_pg_sessions
    actor_id = _actor(sessions, ["*"])
    family_code = f"CREATE-LOCK-{uuid4().hex[:8]}"
    approved_at = datetime.now(timezone.utc)
    with sessions.begin() as db:
        base = Model(
            code=family_code,
            name="Approved CREATE family",
            status="approved",
            approved_by=actor_id,
            approved_at=approved_at,
            catalog_scope="standard",
            details_json={"general": {"model_no": family_code}},
        )
        db.add(base)
        db.flush()
        base_id = base.id
    lock_key = f"model-approval:standard:model:{family_code.casefold()}"

    def create_variant(actor_id, variant_no, start, pid_queue):
        with sessions() as db:
            db.execute(text("SET LOCAL lock_timeout = '9s'"))
            db.execute(text("SET LOCAL statement_timeout = '18s'"))
            actor = db.get(User, actor_id)
            pid_queue.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            start.wait(timeout=8)
            return models_service.create_model(
                actor,
                db,
                ModelCreateIn(
                    code=f"{family_code}-V-{variant_no}",
                    name="Approved CREATE variant",
                    details_json={"general": {"model_no": family_code, "variant_no": variant_no}},
                ),
            )

    holder = sessions()
    holder_pid = holder.execute(text("SELECT pg_backend_pid()")).scalar_one()
    holder.execute(text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"), {"lock_key": lock_key})
    pool = ThreadPoolExecutor(max_workers=2)
    start = Barrier(3)
    pid_queue = Queue()
    workers = [pool.submit(create_variant, actor_id, value, start, pid_queue) for value in ("2", "3")]
    observer = sessions()
    worker_pids = set()
    lock_witnesses = {}
    wait_diagnostics = {}
    snapshot_refreshes = 0
    try:
        worker_pids = {pid_queue.get(timeout=5), pid_queue.get(timeout=5)}
        start.wait(timeout=8)
        deadline = monotonic() + 8
        while monotonic() < deadline:
            observer.execute(text("SELECT pg_stat_clear_snapshot()"))
            snapshot_refreshes += 1
            for worker_pid in worker_pids:
                state = observer.execute(text("""
                    SELECT wait_event_type, wait_event, pg_blocking_pids(pid) AS blocking_pids
                    FROM pg_stat_activity WHERE pid = :pid
                """), {"pid": worker_pid}).mappings().one_or_none()
                if state is None:
                    continue
                advisory = observer.execute(text("""
                    SELECT mode, granted FROM pg_locks
                    WHERE pid = :pid AND locktype = 'advisory'
                """), {"pid": worker_pid}).mappings().all()
                seen = set(state["blocking_pids"] or ())
                frontier = list(seen)
                while frontier and holder_pid not in seen:
                    parent_pid = frontier.pop()
                    blockers = observer.execute(
                        text("SELECT pg_blocking_pids(:pid)"), {"pid": parent_pid}
                    ).scalar_one()
                    for blocker_pid in blockers:
                        if blocker_pid not in seen:
                            seen.add(blocker_pid)
                            frontier.append(blocker_pid)
                wait_diagnostics[worker_pid] = {
                    "wait_event_type": state["wait_event_type"],
                    "wait_event": state["wait_event"],
                    "advisory_locks": [dict(row) for row in advisory],
                    "blocker_chain": sorted(seen),
                }
                if (
                    state["wait_event_type"] == "Lock"
                    and any(not row["granted"] for row in advisory)
                    and holder_pid in seen
                ):
                    lock_witnesses[worker_pid] = wait_diagnostics[worker_pid]
            if set(lock_witnesses) == worker_pids:
                break
            if all(worker.done() for worker in workers):
                break
            sleep(0.05)
        record_property(
            "model_create_family_lock_witnesses",
            json.dumps({
                "holder_pid": holder_pid,
                "worker_pids": sorted(worker_pids),
                "snapshot_refreshes": snapshot_refreshes,
                "witnesses": lock_witnesses,
                "last_wait_diagnostics": wait_diagnostics,
            }, sort_keys=True),
        )
        assert set(lock_witnesses) == worker_pids, (
            "both Model CREATE workers must wait on the held family advisory lock; "
            f"pids={sorted(worker_pids)}, witnesses={lock_witnesses}, last={wait_diagnostics}"
        )
    finally:
        try:
            holder.rollback()
        finally:
            try:
                holder.close()
            finally:
                try:
                    observer.close()
                finally:
                    pool.shutdown(wait=True, cancel_futures=True)
    results = [worker.result(timeout=0) for worker in workers]
    assert {row["status"] for row in results} == {"approved"}
    created_ids = [row["id"] for row in results]
    with sessions() as db:
        base = db.get(Model, base_id)
        assert base.status == "approved" and base.approved_by == actor_id and base.approved_at == approved_at
        created = [db.get(Model, model_id) for model_id in created_ids]
        assert {row.status for row in created} == {"approved"}
        assert {row.approved_by for row in created} == {actor_id}
        assert {row.approved_at for row in created} == {approved_at}
        audits = db.query(AuditLog).filter(
            AuditLog.entity_type == "Model", AuditLog.entity_id.in_(created_ids), AuditLog.action == "create"
        ).all()
        assert len(audits) == 2
    chain(sessions)


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


def test_pg_paid_operations_concurrent_factories_serialize_same_family_and_prove_row_lock_wait(
    customer_pg_sessions, record_property
):
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
                "sewing_factory": {"MIL": "milana", "BST": "besttex"}[factory],
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
    start = Barrier(3)
    workers = [
        pool.submit(save, actor_id, factory, prefix, start, worker_pid)
        for actor_id, factory, prefix in ((mil_id, "MIL", "mil"), (bst_id, "BST", "bst"))
    ]
    observer = sessions()
    lock_witnesses = {}
    wait_diagnostics = {}
    blocked_pids = set()
    snapshot_refreshes = 0
    try:
        blocked_pids = {worker_pid.get(timeout=5), worker_pid.get(timeout=5)}
        # Join after both worker connections are known while the holder still
        # owns the family row, then start the 8s observer.
        start.wait(timeout=8)
        wait_diagnostics = {pid: {} for pid in blocked_pids}
        deadline = monotonic() + 8
        while monotonic() < deadline:
            observer.execute(text("SELECT pg_stat_clear_snapshot()"))
            snapshot_refreshes += 1
            for blocked_pid in blocked_pids:
                state = observer.execute(text("""
                    SELECT wait_event_type, wait_event, query, length(query) AS query_length,
                           current_setting('track_activity_query_size') AS query_size_limit,
                           pg_blocking_pids(pid) AS blocking_pids
                      FROM pg_stat_activity WHERE pid = :pid
                """), {"pid": blocked_pid}).one_or_none()
                lock_rows = observer.execute(text("""
                    SELECT l.locktype, l.mode, l.granted, l.page, l.tuple,
                           l.transactionid, n.nspname, c.relname
                      FROM pg_locks AS l
                      LEFT JOIN pg_class AS c ON c.oid = l.relation
                      LEFT JOIN pg_namespace AS n ON n.oid = c.relnamespace
                     WHERE l.pid = :pid
                """), {"pid": blocked_pid}).mappings().all()
                if state:
                    model_row_share = any(
                        row["granted"] and row["locktype"] == "relation"
                        and row["nspname"] == "public" and row["relname"] == "models"
                        and row["mode"] == "RowShareLock"
                        for row in lock_rows
                    )
                    waiting_transaction = any(
                        not row["granted"] and row["locktype"] in {"transactionid", "tuple"}
                        for row in lock_rows
                    )
                    waiting_advisory = any(
                        not row["granted"] and row["locktype"] == "advisory"
                        for row in lock_rows
                    )
                    seen = set(state.blocking_pids or ())
                    frontier = list(seen)
                    while frontier:
                        parent_pid = frontier.pop()
                        blockers = observer.execute(text("SELECT pg_blocking_pids(:pid)"), {"pid": parent_pid}).scalar_one()
                        for blocker in blockers:
                            if blocker not in seen:
                                seen.add(blocker)
                                frontier.append(blocker)
                    expected_lock = (
                        (model_row_share and waiting_transaction)
                        or waiting_advisory
                    )
                    wait_diagnostics[blocked_pid] = {
                        "wait_event_type": state.wait_event_type,
                        "wait_event": state.wait_event,
                        "query_length": state.query_length,
                        "query_size_limit": state.query_size_limit,
                        "query_has_for_update": "for update" in (state.query or "").lower(),
                        "snapshot_refreshes": snapshot_refreshes,
                        "query_prefix": (state.query or "")[:100],
                        "model_row_share": model_row_share,
                        "waiting_transaction": waiting_transaction,
                        "waiting_advisory": waiting_advisory,
                        "non_granted_locks": [
                            {"locktype": row["locktype"], "mode": row["mode"],
                             "relation": f"{row['nspname']}.{row['relname']}" if row["relname"] else None,
                             "page": row["page"], "tuple": row["tuple"],
                             "transactionid": str(row["transactionid"]) if row["transactionid"] else None}
                            for row in lock_rows if not row["granted"]
                        ][:8],
                        "blocking_chain": (
                            ([holder_pid] if holder_pid in seen else [])
                            + sorted(seen - {holder_pid})[:15]
                        ),
                    }
                    if state.wait_event_type == "Lock" and holder_pid in seen and expected_lock:
                        lock_witnesses[blocked_pid] = wait_diagnostics[blocked_pid]
            if set(lock_witnesses) == blocked_pids or all(worker.done() for worker in workers):
                break
            sleep(0.02)
    finally:
        holder.rollback()
        holder.close()
        observer.close()
        pool.shutdown(wait=True, cancel_futures=True)
    for worker in workers:
        # Surface worker errors (for example a rejected enum request) before
        # reporting the more general absence of a lock-chain witness.
        worker.result(timeout=15)
    record_property(
        "paid_operations_postgres_lock_witnesses",
        json.dumps(
            {
                "holder_pid": holder_pid,
                "worker_pids": sorted(blocked_pids),
                "snapshot_refreshes": snapshot_refreshes,
                "witnesses": lock_witnesses,
            },
            sort_keys=True,
        ),
    )
    assert set(lock_witnesses) == blocked_pids, (
        "each worker needs a live PG lock wait witnessed by catalog/advisory locks and a blocker chain to the holder; "
        f"pids={sorted(blocked_pids)}, witnesses={lock_witnesses}, "
        f"snapshot_refreshes={snapshot_refreshes}, latest={wait_diagnostics}"
    )
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
