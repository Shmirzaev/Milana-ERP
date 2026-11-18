"""Split print batches allocations while retaining rendered output and refusals."""
import base64
from io import BytesIO
import re
from datetime import datetime, timezone

import qrcode
from PIL import Image, ImageChops
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.tests.payroll_isolated_growth_fixture import payroll_isolated_database as payroll_isolated_database
from app.models.people import payroll_service as service
from app.schemas import Employee, PayrollQrLabel, PayrollRecord


def user(factory="MIL"):
    return SimpleNamespace(role=SimpleNamespace(name="", permissions=[]), factory_code=factory, session_factory_code=factory)


def seed(sessions, size, shared=False):
    marker = uuid4().hex[:8]
    with sessions() as db:
        employees = [Employee(factory_code="MIL", employee_no=f"PR-{marker}-{i}", full_name=f"Person & {marker} {i}", status="active") for i in range(1 if shared else size)]
        db.add_all(employees)
        db.flush()
        records = [PayrollRecord(factory_code="MIL", dedupe_key=f"{marker}-{i}", employee_id=employees[0 if shared else i].id,
            scanned_at=datetime(2026, 9, 1, tzinfo=timezone.utc), source="growth", status="recorded") for i in range(size)]
        db.add_all(records)
        db.flush()
        original = PayrollQrLabel(factory_code="MIL", label_uid=f"orig-{marker}", payroll_record_id=records[0].id, status="superseded")
        db.add(original)
        db.flush()
        labels = [PayrollQrLabel(factory_code="MIL", label_uid=f"child-{marker}-{i}", split_from_label_id=original.id,
            payroll_record_id=record.id, operation_name=f"Operation {i}", quantity=1, status="scanned") for i, record in enumerate(records)]
        db.add_all(labels)
        db.commit()
        return records[0].id, [label.id for label in labels], marker


@pytest.mark.parametrize("shared", [False, True])
def test_split_print_queries_and_real_output(shared, payroll_isolated_database):
    engine, sessions = payroll_isolated_database
    counts = []
    for size in (1, 10, 50):
        record_id, label_ids, marker = seed(sessions, size, shared)
        statements = []
        def capture(_conn, _cursor, statement, _params, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)
        with sessions() as db:
            event.listen(engine, "before_cursor_execute", capture)
            try:
                html = service.print_split_record_labels(record_id, db, user())
            finally:
                event.remove(engine, "before_cursor_execute", capture)
        cards = re.findall(r"<article>(.*?)</article>", html, re.DOTALL)
        assert len(cards) == size
        for index, (card, label_id) in enumerate(zip(cards, label_ids)):
            employee_index = 0 if shared else index
            token = f"2{label_id:08d}"
            assert f'<p class="operation">Operation {index}</p>' in card
            assert f'<p class="employee">Person &amp; {marker} {employee_index}</p>' in card
            assert f'PR-{marker}-{employee_index} ·  · 1' in card
            assert f'<p>{token}</p>' in card
            encoded = re.search(r'src="data:image/png;base64,([^"]+)"', card).group(1)
            actual = Image.open(BytesIO(base64.b64decode(encoded))).convert("1")
            qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=2)
            qr.add_data(token)
            qr.make(fit=True)
            expected = qr.make_image(fill_color="black", back_color="white").get_image().convert("1")
            assert actual.size == expected.size
            assert ImageChops.difference(actual, expected).getbbox() is None
        counts.append(len(statements))
    assert counts[0] == counts[1] == counts[2], counts


def test_split_print_refuses_unrecorded_and_other_factory(payroll_isolated_database):
    engine, sessions = payroll_isolated_database
    record_id, _, _ = seed(sessions, 1)
    with sessions() as db:
        with pytest.raises(HTTPException) as error:
            service.print_split_record_labels(record_id, db, user("BST"))
        assert error.value.status_code == 404
        db.get(PayrollRecord, record_id).status = "voided"
        db.flush()
        with pytest.raises(HTTPException) as error:
            service.print_split_record_labels(record_id, db, user())
        assert error.value.status_code == 409


def test_split_print_chunk_boundary(payroll_isolated_database):
    engine, sessions = payroll_isolated_database
    record_id, label_ids, _ = seed(sessions, 401)
    statements = []
    def capture(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)
    with sessions() as db:
        event.listen(engine, "before_cursor_execute", capture)
        try:
            html = service.print_split_record_labels(record_id, db, user())
        finally:
            event.remove(engine, "before_cursor_execute", capture)
    assert html.count("<article>") == len(label_ids) == 401
    assert len(statements) == 6, statements


def test_split_print_refuses_missing_allocation_and_wrong_factory_employee(payroll_isolated_database):
    engine, sessions = payroll_isolated_database
    record_id, label_ids, _ = seed(sessions, 1)
    with sessions() as db:
        label = db.get(PayrollQrLabel, label_ids[0])
        label.payroll_record_id = None
        db.flush()
        with pytest.raises(HTTPException) as error:
            service.print_split_record_labels(record_id, db, user())
        assert (error.value.status_code, error.value.detail) == (409, "Split allocations are no longer recorded")
        label.payroll_record_id = record_id
        employee = db.get(Employee, db.get(PayrollRecord, record_id).employee_id)
        employee.factory_code = "BST"
        db.flush()
        with pytest.raises(HTTPException) as error:
            service.print_split_record_labels(record_id, db, user())
        assert (error.value.status_code, error.value.detail) == (409, "Split allocations are no longer recorded")
