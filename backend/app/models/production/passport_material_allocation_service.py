"""One passport calculation can retain several exact physical inventory sources.

This service owns grouping rules and read projections. The surrounding passport
or Cutting operation keeps its transaction and all actual stock persistence.
"""
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.factory_scope_service import factory_for_department, selected_factory_code
from app.schemas import Bundle, CuttingPassport, CuttingRecord, Department, MaterialReservation, ProductionBatch, StockBatch, Warehouse
from app.libs.dto.production.cutting_material import PassportMaterial
from app.libs.enums.inventory import MaterialReservationStatus
from app.schemas.production.passport_material_persistence import replace_grouped_passport_materials


def material_quantity(source):
    def number(key):
        value = Decimal(str(source.get(key) or 0))
        if not value.is_finite() or value < 0:
            raise HTTPException(400, "Correct the material quantities in the cutting passport")
        return value
    layer, layers = number("layer_weight_kg"), number("total_layers")
    binding = number("beka_per_piece_kg") * number("pieces") if source.get("meter_mode") else Decimal(0)
    return round(layer * layers + number("scrap_kg") + binding if layer > 0 and layers > 0 else number("planned_kg"), 3)


def passport_unit(source, batch_unit):
    unit = "m" if source.get("meter_mode", False) else "kg"
    if str(batch_unit or "").strip().lower() != unit:
        raise HTTPException(400, f"Passport calculation unit ({unit}) must match the inventory batch unit ({batch_unit})")
    return str(batch_unit)


def material_source_ids(rows) -> list[int]:
    return [int(part["stock_batch_id"]) for row in rows for part in (row.get("batch_allocations") or [row])]


def normalize_grouped_materials(db: Session, order, rows: list[dict], current) -> list[dict]:
    ids = material_source_ids(rows)
    if len(ids) != len(set(ids)):
        raise HTTPException(400, "The same fabric batch cannot appear in more than one material entry")
    grouped_ids = sorted({part["stock_batch_id"] for row in rows for part in row.get("batch_allocations") or []})
    if not grouped_ids:
        return rows
    if order.source_type == "usluga":
        raise HTTPException(400, "Customer-supplied Usluga materials cannot group warehouse batches")
    # Lock the complete physical source set, including independent legacy rows,
    # before any later item/reservation locks. A grouped-only prefix can invert
    # the inventory consumption lock order when another row sits between IDs.
    batches = {batch.id: batch for batch in db.query(StockBatch).filter(StockBatch.id.in_(sorted(ids))).order_by(
        StockBatch.id).with_for_update(of=StockBatch).populate_existing().all()}
    departments = dict(db.query(Warehouse.id, Department.code).join(Department, Warehouse.department_id == Department.id).filter(
        Warehouse.id.in_({batch.warehouse_id for batch in batches.values()})).all())
    factory = selected_factory_code(current)
    normalized = []
    for source in rows:
        allocations = source.get("batch_allocations") or []
        if not allocations:
            normalized.append(source)
            continue
        sources = [batches.get(part["stock_batch_id"]) for part in allocations]
        if any(batch is None for batch in sources):
            raise HTTPException(404, "Grouped fabric inventory batch not found")
        primary = batches[source["stock_batch_id"]]
        color = str(primary.color or "").strip().casefold()
        unit = passport_unit(source, primary.unit)
        for batch in sources:
            if (batch.item_id != primary.item_id or str(batch.color or "").strip().casefold() != color
                    or str(batch.unit or "").strip().lower() != unit.strip().lower()):
                raise HTTPException(400, "Grouped batches must use the same fabric, color and unit")
            if not batch.item or batch.item.category not in {"fabric", "semi_finished"} or batch.archived_at:
                raise HTTPException(409, "Select active fabric inventory batches for grouping")
            batch_factory = factory_for_department(departments.get(batch.warehouse_id))
            if batch_factory and batch_factory != factory:
                raise HTTPException(403, "Grouped fabric batch is outside the selected factory")
        for name in ("width", "gsm"):
            known = {Decimal(str(getattr(batch, name))) for batch in sources if getattr(batch, name) is not None}
            if len(known) > 1:
                raise HTTPException(400, "Batches with different width or grammage need separate material entries")
        total = sum((Decimal(str(part["quantity"])) for part in allocations), Decimal(0))
        if total != material_quantity(source):
            raise HTTPException(400, "Batch allocation total must equal the calculated stock usage")
        canonical = [{"stock_batch_id": part["stock_batch_id"], "quantity": part["quantity"],
                      "batch_no": batches[part["stock_batch_id"]].batch_no or batches[part["stock_batch_id"]].internal_batch_no or str(part["stock_batch_id"])}
                     for part in allocations]
        canonical.sort(key=lambda part: part["stock_batch_id"] != source["stock_batch_id"])
        label = " + ".join(part["batch_no"] for part in canonical)
        normalized.append({**source, "batch_allocations": canonical, "lot_no": label if len(label) <= 64 else label[:61] + "..."})
    return normalized


def material_stock_metadata(db: Session, batch_ids: list[int], order_id: int) -> dict[int, dict]:
    """One bounded aggregate projection, never one reservation query per material.

    Availability includes this order's own reservations; other orders' outstanding
    reservations cannot be offered as free source capacity.
    """
    if not batch_ids:
        return {}
    reserved = db.query(MaterialReservation.stock_batch_id.label("batch_id"), func.sum(
        MaterialReservation.reserved_quantity - MaterialReservation.consumed_quantity - MaterialReservation.released_quantity
    ).label("quantity")).filter(MaterialReservation.stock_batch_id.in_(batch_ids),
        MaterialReservation.production_order_id != order_id,
        MaterialReservation.status.in_([MaterialReservationStatus.RESERVED, MaterialReservationStatus.PARTIALLY_CONSUMED])).group_by(MaterialReservation.stock_batch_id).subquery()
    return {batch.id: {"unit": batch.unit, "color": batch.color,
                      "available_quantity": max(0.0, float(batch.quantity or 0) - float(other_reserved or 0)),
                      "warehouse_name": warehouse_name}
            for batch, other_reserved, warehouse_name in db.query(StockBatch, reserved.c.quantity, Warehouse.name).outerjoin(
                reserved, reserved.c.batch_id == StockBatch.id).outerjoin(Warehouse, Warehouse.id == StockBatch.warehouse_id).filter(
                    StockBatch.id.in_(batch_ids)).all()}


def grouped_stock_sources(rows: list[dict]) -> list[dict]:
    """Expand physical checks/debits without duplicating the common calculation."""
    result = []
    for row in rows:
        for part in row.get("batch_allocations") or [row]:
            result.append({**row, "stock_batch_id": part["stock_batch_id"],
                           "allocated_quantity": part.get("quantity") if row.get("batch_allocations") else None})
    return result


def require_unchanged_used_allocations(old_rows: list[dict], new_rows: list[dict]) -> None:
    if not any(row.get("batch_allocations") for row in old_rows + new_rows):
        return
    # Calculation/source edits after consumption would rewrite its recorded basis.
    def values(rows):
        normalized = []
        for row in rows:
            value = PassportMaterial.model_validate(row).model_dump(exclude={"lot_no", "fabric_type"})
            value["batch_allocations"] = sorted([
                {"stock_batch_id": part["stock_batch_id"], "quantity": part["quantity"]}
                for part in value["batch_allocations"]
            ], key=lambda part: part["stock_batch_id"])
            normalized.append(value)
        return normalized
    if values(old_rows) != values(new_rows):
        raise HTTPException(409, "Grouped material allocations and calculations are locked after Cutting confirmation")


def allocated_usage_lines(source: dict, common: dict, total: Decimal, unit: str) -> list[dict]:
    """Allocate additive evidence once; garment pieces/rolls stay on the anchor.

    Batch usage retains group identity and its canonical source labels for sheet
    grouping. The final source receives the rounding remainder for exact totals.
    """
    parts = source["batch_allocations"]
    anchor = source["stock_batch_id"]
    result, assigned = [], {"waste_quantity": Decimal(0), "beika_kg": Decimal(0), "layer_material_kg": Decimal(0)}
    cumulative_quantity = Decimal(0)
    for index, part in enumerate(parts):
        quantity = Decimal(str(part["quantity"]))
        cumulative_quantity += quantity
        details = dict(common)
        for field in assigned:
            full = Decimal(str(common[field]))
            cumulative_share = full if index == len(parts) - 1 else round(full * cumulative_quantity / total, 3 if field == "waste_quantity" else 6)
            share = cumulative_share - assigned[field]
            details[field] = float(share)
            assigned[field] += share
        if part["stock_batch_id"] != anchor:
            details["cut_pieces"] = 0
            details["material_rolls_used"] = 0
        details["passport_material_group"] = {"anchor_stock_batch_id": anchor}
        if part["stock_batch_id"] == anchor:
            # Keep the durable source list once, rather than quadratic JSON
            # duplicated on every physical usage row.
            details["passport_material_group"]["batch_allocations"] = parts
        result.append({"stock_batch_id": part["stock_batch_id"], "quantity": float(quantity), "unit": unit, "details": details})
    # Primary source must come first: the legacy record's scalar summary uses it.
    return sorted(result, key=lambda row: row["stock_batch_id"] != anchor)


def grouped_material_computed_fields(source: dict, computed: dict) -> dict:
    if not source.get("batch_allocations"):
        return computed
    actual = float(material_quantity(source))
    return {**computed, "actual_kg": actual,
            "actual_kg_per_piece": round(actual / source["pieces"], 6) if source.get("pieces") else None}


def passport_primary_computed_fields(passport, computed: dict) -> dict:
    rows = passport.materials or []
    return grouped_material_computed_fields(rows[0], computed) if rows else computed


def material_sheet_entries(usages) -> list[dict]:
    """Present one group, retaining all lot labels and separate persisted debits."""
    usages = list(usages)
    full_groups = {(row.details or {})["passport_material_group"]["anchor_stock_batch_id"]:
                   (row.details or {})["passport_material_group"] for row in usages
                   if ((row.details or {}).get("passport_material_group") or {}).get("batch_allocations")}
    stocks = {row.stock_batch_id: row.stock_batch for row in usages}
    source_details = {row.stock_batch_id: row.details or {} for row in usages}
    entries, grouped = [], {}
    for usage in usages:
        details = usage.details
        if details is None:
            continue
        group = details.get("passport_material_group")
        key = group.get("anchor_stock_batch_id") if isinstance(group, dict) else None
        if key is None:
            entries.append({"stock": usage.stock_batch, "lot_no": usage.stock_batch.batch_no if usage.stock_batch else "",
                            "quantity": usage.quantity, "unit": usage.unit, "details": details})
            continue
        if key not in grouped:
            full = full_groups.get(key, group)
            entry = {"stock": stocks.get(key) or usage.stock_batch, "lot_no": allocation_source_label(full, usage.unit),
                     "quantity": Decimal(0), "unit": usage.unit, "details": {**source_details.get(key, details)}}
            for field in ("layer_material_kg", "beika_kg", "material_rolls_used", "cut_pieces", "waste_quantity"):
                entry["details"][field] = Decimal(0)
            entries.append(entry)
            grouped[key] = entry
        entry = grouped[key]
        entry["quantity"] += Decimal(str(usage.quantity))
        for field in ("layer_material_kg", "beika_kg", "material_rolls_used", "cut_pieces", "waste_quantity"):
            entry["details"][field] += Decimal(str(details.get(field) or 0))
    return entries


def allocation_source_label(source: dict, unit: str) -> str:
    parts = source.get("batch_allocations") or []
    if not parts:
        return source.get("lot_no") or ""
    return " + ".join(f"{part.get('batch_no') or part['stock_batch_id']} ({format(Decimal(str(part['quantity'])).normalize(), 'f')} {unit})" for part in parts)


def replace_grouped_passport_source(db: Session, order, passport, old_batch_id: int, new_batch, current) -> bool:
    original = passport.materials or []
    if not any(part["stock_batch_id"] == old_batch_id for row in original for part in row.get("batch_allocations") or []):
        return False
    changed = []
    for row in original:
        allocations = row.get("batch_allocations") or []
        if not any(part["stock_batch_id"] == old_batch_id for part in allocations):
            changed.append(row)
            continue
        changed.append({**row,
                        "stock_batch_id": new_batch.id if row["stock_batch_id"] == old_batch_id else row["stock_batch_id"],
                        "batch_allocations": [{**part, "stock_batch_id": new_batch.id} if part["stock_batch_id"] == old_batch_id else part for part in allocations]})
    rows = normalize_grouped_materials(db, order, changed, current)
    replace_grouped_passport_materials(passport, rows,
        primary_changed=bool(original and any(part["stock_batch_id"] == old_batch_id for part in original[0].get("batch_allocations") or [])))
    return True


def require_grouped_cutting_notes_only(record, changed_fields: set[str]) -> None:
    if changed_fields - {"notes"} and any((row.details or {}).get("passport_material_group") for row in record.materials):
        raise HTTPException(409, "Grouped material calculations are locked after Cutting confirmation; only notes can be edited")


def primary_material_details(materials: list[dict]) -> dict:
    first = materials[0]["details"]
    group = first.get("passport_material_group")
    if not group:
        return first
    common = dict(first)
    related = [row["details"] for row in materials if (row["details"].get("passport_material_group") or {}).get("anchor_stock_batch_id") == group["anchor_stock_batch_id"]]
    for field in ("layer_material_kg", "beika_kg", "material_rolls_used", "cut_pieces", "waste_quantity"):
        common[field] = float(sum((Decimal(str(row.get(field) or 0)) for row in related), Decimal(0)))
    return common


def require_grouped_passport_submission(db: Session, batch_id: int | None, passport_id: int | None, use_passport_materials: bool) -> None:
    batch = db.get(ProductionBatch, batch_id) if batch_id else None
    linked_id = batch.cutting_passport_id if batch else None
    for candidate in {linked_id, passport_id} - {None}:
        # The caller already holds this order's PO/WO locks; passport mutations
        # use that same interlock. Reuse hydrated rows for independent Nastils.
        passport = db.get(CuttingPassport, candidate)
        if passport and any(row.get("batch_allocations") for row in passport.materials or []):
            if candidate != passport_id or not use_passport_materials:
                raise HTTPException(409, "Confirm this Nastil using its saved grouped passport material allocations")


def grouped_passport_has_execution(db: Session, passport, batch_id: int | None) -> bool:
    if not batch_id or not any(row.get("batch_allocations") for row in passport.materials or []):
        return False
    return bool(db.query(CuttingRecord.id).filter_by(production_batch_id=batch_id).first()
                or db.query(Bundle.id).filter_by(production_batch_id=batch_id).first())
