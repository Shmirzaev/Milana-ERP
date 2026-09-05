from scripts.repair_old_erp_package_size_quantity import (
    allocate_sizes,
    choose_package_quantities,
)


def package(package_id: int, quantity: int, suffix: int | None = None) -> dict:
    suffix = suffix if suffix is not None else package_id
    return {
        "package_id": package_id,
        "package_no": f"OLD-100-{suffix}",
        "barcode": f"uzerp_ii_100_{suffix}",
        "total_quantity": quantity,
    }


def test_choose_package_quantities_deduplicates_exact_total() -> None:
    result = choose_package_quantities(
        [package(10, 90, 1), package(11, 90, 2), package(12, 90, 3)],
        90,
    )

    assert result == {10: 90}


def test_choose_package_quantities_keeps_two_when_old_total_requires_two() -> None:
    result = choose_package_quantities(
        [package(10, 60, 1), package(11, 90, 2), package(12, 90, 3)],
        180,
    )

    assert result == {11: 90, 12: 90}


def test_choose_package_quantities_preserves_protected_package() -> None:
    result = choose_package_quantities(
        [package(10, 60, 1), package(11, 60, 2), package(12, 60, 3)],
        60,
        {11},
    )

    assert result == {11: 60}


def test_choose_package_quantities_adjusts_when_no_exact_subset_exists() -> None:
    result = choose_package_quantities(
        [package(10, 90, 1), package(11, 90, 2), package(12, 90, 3)],
        174,
    )

    assert result == {10: 90, 11: 84}


def test_allocate_sizes_splits_equal_assortments_across_two_packages() -> None:
    allocation = allocate_sizes(
        {"M-46": 30, "L-48": 30, "XL-50": 30, "2XL-52": 30, "3XL-54": 30, "4XL-56": 30},
        {11: 90, 12: 90},
    )

    assert allocation[11] == [
        {"size": "M-46", "quantity": 15},
        {"size": "L-48", "quantity": 15},
        {"size": "XL-50", "quantity": 15},
        {"size": "2XL-52", "quantity": 15},
        {"size": "3XL-54", "quantity": 15},
        {"size": "4XL-56", "quantity": 15},
    ]
    assert allocation[12] == allocation[11]


def test_allocate_sizes_preserves_uneven_totals_exactly() -> None:
    allocation = allocate_sizes(
        {"S-44": 9, "M-46": 9, "L-48": 6},
        {3: 20, 4: 4},
    )

    assert sum(item["quantity"] for item in allocation[3]) == 20
    assert sum(item["quantity"] for item in allocation[4]) == 4
    aggregate: dict[str, int] = {}
    for items in allocation.values():
        for item in items:
            aggregate[item["size"]] = aggregate.get(item["size"], 0) + item["quantity"]
    assert aggregate == {"S-44": 9, "M-46": 9, "L-48": 6}
