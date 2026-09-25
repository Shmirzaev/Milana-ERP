"""Read-only, per-record preview of historical waste-sale inconsistencies.

Repeated sales are candidates for human reconciliation, never proof of a
duplicate. No repair is performed or proposed from these records alone.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from sqlalchemy import inspect, select
from sqlalchemy.engine import Connection, create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import AuditLog, IdempotencyRecord, WasteRecord, WasteSale
from scripts.audit_item_unit_history import _read_only_transaction


_REQUIRED = {
    "waste_records": {"id", "quantity", "status"},
    "waste_sales": {"id", "waste_record_id", "buyer_name", "quantity", "unit_price", "total_amount", "sold_at"},
    "audit_logs": {"id", "action", "entity_type", "entity_id", "new_value_json"},
    "idempotency_records": {"id", "scope", "response_json", "status_code"},
}


def _decimal(value: object) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def preview_waste_sale_history(connection: Connection, waste_record_id: int) -> dict:
    """Return IDs and numeric evidence for one record; omit buyer names and keys."""
    if waste_record_id < 1:
        raise ValueError("waste_record_id must be positive")
    with _read_only_transaction(connection):
        inspector = inspect(connection)
        for table_name, required in _REQUIRED.items():
            if not inspector.has_table(table_name):
                raise RuntimeError(f"Required table is missing: {table_name}")
            missing = required - {col["name"] for col in inspector.get_columns(table_name)}
            if missing:
                raise RuntimeError(f"Required columns are missing from {table_name}: {', '.join(sorted(missing))}")

        record = connection.execute(
            select(WasteRecord.id, WasteRecord.quantity, WasteRecord.status).where(WasteRecord.id == waste_record_id)
        ).one_or_none()
        if record is None:
            raise ValueError(f"Waste record {waste_record_id} does not exist")
        sales = connection.execute(
            select(WasteSale.id, WasteSale.buyer_name, WasteSale.quantity,
                   WasteSale.unit_price, WasteSale.total_amount, WasteSale.sold_at)
            .where(WasteSale.waste_record_id == waste_record_id).order_by(WasteSale.id)
        ).all()
        audits = connection.execute(
            select(AuditLog.id, AuditLog.new_value_json)
            .where(AuditLog.entity_type == "WasteRecord", AuditLog.entity_id == waste_record_id,
                   AuditLog.action == "sell").order_by(AuditLog.id)
        ).all()
        # Scope embeds actor and waste ID. A suffix match alone would include
        # other records (e.g. 1 and 11), so parse the last path component.
        replay_rows = connection.execute(
            select(IdempotencyRecord.id, IdempotencyRecord.scope,
                   IdempotencyRecord.response_json, IdempotencyRecord.status_code)
            .where(IdempotencyRecord.scope.like(f"waste.sales.%.{waste_record_id}"))
        ).all()
        replays = [row for row in replay_rows if row.scope.rsplit(".", 1)[-1] == str(waste_record_id)]

        issues: list[dict] = []
        original = _decimal(record.quantity)
        if original is None or original <= 0:
            issues.append({"kind": "invalid_record_quantity"})
        sold = Decimal(0)
        same_sale = defaultdict(list)
        sale_ids = {sale.id for sale in sales}
        for sale in sales:
            quantity = _decimal(sale.quantity)
            price = _decimal(sale.unit_price)
            total = _decimal(sale.total_amount)
            if quantity is not None and quantity > 0:
                sold += quantity
            if quantity is None or quantity <= 0 or price is None or price < 0 or total is None or total < 0:
                issues.append({"kind": "invalid_sale_values", "sale_ids": [sale.id]})
                continue
            expected = (quantity * price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if total != expected:
                issues.append({"kind": "amount_mismatch", "sale_ids": [sale.id],
                               "stored": str(total), "computed": str(expected)})
            # Exact buyer comparison occurs in memory; no buyer data is emitted.
            same_sale[(sale.buyer_name, quantity, price, total)].append(sale)

        if original is not None and sold > original:
            issues.append({"kind": "oversold", "excess_quantity": str(sold - original),
                           "sale_ids": sorted(sale_ids)})
        for group in same_sale.values():
            for left, right in zip(group, group[1:]):
                if left.sold_at and right.sold_at and abs(right.sold_at - left.sold_at) <= timedelta(minutes=5):
                    issues.append({"kind": "possible_repeat", "sale_ids": [left.id, right.id]})
        for replay in replays:
            response = replay.response_json
            sale_id = response.get("id") if isinstance(response, dict) else None
            # Tombstones and other non-success records do not claim a sale.
            if replay.status_code == 200 and isinstance(sale_id, int) and sale_id not in sale_ids:
                issues.append({"kind": "orphan_success_replay", "replay_ids": [replay.id],
                               "sale_ids": [sale_id]})
        if len(audits) != len(sales):
            issues.append({"kind": "sale_audit_count_mismatch", "sale_count": len(sales),
                           "sell_audit_count": len(audits)})

        return {
            "waste_record_id": waste_record_id,
            "record_quantity": str(original) if original is not None else None,
            "sold_quantity": str(sold),
            "remaining_quantity": str(original - sold) if original is not None else None,
            "status": record.status,
            "sale_ids": sorted(sale_ids),
            "sell_audit_ids": [audit.id for audit in audits],
            "success_replay_ids": [row.id for row in replays if row.status_code == 200],
            "issues": issues,
            "interpretation": "Possible repeats and count mismatches require source payment, invoice, and buyer evidence; no sale is automatically a duplicate.",
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("waste_record_id", type=int)
    args = parser.parse_args(argv)
    url = os.environ.get("WASTE_SALE_PREVIEW_DATABASE_URL")
    if not url:
        raise SystemExit("Set WASTE_SALE_PREVIEW_DATABASE_URL to the explicitly selected database URL.")
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            report = preview_waste_sale_history(connection, args.waste_record_id)
    finally:
        engine.dispose()
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
