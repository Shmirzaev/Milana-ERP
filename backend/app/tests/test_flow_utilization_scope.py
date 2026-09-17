"""Utilization must honor the same selected-factory boundary as flow detail."""

from itertools import permutations
from uuid import uuid4

import pytest

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import SewingFlow, User


FACTORIES = ("MIL", "BST", "ECO")


def _actor(factory, permissions):
    with SessionLocal() as db:
        user = User(
            name="Utilization scope",
            email=f"utilization-{uuid4().hex}@example.invalid",
            password_hash="unused-synthetic-token-test",
            factory_code=factory,
            extra_permissions=list(permissions),
            is_active=True,
        )
        db.add(user)
        db.commit()
        return user.id


def _headers(user_id, factory):
    return {"Authorization": f"Bearer {create_access_token(user_id, {'factory_code': factory})}"}


def _flow(factory):
    with SessionLocal() as db:
        flow = SewingFlow(
            factory_code=factory, name="Utilization scope", code=f"UTIL-{uuid4().hex[:8]}",
            capacity_per_day=250, is_active=True,
        )
        db.add(flow)
        db.commit()
        return flow.id, flow.code


@pytest.mark.parametrize(("selected", "target"), list(permutations(FACTORIES, 2)))
@pytest.mark.parametrize("permissions", [("sewing.flows",), ("*", "admin.super")])
def test_utilization_rejects_other_factory_like_flow_detail(client, selected, target, permissions):
    user_id = _actor(selected, permissions)
    flow_id, _ = _flow(target)
    headers = _headers(user_id, selected)

    detail = client.get(f"/api/sewing-flows/{flow_id}", headers=headers)
    response = client.get(f"/api/sewing-flows/{flow_id}/utilization", headers=headers)

    assert detail.status_code == 403, detail.text
    assert response.status_code == 403, response.text
    assert response.json() == detail.json()


@pytest.mark.parametrize("factory", FACTORIES)
@pytest.mark.parametrize("permissions", [(), ("sewing.flows",), ("planning.production",), ("*", "admin.super")])
def test_utilization_preserves_existing_readers_and_payload(client, factory, permissions):
    user_id = _actor(factory, permissions)
    flow_id, code = _flow(factory)
    headers = _headers(user_id, factory)

    detail = client.get(f"/api/sewing-flows/{flow_id}", headers=headers)
    response = client.get(f"/api/sewing-flows/{flow_id}/utilization", headers=headers)

    assert detail.status_code == 200, detail.text
    assert response.status_code == 200, response.text
    assert response.json() == {
        "flow_id": flow_id, "code": code, "capacity_per_day": 250,
        "committed_today": 0, "utilization_pct": 0.0,
    }


def test_utilization_secondary_grant_requires_selected_factory(client):
    user_id = _actor("MIL", ("sewing.flows", "factory:BST:sewing.flows"))
    flow_id, _ = _flow("BST")

    wrong_session = client.get(f"/api/sewing-flows/{flow_id}/utilization", headers=_headers(user_id, "MIL"))
    selected_session = client.get(f"/api/sewing-flows/{flow_id}/utilization", headers=_headers(user_id, "BST"))

    assert wrong_session.status_code == 403, wrong_session.text
    assert selected_session.status_code == 200, selected_session.text


def test_utilization_missing_flow_stays_404(client):
    user_id = _actor("MIL", ("sewing.flows",))
    response = client.get("/api/sewing-flows/2000000000/utilization", headers=_headers(user_id, "MIL"))
    assert response.status_code == 404
    assert response.json()["detail"] == "Flow not found"


def test_utilization_requires_authentication(client):
    flow_id, _ = _flow("MIL")
    response = client.get(f"/api/sewing-flows/{flow_id}/utilization")
    assert response.status_code == 401
