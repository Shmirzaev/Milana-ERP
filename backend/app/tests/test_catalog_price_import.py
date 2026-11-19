"""Reviewed price imports preserve saved orders and approval evidence."""

from decimal import Decimal
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.db.session import SessionLocal
from app.libs.dto.catalog.price_import_input import PriceImportManifest
from app.models.catalog import price_import_service as service
from app.schemas import AuditLog, Model, PriceCalculationRequest, User
from app.tests.test_variant_price_workflow import protected_facts


def manifest_for(models):
    return PriceImportManifest.model_validate(
        {
            "source_name": "10-11.xlsx",
            "source_workbook_sha256": "a" * 64,
            "data_sha256": "b" * 64,
            "prices": [
                {
                    "model_id": model.id,
                    "erp_code": model.code,
                    "source_rows": [6 + index],
                    "source_codes": [model.code],
                    "base_price": "8.00",
                    "selling_price": "8.30",
                    "expected": service.current_baseline(model).model_dump(mode="json"),
                }
                for index, model in enumerate(models)
            ],
        }
    )


def test_import_preview_apply_retry_and_saved_order_conservation(client, auth_headers):
    with SessionLocal() as db:
        actor = db.query(User).filter_by(email="admin@example.com").one()
        model = Model(code="PRICE-IMPORT-EXACT", name="Price import", status="approved")
        db.add(model)
        db.flush()
        request = PriceCalculationRequest(
            model_id=model.id,
            active_model_id=model.id,
            factory_code="MIL",
            workflow_state="awaiting_finance",
            created_by_id=actor.id,
        )
        db.add(request)
        db.commit()
        model_id, request_id = model.id, request.id
        manifest = manifest_for([model])
        before = db.query(AuditLog).count()
        assert service.import_reviewed_prices(db, manifest, actor)["update_count"] == 1
        assert db.query(AuditLog).count() == before
        assert db.get(Model, model_id).selling_price is None
    saved = client.post(
        "/api/sales-orders",
        headers=auth_headers,
        json={"items": [{"model_id": model_id, "color": "blue", "size": "S", "quantity": 4, "unit_price": 1.25}]},
    )
    assert saved.status_code == 201, saved.text
    with SessionLocal() as db:
        actor = db.query(User).filter_by(email="admin@example.com").one()
        facts = protected_facts(db)
        result = service.import_reviewed_prices(db, manifest, actor, apply=True)
        assert result["update_count"] == 1 and result["readback_verified"]
        assert result["cancelled_requests"] == [request_id]
        assert protected_facts(db) == facts
        assert db.get(Model, model_id).selling_price == Decimal("8.3000")
        request = db.get(PriceCalculationRequest, request_id)
        assert request.workflow_state == "cancelled" and request.active_model_id is None
        audits = db.query(AuditLog).count()
        again = service.import_reviewed_prices(db, manifest, actor, apply=True)
        assert again["update_count"] == 0 and again["unchanged_count"] == 1
        assert db.query(AuditLog).count() == audits


def test_changed_baseline_refuses_entire_import_before_any_write(client):
    with SessionLocal() as db:
        actor = db.query(User).filter_by(email="admin@example.com").one()
        models = [Model(code=f"IMPORT-RACE-{i}", name="Imported", status="approved") for i in range(2)]
        db.add_all(models)
        db.commit()
        manifest = manifest_for(models)
        models[1].selling_price = 9
        models[1].selling_price_currency = "USD"
        db.commit()
        count = db.query(AuditLog).count()
        with pytest.raises(HTTPException) as error:
            service.import_reviewed_prices(db, manifest, actor, apply=True)
        assert error.value.status_code == 409
        db.rollback()
        assert models[0].selling_price is None and models[1].selling_price == 9
        assert db.query(AuditLog).count() == count


def test_import_failure_rolls_back_prices_cancellations_and_audits(client, monkeypatch):
    with SessionLocal() as db:
        actor = db.query(User).filter_by(email="admin@example.com").one()
        model = Model(code="IMPORT-ATOMIC", name="Import fault", status="approved")
        db.add(model)
        db.flush()
        request = PriceCalculationRequest(
            model_id=model.id,
            active_model_id=model.id,
            factory_code="MIL",
            workflow_state="collecting",
            created_by_id=actor.id,
        )
        db.add(request)
        db.commit()
        manifest = manifest_for([model])
        original = service.log_action

        def fail_after_write(*args, **kwargs):
            original(*args, **kwargs)
            if args[2] == "import_catalog_selling_price":
                assert model.selling_price == Decimal("8.30") and request.active_model_id is None
                raise RuntimeError("injected after import price and cancellation")

        monkeypatch.setattr(service, "log_action", fail_after_write)
        count = db.query(AuditLog).count()
        with pytest.raises(RuntimeError, match="after import"):
            service.import_reviewed_prices(db, manifest, actor, apply=True)
        db.rollback()
        assert (
            model.selling_price is None
            and request.active_model_id == model.id
            and request.workflow_state == "collecting"
        )
        assert db.query(AuditLog).count() == count


def test_import_actor_and_catalogue_scope_are_enforced(client):
    with SessionLocal() as db:
        actor = db.query(User).filter_by(email="admin@example.com").one()
        denied = User(
            name="Import viewer",
            email="import.viewer@example.invalid",
            password_hash="unused",
            extra_permissions=["finance.view", "price_calculation.approve"],
        )
        model = Model(
            code="IMPORT-USLUGA", name="Restricted", status="approved", catalog_scope="usluga", factory_code="ECO"
        )
        db.add_all([model, denied])
        db.commit()
        manifest = manifest_for([model])
        with pytest.raises(HTTPException) as error:
            service.import_reviewed_prices(db, manifest, denied, apply=True)
        assert error.value.status_code == 403
        with pytest.raises(HTTPException) as error:
            service.import_reviewed_prices(db, manifest, actor, apply=True)
        assert error.value.status_code == 409
        db.rollback()
        assert model.selling_price is None


@pytest.mark.parametrize("grant", ["factory_token", "factory_policy"])
def test_factory_wildcard_cannot_import_shared_catalogue(client, grant):
    with SessionLocal() as db:
        actor = User(
            name="Factory admin",
            email=f"import.{grant}@example.invalid",
            password_hash="unused",
            factory_code="ECO",
            extra_permissions=["factory:ECO:*"] if grant == "factory_token" else [],
            access_policy={"ECO": {"allow": ["*"]}} if grant == "factory_policy" else {},
        )
        actor.session_factory_code = "ECO"
        model = Model(code=f"IMPORT-FACTORY-{grant}", name="Shared model", status="approved", factory_code="MIL")
        db.add_all([actor, model])
        db.commit()
        with pytest.raises(HTTPException) as error:
            service.import_reviewed_prices(db, manifest_for([model]), actor, apply=True)
        assert error.value.status_code == 403
        db.rollback()
        assert model.selling_price is None


@pytest.mark.parametrize("price", ["0.30", "8.60", "NaN", "Infinity", "10000000000.0000"])
def test_import_never_double_adds_or_uses_blank_formula_prices(price):
    row = {
        "model_id": 1,
        "erp_code": "A",
        "source_rows": [2],
        "source_codes": ["A"],
        "base_price": "8",
        "selling_price": price,
        "expected": {"price": None, "currency": None, "source": None, "request_id": None, "updated_at": None},
    }
    with pytest.raises(ValidationError):
        PriceImportManifest.model_validate(
            {"source_name": "test.xlsx", "source_workbook_sha256": "a" * 64, "data_sha256": "b" * 64, "prices": [row]}
        )
