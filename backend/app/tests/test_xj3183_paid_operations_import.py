from copy import deepcopy
from pathlib import Path

import pytest

from scripts.import_xj3183_paid_operations import FACTORIES, load_operations, next_details

MANIFEST = Path(__file__).resolve().parents[2] / "data/xj3183-paid-operations-20260907.json"


def test_workbook_operations_preserve_order_rates_and_all_factories():
    manifest, operations = load_operations(MANIFEST)
    assert len(operations) == 108
    assert len({row["id"] for row in operations}) == 108
    for factory in FACTORIES:
        rows = [row for row in operations if row["sewingFactory"] == factory]
        assert [row["sourceOrder"] for row in rows] == list(range(1, 37))
        assert [row["name"] for row in rows] == [row["name"] for row in manifest["operations"]]
        assert [row["rate"] for row in rows] == [row["rate"] for row in manifest["operations"]]
        assert rows[-1]["rate"] == "0"
        assert all(row["selected"] for row in rows)


def test_import_is_idempotent_and_preserves_unrelated_details():
    _, operations = load_operations(MANIFEST)
    previous = {"general": {"model_no": "XJ3183"}, "old_erp_catalog_sync": {"keep": True}}
    frozen = deepcopy(previous)
    result = next_details(previous, operations)
    assert previous == frozen
    assert result["general"] == previous["general"]
    assert result["old_erp_catalog_sync"] == previous["old_erp_catalog_sync"]
    assert next_details(result, operations) == result
    with pytest.raises(ValueError, match="refusing to overwrite"):
        next_details({"paid_operations": [{"name": "Payroll's new work"}]}, operations)
    with pytest.raises(ValueError, match="refusing to overwrite"):
        next_details({"paidOperations": [{"name": "Legacy work"}]}, operations)


def test_import_rejects_changed_source(tmp_path):
    changed = tmp_path / "changed.json"
    changed.write_bytes(MANIFEST.read_bytes().replace(b'"8680"', b'"9999"') + b" ")
    with pytest.raises(ValueError, match="SHA-256"):
        load_operations(changed)
