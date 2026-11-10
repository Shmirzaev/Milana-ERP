"""Preview missing-price requests; apply only on explicit operator instruction.

Example: python scripts/reconcile_variant_pricing.py --actor-id <finance-user>
--factory MIL. Add --apply only after reviewing the preview and authorizing data
reconciliation. It never changes models, prices, orders, stock or legacy requests.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal
from app.libs.enums.catalog import CatalogScope
from app.libs.enums.planning import PriceReportFilter
from app.models.factory_scope_service import bind_session_factory
from app.models.planning import price_reports_service, variant_pricing_service
from app.schemas import CuttingPassport, User
from app.schemas.planning.price_calculation import PriceCalculationRequest


def reconcile(db, current, catalog_scope=CatalogScope.STANDARD, apply=False):
    if not variant_pricing_service.can_approve(current):
        raise ValueError("An active Finance price approver is required")
    models = price_reports_service._query(db, current, PriceReportFilter.PENDING, "", catalog_scope).order_by(
        price_reports_service.Model.id).all()
    result = []
    for model in models:
        if db.query(PriceCalculationRequest.id).filter_by(active_model_id=model.id).first():
            continue
        passport = variant_pricing_service.passport_query(db, model.id, model.code, current).order_by(CuttingPassport.id.desc()).first()
        result.append({"model": model.code, "passport": passport.passport_no if passport else None,
                       "action": "create_request" if passport else "review_source"})
        if apply and passport:
            variant_pricing_service.sync_passport_pricing(db, passport, current)
    if apply:
        db.commit()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actor-id", required=True, type=int)
    parser.add_argument("--factory", required=True, choices=["MIL", "BST", "ECO"])
    parser.add_argument("--catalog", choices=[scope.value for scope in CatalogScope], default="standard")
    parser.add_argument("--apply", action="store_true", help="Explicitly create reviewed missing-price requests")
    args = parser.parse_args()
    with SessionLocal() as session:
        actor = session.get(User, args.actor_id)
        if actor is None or not actor.is_active:
            parser.error("Select an active existing Finance approver")
        bind_session_factory(actor, args.factory)
        print(json.dumps({"applied": args.apply, "variants": reconcile(session, actor, CatalogScope(args.catalog), args.apply)}, ensure_ascii=False, indent=2))
