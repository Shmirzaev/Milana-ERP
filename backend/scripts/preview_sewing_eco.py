"""Disposable local QA data only. Never connect this harness to a real database."""
import sys
from pathlib import Path
root = Path(__file__).resolve().parents[2]
(root / "outputs/preview").mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(root / "backend"))
from app.tests import conftest
from app.tests.test_sewing_corrections import setup_record
from app.models import Item, StockBatch, Warehouse, PayrollQrLabel, User, Role
from app.tests.conftest import TestSessionLocal
from app.main import app
import json
import uvicorn
setup = conftest.setup_db.__wrapped__()
next(setup)
rid, wid, aid = setup_record()
with TestSessionLocal() as db:
    from app.core.security import hash_password
    preview_role = Role(name="QA Fabric transfer", permissions=["storage.items", "inventory.materials_only", "inventory.eco_transfers"])
    db.add(User(name="Mubina (local preview)", email="mubina@example.com", password_hash=hash_password("test-mubina-password-123!"), role=preview_role, factory_code="MIL"))
    item = db.query(Item).filter_by(category="fabric").first()
    item.name = "Cotton jersey / Хлопковый трикотаж"
    wh = db.query(Warehouse).first()
    first = StockBatch(item_id=item.id, warehouse_id=wh.id, batch_no="PREVIEW-5501", color="Ivory", quantity=45,
              piece_count=3, roll_weights_kg=[10, 15, 20], unit="kg", cost_per_unit=2)
    second = StockBatch(item_id=item.id, warehouse_id=wh.id, batch_no="PREVIEW-5502", color="Navy", quantity=48,
              piece_count=2, roll_weights_kg=[24, 24], unit="kg", cost_per_unit=2)
    db.add_all([first, second]); db.flush()
    for order, count in [("PREVIEW-0181", 0), ("PREVIEW-0182", 2), ("PREVIEW-0183", 4)]:
        for index in range(4):
            db.add(PayrollQrLabel(label_uid=f"{order}-{index}", factory_code="MIL", payload="preview",
                production_no=order, status="scanned" if index < count else "available", operation_code=f"OP-{index+1}",
                operation_name=["Shoulder seam", "Side seam", "Neck binding", "Bottom hem"][index],
                batch_no="Preview batch 1", model_code="Preview cotton top", quantity=50, rate_per_piece=120))
    db.commit()
    fixture = {"workOrderId": wid, "recordId": rid, "firstBatch": first.id, "secondBatch": second.id}
(root / "outputs/preview/fixture.json").write_text(json.dumps(fixture))
print("Local disposable QA backend ready", flush=True)
uvicorn.run(app, host="127.0.0.1", port=8197, log_level="warning")
