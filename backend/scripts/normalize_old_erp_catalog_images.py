"""Normalize browser-tolerant old-ERP images into pixel-identical lossless WebP."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from PIL import Image, ImageFile, ImageOps


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pixel_sha256(image: Image.Image) -> str:
    digest = hashlib.sha256()
    digest.update(f"{image.mode}:{image.width}x{image.height}:".encode())
    digest.update(image.tobytes())
    return digest.hexdigest()


def normalize_image(source: Path, output_dir: Path) -> dict[str, Any]:
    ImageFile.LOAD_TRUNCATED_IMAGES = True
    with Image.open(source) as opened:
        opened.load()
        oriented = ImageOps.exif_transpose(opened)
        has_alpha = "A" in oriented.getbands() or (
            oriented.mode == "P" and "transparency" in opened.info
        )
        pixels = oriented.convert("RGBA" if has_alpha else "RGB")
        source_pixels_sha256 = pixel_sha256(pixels)
        width, height = pixels.size
        temporary = output_dir / f".normalize-{os.getpid()}-{source.name}.webp"
        pixels.save(
            temporary,
            format="WEBP",
            lossless=True,
            quality=100,
            method=1,
            exact=has_alpha,
        )
        pixels.close()
    with Image.open(temporary) as check:
        check.load()
        normalized = check.convert("RGBA" if has_alpha else "RGB")
        if normalized.size != (width, height) or pixel_sha256(normalized) != source_pixels_sha256:
            temporary.unlink(missing_ok=True)
            raise ValueError(f"Lossless pixel validation failed: {source}")
        normalized.close()
    digest = file_sha256(temporary)
    target = output_dir / f"old_erp_catalog_hq_{digest[:24]}.webp"
    if target.exists():
        if file_sha256(target) != digest:
            temporary.unlink(missing_ok=True)
            raise ValueError(f"Existing normalized image differs: {target}")
        temporary.unlink()
    else:
        os.replace(temporary, target)
    return {
        "path": target.name,
        "sha256": digest,
        "bytes": target.stat().st_size,
        "width": width,
        "height": height,
        "content_type": "image/webp",
        "pixel_sha256": source_pixels_sha256,
    }


def build_mapping(manifest_path: Path, asset_root: Path, output_dir: Path) -> dict[str, Any]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_specs: dict[str, dict[str, Any]] = {}
    for row in payload.get("models") or []:
        for spec in [row["primary_image"], *(row.get("material_images") or [])]:
            source_specs[spec["sha256"]] = spec
    output_dir.mkdir(parents=True, exist_ok=True)
    mapping = {}
    for source_sha, spec in sorted(source_specs.items()):
        source = (asset_root.resolve() / spec["path"]).resolve()
        if asset_root.resolve() not in source.parents or not source.is_file():
            raise ValueError(f"Unsafe or missing source image: {spec['path']}")
        if file_sha256(source) != source_sha or source.stat().st_size != int(spec["bytes"]):
            raise ValueError(f"Source image changed: {source}")
        normalized = normalize_image(source, output_dir)
        mapping[source_sha] = {
            "source": {
                "path": spec["path"],
                "sha256": source_sha,
                "bytes": int(spec["bytes"]),
            },
            "normalized": normalized,
        }
    return {
        "version": 1,
        "kind": "old_erp_catalog_lossless_image_normalization",
        "source_manifest_sha256": file_sha256(manifest_path),
        "source_images": len(mapping),
        "normalized_unique_files": len(
            {row["normalized"]["sha256"] for row in mapping.values()}
        ),
        "mapping": mapping,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = build_mapping(args.manifest, args.asset_root, args.output_dir)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "source_images": payload["source_images"],
                "normalized_unique_files": payload["normalized_unique_files"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
