"""November eligibility, bypass refusals and lossless atomic queue retirement."""
from datetime import timedelta
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from openpyxl import load_workbook
from sqlalchemy import select

from app.db.session import SessionLocal
from app.core.security import create_access_token
from app.libs.dto.planning.price_workflow_input import PriceRetirementTarget
from app.models.planning import variant_pricing_policy as policy
from app.models.planning import variant_pricing_reconciliation_service as retirement
from app.schemas import AuditLog, Model, PriceCalculationRequest, User
from app.tests.test_variant_price_workflow import setup, protected_facts, save_costs, submit


@pytest.mark.parametrize("offset", [-1, 0, 1])
@pytest.mark.parametrize("naive", [False, True])
def test_cutoff_is_tashkent_midnight_with_utc_storage(offset, naive):
    created = policy.CREATED_FROM + timedelta(microseconds=offset)
    if naive:
        created = created.replace(tzinfo=None)
    assert policy.eligible(SimpleNamespace(created_at=created, catalog_scope="standard", selling_price=None)) == (offset >= 0)


@pytest.mark.parametrize("scope,price,created,expected", [
    ("standard", None, policy.CREATED_FROM, True),
    ("standard", 0, policy.CREATED_FROM, True),
    ("standard", -1, policy.CREATED_FROM, True),
    ("standard", 1, policy.CREATED_FROM, False),
    ("usluga", None, policy.CREATED_FROM, False),
    ("standard", None, None, False),
])
def test_python_and_sql_eligibility_match(client, scope, price, created, expected):
    model = Model(code=f"POLICY-{scope}-{price}-{created}", name="Scope", catalog_scope=scope,
                  factory_code="ECO" if scope == "usluga" else None, selling_price=price)
    assert policy.eligible(SimpleNamespace(created_at=created, catalog_scope=scope, selling_price=price)) is expected
    if created is None:
        return  # Persisted timestamps are NOT NULL; malformed in-memory inputs refuse.
    model.created_at = created
    with SessionLocal() as db:
        db.add(model)
        db.commit()
        selected = db.query(Model.id).filter(Model.id == model.id, policy.predicate()).first()
        assert (selected is not None) is expected


@pytest.mark.parametrize("kind", ["old", "usluga", "priced"])
def test_manual_creation_and_reprice_cannot_bypass_scope(client, auth_headers, kind):
    data = setup(client, f"scope-create-{kind}")
    headers = auth_headers
    with SessionLocal() as db:
        model = db.get(Model, data["model_id"])
        if kind == "old":
            model.created_at = policy.CREATED_FROM - timedelta(microseconds=1)
        elif kind == "usluga":
            model.catalog_scope = "usluga"
            model.factory_code = "ECO"
            admin = db.query(User).filter_by(email="admin@example.com").one()
            admin.factory_code = "ECO"
            headers = {"Authorization": f"Bearer {create_access_token(admin.id, extra={'factory_code': 'ECO'})}"}
        else:
            model.selling_price = 7
        db.commit()
        before = protected_facts(db)
        count = db.query(PriceCalculationRequest).filter_by(model_id=model.id).count()
    for path, body in [("requests", {"model_id": data["model_id"], "reprice_reason": "Explicit reason"}),
                       (f"models/{data['model_id']}/reprice", {"reason": "Explicit reason"})]:
        response = client.post("/api/price-calculation/" + path, headers=headers, json=body)
        assert response.status_code == 409, response.text
    if kind == "usluga":
        saved = client.post("/api/cutting-passports", headers=headers,
            json=data["payload"] | {"passport_no": "AUTHORIZED-USLUGA-NO-PRICING"})
        assert saved.status_code == 201, saved.text
    with SessionLocal() as db:
        assert db.query(PriceCalculationRequest).filter_by(model_id=data["model_id"]).count() == count
        assert protected_facts(db) == before


def test_sql_predicate_matches_both_sides_of_exact_cutoff(client):
    with SessionLocal() as db:
        models = []
        wanted = set()
        for naive in (False, True):
            for offset in (-1, 0, 1):
                created = policy.CREATED_FROM + timedelta(microseconds=offset)
                if naive:
                    created = created.replace(tzinfo=None)
                model = Model(code=f"POLICY-BOUNDARY-{naive}-{offset}", name="Boundary", created_at=created)
                db.add(model)
                db.flush()
                models.append(model.id)
                if offset >= 0:
                    wanted.add(model.id)
        db.commit()
        actual = {row.id for row in db.query(Model.id).filter(Model.id.in_(models), policy.predicate())}
        assert actual == wanted


def test_ineligible_source_delete_keeps_submissions_with_replacement_available(client, auth_headers):
    data = setup(client, "scope-delete-source")
    replacement = client.post("/api/cutting-passports", headers=data["cutting"],
        json=data["payload"] | {"passport_no": "SCOPE-REPLACEMENT"})
    assert replacement.status_code == 201
    request = submit(client, data, "accessories", submit(client, data, "purchasing", save_costs(client, data)))
    with SessionLocal() as db:
        db.get(Model, data["model_id"]).created_at = policy.CREATED_FROM - timedelta(days=1)
        db.commit()
        row = db.get(PriceCalculationRequest, request["id"])
        before = (row.materials_json, row.accessories_json, row.sewing_cost, row.passport_snapshot_json,
                  row.purchasing_submitted_at, row.accessories_submitted_at)
    result = client.delete(f"/api/cutting-passports/{data['passport']['id']}", headers=auth_headers)
    assert result.status_code == 204, result.text
    with SessionLocal() as db:
        row = db.get(PriceCalculationRequest, request["id"])
        assert row.workflow_state == "cancelled" and row.active_model_id is None and row.cutting_passport_id is None
        assert before == (row.materials_json, row.accessories_json, row.sewing_cost, row.passport_snapshot_json,
                          row.purchasing_submitted_at, row.accessories_submitted_at)
        assert row.approval_snapshot_json


def test_move_passport_to_old_variant_detaches_without_creating_target_request(client):
    data = setup(client, "scope-move-source")
    with SessionLocal() as db:
        old = Model(code="POLICY-OLD-TARGET", name="Old target", created_at=policy.CREATED_FROM - timedelta(days=1))
        db.add(old)
        db.commit()
        old_id = old.id
    saved = client.patch(f"/api/cutting-passports/{data['passport']['id']}", headers=data["cutting"],
        json=data["payload"] | {"model_code": "POLICY-OLD-TARGET"})
    assert saved.status_code == 200, saved.text
    with SessionLocal() as db:
        prior = db.get(PriceCalculationRequest, data["request_id"])
        assert prior.workflow_state == "cancelled" and prior.cutting_passport_id is None
        assert db.query(PriceCalculationRequest).filter_by(model_id=old_id).count() == 0


def test_ineligible_active_request_is_hidden_and_all_mutations_refuse_but_cancel_works(client, auth_headers):
    data = setup(client, "scope-mutations")
    request = submit(client, data, "accessories", submit(client, data, "purchasing", save_costs(client, data)))
    with SessionLocal() as db:
        db.get(Model, data["model_id"]).created_at = policy.CREATED_FROM - timedelta(microseconds=1)
        db.commit()
        before = protected_facts(db)
        saved = db.get(PriceCalculationRequest, request["id"])
        costs = (saved.materials_json, saved.accessories_json, saved.sewing_cost,
                 saved.purchasing_submitted_at, saved.accessories_submitted_at, saved.passport_snapshot_json)
    for queue in ("pending", "approval"):
        response = client.get(f"/api/price-calculation/requests?queue={queue}", headers=auth_headers)
        assert response.status_code == 200 and all(row["id"] != request["id"] for row in response.json())
    for status in ("pending", "approval"):
        assert client.get(f"/api/price-calculation/report?status={status}&q=scope-mutations", headers=auth_headers).json() == []
        export = client.get(f"/api/price-calculation/report.xlsx?status={status}&q=scope-mutations", headers=auth_headers)
        assert export.status_code == 200
        assert load_workbook(BytesIO(export.content))["Variant Prices"].max_row == 1
    base = f"/api/price-calculation/requests/{request['id']}"
    actions = [("patch", "purchasing", {"sewing_cost": 2}), ("patch", "accessories", {"accessories": []}),
               ("patch", "finance", {"selling_price": 8}), ("patch", "cutting", {"kroy_no": "SOURCE"}),
               ("post", "submit/purchasing", {}), ("post", "submit/accessories", {}),
               ("post", "return", {"team": "purchasing", "reason": "Check costs"}),
               ("post", "approve", {"selling_price": 8})]
    for method, action, body in actions:
        response = getattr(client, method)(base + "/" + action, headers=auth_headers,
            json={"expected_revision": request["revision"], **body})
        assert response.status_code == 409, (action, response.text)
    history = client.get(f"/api/price-calculation/models/{data['model_id']}/history", headers=auth_headers)
    assert history.status_code == 200 and any(row["id"] == request["id"] for row in history.json())
    cancelled = client.post(base + "/cancel", headers=auth_headers,
        json={"expected_revision": request["revision"], "reason": "Outside November pricing scope"})
    assert cancelled.status_code == 200 and cancelled.json()["workflow_state"] == "cancelled"
    with SessionLocal() as db:
        saved = db.get(PriceCalculationRequest, request["id"])
        assert costs == (saved.materials_json, saved.accessories_json, saved.sewing_cost,
                         saved.purchasing_submitted_at, saved.accessories_submitted_at, saved.passport_snapshot_json)
        assert protected_facts(db) == before


def test_old_passport_save_retires_slot_without_blocking_or_recreating(client):
    data = setup(client, "scope-passport")
    with SessionLocal() as db:
        db.get(Model, data["model_id"]).created_at = policy.CREATED_FROM - timedelta(microseconds=1)
        db.commit()
    for index in range(2):
        result = client.post("/api/cutting-passports", headers=data["cutting"],
            json=data["payload"] | {"passport_no": f"OLD-SCOPE-{index}"})
        assert result.status_code == 201, result.text
    with SessionLocal() as db:
        request = db.get(PriceCalculationRequest, data["request_id"])
        assert request.workflow_state == "cancelled" and request.active_model_id is None
        assert db.query(PriceCalculationRequest).filter_by(model_id=data["model_id"]).count() == 1


def test_retirement_is_atomic_preserves_history_and_rejects_stale_manifest(client, monkeypatch):
    first = setup(client, "scope-retire-a")
    second = setup(client, "scope-retire-b")
    ready = submit(client, first, "accessories", submit(client, first, "purchasing", save_costs(client, first)))
    with SessionLocal() as db:
        for data in (first, second):
            db.get(Model, data["model_id"]).created_at = policy.CREATED_FROM - timedelta(days=1)
        db.commit()
        admin = db.query(User).filter_by(email="admin@example.com").one()
        preview = retirement.reconcile(db, admin)
        targets = [PriceRetirementTarget.model_validate(row) for row in preview["targets"]]
        assert len(targets) == 2
        before = protected_facts(db)
        table = PriceCalculationRequest.__table__
        original = {row.id: dict(row._mapping) for row in db.execute(select(table))}
        audits = db.query(AuditLog).count()
        real = retirement.workflow.retire_request
        def fail_second(session, request, actor, reason):
            if request.id == second["request_id"]:
                raise RuntimeError("Synthetic batch failure")
            return real(session, request, actor, reason)
        with monkeypatch.context() as scoped:
            scoped.setattr(retirement.workflow, "retire_request", fail_second)
            with pytest.raises(RuntimeError, match="Synthetic batch failure"):
                retirement.reconcile(db, admin, targets, apply=True)
            db.rollback()
        assert {row.id: dict(row._mapping) for row in db.execute(select(table))} == original
        assert db.query(AuditLog).count() == audits
        stale = [row.model_copy(update={"expected_revision": row.expected_revision + 1}) for row in targets]
        with pytest.raises(HTTPException) as error:
            retirement.reconcile(db, admin, stale, apply=True)
        assert error.value.status_code == 409
        db.rollback()
        result = retirement.reconcile(db, admin, targets, apply=True)
        assert result["readback_verified"]
        for row in db.execute(select(table)):
            values = dict(row._mapping)
            if row.id in {first["request_id"], second["request_id"]}:
                assert values.pop("workflow_state") == "cancelled"
                assert values.pop("active_model_id") is None
                assert values.pop("revision") == original[row.id]["revision"] + 1
                values.pop("correction_reason")
                values.pop("updated_at")
                assert values == {k: v for k, v in original[row.id].items() if k not in {"workflow_state", "active_model_id", "revision", "correction_reason", "updated_at"}}
            else:
                assert values == original[row.id]
        assert protected_facts(db) == before
        assert db.get(PriceCalculationRequest, ready["id"]).purchasing_submitted_at is not None


def test_factory_wildcard_cannot_retire_cross_factory_requests(client):
    with SessionLocal() as db:
        scoped = User(name="Factory wildcard", email="scope-wildcard@example.invalid", password_hash="unused",
                      factory_code="MIL", extra_permissions=["*"])
        db.add(scoped)
        db.commit()
        for apply, targets in ((False, None), (True, [])):
            with pytest.raises(HTTPException) as error:
                retirement.reconcile(db, scoped, targets, apply=apply)
            assert error.value.status_code == 403
