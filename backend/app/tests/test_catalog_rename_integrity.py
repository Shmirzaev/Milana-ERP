from uuid import uuid4

import pytest

from app.api.routes import catalog
from app.core.security import create_access_token
from app.models import AuditLog, Model, User
from app.tests.conftest import TestSessionLocal


def _family(*, wildcard: bool = False) -> tuple[int, list[int], str, str]:
    marker = uuid4().hex[:8].upper()
    old_model_no = f"OLD%_{marker}" if wildcard else f"OLD-{marker}"
    new_model_no = f"NEW-{marker}"
    with TestSessionLocal() as db:
        rows = [
            Model(
                code=old_model_no,
                name="Catalog rename source",
                status="draft",
                details_json={"general": {"model_no": old_model_no}},
            ),
            Model(
                code=f"{old_model_no}-V-2",
                name="Catalog rename variant",
                status="draft",
                details_json={"general": {"model_no": old_model_no, "variant_no": "V-2"}},
            ),
        ]
        db.add_all(rows)
        db.commit()
        return int(rows[0].id), [int(row.id) for row in rows], old_model_no, new_model_no


def _rename_payload(new_model_no: str) -> dict:
    return {
        "code": new_model_no,
        "name": "Catalog rename source",
        "status": "draft",
        "details_json": {"general": {"model_no": new_model_no}},
    }


def _codes(model_ids: list[int]) -> list[str]:
    with TestSessionLocal() as db:
        return [str(db.get(Model, model_id).code) for model_id in model_ids]


def test_catalog_rename_collision_keeps_wildcard_family_unchanged(client, auth_headers):
    source_id, family_ids, old_model_no, new_model_no = _family(wildcard=True)
    with TestSessionLocal() as db:
        conflict = Model(
            code=f"{new_model_no.lower()}-v-2",
            name="Case-insensitive collision",
            status="draft",
            details_json={"general": {"model_no": "OTHER", "variant_no": "collision"}},
        )
        unrelated = Model(
            code=f"OLDXX{old_model_no[-8:]}-V-9",
            name="Wildcard lookalike",
            status="draft",
            details_json={"general": {"model_no": f"OLDXX{old_model_no[-8:]}", "variant_no": "V-9"}},
        )
        db.add_all([conflict, unrelated])
        db.commit()
        unrelated_id = int(unrelated.id)
        audit_count = db.query(AuditLog).count()

    response = client.patch(
        f"/api/models/{source_id}",
        json=_rename_payload(new_model_no),
        headers=auth_headers,
    )

    assert response.status_code == 409, response.text
    assert "conflicts with existing variant V-2" in response.text
    assert _codes(family_ids) == [old_model_no, f"{old_model_no}-V-2"]
    with TestSessionLocal() as db:
        assert db.get(Model, unrelated_id).code.startswith("OLDXX")
        assert db.query(AuditLog).count() == audit_count


def test_catalog_rename_requires_model_permission_and_does_not_audit(client):
    source_id, family_ids, old_model_no, new_model_no = _family()
    with TestSessionLocal() as db:
        denied = User(
            name="Catalog rename denied",
            email=f"catalog-rename-{uuid4().hex}@example.invalid",
            password_hash="unused-token-fixture",
            factory_code="MIL",
            extra_permissions=[],
            is_active=True,
        )
        db.add(denied)
        db.commit()
        denied_id = int(denied.id)
        audit_count = db.query(AuditLog).count()

    response = client.patch(
        f"/api/models/{source_id}",
        json=_rename_payload(new_model_no),
        headers={"Authorization": f"Bearer {create_access_token(denied_id)}"},
    )

    assert response.status_code == 403, response.text
    assert _codes(family_ids) == [old_model_no, f"{old_model_no}-V-2"]
    with TestSessionLocal() as db:
        assert db.query(AuditLog).count() == audit_count


def test_catalog_rename_audit_failure_rolls_back_every_variant(client, auth_headers, monkeypatch):
    source_id, family_ids, old_model_no, new_model_no = _family()
    with TestSessionLocal() as db:
        audit_count = db.query(AuditLog).count()

    original_log_action = catalog.log_action
    calls = 0

    def fail_second_audit(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = original_log_action(*args, **kwargs)
        if calls == 2:
            raise RuntimeError("synthetic catalog audit failure")
        return result

    monkeypatch.setattr(catalog, "log_action", fail_second_audit)
    with pytest.raises(RuntimeError, match="synthetic catalog audit failure"):
        client.patch(
            f"/api/models/{source_id}",
            json=_rename_payload(new_model_no),
            headers=auth_headers,
        )

    assert calls == 2
    assert _codes(family_ids) == [old_model_no, f"{old_model_no}-V-2"]
    with TestSessionLocal() as db:
        assert db.query(AuditLog).count() == audit_count


def test_catalog_rename_response_and_audits_keep_family_parity(client, auth_headers):
    source_id, family_ids, _old_model_no, new_model_no = _family()
    with TestSessionLocal() as db:
        audit_count = db.query(AuditLog).count()

    response = client.patch(
        f"/api/models/{source_id}",
        json=_rename_payload(new_model_no),
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["code"] == new_model_no
    assert response.json()["details_json"]["general"]["model_no"] == new_model_no
    assert _codes(family_ids) == [new_model_no, f"{new_model_no}-V-2"]
    with TestSessionLocal() as db:
        audits = (
            db.query(AuditLog)
            .filter(AuditLog.entity_type == "Model", AuditLog.entity_id.in_(family_ids))
            .all()
        )
        assert db.query(AuditLog).count() == audit_count + 2
        assert {int(row.entity_id) for row in audits[-2:]} == set(family_ids)
