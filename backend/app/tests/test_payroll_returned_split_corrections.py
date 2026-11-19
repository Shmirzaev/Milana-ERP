"""Returned split corrections change future QR metadata, never old earnings."""
import json
import re
from base64 import b64encode
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
from html import escape
from uuid import uuid4

import pytest

from app.schemas import AuditLog, PayrollPeriod, PayrollQrLabel, PayrollRecord
from app.tests.conftest import TestSessionLocal
from app.tests.test_payroll import _create_employee, _create_user_with_permissions
from app.tests.test_payroll_scan_allocations import issue, scan


def _records():
    with TestSessionLocal() as db:
        return json.dumps([
            {column.name: getattr(row, column.name) for column in PayrollRecord.__table__.columns}
            for row in db.query(PayrollRecord).order_by(PayrollRecord.id)
        ], sort_keys=True, default=str)


def _labels():
    with TestSessionLocal() as db:
        return json.dumps([
            {column.name: getattr(row, column.name) for column in PayrollQrLabel.__table__.columns}
            for row in db.query(PayrollQrLabel).order_by(PayrollQrLabel.id)
        ], sort_keys=True, default=str)


def _audit_count():
    with TestSessionLocal() as db:
        return db.query(AuditLog).filter_by(action="correct_returned_split_labels").count()


def _returned_group(client, headers, *, mixed=False, nameless=False, historical_name=None):
    employees = [_create_employee(client, headers) for _ in range(3)]
    if nameless or historical_name is not None:
        values = {
            "label_uid": f"PY:{uuid4().hex}", "quantity": 105, "rate_per_piece": "1.2345", "currency": "UZS", "size": "L",
        }
        if historical_name is not None:
            values["operation_name"] = historical_name
        issued = client.post("/api/payroll/qr-labels/issue", headers=headers, json={"labels": [values]})
        assert issued.status_code == 200, issued.text
        label = issued.json()["labels"][0]
    else:
        label = issue(client, headers, quantity=105)
    scanned = scan(client, headers, label, employees[0])
    assert scanned.status_code == 201, scanned.text
    original = scanned.json()["record"]
    split = client.post(f"/api/payroll/records/{original['id']}/split", headers=headers, json={"parts": [
        {"employee_id": employees[0]["id"], "quantity": 53},
        {"employee_id": employees[1]["id"], "quantity": 52},
    ]})
    assert split.status_code == 200, split.text
    with TestSessionLocal() as db:
        parent = db.query(PayrollQrLabel).filter_by(label_uid=label["label_uid"]).one()
        children = db.query(PayrollQrLabel).filter_by(split_from_label_id=parent.id).order_by(PayrollQrLabel.id).all()
        ids = [child.id for child in children]
        uids = [child.label_uid for child in children]
    returned_labels = []
    for child_id in ids[:1] if mixed else ids:
        response = client.post(f"/api/payroll/qr-labels/{child_id}/return", headers=headers)
        assert response.status_code == 200, response.text
        returned_labels.append(response.json())
    return dict(employees=employees, original=original, records=split.json(), ids=ids, uids=uids,
                returned_labels=returned_labels, endpoint=f"/api/payroll/qr-labels/{ids[0]}/split-allocation")


def _body(client, headers, group):
    response = client.get(group["endpoint"], headers=headers)
    assert response.status_code == 200, response.text
    view = response.json()
    assert view["mode"] == "returned"
    return view, {"revision": view["revision"], "reason": "Fix returned sticker quantities", "parts": [
        {key: part[key] for key in ("label_id", "employee_id", "quantity", "operation_name", "rate_per_piece")}
        for part in view["parts"]
    ]}


def _changed(body):
    body["parts"][0].update(quantity=60, operation_name="Corrected returned work", rate_per_piece="2.5")
    body["parts"][1].update(quantity=45, operation_name="Other returned work", rate_per_piece="3")
    return body


def test_returned_split_is_loadable_without_reassigning_history(client, auth_headers):
    group = _returned_group(client, auth_headers)
    before = _records()
    response = client.get(group["endpoint"], headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()["mode"] == "returned"
    assert response.json()["total_quantity"] == 105
    assert [part["quantity"] for part in response.json()["parts"]] == [53, 52]
    assert all(part["editable"] and part["employee_id"] is None for part in response.json()["parts"])
    assert _records() == before


def test_returned_53_52_becomes_60_45_without_any_payroll_history_write(client, auth_headers):
    group = _returned_group(client, auth_headers)
    before = _records()
    _, body = _body(client, auth_headers, group)
    response = client.patch(group["endpoint"], headers=auth_headers, json=_changed(body))
    assert response.status_code == 200, response.text
    view = response.json()
    assert view["mode"] == "returned" and view["total_quantity"] == 105
    assert [part["quantity"] for part in view["parts"]] == [60, 45]
    assert [Decimal(part["rate_per_piece"]) for part in view["parts"]] == [Decimal("2.5"), Decimal("3")]
    assert all(part["editable"] and part["employee_id"] is None for part in view["parts"])
    assert [part["label_uid"] for part in view["parts"]] == group["uids"]
    assert _records() == before  # Every mapped column, including original_scan_uid and raw snapshots.
    with TestSessionLocal() as db:
        for child_id in group["ids"]:
            label = db.get(PayrollQrLabel, child_id)
            assert label.status == "available" and label.payroll_record_id is None
            assert label.return_count == 1 and label.returned_at and label.returned_by
        audit = db.query(AuditLog).filter_by(action="correct_returned_split_labels").one()
        assert "reason" in audit.new_value_json
    reopened = client.get(group["endpoint"], headers=auth_headers)
    assert reopened.status_code == 200 and reopened.json() == view
    retry = client.patch(group["endpoint"], headers=auth_headers, json=body)
    assert retry.status_code == 200 and retry.json() == view
    assert _audit_count() == 1 and _records() == before
    stale = json.loads(json.dumps(body))
    stale["parts"][0]["operation_name"] = "Competing stale edit"
    assert client.patch(group["endpoint"], headers=auth_headers, json=stale).status_code == 409
    assert _records() == before
    printed = client.get(group["endpoint"] + "/print", headers=auth_headers)
    assert printed.status_code == 200, printed.text
    assert "Corrected returned work" in printed.text and "Other returned work" in printed.text
    assert printed.text.count("<article") == 2
    assert all(employee["full_name"] not in printed.text for employee in group["employees"])
    for label in group["returned_labels"]:
        assert label["qr_token"] in printed.text
    assert _records() == before


def test_normal_rescan_credits_corrected_values_once_without_restoring_old_earnings(client, auth_headers):
    group = _returned_group(client, auth_headers)
    old_history = json.loads(_records())
    _, body = _body(client, auth_headers, group)
    response = client.patch(group["endpoint"], headers=auth_headers, json=_changed(body))
    assert response.status_code == 200, response.text
    assert json.loads(_records()) == old_history
    scanner = _create_user_with_permissions(client, auth_headers, email=f"rescan-{uuid4().hex}@example.com", permissions=["payroll.scan"])
    response = scan(client, scanner, group["returned_labels"][0], group["employees"][2])
    assert response.status_code == 201, response.text
    new_record = response.json()["record"]
    assert Decimal(new_record["quantity"]) == 60
    assert Decimal(new_record["rate_per_piece"]) == Decimal("2.5")
    assert Decimal(new_record["total_amount"]) == 150
    assert new_record["operation_name"] == "Corrected returned work"
    assert new_record["employee_id"] == group["employees"][2]["id"]
    assert new_record["id"] not in {row["id"] for row in old_history}
    with TestSessionLocal() as db:
        assert db.query(PayrollRecord).count() == len(old_history) + 1
        assert db.query(PayrollRecord).filter(PayrollRecord.status != "voided").count() == 1
        assert db.get(PayrollQrLabel, group["ids"][0]).payroll_record_id == new_record["id"]
    after = json.loads(_records())
    assert [row for row in after if row["id"] in {old["id"] for old in old_history}] == old_history
    retry = scan(client, scanner, group["returned_labels"][0], group["employees"][2])
    assert retry.status_code in {200, 201}, retry.text
    assert retry.json()["record"]["id"] == new_record["id"]
    assert json.loads(_records()) == after


def test_mixed_group_preserves_scanned_sibling_and_prints_both_states(client, auth_headers):
    group = _returned_group(client, auth_headers, mixed=True)
    before = _records()
    view, body = _body(client, auth_headers, group)
    assert [part["editable"] for part in view["parts"]] == [True, False]
    assert view["parts"][0]["employee_id"] is None
    assert view["parts"][1]["employee_id"] == group["employees"][1]["id"]
    body["parts"][0].update(operation_name="Returned side only", rate_per_piece="2.75")
    response = client.patch(group["endpoint"], headers=auth_headers, json=body)
    assert response.status_code == 200, response.text
    assert response.json()["parts"][1] == view["parts"][1]
    assert _records() == before
    printed = client.get(group["endpoint"] + "/print", headers=auth_headers)
    assert printed.status_code == 200 and printed.text.count("<article") == 2, printed.text
    assert "Returned side only" in printed.text and group["employees"][1]["full_name"] in printed.text
    assert group["employees"][0]["full_name"] not in printed.text
    assert group["returned_labels"][0]["qr_token"] in printed.text
    assert _records() == before


def test_print_policy_allows_its_exact_label_fitting_script(client, auth_headers):
    group = _returned_group(client, auth_headers)
    _, body = _body(client, auth_headers, group)
    malicious_name = '<img src=x onerror="alert(1)"><script>alert(2)</script>'
    body["parts"][0]["operation_name"] = malicious_name
    saved = client.patch(group["endpoint"], headers=auth_headers, json=body)
    assert saved.status_code == 200, saved.text
    response = client.get(group["endpoint"] + "/print", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert escape(malicious_name, quote=True) in response.text
    assert malicious_name not in response.text
    policy = {parts[0]: parts[1:] for directive in response.headers.get("content-security-policy", "").split(";")
              if (parts := directive.split())}
    sources = policy.get("script-src-elem", policy.get("script-src", policy.get("default-src", [])))
    assert "'unsafe-inline'" not in sources
    for script in re.findall(r"<script[^>]*>(.*?)</script>", response.text, flags=re.DOTALL):
        digest = b64encode(sha256(script.encode()).digest()).decode()
        assert f"'sha256-{digest}'" in sources, "Label-fitting JavaScript must execute under its exact CSP hash"


def test_blank_readonly_sibling_name_does_not_block_returned_correction(client, auth_headers):
    group = _returned_group(client, auth_headers, mixed=True, nameless=True)
    view, body = _body(client, auth_headers, group)
    assert not view["parts"][1]["editable"] and body["parts"][1]["operation_name"] == ""
    body["parts"][0]["operation_name"] = "Named returned work"
    records = _records()
    response = client.patch(group["endpoint"], headers=auth_headers, json=body)
    assert response.status_code == 200, response.text
    assert response.json()["parts"][1] == view["parts"][1]
    assert _records() == records


def test_padded_readonly_sibling_name_roundtrips_without_history_normalization(client, auth_headers):
    group = _returned_group(client, auth_headers, mixed=True, historical_name="  Historical sew  ")
    view, body = _body(client, auth_headers, group)
    assert body["parts"][1]["operation_name"] == "  Historical sew  "
    body["parts"][0]["operation_name"] = "Correct returned work"
    records = _records()
    response = client.patch(group["endpoint"], headers=auth_headers, json=body)
    assert response.status_code == 200, response.text
    assert response.json()["parts"][1] == view["parts"][1]
    assert _records() == records


def test_second_return_cycle_preserves_both_generations_of_voided_history(client, auth_headers):
    group = _returned_group(client, auth_headers)
    _, body = _body(client, auth_headers, group)
    assert client.patch(group["endpoint"], headers=auth_headers, json=_changed(body)).status_code == 200
    rescanned = scan(client, auth_headers, group["returned_labels"][0], group["employees"][2])
    assert rescanned.status_code == 201, rescanned.text
    returned = client.post(f"/api/payroll/qr-labels/{group['ids'][0]}/return", headers=auth_headers)
    assert returned.status_code == 200 and returned.json()["return_count"] == 2, returned.text
    history = _records()
    _, body = _body(client, auth_headers, group)
    body["parts"][0].update(quantity=65, operation_name="Second returned correction")
    body["parts"][1]["quantity"] = 40
    response = client.patch(group["endpoint"], headers=auth_headers, json=body)
    assert response.status_code == 200, response.text
    assert [part["quantity"] for part in response.json()["parts"]] == [65, 40]
    assert _records() == history and _audit_count() == 2


@pytest.mark.parametrize("field", ["quantity", "employee_id", "operation_name", "rate_per_piece"])
def test_mixed_group_rejects_any_scanned_sibling_tamper(client, auth_headers, field):
    group = _returned_group(client, auth_headers, mixed=True)
    _, body = _body(client, auth_headers, group)
    if field == "quantity":
        body["parts"][0]["quantity"] += 1
        body["parts"][1]["quantity"] -= 1
    else:
        body["parts"][1][field] = {"employee_id": group["employees"][2]["id"], "operation_name": "Tampered sibling", "rate_per_piece": "99"}[field]
    records, labels = _records(), _labels()
    assert client.patch(group["endpoint"], headers=auth_headers, json=body).status_code == 409
    assert (_records(), _labels(), _audit_count()) == (records, labels, 0)


@pytest.mark.parametrize("invalid", ["employee_assignment", "wrong_total", "duplicate", "missing", "reason", "control", "negative_rate"])
def test_returned_correction_refusals_are_atomic(client, auth_headers, invalid):
    group = _returned_group(client, auth_headers)
    _, body = _body(client, auth_headers, group)
    _changed(body)
    if invalid == "employee_assignment":
        body["parts"][0]["employee_id"] = group["employees"][2]["id"]
    elif invalid == "wrong_total":
        body["parts"][1]["quantity"] = 44
    elif invalid == "duplicate":
        body["parts"][1]["label_id"] = body["parts"][0]["label_id"]
    elif invalid == "missing":
        body["parts"].pop()
    elif invalid == "reason":
        body["reason"] = " "
    elif invalid == "control":
        body["parts"][0]["operation_name"] = "Control"
    else:
        body["parts"][0]["rate_per_piece"] = "-1"
    records, labels = _records(), _labels()
    response = client.patch(group["endpoint"], headers=auth_headers, json=body)
    assert response.status_code in {409, 422}, response.text
    assert (_records(), _labels(), _audit_count()) == (records, labels, 0)


@pytest.mark.parametrize("kind", ["anonymous", "scanner", "other_factory"])
def test_returned_editor_and_print_require_manager_in_selected_factory(client, auth_headers, kind):
    group = _returned_group(client, auth_headers)
    _, body = _body(client, auth_headers, group)
    headers = {} if kind == "anonymous" else _create_user_with_permissions(
        client, auth_headers, email=f"returned-{uuid4().hex}@example.com",
        permissions=["payroll.scan"] if kind == "scanner" else ["payroll.manage"],
        factory_code="ECO" if kind == "other_factory" else "MIL",
    )
    expected = {"anonymous": 401, "scanner": 403, "other_factory": 404}[kind]
    records, labels = _records(), _labels()
    assert client.get(group["endpoint"], headers=headers).status_code == expected
    assert client.patch(group["endpoint"], headers=headers, json=_changed(body)).status_code == expected
    assert client.get(group["endpoint"] + "/print", headers=headers).status_code == expected
    assert (_records(), _labels(), _audit_count()) == (records, labels, 0)


@pytest.mark.parametrize("period_status", ["locked", "approved", "paid"])
def test_closed_historical_period_does_not_block_future_label_metadata(client, auth_headers, period_status):
    group = _returned_group(client, auth_headers)
    with TestSessionLocal() as db:
        original = db.get(PayrollRecord, group["original"]["id"])
        period = PayrollPeriod(factory_code="MIL", period_no=f"HISTORY-{uuid4().hex}", name="Historical closed earnings",
                               start_date=original.scanned_at - timedelta(days=1), end_date=original.scanned_at + timedelta(days=1), status=period_status)
        db.add(period)
        db.flush()
        for row in db.query(PayrollRecord):
            row.payroll_period_id = period.id
        db.commit()
    before = _records()
    _, body = _body(client, auth_headers, group)
    response = client.patch(group["endpoint"], headers=auth_headers, json=_changed(body))
    assert response.status_code == 200, response.text
    assert _records() == before


@pytest.mark.parametrize("state", ["rescanned", "closed", "not_returned", "parent_active", "inconsistent_total", "nested"])
def test_changed_return_or_split_structure_refuses_stale_edit(client, auth_headers, state):
    group = _returned_group(client, auth_headers, mixed=state == "nested")
    _, body = _body(client, auth_headers, group)
    body["parts"][0]["operation_name"] = "Should never persist"
    if state == "rescanned":
        response = scan(client, auth_headers, group["returned_labels"][0], group["employees"][0])
        assert response.status_code == 201, response.text
    elif state == "nested":
        response = client.post(f"/api/payroll/records/{group['records'][1]['id']}/split", headers=auth_headers, json={"parts": [
            {"employee_id": group["employees"][1]["id"], "quantity": 26},
            {"employee_id": group["employees"][2]["id"], "quantity": 26},
        ]})
        assert response.status_code == 200, response.text
    else:
        with TestSessionLocal() as db:
            child = db.get(PayrollQrLabel, group["ids"][0])
            if state == "closed":
                child.status = "closed"
            elif state == "not_returned":
                child.return_count = 0
            elif state == "parent_active":
                db.get(PayrollQrLabel, child.split_from_label_id).status = "available"
            else:
                db.get(PayrollQrLabel, child.split_from_label_id).quantity = 106
            db.commit()
    records, labels = _records(), _labels()
    assert client.patch(group["endpoint"], headers=auth_headers, json=body).status_code == 409
    assert (_records(), _labels(), _audit_count()) == (records, labels, 0)


def test_second_persistence_failure_rolls_back_every_returned_label(client, auth_headers, monkeypatch):
    from app.models import payroll_returned_split_correction_service as service

    group = _returned_group(client, auth_headers)
    _, body = _body(client, auth_headers, group)
    records, labels = _records(), _labels()
    apply = service.apply_returned_split_part
    calls = []

    def failing_apply(*args, **kwargs):
        calls.append(1)
        apply(*args, **kwargs)
        if len(calls) == 2:
            raise RuntimeError("Injected returned-label persistence failure")

    monkeypatch.setattr(service, "apply_returned_split_part", failing_apply)
    with pytest.raises(RuntimeError, match="Injected returned-label persistence failure"):
        client.patch(group["endpoint"], headers=auth_headers, json=_changed(body))
    assert len(calls) == 2
    assert (_records(), _labels(), _audit_count()) == (records, labels, 0)
    monkeypatch.setattr(service, "apply_returned_split_part", apply)
    assert client.patch(group["endpoint"], headers=auth_headers, json=body).status_code == 200
    assert _records() == records and _audit_count() == 1


def test_twenty_returned_changes_and_retries_never_credit_or_rewrite_payroll(client, auth_headers):
    group = _returned_group(client, auth_headers)
    history = _records()
    for step in range(20):
        _, body = _body(client, auth_headers, group)
        body["parts"][0].update(quantity=60 + step % 5, operation_name=f"Returned revision {step}", rate_per_piece="2.5")
        body["parts"][1]["quantity"] = 105 - body["parts"][0]["quantity"]
        response = client.patch(group["endpoint"], headers=auth_headers, json=body)
        assert response.status_code == 200, response.text
        retry = client.patch(group["endpoint"], headers=auth_headers, json=body)
        assert retry.status_code == 200 and retry.json() == response.json()
        assert _records() == history
        assert _audit_count() == step + 1
    with TestSessionLocal() as db:
        assert db.query(PayrollQrLabel).count() == 3
        assert db.query(PayrollRecord).filter(PayrollRecord.status != "voided").count() == 0
