"""Compare a captured old-ERP variant list with a new-ERP catalog snapshot."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any


CONFUSABLES = str.maketrans(
    {
        "А": "A",
        "В": "B",
        "С": "C",
        "Е": "E",
        "Н": "H",
        "К": "K",
        "М": "M",
        "О": "O",
        "Р": "P",
        "Т": "T",
        "Х": "X",
        "У": "Y",
        "І": "I",
        "Ј": "J",
    }
)


def clean(value: Any) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).strip().split())


def normalized_base(value: Any) -> str:
    return "".join(ch for ch in clean(value).upper().translate(CONFUSABLES) if ch.isalnum())


def normalized_variant(value: Any) -> str:
    value = re.sub(r"^V[\s_-]*", "", clean(value).upper().translate(CONFUSABLES), count=1)
    key = "".join(ch for ch in value if ch.isalnum())
    return str(int(key)) if key.isdigit() else key


def old_identity(row: dict[str, Any]) -> tuple[str, str]:
    return normalized_base(row.get("model_no")), normalized_variant(row.get("variant_no"))


def production_identity(row: dict[str, Any]) -> tuple[str, str]:
    general = row.get("general_details")
    if not isinstance(general, dict):
        general = {}
    return (
        normalized_base(general.get("model_no") or general.get("modelNo")),
        normalized_variant(general.get("variant_no") or general.get("variantNo")),
    )


def compact_old(row: dict[str, Any]) -> dict[str, Any]:
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
        "source_page": row.get("source_page"),
    }


def analyze(old_path: Path, production_path: Path) -> dict[str, Any]:
    old_payload = json.loads(old_path.read_text(encoding="utf-8"))
    production_payload = json.loads(production_path.read_text(encoding="utf-8"))
    old_rows = old_payload.get("rows") or []
    production_rows = production_payload.get("models") or []

    old_by_identity: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    invalid_old = []
    for row in old_rows:
        identity = old_identity(row)
        if not all(identity):
            invalid_old.append(compact_old(row))
            continue
        old_by_identity[identity].append(row)

    production_by_identity: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in production_rows:
        identity = production_identity(row)
        if all(identity):
            production_by_identity[identity].append(row)

    missing = []
    for identity, rows in sorted(old_by_identity.items()):
        if identity in production_by_identity:
            continue
        representative = max(
            rows,
            key=lambda row: (
                int(bool((row.get("main_image") or {}).get("present"))),
                int((row.get("main_image") or {}).get("sourceLength") or 0),
                int(clean(row.get("old_id")) or 0),
            ),
        )
        missing.append(
            {
                "normalized_identity": list(identity),
                "old_duplicate_rows": len(rows),
                "old_ids": sorted(clean(row.get("old_id")) for row in rows),
                **compact_old(representative),
            }
        )

    duplicate_old = []
    for identity, rows in sorted(old_by_identity.items()):
        if len(rows) <= 1:
            continue
        signatures = {
            (
                clean(row.get("model_no")),
                clean(row.get("variant_no")),
                clean(row.get("color")),
                clean(row.get("design")),
                bool((row.get("main_image") or {}).get("present")),
                int((row.get("main_image") or {}).get("sourceLength") or 0),
            )
            for row in rows
        }
        duplicate_old.append(
            {
                "normalized_identity": list(identity),
                "rows": len(rows),
                "conflicting_metadata": len(signatures) > 1,
                "old_ids": sorted(clean(row.get("old_id")) for row in rows),
            }
        )

    duplicate_production = []
    for identity, rows in sorted(production_by_identity.items()):
        if len(rows) > 1:
            duplicate_production.append(
                {
                    "normalized_identity": list(identity),
                    "model_ids": [int(row["id"]) for row in rows],
                    "codes": [clean(row.get("code")) for row in rows],
                }
            )

    return {
        "old_source": {
            "path": str(old_path),
            "captured_at": old_payload.get("captured_at"),
            "rows": len(old_rows),
            "valid_identity_rows": len(old_rows) - len(invalid_old),
            "unique_identities": len(old_by_identity),
            "invalid_identity_rows": invalid_old,
            "duplicate_identity_groups": duplicate_old,
        },
        "production_source": {
            "path": str(production_path),
            "guard": production_payload.get("guard"),
            "models": len(production_rows),
            "models_with_identity": sum(len(rows) for rows in production_by_identity.values()),
            "unique_identities": len(production_by_identity),
            "duplicate_identity_groups": duplicate_production,
        },
        "comparison": {
            "old_identities_already_in_production": sum(
                1 for identity in old_by_identity if identity in production_by_identity
            ),
            "old_identities_missing_from_production": len(missing),
            "missing": missing,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("old", type=Path)
    parser.add_argument("production", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = analyze(args.old, args.production)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "old_rows": report["old_source"]["rows"],
                "old_unique_identities": report["old_source"]["unique_identities"],
                "production_models": report["production_source"]["models"],
                "already_present": report["comparison"]["old_identities_already_in_production"],
                "missing": report["comparison"]["old_identities_missing_from_production"],
                "invalid_old_rows": len(report["old_source"]["invalid_identity_rows"]),
                "old_duplicate_groups": len(report["old_source"]["duplicate_identity_groups"]),
                "production_duplicate_groups": len(
                    report["production_source"]["duplicate_identity_groups"]
                ),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
