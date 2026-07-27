"""Read-only identity helpers for legacy stock without catalog models."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import LegacyStockReceipt, Package


def _clean(value: Any, *, limit: int | None = None) -> str:
    text = " ".join(str(value or "").strip().split())
    return text[:limit] if limit else text


def receipt_identity(receipt: LegacyStockReceipt | None) -> dict[str, str | None]:
    payload = receipt.source_payload if receipt and isinstance(receipt.source_payload, dict) else {}
    model_code = _clean(
        payload.get("model_code")
        or payload.get("source_model")
        or payload.get("product_article"),
        limit=64,
    )
    model_name = _clean(
        payload.get("model_name")
        or payload.get("product")
        or payload.get("finished_name"),
        limit=255,
    )
    return {
        "model_code": model_code or None,
        "model_name": model_name or None,
        "category": _clean(payload.get("category"), limit=64) or None,
        "season": _clean(payload.get("season") or payload.get("department"), limit=64) or None,
    }


def package_legacy_identity(db: Session, package: Package | None) -> dict[str, str | None]:
    if not package or not package.legacy_receipt_id:
        return receipt_identity(None)
    receipt = db.get(LegacyStockReceipt, int(package.legacy_receipt_id))
    return receipt_identity(receipt)
