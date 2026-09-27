from uuid import uuid4

import pytest

from app.db.session import SessionLocal
from app.models import AuditLog, SewingFlow


def _payload(marker: str, **overrides) -> dict:
    return {
        "factory_code": "MIL",
        "name": f"Supervisor bound {marker}",
        "code": f"SB-{marker}",
        "capacity_per_day": 100,
        **overrides,
    }


def _counts() -> tuple[int, int]:
    with SessionLocal() as db:
        return (
            db.query(SewingFlow).count(),
            db.query(AuditLog).filter(AuditLog.entity_type == "SewingFlow").count(),
        )


@pytest.mark.parametrize("supervisor_id", [0, -1, 2_147_483_648])
def test_sewing_flow_create_rejects_unstorable_supervisor_id(client, auth_headers, supervisor_id):
    before = _counts()
    response = client.post(
        "/api/sewing-flows",
        headers=auth_headers,
        json=_payload(uuid4().hex[:10], supervisor_id=supervisor_id),
    )

    assert response.status_code == 422, response.text
    assert "supervisor_id" in response.text
    assert _counts() == before


def test_sewing_flow_patch_rejects_unstorable_supervisor_id_without_mutation(client, auth_headers):
    marker = uuid4().hex[:10]
    created = client.post("/api/sewing-flows", headers=auth_headers, json=_payload(marker))
    assert created.status_code == 201, created.text
    flow_id = created.json()["id"]
    before = _counts()

    response = client.patch(
        f"/api/sewing-flows/{flow_id}",
        headers=auth_headers,
        json={"supervisor_id": 2_147_483_648},
    )

    assert response.status_code == 422, response.text
    assert _counts() == before
    with SessionLocal() as db:
        assert db.get(SewingFlow, flow_id).supervisor_id is None
