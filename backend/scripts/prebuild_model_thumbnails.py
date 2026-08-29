from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.services.image_storage import PREBUILT_THUMBNAIL_SIZES, ensure_webp_thumbnail


def main() -> int:
    parser = argparse.ArgumentParser(description="Prebuild cached WebP model thumbnails")
    parser.add_argument("--force", action="store_true", help="Replace thumbnails that already exist")
    parser.add_argument("--root", default=settings.MODEL_FILES_DIR)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    thumbnail_root = root / "_thumbs"
    thumbnail_root.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    generated = 0
    cached = 0
    skipped = 0
    failed: list[str] = []

    sources = sorted(path for path in root.iterdir() if path.is_file())
    for source in sources:
        for size in PREBUILT_THUMBNAIL_SIZES:
            destination = thumbnail_root / f"{size}_{source.name}.webp"
            if destination.exists() and not args.force:
                cached += 1
                continue
            if args.force:
                destination.unlink(missing_ok=True)
            try:
                ensure_webp_thumbnail(
                    source_path=str(source),
                    destination_path=str(destination),
                    size=size,
                )
                generated += 1
            except Exception as exc:
                if str(exc).startswith("415") or "supported image" in str(exc):
                    skipped += 1
                else:
                    failed.append(f"{source.name}@{size}: {exc}")

    elapsed = time.perf_counter() - started
    print(
        f"thumbnail_backfill root={root} generated={generated} cached={cached} "
        f"skipped={skipped} failed={len(failed)} elapsed_seconds={elapsed:.3f}"
    )
    for row in failed[:20]:
        print(f"FAILED {row}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
