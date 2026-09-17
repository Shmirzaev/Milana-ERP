from io import BytesIO
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from app.services.inventory_reports import _register_report_fonts

TEXT = {
    "en": ["Fabric dispatch to Eco Cotton", "Sent items", "Remaining fabric inventory after dispatch",
           "Fabric", "Batch", "Color", "Roll", "Quantity", "Unit", "Operator", "Sent", "Page",
           "Internal custody record. No inventory receipt is created at Eco Cotton.", "No remaining fabric.", "Rolls"],
    "ru": ["Отправка ткани в Eco Cotton", "Отправленные материалы", "Остаток ткани на складе после отправки",
           "Ткань", "Партия", "Цвет", "Рулон", "Количество", "Ед.", "Оператор", "Отправлено", "Страница",
           "Внутренний учёт передачи. Приход на склад Eco Cotton не создаётся.", "Ткани на складе не осталось.", "Рулоны"],
    "uz": ["Eco Cottonga mato yuborish", "Yuborilgan materiallar", "Yuborilgandan keyingi ombordagi mato qoldig‘i",
           "Mato", "Partiya", "Rang", "Rulon", "Miqdor", "Birlik", "Operator", "Yuborildi", "Sahifa",
           "Ichki hisob. Eco Cotton omboriga kirim yaratilmaydi.", "Omborda mato qolmadi.", "Rulonlar"],
}


def build_pdf(dispatch, lang="en"):
    from app.api.routes.fabric_scans import TASHKENT
    from datetime import timezone
    t = TEXT.get(lang, TEXT["en"])
    regular, bold = _register_report_fonts()
    output = BytesIO()
    document = SimpleDocTemplate(output, pagesize=A4, leftMargin=32, rightMargin=32,
                                 topMargin=34, bottomMargin=36, title=t[0], author="Milana ERP")
    body = ParagraphStyle("body", fontName=regular, fontSize=9, leading=13)
    heading = ParagraphStyle("heading", fontName=bold, fontSize=15, leading=21, spaceAfter=10)
    subheading = ParagraphStyle("section", fontName=bold, fontSize=11, leading=16, spaceBefore=14, spaceAfter=8)
    def p(value): return Paragraph(escape(str(value or "-")), body)
    def table(rows):
        headers = [t[3], t[4], t[5], t[6], t[7], t[8]]
        data = [[p(value) for value in headers]]
        for row in rows:
            values = [row["fabric_name"], row["batch_no"], row.get("color")]
            values.append(row["roll_number"])
            values.extend([f'{float(row["quantity"]):,.2f}', row["unit"]])
            data.append([p(value) for value in values])
        widths = [170, 84, 75, 62, 90, 50]
        result = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
        result.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#f1efe8")),
            ("VALIGN", (0,0), (-1,-1), "TOP"), ("LINEBELOW", (0,0), (-1,0), .7, colors.HexColor("#777366")),
            ("LINEBELOW", (0,1), (-1,-1), .35, colors.HexColor("#dad7ce")),
            ("TOPPADDING", (0,0), (-1,-1), 7), ("BOTTOMPADDING", (0,0), (-1,-1), 7)]))
        return result
    timestamp = dispatch["sent_at"]
    if timestamp.tzinfo is None: timestamp = timestamp.replace(tzinfo=timezone.utc)
    when = timestamp.astimezone(TASHKENT).strftime("%d.%m.%Y %H:%M")
    story = [Paragraph("Milana Premium", heading), Paragraph(escape(t[0]), heading),
             p(f'{dispatch["number"]} | {t[10]}: {when} (Tashkent)'),
             p(f'{t[9]}: {dispatch["operator_name"]}'), Spacer(1, 8), p(t[12]),
             Paragraph(escape(t[1]), subheading), table(dispatch["rows"]),
             Spacer(1, 8), p(f'{t[14]}: {dispatch["sent_rolls"]} | {float(dispatch["sent_kg"]):,.2f} kg')]
    def footer(canvas, doc):
        canvas.setFont(regular, 8)
        canvas.drawString(32, 20, dispatch["number"])
        canvas.drawRightString(A4[0]-32, 20, f"{t[11]} {doc.page}")
    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
