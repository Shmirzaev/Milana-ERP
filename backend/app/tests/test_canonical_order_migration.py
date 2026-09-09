import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select

from app.models import BusinessOrderAlias, Model, ProductionOrder, SalesOrder, PayrollQrLabel, PayrollRecord, Employee, Bundle, BrandedPlanningOrder
from app.tests.conftest import TestSessionLocal

path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0119_canonical_order_references.py"
spec = importlib.util.spec_from_file_location("canonical_order_migration", path)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


def test_mapping_preserves_canonical_numbers_and_safely_allocates_collisions_manual_and_overflow():
    rows = [dict(id=1, reference="PO-0005"), dict(id=2, reference="PO-2026-000005"),
            dict(id=3, reference="SO-2025-000202"), dict(id=4, reference="SO-2025-000202-2"),
            dict(id=5, reference="Manual factory order"), dict(id=6, reference="PO-2026-100000"),
            dict(id=7, reference="PO-2026-000033")]
    result = migration.plan_namespace("PO", rows)
    assert result == migration.plan_namespace("PO", list(reversed(rows)))
    mapped = {row["entity_id"]: row["canonical_reference"] for row in result}
    assert mapped[1] == "PO-0005"
    assert mapped[7] == "PO-0033"
    assert len(set(mapped.values())) == len(rows)
    assert all(len(value) == 7 for value in mapped.values())
    assert mapped[3] != mapped[4]


def test_mapping_rejects_more_than_9999_orders():
    with pytest.raises(RuntimeError, match="more than 9999"):
        migration.plan_namespace("SO", [dict(id=index, reference=f"MAN-{index}") for index in range(10000)])


def test_payload_only_rewrites_known_reference_fields():
    production = {"PO-2026-000202": "PO-0202"}
    sales = {"SO-2026-000202": "SO-0202"}
    payload = "MW2*keep-uid*PO-2026-000202*BATCH*MODEL*48*OP*control*Control*119*17*UZS*1*none*id*SO-2026-000202"
    rewritten = migration.rewrite_payroll_payload(payload, production, sales)
    old_parts, new_parts = payload.split("*"), rewritten.split("*")
    assert new_parts[2] == "PO-0202" and new_parts[15] == "SO-0202"
    assert all(value == new_parts[index] for index, value in enumerate(old_parts) if index not in {2, 15})
    raw = json.dumps({"po": "PO-2026-000202", "so": "SO-2026-000202", "uid": "original", "rate": 17, "quantity": 119})
    assert json.loads(migration.rewrite_payroll_payload(raw, production, sales)) == {
        "po": "PO-0202", "so": "SO-0202", "uid": "original", "rate": 17, "quantity": 119}
    untouched = ' { "uid" : "leave spacing", "po": "external" } '
    assert migration.rewrite_payroll_payload(untouched, production, sales) == untouched
    with pytest.raises(RuntimeError, match="Ambiguous"):
        migration.rewrite_payroll_payload(raw, production, sales, {"SO-2026-000202"})
    with pytest.raises(RuntimeError, match="Unknown managed"):
        migration.rewrite_payroll_payload('{"po":"PO-2026-009999"}', production, sales, fail_unknown=True)


def test_migration_updates_live_orders_references_payload_and_preserves_label_identity():
    with TestSessionLocal() as db:
        model = db.query(Model).first()
        so = SalesOrder(order_no="SO-2026-000606")
        db.add(so)
        db.flush()
        po = ProductionOrder(production_no="PO-2026-000202", model_id=model.id, production_type="branded_stock")
        linked = ProductionOrder(production_no=so.order_no, sales_order_id=so.id, model_id=model.id, production_type="client_order")
        linked2 = ProductionOrder(production_no=so.order_no + "-2", sales_order_id=so.id, model_id=model.id, production_type="client_order")
        db.add_all([po, linked, linked2])
        db.flush()
        payload = json.dumps({"id": "keep-uid", "po": po.production_no, "so": "SO-2026-000202", "q": 119, "r": 17})
        label = PayrollQrLabel(label_uid="keep-uid", production_order_id=po.id, production_no=po.production_no,
                               sales_order_no="SO-2026-000202", payload=payload, quantity=119, rate_per_piece=17)
        original_raw = {"production_no": po.production_no, "sales_order_no": "SO-2026-000202", "quantity": 119, "rate": 17}
        employee = Employee(full_name="Canonical migration fixture")
        db.add(employee)
        db.flush()
        record = PayrollRecord(employee_id=employee.id, dedupe_key="keep-original-dedupe",
                               scan_uid="keep-original-scan", original_scan_uid="keep-original-scan",
                               production_order_id=po.id, production_no=po.production_no,
                               sales_order_no="SO-2026-000202", quantity=119, rate_per_piece=17,
                               total_amount=2023, scanned_at=datetime.now(timezone.utc), raw_work_json=original_raw)
        bundle = Bundle(bundle_no="BND-2026-000123", barcode="unchanged-barcode", production_order_id=po.id,
                        model_id=model.id, color="Red", size="48", quantity=119, qr_code_url="/storage/old.png")
        db.add_all([label, bundle, record])
        db.commit()
        po_id, sale_id, label_id, bundle_id = po.id, so.id, label.id, bundle.id
        record_id = record.id
        linked_ids = [linked.id, linked2.id]
        before_bso = db.query(BrandedPlanningOrder.order_no).all()
    with TestSessionLocal().get_bind().begin() as connection:
        assert connection.execute(select(BusinessOrderAlias.id)).first() is None
        BusinessOrderAlias.__table__.drop(connection)
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
    from app.core.order_reference import canonical_order_reference, resolve_order_id, order_reference_variants
    from app.api.routes.traceability import _find_production_order
    from app.services.finance_1c import _resolve_sales_order
    with TestSessionLocal() as db:
        assert db.get(ProductionOrder, po_id).production_no == "PO-0202"
        assert db.get(SalesOrder, sale_id).order_no == "SO-0606"
        linked_numbers = [db.get(ProductionOrder, value).production_no for value in linked_ids]
        assert all(value.startswith("PO-") and len(value) == 7 for value in linked_numbers)
        assert len(set(linked_numbers)) == 2
        label = db.get(PayrollQrLabel, label_id)
        assert label.production_no == "PO-0202" and label.sales_order_no == "PO-0202"
        assert label.label_uid == "keep-uid" and label.quantity == 119 and label.rate_per_piece == 17
        record = db.get(PayrollRecord, record_id)
        assert record.production_no == "PO-0202" and record.sales_order_no == "PO-0202"
        assert record.raw_work_json == original_raw
        assert record.scan_uid == record.original_scan_uid == "keep-original-scan"
        assert record.dedupe_key == "keep-original-dedupe" and record.total_amount == 2023
        assert json.loads(label.payload) == {"id": "keep-uid", "po": "PO-0202", "so": "PO-0202", "q": 119, "r": 17}
        bundle = db.get(Bundle, bundle_id)
        assert bundle.barcode == "unchanged-barcode" and bundle.bundle_no == "BND-2026-000123"
        assert bundle.qr_code_url == f"/api/barcode/bundle-image/{bundle_id}"
        assert db.query(BrandedPlanningOrder.order_no).all() == before_bso
        assert _find_production_order(db, "PO-2026-000202").id == po_id
        assert _resolve_sales_order(db, None, "SO-2026-000606").id == sale_id
        assert canonical_order_reference(db, "SO", "SO-2026-000202") == "PO-0202"
        assert resolve_order_id(db, "SO", "SO-2026-000202") is None
        assert order_reference_variants(db, "SO", "PO-0202", production_order_id=po_id) == {"SO-2026-000202", "PO-0202"}


@pytest.mark.parametrize("hinted", [False, True])
def test_payload_only_public_sales_collision_requires_production_hint(hinted):
    old_sales = "SO-2026-000808"
    with TestSessionLocal() as db:
        model = db.query(Model).first()
        sale = SalesOrder(order_no=old_sales)
        production = ProductionOrder(production_no="PO-2026-000808", model_id=model.id, production_type="branded_stock")
        db.add_all([sale, production])
        db.flush()
        payload = {"so": old_sales, "label_id": "unchanged"}
        if hinted:
            payload["pid"] = production.id
        label = PayrollQrLabel(label_uid="collision-payload", payload=json.dumps(payload))
        db.add(label)
        db.commit()
        label_id, sale_id = label.id, sale.id
    with TestSessionLocal().get_bind().begin() as connection:
        BusinessOrderAlias.__table__.drop(connection)
        with Operations.context(MigrationContext.configure(connection)):
            if hinted:
                migration.upgrade()
            else:
                with pytest.raises(RuntimeError, match="Ambiguous"):
                    migration.upgrade()
                assert connection.execute(select(SalesOrder.order_no).where(SalesOrder.id == sale_id)).scalar_one() == old_sales
    if hinted:
        with TestSessionLocal() as db:
            label = db.get(PayrollQrLabel, label_id)
            assert json.loads(label.payload) == {**payload, "so": "PO-0808"}
            assert label.production_order_id is None and label.sales_order_id is None
