from uuid import uuid4

from app.db.session import SessionLocal
from app.models import AuditLog, SewingFlow


def _counts() -> tuple[int, int]:
    with SessionLocal() as db:
        return (
            db.query(SewingFlow).count(),
            db.query(AuditLog).filter(AuditLog.entity_type == "SewingFlow").count(),
        )


def _payload(marker: str, **values) -> dict:
    return {
        "factory_code": "MIL",
        "name": f"Line {marker}",
        "code": f"L-{marker}",
        "capacity_per_day": 100,
        **values,
    }


def test_sewing_flow_name_and_code_accept_varchar_boundaries(client, auth_headers):
    marker = uuid4().hex[:12]
    created = client.post(
        "/api/sewing-flows",
        json=_payload(marker, name="N" * 64, code="C" * 32),
        headers=auth_headers,
    )

    assert created.status_code == 201, created.text
    assert len(created.json()["name"]) == 64
    assert len(created.json()["code"]) == 32


def test_sewing_flow_overlong_text_is_rejected_without_writes_or_mutation(client, auth_headers):
    marker = uuid4().hex[:12]
    created = client.post(
        "/api/sewing-flows",
        json=_payload(marker),
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    flow_id = int(created.json()["id"])
    before = _counts()

    for field, value in (("name", "N" * 65), ("code", "C" * 33)):
        response = client.patch(
            f"/api/sewing-flows/{flow_id}",
            json={field: value},
            headers=auth_headers,
        )
        assert response.status_code == 422, (field, response.text)
        assert _counts() == before

    with SessionLocal() as db:
        flow = db.get(SewingFlow, flow_id)
        assert flow is not None
        assert flow.name == f"Line {marker}"
        assert flow.code == f"L-{marker}"


def test_sewing_flow_text_bounds_preserve_auth_and_resource_precedence(client, auth_headers):
    marker = uuid4().hex[:12]
    payload = _payload(marker, name="N" * 65)

    unauthenticated = client.post("/api/sewing-flows", json=payload)
    assert unauthenticated.status_code == 401

    missing = client.patch(
        "/api/sewing-flows/2147483647",
        json={"name": "N" * 65},
        headers=auth_headers,
    )
    assert missing.status_code == 404
