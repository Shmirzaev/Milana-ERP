"""Build a non-mutating reconciliation plan for old-ERP catalog variants."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from scripts.analyze_old_erp_catalog_delta import (
    clean,
    normalized_base,
    old_identity,
    production_identity,
)


EXCLUDED_IDENTITIES = {
    ("XJ3062", "5709"): "user-confirmed mixed-material pack; no catalog variant",
}


def _master_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "old_model_id": clean(row.get("old_model_id")),
        "model_no": clean(row.get("model_no")),
        "name": clean(row.get("name")),
        "product": clean(row.get("product")),
        "model_variant": clean(row.get("model_variant")),
        "style": clean(row.get("style")),
        "company": clean(row.get("company")),
        "image": row.get("image"),
        "edit_href": clean(row.get("edit_href")),
    }


def _old_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "old_id": clean(row.get("old_id")),
        "model_no": clean(row.get("model_no")),
        "variant_no": clean(row.get("variant_no")),
        "sewing_model_ref": clean(row.get("sewing_model_ref")),
        "color": clean(row.get("color")),
        "design": clean(row.get("design")),
        "main_image": row.get("main_image"),
        "thermo_image": row.get("thermo_image"),
        "embroidery_image": row.get("embroidery_image"),
        "design_image": row.get("design_image"),
        "edit_href": clean(row.get("edit_href")),
    }


def _linked_masters(
    old_rows: list[dict[str, Any]],
    masters_by_base: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], str]:
    matched: dict[str, dict[str, Any]] = {}
    for old_row in old_rows:
        candidates = masters_by_base.get(old_identity(old_row)[0], [])
        old_ref = clean(old_row.get("sewing_model_ref")).casefold()
        exact = [row for row in candidates if clean(row.get("name")).casefold() == old_ref]
        selected = exact if exact else (candidates if len(candidates) == 1 else [])
        for row in selected:
            matched[clean(row.get("old_model_id"))] = row
    if matched:
        return [matched[key] for key in sorted(matched, key=int)], "linked"
    base = old_identity(old_rows[0])[0]
    candidates = masters_by_base.get(base, [])
    if not candidates:
        return [], "no_master_model"
    return candidates, "ambiguous_master_model"


def build_plan(
    old_path: Path,
    master_path: Path,
    production_path: Path,
) -> dict[str, Any]:
    old_payload = json.loads(old_path.read_text(encoding="utf-8"))
    master_payload = json.loads(master_path.read_text(encoding="utf-8"))
    production_payload = json.loads(production_path.read_text(encoding="utf-8"))
    old_rows = old_payload.get("rows") or []
    master_rows = master_payload.get("rows") or []
    production_rows = production_payload.get("models") or []

    old_by_identity: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in old_rows:
        identity = old_identity(row)
        if all(identity):
            old_by_identity[identity].append(row)

    production_by_identity: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    production_by_base: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in production_rows:
        identity = production_identity(row)
        if all(identity):
            production_by_identity[identity].append(row)
            production_by_base[identity[0]].append(row)

    masters_by_base: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in master_rows:
        base = normalized_base(row.get("model_no"))
        if base:
            masters_by_base[base].append(row)

    planned = []
    excluded = []
    unresolved = []
    for identity, grouped_rows in sorted(old_by_identity.items()):
        if identity in production_by_identity:
            continue
        old_summaries = [_old_summary(row) for row in sorted(grouped_rows, key=lambda x: int(clean(x.get("old_id")) or 0))]
        masters, link_status = _linked_masters(grouped_rows, masters_by_base)
        candidate = {
            "normalized_identity": list(identity),
            "old_rows": old_summaries,
            "master_link_status": link_status,
            "master_models": [_master_summary(row) for row in masters],
            "production_family": [
                {
                    "id": int(row["id"]),
                    "code": clean(row.get("code")),
                    "name": clean(row.get("name")),
                    "general_details": row.get("general_details"),
                    "category": row.get("category"),
                    "brand_id": row.get("brand_id"),
                    "collection_id": row.get("collection_id"),
                    "product_type": row.get("product_type"),
                    "season": row.get("season"),
                    "sizes": row.get("sizes") or [],
                    "colors": row.get("colors") or [],
                    "images": row.get("images") or [],
                }
                for row in production_by_base.get(identity[0], [])
            ],
        }
        exclusion_reason = EXCLUDED_IDENTITIES.get(identity)
        if exclusion_reason:
            candidate["reason"] = exclusion_reason
            excluded.append(candidate)
        elif identity[0] and set(identity[0]) == {"0"}:
            candidate["reason"] = "placeholder all-zero model number"
            excluded.append(candidate)
        elif link_status != "linked":
            candidate["reason"] = link_status
            unresolved.append(candidate)
        elif not any(
            (row.get("image") or {}).get("present")
            and int((row.get("image") or {}).get("sourceLength") or 0) > 100
            and int((row.get("image") or {}).get("width") or 0) > 0
            and int((row.get("image") or {}).get("height") or 0) > 0
            for row in candidate["master_models"]
        ) and not any(
            (row.get("main_image") or {}).get("present")
            and int((row.get("main_image") or {}).get("sourceLength") or 0) > 100
            and int((row.get("main_image") or {}).get("width") or 0) > 0
            and int((row.get("main_image") or {}).get("height") or 0) > 0
            for row in candidate["old_rows"]
        ) and not any(
            image.get("is_primary")
            for row in candidate["production_family"]
            for image in row.get("images") or []
        ):
            candidate["reason"] = "no readable model or variant picture"
            unresolved.append(candidate)
        else:
            planned.append(candidate)

    return {
        "version": 1,
        "sources": {
            "old_variants": str(old_path),
            "old_master_models": str(master_path),
            "production_catalog": str(production_path),
            "production_guard": production_payload.get("guard"),
        },
        "counts": {
            "old_variant_rows": len(old_rows),
            "old_unique_identities": len(old_by_identity),
            "production_models": len(production_rows),
            "already_present": sum(
                1 for identity in old_by_identity if identity in production_by_identity
            ),
            "planned_creates": len(planned),
            "excluded": len(excluded),
            "unresolved": len(unresolved),
        },
        "planned_creates": planned,
        "excluded": excluded,
        "unresolved": unresolved,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("old", type=Path)
    parser.add_argument("master", type=Path)
    parser.add_argument("production", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    plan = build_plan(args.old, args.master, args.production)
    args.output.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(plan["counts"], ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
