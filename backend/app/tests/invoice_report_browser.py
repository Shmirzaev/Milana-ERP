"""Disposable invoice/report and Sewing fixture app, bound only to loopback."""
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys


def main():
    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root / "backend"))
    from app.tests.conftest import test_engine
    from app.core.config import settings
    from app.db.base import Base
    from app.db.seed import seed
    from app.db.session import SessionLocal
    from app.schemas import Shipment
    from app.tests.test_invoice_complete_packs import invoice_fixture
    from app.tests.test_sewing_receive_pagination import waiting_batches

    settings.CORS_ORIGINS = "http://127.0.0.1:18823"
    Base.metadata.create_all(test_engine)
    seed()
    fixtures = {}
    for factory, count in (("MIL", 49), ("BST", 123), ("ECO", 3)):
        order, ids = waiting_batches(factory, count)
        fixtures[factory] = {"order": order, "ids": ids}
    output = root / "outputs/load-more"
    output.mkdir(parents=True, exist_ok=True)
    (output / "fixture.json").write_text(json.dumps(fixtures), encoding="utf-8")
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        document = invoice_fixture()
        document.update(customer="Invoice QA customer", sales_order_no="SO-QA",
                        shipped_at=now.isoformat(), shipment_no="INVOICE-QA")
        document["lines"] += [{"package_no": "AGG", "model_no": "AGGREGATE-QA",
                               "variant_no": "V-2", "description": "Recorded size group",
                               "size_display": "XL, S, M, L", "quantity": 24,
                               "amount": "48.00", "unit_price": "2.00"}]
        document["package_details"] += [{"package_no": "AGG", "quantity": 24, "weight_kg": "1.00"}]
        document.update(quantity=219, packages_count=4, amount="438.00")
        current = Shipment(shipment_no="INVOICE-QA", status="shipped", shipped_at=now,
                           dispatch_snapshot={"document": document})
        older = deepcopy(document)
        older.update(shipment_no="INVOICE-QA-OLDER", shipped_at=(now - timedelta(days=40)).isoformat())
        db.add_all([current, Shipment(shipment_no="INVOICE-QA-OLDER", status="delivered",
                                     shipped_at=now - timedelta(days=40), dispatch_snapshot={"document": older})])
        db.commit()
        (root / "outputs/invoice-fixture.json").write_text(json.dumps({"shipment_id": current.id}), encoding="utf-8")
    from app.main import app
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=18822, access_log=False)


if __name__ == "__main__":
    main()
