"""Plan and apply an additive, hash-pinned old ERP catalog reconciliation.

No stock, order, payroll, user, existing identity or configured operation list is
changed. Ambiguous identities are reported, never merged. The plan is reviewable
JSON; apply locks/rechecks all targets and rejects any intervening catalog drift.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re

from sqlalchemy import text

from app.models import Model, ModelColor, ModelImage, ModelSize, SystemSetting, User
from app.services.audit import log_action

SOURCE_KEY = "old-erp-catalog-parity-20260930"
CONFUSABLES = str.maketrans("АВСЕНКМОРТХУІЈ", "ABCEHKMOPTXYIJ")
SECTIONS = {"Tikuv": "sewing", "Кнопки": "sewing", "Упаковка": "packaging",
            "Склад": "packaging", "Чистка": "pressing", "Контроль": "sewing"}
GENERAL = {"Дата": "source_date", "Код Модели": "code", "Продукт": "product", "Имя": "name",
           "Вариант": "model_variant", "Описание": "description", "Стиль": "style", "Компания": "company",
           "Тип Планирования": "planning_type", "Основная модель пошива": "parent_sew_model",
           "Вышивка": "embroidery", "Термо Печать": "thermal_print"}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def normalize(value):
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper().translate(CONFUSABLES))


def variant_number(value):
    value = re.sub(r"^V[-\s]*", "", str(value or "").strip().upper())
    return str(int(value)) if value.isdigit() else normalize(value)


def identity(model):
    details = model.get("details_json") or {}
    general = details.get("general") or {}
    base = general.get("model_no") or general.get("modelNo")
    variant = general.get("variant_no") or general.get("variantNo")
    if not base:
        match = re.fullmatch(r"(.+?)[- ]V?[- ]*(\d+)", model.get("code", ""), re.I)
        base, variant = match.groups() if match else (model.get("code"), "")
    return normalize(base), variant_number(variant)


def source_record(record):
    grids = record["grids"]
    if len(grids) != 3:
        raise ValueError(f"Incomplete detail grids for source {record['old_model_id']}")
    general = {translated: record["general"].get(original, "") for original, translated in GENERAL.items()}
    sizes = next(g["rows"] for g in grids if "Размер Варианта Швейной Модели" in g["headers"])
    raw_operations = next(g["rows"] for g in grids if "Операции" in g["headers"])
    recipes = next(g["rows"] for g in grids if "Вид Расхода" in g["headers"])
    operations = []
    for row in raw_operations:
        if len(row) != 8 or row[5] not in SECTIONS:
            raise ValueError(f"Unknown operation columns/stage: {row}")
        price = row[3].replace(" ", "").replace(",", ".")
        if not Decimal(price).is_finite() or Decimal(price) < 0:
            raise ValueError("Invalid source rate")
        operations.append({"source_order": int(row[0]), "name": row[1], "duration": row[2], "price": price,
                           "currency": row[4], "stage": row[5], "control_change_direction": row[6],
                           "final_operation": row[7].lower() == "true"})
    if [x["source_order"] for x in operations] != list(range(1, len(operations)+1)):
        raise ValueError("Incomplete or reordered source operations")
    return {"source_key": SOURCE_KEY, "master_id": int(record["old_model_id"]), "general": general,
            "operations": operations, "recipes": [{"source_order": int(r[0]), "product": r[1],
            "order": int(r[0]), "quantity": r[2], "sewing_type_list": r[3]} for r in recipes], "sizes": [r[1] for r in sizes]}


def paid_operations(source):
    result = []
    for raw in source["operations"]:
        sha = digest(raw)
        section = SECTIONS[raw["stage"]]
        result.append({"id": f"old-erp-op-{sha[:24]}", "selected": True, "section": section,
                       "code": f"OERP-{ {'sewing': 'SEW', 'pressing': 'PRS', 'packaging': 'PKG'}[section]}-{raw['source_order']:03d}-{sha[:16].upper()}",
                       "name": raw["name"], "rate": raw["price"], "sourceOrder": raw["source_order"],
                       "duration": raw["duration"], "currency": raw["currency"], "sourceStage": raw["stage"],
                       "changeDirection": raw["control_change_direction"], "finalOperation": raw["final_operation"],
                       "quantityMode": "batch", "customQuantity": 0, "copies": 1, "splitMode": "none", "splitQuantities": []})
    return result


def merge_details(existing, desired, source, *, new=False):
    details = deepcopy(existing or {})
    general = dict(details.get("general") or {})
    for key, value in desired.items():
        if value not in (None, "") and general.get(key) in (None, ""):
            general[key] = value
    details["general"] = general
    configured = details.get("paid_operations") or details.get("paidOperations")
    if not configured and (new or source["operations"]):
        details["paid_operations"] = paid_operations(source)
    # Keep original migration receipts. This additional source record also
    # supplies missing recipe/general details to the existing detail-page reader.
    details["old_erp_catalog_reconciliation"] = source
    if not details.get("old_erp_delta_migration"):
        details["old_erp_delta_migration"] = source
    return details


def build_plan(snapshot, records, variants, assets, numbering, *, master_catalog=None):
    models = snapshot["models"]
    current = defaultdict(list)
    for row in models:
        if row["catalog_scope"] == "standard" and not row["code"].startswith("LEGACY-"):
            current[identity(row)].append(row)
    masters = defaultdict(list)
    by_id = {}
    for record in master_catalog if master_catalog is not None else records:
        masters[normalize(record["model_no"])].append(record)
    for record in records:
        by_id[str(record["old_model_id"])] = record
    children = {}
    for table in ("model_sizes", "model_colors", "model_images"):
        children[table] = defaultdict(list)
        for row in snapshot[table]:
            children[table][row["model_id"]].append(row)
    entries, issues, considered = [], [], set()

    def add(base, variant, source, variant_row=None):
        key = normalize(base), variant_number(variant)
        if key in considered:
            return
        considered.add(key)
        matches = current[key]
        if len(matches) > 1:
            issues.append({"identity": list(key), "reason": "existing_duplicates_preserved", "ids": [m["id"] for m in matches]})
            return
        if not key[0] or set(key[0]) == {"0"}:
            issues.append({"identity": list(key), "reason": "invalid_source_identity"})
            return
        existing = matches[0] if matches else None
        src = deepcopy(source)
        src["variant_id"] = int(variant_row["old_id"]) if variant_row else None
        src["variant"] = deepcopy(variant_row) if variant_row else None
        g = src["general"]
        desired = {"model_no": base.strip(), "variant_no": f"V-{key[1]}" if key[1] else "",
                   "qolip_no": g["name"], "mold_no": g["name"], "legacy_source_date": g["source_date"],
                   "legacy_product": g["product"], "legacy_style": g["style"], "legacy_company": g["company"],
                   "legacy_planning_type": g["planning_type"], "legacy_parent_sew_model": g["parent_sew_model"],
                   "legacy_master_embroidery": g["embroidery"], "legacy_master_thermal_print": g["thermal_print"]}
        if variant_row:
            desired.update(variant_color=variant_row["color"], legacy_design=variant_row["design"],
                           legacy_thermal_print=variant_row["thermo"], legacy_embroidery=variant_row["embroidery"])
        existing_details = existing["details_json"] if existing else {}
        mid = existing["id"] if existing else None
        new_details = merge_details(existing_details, desired, src, new=existing is None)
        present_sizes = {r["size"].strip().casefold() for r in children["model_sizes"][mid]}
        sizes = [s for s in dict.fromkeys(src["sizes"]) if s.strip().casefold() not in present_sizes]
        present_colors = {r["color_name"].strip().casefold() for r in children["model_colors"][mid]}
        colors = ([variant_row["color"]] if variant_row and variant_row["color"]
                  and variant_row["color"].strip().casefold() not in present_colors else [])
        image_specs = list(assets.get(f"master:{src['master_id']}", []))
        if variant_row:
            image_specs += assets.get(f"variant:{variant_row['old_id']}", [])
        roles = {r["image_type"] or "model" for r in children["model_images"][mid]}
        images = [dict(s) for s in image_specs if s["image_type"] not in roles]
        if any(r["is_primary"] for r in children["model_images"][mid]):
            for image in images:
                image["is_primary"] = False
        # An already populated record needs no provenance-only rewrite unless
        # an applicable missing field/child is actually being supplied.
        substantive = {k:v for k,v in new_details.items() if k != "old_erp_catalog_reconciliation"}
        old_substantive = {k:v for k,v in (existing_details or {}).items() if k != "old_erp_catalog_reconciliation"}
        if existing and substantive == old_substantive and not (sizes or colors or images):
            return
        entries.append({"identity": list(key), "target_id": mid,
                        "before": {"code": existing["code"], "name": existing["name"], "details_sha256": digest(existing_details),
                                   "sizes": digest(sorted(children["model_sizes"][mid], key=lambda r:r["id"])), "colors": digest(sorted(children["model_colors"][mid], key=lambda r:r["id"])),
                                   "images": digest(sorted(children["model_images"][mid], key=lambda r:r["id"]))} if existing else None,
                        "code": existing["code"] if existing else base.strip() + (f"-V-{key[1]}" if key[1] else ""),
                        "name": existing["name"] if existing else (g["product"] or g["name"] or base),
                        "details_json": new_details, "sizes": sizes, "colors": colors, "images": images})

    for variant in variants:
        key = normalize(variant["model_no"]), variant_number(variant["variant_no"])
        # Capture only the reviewed source masters; existing configured rows
        # outside this additive review are preserved.
        candidates = masters[key[0]]
        exact = [r for r in candidates if r["name"].strip() == variant["sewing_model_ref"].strip()]
        linked = exact if len(exact) == 1 else candidates if len(candidates) == 1 else []
        if not linked:
            if not current[key] or len(exact) > 1:
                issues.append({"identity": list(key), "reason": "source_master_unresolved"})
            continue
        record = by_id.get(str(linked[0]["old_model_id"]))
        if record:
            add(variant["model_no"], variant["variant_no"], source_record(record), variant)

    variant_bases = {normalize(r["model_no"]) for r in variants}
    for record in records:
        base = record["model_no"].strip()
        # Old master records named "PJ1062 V-2640" describe an existing variant.
        match = re.fullmatch(r"(.+?)[\s_-]+V[- ]*(\d+)", base, re.I)
        if match:
            base, variant = match.groups()
            if base.upper().endswith("V") and not current[(normalize(base), variant_number(variant))]:
                base = base[:-1]
            if current[(normalize(base), variant_number(variant))]:
                continue
            if any(variant_number(v["variant_no"]) == variant_number(variant) for v in variants):
                issues.append({"identity": [normalize(base), variant_number(variant)], "reason": "master_label_conflicts_with_variant_catalog"})
                continue
        else:
            variant = ""
            if normalize(base) in variant_bases or any(key[0] == normalize(base) for key in current):
                continue
            if not re.fullmatch(r"[A-Za-z]{1,2}[- ]?\d+", base):
                issues.append({"identity": [base, ""], "reason": "noncanonical_historical_master_label"})
                continue
        add(base, variant, source_record(record))
    return {"schema_version": 1, "source_key": SOURCE_KEY, "entries": entries, "issues": issues,
            "numbering": numbering, "summary": {"create": sum(e["target_id"] is None for e in entries),
            "update": sum(e["target_id"] is not None for e in entries), "sizes": sum(len(e["sizes"]) for e in entries),
            "images": sum(len(e["images"]) for e in entries)}}


def apply_plan(db, plan, media_root: Path, actor_id: int, *, dry_run=False):
    from app.core.config import settings
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(1297047632, hashtext('catalog-reconciliation'))"))
        for stream in ("model_numbering", "model_variant_numbering"):
            db.execute(text("SELECT pg_advisory_xact_lock(1297047632, hashtext(:stream))"), {"stream": stream})
        # Prevent a concurrent catalog create/import from racing identity checks.
        db.execute(text("LOCK TABLE models, model_sizes, model_colors, model_images IN SHARE ROW EXCLUSIVE MODE"))
    actor = db.get(User, actor_id)
    if not actor:
        raise ValueError("Audit actor not found")
    # Identity checks need only scalar metadata, not the large historical
    # operation/provenance documents on every model in production.
    existing = db.query(Model.id, Model.code, Model.catalog_scope,
                        Model.details_json["general"].label("general")).all()
    by_identity = defaultdict(list)
    by_code = {m.code: m.id for m in existing}
    for m in existing:
        if m.catalog_scope == "standard" and not m.code.startswith("LEGACY-"):
            by_identity[identity({"code": m.code, "details_json": {"general": m.general}})].append(m.id)
    target_dir = Path(settings.MODEL_FILES_DIR)
    targets = []
    plan_digest = digest(plan)
    for entry in plan["entries"]:
        key = tuple(entry["identity"])
        found = by_identity[key]
        mid = entry["target_id"]
        if not mid and entry["code"] in by_code:
            raise ValueError(f"Catalog code occupied: {entry['code']}")
        if found != ([mid] if mid else []):
            raise ValueError(f"Catalog identity changed: {key}")
        model = db.get(Model, mid) if mid else None
        if mid:
            before = entry["before"]
            if model.code != before["code"] or model.name != before["name"] or digest(model.details_json) != before["details_sha256"]:
                raise ValueError(f"Target changed since review: {mid}")
            for table, label, columns in (
                (ModelSize, "sizes", ("id", "model_id", "size", "measurement_json")),
                (ModelColor, "colors", ("id", "model_id", "color_name", "color_code")),
                (ModelImage, "images", ("id", "model_id", "file_url", "image_type", "is_primary")),
            ):
                rows = [{column: getattr(r, column) for column in columns} for r in db.query(table).filter_by(model_id=mid).all()]
                if digest(sorted(rows, key=lambda r:r["id"])) != before[label]:
                    raise ValueError(f"Target children changed: {mid}/{label}")
        for spec in entry["images"]:
            name = spec["file_name"]
            if Path(name).name != name or not re.fullmatch(r"catalog_parity_[0-9a-f]{64}\.(webp|png|jpg|gif)", name):
                raise ValueError("Unsafe media filename")
            if hashlib.sha256((media_root / name).read_bytes()).hexdigest() != spec["sha256"]:
                raise ValueError("Media integrity mismatch")
        if dry_run:
            targets.append({"id": mid, "identity": list(key)})
            continue
        if not mid:
            model = Model(code=entry["code"], name=entry["name"], catalog_scope="standard", status="draft", created_by=actor_id)
            db.add(model)
        model.details_json = deepcopy(entry["details_json"])
        db.flush()
        for size in entry["sizes"]:
            db.add(ModelSize(model_id=model.id, size=size))
        for color in entry["colors"]:
            db.add(ModelColor(model_id=model.id, color_name=color))
        for spec in entry["images"]:
            name = spec["file_name"]
            if Path(name).name != name or not re.fullmatch(r"catalog_parity_[0-9a-f]{64}\.(webp|png|jpg|gif)", name):
                raise ValueError("Unsafe media filename")
            source_file = media_root / name
            data = source_file.read_bytes()
            if hashlib.sha256(data).hexdigest() != spec["sha256"]:
                raise ValueError("Media integrity mismatch")
            destination = target_dir / name
            if not destination.exists():
                with destination.open("xb") as stream:
                    stream.write(data)
            elif hashlib.sha256(destination.read_bytes()).hexdigest() != spec["sha256"]:
                raise ValueError("Existing media differs")
            db.add(ModelImage(model_id=model.id, file_url="/storage/model-files/"+name, file_name=name,
                              content_type=spec["content_type"], image_type=spec["image_type"], is_primary=spec["is_primary"]))
        log_action(db, actor, "catalog_parity_create" if not mid else "catalog_parity_fill", "Model", model.id,
                   new_value={"source_key": SOURCE_KEY, "identity": list(key), "plan_sha256": plan_digest})
        targets.append({"id": model.id, "identity": list(key), "details_sha256": digest(model.details_json)})
    if dry_run:
        return targets
    for setting_key, floors in (("model_variant_numbering", plan["numbering"]["variant_last_assigned"]),
                               ("model_numbering", plan["numbering"]["models"])):
        row = db.query(SystemSetting).filter_by(key=setting_key).one_or_none()
        previous = row.value_json if row and isinstance(row.value_json, dict) else {}
        if setting_key == "model_variant_numbering":
            updated = {**previous, "last_assigned": max(int(previous.get("last_assigned") or 0), floors)}
        else:
            numbers = dict(previous.get("last_assigned") or {})
            for prefix, source in floors.items():
                numbers[prefix] = max(int(numbers.get(prefix) or 0), source["number"])
            updated = {**previous, "last_assigned": numbers}
        if row:
            row.value_json = updated
        else:
            row = SystemSetting(key=setting_key, value_json=updated)
            db.add(row)
        db.flush()
        log_action(db, actor, "catalog_numbering_calibrate", "SystemSetting", row.id,
                   old_value=previous, new_value=updated)
    db.flush()
    return targets


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--media", type=Path, required=True)
    parser.add_argument("--actor-id", type=int, default=1)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    raw = args.plan.read_bytes()
    if hashlib.sha256(raw).hexdigest() != args.sha256:
        raise ValueError("Reviewed plan hash mismatch")
    plan = json.loads(raw)
    from app.db.session import SessionLocal
    with SessionLocal() as db:
        if db.bind.dialect.name == "postgresql":
            if db.bind.url.host != "172.16.10.3" or db.execute(text("select version_num from alembic_version")).scalar_one() != "0133_storage_customers":
                raise ValueError("Unexpected production database")
        result = apply_plan(db, plan, args.media, args.actor_id, dry_run=not args.apply)
        if args.apply:
            db.commit()
        else:
            db.rollback()
        print(json.dumps({"applied": args.apply, "targets": result, "summary": plan["summary"]}))


if __name__ == "__main__":
    main()
