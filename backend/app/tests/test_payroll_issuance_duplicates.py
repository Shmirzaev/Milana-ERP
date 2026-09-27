from app.models import AuditLog, PayrollQrLabel
from app.tests.conftest import TestSessionLocal


def _row(label_uid: str, operation_name: str = "Synthetic sewing") -> dict:
    return {
        "label_uid": label_uid,
        "operation_name": operation_name,
        "quantity": 2,
        "rate_per_piece": 25,
    }


def _labels_for(uids: set[str]) -> list[PayrollQrLabel]:
    db = TestSessionLocal()
    try:
        return db.query(PayrollQrLabel).filter(PayrollQrLabel.label_uid.in_(uids)).all()
    finally:
        db.close()


def test_duplicate_new_uids_return_each_entry_but_create_and_audit_once(client, auth_headers):
    before_audits = TestSessionLocal()
    try:
        before = before_audits.query(AuditLog).filter(
            AuditLog.entity_type == "PayrollQrLabel", AuditLog.action == "issue",
        ).count()
    finally:
        before_audits.close()

    response = client.post(
        "/api/payroll/qr-labels/issue",
        headers=auth_headers,
        json={"labels": [_row(" DUP-NEW "), _row("DUP-NEW")]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["issued_count"], body["created_count"], body["existing_count"]) == (2, 1, 1)
    assert [row["label_uid"] for row in body["labels"]] == ["DUP-NEW", "DUP-NEW"]
    assert len(_labels_for({"DUP-NEW"})) == 1

    after_audits = TestSessionLocal()
    try:
        assert after_audits.query(AuditLog).filter(
            AuditLog.entity_type == "PayrollQrLabel", AuditLog.action == "issue",
        ).count() == before + 1
        audit = after_audits.query(AuditLog).filter(
            AuditLog.entity_type == "PayrollQrLabel", AuditLog.action == "issue",
        ).order_by(AuditLog.id.desc()).first()
        assert audit.new_value_json["count"] == 1
        assert len(audit.new_value_json["label_ids"]) == 1
    finally:
        after_audits.close()


def test_existing_duplicate_and_mixed_requests_preserve_existing_count(client, auth_headers):
    first = client.post(
        "/api/payroll/qr-labels/issue", headers=auth_headers,
        json={"labels": [_row("DUP-EXIST")]},
    )
    assert first.status_code == 200, first.text

    repeated = client.post(
        "/api/payroll/qr-labels/issue", headers=auth_headers,
        json={"labels": [_row(" DUP-EXIST "), _row("DUP-EXIST")]},
    )
    assert repeated.status_code == 200, repeated.text
    assert (repeated.json()["issued_count"], repeated.json()["created_count"], repeated.json()["existing_count"]) == (2, 0, 2)

    mixed = client.post(
        "/api/payroll/qr-labels/issue", headers=auth_headers,
        json={"labels": [_row("DUP-EXIST"), _row("DUP-MIXED"), _row(" DUP-MIXED ")]},
    )
    assert mixed.status_code == 200, mixed.text
    assert (mixed.json()["issued_count"], mixed.json()["created_count"], mixed.json()["existing_count"]) == (3, 1, 2)
    assert len(_labels_for({"DUP-EXIST", "DUP-MIXED"})) == 2


def test_conflicting_operation_does_not_create_extra_label_or_audit(client, auth_headers):
    first = client.post(
        "/api/payroll/qr-labels/issue", headers=auth_headers,
        json={"labels": [_row("DUP-CONFLICT", "Sewing")]},
    )
    assert first.status_code == 200, first.text

    db = TestSessionLocal()
    try:
        before_labels = db.query(PayrollQrLabel).filter(PayrollQrLabel.label_uid == "DUP-CONFLICT").count()
        before_audits = db.query(AuditLog).filter(
            AuditLog.entity_type == "PayrollQrLabel", AuditLog.action == "issue",
        ).count()
    finally:
        db.close()

    conflict = client.post(
        "/api/payroll/qr-labels/issue", headers=auth_headers,
        json={"labels": [_row(" DUP-CONFLICT ", "Cutting"), _row("DUP-CONFLICT-EXTRA", "Cutting")]},
    )
    assert conflict.status_code == 409, conflict.text

    db = TestSessionLocal()
    try:
        assert db.query(PayrollQrLabel).filter(PayrollQrLabel.label_uid == "DUP-CONFLICT").count() == before_labels
        assert db.query(PayrollQrLabel).filter(PayrollQrLabel.label_uid == "DUP-CONFLICT-EXTRA").count() == 0
        assert db.query(AuditLog).filter(
            AuditLog.entity_type == "PayrollQrLabel", AuditLog.action == "issue",
        ).count() == before_audits
    finally:
        db.close()
