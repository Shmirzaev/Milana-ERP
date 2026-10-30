from copy import deepcopy
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.schemas import AuditLog, Item, Model, ModelBOM, SewingFlow, User
from app.models.paid_operations_service import filter_paid_operations_for_factory, merge_scoped_paid_operation_update
from app.libs.dto.catalog.model_input import ModelPaidOperationsIn, ModelUpdateIn, PaidOperationIn
from app.libs.enums.catalog import (
    PaidOperationFactory,
    PaidOperationQuantityMode,
    PaidOperationSplitMode,
    PaidProcessSection,
)
from app.schemas.catalog.model_paid_operations_persistence import persist_model_paid_operations
from app.models.catalog import models_service
from app.tests.conftest import TestSessionLocal
from app.tests.test_paid_operation_factory_scope import _create_payroll_manager, _operation
from app.tests.test_payroll import _create_employee


def _model(code, *, family="PJ1236", rows=(), scope="standard", legacy=False):
    with TestSessionLocal() as db:
        model = Model(code=code, name="Family paid operations", catalog_scope=scope,
                      details_json={"general": {"model_no": family}, "variant_note": code,
                                    "legacy_import": legacy, "paid_operations": deepcopy(list(rows))})
        db.add(model)
        db.commit()
        return model.id


def _save(client, headers, mid, rows, factory="milana"):
    return client.patch(f"/api/models/{mid}/paid-operations", headers=headers,
                        json={"paid_operations": rows, "sewing_factory": factory})


def _details(mid):
    with TestSessionLocal() as db:
        return deepcopy(db.get(Model, mid).details_json)


def test_save_applies_to_exact_family_preserves_other_factories_and_variant_fields(client, auth_headers):
    base = _model("PJ1236")
    selected = _model("PJ1236-V-6120", rows=[_operation("old", "milana")])
    hidden = _operation("besttex-only", "besttex")
    sibling = _model("PJ1236-V-6123", rows=[hidden])
    excluded = [
        _model("PJ12360-V-6123", family="PJ12360"),
        _model("SERVICE-PJ1236", scope="usluga"),
        _model("IMPORT-PJ1236", legacy=True),
    ]
    before = {mid: _details(mid) for mid in [base, selected, sibling, *excluded]}
    operations = [_operation("second", "milana"), _operation("first", "milana")]
    operations[0].update(rate="50.125", copies=2, splitMode="custom", splitQuantities=[3, 4])
    operations[1]["selected"] = False
    response = _save(client, auth_headers, selected, operations)
    assert response.status_code == 200, response.text
    for mid in [base, selected, sibling]:
        details = client.get(f"/api/models/{mid}", headers=auth_headers).json()["details_json"]
        assert filter_paid_operations_for_factory(details, "milana")["paid_operations"] == operations
        assert {k: v for k, v in details.items() if k != "paid_operations"} == {
            k: v for k, v in before[mid].items() if k != "paid_operations"}
    assert filter_paid_operations_for_factory(_details(sibling), "besttex")["paid_operations"] == [hidden]
    assert all(_details(mid) == before[mid] for mid in excluded)
    with TestSessionLocal() as db:
        audits = db.query(AuditLog).filter(AuditLog.action == "update_paid_operations").all()
        assert {row.entity_id for row in audits} == {base, selected, sibling}
        assert all(row.new_value_json["scope"] == "model_family" for row in audits)
    # Saving from a different variant updates the base and original selection too.
    assert _save(client, auth_headers, sibling, operations[:1]).status_code == 200
    for mid in [base, selected, sibling]:
        assert filter_paid_operations_for_factory(_details(mid), "milana")["paid_operations"] == operations[:1]


def test_payroll_family_save_cannot_override_factory_and_rejection_is_atomic(client, auth_headers):
    mids = [_model("PJ1236"), _model("PJ1236-V-6120"), _model("PJ1236-V-6123")]
    headers = _create_payroll_manager(client, auth_headers, "BST")
    before = {mid: _details(mid) for mid in mids}
    assert _save(client, headers, mids[1], [], "milana").status_code == 403
    assert _save(client, headers, mids[1], [_operation("bad", "milana")], "besttex").status_code == 403
    assert _save(client, auth_headers, mids[1], [], "unknown").status_code == 422
    assert all(_details(mid) == before[mid] for mid in mids)
    operations = [_operation("besttex", "besttex")]
    response = _save(client, headers, mids[1], operations, "besttex")
    assert response.status_code == 200, response.text
    assert all(_details(mid)["paid_operations"] == operations for mid in mids)


def test_typed_paid_operation_contract_preserves_extensions_and_rejects_invalid_values(client, auth_headers):
    mid = _model("TYPED-ROWS")
    row = {**_operation("typed", "MIL"), "selected": False, "copies": 0,
           "extension": {"empty": "", "list": []}}
    saved = _save(client, auth_headers, mid, [row])
    assert saved.status_code == 200, saved.text
    stored = _details(mid)["paid_operations"][0]
    assert stored["sewingFactory"] == "milana"
    assert stored["selected"] is False and stored["copies"] == 0
    assert stored["extension"] == {"empty": "", "list": []}

    edited_row = {**row, "quantityMode": "custom", "splitMode": "equal"}
    positive = client.patch(
        f"/api/models/{mid}", headers=auth_headers,
        json={"code": "TYPED-ROWS", "name": "Family paid operations",
              "details_json": {**_details(mid), "paid_operations": [edited_row], "editor_note": "kept"}},
    )
    assert positive.status_code == 200, positive.text
    readback = _details(mid)
    assert readback["paid_operations"] == [{**edited_row, "sewingFactory": "milana"}]
    assert readback["editor_note"] == "kept"

    snapshot = readback
    audits_before = _audit_count()
    rejected = _save(client, auth_headers, mid, [row, {**row, "section": "arbitrary"}])
    assert rejected.status_code == 422
    assert _details(mid) == snapshot
    assert _audit_count() == audits_before

    whole_model = client.patch(
        f"/api/models/{mid}", headers=auth_headers,
        json={"code": "TYPED-ROWS", "name": "Family paid operations",
              "details_json": {**snapshot, "paid_operations": [{**row, "quantityMode": "unbounded"}]}},
    )
    assert whole_model.status_code == 422
    assert _details(mid) == snapshot
    assert _audit_count() == audits_before

    malformed_known_field = client.patch(
        f"/api/models/{mid}", headers=auth_headers,
        json={"code": "TYPED-ROWS", "name": "Family paid operations",
              "details_json": {**snapshot, "paid_operations": [{**row, "splitQuantities": {"bad": True}}]}},
    )
    assert malformed_known_field.status_code == 422
    assert _details(mid) == snapshot
    assert _audit_count() == audits_before

    malformed_rate = _save(client, auth_headers, mid, [{**row, "rate": True}])
    assert malformed_rate.status_code == 422
    assert _details(mid) == snapshot
    assert _audit_count() == audits_before


def test_dedicated_patch_preserves_known_legacy_fallback_keys_on_the_wire(client, auth_headers):
    mid = _model("PAID-ALIAS-WIRE", family="PAID-ALIAS-WIRE")
    row = {
        "id": "fallback-row", "selected": True, "section": "sewing", "code": "",
        "name": "", "operation_name": "Backend alias name", "rate": 0,
        "sewingFactory": "MIL", "sourceOrder": None, "sequence": 2,
        "quantityMode": None, "quantity_mode": "custom", "splitMode": None,
        "split_mode": "equal", "splitQuantities": None, "split_quantities": [0, "4"],
        "extension": {"kept": False},
    }
    response = _save(client, auth_headers, mid, [row])
    assert response.status_code == 200, response.text
    expected = {**row, "sewingFactory": "milana"}
    assert response.json()["details_json"]["paid_operations"] == [expected]
    assert _details(mid)["paid_operations"] == [expected]

    whole_row = {**row, "id": "whole-fallback-row", "sequence": 7}
    whole = client.patch(
        f"/api/models/{mid}", headers=auth_headers,
        json={"code": "PAID-ALIAS-WIRE", "name": "Family paid operations",
              "details_json": {**_details(mid), "paid_operations": [whole_row]}},
    )
    assert whole.status_code == 200, whole.text
    whole_expected = {**whole_row, "sewingFactory": "milana"}
    assert whole.json()["details_json"]["paid_operations"] == [whole_expected]
    assert _details(mid)["paid_operations"] == [whole_expected]


def test_typed_paid_operation_row_enums_roundtrip_and_keep_omissions():
    for section in PaidProcessSection:
        row = PaidOperationIn(section=section)
        assert row.model_dump(exclude_unset=True, mode="json") == {"section": section.value}
    for factory in PaidOperationFactory:
        assert PaidOperationIn(sewingFactory=factory).model_dump(mode="json")["sewingFactory"] == factory.value
    for mode in PaidOperationQuantityMode:
        assert PaidOperationIn(quantityMode=mode).model_dump(mode="json")["quantityMode"] == mode.value
    for mode in PaidOperationSplitMode:
        assert PaidOperationIn(splitMode=mode).model_dump(mode="json")["splitMode"] == mode.value
    for rate in ("12.50", 12, 12.5):
        parsed = PaidOperationIn(rate=rate)
        assert parsed.rate == rate and type(parsed.rate) is type(rate)
    with pytest.raises(ValueError):
        PaidOperationIn(rate=True)

    row = PaidOperationIn.model_validate({"factory": "BST", "extension": {"enabled": False, "count": 0}})
    assert row.model_dump(exclude_unset=True, mode="json") == {
        "sewingFactory": "besttex", "factory": "BST", "extension": {"enabled": False, "count": 0},
    }

    company_only = PaidOperationIn.model_validate({"company": "BST", "name": "legacy"})
    assert not company_only.factory_was_explicit
    assert company_only.resolved_factory_hint == PaidOperationFactory.BESTTEX
    assert company_only.model_dump(exclude_unset=True, mode="json") == {"company": "BST", "name": "legacy"}

    mixed = PaidOperationIn.model_validate({"company": "BST", "sewingFactory": "milana"})
    assert mixed.factory_was_explicit
    assert mixed.resolved_factory_hint == PaidOperationFactory.MILANA
    assert mixed.model_dump(exclude_unset=True, mode="json") == {
        "sewingFactory": "milana", "company": "BST",
    }

    schema = PaidOperationIn.model_json_schema()
    assert set(schema["properties"]) == {
        "id", "selected", "section", "code", "name", "operation_name", "rate",
        "sewingFactory", "legacySourceId", "legacy_source_id", "sourceOrder",
        "source_order", "sequence", "duration", "operation_duration", "currency",
        "sourceStage", "source_stage", "originalStage", "original_stage", "stage",
        "changeDirection", "change_direction", "controlChangeDirection",
        "control_change_direction", "finalOperation", "final_operation", "final",
        "quantityMode", "quantity_mode", "customQuantity", "custom_quantity", "copies",
        "splitMode", "split_mode", "splitQuantities", "split_quantities",
    }
    assert "factory_was_explicit" not in schema["properties"]
    assert "resolved_factory_hint" not in schema["properties"]

    client_flags = PaidOperationIn.model_validate({
        "factory_was_explicit": True,
        "resolved_factory_hint": "besttex",
        "extension": "keep-me",
    })
    assert not client_flags.factory_was_explicit
    assert client_flags.resolved_factory_hint is None
    assert client_flags.model_dump(exclude_unset=True, mode="json") == {
        "factory_was_explicit": True,
        "resolved_factory_hint": "besttex",
        "extension": "keep-me",
    }

    known_row = PaidOperationIn.model_validate({
        "id": "op-1", "selected": False, "section": "sewing", "code": "OP-1",
        "name": "Stitch", "rate": "125.50", "sewingFactory": "milana",
        "legacySourceId": "old-1", "sourceOrder": "2", "duration": "1.25",
        "currency": "UZS", "sourceStage": "sewing", "changeDirection": "add",
        "finalOperation": True, "quantityMode": "custom", "customQuantity": "",
        "copies": 1.5, "splitMode": "equal", "splitQuantities": [0, "4", ""],
        "extension": {"kept": 0},
    })
    assert known_row.model_dump(exclude_unset=True, mode="json") == {
        "id": "op-1", "selected": False, "section": "sewing", "code": "OP-1",
        "name": "Stitch", "rate": "125.50", "sewingFactory": "milana",
        "legacySourceId": "old-1", "sourceOrder": "2", "duration": "1.25",
        "currency": "UZS", "sourceStage": "sewing", "changeDirection": "add",
        "finalOperation": True, "quantityMode": "custom", "customQuantity": "",
        "copies": 1.5, "splitMode": "equal", "splitQuantities": [0, "4", ""],
        "extension": {"kept": 0},
    }

    aliased_row = PaidOperationIn.model_validate({
        "operation_name": "Alias name", "source_stage": "sewing", "custom_quantity": "3",
        "split_quantities": ["2"], "company": "BST",
    })
    assert aliased_row.model_dump(exclude_unset=True, mode="json") == {
        "operation_name": "Alias name", "source_stage": "sewing", "custom_quantity": "3",
        "split_quantities": ["2"], "company": "BST",
    }

    fallback_row = PaidOperationIn.model_validate({
        "name": "", "operation_name": "Fallback name", "rate": 0, "selected": False,
        "sourceOrder": None, "sequence": 2, "quantityMode": None,
        "quantity_mode": "custom", "splitMode": None, "split_mode": "equal",
        "splitQuantities": None, "split_quantities": [0, "4"],
    })
    assert fallback_row.model_dump(exclude_unset=True, mode="json") == {
        "name": "", "operation_name": "Fallback name", "rate": 0, "selected": False,
        "sourceOrder": None, "sequence": 2, "quantityMode": None,
        "quantity_mode": "custom", "splitMode": None, "split_mode": "equal",
        "splitQuantities": None, "split_quantities": [0, "4"],
    }

    legacy_scoped = merge_scoped_paid_operation_update(
        {}, {"paid_operations": [{"company": "BST"}]}, [company_only], "milana",
    )
    assert legacy_scoped["paid_operations"] == [{"company": "BST", "name": "legacy"}]
    mixed_scoped = merge_scoped_paid_operation_update(
        {}, {"paid_operations": [{"company": "BST", "sewingFactory": "milana"}]}, [mixed], "milana",
    )
    assert mixed_scoped["paid_operations"] == [{"sewingFactory": "milana", "company": "BST"}]

    null_precedence = PaidOperationIn.model_validate({"sewingFactory": None, "factory": "BST"})
    with pytest.raises(HTTPException) as refused:
        merge_scoped_paid_operation_update(
            {}, {"paid_operations": [{"sewingFactory": None, "factory": "BST"}]},
            [null_precedence], "milana",
        )
    assert refused.value.status_code == 403

    raw_details = {"paid_operations": [{"section": "sewing", "company": "BST"}]}
    update = ModelUpdateIn(code="C", name="N", details_json=raw_details)
    assert update.model_dump(exclude_unset=True, mode="json")["details_json"] == raw_details
    assert update.paid_operations_update[0].section == PaidProcessSection.SEWING
    assert "paid_operations_update" not in update.model_dump()

    update_schema = ModelUpdateIn.model_json_schema()
    details_schema_ref = next(
        item["$ref"] for item in update_schema["properties"]["details_json"]["anyOf"]
        if "$ref" in item
    )
    details_schema = update_schema["$defs"][details_schema_ref.rsplit("/", 1)[-1]]
    assert details_schema["additionalProperties"] is True
    for key in ("paid_operations", "paidOperations"):
        assert "#/$defs/PaidOperationIn" in str(details_schema["properties"][key])

    omitted_details = ModelUpdateIn(code="C", name="N", details_json={})
    assert omitted_details.model_dump(exclude_unset=True, mode="json")["details_json"] == {}
    assert omitted_details.paid_operations_update is None

    explicit_null = ModelUpdateIn(code="C", name="N", details_json={"paid_operations": None})
    assert explicit_null.model_dump(exclude_unset=True, mode="json")["details_json"] == {"paid_operations": None}
    assert explicit_null.paid_operations_update is None

    camel_details = ModelUpdateIn(
        code="C", name="N", details_json={"paidOperations": [{"section": "sewing"}], "note": "kept"}
    )
    assert camel_details.paid_operations_update[0].section == PaidProcessSection.SEWING
    assert camel_details.model_dump(exclude_unset=True, mode="json")["details_json"] == {
        "paidOperations": [{"section": "sewing"}], "note": "kept",
    }


def test_paid_operation_persistence_uses_the_callers_session_and_does_not_commit():
    model_id = _model("PERSISTENCE-SESSION")
    with TestSessionLocal() as db:
        model = db.get(Model, model_id)
        original = deepcopy(model.details_json)
        updated = {**original, "paid_operations": [{"id": "session-row"}]}
        persist_model_paid_operations(db, model, updated)
        assert model.details_json == updated
        db.flush()
        db.rollback()

    assert _details(model_id) == original


def test_create_keeps_legacy_paid_operation_json_opaque(client, auth_headers):
    code = f"OPAQUE-{uuid4().hex[:8]}"
    legacy_details = {
        "general": {"model_no": code},
        "paid_operations": [{"id": "legacy", "section": "old-section", "company": "MIL",
                             "quantityMode": "historical-mode", "extension": {"kept": True}}],
    }
    response = client.post(
        "/api/models", headers=auth_headers,
        json={"code": code, "name": "Opaque create", "details_json": legacy_details},
    )
    assert response.status_code == 201, response.text
    assert response.json()["details_json"] == legacy_details


def test_paid_operation_audit_failure_rolls_back_and_retry_succeeds(monkeypatch):
    model_id = _model("PAID-AUDIT-RETRY", family="PAID-AUDIT-RETRY")
    original_details = _details(model_id)
    original_audit = models_service.log_action

    def fail_after_audit(*args, **kwargs):
        original_audit(*args, **kwargs)
        raise RuntimeError("injected paid-operation audit failure")

    monkeypatch.setattr(models_service, "log_action", fail_after_audit)
    with TestSessionLocal() as db:
        actor = db.query(User).filter(User.email == "admin@example.com").one()
        payload = ModelPaidOperationsIn(
            paid_operations=[PaidOperationIn(section="sewing", sewingFactory="milana", name="Retry")],
            sewing_factory="milana",
        )
        with pytest.raises(RuntimeError, match="injected paid-operation audit failure"):
            models_service.update_model_paid_operations(actor, db, model_id, payload)
        db.rollback()

    assert _details(model_id) == original_details
    with TestSessionLocal() as db:
        assert db.query(AuditLog).filter_by(entity_id=model_id, action="update_paid_operations").count() == 0
    monkeypatch.setattr(models_service, "log_action", original_audit)
    with TestSessionLocal() as db:
        actor = db.query(User).filter(User.email == "admin@example.com").one()
        models_service.update_model_paid_operations(actor, db, model_id, payload)
    assert _details(model_id)["paid_operations"][0]["name"] == "Retry"


def test_paid_operation_flush_failure_rolls_back_and_retry_succeeds():
    model_id = _model("PAID-FLUSH-RETRY", family="PAID-FLUSH-RETRY")
    original_details = _details(model_id)
    payload = ModelPaidOperationsIn(
        paid_operations=[PaidOperationIn(section="sewing", sewingFactory="milana", name="Flush retry")],
        sewing_factory="milana",
    )
    with TestSessionLocal() as db:
        actor = db.query(User).filter(User.email == "admin@example.com").one()
        original_flush = db.flush

        def fail_after_flush(*args, **kwargs):
            original_flush(*args, **kwargs)
            raise RuntimeError("injected model flush failure")

        db.flush = fail_after_flush
        with pytest.raises(RuntimeError, match="injected model flush failure"):
            models_service.update_model_paid_operations(actor, db, model_id, payload)
        db.flush = original_flush
        db.rollback()
        models_service.update_model_paid_operations(actor, db, model_id, payload)

    assert _details(model_id) != original_details
    assert _details(model_id)["paid_operations"][0]["name"] == "Flush retry"


def _audit_count():
    with TestSessionLocal() as db:
        return db.query(AuditLog).count()


def test_clear_legacy_operations_does_not_resurrect_them_or_clear_other_factories(client, auth_headers):
    legacy = {"id": "shared", "name": "Legacy", "rate": "125", "code": "OP-1"}
    override = _operation("besttex-override", "besttex", "shared")
    mids = [_model("PJ1236", rows=[legacy]), _model("PJ1236-V-6120", rows=[legacy, override])]
    response = _save(client, auth_headers, mids[0], [])
    assert response.status_code == 200, response.text
    for mid in mids:
        details = _details(mid)
        assert filter_paid_operations_for_factory(details, "milana")["paid_operations"] == []
        eco = filter_paid_operations_for_factory(details, "eco_cotton")["paid_operations"]
        assert len(eco) == 1 and eco[0]["rate"] == "125"
    assert filter_paid_operations_for_factory(_details(mids[1]), "besttex")["paid_operations"] == [override]
    snapshot = {mid: _details(mid) for mid in mids}
    assert _save(client, auth_headers, mids[1], []).status_code == 200
    assert all(_details(mid) == snapshot[mid] for mid in mids)


def test_new_variant_inherits_family_operations(client, auth_headers):
    base = _model("PJ1236")
    selected = _model("PJ1236-V-6120")
    with TestSessionLocal() as db:
        fabric = Item(sku="FAMILY-FABRIC", name="Family fabric", category="fabric", unit="kg")
        db.add(fabric)
        db.flush()
        db.add(ModelBOM(model_id=base, item_id=fabric.id, quantity_per_piece=1, unit="kg"))
        db.commit()
        fabric_id = fabric.id
    operations = [_operation("sew", "milana")]
    assert _save(client, auth_headers, selected, operations).status_code == 200
    response = client.post(f"/api/models/{base}/variants", headers=auth_headers,
                           json={"variant_no": "6999", "fabric_item_id": fabric_id})
    assert response.status_code == 201, response.text
    assert response.json()["details_json"]["paid_operations"] == operations


def test_family_rate_changes_preserve_issued_label_and_payroll_snapshot(client, auth_headers):
    selected = _model("PJ1236-V-6120")
    sibling = _model("PJ1236-V-6123")
    operation = _operation("sew", "milana")
    operation["rate"] = "250"
    assert _save(client, auth_headers, selected, [operation]).status_code == 200
    employee = _create_employee(client, auth_headers, "Family operation worker")
    with TestSessionLocal() as db:
        flow = SewingFlow(factory_code="MIL", code="FAMILY-LINE", name="Family line")
        db.add(flow)
        db.commit()
        flow_id = flow.id
    label = {
        "label_uid": f"PY:MAN:{sibling}:FAMILY:SEW:MIL:LINE:48:1",
        "model_id": sibling, "model_code": "PJ1236-V-6123", "production_no": f"MAN-{sibling}-FAMILY",
        "batch_no": "FAMILY", "cutting_passport_no": "FAMILY", "operation_section": "sewing",
        "operation_code": "SEW", "operation_name": "sew", "sewing_flow_id": flow_id,
        "sewing_line_code": "FAMILY-LINE", "sewing_line_name": "Family line", "size": "48",
        "copy_index": 1, "quantity": 12, "rate_per_piece": 250, "currency": "UZS",
    }
    issued = client.post("/api/payroll/qr-labels/issue", headers=auth_headers, json={"labels": [label]})
    assert issued.status_code == 200, issued.text
    token = issued.json()["labels"][0]["qr_token"]
    operation["rate"] = "999"
    assert _save(client, auth_headers, selected, [operation]).status_code == 200
    assert _details(sibling)["paid_operations"][0]["rate"] == "999"
    scanned = client.post("/api/payroll/scan/numeric-work", headers=auth_headers,
                          json={"token": token, "employee_id": employee["id"]})
    assert scanned.status_code == 201, scanned.text
    assert float(scanned.json()["record"]["rate_per_piece"]) == 250
    assert float(scanned.json()["record"]["total_amount"]) == 3000
