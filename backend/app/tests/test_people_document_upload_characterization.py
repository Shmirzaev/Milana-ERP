"""Existing HR document upload lifecycle on both databases."""

from pathlib import Path
from uuid import uuid4

import pytest

from app.api.routes import hr_workspace as routes
from app.core.config import settings
from app.schemas import AuditLog, Employee, HrEmployeeDocument
from app.tests.test_peo01_create_employee_characterization import (
    employee_database as employee_database, h as h, headers,
)


def _employee(h, factory_code='MIL'):
    with h[0]() as db:
        row = Employee(factory_code=factory_code, full_name=uuid4().hex, status='active')
        db.add(row); db.commit(); return row.id


def _upload(h, employee_id, **values):
    data = {'employee_id': str(employee_id), 'category': 'other', 'title': ' Test document ', **values}
    return h[2].post('/api/hr/documents', headers=headers(h), data=data,
                     files={'file': ('test-only.pdf', b'test document', 'application/pdf')})


def test_document_upload_commits_file_metadata_and_audit(h, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'HR_DOCUMENTS_DIR', str(tmp_path))
    employee_id = _employee(h)
    response = _upload(h, employee_id)
    assert response.status_code == 201, response.text
    body = response.json()
    assert (body['title'], body['category'], body['size_bytes'], body['original_name']) == (
        'Test document', 'other', 13, 'test-only.pdf',
    )
    assert body['download_url'] == f"/api/hr/documents/{body['id']}/download"
    with h[0]() as db:
        row = db.get(HrEmployeeDocument, body['id'])
        assert (row.factory_code, row.employee_id, row.uploaded_by) == ('MIL', employee_id, h[1]['hr'])
        assert (Path(settings.HR_DOCUMENTS_DIR) / row.stored_name).read_bytes() == b'test document'
        audit = db.query(AuditLog).filter_by(user_id=h[1]['hr']).one()
        assert audit.new_value_json == {'employee_id': employee_id, 'category': 'other', 'title': 'Test document'}
    download = h[2].get(body['download_url'], headers=headers(h))
    assert download.status_code == 200 and download.content == b'test document'


def test_document_upload_checks_employee_before_category_and_leaves_no_files(h, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'HR_DOCUMENTS_DIR', str(tmp_path))
    other_id = _employee(h, 'ECO')
    for employee_id in (other_id, 99999999):
        response = _upload(h, employee_id, category='invalid')
        assert (response.status_code, response.json()) == (404, {'detail': 'Employee not found'})
    employee_id = _employee(h)
    assert _upload(h, employee_id, category='invalid').status_code == 422
    denied = h[2].post('/api/hr/documents', headers=headers(h, 'denied'), data={
        'employee_id': employee_id, 'category': 'other', 'title': 'Denied',
    }, files={'file': ('test.pdf', b'data', 'application/pdf')})
    assert denied.status_code == 403
    assert list(tmp_path.iterdir()) == []
    with h[0]() as db:
        assert db.query(HrEmployeeDocument).filter_by(employee_id=employee_id).count() == 0
        assert db.query(AuditLog).filter_by(user_id=h[1]['hr']).count() == 0


def test_document_upload_audit_failure_removes_file_and_rolls_back(h, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'HR_DOCUMENTS_DIR', str(tmp_path))
    employee_id = _employee(h)
    original = routes.log_action
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('document upload audit failure')
    monkeypatch.setattr(routes, 'log_action', fail)
    with pytest.raises(RuntimeError, match='document upload audit failure'):
        _upload(h, employee_id)
    assert list(tmp_path.iterdir()) == []
    with h[0]() as db:
        assert db.query(HrEmployeeDocument).filter_by(employee_id=employee_id).count() == 0
        assert db.query(AuditLog).filter_by(user_id=h[1]['hr']).count() == 0
