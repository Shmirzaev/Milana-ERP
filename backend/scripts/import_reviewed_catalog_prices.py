"""Preview/apply pinned Excel+USD0.30 prices through the reviewed service."""
import argparse
import hashlib
import json
from pathlib import Path

from app.db.session import SessionLocal
from app.libs.dto.catalog.price_import_input import PriceImportManifest
from app.models.catalog.price_import_service import import_reviewed_prices, manifest_hash
from app.schemas import User


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--workbook", required=True, type=Path)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--actor-id", required=True, type=int)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    payload = json.loads(args.manifest.read_text(encoding="utf-8"))
    digest = manifest_hash(payload)
    if digest != payload.get("data_sha256") or digest != args.expected_manifest_sha256:
        raise RuntimeError("Reviewed import manifest hash changed")
    manifest = PriceImportManifest.model_validate(payload)
    if hashlib.sha256(args.workbook.read_bytes()).hexdigest() != manifest.source_workbook_sha256:
        raise RuntimeError("Source workbook hash changed")
    with SessionLocal() as db:
        actor = db.get(User, args.actor_id)
        if actor is None:
            raise RuntimeError("Existing import actor was not found")
        report = import_reviewed_prices(db, manifest, actor, apply=args.apply)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "changes"}))


if __name__ == "__main__":
    main()
