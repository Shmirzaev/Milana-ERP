"""Real PostgreSQL HTTP characterization for customer reads (no query mocks)."""
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.partners import router as partners_router
from app.api.routes.planning import router as planning_router
from app.core.deps import get_db
from app.core.security import create_access_token
from app.schemas import AuditLog, Customer, User
from app.tests.test_customer_invoice_creation_race import receipt_race_sessions as receipt_race_sessions


@pytest.fixture
def customer_http(receipt_race_sessions):
    sessions = receipt_race_sessions
    marker = "pg" + uuid4().hex
    with sessions.begin() as db:
        allowed = User(name="Read allowed", email=f"{marker}-yes@example.invalid", password_hash="unused",
                       extra_permissions=["planning.production", "sales.customers"], is_active=True)
        denied = User(name="Read denied", email=f"{marker}-no@example.invalid", password_hash="unused",
                      extra_permissions=[], is_active=True)
        db.add_all([allowed, denied])
        db.flush()
        allowed_id, denied_id = allowed.id, denied.id
    app = FastAPI()
    app.include_router(planning_router, prefix="/api")
    app.include_router(partners_router, prefix="/api")

    def isolated_db():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = isolated_db
    with TestClient(app) as client:
        yield sessions, client, marker, {
            "Authorization": f"Bearer {create_access_token(allowed_id)}"
        }, {"Authorization": f"Bearer {create_access_token(denied_id)}"}


def seed(sessions, names):
    with sessions.begin() as db:
        rows = [Customer(name=name) for name in names]
        db.add_all(rows)
        db.flush()
        return [(row.id, row.name) for row in rows]


def snapshot(sessions):
    with sessions() as db:
        return ([(c.id, c.name, c.phone, c.email, c.address, c.notes, c.created_at, c.updated_at)
                 for c in db.query(Customer).order_by(Customer.id)],
                [(a.id, a.action, a.entity_type, a.entity_id) for a in db.query(AuditLog).order_by(AuditLog.id)])


def test_planning_literal_search_and_access(customer_http):
    sessions, client, marker, allowed, denied = customer_http
    names = [f"{marker} 100% A", f"{marker} 100X A", f"{marker} under_score",
             f"{marker} underXscore", f"{marker} fabric\\roll", f"{marker} fabricXroll"]
    rows = seed(sessions, names)
    before = snapshot(sessions)
    path = "/api/planning/branded-order-customers"
    assert client.get(path).status_code == 401
    assert client.get(path, headers=denied).status_code == 403
    for query, index in [(f"  {marker} 100%  ", 0), (f"{marker} under_score", 2),
                         (f"{marker} fabric\\roll", 4)]:
        response = client.get(path, headers=allowed, params={"q": query})
        assert response.status_code == 200
        assert response.json() == [{"id": rows[index][0], "name": names[index]}]
    assert client.get(path, headers=allowed, params={"q": marker + "-missing"}).json() == []
    # The empty and whitespace searches use the same unfiltered result.
    empty = client.get(path, headers=allowed, params={"q": ""})
    whitespace = client.get(path, headers=allowed, params={"q": "   "})
    assert empty.status_code == whitespace.status_code == 200
    assert empty.json() == whitespace.json()
    assert all(set(row) == {"id", "name"} for row in empty.json())
    assert {(row["id"], row["name"]) for row in empty.json()} >= set(rows)
    assert snapshot(sessions) == before


def test_planning_equal_name_limit_and_id_order(customer_http):
    sessions, client, marker, allowed, _ = customer_http
    name = f"{marker} same"
    rows = seed(sessions, [name] * 51)
    before = snapshot(sessions)
    response = client.get("/api/planning/branded-order-customers", headers=allowed, params={"q": marker})
    assert response.status_code == 200
    assert response.json() == [{"id": ident, "name": name} for ident, _ in sorted(rows)[:50]]
    assert snapshot(sessions) == before


def test_directory_wildcards_pages_clamps_and_access(customer_http):
    sessions, client, marker, allowed, denied = customer_http
    rows = seed(sessions, [f"{marker} A-one", f"{marker} AB-one", f"{marker} A-two"])
    before = snapshot(sessions)
    path = "/api/customers"
    assert client.get(path).status_code == 401
    assert client.get(path, headers=denied).status_code == 403
    # ILIKE intentionally interprets percent and underscore as wildcards.
    response = client.get(path, headers=allowed, params={"q": f"{marker} A%-one"})
    assert response.status_code == 200
    assert [(r["id"], r["name"]) for r in response.json()] == list(reversed(rows[:2]))
    response = client.get(path, headers=allowed, params={"q": f"{marker} A_-one"})
    assert response.status_code == 200
    assert [(r["id"], r["name"]) for r in response.json()] == [rows[1]]
    page = client.get(path, headers=allowed, params={"q": marker, "include_total": "true", "page": 2, "page_size": 1})
    assert page.status_code == 200
    body = page.json()
    assert (body["total"], body["page"], body["page_size"]) == (3, 2, 1)
    assert [(r["id"], r["name"]) for r in body["rows"]] == [rows[1]]
    low = client.get(path, headers=allowed, params={"q": marker, "include_total": "true", "page": 0, "page_size": 0}).json()
    assert (low["total"], low["page"], low["page_size"]) == (3, 1, 1)
    assert [(r["id"], r["name"]) for r in low["rows"]] == [rows[2]]
    high = client.get(path, headers=allowed, params={"q": marker, "include_total": "true", "page_size": 501}).json()
    assert (high["total"], high["page"], high["page_size"]) == (3, 1, 500)
    assert [(r["id"], r["name"]) for r in high["rows"]] == list(reversed(rows))
    assert client.get(path, headers=allowed, params={"q": marker + "-missing"}).json() == []
    empty = client.get(path, headers=allowed, params={"q": marker + "-missing", "include_total": "true"}).json()
    assert empty == {"rows": [], "total": 0, "page": 1, "page_size": 50}
    assert snapshot(sessions) == before
