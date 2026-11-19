"""HR document deletion keeps factory isolation and transactional file ordering."""

from uuid import uuid4

import pytest

from app.api.routes import hr_workspace as routes
from app.core.config import settings
from app.schemas import AuditLog, Employee, HrEmployeeDocument
from app.tests.test_peo01_create_employee_characterization import (
    employee_database as employee_database, h as h, headers,
)


def _document(h, tmp_path, factory_code='MIL'):
    stored_name = f'{uuid4().hex}.pdf'
    with h[0]() as db:
        employee = Employee(factory_code=factory_code, full_name=uuid4().hex, status='active')
        db.add(employee); db.flush()
        row = HrEmployeeDocument(factory_code=factory_code, employee_id=employee.id, category='other',
                                 title='Test only', original_name='test.pdf', stored_name=stored_name,
                                 size_bytes=4, uploaded_by=h[1]['hr'])
        db.add(row); db.commit(); return row.id, tmp_path / stored_name


@pytest.mark.parametrize('file_exists', [False, True])
def test_document_delete_commits_then_removes_optional_file(h, tmp_path, monkeypatch, file_exists):
    monkeypatch.setattr(settings, 'HR_DOCUMENTS_DIR', str(tmp_path))
    row_id, path = _document(h, tmp_path)
    if file_exists: path.write_bytes(b'data')
    response = h[2].delete(f'/api/hr/documents/{row_id}', headers=headers(h))
    assert response.status_code == 204 and response.content == b''
    assert not path.exists()
    with h[0]() as db:
        assert db.get(HrEmployeeDocument, row_id) is None
        audit = db.query(AuditLog).filter_by(user_id=h[1]['hr']).one()
        assert (audit.action, audit.entity_type, audit.entity_id) == ('delete', 'HrEmployeeDocument', row_id)
    assert h[2].delete(f'/api/hr/documents/{row_id}', headers=headers(h)).status_code == 404


def test_document_delete_refusals_preserve_row_and_file(h, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'HR_DOCUMENTS_DIR', str(tmp_path))
    row_id, path = _document(h, tmp_path, 'ECO'); path.write_bytes(b'data')
    assert h[2].delete(f'/api/hr/documents/{row_id}', headers=headers(h)).status_code == 404
    assert h[2].delete(f'/api/hr/documents/{row_id}', headers=headers(h, 'denied')).status_code == 403
    assert path.read_bytes() == b'data'
    with h[0]() as db:
        assert db.get(HrEmployeeDocument, row_id) is not None
        assert db.query(AuditLog).filter_by(user_id=h[1]['hr']).count() == 0


def test_document_delete_audit_failure_keeps_file_and_row(h, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'HR_DOCUMENTS_DIR', str(tmp_path))
    row_id, path = _document(h, tmp_path); path.write_bytes(b'data')
    original = routes.log_action
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('document delete audit failure')
    monkeypatch.setattr(routes, 'log_action', fail)
    with pytest.raises(RuntimeError, match='document delete audit failure'):
        h[2].delete(f'/api/hr/documents/{row_id}', headers=headers(h))
    assert path.read_bytes() == b'data'
    with h[0]() as db:
        assert db.get(HrEmployeeDocument, row_id) is not None
        assert db.query(AuditLog).filter_by(user_id=h[1]['hr']).count() == 0
