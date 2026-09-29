from copy import deepcopy

from app.models import AuditLog, Item, Model, ModelBOM, SewingFlow
from app.services.paid_operations import filter_paid_operations_for_factory
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
    operations[0].update(rate="50.125", copies=2, splitMode="manual", splitQuantities=[3, 4])
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
