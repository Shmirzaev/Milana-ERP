import asyncio
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import UploadFile

from app.api.routes import hr_workspace
from app.models import AuditLog, Employee, HrEmployeeDocument, User
from app.tests.conftest import TestSessionLocal
from app.tests.upload_test_support import failing_upload_session_factory


def _references() -> tuple[int, int, int, int]:
    with TestSessionLocal() as db:
        employee = Employee(
            factory_code="MIL",
            employee_no="hr-upload-lifecycle",
            full_name="HR upload lifecycle employee",
        )
        db.add(employee)
        db.commit()
        employee_id = int(employee.id)
        user_id = int(db.query(User.id).filter(User.email == "admin@example.com").one()[0])
        document_count = db.query(HrEmployeeDocument).count()
        audit_count = db.query(AuditLog).count()
    return employee_id, user_id, document_count, audit_count


def _stored_files(root: Path) -> set[Path]:
    return {path.relative_to(root) for path in root.rglob("*") if path.is_file()}


def test_hr_document_commit_failure_rolls_back_and_removes_only_new_file(tmp_path, monkeypatch):
    employee_id, user_id, document_count, audit_count = _references()
    existing = tmp_path / "existing-document.txt"
    existing.write_bytes(b"keep existing document")
    monkeypatch.setattr(hr_workspace.settings, "HR_DOCUMENTS_DIR", str(tmp_path))
    upload = UploadFile(file=BytesIO(b"new document"), filename="new-document.txt")

    try:
        with TestSessionLocal() as db:
            current = db.get(User, user_id)

            monkeypatch.setattr(
                hr_workspace,
                "upload_session_factory",
                lambda _db: failing_upload_session_factory(
                    db,
                    "Synthetic HR document commit failure",
                ),
            )
            with pytest.raises(RuntimeError, match="Synthetic HR document commit failure"):
                asyncio.run(hr_workspace.upload_document(
                    db=db,
                    current=current,
                    employee_id=employee_id,
                    category="other",
                    title="New document",
                    expires_on=None,
                    file=upload,
                ))
    finally:
        asyncio.run(upload.close())

    assert existing.read_bytes() == b"keep existing document"
    assert _stored_files(tmp_path) == {Path(existing.name)}
    with TestSessionLocal() as db:
        assert db.query(HrEmployeeDocument).count() == document_count
        assert db.query(AuditLog).count() == audit_count


def test_hr_document_cancellation_shields_new_file_cleanup(tmp_path, monkeypatch):
    employee_id, user_id, document_count, audit_count = _references()
    existing = tmp_path / "existing-document.txt"
    existing.write_bytes(b"keep existing document")
    monkeypatch.setattr(hr_workspace.settings, "HR_DOCUMENTS_DIR", str(tmp_path))
    upload = UploadFile(file=BytesIO(b"cancelled document"), filename="cancelled.txt")

    async def run():
        with TestSessionLocal() as db:
            current = db.get(User, user_id)
            def cancel_after_file_write(*_args, **_kwargs):
                raise asyncio.CancelledError

            monkeypatch.setattr(hr_workspace, "log_action", cancel_after_file_write)
            with pytest.raises(asyncio.CancelledError):
                await hr_workspace.upload_document(
                    db=db,
                    current=current,
                    employee_id=employee_id,
                    category="other",
                    title="Cancelled document",
                    expires_on=None,
                    file=upload,
                )

    try:
        asyncio.run(run())
    finally:
        asyncio.run(upload.close())

    assert existing.read_bytes() == b"keep existing document"
    assert _stored_files(tmp_path) == {Path(existing.name)}
    with TestSessionLocal() as db:
        assert db.query(HrEmployeeDocument).count() == document_count
        assert db.query(AuditLog).count() == audit_count


def test_hr_document_name_collision_preserves_preexisting_file(tmp_path, monkeypatch):
    employee_id, user_id, document_count, audit_count = _references()
    collision = tmp_path / f"mil_{employee_id}_collision.txt"
    collision.write_bytes(b"keep collision content")
    monkeypatch.setattr(hr_workspace.settings, "HR_DOCUMENTS_DIR", str(tmp_path))
    monkeypatch.setattr(hr_workspace.secrets, "token_hex", lambda _size: "collision")
    upload = UploadFile(file=BytesIO(b"replacement content"), filename="document.txt")

    try:
        with TestSessionLocal() as db:
            current = db.get(User, user_id)
            with pytest.raises(FileExistsError):
                asyncio.run(hr_workspace.upload_document(
                    db=db,
                    current=current,
                    employee_id=employee_id,
                    category="other",
                    title="Collision document",
                    expires_on=None,
                    file=upload,
                ))
    finally:
        asyncio.run(upload.close())

    assert collision.read_bytes() == b"keep collision content"
    assert _stored_files(tmp_path) == {Path(collision.name)}
    with TestSessionLocal() as db:
        assert db.query(HrEmployeeDocument).count() == document_count
        assert db.query(AuditLog).count() == audit_count


def test_hr_document_reads_in_bounded_chunks(tmp_path, monkeypatch):
    employee_id, user_id, document_count, audit_count = _references()
    monkeypatch.setattr(hr_workspace.settings, "HR_DOCUMENTS_DIR", str(tmp_path))
    read_sizes: list[int] = []

    class TrackedStream(BytesIO):
        def read(self, size=-1):
            read_sizes.append(size)
            return super().read(size)

    upload = UploadFile(
        file=TrackedStream(b"bounded document content"),
        filename="bounded.txt",
    )
    try:
        with TestSessionLocal() as db:
            current = db.get(User, user_id)
            response = asyncio.run(hr_workspace.upload_document(
                db=db,
                current=current,
                employee_id=employee_id,
                category="other",
                title="Bounded document",
                expires_on=None,
                file=upload,
            ))
    finally:
        asyncio.run(upload.close())

    assert read_sizes
    assert -1 not in read_sizes
    assert max(read_sizes) <= 1024 * 1024
    assert response["size_bytes"] == len(b"bounded document content")
    with TestSessionLocal() as db:
        assert db.query(HrEmployeeDocument).count() == document_count + 1
        assert db.query(AuditLog).count() == audit_count + 1
