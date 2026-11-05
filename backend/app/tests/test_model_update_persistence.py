"""Contract checks for the Catalog/Usluga model update persistence seam."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.libs.dto.catalog.model_input import ModelIn
from app.models.catalog import models_service as service
from app.schemas.catalog.catalog import Model
from app.schemas.catalog.model_update_persistence import apply_model_update


class SessionProbe:
    def __init__(self):
        self.events = []

    def commit(self):
        self.events.append("commit")

    def refresh(self, row):
        self.events.append("refresh")


def test_schema_update_preserves_omitted_fields_and_explicit_null():
    row = Model(code="M-1", name="before", description="description")
    db = SessionProbe()
    assert apply_model_update(db, row=row, values={"name": "after", "description": None}) is row
    assert (row.code, row.name, row.description) == ("M-1", "after", None)
    assert db.events == []


@pytest.mark.parametrize("scope", ["standard", "usluga"])
def test_update_preserves_source_overwrite_and_audit_order(monkeypatch, scope):
    db = SessionProbe()
    row = Model(id=1, code="OLD-1", name="old", details_json={"general": {"model_no": "OLD", "variant_no": "1"}})
    sibling = Model(id=2, code="OLD-2", name="sibling", details_json={"general": {"model_no": "OLD", "variant_no": "2"}})
    monkeypatch.setattr(service, "_catalog_model", lambda *args: row)
    monkeypatch.setattr(service, "sewing_master_factory_scope", lambda actor: None)
    monkeypatch.setattr(service, "_model_out_payload", lambda model, factory: {"code": model.code, "factory": factory})
    def rename(session, source, number, catalog_scope):
        service._set_model_identity(session, source, model_no=number, variant_no="1")
        service._set_model_identity(session, sibling, model_no=number, variant_no="2")
        return [(source, "OLD-1"), (sibling, "OLD-2")]
    monkeypatch.setattr(service, "_rename_model_group", rename)
    def audit(session, actor, action, entity, entity_id, **kwargs):
        db.events.append((entity_id, kwargs["old_value"]["code"], kwargs["new_value"]["code"]))
    monkeypatch.setattr(service, "log_action", audit)
    result = service.update_model(SimpleNamespace(), db, 1, ModelIn(code="NEW-1", name="new"), scope)
    assert result == {"code": "NEW-1", "factory": "eco_cotton" if scope == "usluga" else None}
    assert sibling.code == "NEW-2"
    assert db.events == [(2, "OLD-2", "NEW-2"), (1, "OLD-1", "NEW-1"), "commit", "refresh"]


def test_scoped_foreign_factory_refusal_precedes_writes(monkeypatch):
    db = SessionProbe()
    row = Model(id=1, code="M-1", name="before", details_json={})
    monkeypatch.setattr(service, "_catalog_model", lambda *args: row)
    monkeypatch.setattr(service, "apply_model_update", lambda *args, **kwargs: pytest.fail("unexpected write"))
    payload = ModelIn(code="M-1", name="after", details_json={"paid_operations": [{"factory": "besttex"}]})
    with pytest.raises(HTTPException) as caught:
        service.update_model(SimpleNamespace(), db, 1, payload, "usluga")
    assert caught.value.status_code == 403
    assert row.name == "before" and db.events == []
