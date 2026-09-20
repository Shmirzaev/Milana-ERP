"""Bounded issuance reads without changing per-label writes or retry semantics."""

import json
from uuid import uuid4

from sqlalchemy import event

from app.models import Department, PayrollQrLabel, WorkOrder
from app.tests.conftest import test_engine
from app.tests.conftest import TestSessionLocal
from app.tests.test_payroll_label_query_growth import order_references  # noqa: F401
from app.tests.test_payroll import _create_user_with_permissions


def _issue(client, headers, labels):
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        response = client.post("/api/payroll/qr-labels/issue", headers=headers, json={"labels": labels})
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)
    return response, statements


def _select_count(statements):
    return sum(statement.lstrip().upper().startswith("SELECT") for statement in statements)


def test_issuance_and_retry_reads_are_batch_bounded(client, auth_headers):
    created_reads, retry_reads, writes = [], [], []
    for size in (1, 10, 50):
        rows = [{"label_uid": f"issuance-{size}-{index}", "operation_name": "Synthetic sewing", "quantity": 2,
                 "rate_per_piece": 25} for index in range(size)]
        response, statements = _issue(client, auth_headers, rows)
        assert response.status_code == 200, response.text
        body = response.json()
        assert (body["issued_count"], body["created_count"], body["existing_count"]) == (size, size, 0)
        assert [row["label_uid"] for row in body["labels"]] == [row["label_uid"] for row in rows]
        created_reads.append(_select_count(statements))
        writes.append(sum(statement.lstrip().upper().startswith("INSERT INTO PAYROLL_QR_LABELS") for statement in statements))
        repeated, statements = _issue(client, auth_headers, rows)
        assert repeated.status_code == 200, repeated.text
        assert repeated.json() == {**body, "created_count": 0, "existing_count": size}
        retry_reads.append(_select_count(statements))
    print(f"Issuance SELECTs for 1/10/50 labels: {created_reads}; retries: {retry_reads}; label INSERTs: {writes}")
    assert created_reads == [4, 4, 4] and retry_reads == [3, 3, 3]
    assert writes == [1, 10, 50]


def test_reference_only_issuance_reads_do_not_scale_per_label(client, auth_headers):
    """Reference canonicalization is part of issuance and must be batched too."""
    counts = []
    for size in (1, 10, 50):
        rows = [
            {
                "label_uid": f"reference-{size}-{index}",
                "production_no": f"MANUAL-PO-{size}-{index}",
                "payload": json.dumps({
                    "production_no": f"MANUAL-PO-{size}-{index}",
                    "operation_name": "Synthetic sewing",
                }),
                "operation_name": "Synthetic sewing",
                "quantity": 2,
                "rate_per_piece": 25,
            }
            for index in range(size)
        ]
        response, statements = _issue(client, auth_headers, rows)
        assert response.status_code == 200, response.text
        assert response.json()["created_count"] == size
        counts.append(_select_count(statements))
    print(f"Reference-only issuance SELECTs for 1/10/50 labels: {counts}")
    # Keep a small fixed allowance for auth/audit and chunk-boundary setup;
    # this deliberately rejects one canonicalization lookup per label.
    assert counts[1] <= counts[0] + 5
    assert counts[2] <= counts[1] + 5


def test_reference_only_lookup_chunks_at_400_without_row_growth(client, auth_headers):
    rows = [
        {
            "label_uid": f"chunk-reference-{index}",
            "production_no": f"MANUAL-CHUNK-PO-{index}",
            "payload": json.dumps({"production_no": f"MANUAL-CHUNK-PO-{index}"}),
            "operation_name": "Synthetic sewing",
            "quantity": 2,
            "rate_per_piece": 25,
        }
        for index in range(401)
    ]
    response, statements = _issue(client, auth_headers, rows)
    assert response.status_code == 200, response.text
    assert response.json()["created_count"] == 401
    assert _select_count(statements) <= 15


def test_payroll_record_lookup_happens_after_label_flush(client, auth_headers):
    response, statements = _issue(client, auth_headers, [{
        "label_uid": "late-record-ordering",
        "operation_name": "Synthetic sewing",
        "quantity": 2,
        "rate_per_piece": 25,
    }])
    assert response.status_code == 200, response.text
    inserts = [
        index for index, statement in enumerate(statements)
        if statement.lstrip().upper().startswith("INSERT INTO PAYROLL_QR_LABELS")
    ]
    record_reads = [
        index for index, statement in enumerate(statements)
        if "from payroll_records" in statement.lower()
    ]
    assert inserts and record_reads and max(inserts) < min(record_reads)


def test_existing_uid_retry_skips_new_reference_ambiguity(client, auth_headers, order_references):
    with TestSessionLocal() as db:
        db.add(PayrollQrLabel(label_uid="existing-collision", factory_code="MIL",
                              production_no="COLLISION-PROD", operation_name="Synthetic sewing"))
        db.commit()
    response = client.post("/api/payroll/qr-labels/issue", headers=auth_headers, json={"labels": [{
        "label_uid": "existing-collision", "production_no": "COLLISION-PROD",
        "operation_name": "Synthetic sewing", "quantity": 2, "rate_per_piece": 25,
    }]})
    assert response.status_code == 200, response.text
    assert response.json()["existing_count"] == 1


def test_duplicate_new_uid_only_canonicalizes_first_row(client, auth_headers, order_references):
    uid = f"duplicate-{uuid4().hex}"
    rows = [{"label_uid": uid, "production_no": "MANUAL-FIRST", "operation_name": "Synthetic sewing",
             "quantity": 2, "rate_per_piece": 25},
            {"label_uid": uid, "production_no": "COLLISION-PROD", "operation_name": "Synthetic sewing",
             "quantity": 2, "rate_per_piece": 25}]
    response = client.post("/api/payroll/qr-labels/issue", headers=auth_headers, json={"labels": rows})
    assert response.status_code == 200, response.text
    assert (response.json()["created_count"], response.json()["existing_count"]) == (1, 1)


def test_new_ambiguous_reference_rejects_without_insert(client, auth_headers, order_references):
    uid = f"ambiguous-{uuid4().hex}"
    response = client.post("/api/payroll/qr-labels/issue", headers=auth_headers, json={"labels": [{
        "label_uid": uid, "production_no": "COLLISION-PROD", "operation_name": "Synthetic sewing",
        "quantity": 2, "rate_per_piece": 25,
    }]})
    assert response.status_code == 409, response.text
    with TestSessionLocal() as db:
        assert db.query(PayrollQrLabel).filter_by(label_uid=uid).count() == 0


def test_reference_resolved_in_wrong_factory_rejects_without_insert(client, auth_headers, order_references):
    linked, _, _, _, _ = order_references
    with TestSessionLocal() as db:
        department = db.query(Department).filter_by(code="MIL").one()
        db.add(WorkOrder(production_order_id=linked, department_id=department.id, operation="sewing"))
        db.commit()
    foreign_headers = _create_user_with_permissions(
        client, auth_headers, email=f"payroll-bst-{uuid4().hex}@example.com",
        permissions=["payroll.scan", "payroll.manage"], factory_code="BST",
    )
    uid = f"wrong-factory-{uuid4().hex}"
    response = client.post("/api/payroll/qr-labels/issue", headers=foreign_headers, json={"labels": [{
        "label_uid": uid, "production_no": "OLD-PO", "operation_name": "Synthetic sewing",
        "quantity": 2, "rate_per_piece": 25,
    }]})
    assert response.status_code == 404, response.text
    with TestSessionLocal() as db:
        assert db.query(PayrollQrLabel).filter_by(label_uid=uid).count() == 0


def test_linked_alias_issue_canonicalizes_snapshot_without_rewriting_manual_fields(
    client, auth_headers, order_references,
):
    linked, _, _, first, _ = order_references
    with TestSessionLocal() as db:
        department = db.query(Department).filter_by(code="MIL").one()
        db.add(WorkOrder(production_order_id=linked, department_id=department.id, operation="sewing"))
        db.commit()
    uid = f"linked-{uuid4().hex}"
    payload = json.dumps({"production_no": "OLD-PO", "sales_order_no": "OLD-SO",
                          "manual_text": "OLD-PO", "rate_per_piece": 999})
    response = client.post("/api/payroll/qr-labels/issue", headers=auth_headers, json={"labels": [{
        "label_uid": uid, "production_order_id": linked, "sales_order_id": first,
        "production_no": "OLD-PO", "sales_order_no": "OLD-SO", "payload": payload,
        "operation_name": "Synthetic sewing", "quantity": 2, "rate_per_piece": 25,
    }]})
    assert response.status_code == 200, response.text
    with TestSessionLocal() as db:
        label = db.query(PayrollQrLabel).filter_by(label_uid=uid).one()
        assert (label.production_no, label.sales_order_no, label.rate_per_piece) == ("PO-9101", "SO-9101", 25)
        stored = json.loads(label.payload)
        assert (stored["production_no"], stored["sales_order_no"], stored["manual_text"], stored["rate_per_piece"]) == (
            "PO-9101", "SO-9101", "OLD-PO", 999,
        )


def test_linked_id_issue_reads_are_flat_for_1_10_50(client, auth_headers, order_references):
    linked, _, _, first, _ = order_references
    with TestSessionLocal() as db:
        department = db.query(Department).filter_by(code="MIL").one()
        db.add(WorkOrder(production_order_id=linked, department_id=department.id, operation="sewing"))
        db.commit()
    counts = []
    for size in (1, 10, 50):
        rows = [{"label_uid": f"linked-growth-{size}-{index}", "production_order_id": linked,
                 "sales_order_id": first, "production_no": "OLD-PO", "sales_order_no": "OLD-SO",
                 "payload": json.dumps({"production_no": "OLD-PO", "sales_order_no": "OLD-SO"}),
                 "operation_name": "Synthetic sewing", "quantity": 2, "rate_per_piece": 25}
                for index in range(size)]
        response, statements = _issue(client, auth_headers, rows)
        assert response.status_code == 200, response.text
        counts.append(_select_count(statements))
    assert counts[1] <= counts[0] + 5 and counts[2] <= counts[1] + 5
