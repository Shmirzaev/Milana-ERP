"""Plan or apply the reviewed catalog prices to exact ERP model variants."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.db.session import SessionLocal
from app.models import Model, User
from app.services.audit import log_action


CYRILLIC_CONFUSABLES = str.maketrans(
    {
        "а": "a", "в": "b", "е": "e", "к": "k", "м": "m", "н": "h",
        "о": "o", "р": "p", "с": "c", "т": "t", "х": "x", "у": "y",
    }
)


def normalize_identity(value: Any) -> str:
    text_value = " ".join(str(value or "").strip().casefold().split()).translate(CYRILLIC_CONFUSABLES)
    return re.sub(r"[^a-z0-9]+", "", text_value)


def normalize_variant(value: Any) -> str:
    text_value = re.sub(r"^[vV\u0412\u0432]\s*[-_ ]*", "", str(value or "").strip(), count=1)
    return normalize_identity(text_value)


def model_parts(model: Model) -> tuple[str, str]:
    details = model.details_json if isinstance(model.details_json, dict) else {}
    general = details.get("general") if isinstance(details.get("general"), dict) else {}
    code = str(model.code or "").strip()
    left, separator, right = code.rpartition("-")
    model_no = str(general.get("model_no") or general.get("modelNo") or (left if separator else code)).strip()
    variant_no = str(general.get("variant_no") or general.get("variantNo") or (right if separator else "")).strip()
    return model_no, variant_no


def load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected_hash = str(payload.pop("data_sha256", ""))
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    actual_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if not expected_hash or actual_hash != expected_hash:
        raise RuntimeError(f"Manifest hash mismatch: expected {expected_hash or '<missing>'}, got {actual_hash}")
    payload["data_sha256"] = expected_hash
    prices = payload.get("prices")
    if not isinstance(prices, list) or not prices:
        raise RuntimeError("Manifest has no prices")
    return payload


def plan_import(db, manifest: dict[str, Any]) -> tuple[dict[str, Any], list[tuple[Model, dict[str, Any]]]]:
    db_models: dict[tuple[str, str], list[Model]] = defaultdict(list)
    db_variants: dict[str, list[Model]] = defaultdict(list)
    for model in db.query(Model).filter(Model.catalog_scope == "standard").all():
        model_no, variant_no = model_parts(model)
        key = (normalize_identity(model_no), normalize_variant(variant_no))
        if key[0] and key[1]:
            db_models[key].append(model)
        if key[1]:
            db_variants[key[1]].append(model)

    updates: list[tuple[Model, dict[str, Any]]] = []
    manifest_variant_counts = Counter(str(row["normalized_variant_no"]) for row in manifest["prices"])
    matched: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    duplicate_identities: list[dict[str, Any]] = []
    unchanged: list[dict[str, Any]] = []
    unique_variant_matches = 0
    for row in manifest["prices"]:
        key = (str(row["normalized_model_no"]), str(row["normalized_variant_no"]))
        candidates = db_models.get(key, [])
        match_rule = "exact_model_variant"
        if not candidates:
            variant_candidates = db_variants.get(key[1], [])
            if len(variant_candidates) == 1 and manifest_variant_counts[key[1]] == 1:
                # Old catalog model text contains several known OCR/typing errors.
                # A globally unique exact variant number is deterministic and is
                # stronger evidence than guessing or creating a second model.
                candidates = variant_candidates
                match_rule = "globally_unique_variant_no"
                unique_variant_matches += 1
        reference = {
            "model_no": row["model_no"],
            "variant_no": row["variant_no"],
            "selling_price": row["selling_price"],
            "currency": row["currency"],
        }
        if not candidates:
            missing.append(reference)
            continue
        if len(candidates) > 1:
            # Do not create or choose another identity. Apply the same exact
            # variant price to every already-existing duplicate so either legacy
            # row behaves consistently in old orders and current selectors.
            duplicate_identities.append({
                **reference,
                "erp_models": [{"id": model.id, "code": model.code} for model in candidates],
            })
        for model in candidates:
            target = Decimal(str(row["selling_price"]))
            current = Decimal(str(model.selling_price)) if model.selling_price is not None else None
            result = {**reference, "model_id": model.id, "erp_code": model.code, "match_rule": match_rule, "previous_price": str(current) if current is not None else None}
            matched.append(result)
            if current == target and model.selling_price_currency == row["currency"]:
                unchanged.append(result)
            else:
                updates.append((model, row))

    report = {
        "manifest_data_sha256": manifest["data_sha256"],
        "manifest_price_count": len(manifest["prices"]),
        "matched_identity_count": len(manifest["prices"]) - len(missing),
        "matched_model_count": len(matched),
        "would_update_count": len(updates),
        "unchanged_count": len(unchanged),
        "missing_count": len(missing),
        "duplicate_identity_count": len(duplicate_identities),
        "globally_unique_variant_match_count": unique_variant_matches,
        "matched": matched,
        "missing": missing,
        "duplicate_identities": duplicate_identities,
    }
    return report, updates


def verify_snapshot(manifest: dict[str, Any], snapshot_path: Path) -> dict[str, Any]:
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    model_index: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    model_no_index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    variant_no_index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for model in snapshot.get("models", []):
        general = model.get("general_details") if isinstance(model.get("general_details"), dict) else {}
        key = (
            normalize_identity(general.get("model_no") or model.get("code")),
            normalize_variant(general.get("variant_no")),
        )
        if key[0] and key[1]:
            model_index[key].append(model)
        if key[0]:
            model_no_index[key[0]].append(model)
        if key[1]:
            variant_no_index[key[1]].append(model)
    missing: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    matched_model_count = 0
    unique_variant_matches = 0
    manifest_variant_counts = Counter(str(row["normalized_variant_no"]) for row in manifest["prices"])
    for row in manifest["prices"]:
        key = (str(row["normalized_model_no"]), str(row["normalized_variant_no"]))
        candidates = model_index.get(key, [])
        reference = {
            "model_no": row["model_no"],
            "variant_no": row["variant_no"],
            "selling_price": row["selling_price"],
        }
        if (
            not candidates
            and len(variant_no_index.get(key[1], [])) == 1
            and manifest_variant_counts[key[1]] == 1
        ):
            candidates = variant_no_index[key[1]]
            unique_variant_matches += 1
        if not candidates:
            missing.append({
                **reference,
                "same_model_no": [
                    {"id": model.get("id"), "code": model.get("code"), "general_details": model.get("general_details")}
                    for model in model_no_index.get(key[0], [])
                ],
                "same_variant_no": [
                    {"id": model.get("id"), "code": model.get("code"), "general_details": model.get("general_details")}
                    for model in variant_no_index.get(key[1], [])
                ],
            })
            continue
        matched_model_count += len(candidates)
        if len(candidates) > 1:
            duplicates.append({
                **reference,
                "erp_models": [{"id": model.get("id"), "code": model.get("code")} for model in candidates],
            })
    return {
        "manifest_data_sha256": manifest["data_sha256"],
        "manifest_price_count": len(manifest["prices"]),
        "matched_identity_count": len(manifest["prices"]) - len(missing),
        "matched_model_count": matched_model_count,
        "missing_count": len(missing),
        "duplicate_identity_count": len(duplicates),
        "globally_unique_variant_match_count": unique_variant_matches,
        "missing": missing,
        "duplicate_identities": duplicates,
        "snapshot_guard": snapshot.get("guard"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--actor-email")
    parser.add_argument("--actor-id", type=int)
    parser.add_argument("--snapshot", type=Path)
    args = parser.parse_args()
    manifest = load_manifest(args.manifest)
    if args.snapshot:
        if args.apply:
            raise RuntimeError("--snapshot verification cannot be combined with --apply")
        report = verify_snapshot(manifest, args.snapshot)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({key: value for key, value in report.items() if not isinstance(value, list)}, indent=2))
        return
    db = SessionLocal()
    try:
        revision = db.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if revision != "0113_variant_selling_price":
            raise RuntimeError(f"Database revision must be 0113_variant_selling_price, got {revision}")
        report, updates = plan_import(db, manifest)
        report["database_revision"] = revision
        report["applied"] = False
        if args.apply:
            if not args.actor_email and not args.actor_id:
                raise RuntimeError("--actor-email or --actor-id is required with --apply")
            actor_query = db.query(User)
            actor = (
                actor_query.filter(User.id == args.actor_id).one_or_none()
                if args.actor_id
                else actor_query.filter(User.email == args.actor_email).one_or_none()
            )
            if not actor:
                raise RuntimeError("Price import actor was not found")
            changed_at = datetime.now(timezone.utc)
            for model, row in updates:
                model.selling_price = Decimal(str(row["selling_price"]))
                model.selling_price_currency = str(row["currency"])
                model.selling_price_source = "catalog"
                model.selling_price_request_id = None
                model.selling_price_updated_at = changed_at
            log_action(
                db,
                actor,
                "sync_catalog_variant_prices",
                "ModelSellingPriceCatalogSync",
                new_value={
                    "manifest_data_sha256": manifest["data_sha256"],
                    "matched_identity_count": report["matched_identity_count"],
                    "matched_model_count": report["matched_model_count"],
                    "updated_count": len(updates),
                    "missing_count": report["missing_count"],
                    "duplicate_identity_count": report["duplicate_identity_count"],
                },
            )
            db.commit()
            report["applied"] = True
            report["applied_count"] = len(updates)
            report["applied_at"] = changed_at.isoformat()
        else:
            db.rollback()
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({key: value for key, value in report.items() if not isinstance(value, list)}, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
