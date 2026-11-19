"""Owner's active pricing scope; history and manufacturing stay outside this rule."""
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import and_, or_

from app.libs.enums.catalog import CatalogScope
from app.models.planning.price_workflow_calculation import amount
from app.schemas import Model


# 1 November 2026, 00:00 Asia/Tashkent. SQLite stores these UTC dates naive.
CREATED_FROM = datetime(2026, 10, 31, 19, tzinfo=timezone.utc)
POLICY_REASON = "Only unpriced standard variants created from 1 November 2026 (Asia/Tashkent) require pricing; Usluga is excluded"


def eligible(model):
    created = model.created_at
    if created is None or model.catalog_scope != CatalogScope.STANDARD:
        return False
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    price = amount(model.selling_price)
    return created >= CREATED_FROM and (model.selling_price is None or price is not None and price <= 0)


def predicate():
    return and_(Model.catalog_scope == CatalogScope.STANDARD,
                Model.created_at.is_not(None), Model.created_at >= CREATED_FROM,
                or_(Model.selling_price.is_(None), Model.selling_price <= 0))


def require_eligible(model):
    if not eligible(model):
        raise HTTPException(409, POLICY_REASON)
