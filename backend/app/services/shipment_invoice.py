"""Standalone printable shipment invoice; deliberately never writes finance data."""
from html import escape
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import re
from types import SimpleNamespace


def invoice_model_identity(model, source: dict | None = None) -> tuple[str | None, str | None]:
    if model is None:
        return None, None
    details = model.details_json if isinstance(model.details_json, dict) else {}
    general = details.get("general") if isinstance(details.get("general"), dict) else {}
    code = str(model.code or "")
    matched = re.fullmatch(r"(.*?)-(V-\d+|[^-]+)", code)
    source = source or {}
    hidden = bool(details.get("legacy_import")) or code.startswith("LEGACY-")
    source_model = (source.get("original_model_number") or source.get("model_number") or source.get("model_code")) if hidden else None
    source_variant = (source.get("original_article") or source.get("article") or source.get("variant_number") or source.get("variant")) if hidden else None
    model_no = str(general.get("model_no") or general.get("modelNo") or details.get("legacy_original_model_no") or
                   source_model or ("" if hidden else matched[1] if matched else code)).strip()
    variant_no = str(general.get("variant_no") or general.get("variantNo") or details.get("legacy_original_variant_no") or
                     source_variant or ("" if hidden else matched[2] if matched else "")).strip()
    if variant_no and model_no.endswith("-" + variant_no):
        model_no = model_no[:-(len(variant_no) + 1)]
    return model_no or None, variant_no or None


def build_invoice_rows(lines: list[dict], packages: list[dict]) -> list[dict]:
    """One row per package/model/price; shared pack and weight cells span splits."""
    result = []
    for package in packages:
        groups: dict[tuple, dict] = OrderedDict()
        for line in lines:
            if line.get("package_no") != package["package_no"]:
                continue
            parsed_model, parsed_variant = invoice_model_identity(SimpleNamespace(code=line.get("model_code"), details_json={}))
            key = (line.get("model_no") or parsed_model, line.get("variant_no") or parsed_variant,
                   line.get("description"), line.get("unit_price"))
            group = groups.setdefault(key, {"package_no": package["package_no"], "model_no": key[0],
                                             "variant_no": key[1], "description": key[2], "unit_price": key[3],
                                             "quantity": 0, "sizes": [], "amount": Decimal("0")})
            group["quantity"] += int(line["quantity"])
            group["sizes"].append({"size": line.get("size"), "color": line.get("color"), "quantity": line["quantity"]})
            if line.get("amount") is None:
                group["amount"] = None
            elif group["amount"] is not None:
                group["amount"] += Decimal(line["amount"])
        if not groups:
            groups[()] = {"package_no": package["package_no"], "model_no": None, "variant_no": None,
                          "description": None, "unit_price": None, "quantity": package.get("quantity", 0),
                          "sizes": [], "amount": None}
        for index, group in enumerate(groups.values()):
            group["amount"] = str(group["amount"].quantize(Decimal("0.01"))) if group["amount"] is not None else None
            group["package_rowspan"] = len(groups) if index == 0 else 0
            group["pack_count"] = 1 if index == 0 else 0
            group["weight_kg"] = package.get("weight_kg") if index == 0 else None
            result.append(group)
    return result


LABELS = {
    "en": {"title": "Commercial invoice", "posting": "Unposted to Finance until delivery.", "print": "Print", "order": "Sales order", "customer": "Customer",
           "date": "Shipped", "pack": "Package", "model": "Model / variant", "color": "Color", "size": "Size",
           "qty": "Pieces", "price": "Unit price", "amount": "Amount", "total": "Total", "packs": "Packages",
           "calculated": "Calculated amount", "adjustment": "Warehouse adjustment", "net": "Net prices. No tax calculation.",
           "reference": "Basic layout — reference document pending.",
           "historical": "Historical shipment: reconstructed from current records; original financial snapshot unavailable.",
           "missing": "Price unavailable", "signature": "Issued by / Received by"},
    "ru": {"title": "Коммерческий инвойс", "posting": "Не проведён в финансах до подтверждения доставки.", "print": "Печать", "order": "Заказ", "customer": "Клиент",
           "date": "Отгружено", "pack": "Упаковка", "model": "Модель / вариант", "color": "Цвет", "size": "Размер",
           "qty": "Штук", "price": "Цена", "amount": "Сумма", "total": "Итого", "packs": "Упаковок",
           "calculated": "Расчётная сумма", "adjustment": "Корректировка склада", "net": "Цены нетто. Налог не рассчитывается.",
           "reference": "Базовая форма — ожидается образец документа.",
           "historical": "Историческая отгрузка: данные восстановлены из текущих записей; исходный финансовый снимок отсутствует.",
           "missing": "Цена не указана", "signature": "Отпустил / Получил"},
    "uz": {"title": "Tijorat hisob-fakturasi", "posting": "Yetkazish tasdiqlanmaguncha Moliyaga o‘tkazilmagan.", "print": "Chop etish", "order": "Buyurtma", "customer": "Mijoz",
           "date": "Jo‘natilgan", "pack": "Qadoq", "model": "Model / variant", "color": "Rang", "size": "O‘lcham",
           "qty": "Dona", "price": "Narx", "amount": "Summa", "total": "Jami", "packs": "Qadoqlar",
           "calculated": "Hisoblangan summa", "adjustment": "Ombor tuzatishi", "net": "Sof narxlar. Soliq hisoblanmaydi.",
           "reference": "Asosiy shakl — hujjat namunasi kutilmoqda.",
           "historical": "Tarixiy jo‘natma: joriy yozuvlardan tiklangan; asl moliyaviy nusxa mavjud emas.",
           "missing": "Narx mavjud emas", "signature": "Topshirdi / Qabul qildi"},
}


def render_shipment_invoice(document: dict, language: str) -> str:
    lang = language if language in LABELS else "en"
    text = LABELS[lang]

    def value(raw):
        return escape(str(raw)) if raw is not None else ""

    def number(raw):
        if raw is None:
            return ""
        try:
            parsed = Decimal(str(raw))
            return format(parsed.quantize(Decimal("0.01")), "f") if parsed.is_finite() else ""
        except (InvalidOperation, ValueError):
            return ""

    def weight(raw):
        return "—" if raw is None else number(raw)

    def date(raw):
        if not raw:
            return ""
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone(timedelta(hours=5))).strftime("%d/%m/%Y %H:%M:%S")
        except ValueError:
            return value(raw)

    posting = text["posting"]
    if document.get("finance_posting_status") == "posted":
        posting = {"en": "Posted on delivery to ledger invoice", "ru": "Проведён при доставке в финансовый счёт",
                   "uz": "Yetkazishda moliyaviy hisobga o‘tkazilgan"}[lang] + ": " + value(document.get("ledger_invoice_no"))
    packages = document.get("package_details")
    if packages is None:
        packages = list({line["package_no"]: {"package_no": line["package_no"], "weight_kg": None}
                         for line in document.get("lines", [])}.values())
    invoice_rows = document.get("invoice_rows") or build_invoice_rows(document.get("lines", []), packages)
    body = []
    for index, row in enumerate(invoice_rows, 1):
        sizes = " : ".join(f'{value(item.get("size"))} ({int(item["quantity"])})' for item in row.get("sizes", []))
        colors = list(dict.fromkeys(item.get("color") for item in row.get("sizes", []) if item.get("color")))
        if len(colors) > 1:
            sizes = " : ".join(f'{value(item.get("color"))} / {value(item.get("size"))} ({int(item["quantity"])})'
                               for item in row.get("sizes", []))
        span = row["package_rowspan"]
        pack_cell = f'<td rowspan="{span}" class="numeric">{number(row["pack_count"])}</td>' if span else ""
        weight_cells = f'<td rowspan="{span}" class="numeric">{weight(row.get("weight_kg"))}</td>' * 2 if span else ""
        body.append(f'<tr><td>{number(index)}</td><td>{value(row.get("model_no"))}</td>'
                    f'<td>{value(row.get("variant_no"))}</td><td>{value(row.get("description"))}</td>'
                    f'<td class="sizes">{sizes}</td>{pack_cell}<td class="numeric">{number(row["quantity"])}</td>'
                    f'{weight_cells}<td class="numeric">{number(row.get("unit_price"))}</td><td class="numeric">{number(row.get("amount"))}</td></tr>')
    cautions = []
    if document.get("historical_reconstruction"):
        cautions.append(text["historical"])
    if document.get("invoice_layout_version") != 2:
        cautions.append({"en": "Historical snapshot has no original transport, model description or weight details; missing values are blank.",
                         "ru": "Исторический снимок не содержит исходные данные транспорта, описания модели или веса; пропуски оставлены пустыми.",
                         "uz": "Tarixiy nusxada asl transport, model tavsifi yoki vazn tafsilotlari yo‘q; qiymatlar bo‘sh qoldirildi."}[lang])
    if document.get("missing_weight_packages", len(packages) if document.get("invoice_layout_version") != 2 else 0):
        cautions.append({"en": "Some package weights are unknown. Total weight is not estimated.",
                         "ru": "Вес некоторых упаковок неизвестен. Общий вес не рассчитывается по предположению.",
                         "uz": "Ayrim qadoqlar vazni noma’lum. Jami vazn taxmin qilinmaydi."}[lang])
    if not document.get("pricing_complete", False):
        cautions.append(text["missing"])
    warning = "".join(f'<p class="warning">{value(caution)}</p>' for caution in cautions)
    adjustment = ""
    if document.get("adjustment_reason"):
        difference = None
        if document.get("amount") is not None and document.get("calculated_amount") is not None:
            difference = Decimal(document["amount"]) - Decimal(document["calculated_amount"])
        adjustment = (f'<p>{text["calculated"]}: {number(document.get("calculated_amount"))}; '
                      f'{text["adjustment"]}: {number(difference)}; {text["total"]}: {number(document.get("amount"))}</p>'
                      f'<p>{text["reason"] if "reason" in text else text["adjustment"]}: {value(document["adjustment_reason"])}</p>')
    transport = document.get("transport_details") or {}
    metadata = [
        ("Reys nomer", document.get("shipment_no"), "Haydovchi ismi", transport.get("driver_name")),
        ("Sana", date(document.get("shipped_at")), "Mashina malumoti", transport.get("vehicle_info")),
        ("Mijoz", document.get("customer"), "Kargo nomi", transport.get("cargo_name")),
        ("", "", "Haydovchi nomeri", transport.get("driver_phone")),
    ]
    metadata_html = "".join(f'<tr><th>{value(left)}</th><td class="left-value">{value(left_value)}</td>'
                            f'<th class="transport-label">{right}</th><td>{value(right_value)}</td></tr>'
                            for left, left_value, right, right_value in metadata)
    headers = ["№", "№ Model", "Variant", "Mahsulot tavsifi", "Olchov", "Paket", "Miqdor", "Kg", "Jami Kg", "Narh", "Jami"]
    columns = "".join(f'<col style="width:{width}%">' for width in [3.8, 9.6, 15.1, 17.1, 19.8, 5.8, 6.1, 5.6, 5.6, 4.9, 6.6])
    weights = weight(document.get("total_weight_kg"))
    return f'''<!doctype html><html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Ombor hisob-fakturasi {value(document["shipment_no"])}</title>
<style>
*{{box-sizing:border-box}}body{{font:700 9pt "Times New Roman",Times,serif;color:#000;background:#fff;margin:16px auto;max-width:190mm;padding:0}}
.controls{{margin:0 0 12px}}button{{font:inherit;padding:6px 12px;background:#fff;border:1px solid #000;cursor:pointer}}
table{{width:100%;border-collapse:collapse;table-layout:fixed}}td,th{{border:1px solid #000;padding:3px 2px;vertical-align:middle;text-align:center;overflow-wrap:anywhere;font-weight:700}}
.meta th{{text-align:left}}.meta .transport-label{{text-align:center}}.meta .left-value{{text-align:left}}.meta td{{font-size:10pt}}
.meta .brand{{font-size:18pt;text-align:left;padding:9px 2px 1px;height:15mm;vertical-align:bottom;border-bottom:0}}
.meta .invoice-title{{font-size:12pt;text-align:left;border-top:0;padding:0 2px 7px}}
.items{{font-size:8pt}}.items thead th{{background:#5b9bd5;font-size:10pt;border:2px solid #000;padding:7px 1px;overflow-wrap:normal;word-break:normal}}
.items thead th:nth-child(7),.items thead th:nth-child(10){{font-size:8pt;white-space:nowrap}}
.items tbody td{{border:2px solid #000}}.items .sizes{{font-size:8pt}}.numeric{{font-variant-numeric:tabular-nums}}
thead{{display:table-header-group}}tr{{break-inside:avoid}}.totals td{{border:2px solid #000;height:14mm;font-size:10pt}}
.totals .total-label{{background:#ffff00;font-size:16pt}}.totals .total-measure{{background:#538135}}
.accounting{{margin-top:8px;font-size:8pt;break-inside:avoid}}p{{margin:4px 0}}.warning{{border:1px solid #000;padding:4px}}
@page{{size:A4 portrait;margin:10mm}}@media print{{body{{margin:0;max-width:none;width:100%}}.controls{{display:none}}*{{print-color-adjust:exact;-webkit-print-color-adjust:exact}}}}
</style></head><body><div class="controls"><button onclick="window.print()">{text["print"]}</button></div>
<table class="meta"><colgroup><col style="width:13.4%"><col style="width:17%"><col style="width:20%"><col style="width:49.6%"></colgroup>
<tbody><tr><td class="brand" colspan="3">Milana Tex</td><td rowspan="2"></td></tr><tr><td class="invoice-title" colspan="3">Ombor hisob-fakturasi</td></tr>{metadata_html}</tbody></table>
<table class="items"><colgroup>{columns}</colgroup><thead><tr>{"".join(f"<th>{header}</th>" for header in headers)}</tr></thead>
<tbody>{"".join(body)}<tr class="totals"><td class="total-label" colspan="5">JAMI</td>
<td class="total-measure">{number(document["packages_count"])}</td><td class="total-measure">{number(document["quantity"])}</td>
<td class="total-measure">{weights}</td><td class="total-measure">{weights}</td><td colspan="2">{number(document.get("amount"))}</td></tr></tbody></table>
<div class="accounting">{adjustment}{warning}<p>{posting}</p><p>{text["net"]}</p></div></body></html>'''
