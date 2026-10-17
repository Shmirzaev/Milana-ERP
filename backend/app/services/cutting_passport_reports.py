"""Read-only reporting; the top/bottom multiplier exists only in dashboard totals."""
from decimal import Decimal
from io import BytesIO

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font, PatternFill


def _zero():
    return {"passports": 0, "fabric_kg": Decimal(0), "fabric_m": Decimal(0), "rolls": 0, "pieces": 0}


def build_dashboard(passports):
    total = _zero()
    days = {}
    for passport, materials in passports:
        day = passport.date.date().isoformat()
        row = days.setdefault(day, _zero())
        row["passports"] += 1
        # Multiple fabrics describe the same garment output, not additional pieces.
        row["pieces"] += (passport.pieces or 0) * (2 if passport.tepa_pass else 1)
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
    _append(summary, _HEADERS[lang][:12], header=True)
    _append(detail, _HEADERS[lang][:8] + _HEADERS[lang][12:], header=True)
    count = material_count = 0
    for p, materials in passports:
        identity = [p.passport_no, p.date.date().isoformat(), p.production_order.order_no if p.production_order else p.order_no,
                    p.model_code, p.variant, p.mold_no, p.size_range, p.operator.name if p.operator else p.operator_name_manual]
        # Excel preserves original quantities. Tepa pass never doubles an export.
        _append(summary, identity + [p.has_print, p.tepa_pass, p.pieces, p.notes])
        count += 1
        for material in materials:
            material["unit"] = "m" if material.get("meter_mode") else "kg"
            material_identity = identity.copy()
            material_identity[7] = material.get("operator_name_manual") or identity[7]
            _append(detail, material_identity + [material.get(key) for key in _MATERIAL_KEYS])
            material_count += 1
    summary.auto_filter.ref = f"A1:L{count + 1}"
    detail.auto_filter.ref = f"A1:AF{material_count + 1}"
    stream = BytesIO()
    book.save(stream)
    return stream.getvalue()
