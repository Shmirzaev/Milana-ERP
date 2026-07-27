"""Prepare and reconcile UZERP ready-product inventory for the ERP importer.

The browser extraction stores each visible report row as a 94-element JSON
array in NDJSON format. This script converts those arrays into named records,
joins the separately extracted sewing-model report, and fails closed on
duplicate source records, invalid quantities, mixed warehouses, sequence
gaps, or ambiguous model mappings.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


COL = {
    "row_number": 0,
    "source_record_id": 2,
    "product_barcode": 3,
    "item_barcode": 4,
    "barcode_created_at": 6,
    "created_at": 7,
    "category": 10,
    "product": 11,
    "color": 12,
    "size": 15,
    "order_no": 20,
    "customer_order_no": 21,
    "warehouse": 23,
    "unit": 33,
    "total": 40,
    "product_article": 53,
    "available": 73,
    "model_name": 75,
    "model_code": 76,
    "variant": 78,
    "package_no": 80,
    "external_barcode": 81,
    "sewing_barcode": 84,
    "quantity": 89,
    "finished_name": 93,
}

EXPECTED_COLUMNS = 94
EXPECTED_WAREHOUSE = "TAYYOR MAHSULOT OMBORI"
EMPTY_TOKENS = {"", "-", "—", "null", "none", "n/a"}


def clean(value: Any) -> str:
    text = " ".join(str(value or "").strip().split())
    return "" if text.casefold() in EMPTY_TOKENS else text


def read_ndjson(path: Path) -> list[list[str]]:
    rows: list[list[str]] = []
    with path.open(encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, list) or len(row) != EXPECTED_COLUMNS:
                raise ValueError(
                    f"{path}:{line_no}: expected a {EXPECTED_COLUMNS}-column JSON array"
                )
            rows.append([clean(value) for value in row])
    return rows


def named_row(row: list[str]) -> dict[str, str]:
    return {name: row[index] for name, index in COL.items() if name != "row_number"}


def positive_piece_quantity(value: str, *, record_id: str) -> int:
    try:
        number = float(clean(value).replace(",", "."))
    except ValueError:
        raise ValueError(f"{record_id}: quantity is not numeric: {value!r}") from None
    rounded = int(round(number))
    if number <= 0 or abs(number - rounded) > 0.000001:
        raise ValueError(f"{record_id}: quantity is not a positive whole-piece count: {value!r}")
    return rounded


def row_sequence(rows: Iterable[list[str]]) -> list[int]:
    sequence: list[int] = []
    for row in rows:
        try:
            sequence.append(int(row[COL["row_number"]]))
        except ValueError:
            raise ValueError(f"Invalid report row number: {row[COL['row_number']]!r}") from None
    return sequence


def mapping_key(row: dict[str, str]) -> tuple[str, str, str]:
    return (clean(row["model_name"]), clean(row["model_code"]), clean(row["variant"]))


def build_model_maps(
    secondary_rows: list[list[str]],
) -> tuple[
    dict[str, tuple[str, str, str]],
    dict[str, tuple[str, str, str]],
    dict[tuple[str, str], tuple[str, str, str]],
    dict[tuple[str, str], tuple[str, str, str]],
    dict[str, tuple[str, str, str]],
    dict[str, tuple[str, str, str]],
    dict[str, list[tuple[str, str, str]]],
]:
    by_external_sets: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
    by_sewing_sets: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
    by_customer_product_sets: dict[
        tuple[str, str], set[tuple[str, str, str]]
    ] = defaultdict(set)
    by_order_product_sets: dict[
        tuple[str, str], set[tuple[str, str, str]]
    ] = defaultdict(set)
    by_customer_order_sets: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
    by_order_sets: dict[str, set[tuple[str, str, str]]] = defaultdict(set)

    for raw in secondary_rows:
        row = named_row(raw)
        identity = mapping_key(row)
        if not any(identity):
            continue
        if row["external_barcode"]:
            by_external_sets[row["external_barcode"]].add(identity)
        if row["sewing_barcode"]:
            by_sewing_sets[row["sewing_barcode"]].add(identity)
        if row["customer_order_no"] and row["product"]:
            by_customer_product_sets[
                (row["customer_order_no"], row["product"])
            ].add(identity)
        if row["order_no"] and row["product"]:
            by_order_product_sets[(row["order_no"], row["product"])].add(identity)
        if row["customer_order_no"]:
            by_customer_order_sets[row["customer_order_no"]].add(identity)
        if row["order_no"]:
            by_order_sets[row["order_no"]].add(identity)

    ambiguous: dict[str, list[tuple[str, str, str]]] = {}
    by_external: dict[str, tuple[str, str, str]] = {}
    by_sewing: dict[str, tuple[str, str, str]] = {}
    for key, identities in by_external_sets.items():
        if len(identities) == 1:
            by_external[key] = next(iter(identities))
        else:
            ambiguous[f"external:{key}"] = sorted(identities)
    for key, identities in by_sewing_sets.items():
        if len(identities) == 1:
            by_sewing[key] = next(iter(identities))
        else:
            ambiguous[f"sewing:{key}"] = sorted(identities)

    def unique_only(
        values: dict[Any, set[tuple[str, str, str]]],
    ) -> dict[Any, tuple[str, str, str]]:
        return {
            key: next(iter(identities))
            for key, identities in values.items()
            if len(identities) == 1
        }

    return (
        by_external,
        by_sewing,
        unique_only(by_customer_product_sets),
        unique_only(by_order_product_sets),
        unique_only(by_customer_order_sets),
        unique_only(by_order_sets),
        ambiguous,
    )


def prepare(
    primary_rows: list[list[str]],
    secondary_rows: list[list[str]],
    *,
    expected_rows: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if len(primary_rows) != expected_rows:
        raise ValueError(f"Expected {expected_rows} primary rows, found {len(primary_rows)}")

    sequence = row_sequence(primary_rows)
    expected_sequence = list(range(1, expected_rows + 1))
    if sequence != expected_sequence:
        mismatch = next(
            (
                (index + 1, actual)
                for index, actual in enumerate(sequence)
                if actual != index + 1
            ),
            (len(sequence) + 1, None),
        )
        raise ValueError(
            f"Report row sequence is not contiguous at expected {mismatch[0]} "
            f"(found {mismatch[1]!r})"
        )

    rows = [named_row(raw) for raw in primary_rows]
    source_ids = [row["source_record_id"] for row in rows]
    missing_ids = sum(not source_id for source_id in source_ids)
    duplicate_ids = [value for value, count in Counter(source_ids).items() if value and count > 1]
    if missing_ids:
        raise ValueError(f"{missing_ids} rows have no source system number")
    if duplicate_ids:
        raise ValueError(f"Duplicate source system numbers: {duplicate_ids[:20]}")

    warehouses = Counter(row["warehouse"] or "(blank)" for row in rows)
    unexpected_warehouses = {
        warehouse: count
        for warehouse, count in warehouses.items()
        if warehouse != EXPECTED_WAREHOUSE
    }
    if unexpected_warehouses:
        raise ValueError(f"Unexpected warehouses in primary data: {unexpected_warehouses}")

    (
        by_external,
        by_sewing,
        by_customer_product,
        by_order_product,
        by_customer_order,
        by_order,
        ambiguous_mappings,
    ) = build_model_maps(secondary_rows)
    resolved_direct = 0
    resolved_external = 0
    resolved_sewing = 0
    resolved_customer_product = 0
    resolved_order_product = 0
    resolved_customer_order = 0
    resolved_order = 0
    unresolved = 0
    mapping_conflicts: list[dict[str, Any]] = []
    quantities: list[int] = []
    available_quantities: list[int] = []
    available_mismatches = 0

    for row in rows:
        record_id = row["source_record_id"]
        quantity = positive_piece_quantity(row["quantity"], record_id=record_id)
        quantities.append(quantity)
        available = (
            positive_piece_quantity(row["available"], record_id=record_id)
            if row["available"]
            else quantity
        )
        if available > quantity:
            raise ValueError(
                f"{record_id}: available quantity {available} exceeds original quantity {quantity}"
            )
        available_quantities.append(available)
        if available != quantity:
            available_mismatches += 1

        direct = mapping_key(row)
        external = by_external.get(row["external_barcode"])
        sewing = by_sewing.get(row["sewing_barcode"])
        candidates = {
            candidate
            for candidate in (direct, external, sewing)
            if candidate and any(candidate)
        }
        if len(candidates) > 1:
            mapping_conflicts.append(
                {
                    "source_record_id": record_id,
                    "direct": direct,
                    "external": external,
                    "sewing": sewing,
                }
            )
            continue
        if any(direct):
            resolved_direct += 1
            chosen = direct
        elif external:
            resolved_external += 1
            chosen = external
        elif sewing:
            resolved_sewing += 1
            chosen = sewing
        else:
            fallback_candidates = [
                (
                    "customer_order_product",
                    by_customer_product.get(
                        (row["customer_order_no"], row["product"])
                    ),
                ),
                (
                    "order_product",
                    by_order_product.get((row["order_no"], row["product"])),
                ),
                (
                    "customer_order",
                    by_customer_order.get(row["customer_order_no"]),
                ),
                ("order", by_order.get(row["order_no"])),
            ]
            fallback_candidates = [
                (label, candidate)
                for label, candidate in fallback_candidates
                if candidate and any(candidate)
            ]
            fallback_identities = {
                candidate for _, candidate in fallback_candidates
            }
            if len(fallback_identities) > 1:
                mapping_conflicts.append(
                    {
                        "source_record_id": record_id,
                        "fallback_candidates": fallback_candidates,
                    }
                )
                continue
            if fallback_candidates:
                label, chosen = fallback_candidates[0]
                if label == "customer_order_product":
                    resolved_customer_product += 1
                elif label == "order_product":
                    resolved_order_product += 1
                elif label == "customer_order":
                    resolved_customer_order += 1
                else:
                    resolved_order += 1
            else:
                unresolved += 1
                chosen = ("", "", "")
        row["model_name"], row["model_code"], row["variant"] = chosen
        row["quantity"] = str(quantity)

    if mapping_conflicts:
        raise ValueError(
            f"{len(mapping_conflicts)} primary rows have conflicting model mappings; "
            f"first conflicts: {mapping_conflicts[:5]}"
        )

    source_digest = hashlib.sha256(
        "\n".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            for row in rows
        ).encode("utf-8")
    ).hexdigest()
    profile = {
        "row_count": len(rows),
        "piece_quantity": sum(quantities),
        "available_piece_quantity": sum(available_quantities),
        "depleted_piece_quantity": sum(quantities) - sum(available_quantities),
        "distinct_source_records": len(set(source_ids)),
        "available_quantity_mismatch_rows": available_mismatches,
        "units": dict(Counter(row["unit"] or "(blank)" for row in rows).most_common()),
        "model_mapping": {
            "direct": resolved_direct,
            "external_barcode": resolved_external,
            "sewing_barcode": resolved_sewing,
            "customer_order_product": resolved_customer_product,
            "order_product": resolved_order_product,
            "customer_order": resolved_customer_order,
            "order": resolved_order,
            "unresolved": unresolved,
            "ambiguous_secondary_codes": len(ambiguous_mappings),
        },
        "warehouse_rows": dict(warehouses),
        "source_digest_sha256": source_digest,
    }
    payload = {
        "source": {
            "system": "UZERP",
            "warehouse_id": "18",
            "warehouse_name": EXPECTED_WAREHOUSE,
            "expected_rows": len(rows),
            "expected_quantity": sum(quantities),
            "expected_available_quantity": sum(available_quantities),
            "source_digest_sha256": source_digest,
        },
        "rows": rows,
    }
    return payload, profile


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primary", type=Path, required=True)
    parser.add_argument("--secondary", type=Path, required=True)
    parser.add_argument("--expected-rows", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile-output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    primary_rows = read_ndjson(args.primary)
    secondary_rows = read_ndjson(args.secondary)
    payload, profile = prepare(
        primary_rows,
        secondary_rows,
        expected_rows=args.expected_rows,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.profile_output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    rendered_profile = json.dumps(profile, ensure_ascii=False, indent=2, sort_keys=True)
    args.profile_output.write_text(rendered_profile + "\n", encoding="utf-8")
    print(json.dumps(profile, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
