"""Recovery must deny every legacy pricing operation and preserve ordinary routes."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.core.pricing_recovery import PricingRecoveryUnavailable


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/price-calculation/requests"),
    ("POST", "/api/price-calculation/requests"),
    ("PATCH", "/api/price-calculation/requests/1/finance"),
    ("PATCH", "/api/price-calculation/requests/1/cutting"),
    ("PATCH", "/api/price-calculation/requests/1/purchasing"),
    ("PATCH", "/api/price-calculation/requests/1/accessories"),
    ("POST", "/api/price-calculation/requests/1/approve"),
    ("GET", "/api/price-calculation/report.xlsx"),
])
def test_recovery_refuses_legacy_pricing_before_any_handler(method, path):
    app = FastAPI()
    app.add_middleware(PricingRecoveryUnavailable)
    called = []

    @app.api_route("/{path:path}", methods=["GET", "POST", "PATCH"])
    def business_action(path: str):
        called.append(path)
        return {"unexpected": True}

    response = TestClient(app).request(method, path)
    assert response.status_code == 503 and response.headers["retry-after"] == "60"
    assert called == []


@pytest.mark.parametrize("path", ["/health", "/ready", "/api/sales-orders", "/api/cutting-passports"])
def test_recovery_preserves_nonpricing_routing(path):
    app = FastAPI()
    app.add_middleware(PricingRecoveryUnavailable)

    @app.get("/{path:path}")
    def ordinary_route(path: str):
        return {"path": path}

    response = TestClient(app).get(path)
    assert response.status_code == 200 and response.json()["path"] == path.lstrip("/")
