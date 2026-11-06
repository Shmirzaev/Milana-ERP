"""Read-only reporting; the top/bottom multiplier exists only in dashboard totals."""
import base64
from decimal import Decimal
from io import BytesIO
from itertools import islice

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font, PatternFill
from openpyxl.drawing.image import Image
from PIL import Image as PillowImage
from sqlalchemy.orm import load_only, selectinload

from app.schemas import Model, ModelImage, ProductionOrder
from app.models.label_images_service import _uploaded_file_data_uri
from app.models.model_family_images_service import family_images_for_models, model_family_image
from app.models.model_images_service import model_variant_picture_url
from app.models.production.passport_material_allocation_service import allocation_source_label


def _zero():
    return {"passports": 0, "fabric_kg": Decimal(0), "fabric_m": Decimal(0), "rolls": 0, "pieces": 0}


def build_dashboard(passports):
    total = _zero()
    days = {}
    for passport, materials, _model_code in passports:
        day = passport.date.date().isoformat()
        row = days.setdefault(day, _zero())
        row["passports"] += 1
        # The screen expands saved materials into individual passport rows.
        # Count their entered quantities, including historical passports whose
        # parent stores only the first row. Do not rewrite confirmed output.
        quantities = [material["pieces"] for material in materials if material.get("pieces") is not None]
        pieces = sum(quantities) if quantities else (passport.pieces or 0)
        row["pieces"] += pieces * (2 if passport.tepa_pass else 1)
        for material in materials:
            unit = "fabric_m" if material.get("meter_mode") else "fabric_kg"
            row[unit] += Decimal(str(material.get("actual_kg") or 0))
            row["rolls"] += material.get("rolls_count") or 0
    for row in days.values():
        for key in total:
            total[key] += row[key]

    def numbers(row):
        return {key: float(value) if isinstance(value, Decimal) else value for key, value in row.items()}

    return {"totals": numbers(total), "daily": [{"date": day, **numbers(row)} for day, row in sorted(days.items())]}


_HEADERS = {
    "en": ["Passport", "Date", "Order", "Model", "Variant", "Mold", "Size range", "Operator", "Print", "Tepa pass", "Pieces", "Notes",
           "Fabric", "Lot", "Unit", "Rolls", "Layer quantity", "Layers", "Planned quantity", "Actual usage", "Processed quantity", "Pieces",
           "Width (m)", "Lay length (m)", "Gramage (kg/m²)", "Waste %", "Binding per piece", "Other binding per piece", "Scrap", "Ribana per piece",
           "Binding total", "Other binding total", "Ribana total", "Per-piece consumption", "Actual per piece", "Gross per piece"],
    "ru": ["Паспорт", "Дата", "Заказ", "Модель", "Вариант", "Лекало", "Размеры", "Оператор", "Печать", "Tepa pass", "Количество изделий", "Примечание",
           "Ткань", "Партия", "Ед.", "Рулоны", "Расход на слой", "Слои", "Плановый расход", "Фактический расход", "Расчётный расход", "Количество изделий",
           "Ширина (м)", "Длина настила (м)", "Плотность (кг/м²)", "Отход %", "Бейка на изделие", "Другая бейка на изделие", "Брак", "Рибана на изделие",
           "Бейка всего", "Другая бейка всего", "Рибана всего", "Расход на изделие", "Факт на изделие", "Брутто на изделие"],
    "uz": ["Pasport", "Sana", "Buyurtma", "Model", "Variant", "Qolip", "O‘lchamlar", "Operator", "Pechat", "Tepa pass", "Ish soni", "Izoh",
           "Mato", "Partiya", "Birlik", "Rulonlar", "Bir qatlam sarfi", "Qatlamlar", "Rejadagi sarf", "Haqiqiy sarf", "Hisoblangan sarf", "Ish soni",
           "Eni (m)", "Nastil uzunligi (m)", "Grammaj (kg/m²)", "Chiqindi %", "Bir ishga beyka", "Bir ishga boshqa beyka", "Brak", "Bir ishga ribana",
           "Jami beyka", "Jami boshqa beyka", "Jami ribana", "Bir ishga sarf", "Bir ishga haqiqiy sarf", "Bir ishga brutto"],
}
_MATERIAL_KEYS = ("fabric_type", "lot_no", "unit", "rolls_count", "layer_weight_kg", "total_layers", "planned_kg", "actual_kg", "theoretical_kg", "pieces",
                  "fabric_width_m", "lay_length_m", "gramage", "waste_pct", "beka_per_piece_kg", "other_beka_per_piece_kg", "scrap_kg", "ribana_per_piece_kg",
                  "total_beka_kg", "other_beka_kg", "total_ribana_kg", "per_piece_weight_kg", "actual_kg_per_piece", "gross_kg_per_piece")
_PICTURE_HEADERS = {"en": ["Model picture", "Variant picture"],
                    "ru": ["Фото модели", "Фото варианта"],
                    "uz": ["Model rasmi", "Variant rasmi"]}


def _rows_with_pictures(db, passports):
    """Resolve selected upload bytes in batches, never fetch remote URLs."""
    iterator = iter(passports)
    cache = {}
    while chunk := list(islice(iterator, 200)):
        order_ids = {p.production_order_id for p, _, _ in chunk if p.production_order_id}
        order_models = dict(db.query(ProductionOrder.id, ProductionOrder.model_id).filter(
            ProductionOrder.id.in_(order_ids)).all()) if order_ids else {}
        missing = set(order_models.values()) - cache.keys()
        models = db.query(Model).options(
            load_only(Model.id, Model.code, Model.name, Model.details_json, Model.catalog_scope, Model.factory_code),
            selectinload(Model.images).load_only(ModelImage.id, ModelImage.model_id, ModelImage.file_url,
                ModelImage.file_name, ModelImage.content_type, ModelImage.image_type, ModelImage.is_primary),
        ).filter(Model.id.in_(missing)).all() if missing else []
        family_images_for_models(db, models)
        selections = {}
        for model in models:
            variant_url = model_variant_picture_url(model)
            selections[model.id] = (model_family_image(model),
                next((image for image in model.images if image.file_url == variant_url), None))
        image_ids = {image.id for pair in selections.values() for image in pair if image}
        binaries = dict(db.query(ModelImage.id, ModelImage.file_data).filter(
            ModelImage.id.in_(image_ids)).all()) if image_ids else {}
        for model_id, images in selections.items():
            cache[model_id] = tuple(_uploaded_file_data_uri(image.file_url, image.content_type, binaries.get(image.id))
                                    if image else None for image in images)
        for p, materials, code in chunk:
            model_picture, variant_picture = cache.get(order_models.get(p.production_order_id), (None, None))
            pictures = (model_picture or _uploaded_file_data_uri(p.image_ref), variant_picture)
            yield p, materials, code, *pictures


def export_passport_workbook(db, passports, lang="en"):
    return export_workbook(_rows_with_pictures(db, passports), lang)


def _picture(sheet, anchor, source):
    """Return literal fallback text or embed an uploaded image in OpenXML."""
    if not source or not source.startswith("data:image/"):
        return source
    try:
        raw = base64.b64decode(source.split(",", 1)[1], validate=True)
        with PillowImage.open(BytesIO(raw)) as original:
            original.thumbnail((480, 400))
            stream = BytesIO()
            original.convert("RGBA").save(stream, format="PNG")
        stream.seek(0)
        picture = Image(stream)
        ratio = min(120 / picture.width, 100 / picture.height, 1)
        picture.width *= ratio
        picture.height *= ratio
        sheet.add_image(picture, anchor)
    except (OSError, ValueError, IndexError):
        return "Image unavailable"
    return None


def _append(sheet, values, header=False):
    cells = []
    for value in values:
        cell = WriteOnlyCell(sheet, value=value)
        if isinstance(value, str):
            # All user-entered text stays literal, including strings starting '='.
            cell.data_type = "s"
        elif isinstance(value, (float, Decimal)):
            cell.number_format = "0.######"
        if header:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="475569")
        cells.append(cell)
    sheet.append(cells)


def export_workbook(passports, lang="en"):
    book = Workbook(write_only=True)
    names = {"en": ("Passports", "Materials"), "ru": ("Паспорта", "Материалы"), "uz": ("Pasportlar", "Matolar")}[lang]
    summary, detail = [book.create_sheet(name) for name in names]
    for sheet in (summary, detail):
        sheet.freeze_panes = "A2"
        for col in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            sheet.column_dimensions[col].width = 20
    for sheet, columns in ((summary, ("M", "N")), (detail, ("AG", "AH"))):
        for column in columns:
            sheet.column_dimensions[column].width = 19
    _append(summary, _HEADERS[lang][:12] + _PICTURE_HEADERS[lang], header=True)
    _append(detail, _HEADERS[lang][:8] + _HEADERS[lang][12:] + _PICTURE_HEADERS[lang], header=True)
    count = material_count = 0
    for entry in passports:
        p, materials, model_code = entry[:3]
        model_picture, variant_picture = entry[3:] if len(entry) > 3 else (None, None)
        identity = [p.passport_no, p.date.date().isoformat(), p.production_order.order_no if p.production_order else p.order_no,
                    model_code, p.variant, p.mold_no, p.size_range, p.operator.name if p.operator else p.operator_name_manual]
        # Excel preserves original quantities. Tepa pass never doubles an export.
        row = count + 2
        summary.row_dimensions[row].height = 80 if model_picture or variant_picture else 15
        pictures = [_picture(summary, f"M{row}", model_picture), _picture(summary, f"N{row}", variant_picture)]
        _append(summary, identity + [p.has_print, p.tepa_pass, p.pieces, p.notes] + pictures)
        count += 1
        for material in materials:
            material["unit"] = "m" if material.get("meter_mode") else "kg"
            if material.get("batch_allocations"):
                material["lot_no"] = allocation_source_label(material, material["unit"])
            material_identity = identity.copy()
            material_identity[6] = material.get("size_range") if material.get("size_range") is not None else p.size_range
            material_identity[7] = material.get("operator_name_manual") or identity[7]
            row = material_count + 2
            detail.row_dimensions[row].height = 80 if model_picture or variant_picture else 15
            pictures = [_picture(detail, f"AG{row}", model_picture), _picture(detail, f"AH{row}", variant_picture)]
            _append(detail, material_identity + [material.get(key) for key in _MATERIAL_KEYS] + pictures)
            material_count += 1
    summary.auto_filter.ref = f"A1:N{count + 1}"
    detail.auto_filter.ref = f"A1:AH{material_count + 1}"
    stream = BytesIO()
    book.save(stream)
    return stream.getvalue()
