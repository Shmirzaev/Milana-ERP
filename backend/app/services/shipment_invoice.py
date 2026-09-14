"""Standalone printable shipment invoice; deliberately never writes finance data."""
from base64 import b64encode
from functools import lru_cache
from pathlib import Path
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
    "en": {"title": "Warehouse invoice", "posting": "Unposted to Finance until delivery.", "print": "Print", "order": "Sales order", "customer": "Customer",
           "date": "Shipped", "pack": "Package", "model": "Model / variant", "color": "Color", "size": "Size",
           "qty": "Pieces", "price": "Unit price", "amount": "Amount", "total": "Total", "packs": "Packages",
           "calculated": "Calculated amount", "adjustment": "Warehouse adjustment", "net": "Net prices. No tax calculation.",
           "shipment": "Shipment no.", "driver": "Driver", "vehicle": "Vehicle", "carrier": "Carrier", "phone": "Driver phone",
           "modelNo": "Model", "variant": "Variant", "description": "Description", "weight": "Kg / pack", "totalWeight": "Total kg",
           "issued": "Issued by", "received": "Received by", "ledger": "Ledger invoice",
           "historical": "Historical shipment: reconstructed from current records; original financial snapshot unavailable.",
           "missing": "Price unavailable", "signature": "Issued by / Received by"},
    "ru": {"title": "Складская накладная", "posting": "Не проведён в финансах до подтверждения доставки.", "print": "Печать", "order": "Заказ", "customer": "Клиент",
           "date": "Отгружено", "pack": "Упаковка", "model": "Модель / вариант", "color": "Цвет", "size": "Размер",
           "qty": "Штук", "price": "Цена", "amount": "Сумма", "total": "Итого", "packs": "Упаковок",
           "calculated": "Расчётная сумма", "adjustment": "Корректировка склада", "net": "Цены нетто. Налог не рассчитывается.",
           "shipment": "№ отгрузки", "driver": "Водитель", "vehicle": "Автомобиль", "carrier": "Перевозчик", "phone": "Телефон водителя",
           "modelNo": "Модель", "variant": "Вариант", "description": "Описание", "weight": "Кг / уп.", "totalWeight": "Всего кг",
           "issued": "Отпустил", "received": "Получил", "ledger": "Финансовый счёт",
           "historical": "Историческая отгрузка: данные восстановлены из текущих записей; исходный финансовый снимок отсутствует.",
           "missing": "Цена не указана", "signature": "Отпустил / Получил"},
    "uz": {"title": "Ombor hisob-fakturasi", "posting": "Yetkazish tasdiqlanmaguncha Moliyaga o‘tkazilmagan.", "print": "Chop etish", "order": "Buyurtma", "customer": "Mijoz",
           "date": "Jo‘natilgan", "pack": "Qadoq", "model": "Model / variant", "color": "Rang", "size": "O‘lcham",
           "qty": "Dona", "price": "Narx", "amount": "Summa", "total": "Jami", "packs": "Qadoqlar",
           "calculated": "Hisoblangan summa", "adjustment": "Ombor tuzatishi", "net": "Sof narxlar. Soliq hisoblanmaydi.",
           "shipment": "Reys raqami", "driver": "Haydovchi", "vehicle": "Avtomobil", "carrier": "Kargo nomi", "phone": "Haydovchi telefoni",
           "modelNo": "Model", "variant": "Variant", "description": "Mahsulot tavsifi", "weight": "Kg / qadoq", "totalWeight": "Jami kg",
           "issued": "Topshirdi", "received": "Qabul qildi", "ledger": "Moliyaviy hisob",
           "historical": "Tarixiy jo‘natma: joriy yozuvlardan tiklangan; asl moliyaviy nusxa mavjud emas.",
           "missing": "Narx mavjud emas", "signature": "Topshirdi / Qabul qildi"},
}


@lru_cache(maxsize=1)
def invoice_logo_uri() -> str:
    """Embed the supplied vector artwork so print pages need no external assets."""
    artwork = Path(__file__).resolve().parents[1] / "assets" / "milana-premium-logo.svg"
    return "data:image/svg+xml;base64," + b64encode(artwork.read_bytes()).decode("ascii")


def render_shipment_invoice(document: dict, language: str) -> str:
    lang = language if language in LABELS else "en"
    text = LABELS[lang]

    def value(raw):
        return escape(str(raw)) if raw is not None else ""

    def number(raw, decimals=2):
        if raw is None:
            return ""
        try:
            parsed = Decimal(str(raw))
            return format(parsed, f",.{decimals}f").replace(",", "\u00a0") if parsed.is_finite() else ""
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
        posting = text["ledger"] + ": " + value(document.get("ledger_invoice_no"))
    packages = document.get("package_details")
    if packages is None:
        packages = list({line["package_no"]: {"package_no": line["package_no"], "weight_kg": None}
                         for line in document.get("lines", [])}.values())
    invoice_rows = document.get("invoice_rows") or build_invoice_rows(document.get("lines", []), packages)
    body = []
    for index, row in enumerate(invoice_rows, 1):
        sizes = "".join(f'<span class="size-label">{value(item.get("size"))} ({int(item["quantity"])})</span>' for item in row.get("sizes", []))
        colors = list(dict.fromkeys(item.get("color") for item in row.get("sizes", []) if item.get("color")))
        if len(colors) > 1:
            sizes = "".join(f'<span class="size-label multicolor">{value(item.get("color"))} / {value(item.get("size"))} ({int(item["quantity"])})</span>'
                               for item in row.get("sizes", []))
        span = row["package_rowspan"]
        pack_cell = f'<td rowspan="{span}" class="numeric">{number(row["pack_count"], 0)}</td>' if span else ""
        weight_cells = f'<td rowspan="{span}" class="numeric">{weight(row.get("weight_kg"))}</td>' * 2 if span else ""
        body.append(f'<tr><td>{index}</td><td>{value(row.get("model_no"))}</td>'
                    f'<td>{value(row.get("variant_no"))}</td><td class="description">{value(row.get("description"))}</td>'
                    f'<td class="sizes">{sizes}</td>{pack_cell}<td class="numeric">{number(row["quantity"], 0)}</td>'
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
        (text["shipment"], document.get("shipment_no"), text["driver"], transport.get("driver_name")),
        (text["date"], date(document.get("shipped_at")), text["vehicle"], transport.get("vehicle_info")),
        (text["customer"], document.get("customer"), text["carrier"], transport.get("cargo_name")),
        (text["order"], document.get("sales_order_no"), text["phone"], transport.get("driver_phone")),
    ]
    metadata_html = "".join(f'<tr><th>{value(left)}</th><td>{value(left_value) or "—"}</td>'
                            f'<th>{value(right)}</th><td>{value(right_value) or "—"}</td></tr>'
                            for left, left_value, right, right_value in metadata)
    headers = ["№", text["modelNo"], text["variant"], text["description"], text["size"], {"en": "Packs", "ru": "Упак.", "uz": "Qadoq"}[lang],
               text["qty"], text["weight"], text["totalWeight"], text["price"], text["amount"]]
    columns = "".join(f'<col style="width:{width}%">' for width in [3, 9, 8, 16, 17, 6, 6, 7, 7, 10, 11])
    weights = weight(document.get("total_weight_kg"))
    return f'''<!doctype html><html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{text["title"]} {value(document["shipment_no"])}</title>
<style>
*{{box-sizing:border-box}}body{{font:400 9pt "Helvetica Neue",Arial,sans-serif;line-height:1.35;color:#202124;background:#fff;margin:20px auto;max-width:190mm;padding:0}}
.controls{{margin-bottom:16px}}button{{font:inherit;padding:8px 16px;background:#fff;border:1px solid #b9bec4;border-radius:4px;cursor:pointer}}
.masthead{{display:flex;align-items:center;justify-content:space-between;gap:10mm;padding:0 0 4mm;border-bottom:1.5pt solid #b82025;break-inside:avoid}}
h1{{font-size:19pt;line-height:1.2;font-weight:700;margin:2mm 0}}.supplier{{margin:0;font-size:11pt}}.document-number{{margin:2mm 0 0;color:#51565d;font-size:9pt}}
.logo{{width:38mm;height:auto;display:block;flex:none}}
table{{width:100%;border-collapse:collapse;table-layout:fixed}}td,th{{overflow-wrap:anywhere;vertical-align:middle}}
.meta{{margin:3mm 0 4mm}}.meta th,.meta td{{padding:1mm 2mm 1mm 0;text-align:left;border-bottom:.5pt solid #e1e4e7}}
.meta th{{font-size:8pt;font-weight:400;color:#575e66}}.meta td{{font-size:9pt;font-weight:700}}.meta th:nth-child(3){{padding-left:5mm}}
.items{{font-size:7.5pt;line-height:1.15}}.items th,.items td{{padding:.7mm 1mm;border:.5pt solid #c8cdd2;text-align:center}}
.items thead th{{background:#eaf0f5;color:#263746;font-size:7pt;font-weight:700;padding:2.2mm .8mm}}
.items .description,.items .sizes{{text-align:left}}.items .sizes{{font-size:7pt;color:#444b52}}
.items .numeric{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap;font-size:7pt}}
.size-label{{display:inline-block;width:50%;white-space:normal}}.size-label.multicolor{{width:100%;white-space:normal}}
thead{{display:table-header-group}}tr{{break-inside:avoid}}.items tbody:first-of-type tr:last-child{{break-after:avoid}}
.items .totals td{{font-weight:700;background:#eef1f3;border-top:1pt solid #64717e;padding-top:3mm;padding-bottom:3mm}}
.items .totals .total-label{{font-size:10pt;text-align:left;padding-left:3mm}}
.accounting{{margin-top:4mm;font-size:8pt;break-inside:avoid;color:#51565d}}p{{margin:1.5mm 0}}.warning{{padding-left:2mm;border-left:1.5pt solid #b82025}}
.signatures{{display:flex;gap:20mm;justify-content:space-between;margin-top:6mm;break-inside:avoid;color:#51565d;font-size:8pt}}
.signatures div{{width:44%;border-top:.5pt solid #939ba3;padding-top:2mm}}
@page{{size:A4 portrait;margin:10mm;@bottom-right{{content:counter(page) " / " counter(pages);font:8pt Arial,sans-serif;color:#67717a}}}}
@media print{{body{{margin:0;max-width:none;width:100%}}.controls{{display:none}}*{{print-color-adjust:exact;-webkit-print-color-adjust:exact}}}}
@media screen and (max-width:740px){{body{{min-width:700px;margin:16px}}}}
</style></head><body><div class="controls"><button onclick="window.print()">{text["print"]}</button></div>
<header class="masthead"><div><p class="supplier">{value(document.get("supplier") or "Milana Tex")}</p><h1>{text["title"]}</h1>
<p class="document-number">{value(document["shipment_no"])}</p></div><img class="logo" src="{invoice_logo_uri()}" alt="Milana Premium"></header>
<table class="meta"><colgroup><col style="width:16%"><col style="width:34%"><col style="width:21%"><col style="width:29%"></colgroup><tbody>{metadata_html}</tbody></table>
<table class="items"><colgroup>{columns}</colgroup><thead><tr>{"".join(f"<th scope='col'>{header}</th>" for header in headers)}</tr></thead>
<tbody>{"".join(body)}</tbody><tbody><tr class="totals"><td class="total-label" colspan="5">{text["total"]}</td>
<td class="numeric">{number(document["packages_count"], 0)}</td><td class="numeric">{number(document["quantity"], 0)}</td>
<td class="numeric">{weights}</td><td class="numeric">{weights}</td><td class="numeric" colspan="2">{number(document.get("amount"))}</td></tr></tbody></table>
<div class="accounting">{adjustment}{warning}<p>{posting}</p><p>{text["net"]}</p></div>
<div class="signatures"><div>{text["issued"]}</div><div>{text["received"]}</div></div></body></html>'''
