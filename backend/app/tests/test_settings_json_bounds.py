from copy import deepcopy

import pytest

from app.models import AuditLog, SystemSetting
from app.tests.conftest import TestSessionLocal

_MAX_SETTING_BYTES = 16 * 1024


def _snapshot(section: str) -> tuple[dict | None, int]:
    with TestSessionLocal() as db:
        row = db.query(SystemSetting).filter_by(key=section).one_or_none()
        return deepcopy(row.value_json) if row else None, db.query(AuditLog.id).count()


@pytest.mark.parametrize(
    ("section", "payload"),
    [
        (
            "preferences",
            {"model_types": ["Ж" * 32 for _ in range(300)]},
        ),
        (
            "company_info",
            {"address": "Ж" * (_MAX_SETTING_BYTES // 2 + 1)},
        ),
    ],
)
def test_settings_patch_rejects_oversized_json_without_setting_or_audit_write(
    client, auth_headers, section, payload,
):
    before = _snapshot(section)

    response = client.patch(f"/api/settings/{section}", headers=auth_headers, json=payload)

    assert response.status_code == 422, response.text
    assert "UTF-8 bytes" in response.text
    assert _snapshot(section) == before


def test_settings_patch_allows_exact_oversized_legacy_value_but_rejects_changed_document(
    client, auth_headers,
):
    section = "preferences"
    legacy = {
        "default_language": "en",
        "timezone": "UTC",
        "model_types": ["Legacy model type " + "x" * 16 for _ in range(1_000)],
        "require_material_reservation_before_cutting": False,
    }
    with TestSessionLocal() as db:
        row = db.query(SystemSetting).filter_by(key=section).one_or_none()
        if row is None:
            db.add(SystemSetting(key=section, value_json=legacy))
        else:
            row.value_json = legacy
        db.commit()

    unchanged = client.patch(
        f"/api/settings/{section}",
        headers=auth_headers,
        json={"model_types": legacy["model_types"]},
    )
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json()["model_types"] == legacy["model_types"]
    assert _snapshot(section)[0] == legacy

    before = _snapshot(section)
    changed = client.patch(
        f"/api/settings/{section}",
        headers=auth_headers,
        json={"require_material_reservation_before_cutting": True},
    )

    assert changed.status_code == 422, changed.text
    assert "UTF-8 bytes" in changed.text
    assert _snapshot(section) == before
