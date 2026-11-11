"""Apply reviewed exact record mappings without rewriting any saved order price."""

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import lazyload

from app.libs.dto.catalog.price_import_input import PriceImportBaseline, PriceImportManifest
from app.libs.enums.catalog import CatalogScope
from app.libs.enums.planning import PriceWorkflowState
from app.models.audit_service import log_action
from app.models.factory_scope_service import user_is_super_admin
from app.models.planning.variant_pricing_service import baseline, can_approve
from app.schemas import Model, PriceCalculationRequest
from app.schemas.catalog.model_price_persistence import apply_catalog_selling_price
from app.schemas.planning.price_calculation_persistence import apply_workflow_fields


def manifest_hash(payload):
    data = {key: value for key, value in payload.items() if key != "data_sha256"}
    return hashlib.sha256(
        json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def current_baseline(model):
    return PriceImportBaseline.model_validate({key: value for key, value in baseline(model).items() if key != "reason"})


def import_reviewed_prices(db, manifest: PriceImportManifest, actor, *, apply=False):
    """One outer transaction; preview never writes or changes request lifecycle."""
    # This operation intentionally spans the shared standard catalogue and can
    # retire active tasks in either factory, so a global admin is required.
    if not actor.is_active or not user_is_super_admin(actor) or not can_approve(actor):
        raise HTTPException(403, "Active global Finance approver required for catalogue import")
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SET LOCAL lock_timeout = '5s'"))
        db.execute(text("SET LOCAL statement_timeout = '60s'"))
        revisions = db.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
        # The reviewed HR merge preserves the exact deployed pricing storage.
        # Unknown descendants and partially migrated multi-head databases refuse.
        if len(revisions) != 1 or revisions[0] not in {
            "0156_variant_price_workflow", "0157_pricing_gate_live_merge"
        }:
            raise HTTPException(409, "Catalogue import requires a reviewed pricing schema head")
    ids = sorted(row.model_id for row in manifest.prices)
    query = db.query(Model).options(lazyload("*")).filter(Model.id.in_(ids)).order_by(Model.id)
    if apply:
        query = query.with_for_update(of=Model).populate_existing()
    models = {model.id: model for model in query.all()}
    if set(models) != set(ids):
        raise HTTPException(409, "A reviewed model no longer exists")
    changes, unchanged = [], []
    for row in manifest.prices:
        model = models[row.model_id]
        if model.code != row.erp_code or model.catalog_scope != CatalogScope.STANDARD:
            raise HTTPException(409, f"Catalogue identity changed for {row.erp_code}")
        if (
            model.selling_price is not None
            and Decimal(str(model.selling_price)) == row.selling_price
            and model.selling_price_currency == "USD"
        ):
            unchanged.append(model.id)
            continue
        if current_baseline(model) != row.expected:
            raise HTTPException(409, f"Price changed since preview for {row.erp_code}; compare again")
        changes.append((model, row))
    report = {
        "manifest_sha256": manifest.data_sha256,
        "workbook_sha256": manifest.source_workbook_sha256,
        "matched_count": len(ids),
        "unchanged_count": len(unchanged),
        "update_count": len(changes),
        "changes": [
            {
                "model_id": model.id,
                "code": model.code,
                "source_rows": row.source_rows,
                "before": row.expected.model_dump(mode="json"),
                "selling_price": str(row.selling_price),
            }
            for model, row in changes
        ],
        "applied": False,
    }
    if not apply:
        db.rollback()
        return report
    changed_at = datetime.now(timezone.utc)
    cancelled = []
    for model, row in changes:
        # All model locks were acquired first in ID order, matching the lifecycle.
        active = (
            db.query(PriceCalculationRequest)
            .options(lazyload("*"))
            .filter_by(active_model_id=model.id)
            .with_for_update(of=PriceCalculationRequest)
            .one_or_none()
        )
        if active:
            if active.workflow_state not in {PriceWorkflowState.COLLECTING, PriceWorkflowState.AWAITING_FINANCE}:
                raise HTTPException(409, "Invalid active pricing lifecycle; resolve before import")
            apply_workflow_fields(
                db,
                active,
                workflow_state=PriceWorkflowState.CANCELLED.value,
                active_model_id=None,
                correction_reason=f"Superseded by catalogue import {manifest.data_sha256}",
                revision=active.revision + 1,
            )
            log_action(
                db,
                actor,
                "cancel_price_request_for_import",
                "PriceCalculationRequest",
                active.id,
                new_value={"manifest_sha256": manifest.data_sha256, "model_id": model.id},
            )
            cancelled.append(active.id)
        apply_catalog_selling_price(db, model, price=row.selling_price, updated_at=changed_at)
        log_action(
            db,
            actor,
            "import_catalog_selling_price",
            "Model",
            model.id,
            old_value=row.expected.model_dump(mode="json"),
            new_value={
                "selling_price": str(row.selling_price),
                "currency": "USD",
                "source": "catalog",
                "source_rows": row.source_rows,
                "source_codes": row.source_codes,
                "workbook_sha256": manifest.source_workbook_sha256,
                "manifest_sha256": manifest.data_sha256,
            },
        )
    if changes:
        log_action(
            db,
            actor,
            "sync_reviewed_catalog_prices",
            "ModelSellingPriceCatalogSync",
            new_value={
                "manifest_sha256": manifest.data_sha256,
                "workbook_sha256": manifest.source_workbook_sha256,
                "updated_count": len(changes),
                "unchanged_count": len(unchanged),
                "cancelled_requests": cancelled,
            },
        )
    expected_prices = {model.id: row.selling_price for model, row in changes}
    db.commit()
    report.update(applied=True, applied_at=changed_at.isoformat(), cancelled_requests=cancelled)
    # Persisted readback is separate from the write transaction. A failed readback
    # must be reported as verification failure, never retried as a new mutation.
    saved_rows = (
        db.query(
            Model.id,
            Model.selling_price,
            Model.selling_price_currency,
            Model.selling_price_source,
            Model.selling_price_request_id,
        )
        .filter(Model.id.in_(expected_prices))
        .all()
    )
    if len(saved_rows) != len(expected_prices):
        raise RuntimeError("Committed import readback is incomplete; inspect recorded audit before retry")
    for model_id, price, currency, source, request_id in saved_rows:
        if price != expected_prices[model_id] or currency != "USD" or source != "catalog" or request_id is not None:
            raise RuntimeError("Committed import readback failed; inspect recorded audit before retry")
    cancelled_rows = (
        db.query(
            PriceCalculationRequest.id, PriceCalculationRequest.workflow_state, PriceCalculationRequest.active_model_id
        )
        .filter(PriceCalculationRequest.id.in_(cancelled))
        .all()
    )
    if len(cancelled_rows) != len(cancelled) or any(
        state != PriceWorkflowState.CANCELLED or active_id is not None for _, state, active_id in cancelled_rows
    ):
        raise RuntimeError("Committed cancellation readback failed; inspect recorded audit before retry")
    report["readback_verified"] = True
    return report
