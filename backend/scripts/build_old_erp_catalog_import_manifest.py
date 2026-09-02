"""Build the reviewed, hashable import manifest for an old-ERP catalog delta."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageFile, ImageOps

from scripts.analyze_old_erp_catalog_delta import clean, normalized_base


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def common_value(values: Iterable[Any]) -> Any:
    cleaned = [value for value in values if value not in (None, "", [])]
    if not cleaned:
        return None
    counts = Counter(json.dumps(value, ensure_ascii=False, sort_keys=True) for value in cleaned)
    encoded = sorted(counts, key=lambda value: (-counts[value], value))[0]
    return json.loads(encoded)


def validate_asset(root: Path, spec: dict[str, Any]) -> dict[str, Any]:
    path = (root / spec["path"]).resolve()
    if root.resolve() not in path.parents or not path.is_file():
        raise ValueError(f"Unsafe or missing asset: {spec.get('path')!r}")
    if path.stat().st_size != int(spec["bytes"]) or file_sha256(path) != spec["sha256"]:
        raise ValueError(f"Asset bytes changed: {path}")
    try:
        ImageFile.LOAD_TRUNCATED_IMAGES = True
        with Image.open(path) as image:
            image.load()
            width, height = ImageOps.exif_transpose(image).size
    except OSError as exc:
        raise ValueError(f"Asset cannot be fully decoded: {path}: {exc}") from exc
    expected_dimensions = (int(spec["width"]), int(spec["height"]))
    if all(expected_dimensions) and (width, height) != expected_dimensions:
        raise ValueError(f"Asset dimensions changed: {path}")
    return {
        "path": spec["path"],
        "sha256": spec["sha256"],
        "bytes": int(spec["bytes"]),
        "width": width,
        "height": height,
        "content_type": spec["content_type"],
    }


def build_manifest(
    plan_path: Path,
    production_path: Path,
    master_assets_path: Path,
    variant_assets_path: Path,
    master_sizes_path: Path,
    asset_root: Path,
) -> dict[str, Any]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    production = json.loads(production_path.read_text(encoding="utf-8"))
    master_assets = json.loads(master_assets_path.read_text(encoding="utf-8"))
    variant_assets = json.loads(variant_assets_path.read_text(encoding="utf-8"))
    master_sizes = json.loads(master_sizes_path.read_text(encoding="utf-8"))
    production_codes = {
        normalized_base(row.get("code")) for row in production.get("models") or []
    }

    records = []
    target_codes: set[str] = set()
    for candidate in plan["planned_creates"]:
        model_no, variant_key = candidate["normalized_identity"]
        code = f"{model_no}-{variant_key}"
        code_key = normalized_base(code)
        if code_key in target_codes:
            raise ValueError(f"Duplicate target code: {code}")
        # Same-family production codes are the only plausible normalized
        # collisions for this identity shape; the production importer performs
        # the final all-catalog collision guard immediately before apply.
        if code_key in production_codes:
            raise ValueError(f"Target code already exists in production family: {code}")
        target_codes.add(code_key)

        master = candidate["master_models"][0]
        family = candidate.get("production_family") or []
        old_rows = candidate["old_rows"]
        old_ids = [str(row["old_id"]) for row in old_rows]
        master_id = str(master["old_model_id"])
        family_sizes = sorted(
            {clean(size) for row in family for size in row.get("sizes") or [] if clean(size)}
        )
        sizes = family_sizes or [clean(size) for size in master_sizes.get(master_id, []) if clean(size)]
        if not sizes:
            raise ValueError(f"No sizes for {model_no} / {variant_key}")
        colors = sorted({clean(row.get("color")) for row in old_rows if clean(row.get("color"))})

        primary = master_assets.get(master_id)
        if primary:
            primary = validate_asset(asset_root, primary)
            primary_source = {"kind": "old_erp_master", "old_model_id": master_id}
        else:
            variant_candidates = [
                variant_assets.get(old_id, {}).get("main") for old_id in old_ids
            ]
            variant_candidates = [spec for spec in variant_candidates if spec]
            if not variant_candidates:
                raise ValueError(f"No original picture for {model_no} / {variant_key}")
            primary_raw = max(
                variant_candidates,
                key=lambda spec: (int(spec["width"]) * int(spec["height"]), int(spec["bytes"])),
            )
            primary = validate_asset(asset_root, primary_raw)
            primary_source = {"kind": "old_erp_variant", "old_variant_ids": old_ids}

        material_images = []
        seen_material: set[str] = set()
        for old_id in old_ids:
            spec = variant_assets.get(old_id, {}).get("main")
            if not spec or spec["sha256"] in seen_material:
                continue
            seen_material.add(spec["sha256"])
            material_images.append(
                {
                    **validate_asset(asset_root, spec),
                    "source": {"kind": "old_erp_variant", "old_variant_id": old_id},
                }
            )

        name = clean(master.get("product")) or clean(
            common_value(row.get("name") for row in family)
        ) or clean(master.get("name")) or model_no
        product_type = clean(master.get("product")) or clean(
            common_value(row.get("product_type") for row in family)
        ) or None
        record = {
            "model_number": model_no,
            "variant_number": f"V-{variant_key}",
            "code": code,
            "name": name,
            "category": common_value(row.get("category") for row in family),
            "brand_id": common_value(row.get("brand_id") for row in family),
            "collection_id": common_value(row.get("collection_id") for row in family),
            "product_type": product_type,
            "season": common_value(row.get("season") for row in family),
            "sam_minutes": common_value(row.get("sam_minutes") for row in family) or 0,
            "sizes": sizes,
            "colors": colors,
            "primary_image": {**primary, "source": primary_source},
            "material_images": material_images,
            "old_erp": {
                "old_model_id": master_id,
                "old_variant_ids": old_ids,
                "master_name": clean(master.get("name")),
                "master_product": clean(master.get("product")),
                "master_variant": clean(master.get("model_variant")),
                "variant_rows": [
                    {
                        "old_id": str(row["old_id"]),
                        "variant_no": clean(row.get("variant_no")),
                        "sewing_model_ref": clean(row.get("sewing_model_ref")),
                        "color": clean(row.get("color")),
                        "design": clean(row.get("design")),
                        "thermo_print": bool(variant_assets.get(str(row["old_id"]), {}).get("thermo")),
                        "embroidery": bool(
                            variant_assets.get(str(row["old_id"]), {}).get("embroidery")
                        ),
                    }
                    for row in old_rows
                ],
            },
        }
        records.append(record)

    return {
        "version": 1,
        "package_kind": "old_erp_catalog_full_delta_2026_09_02",
        "expected_models": len(records),
        "expected_primary_images": len(records),
        "expected_material_images": sum(len(row["material_images"]) for row in records),
        "expected_sizes": sum(len(row["sizes"]) for row in records),
        "expected_colors": sum(len(row["colors"]) for row in records),
        "excluded": plan["excluded"],
        "unresolved": plan["unresolved"],
        "models": records,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("production", type=Path)
    parser.add_argument("master_assets", type=Path)
    parser.add_argument("variant_assets", type=Path)
    parser.add_argument("master_sizes", type=Path)
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = build_manifest(
        args.plan,
        args.production,
        args.master_assets,
        args.variant_assets,
        args.master_sizes,
        args.asset_root,
    )
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {key: value for key, value in payload.items() if key.startswith("expected_")},
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
