"""Export the exact prices displayed by the Milana catalog admin.

The catalog is composed from extracted rows, manual overrides, and visibility
overrides. This script mirrors that merge so a reviewed manifest can be applied
to ERP variants without relying on browser timing or guessing missing values.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


API_ROOT = "https://catalog.milanapremium.uz"
CATALOGS = (
    (1, "01_Staple_Model_Catalog.pdf", 52),
    (2, "02_Milana_Man_Premium_Collection.pdf", 76),
    (3, "03_Kindergarten_Set.pdf", 35),
    (4, "04_Milana_Products_in_Stock.pdf", 1385),
    (5, "05_Winter_Collection.pdf", 153),
    (6, "06_3_IP.pdf", 48),
)
CYRILLIC_CONFUSABLES = str.maketrans(
    {
        "а": "a", "в": "b", "е": "e", "к": "k", "м": "m", "н": "h",
        "о": "o", "р": "p", "с": "c", "т": "t", "х": "x", "у": "y",
    }
)


def fetch_json(path: str) -> Any:
    request = urllib.request.Request(
        f"{API_ROOT}{path}",
        headers={"Accept": "application/json", "User-Agent": "Milana-ERP-price-sync/1.0"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def product_key(row: dict[str, Any]) -> str:
    return f"{row.get('source_pdf') or ''}:{int(row.get('page') or 0)}:{int(row.get('card_index') or 0)}"


def has_image(row: dict[str, Any]) -> bool:
    return bool(row.get("image_url") or row.get("image_path") or row.get("image_storage_path"))


def normalize_identity(value: Any) -> str:
    text = " ".join(str(value or "").strip().casefold().split()).translate(CYRILLIC_CONFUSABLES)
    return re.sub(r"[^a-z0-9]+", "", text)


def normalize_variant(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^[vV\u0412\u0432]\s*[-_ ]*", "", text, count=1)
    return normalize_identity(text)


def positive_price(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        price = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return price if price > 0 else None


def visible(row: dict[str, Any]) -> bool:
    return row.get("is_visible") is not False and row.get("extraction_status") != "admin_hidden"


def load_catalog(catalog_id: int, source_pdf: str) -> list[dict[str, Any]]:
    encoded = urllib.parse.quote(source_pdf)
    base = fetch_json(f"/api/products?source_pdf={encoded}&include_hidden=true")
    manual = fetch_json(f"/api/manual-products?source_pdf={encoded}&include_hidden=true")
    rows: dict[str, dict[str, Any]] = {
        product_key(row): dict(row)
        for row in base
        if isinstance(row, dict) and row.get("source_pdf") == source_pdf
    }
    for row in manual:
        if not isinstance(row, dict) or row.get("source_pdf") != source_pdf:
            continue
        key = product_key(row)
        rows[key] = {**rows.get(key, {}), **row}

    if catalog_id == 4:
        imaged = {
            (str(row.get("model_code") or ""), str(row.get("product_code") or ""))
            for row in rows.values()
            if row.get("model_code") and row.get("product_code") and has_image(row)
        }
        rows = {
            key: row for key, row in rows.items()
            if has_image(row)
            or not row.get("model_code")
            or not row.get("product_code")
            or (str(row.get("model_code")), str(row.get("product_code"))) not in imaged
        }

    visibility_payload = fetch_json(f"/api/visibility-overrides?source_pdf={encoded}")
    overrides = visibility_payload.get("visibility", {}) if isinstance(visibility_payload, dict) else {}
    for key, row in rows.items():
        if overrides.get(key) is False:
            row["is_visible"] = False
            row["extraction_status"] = "admin_hidden"
    return sorted(rows.values(), key=lambda row: (int(row.get("page") or 0), int(row.get("card_index") or 0)))


def source_ref(row: dict[str, Any], catalog_id: int) -> dict[str, Any]:
    return {
        "catalog_id": catalog_id,
        "source_pdf": row.get("source_pdf"),
        "page": int(row.get("page") or 0),
        "card_index": int(row.get("card_index") or 0),
        "model_no": str(row.get("model_code") or "").strip(),
        "variant_no": str(row.get("product_code") or "").strip(),
        "price": str(positive_price(row.get("price"))) if positive_price(row.get("price")) is not None else None,
        "currency": str(row.get("currency") or "USD").upper(),
        "visible": visible(row),
        "image_url": row.get("image_url"),
        "manual_override": bool(row.get("manual_storage")),
    }


def load_reviewed_cards(path: Path) -> dict[int, list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError("Reviewed card export must be a JSON array")
    by_catalog: dict[int, list[dict[str, Any]]] = defaultdict(list)
    source_pdf_by_id = {catalog_id: source_pdf for catalog_id, source_pdf, _ in CATALOGS}
    for item in payload:
        if not isinstance(item, dict):
            continue
        catalog_id = int(item.get("catalogId") or 0)
        if catalog_id not in source_pdf_by_id:
            raise RuntimeError(f"Unknown catalog id in reviewed cards: {catalog_id}")
        by_catalog[catalog_id].append({
            "source_pdf": source_pdf_by_id[catalog_id],
            "page": 0,
            "card_index": int(item.get("index") or 0) + 1,
            "model_code": item.get("model"),
            "product_code": item.get("variant"),
            "price": item.get("price"),
            "currency": "USD",
            "is_visible": item.get("clientVisible") is not False,
            "extraction_status": "browser_reviewed",
        })
    return by_catalog


def build_manifest(*, allow_count_drift: bool = False, cards_input: Path | None = None) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    excluded: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    reviewed_cards = load_reviewed_cards(cards_input) if cards_input else None
    for catalog_id, source_pdf, expected_count in CATALOGS:
        rows = reviewed_cards.get(catalog_id, []) if reviewed_cards is not None else load_catalog(catalog_id, source_pdf)
        counts[str(catalog_id)] = len(rows)
        if len(rows) != expected_count and not allow_count_drift:
            raise RuntimeError(
                f"Catalog {catalog_id} changed: expected {expected_count} cards, received {len(rows)}. "
                "Review the source before exporting with --allow-count-drift."
            )
        for row in rows:
            model_no = str(row.get("model_code") or "").strip()
            variant_no = str(row.get("product_code") or "").strip()
            model_key = normalize_identity(model_no)
            variant_key = normalize_variant(variant_no)
            reason = None
            if not model_key:
                reason = "missing_model_no"
            elif not variant_key:
                reason = "missing_variant_no"
            elif positive_price(row.get("price")) is None:
                reason = "missing_positive_price"
            elif str(row.get("currency") or "USD").upper() != "USD":
                reason = "unsupported_currency"
            if reason:
                excluded.append({"reason": reason, **source_ref(row, catalog_id)})
                continue
            grouped[(model_key, variant_key)].append((catalog_id, row))

    prices: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for (model_key, variant_key), candidates in sorted(grouped.items()):
        unique_prices = sorted({positive_price(row.get("price")) for _, row in candidates})
        chosen: Decimal | None = unique_prices[0] if len(unique_prices) == 1 else None
        resolution = "single_price" if len(unique_prices) == 1 and len(candidates) == 1 else "duplicate_same_price"
        if len(unique_prices) > 1:
            visible_prices = {positive_price(row.get("price")) for _, row in candidates if visible(row)}
            if len(visible_prices) == 1:
                chosen = next(iter(visible_prices))
                resolution = "only_visible_price"
        refs = [source_ref(row, catalog_id) for catalog_id, row in candidates]
        if chosen is None:
            unresolved.append({
                "reason": "conflicting_visible_prices",
                "normalized_model_no": model_key,
                "normalized_variant_no": variant_key,
                "sources": refs,
            })
            continue
        display = next((row for _, row in candidates if visible(row) and positive_price(row.get("price")) == chosen), candidates[0][1])
        prices.append({
            "normalized_model_no": model_key,
            "normalized_variant_no": variant_key,
            "model_no": str(display.get("model_code") or "").strip(),
            "variant_no": str(display.get("product_code") or "").strip(),
            "selling_price": str(chosen),
            "currency": "USD",
            "resolution": resolution,
            "sources": refs,
        })

    issue_counts: dict[str, int] = defaultdict(int)
    for issue in excluded:
        issue_counts[issue["reason"]] += 1
    manifest = {
        "schema_version": 1,
        "source": f"{API_ROOT}/admin.html",
        "source_method": "authenticated_browser_review" if cards_input else "catalog_api_merge",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "catalog_card_counts": counts,
        "catalog_card_total": sum(counts.values()),
        "prices": prices,
        "price_count": len(prices),
        "excluded_count": len(excluded),
        "excluded_counts": dict(sorted(issue_counts.items())),
        "excluded": excluded,
        "unresolved_conflicts": unresolved,
    }
    hash_payload = {key: value for key, value in manifest.items() if key != "exported_at"}
    canonical = json.dumps(hash_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    manifest["manifest_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--cards-input",
        type=Path,
        required=True,
        help="Authenticated browser export of every displayed catalog card",
    )
    parser.add_argument("--import-output", type=Path)
    parser.add_argument("--allow-count-drift", action="store_true")
    args = parser.parse_args()
    manifest = build_manifest(allow_count_drift=args.allow_count_drift, cards_input=args.cards_input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.import_output:
        import_payload = {
            "schema_version": 1,
            "source": manifest["source"],
            "source_method": manifest["source_method"],
            "reviewed_manifest_sha256": manifest["manifest_sha256"],
            "catalog_card_counts": manifest["catalog_card_counts"],
            "excluded_counts": manifest["excluded_counts"],
            "prices": [
                {
                    "model_no": row["model_no"],
                    "variant_no": row["variant_no"],
                    "normalized_model_no": row["normalized_model_no"],
                    "normalized_variant_no": row["normalized_variant_no"],
                    "selling_price": row["selling_price"],
                    "currency": row["currency"],
                }
                for row in manifest["prices"]
            ],
        }
        canonical_import = json.dumps(import_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        import_payload["data_sha256"] = hashlib.sha256(canonical_import.encode("utf-8")).hexdigest()
        args.import_output.parent.mkdir(parents=True, exist_ok=True)
        args.import_output.write_text(json.dumps(import_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "catalog_card_total": manifest["catalog_card_total"],
        "price_count": manifest["price_count"],
        "excluded_count": manifest["excluded_count"],
        "excluded_counts": manifest["excluded_counts"],
        "unresolved_conflicts": len(manifest["unresolved_conflicts"]),
        "manifest_sha256": manifest["manifest_sha256"],
        "import_output": str(args.import_output) if args.import_output else None,
    }, indent=2))


if __name__ == "__main__":
    main()
