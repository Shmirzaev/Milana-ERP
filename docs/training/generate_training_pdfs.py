from __future__ import annotations

import html
import re
from pathlib import Path

from pypdf import PdfWriter, PdfReader
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "docs" / "training"
OUTPUT_DIR = ROOT / "output" / "pdf" / "training"

DOC_ORDER = [
    "README.md",
    "00_FULL_PROCESS_OVERVIEW.md",
    "01_SALES.md",
    "02_MODELING_PLM.md",
    "03_PLANNING.md",
    "04_PURCHASING.md",
    "05_FABRIC_ACCESSORIES_STORAGE.md",
    "06_CUTTING.md",
    "07_PRINTING.md",
    "08_SEWING.md",
    "09_MILANA_SEWING_FACTORY.md",
    "10_BESTTEX_SEWING_FACTORY.md",
    "11_PACKAGING.md",
    "12_BESTTEX_TEXTILE_PACKAGING.md",
    "13_READY_PRODUCT_STORAGE.md",
    "14_WASTE_DEPARTMENT.md",
    "15_FINANCE.md",
    "16_HR.md",
    "17_MANAGEMENT_ADMIN.md",
    "18_SUPERADMIN_FULL_DETAILS.md",
]


def make_styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "TrainingTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=22,
            leading=27,
            textColor=colors.HexColor("#14110b"),
            spaceAfter=10,
        ),
        "subtitle": ParagraphStyle(
            "TrainingSubtitle",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#56503f"),
            spaceAfter=8,
        ),
        "h1": ParagraphStyle(
            "TrainingH1",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=colors.HexColor("#14110b"),
            spaceBefore=8,
            spaceAfter=8,
        ),
        "h2": ParagraphStyle(
            "TrainingH2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=16,
            textColor=colors.HexColor("#2c2920"),
            spaceBefore=10,
            spaceAfter=5,
        ),
        "h3": ParagraphStyle(
            "TrainingH3",
            parent=base["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=11.5,
            leading=14,
            textColor=colors.HexColor("#3b3528"),
            spaceBefore=8,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "TrainingBody",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=13.2,
            textColor=colors.HexColor("#2c2920"),
            spaceAfter=5,
        ),
        "list": ParagraphStyle(
            "TrainingList",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9.3,
            leading=12.5,
            leftIndent=8,
            firstLineIndent=0,
            textColor=colors.HexColor("#2c2920"),
        ),
        "code": ParagraphStyle(
            "TrainingCode",
            parent=base["Code"],
            fontName="Courier",
            fontSize=8.2,
            leading=10.5,
            leftIndent=6,
            rightIndent=6,
            borderPadding=5,
            backColor=colors.HexColor("#f1efe8"),
            textColor=colors.HexColor("#14110b"),
            spaceBefore=4,
            spaceAfter=6,
        ),
        "table_header": ParagraphStyle(
            "TrainingTableHeader",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=7.8,
            leading=9.4,
            textColor=colors.HexColor("#14110b"),
        ),
        "table_cell": ParagraphStyle(
            "TrainingTableCell",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=7.8,
            leading=9.4,
            textColor=colors.HexColor("#2c2920"),
        ),
        "cover": ParagraphStyle(
            "TrainingCover",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=24,
            leading=29,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#14110b"),
            spaceAfter=12,
        ),
        "cover_sub": ParagraphStyle(
            "TrainingCoverSub",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=11,
            leading=15,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#56503f"),
            spaceAfter=8,
        ),
    }


STYLES = make_styles()


def inline_markup(text: str) -> str:
    text = html.escape(text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)
    text = re.sub(r"`([^`]+)`", r'<font name="Courier">\1</font>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    return text


def para(text: str, style_name: str = "body") -> Paragraph:
    return Paragraph(inline_markup(text), STYLES[style_name])


def parse_table(lines: list[str], start: int) -> tuple[Table, int]:
    rows: list[list[str]] = []
    i = start
    while i < len(lines) and lines[i].strip().startswith("|"):
        raw = lines[i].strip()
        cells = [cell.strip() for cell in raw.strip("|").split("|")]
        if not all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in cells):
            rows.append(cells)
        i += 1

    column_count = max(len(row) for row in rows)
    normalized = [row + [""] * (column_count - len(row)) for row in rows]
    data = []
    for row_index, row in enumerate(normalized):
        style = "table_header" if row_index == 0 else "table_cell"
        data.append([Paragraph(inline_markup(cell), STYLES[style]) for cell in row])

    available_width = A4[0] - 36 * mm
    col_widths = [available_width / column_count] * column_count
    table = Table(data, colWidths=col_widths, hAlign="LEFT", repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1efe8")),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d8d2c2")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table, i


def parse_list(lines: list[str], start: int, ordered: bool) -> tuple[ListFlowable, int]:
    items = []
    i = start
    pattern = r"^\s*\d+\.\s+(.*)$" if ordered else r"^\s*[-*]\s+(.*)$"
    while i < len(lines):
        match = re.match(pattern, lines[i])
        if not match:
            break
        items.append(ListItem(para(match.group(1), "list"), leftIndent=0))
        i += 1
    flow = ListFlowable(
        items,
        bulletType="1" if ordered else "bullet",
        start="1" if ordered else None,
        leftIndent=15,
        bulletFontName="Helvetica",
        bulletFontSize=8,
        bulletColor=colors.HexColor("#56503f"),
    )
    return flow, i


def markdown_to_story(path: Path, *, include_title: bool = True) -> list:
    lines = path.read_text(encoding="utf-8").splitlines()
    story: list = []
    i = 0
    in_code = False
    code_lines: list[str] = []
    pending_para: list[str] = []

    def flush_para() -> None:
        nonlocal pending_para
        if pending_para:
            story.append(para(" ".join(pending_para)))
            pending_para = []

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):
            flush_para()
            if in_code:
                story.append(Paragraph("<br/>".join(html.escape(x) for x in code_lines), STYLES["code"]))
                code_lines = []
                in_code = False
            else:
                in_code = True
            i += 1
            continue

        if in_code:
            code_lines.append(line)
            i += 1
            continue

        if not stripped:
            flush_para()
            i += 1
            continue

        if stripped.startswith("|"):
            flush_para()
            table, i = parse_table(lines, i)
            story.append(table)
            story.append(Spacer(1, 7))
            continue

        if re.match(r"^\s*\d+\.\s+", line):
            flush_para()
            flow, i = parse_list(lines, i, ordered=True)
            story.append(flow)
            story.append(Spacer(1, 4))
            continue

        if re.match(r"^\s*[-*]\s+", line):
            flush_para()
            flow, i = parse_list(lines, i, ordered=False)
            story.append(flow)
            story.append(Spacer(1, 4))
            continue

        if stripped.startswith("# "):
            flush_para()
            if include_title:
                story.append(para(stripped[2:].strip(), "title"))
            i += 1
            continue

        if stripped.startswith("## "):
            flush_para()
            story.append(para(stripped[3:].strip(), "h2"))
            i += 1
            continue

        if stripped.startswith("### "):
            flush_para()
            story.append(para(stripped[4:].strip(), "h3"))
            i += 1
            continue

        pending_para.append(stripped)
        i += 1

    flush_para()
    return story


def doc_title(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem.replace("_", " ").title()


def header_footer(canvas, doc, title: str):
    canvas.saveState()
    width, height = A4
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#8a8472"))
    canvas.drawString(18 * mm, height - 11 * mm, "Milana ERP Training")
    canvas.drawRightString(width - 18 * mm, height - 11 * mm, title[:82])
    canvas.setStrokeColor(colors.HexColor("#e3dfd3"))
    canvas.setLineWidth(0.35)
    canvas.line(18 * mm, height - 14 * mm, width - 18 * mm, height - 14 * mm)
    canvas.setFont("Helvetica", 8)
    canvas.drawCentredString(width / 2, 10 * mm, f"Page {doc.page}")
    canvas.restoreState()


def build_pdf(source: Path, target: Path) -> None:
    title = doc_title(source)
    doc = SimpleDocTemplate(
        str(target),
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=20 * mm,
        bottomMargin=18 * mm,
        title=title,
        author="Milana ERP",
    )
    story = markdown_to_story(source)
    doc.build(story, onFirstPage=lambda c, d: header_footer(c, d, title), onLaterPages=lambda c, d: header_footer(c, d, title))


def build_combined(paths: list[Path], target: Path) -> None:
    title = "Milana ERP Training Pack"
    doc = SimpleDocTemplate(
        str(target),
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=20 * mm,
        bottomMargin=18 * mm,
        title=title,
        author="Milana ERP",
    )
    story: list = [
        Spacer(1, 60 * mm),
        Paragraph("Milana ERP Training Pack", STYLES["cover"]),
        Paragraph("Department manuals and Super Admin full details", STYLES["cover_sub"]),
        Paragraph("Generated from docs/training", STYLES["cover_sub"]),
        PageBreak(),
    ]
    for idx, path in enumerate(paths):
        if idx:
            story.append(PageBreak())
        story.extend(markdown_to_story(path))
    doc.build(story, onFirstPage=lambda c, d: header_footer(c, d, title), onLaterPages=lambda c, d: header_footer(c, d, title))


def count_pages(path: Path) -> int:
    return len(PdfReader(str(path)).pages)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    sources = [SOURCE_DIR / name for name in DOC_ORDER]
    missing = [str(path) for path in sources if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing training sources: " + ", ".join(missing))

    for source in sources:
        build_pdf(source, OUTPUT_DIR / source.with_suffix(".pdf").name)

    combined = OUTPUT_DIR / "Milana_ERP_Training_Pack_All_Departments.pdf"
    build_combined(sources, combined)

    summary = []
    for pdf in sorted(OUTPUT_DIR.glob("*.pdf")):
        summary.append(f"{pdf.name}: {count_pages(pdf)} pages")
    print("\n".join(summary))


if __name__ == "__main__":
    main()
