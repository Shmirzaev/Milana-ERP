from __future__ import annotations

import importlib.util
from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "0104_purchase_batch_images.py"
)


def test_backfill_is_limited_to_linked_purchase_receipts_without_pictures(monkeypatch):
    spec = importlib.util.spec_from_file_location("purchase_batch_image_migration", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    statements: list[str] = []
    monkeypatch.setattr(module.op, "execute", statements.append)
    module.upgrade()

    assert len(statements) == 1
    sql = " ".join(statements[0].split())
    assert "SET image_url = purchase_line.photo_url" in sql
    assert "movement.batch_id = batch.id" in sql
    assert "movement.movement_type = 'receive'" in sql
    assert "movement.reference_type = 'PurchaseOrderLine'" in sql
    assert "batch.image_url IS NULL OR btrim(batch.image_url) = ''" in sql
    assert "purchase_line.photo_url IS NOT NULL" in sql
