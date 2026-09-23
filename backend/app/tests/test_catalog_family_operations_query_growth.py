from __future__ import annotations

from math import ceil
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.api.routes import catalog
from app.core.security import create_access_token
from app.models import AuditLog, Model, User
from app.tests.conftest import TestSessionLocal


def _copy_code(source_code: str, index: int) -> str:
    suffix = "-COPY" if index == 1 else f"-COPY-{index}"
    return f"{source_code[: max(1, 64 - len(suffix))]}{suffix}"


@pytest.mark.parametrize("occupied_count", [1, 50, 401])
def test_clone_numbering_uses_exact_bounded_candidate_batches(occupied_count):
    marker = uuid4().hex
    source_code = f"CLONE%_{marker}-{'X' * 40}"[:64]
    with TestSessionLocal() as db:
        db.add_all(
            [Model(code=source_code, name="Clone source")]
            + [
                Model(code=_copy_code(source_code, index), name="Existing clone")
                for index in range(1, occupied_count + 1)
            ]
        )
        db.flush()
        statements: list[str] = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select") and "models.code" in normalized:
                statements.append(normalized)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            candidate = catalog._unique_model_copy_code(db, source_code)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert candidate == _copy_code(source_code, occupied_count + 1)
    assert len(statements) == ceil((occupied_count + 1) / catalog._MODEL_COPY_CODE_BATCH_SIZE)
    assert all(" in " in f" {statement} " for statement in statements)
    assert all(" like " not in f" {statement} " for statement in statements)
    assert all("models.details_json" not in statement for statement in statements)


def test_clone_numbering_preserves_lowest_gap_and_global_scope():
    marker = uuid4().hex
    source_code = f"GAP-{marker}-{'Y' * 40}"[:64]
    with TestSessionLocal() as db:
        db.add_all(
            [
                Model(code=source_code, name="Clone source", catalog_scope="standard"),
                Model(code=_copy_code(source_code, 1), name="Existing standard clone"),
                Model(
                    code=_copy_code(source_code, 2),
                    name="Existing Usluga clone",
                    catalog_scope="usluga",
                    factory_code="ECO",
                ),
                Model(code=_copy_code(source_code, 4), name="Existing later clone"),
            ]
        )
        db.flush()
        assert catalog._unique_model_copy_code(db, source_code) == _copy_code(source_code, 3)


@pytest.mark.parametrize("family_size", [1, 50, 401])
def test_rename_family_queries_do_not_grow_with_family_size(family_size):
    marker = uuid4().hex[:8]
    old_model_no = f"RENAME%_{marker}"
    new_model_no = f"RENAMED-{marker}"
    with TestSessionLocal() as db:
        family = [
            Model(
                code=old_model_no if index == 0 else f"{old_model_no}-V-{index}",
                name="Rename family",
                details_json={
                    "general": {
                        "model_no": old_model_no,
                        **({} if index == 0 else {"variant_no": f"V-{index}"}),
                    }
                },
            )
            for index in range(family_size)
        ]
        db.add_all(family)
        db.flush()
        statements: list[str] = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select") and " from models " in f" {normalized} ":
                statements.append(normalized)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            renamed = catalog._rename_model_group(db, family[0], new_model_no)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert len(renamed) == family_size
    assert len(statements) == 2
    assert "models.description" not in statements[0]
    assert "models.details_json" not in statements[1]


@pytest.mark.parametrize("family_size", [1, 50, 401])
def test_approval_family_lookup_is_one_filtered_read(family_size):
    marker = uuid4().hex[:8]
    model_no = f"APPROVAL%_{marker}"
    with TestSessionLocal() as db:
        family = [
            Model(
                code=model_no if index == 0 else f"{model_no}-V-{index}",
                name="Approval family",
                details_json={
                    "general": {
                        "model_no": model_no,
                        **({} if index == 0 else {"variant_no": f"V-{index}"}),
                    }
                },
            )
            for index in range(family_size)
        ]
        db.add_all(family)
        db.flush()
        statements: list[str] = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select") and " from models " in f" {normalized} ":
                statements.append(normalized)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            rows = catalog._approval_family(db, family[0])
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert len(rows) == family_size
    assert len(statements) == 1
    assert " where " in f" {statements[0]} "


def test_clone_requires_model_permission_without_writes_or_audit(client):
    marker = uuid4().hex
    with TestSessionLocal() as db:
        source = Model(code=f"CLONE-DENIED-{marker}", name="Clone denied source")
        denied = User(
            name="Clone denied actor",
            email=f"clone-denied-{marker}@example.invalid",
            password_hash="unused-token-fixture",
            is_active=True,
            extra_permissions=[],
        )
        db.add_all([source, denied])
        db.commit()
        source_id = int(source.id)
        denied_id = int(denied.id)
        model_count = db.query(Model).count()
        audit_count = db.query(AuditLog).count()

    response = client.post(
        f"/api/models/{source_id}/clone",
        headers={"Authorization": f"Bearer {create_access_token(denied_id)}"},
    )

    assert response.status_code == 403, response.text
    with TestSessionLocal() as db:
        assert db.query(Model).count() == model_count
        assert db.query(AuditLog).count() == audit_count


def test_clone_audit_failure_rolls_back_all_copied_rows(client, auth_headers, monkeypatch):
    marker = uuid4().hex
    source_code = f"CLONE-ROLLBACK-{marker}"
    with TestSessionLocal() as db:
        source = Model(code=source_code, name="Clone rollback source")
        db.add(source)
        db.commit()
        source_id = int(source.id)
        audit_count = db.query(AuditLog).count()

    def fail_audit(*_args, **_kwargs):
        raise HTTPException(503, "Synthetic clone audit failure")

    monkeypatch.setattr(catalog, "log_action", fail_audit)
    response = client.post(f"/api/models/{source_id}/clone", headers=auth_headers)

    assert response.status_code == 503, response.text
    with TestSessionLocal() as db:
        assert db.query(Model).filter(Model.code.like(f"{source_code}-COPY%")).count() == 0
        assert db.query(AuditLog).count() == audit_count
