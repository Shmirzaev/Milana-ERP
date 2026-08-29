from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import user_permissions
from app.models import CuttingPassport, Notification, User
from app.models.catalog import Model
from app.models.price_calculation import PriceCalculationRequest
from app.services.audit import log_action
from app.services.model_images import model_preview_image_url, model_variant_picture_url


FIXED_PACKAGING_COST = Decimal("0.1")
PURCHASING_PERMISSION = "price_calculation.purchasing"
ACCESSORIES_PERMISSION = "price_calculation.accessories"
CUTTING_PERMISSION = "price_calculation.cutting"


def _normalized(value: object) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def is_price_purchaser(user: User) -> bool:
    granted = user_permissions(user)
    if "*" in granted or PURCHASING_PERMISSION in granted:
        return True
    name = _normalized(user.name)
    email_local = _normalized(user.email).split("@", 1)[0]
    return name == "abbosbek" or name.startswith("abbosbek ") or email_local == "abbosbek"


def is_accessory_pricing_user(user: User) -> bool:
    granted = user_permissions(user)
    if "*" in granted or ACCESSORIES_PERMISSION in granted:
        return True
    department_code = _normalized(user.department.code if user.department else "").upper()
    return department_code == "STR" and "storage.items" in granted


def is_finance_pricing_user(user: User) -> bool:
    granted = user_permissions(user)
    return "*" in granted or "finance.view" in granted


def is_cutting_pricing_user(user: User) -> bool:
    granted = user_permissions(user)
    return bool(
        "*" in granted
        or "admin.super" in granted
        or CUTTING_PERMISSION in granted
        or {"cutting.records", "cutting.bundles"}.intersection(granted)
    )


def is_sales_pricing_user(user: User) -> bool:
    granted = user_permissions(user)
    return "*" in granted or "sales.orders" in granted


def can_view_price_requests(user: User) -> bool:
    return (
        is_sales_pricing_user(user)
        or is_finance_pricing_user(user)
        or is_cutting_pricing_user(user)
        or is_price_purchaser(user)
        or is_accessory_pricing_user(user)
    )


def _decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _positive(value: object) -> bool:
    parsed = _decimal(value)
    return parsed is not None and parsed > 0


def _money(value: Decimal | None, places: str = "0.0001") -> float | None:
    if value is None:
        return None
    return float(value.quantize(Decimal(places), rounding=ROUND_HALF_UP))


def _model_parts(model: Model) -> tuple[str, str]:
    general = (model.details_json or {}).get("general") if isinstance(model.details_json, dict) else {}
    general = general if isinstance(general, dict) else {}
    code = str(model.code or "").strip()
    left, separator, right = code.rpartition("-")
    model_no = str(general.get("model_no") or general.get("modelNo") or (left if separator else code)).strip()
    variant_no = str(general.get("variant_no") or general.get("variantNo") or (right if separator else "")).strip()
    return model_no, variant_no


def _size_count_from_range(value: str | None) -> int:
    text = str(value or "").strip()
    if not text:
        return 0
    if "," in text:
        return len({part.strip() for part in text.split(",") if part.strip()})
    if "-" not in text:
        return 1
    start_text, end_text = [part.strip() for part in text.split("-", 1)]
    try:
        start = float(start_text)
        end = float(end_text)
    except ValueError:
        return 1
    if start >= end:
        return 1
    step = 2 if start.is_integer() and end.is_integer() and end - start >= 2 else 1
    return int((end - start) // step) + 1


def _stage_status(required_values: list[bool]) -> str:
    completed = sum(1 for value in required_values if value)
    if completed == 0:
        return "new"
    if completed == len(required_values):
        return "complete"
    return "in_progress"


def cutting_status(request: PriceCalculationRequest) -> str:
    return _stage_status([
        bool(str(request.kroy_no or "").strip()),
        _positive(request.fabric_width_m),
        _positive(request.lay_length_m),
        bool(request.size_count and request.size_count > 0),
        _positive(request.gramage),
        request.binding_kg_per_piece is not None,
    ])


def purchasing_status(request: PriceCalculationRequest) -> str:
    return _stage_status([
        _positive(request.fabric_price),
        _positive(request.sewing_cost),
    ])


def accessories_status(request: PriceCalculationRequest) -> str:
    rows = request.accessories_json if isinstance(request.accessories_json, list) else []
    rows = [row for row in rows if isinstance(row, dict) and (str(row.get("name") or "").strip() or row.get("price") is not None)]
    if not rows:
        return "new"
    if all(str(row.get("name") or "").strip() and _positive(row.get("price")) for row in rows):
        return "complete"
    return "in_progress"


def overall_status(request: PriceCalculationRequest) -> str:
    cutting = cutting_status(request)
    purchasing = purchasing_status(request)
    accessories = accessories_status(request)
    selling_complete = _positive(request.selling_price)
    if cutting == "new" and purchasing == "new" and accessories == "new" and not selling_complete:
        return "new"
    if cutting == "complete" and purchasing == "complete" and accessories == "complete" and selling_complete:
        return "complete"
    return "in_progress"


def _calculation(request: PriceCalculationRequest) -> dict:
    ready = cutting_status(request) == "complete" and purchasing_status(request) == "complete" and accessories_status(request) == "complete"
    if not ready:
        return {
            "fabric_consumption": None,
            "consumption_cost": None,
            "binding_price": None,
            "cost_price": None,
            "difference": None,
        }
    width = _decimal(request.fabric_width_m) or Decimal(0)
    length = _decimal(request.lay_length_m) or Decimal(0)
    gramage = _decimal(request.gramage) or Decimal(0)
    size_count = Decimal(request.size_count or 0)
    fabric_price = _decimal(request.fabric_price) or Decimal(0)
    binding = _decimal(request.binding_kg_per_piece) or Decimal(0)
    sewing = _decimal(request.sewing_cost) or Decimal(0)
    consumption = width * length * gramage / size_count
    consumption_cost = consumption * fabric_price
    binding_price = binding * fabric_price
    accessory_total = sum(
        (_decimal(row.get("price")) or Decimal(0))
        for row in (request.accessories_json or [])
        if isinstance(row, dict)
    )
    cost_price = consumption_cost + binding_price + sewing + FIXED_PACKAGING_COST + accessory_total
    selling = _decimal(request.selling_price)
    return {
        "fabric_consumption": _money(consumption, "0.000001"),
        "consumption_cost": _money(consumption_cost),
        "binding_price": _money(binding_price),
        "cost_price": _money(cost_price),
        "difference": _money(selling - cost_price) if selling is not None else None,
    }


def serialize_price_request(request: PriceCalculationRequest) -> dict:
    model = request.model
    model_no, variant_no = _model_parts(model)
    sizes = list(dict.fromkeys(str(row.size or "").strip() for row in (model.sizes or []) if str(row.size or "").strip()))
    passport = request.cutting_passport
    accessories = [
        {"name": str(row.get("name") or "").strip() or None, "price": float(row["price"]) if row.get("price") is not None else None}
        for row in (request.accessories_json or [])
        if isinstance(row, dict)
    ]
    payload = {
        "id": request.id,
        "model_id": request.model_id,
        "model_no": model_no,
        "variant_no": variant_no,
        "model_name": model.name,
        "model_category": model.category or model.product_type,
        "model_sizes": sizes,
        "model_image_url": model_preview_image_url(model),
        "variant_image_url": model_variant_picture_url(model),
        "kroy_no": request.kroy_no,
        "cutting_passport_id": request.cutting_passport_id,
        "date": passport.date if passport else None,
        "fabric_width_m": float(request.fabric_width_m) if request.fabric_width_m is not None else None,
        "lay_length_m": float(request.lay_length_m) if request.lay_length_m is not None else None,
        "size_count": request.size_count,
        "gramage": float(request.gramage) if request.gramage is not None else None,
        "binding_kg_per_piece": float(request.binding_kg_per_piece) if request.binding_kg_per_piece is not None else None,
        "fabric_price": float(request.fabric_price) if request.fabric_price is not None else None,
        "sewing_cost": float(request.sewing_cost) if request.sewing_cost is not None else None,
        "packaging_cost": float(FIXED_PACKAGING_COST),
        "accessories": accessories,
        "cost_price_uzs": float(request.cost_price_uzs) if request.cost_price_uzs is not None else None,
        "selling_price": float(request.selling_price) if request.selling_price is not None else None,
        "profit_percentage": float(request.profit_percentage) if request.profit_percentage is not None else None,
        "exchange_rate": float(request.exchange_rate) if request.exchange_rate is not None else None,
        "purchasing_status": purchasing_status(request),
        "cutting_status": cutting_status(request),
        "accessories_status": accessories_status(request),
        "overall_status": overall_status(request),
        "created_at": request.created_at,
        "updated_at": request.updated_at,
    }
    payload.update(_calculation(request))
    return payload


def _passport_for_kroy(db: Session, request: PriceCalculationRequest, kroy_no: str) -> CuttingPassport | None:
    passport = (
        db.query(CuttingPassport)
        .filter(func.lower(CuttingPassport.passport_no) == kroy_no.casefold())
        .order_by(CuttingPassport.date.desc(), CuttingPassport.id.desc())
        .first()
    )
    if not passport:
        return None
    linked_order = passport.production_order
    if linked_order and linked_order.model_id and int(linked_order.model_id) != int(request.model_id):
        raise HTTPException(409, "Kroy number belongs to a different model variant")
    if not linked_order and str(passport.model_code or "").strip() and _normalized(passport.model_code) != _normalized(request.model.code):
        raise HTTPException(409, "Kroy number belongs to a different model variant")
    return passport


def create_price_request(db: Session, model_id: int, current: User) -> PriceCalculationRequest:
    model = db.get(Model, model_id)
    if not model:
        raise HTTPException(404, "Model not found")
    details = model.details_json if isinstance(model.details_json, dict) else {}
    costing = details.get("costing") if isinstance(details.get("costing"), dict) else {}
    margin = _decimal(costing.get("target_margin_pct"))
    request = PriceCalculationRequest(
        model_id=model.id,
        created_by_id=current.id,
        profit_percentage=margin,
        accessories_json=[],
    )
    db.add(request)
    db.flush()
    log_action(
        db,
        current,
        "create",
        "PriceCalculationRequest",
        request.id,
        new_value={"model_id": model.id},
    )
    _notify_new_request(db, request)
    return request


def update_cutting_details(db: Session, request: PriceCalculationRequest, data: dict, current: User) -> None:
    before = cutting_status(request)
    kroy_no = str(data.get("kroy_no") or "").strip()
    passport = _passport_for_kroy(db, request, kroy_no)
    request.kroy_no = kroy_no
    request.cutting_passport_id = passport.id if passport else None

    passport_binding = None
    if passport and (passport.beka_per_piece_kg is not None or passport.other_beka_per_piece_kg is not None):
        passport_binding = (
            (_decimal(passport.beka_per_piece_kg) or Decimal(0))
            + (_decimal(passport.other_beka_per_piece_kg) or Decimal(0))
        )
    request.fabric_width_m = passport.fabric_width_m if passport and passport.fabric_width_m is not None else data.get("fabric_width_m")
    request.lay_length_m = passport.lay_length_m if passport and passport.lay_length_m is not None else data.get("lay_length_m")
    passport_size_count = _size_count_from_range(passport.size_range) if passport else 0
    request.size_count = passport_size_count or data.get("size_count")
    request.gramage = passport.gramage if passport and passport.gramage is not None else data.get("gramage")
    request.binding_kg_per_piece = passport_binding if passport_binding is not None else data.get("binding_kg_per_piece")
    db.flush()
    after = cutting_status(request)
    log_action(
        db,
        current,
        "update_cutting_price_details",
        "PriceCalculationRequest",
        request.id,
        new_value={
            "kroy_no": request.kroy_no,
            "cutting_passport_id": request.cutting_passport_id,
            "fabric_width_m": data.get("fabric_width_m"),
            "lay_length_m": data.get("lay_length_m"),
            "size_count": data.get("size_count"),
            "gramage": data.get("gramage"),
            "binding_kg_per_piece": data.get("binding_kg_per_piece"),
        },
    )
    if before != "complete" and after == "complete":
        _notify_finance(db, request, "Cutting details completed")


def update_purchasing_details(db: Session, request: PriceCalculationRequest, data: dict, current: User) -> None:
    before = purchasing_status(request)
    request.fabric_price = data.get("fabric_price")
    request.sewing_cost = data.get("sewing_cost")
    request.purchasing_updated_by_id = current.id
    db.flush()
    after = purchasing_status(request)
    log_action(db, current, "update_purchasing_costs", "PriceCalculationRequest", request.id, new_value={"fabric_price": data.get("fabric_price"), "sewing_cost": data.get("sewing_cost")})
    if before != "complete" and after == "complete":
        _notify_finance(db, request, "Purchasing costs completed")


def update_accessories(db: Session, request: PriceCalculationRequest, rows: list[dict], current: User) -> None:
    before = accessories_status(request)
    request.accessories_json = [
        {"name": str(row.get("name") or "").strip() or None, "price": row.get("price")}
        for row in rows
        if str(row.get("name") or "").strip() or row.get("price") is not None
    ][:4]
    request.accessories_updated_by_id = current.id
    db.flush()
    after = accessories_status(request)
    log_action(db, current, "update_accessory_costs", "PriceCalculationRequest", request.id, new_value={"accessories": request.accessories_json})
    if before != "complete" and after == "complete":
        _notify_finance(db, request, "Accessory costs completed")


def _notify_new_request(db: Session, request: PriceCalculationRequest) -> None:
    recipients = [
        user for user in db.query(User).filter(User.is_active.is_(True)).all()
        if is_finance_pricing_user(user) or is_cutting_pricing_user(user) or is_price_purchaser(user) or is_accessory_pricing_user(user)
    ]
    seen: set[int] = set()
    for recipient in recipients:
        if recipient.id in seen or "*" in user_permissions(recipient):
            continue
        seen.add(recipient.id)
        if is_finance_pricing_user(recipient):
            link = "/finance/price-calculation"
        elif is_cutting_pricing_user(recipient):
            link = "/cutting/price-calculation"
        elif is_price_purchaser(recipient):
            link = "/purchasing/price-calculation"
        else:
            link = "/inventory/accessory-pricing"
        db.add(Notification(user_id=recipient.id, title="New price calculation request", message=f"Model {request.model.code} needs cost information.", link=link))


def _notify_finance(db: Session, request: PriceCalculationRequest, title: str) -> None:
    for recipient in db.query(User).filter(User.is_active.is_(True)).all():
        if not is_finance_pricing_user(recipient) or "*" in user_permissions(recipient):
            continue
        db.add(Notification(user_id=recipient.id, title=title, message=f"Model {request.model.code} price request was updated.", link="/finance/price-calculation"))
