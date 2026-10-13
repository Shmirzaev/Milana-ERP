"""Refusal guards for the specifically authorized one-time reset."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("reset_po0287", Path(__file__).parents[2] / "scripts/reset_po0287_packaging.py")
reset = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reset)


@pytest.fixture
def plan():
    s = {k: [] for k in reset.DELETE_COUNTS}
    for index, pid in enumerate(reset.IDS):
        p = dict(id=pid, package_no=f"PKG-2026-{169+index:06d}", status="returned_to_packaging",
                 total_quantity=90, production_batch_id=152, model_id=8444, packaging_department_code="PKG")
        p.update({k: None for k in ("received_at", "received_by", "shipped_at", "sales_order_id", "quantity_shortfall", "dispatched_quantity", "dispatched_quantities", "manual_receipt_id", "legacy_receipt_id")})
        s["packages"].append(p)
        s["package_items"] += [dict(package_id=pid, quantity=15) for _ in range(6)]
        s["package_batch_allocations"].append(dict(package_id=pid, quantity=90))
        s["finished_goods_stock"] += [dict(package_id=pid, quantity=15, available_qty=15,
             sold_qty=0, reserved_qty=0, sales_order_id=None, status="available") for _ in range(6)]
        s["package_scan_logs"] += [dict(package_id=pid, scan_type=v) for v in ("packed", "returned_to_packaging")]
    s["production_orders"] = [dict(production_no="PO-0287")]
    s["package_print_run_members"] = [dict(package_id=pid) for pid in reset.IDS]
    s["package_print_runs"] = [dict(id=14, run_no="PRN-2026-000014", package_ids=reset.IDS.copy(),
         returned_at="2026-10-13", received_at=None, deleted_at=None, deleted_package_ids=[])]
    s["packaging_records"] = [dict(id=23, work_order_id=1226, production_batch_id=152, packed_qty=360, input_qty=360, damaged_qty=0)]
    s["work_orders"] = [dict(id=1224), dict(id=1225), dict(id=1226, operation="packaging", status="completed", passed_qty=360, actual_output_qty=360), dict(id=1227, operation="storage_transfer", passed_qty=0)]
    return s


def test_exact_unused_selection_allowed(plan):
    reset.validate(plan)


def test_unknown_protection_is_never_replaced():
    with pytest.raises(AssertionError):
        reset.exception_definition(reset.ORIGINAL_FUNCTION + "-- another protection", 12, 34)


def test_exception_preserves_original_guard_and_is_transaction_scoped():
    definition = reset.exception_definition(reset.ORIGINAL_FUNCTION, 12, 34)
    assert "pg_backend_pid() = 12 AND txid_current() = 34" in definition
    assert "OLD.id IN (13230,13231,13232,13233)" in definition
    assert "OLD.production_order_id=312" in definition
    assert "r.deleted_package_ids::jsonb = '[13230,13231,13232,13233]'::jsonb" in definition
    original_guard = reset.ORIGINAL_FUNCTION.split("          IF EXISTS", 1)[1]
    assert definition.endswith("          IF EXISTS" + original_guard)


@pytest.mark.parametrize("change", ["received", "reserved", "shipment", "extra_package", "shared_run", "new_work_dependency", "quantity"])
def test_changed_or_used_evidence_refused(plan, change):
    if change == "received":
        plan["packages"][0]["received_at"] = "2026-10-13"
    elif change == "reserved":
        plan["finished_goods_stock"][0]["reserved_qty"] = 1
    elif change == "shipment":
        plan["shipment_packages"] = [dict(package_id=reset.IDS[0])]
    elif change == "extra_package":
        plan["packages"].append(dict(plan["packages"][0], id=99999))
    elif change == "shared_run":
        plan["package_print_runs"][0]["package_ids"].append(99999)
    elif change == "new_work_dependency":
        plan["work_dependencies"] = [dict(table="quality_checks", rows=[dict(id=1)])]
    else:
        plan["package_items"][0]["quantity"] = 16
    with pytest.raises(AssertionError):
        reset.validate(plan)
