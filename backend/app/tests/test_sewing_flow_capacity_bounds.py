from uuid import uuid4

from app.db.session import SessionLocal
from app.models import AuditLog, SewingFlow


DB_INTEGER_MAX = 2_147_483_647
DB_INTEGER_MIN = -2_147_483_648


def _flow_payload(marker: str, **overrides) -> dict:
    return {
        "factory_code": "MIL",
        "name": f"Capacity bound {marker}",
        "code": f"CB-{marker}",
        "capacity_per_day": 100,
        **overrides,
    }


def _flow_counts() -> tuple[int, int]:
    with SessionLocal() as db:
        return (
            db.query(SewingFlow).count(),
            db.query(AuditLog).filter(AuditLog.entity_type == "SewingFlow").count(),
        )


def test_sewing_flow_capacity_accepts_exact_signed_integer_boundaries(client, auth_headers):
    marker = uuid4().hex[:12]
    created = client.post(
        "/api/sewing-flows",
        headers=auth_headers,
        json=_flow_payload(marker, capacity_per_day=DB_INTEGER_MAX),
    )
    assert created.status_code == 201, created.text
    assert created.json()["capacity_per_day"] == DB_INTEGER_MAX

    updated = client.patch(
        f"/api/sewing-flows/{created.json()['id']}",
        headers=auth_headers,
        json={"capacity_per_day": DB_INTEGER_MIN},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["capacity_per_day"] == DB_INTEGER_MIN


def test_sewing_flow_create_rejects_integer_overflow_without_writes(client, auth_headers):
    before = _flow_counts()

    response = client.post(
        "/api/sewing-flows",
        headers=auth_headers,
        json=_flow_payload(uuid4().hex[:12], capacity_per_day=DB_INTEGER_MAX + 1),
    )

    assert response.status_code == 422, response.text
    assert _flow_counts() == before


def test_sewing_flow_patch_rejects_integer_underflow_without_mutation(client, auth_headers):
    marker = uuid4().hex[:12]
    created = client.post(
        "/api/sewing-flows",
        headers=auth_headers,
        json=_flow_payload(marker),
    )
    assert created.status_code == 201, created.text
    flow_id = created.json()["id"]
    before = _flow_counts()

    response = client.patch(
        f"/api/sewing-flows/{flow_id}",
        headers=auth_headers,
        json={"capacity_per_day": DB_INTEGER_MIN - 1, "description": "changed"},
    )

    assert response.status_code == 422, response.text
    assert _flow_counts() == before
    with SessionLocal() as db:
        flow = db.get(SewingFlow, flow_id)
        assert flow.capacity_per_day == 100
        assert flow.description is None


def test_sewing_flow_capacity_preserves_auth_resource_and_duplicate_precedence(
    client, auth_headers,
):
    marker = uuid4().hex[:12]
    first = client.post(
        "/api/sewing-flows",
        headers=auth_headers,
        json=_flow_payload(f"A-{marker}"),
    )
    second = client.post(
        "/api/sewing-flows",
        headers=auth_headers,
        json=_flow_payload(f"B-{marker}"),
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text

    denied = client.post(
        "/api/sewing-flows",
        json=_flow_payload(f"C-{marker}", capacity_per_day=DB_INTEGER_MAX + 1),
    )
    assert denied.status_code == 401, denied.text

    missing = client.patch(
        "/api/sewing-flows/2147483647",
        headers=auth_headers,
        json={"capacity_per_day": DB_INTEGER_MAX + 1},
    )
    assert missing.status_code == 404, missing.text

    duplicate = client.patch(
        f"/api/sewing-flows/{first.json()['id']}",
        headers=auth_headers,
        json={"name": second.json()["name"], "capacity_per_day": DB_INTEGER_MAX + 1},
    )
    assert duplicate.status_code == 400, duplicate.text
