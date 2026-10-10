import importlib.util
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location(
    "normalize_catalog_sizes", Path(__file__).parents[2] / "scripts/normalize_catalog_sizes.py"
)
cleanup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleanup)


def row(key, size, model=1, measurement=None):
    return {"id": key, "model_id": model, "size": size, "measurement_json": measurement}


def test_cleanup_preserves_numeric_ranges_and_measurements_within_each_model():
    source = [row(1, "XL-50", measurement={"length": 70}), row(2, "50"),
              row(3, "XL-50", model=2), row(4, "XS"), row(5, "98-104"),
              row(6, "FREE SIZE"), row(7, "Free Size"), row(8, "12XL-72")]
    result = cleanup.plan(source)
    assert result["duplicate_rows"] == 2
    assert result["standalone_rows"] == 1
    assert {item["id"] for item in result["removed"]} == {1, 4, 6}
    updates = {item["after"]["id"]: item["after"] for item in result["updates"]}
    assert updates[2]["measurement_json"] == {"length": 70}
    assert updates[3]["size"] == "50"
    assert updates[8]["size"] == "72"
    assert 5 not in updates
    final = [updates.get(item["id"], item) for item in source if item["id"] not in {1, 4, 6}]
    assert not cleanup.plan(final)["updates"]
    assert not cleanup.plan(final)["removed"]
    assert cleanup.fingerprint(source) != cleanup.fingerprint(final)


@pytest.mark.parametrize("source", [
    [row(1, "XS", measurement={"length": 10})],
    [row(1, "50", measurement={"length": 10}), row(2, "XL-50", measurement={"length": 20})],
    [row(1, "unknown")],
])
def test_unreviewed_or_conflicting_data_is_rejected(source):
    with pytest.raises(ValueError):
        cleanup.plan(source)
