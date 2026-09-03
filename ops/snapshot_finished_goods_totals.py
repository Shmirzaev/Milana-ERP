from __future__ import annotations

import json

from sqlalchemy import func

from app.db.session import SessionLocal
from app.models import FinishedGoodsStock, Package


with SessionLocal() as db:
    payload = {
        "packages": db.query(Package).filter(Package.warehouse_id == 8).count(),
        "package_quantity": int(
            db.query(func.coalesce(func.sum(Package.total_quantity), 0))
            .filter(Package.warehouse_id == 8).scalar()
        ),
        "stock_rows": db.query(FinishedGoodsStock).filter(FinishedGoodsStock.warehouse_id == 8).count(),
        "stock_quantity": int(
            db.query(func.coalesce(func.sum(FinishedGoodsStock.quantity), 0))
            .filter(FinishedGoodsStock.warehouse_id == 8).scalar()
        ),
        "available_quantity": int(
            db.query(func.coalesce(func.sum(FinishedGoodsStock.available_qty), 0))
            .filter(FinishedGoodsStock.warehouse_id == 8).scalar()
        ),
        "balance_failures": db.query(FinishedGoodsStock).filter(
            FinishedGoodsStock.quantity
            != FinishedGoodsStock.available_qty + FinishedGoodsStock.reserved_qty + FinishedGoodsStock.sold_qty
        ).count(),
    }
    db.rollback()

print(json.dumps(payload, sort_keys=True))
