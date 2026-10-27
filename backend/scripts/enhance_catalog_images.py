from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps, UnidentifiedImageError


SUPPORTED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upscale local ERP catalog images while keeping a lossless backup of every original."
    )
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--backup-dir", required=True, type=Path)
    parser.add_argument("--target-long-edge", type=int, default=1280)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def enhanced_image(source: Path, target_long_edge: int) -> Image.Image:
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened)
        image.load()
        if image.mode not in {"RGB", "RGBA"}:
            image = image.convert("RGBA" if "A" in image.getbands() else "RGB")

    width, height = image.size
    scale = max(1.0, target_long_edge / max(width, height))
    target_size = (max(1, round(width * scale)), max(1, round(height * scale)))
    if target_size != image.size:
        image = image.resize(target_size, Image.Resampling.LANCZOS)

    # A restrained unsharp mask restores edge definition after enlarging without
    # changing garment colors or fabric motifs.
    return image.filter(ImageFilter.UnsharpMask(radius=1.15, percent=125, threshold=3))


def save_atomic(image: Image.Image, destination: Path) -> None:
    temporary = destination.with_name(f".{destination.name}.enhancing")
    suffix = destination.suffix.lower()
    if suffix == ".png":
        image.save(temporary, format="PNG", optimize=False, compress_level=3)
    elif suffix in {".jpg", ".jpeg"}:
        image.convert("RGB").save(temporary, format="JPEG", quality=96, subsampling=0, optimize=True)
    else:
        image.save(temporary, format="WEBP", quality=96, method=6)

    with Image.open(temporary) as check:
        check.verify()
    temporary.replace(destination)


def main() -> None:
    args = parse_args()
    input_dir = args.input_dir.resolve()
    backup_dir = args.backup_dir.resolve()
    target_long_edge = max(640, min(int(args.target_long_edge), 3840))

    if not input_dir.is_dir():
        raise FileNotFoundError(f"Input directory does not exist: {input_dir}")
    if input_dir == backup_dir or input_dir in backup_dir.parents:
        raise ValueError("Backup directory must not contain the input directory")

    candidates = sorted(
        path for path in input_dir.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    )
    summary = {"found": len(candidates), "enhanced": 0, "already_enhanced": 0, "failed": 0}

    for source in candidates:
        backup = backup_dir / source.name
        try:
            with Image.open(source) as current:
                current_size = current.size
            if max(current_size) >= target_long_edge:
                summary["already_enhanced"] += 1
                continue

            if args.dry_run:
                summary["enhanced"] += 1
                continue

            backup_dir.mkdir(parents=True, exist_ok=True)
            if not backup.exists():
                shutil.copy2(source, backup)
            result = enhanced_image(backup, target_long_edge)
            save_atomic(result, source)
            summary["enhanced"] += 1
        except (OSError, UnidentifiedImageError) as exc:
            summary["failed"] += 1
            print(f"FAILED {source.name}: {exc}")

    print(
        " ".join(f"{key}={value}" for key, value in summary.items())
        + f" target_long_edge={target_long_edge} dry_run={args.dry_run}"
    )
    if summary["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
