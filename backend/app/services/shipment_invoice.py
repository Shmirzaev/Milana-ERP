"""Standalone printable shipment invoice; deliberately never writes finance data."""
from html import escape


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
    posting = text["posting"]
    if document.get("finance_posting_status") == "posted":
        posting = {"en": "Posted on delivery to ledger invoice", "ru": "Проведён при доставке в финансовый счёт",
                   "uz": "Yetkazishda moliyaviy hisobga o‘tkazilgan"}[lang] + ": " + escape(str(document.get("ledger_invoice_no") or ""))
    def value(raw):
        return escape(str(raw)) if raw is not None else "—"
    columns = ("pack", "model", "color", "size", "qty", "price", "amount")
    head = "".join(f"<th>{text[key]}</th>" for key in columns)
    rows = []
    for line in document["lines"]:
        cells = [line.get(key) for key in ("package_no", "model_code", "color", "size", "quantity", "unit_price", "amount")]
        rows.append("<tr>" + "".join(f"<td>{value(cell)}</td>" for cell in cells) + "</tr>")
    warning = f'<p class="warning">{text["historical"]}</p>' if document.get("historical_reconstruction") else ""
    adjustment = ""
    if document.get("adjustment_reason"):
        adjustment = f'<p>{text["calculated"]}: {value(document.get("calculated_amount"))}</p><p>{text["adjustment"]}: {value(document["adjustment_reason"])}</p>'
    amount = value(document["amount"]) if document.get("amount") is not None else text["missing"]
    return f'''<!doctype html><html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{text["title"]} {value(document["shipment_no"])}</title>
<style>
body{{font:14px system-ui,sans-serif;color:#14110b;background:#fff;margin:24px auto;max-width:1000px;padding:0 20px}}
h1{{font-size:22px;font-weight:600;margin:8px 0 16px}}p{{margin:8px 0}}header{{border-bottom:1px solid #777;padding-bottom:12px}}
table{{width:100%;border-collapse:collapse;margin:24px 0}}th,td{{text-align:left;padding:8px 6px;border-bottom:1px solid #ccc;overflow-wrap:anywhere}}
th{{font-weight:600}}td:nth-last-child(-n+3),th:nth-last-child(-n+3){{text-align:right;font-variant-numeric:tabular-nums}}
thead{{display:table-header-group}}tr{{break-inside:avoid}}.totals{{text-align:right;break-inside:avoid}}.warning{{border:1px solid #777;padding:8px}}
button{{padding:8px 16px;background:#fff;border:1px solid #777;border-radius:6px;cursor:pointer}}footer{{margin-top:40px;border-top:1px solid #777;padding-top:12px}}
@page{{size:A4;margin:14mm}}@media print{{body{{margin:0;padding:0;max-width:none;font-size:10pt}}.controls{{display:none}}}}
</style></head><body><div class="controls"><button onclick="window.print()">{text["print"]}</button><p>{text["reference"]}</p></div>
<header><p>{value(document["supplier"])}</p><h1>{text["title"]} {value(document["shipment_no"])}</h1>
<p>{text["order"]}: {value(document.get("sales_order_no"))}</p><p>{text["customer"]}: {value(document.get("customer"))}</p>
<p>{text["date"]}: {value(document.get("shipped_at"))}</p><p>{posting}</p></header>{warning}
<table><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table>
<div class="totals"><p>{text["packs"]}: {document["packages_count"]} · {text["qty"]}: {document["quantity"]}</p>{adjustment}
<p><strong>{text["total"]}: {amount}</strong></p><p>{text["net"]}</p></div>
<footer>{text["signature"]}: ____________________ / ____________________</footer></body></html>'''
