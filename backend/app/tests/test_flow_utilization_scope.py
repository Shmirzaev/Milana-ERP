"""Utilization must use the same selected-factory boundary as flow mutations."""

from itertools import permutations

import pytest

from app.db.session import SessionLocal
from app.models import SewingFlow
from app.tests.test_assignment_delete_scope import FACTORIES, _actor, _assignment, _headers, _snapshot


@pytest.mark.parametrize(("selected", "target"), list(permutations(FACTORIES, 2)))
@pytest.mark.parametrize("permissions", [("sewing.flows",), ("*", "admin.super")])
def test_utilization_rejects_other_factory(client, selected, target, permissions):
    actor = _actor(selected, permissions)
    references = _assignment(target)
    before = _snapshot(references)
    response = client.get(
        f"/api/sewing-flows/{references[2][1]}/utilization", headers=_headers(actor, selected),
    )
    assert response.status_code == 403, response.text
    assert "committed_today" not in response.json()
    assert _snapshot(references) == before


@pytest.mark.parametrize("factory", FACTORIES)
def test_utilization_keeps_own_factory_response_and_read_only_behavior(client, factory):
    actor = _actor(factory)
    references = _assignment(factory)
    flow_id = references[2][1]
    with SessionLocal() as db:
        flow = db.get(SewingFlow, flow_id)
        flow.capacity_per_day = 200
        db.commit()
        code = flow.code
    before = _snapshot(references)
    response = client.get(f"/api/sewing-flows/{flow_id}/utilization", headers=_headers(actor, factory))
    assert response.status_code == 200, response.text
    assert response.json() == {
        "flow_id": flow_id, "code": code, "capacity_per_day": 200,
        "committed_today": 0, "utilization_pct": 0.0,
    }
    assert _snapshot(references) == before


def test_utilization_requires_selecting_the_granted_secondary_factory(client):
    actor = _actor(permissions=("sewing.flows", "factory:BST:sewing.flows"))
    flow_id = _assignment("BST")[2][1]
    path = f"/api/sewing-flows/{flow_id}/utilization"
    assert client.get(path, headers=_headers(actor, "MIL")).status_code == 403
    assert client.get(path, headers=_headers(actor, "BST")).status_code == 200


def test_utilization_still_requires_authentication_and_reports_missing_flow(client):
    path = "/api/sewing-flows/2000000000/utilization"
    assert client.get(path).status_code == 401
    actor = _actor()
    assert client.get(path, headers=_headers(actor, "MIL")).status_code == 404
