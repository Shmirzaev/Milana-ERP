"""Manual waste keeps free fields while status uses the lifecycle contract."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.libs.dto.inventory.waste_input import WasteIn
from app.libs.dto.inventory.waste_output import WasteOut
from app.models.inventory import waste_service

STATUSES = (
    "recorded", "received_by_waste_department", "pending_disposal_approval",
    "disposal_approved", "sold", "disposed",
)


@pytest.mark.parametrize("status", STATUSES)
def test_waste_output_preserves_known_wire_status(status):
    output = WasteOut(id=1, waste_type="布🧵", quantity=1, unit="公斤", sellable=False,
                      estimated_value=0, status=status, created_at=datetime.now(timezone.utc))
    assert output.model_dump(mode="json")["status"] == status


def test_waste_output_rejects_unknown_legacy_status():
    with pytest.raises(ValidationError):
        WasteOut(id=1, waste_type="布", quantity=1, unit="公斤", sellable=False,
                 estimated_value=0, status="legacy_unknown", created_at=datetime.now(timezone.utc))


def test_status_filter_openapi_and_http_validation(client, auth_headers):
    schema = client.get("/openapi.json").json()
    parameter = next(p for p in schema["paths"]["/api/waste"]["get"]["parameters"] if p["name"] == "status")
    variants = parameter["schema"].get("anyOf", [parameter["schema"]])
    ref = next(v["$ref"] for v in variants if "$ref" in v)
    assert set(schema["components"]["schemas"][ref.rsplit("/", 1)[-1]]["enum"]) == set(STATUSES)
    for status in STATUSES:
        assert client.get("/api/waste", params={"status": status}, headers=auth_headers).status_code == 200
    assert client.get("/api/waste", params={"status": "legacy_unknown"}, headers=auth_headers).status_code == 422


def test_manual_create_keeps_unicode_free_fields_and_recorded(monkeypatch):
    class Session:
        def add(self, record): self.record = record
        def flush(self): self.record.id = 1
        def commit(self): pass
        def refresh(self, record): pass

    monkeypatch.setattr(waste_service, "_unit_cost_for_waste", lambda *args: 0)
    monkeypatch.setattr(waste_service, "log_action", lambda *args, **kwargs: None)
    db = Session()
    result = waste_service.create_waste(db, WasteIn(waste_type="布🧵 chiqindi", quantity=1, unit="公斤 кг"), SimpleNamespace(id=7))
    assert (result.waste_type, result.unit, result.status) == ("布🧵 chiqindi", "公斤 кг", "recorded")
    assert db.record is result
