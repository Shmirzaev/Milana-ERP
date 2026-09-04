"""Build an immutable package manifest from the reviewed live UZERP stock audit."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from fractions import Fraction
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_compact_sizes(path: Path) -> dict[str, list[tuple[str, int]]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or not lines[0].startswith("# size-dictionary="):
        raise ValueError("Compact size audit is missing its size dictionary")
    sizes = lines[0].split("=", 1)[1].split(",")
    result: dict[str, list[tuple[str, int]]] = {}
    for line in lines[1:]:
        qr, encoded = line.split(":", 1)
        if qr in result:
            raise ValueError(f"Duplicate compact-size QR {qr}")
        values: list[tuple[str, int]] = []
        for item in encoded.split(","):
            size_index, quantity = item.split(".", 1)
            values.append((sizes[int(size_index, 36)], int(quantity, 36)))
        result[qr] = values
    return result


def load_compact_totals(path: Path) -> dict[str, tuple[int, int]]:
    result: dict[str, tuple[int, int]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        qr, quantity, barcode_rows = line.split(":", 2)
        if qr in result:
            raise ValueError(f"Duplicate live-total QR {qr}")
        parsed = (int(quantity), int(barcode_rows))
        if not qr.isdigit() or parsed[0] < 0 or parsed[1] < 0:
            raise ValueError(f"Invalid live-total row {line!r}")
        result[qr] = parsed
    return result


def load_jsonl_rows(path: Path) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        rows.extend(json.loads(line))
    return rows


def direct_row_map(prior_path: Path, resolution_path: Path) -> dict[str, list[Any]]:
    direct: dict[str, list[Any]] = {}
    for row in load_jsonl_rows(prior_path):
        qr = str(row[0])
        if qr in {"3313", "3388"}:
            direct[qr] = row
    for row in json.loads(resolution_path.read_text(encoding="utf-8"))["rows"]:
        direct[str(row[0])] = row
    return direct


def normalize_size_rows(values: list[tuple[str, int]], target: int) -> list[tuple[str, int]]:
    raw_total = sum(quantity for _, quantity in values)
    if raw_total <= 0:
        raise ValueError("Cannot normalize an empty size distribution")
    normalized = [(size, Fraction(quantity * target, raw_total)) for size, quantity in values]
    fractional = [(size, str(quantity)) for size, quantity in normalized if quantity.denominator != 1]
    if fractional:
        raise ValueError(f"Size normalization is fractional: {fractional}")
    result = [(size, int(quantity)) for size, quantity in normalized]
    if sum(quantity for _, quantity in result) != target or any(quantity <= 0 for _, quantity in result):
        raise ValueError("Normalized size distribution does not match the package total")
    return result


def identity(model_number: str, variant_number: str) -> tuple[str, str]:
    def token(value: str) -> str:
        return "".join(ch for ch in str(value or "").upper() if ch.isalnum())

    variant = str(variant_number or "").upper()
    if variant.startswith("V"):
        variant = variant[1:]
    return token(model_number), token(variant)


def build_manifest(args: argparse.Namespace) -> dict[str, Any]:
    plan_payload = json.loads(args.plan.read_text(encoding="utf-8"))
    summary_payload = json.loads(args.summary.read_text(encoding="utf-8"))
    plan = {str(row[0]): row for row in plan_payload["rows"]}
    summary = {str(row["external_qr"]): row for row in summary_payload["packages"]}
    sizes = load_compact_sizes(args.sizes)
    live_totals = load_compact_totals(args.live_totals)
    direct = direct_row_map(args.direct_prior, args.direct_resolution)
    if set(plan) != set(summary):
        raise ValueError("Candidate plan and reconciliation summary package sets differ")
    if set(plan) != set(live_totals):
        missing = sorted(set(plan) - set(live_totals), key=int)
        extra = sorted(set(live_totals) - set(plan), key=int)
        raise ValueError(f"Live-total package set differs: missing={missing}, extra={extra}")

    rows: list[dict[str, Any]] = []
    held: list[dict[str, Any]] = []
    for qr, plan_row in plan.items():
        original_quantity = int(plan_row[1])
        exhaustive_quantity, live_barcode_rows = live_totals[qr]
        exact = direct.get(qr)
        exact_items = list(exact[1]) if exact else []
        exact_total = int(exact[4]) if exact and len(exact) >= 5 else sum(int(item[1]) for item in exact_items)
        if exhaustive_quantity == 0:
            if exact_items or exact_total:
                raise ValueError(f"{qr}: direct query contradicts the zero exhaustive live total")
            held.append(
                {
                    "external_qr": qr,
                    "candidate_quantity": original_quantity,
                    "live_barcode_rows": live_barcode_rows,
                    "reason": "not_present_in_live_old_erp_stock_report",
                }
            )
            continue

        quantity = exact_total if exact_items else exhaustive_quantity
        if exact_items:
            item_source = [
                (str(item[2]), str(item[3]), str(item[0]), int(item[1])) for item in exact_items
            ]
        else:
            if qr not in sizes:
                raise ValueError(f"{qr}: no live size distribution")
            model_rows = plan_row[3]
            if len(model_rows) != 1:
                raise ValueError(f"{qr}: multi-model package requires an exact direct query")
            model_number, variant_number = str(model_rows[0][1]), str(model_rows[0][2])
            item_source = [
                (model_number, variant_number, size, item_quantity)
                for size, item_quantity in normalize_size_rows(sizes[qr], quantity)
            ]

        summary_models = {
            identity(model["model_no"], model["variant_no"]): model
            for model in summary[qr]["models"]
        }
        aggregated: dict[tuple[str, str, str], int] = defaultdict(int)
        for model_number, variant_number, size, item_quantity in item_source:
            aggregated[(model_number, variant_number, size)] += item_quantity

        items: list[dict[str, Any]] = []
        for (model_number, variant_number, size), item_quantity in sorted(aggregated.items()):
            model = summary_models.get(identity(model_number, variant_number))
            if not model:
                raise ValueError(f"{qr}: direct-query identity {model_number}/{variant_number} is not in the plan")
            hidden = model["resolution"] == "INVENTORY_ONLY_HIDDEN_MODEL"
            items.append(
                {
                    "model_number": model_number,
                    "variant_number": variant_number,
                    "size": size,
                    "quantity": item_quantity,
                    "target_kind": "hidden_legacy" if hidden else "catalog",
                    "expected_model_id": None if hidden else int(model["catalog_model_id"]),
                    "expected_model_code": "" if hidden else str(model["catalog_code"]),
                }
            )
        if sum(item["quantity"] for item in items) != quantity:
            raise ValueError(f"{qr}: item total does not equal package total")

        color_values = [str(model_row[6] or "").strip() for model_row in plan_row[3]]
        color = next((value for value in color_values if value), "Not specified")
        rows.append(
            {
                "source_record_id": qr,
                "external_qr": qr,
                "qr_code": f"uzerp_ii_{qr}_1",
                "package_no": f"OLD-{qr}-1",
                "quantity": quantity,
                "candidate_quantity": original_quantity,
                "exhaustive_quantity": exhaustive_quantity,
                "quantity_source": "direct_exact_query" if exact_items else "exhaustive_item_barcode_report",
                "quantity_corrected_from_live_query": quantity != original_quantity,
                "weight_kg": None,
                "allowed_blank_weight": True,
                "color": color,
                "items": items,
            }
        )

    rows.sort(key=lambda row: int(row["external_qr"]))
    held.sort(key=lambda row: int(row["external_qr"]))
    source_files = {
        "candidate_plan": {"name": args.plan.name, "sha256": sha256(args.plan)},
        "reconciliation_summary": {"name": args.summary.name, "sha256": sha256(args.summary)},
        "live_size_audit": {"name": args.sizes.name, "sha256": sha256(args.sizes)},
        "live_package_totals": {"name": args.live_totals.name, "sha256": sha256(args.live_totals)},
        "direct_query_checkpoint": {"name": args.direct_prior.name, "sha256": sha256(args.direct_prior)},
        "direct_query_resolution": {"name": args.direct_resolution.name, "sha256": sha256(args.direct_resolution)},
    }
    return {
        "version": 1,
        "source_system": "UZERP_LIVE_STOCK",
        "source_warehouse_id": "18",
        "source_warehouse_name": "TAYYOR MAHSULOT OMBORI",
        "destination_warehouse_id": 8,
        "destination_warehouse_name": "Finished Goods",
        "source_files": source_files,
        "expected_packages": len(rows),
        "expected_quantity": sum(row["quantity"] for row in rows),
        "expected_item_rows": sum(len(row["items"]) for row in rows),
        "expected_corrected_quantity_packages": sum(row["quantity_corrected_from_live_query"] for row in rows),
        "expected_hidden_legacy_items": sum(
            item["target_kind"] == "hidden_legacy" for row in rows for item in row["items"]
        ),
        "held_packages": held,
        "rows": rows,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--sizes", type=Path, required=True)
    parser.add_argument("--live-totals", type=Path, required=True)
    parser.add_argument("--direct-prior", type=Path, required=True)
    parser.add_argument("--direct-resolution", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_manifest(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "sha256": sha256(args.output),
                "packages": payload["expected_packages"],
                "quantity": payload["expected_quantity"],
                "item_rows": payload["expected_item_rows"],
                "corrected_quantity_packages": payload["expected_corrected_quantity_packages"],
                "held_packages": len(payload["held_packages"]),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
