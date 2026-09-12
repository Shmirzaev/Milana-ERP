"""Check all catalogue image sources and recover truncated-JPEG thumbnails.

Original files and database rows are never changed. Run with --apply to write
only the derived 160/320px WebP cache; the default is read-only inspection.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image
from sqlalchemy import text

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.image_storage import prebuild_webp_thumbnails


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = Path(settings.MODEL_FILES_DIR).resolve()
    with SessionLocal() as db:
        db.execute(text("SET TRANSACTION READ ONLY"))
        urls = db.execute(text("SELECT DISTINCT file_url FROM model_images ORDER BY file_url")).scalars().all()
    counts: Counter[str] = Counter()
    failures = []
    for index, url in enumerate(urls, 1):
        name = url.removeprefix("/storage/model-files/")
        path = root / name
        if not url.startswith("/storage/model-files/") or Path(name).name != name or path.resolve().parent != root:
            failures.append({"url": url, "error": "Unsupported source path"})
            continue
        try:
            content = path.read_bytes()
            try:
                with Image.open(path) as image:
                    image.load()
                counts["valid_sources"] += 1
            except OSError as exc:
                if not content.startswith(b"\xff\xd8") or "truncated" not in str(exc).lower():
                    raise
                counts["truncated_jpeg_sources"] += 1
                if args.apply:
                    digest = hashlib.sha256(content).digest()
                    created = prebuild_webp_thumbnails(
                        content,
                        thumbnail_root=root / "_thumbs",
                        source_file_name=name,
                        recover_legacy_jpeg=True,
                    )
                    for thumbnail in created:
                        with Image.open(thumbnail) as image:
                            image.load()
                    if hashlib.sha256(path.read_bytes()).digest() != digest:
                        raise RuntimeError("Original source changed during recovery")
                    counts["recovered_thumbnails"] += len(created)
        except Exception as exc:
            failures.append({"url": url, "error": str(exc)})
        if index % 500 == 0:
            print(json.dumps({"checked": index, "total": len(urls), "counts": counts}), flush=True)
    print(json.dumps({"checked": len(urls), "apply": args.apply, "counts": counts, "failures": failures}), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
