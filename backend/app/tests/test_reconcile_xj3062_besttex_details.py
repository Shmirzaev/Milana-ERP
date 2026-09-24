from copy import deepcopy

import pytest

from scripts.reconcile_xj3062_besttex_20260912 import CANONICAL, next_canonical_details


def test_reconciliation_preserves_extensions_and_updates_both_model_number_spellings() -> None:
    previous = {
        "general": {"model_no": "XJ3062", "modelNo": "XJ3062", "variant_no": "V-1"},
        "legacy_extension": {"keep": [1, 2]},
    }
    frozen = deepcopy(previous)

    result = next_canonical_details(previous)

    assert previous == frozen
    assert result["general"] == {"model_no": CANONICAL, "modelNo": CANONICAL, "variant_no": "V-1"}
    assert result["legacy_extension"] == previous["legacy_extension"]


@pytest.mark.parametrize("invalid_kind", ["oversized", "deep"])
def test_reconciliation_rejects_changed_unbounded_legacy_without_mutation(invalid_kind: str) -> None:
    extension: object = "x" * (70 * 1024) if invalid_kind == "oversized" else {"leaf": True}
    if invalid_kind == "deep":
        for _ in range(20):
            extension = {"next": extension}
    previous = {"general": {"model_no": "XJ3062"}, "legacy_extension": extension}
    frozen = deepcopy(previous)

    with pytest.raises(ValueError, match="details_json cannot exceed"):
        next_canonical_details(previous)

    assert previous == frozen


def test_reconciliation_preserves_exact_unchanged_oversized_legacy() -> None:
    previous = {"general": {"model_no": CANONICAL}, "legacy_extension": "x" * (70 * 1024)}

    assert next_canonical_details(previous) == previous
