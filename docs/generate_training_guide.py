"""Generate a per-department training guide PDF for the Milana ERP.

Run:
    python docs/generate_training_guide.py

Outputs: docs/Milana_ERP_Training_Guide.pdf
"""
from __future__ import annotations

from pathlib import Path
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak,
    Table, TableStyle, ListFlowable, ListItem, KeepTogether,
)


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------
styles = getSampleStyleSheet()

TITLE = ParagraphStyle(
    "TitleBig", parent=styles["Title"], fontSize=28, leading=34,
    textColor=colors.HexColor("#1e3a8a"), alignment=TA_CENTER, spaceAfter=12,
)
SUBTITLE = ParagraphStyle(
    "Subtitle", parent=styles["Title"], fontSize=14, leading=18,
    textColor=colors.HexColor("#475569"), alignment=TA_CENTER, spaceAfter=24,
)
H1 = ParagraphStyle(
    "H1", parent=styles["Heading1"], fontSize=20, leading=24,
    textColor=colors.HexColor("#1e3a8a"), spaceBefore=18, spaceAfter=12,
)
H2 = ParagraphStyle(
    "H2", parent=styles["Heading2"], fontSize=14, leading=18,
    textColor=colors.HexColor("#1d4ed8"), spaceBefore=14, spaceAfter=8,
)
H3 = ParagraphStyle(
    "H3", parent=styles["Heading3"], fontSize=11, leading=14,
    textColor=colors.HexColor("#0f172a"), spaceBefore=10, spaceAfter=4,
)
BODY = ParagraphStyle(
    "Body", parent=styles["BodyText"], fontSize=10.5, leading=14,
    textColor=colors.HexColor("#1f2937"), spaceAfter=6,
)
NOTE = ParagraphStyle(
    "Note", parent=BODY, fontSize=9.5, leading=12,
    textColor=colors.HexColor("#374151"),
    backColor=colors.HexColor("#fef9c3"),
    borderColor=colors.HexColor("#facc15"),
    borderWidth=0.5, borderPadding=6, leftIndent=0, rightIndent=0,
    spaceBefore=6, spaceAfter=10,
)
TIP = ParagraphStyle(
    "Tip", parent=NOTE,
    backColor=colors.HexColor("#dcfce7"),
    borderColor=colors.HexColor("#22c55e"),
)
WARN = ParagraphStyle(
    "Warn", parent=NOTE,
    backColor=colors.HexColor("#fee2e2"),
    borderColor=colors.HexColor("#ef4444"),
)
CODE = ParagraphStyle(
    "Code", parent=BODY, fontName="Courier", fontSize=9.5, leading=12,
    textColor=colors.HexColor("#0f172a"),
    backColor=colors.HexColor("#f1f5f9"),
    borderPadding=4, leftIndent=4, rightIndent=4,
    spaceBefore=4, spaceAfter=8,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def steps(items: list[str]) -> ListFlowable:
    return ListFlowable(
        [ListItem(Paragraph(t, BODY), leftIndent=18) for t in items],
        bulletType="1", start="1", leftIndent=18, bulletFontSize=10,
        bulletColor=colors.HexColor("#1d4ed8"),
    )


def bullets(items: list[str]) -> ListFlowable:
    return ListFlowable(
        [ListItem(Paragraph(t, BODY), leftIndent=18) for t in items],
        bulletType="bullet", leftIndent=18,
        bulletColor=colors.HexColor("#475569"),
    )


def note(text: str):
    return Paragraph("<b>Note.</b> " + text, NOTE)


def tip(text: str):
    return Paragraph("<b>Tip.</b> " + text, TIP)


def warn(text: str):
    return Paragraph("<b>Important.</b> " + text, WARN)


def code(text: str):
    safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return Paragraph(safe, CODE)


def info_table(rows: list[tuple[str, str]]):
    data = [[Paragraph(f"<b>{k}</b>", BODY), Paragraph(v, BODY)] for k, v in rows]
    t = Table(data, colWidths=[45 * mm, 110 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f1f5f9")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def page_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#64748b"))
    canvas.drawString(20 * mm, 12 * mm, "Milana ERP — Department Training Guide")
    canvas.drawRightString(190 * mm, 12 * mm, f"Page {doc.page}")
    canvas.restoreState()


# ---------------------------------------------------------------------------
# Content blocks
# ---------------------------------------------------------------------------

def cover():
    return [
        Spacer(1, 60 * mm),
        Paragraph("Milana ERP", TITLE),
        Paragraph("Department-by-Department Training Guide", SUBTITLE),
        Spacer(1, 20 * mm),
        Paragraph(
            "A practical, step-by-step manual for operators in Sales, Planning, Storage, "
            "Cutting, Printing, Sewing, Packaging, Ready-Goods Storage, Waste, Finance, "
            "Modeling/PLM, HR, and Management.",
            ParagraphStyle("CoverBody", parent=BODY, alignment=TA_CENTER, fontSize=11),
        ),
        Spacer(1, 50 * mm),
        Paragraph(
            f"Version 1.0 &nbsp;·&nbsp; {date.today().isoformat()}",
            ParagraphStyle("CoverDate", parent=BODY, alignment=TA_CENTER,
                           textColor=colors.HexColor("#64748b")),
        ),
        PageBreak(),
    ]


def toc():
    rows = [
        ("1.", "Getting Started — All Users"),
        ("2.", "Sales Department"),
        ("3.", "Modeling / PLM Department"),
        ("4.", "Planning Department"),
        ("5.", "Fabric & Accessories Storage"),
        ("6.", "Fabric Cutting Department"),
        ("7.", "Printing Department"),
        ("8.", "Sewing Department"),
        ("9.", "Packaging Department"),
        ("10.", "Ready Product Storage"),
        ("11.", "Waste Department"),
        ("12.", "Finance Department"),
        ("13.", "HR Department"),
        ("14.", "Management / Admin"),
        ("15.", "Troubleshooting & FAQ"),
    ]
    data = [[Paragraph(f"<b>{n}</b>", BODY), Paragraph(t, BODY)] for n, t in rows]
    table = Table(data, colWidths=[15 * mm, 140 * mm])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return [Paragraph("Contents", H1), table, PageBreak()]


# ---------------------------------------------------------------------------
# Section: Getting Started
# ---------------------------------------------------------------------------

def section_getting_started():
    blocks = [
        Paragraph("1. Getting Started — All Users", H1),
        Paragraph("1.1 Logging in", H2),
        Paragraph(
            "The ERP web application is available at "
            "<b>http://localhost:3000</b> (or the URL your IT administrator provides). "
            "Every user has a personal email and password.",
            BODY,
        ),
        steps([
            "Open the URL in Chrome, Edge, or Firefox.",
            "On the Login screen, enter your work email and password.",
            "Click <b>Sign in</b>. You will land on the main dashboard.",
            "To log out, use the <b>Logout</b> button in the top-right corner.",
        ]),
        tip("If you forget your password, ask the Admin (Management / Admin department) to reset it from the <i>Admin → Users</i> page."),
        Paragraph("1.2 Training accounts", H2),
        Paragraph(
            "During training, IT may seed one demo user per department. Passwords are provided privately by the Admin and should be changed or disabled before production use.",
            BODY,
        ),
        info_table([
            ("Admin", "admin@example.com"),
            ("Sales", "sales@example.com"),
            ("Planning", "planning@example.com"),
            ("Modeling", "modeling@example.com"),
            ("Storage", "storage@example.com"),
            ("Cutting", "cutting@example.com"),
            ("Printing", "printing@example.com"),
            ("Sewing", "sewing@example.com"),
            ("Packaging", "packaging@example.com"),
            ("Ready Storage", "fgs@example.com"),
            ("Waste", "waste@example.com"),
            ("Finance", "finance@example.com"),
            ("HR", "hr@example.com"),
            ("Management", "mgr@example.com"),
        ]),
        Paragraph("1.3 Layout and navigation", H2),
        bullets([
            "<b>Sidebar (left).</b> Department-specific menu items. You only see what your role allows.",
            "<b>Top bar.</b> Your name, role, department, and a Logout button.",
            "<b>Main area.</b> Tables, forms, and dashboards.",
            "<b>Dashboard cards.</b> Click into any list to drill down to detail pages.",
        ]),
        Paragraph("1.4 Understanding statuses and badges", H2),
        Paragraph(
            "Every order, work order, bundle, and package shows a colored badge with its current status. "
            "Statuses change automatically as you perform actions (confirm, scan, complete). "
            "If a button is missing or disabled, it usually means the record is not in a state where that action is allowed.",
            BODY,
        ),
        Paragraph("1.5 Scanning barcodes and QR codes", H2),
        Paragraph(
            "USB barcode scanners behave like keyboards — they type the barcode value and press Enter. "
            "On any <b>Scan</b> page, simply place the cursor in the input field and scan. "
            "You can also type the value manually for testing.",
            BODY,
        ),
        warn("Never share your login. The ERP audit log records every action under your name, including approvals and stock changes."),
        PageBreak(),
    ]
    return blocks


# ---------------------------------------------------------------------------
# Department template
# ---------------------------------------------------------------------------

def department(
    n: int, name: str, role: str, email: str, color: str,
    overview: str, daily: list[str], procedures: list[tuple[str, list[str]]],
    tips: list[str] | None = None, warns: list[str] | None = None,
    pages: list[str] | None = None,
):
    blocks: list = []
    blocks.append(Paragraph(f"{n}. {name}", H1))

    blocks.append(Paragraph("Quick facts", H2))
    blocks.append(info_table([
        ("Role in ERP", role),
        ("Training login", email),
        ("Pages used", ", ".join(pages or [])),
    ]))

    blocks.append(Paragraph("Overview", H2))
    blocks.append(Paragraph(overview, BODY))

    blocks.append(Paragraph("Daily tasks at a glance", H2))
    blocks.append(bullets(daily))

    blocks.append(Paragraph("Step-by-step procedures", H2))
    for title, items in procedures:
        blocks.append(Paragraph(title, H3))
        blocks.append(steps(items))

    if tips:
        blocks.append(Paragraph("Tips", H2))
        for t in tips:
            blocks.append(tip(t))

    if warns:
        blocks.append(Paragraph("Watch out for", H2))
        for w in warns:
            blocks.append(warn(w))

    blocks.append(PageBreak())
    return blocks


# ---------------------------------------------------------------------------
# Department definitions
# ---------------------------------------------------------------------------

SALES = department(
    n=2, name="Sales Department", role="Sales", email="sales@example.com",
    color="#1d4ed8",
    pages=["Sales Orders", "Customers", "Shipments (read)"],
    overview=(
        "The Sales team is the first point of contact for the customer. You enter "
        "customer information, create sales orders (either client-specific or branded-stock sales), "
        "and monitor delivery status. For branded-stock sales you can reserve finished stock "
        "directly from the warehouse without waiting for new production."
    ),
    daily=[
        "Check the dashboard for late or upcoming order deadlines.",
        "Capture new customer enquiries and create draft orders.",
        "Confirm orders once the customer signs off.",
        "For branded stock sales, reserve stock and report shortages to Planning.",
        "Track shipments and update the customer on delivery progress.",
    ],
    procedures=[
        ("A. Add a new customer", [
            "In the sidebar, click <b>Customers</b>.",
            "Fill the form at the top: name (required), phone, email, address.",
            "Click <b>Add</b>. The customer appears in the table below.",
        ]),
        ("B. Create a sales order (client order)", [
            "Sidebar → <b>Sales Orders</b> → click <b>+ New Order</b>.",
            "Set <b>Order type</b> to <i>Client order</i>.",
            "Pick the customer and set a deadline.",
            "Add one line per (model, color, size, quantity, unit price). Tick <b>Printing</b> if the model needs printing.",
            "Click <b>Create order</b>. The order is saved in status <i>draft</i>.",
            "Open the order detail page and click <b>Confirm</b> when the customer approves. Status changes to <i>confirmed</i> and Planning can now act on it.",
        ]),
        ("C. Create a branded-stock sale", [
            "Sidebar → <b>Sales Orders</b> → click <b>+ New Order</b>.",
            "Set <b>Order type</b> to <i>Branded stock sale</i>.",
            "Add the order lines exactly as for a client order.",
            "Save and confirm.",
            "Open the order detail page and click <b>Reserve stock</b>.",
            "Review the reservation result: how many pieces were reserved, and any shortages.",
            "If shortages exist, notify Planning so they can schedule additional branded production.",
        ]),
        ("D. Track shipment status", [
            "Open the sales order detail page.",
            "Status will progress: <i>confirmed → planning → production → ready → delivered → closed</i>.",
            "When status is <i>ready</i> the Storage team is preparing shipment.",
            "When status is <i>delivered</i> the package has been confirmed by the carrier or customer.",
        ]),
    ],
    tips=[
        "Use the search bar in Sales Orders to quickly find an order number (e.g. <i>SO-2026-000003</i>).",
        "Set a realistic deadline — the dashboard highlights overdue orders in red for everyone.",
    ],
    warns=[
        "Do not change the order quantity after Planning has created a Production Order. Cancel and recreate instead, otherwise material requirements will be wrong.",
    ],
)

MODELING = department(
    n=3, name="Modeling / PLM Department", role="Modeling",
    email="modeling@example.com", color="#7c3aed",
    pages=["Models", "Brands", "Collections", "BOM editor (per model)"],
    overview=(
        "Modeling owns the product catalog. You create models (tech packs), define sizes and "
        "colors, attach a Bill of Materials (BOM) with fabric and accessory consumption per piece, "
        "and submit models for Management approval. Only <b>approved</b> models can be used to "
        "create branded-stock production."
    ),
    daily=[
        "Capture new model specs from designers.",
        "Build or update the BOM for each model.",
        "Submit completed models for approval.",
        "Maintain brands and seasonal collections.",
    ],
    procedures=[
        ("A. Create a new brand", [
            "Sidebar → <b>Brands</b>.",
            "Enter brand name and description.",
            "Click <b>Create</b>.",
        ]),
        ("B. Create a collection", [
            "Sidebar → <b>Collections</b>.",
            "Pick the brand, give the collection a name, season (e.g. <i>Spring/Summer</i>) and year.",
            "Click <b>Create</b>.",
        ]),
        ("C. Create a model (draft)", [
            "Sidebar → <b>Models</b>.",
            "Fill code (e.g. <i>T-SHIRT-002</i>), name, category.",
            "Click <b>Create draft model</b>. The model is saved in status <i>draft</i>.",
            "Click the model name to open its detail page.",
            "Add sizes (S, M, L, XL…) in the Sizes box.",
            "Add colors (name + hex code) in the Colors box.",
        ]),
        ("D. Build the Bill of Materials (BOM)", [
            "On the model detail page, scroll to <b>Bill of Materials</b>.",
            "Pick the item (fabric, accessory, packaging).",
            "Enter quantity per piece, unit, and waste percent.",
            "Click <b>Add BOM row</b>.",
            "Repeat for every input the model consumes (main fabric, lining, thread, buttons, polybag, etc.).",
        ]),
        ("E. Submit for approval", [
            "When the model and BOM are complete, return to <b>Models</b>.",
            "Click <b>Approve</b> next to the model (requires the <i>modeling.approve</i> permission, normally Management).",
            "Status becomes <i>approved</i> and the model becomes available to Planning for production.",
        ]),
    ],
    tips=[
        "Set realistic <b>waste percent</b> on each BOM line. Planning uses it to inflate material requirements.",
        "Reuse standard accessories (thread, polybag) across models — just add the same item to multiple BOMs.",
    ],
    warns=[
        "Once a model is approved and used in production, do not silently change its BOM. Create a new model code (e.g. <i>T-SHIRT-002-v2</i>) so existing orders keep their original BOM.",
    ],
)

PLANNING = department(
    n=4, name="Planning Department", role="Planning",
    email="planning@example.com", color="#0ea5e9",
    pages=["Planning Dashboard", "Production Orders", "Sales Orders (read)"],
    overview=(
        "Planning converts confirmed sales orders into Production Orders and the corresponding "
        "Work Orders for each department (Cutting → Printing → Sewing → Packaging → Storage). "
        "Planning also schedules branded-stock production independently of customer orders."
    ),
    daily=[
        "Review confirmed sales orders awaiting planning.",
        "Calculate material requirements and identify shortages.",
        "Create Production Orders and generate Work Orders.",
        "Schedule branded-stock production when finished stock runs low.",
    ],
    procedures=[
        ("A. Review material requirements for a sales order", [
            "Sidebar → <b>Sales Orders</b> and open the confirmed order.",
            "Scroll down to <b>Material requirements</b>.",
            "Each row shows: required quantity (BOM × order qty × (1 + waste%)), current available stock, and shortage.",
            "If any row has a shortage, alert Storage to order more fabric or accessories before production starts.",
        ]),
        ("B. Create a Production Order for a client order", [
            "Sidebar → <b>Planning Dashboard</b>.",
            "Under <i>Confirmed orders awaiting planning</i>, click <b>Create Production Order</b> on the relevant sales order.",
            "The system automatically copies all order lines into Production Order items and generates Work Orders for Cutting, Sewing, Packaging, and Storage transfer.",
            "Optionally pass <code>include_printing=true</code> if a printing step is required.",
            "You will be redirected to the Production Order detail page.",
        ]),
        ("C. Create a branded-stock production plan", [
            "Sidebar → <b>Planning Dashboard</b>.",
            "Scroll to <b>Branded stock production</b>.",
            "Pick an <b>approved</b> model, set color, size, and quantity.",
            "Click <b>Create branded plan</b>. A Production Order with <i>production_type = branded_stock</i> is created (no sales order attached).",
        ]),
        ("D. Generate work orders later", [
            "If you opened a Production Order without auto-generated work orders, open its detail page.",
            "Click <b>Generate work orders</b>. New work orders appear in the Work orders table at the bottom.",
        ]),
    ],
    tips=[
        "Always check material shortages before generating Work Orders. Sending Cutting into production without fabric guarantees idle time.",
        "Use the <i>active production orders</i> card on the dashboard to monitor workload across all departments.",
    ],
    warns=[
        "Only approved models can be used for branded-stock production. Draft models will be rejected with an error.",
    ],
)

STORAGE = department(
    n=5, name="Fabric & Accessories Storage", role="Storage",
    email="storage@example.com", color="#0d9488",
    pages=["Inventory", "Receive Stock", "Batches", "Suppliers"],
    overview=(
        "Storage receives incoming fabric, accessories, and packaging materials, performs quality "
        "control on the batch, and issues materials to the production floor when Cutting begins. "
        "Every batch is tracked with a unique batch number for traceability."
    ),
    daily=[
        "Receive incoming deliveries from suppliers.",
        "Record batch details (supplier, color, GSM, width, cost).",
        "Mark the batch QC status (pending, passed, failed).",
        "Issue materials to production via stock transfers.",
        "Investigate any low-stock alerts.",
    ],
    procedures=[
        ("A. Add a new supplier", [
            "(If your role lacks access, ask Admin to create the supplier.)",
            "Use the Suppliers list to add company name, phone, email, and address.",
        ]),
        ("B. Receive a fabric batch", [
            "Sidebar → <b>Inventory → Receive Stock</b>.",
            "Pick the item from the dropdown (e.g. <i>FAB-COT-001 — Cotton Jersey</i>).",
            "Enter a unique batch number (e.g. <i>B-COT-202604</i>).",
            "Pick the supplier.",
            "Fill color, width (cm), GSM, quantity, unit (meter / kg / roll), and cost per unit.",
            "Pick the destination warehouse (typically <i>Fabric Storage</i>).",
            "Set QC status to <i>passed</i> if inspection is complete.",
            "Click <b>Receive</b>. The batch appears under <i>Inventory → Batches</i> and inventory totals update.",
        ]),
        ("C. Transfer or issue stock", [
            "When Cutting requests fabric, you record an issue movement.",
            "Sidebar → <b>Inventory</b> (transfer screen). Choose movement type <i>issue</i> or <i>transfer</i>.",
            "Select item, source warehouse, destination warehouse, quantity, and unit.",
            "Save. Stock totals reflect the move immediately.",
        ]),
        ("D. Investigate stock levels", [
            "Sidebar → <b>Inventory</b> to see current on-hand stock per item.",
            "Use <b>Batches</b> to drill into individual lots, their QC status, and remaining quantity.",
        ]),
    ],
    tips=[
        "Always record the supplier when receiving. Finance uses supplier-linked batches to compute material cost and supplier debts.",
        "Use meaningful batch numbers that include item code and date (e.g. <i>B-COT-202604-01</i>) for easy tracing later.",
    ],
    warns=[
        "Do not mark a batch as <i>QC passed</i> until physical inspection is complete. Once passed, the batch becomes available for production and any defect later will be traced back to your decision via the audit log.",
    ],
)

CUTTING = department(
    n=6, name="Fabric Cutting Department", role="Cutting",
    email="cutting@example.com", color="#dc2626",
    pages=["Work Orders", "Cutting screen", "Bundles", "Bundle label printing"],
    overview=(
        "Cutting receives fabric from Storage, cuts it according to the spread plan, and groups "
        "the cut pieces into <b>Bundles</b>. Each bundle has a unique ID, barcode, and QR code "
        "printable as a label. Bundles must be scanned when sent to the next department."
    ),
    daily=[
        "Start the day by picking up Cutting work orders.",
        "Cut fabric and record actual quantities cut, passed, and wasted.",
        "Generate bundles (e.g. 50 pieces of M / white).",
        "Print bundle labels and attach to each bundle.",
        "Record fabric waste in the Waste department screen.",
    ],
    procedures=[
        ("A. Open a cutting work order", [
            "Sidebar → <b>Work Orders</b>.",
            "Filter by department <i>Cutting</i>.",
            "Click <b>Cutting →</b> on the work order you will process.",
            "If status is <i>waiting</i>, you may also need to click <b>Start</b> on the Production Order detail page first.",
        ]),
        ("B. Record cutting output and create bundles", [
            "Pick the fabric batch you cut from (dropdown).",
            "Enter input quantity (meters consumed), cut pieces, passed pieces, defective pieces, and waste qty.",
            "In the <b>Bundle plan</b> section, add one row per (color, size, quantity per bundle, count).",
            "Choose <b>→ Sewing</b> or <b>→ Printing</b> as the next destination per bundle line.",
            "Click <b>Save &amp; create bundles</b>. The system creates the bundles, assigns each one a unique barcode and QR code, and shows a printable table.",
        ]),
        ("C. Print bundle labels", [
            "In the created bundles table, click <b>Print</b> on each bundle.",
            "A label window opens with the bundle number, QR code, barcode, model, color, size, quantity, and date.",
            "Click <b>Print</b> in the label window and attach the printed label to the physical bundle.",
        ]),
        ("D. Send bundles to next department", [
            "Sidebar → <b>Scan Bundle</b>.",
            "Scan or type the bundle barcode and press Enter.",
            "Click <b>Send to Printing</b> or <b>Send to Sewing</b> depending on the bundle's plan.",
            "Status changes to <i>sent_to_printing</i> or <i>sent_to_sewing</i>.",
            "The receiving department will scan again on arrival.",
        ]),
        ("E. Record cutting waste", [
            "Sidebar → <b>Waste</b>.",
            "Pick the fabric waste item, source department <i>Cutting</i>, type <i>fabric</i>.",
            "Enter the quantity in kg, an estimated value, and tick <b>Sellable</b> if the waste can be sold.",
            "Click <b>Record waste</b>. The Waste department will receive it.",
        ]),
    ],
    tips=[
        "Bundle quantity is flexible (20, 50, 100). Smaller bundles flow faster but cost more labels.",
        "Always include color and size in every bundle — one bundle = one model, one color, one size.",
    ],
    warns=[
        "Do not send bundles to Sewing without scanning. The next department cannot receive a bundle that was not properly dispatched.",
    ],
)

PRINTING = department(
    n=7, name="Printing Department", role="Printing",
    email="printing@example.com", color="#db2777",
    pages=["Work Orders", "Printing screen", "Scan Bundle"],
    overview=(
        "Printing is optional. It applies prints (screen, sublimation, DTG, etc.) to cut bundles "
        "before they reach Sewing. You receive bundles by scanning, record print output and "
        "rejects, then dispatch passed bundles to Sewing."
    ),
    daily=[
        "Receive incoming bundles by scanning their barcodes.",
        "Run the print process and inspect output.",
        "Record printed quantities, passed pieces, and rejects with defect reasons.",
        "Send passed bundles to Sewing by scanning.",
    ],
    procedures=[
        ("A. Receive a bundle from Cutting", [
            "Sidebar → <b>Scan Bundle</b>.",
            "Scan or type the bundle barcode.",
            "Confirm details on screen (model, color, size, quantity).",
            "Click <b>Receive at Printing</b>. Status becomes <i>received_printing</i>.",
        ]),
        ("B. Record a printing run", [
            "Sidebar → <b>Work Orders</b>, filter by <i>Printing</i>.",
            "Click <b>Printing →</b> on your work order.",
            "Enter input quantity, printed quantity, passed quantity, rejected quantity.",
            "Add print type (screen, DTG, sublimation…) and defect reason if any rejects.",
            "Click <b>Save record</b>.",
        ]),
        ("C. Send passed bundles to Sewing", [
            "Sidebar → <b>Scan Bundle</b>.",
            "Scan the bundle barcode.",
            "Click <b>Send to Sewing</b>. Status becomes <i>sent_to_sewing</i>.",
        ]),
    ],
    tips=[
        "Group bundles of the same print design together to minimize screen changes.",
    ],
    warns=[
        "Rejected pieces must be recorded with a defect reason. The Finance department uses this to compute defect cost.",
    ],
)

SEWING = department(
    n=8, name="Sewing Department", role="Sewing",
    email="sewing@example.com", color="#f97316",
    pages=["Work Orders", "Sewing screen", "Scan Bundle", "Quality checks"],
    overview=(
        "Sewing assembles the cut and (optionally) printed pieces into finished products. "
        "You receive bundles by scanning, sew on assigned lines, perform in-line QC, and pass "
        "completed garments to Packaging. Failed pieces are sent for rework or scrapped."
    ),
    daily=[
        "Receive bundles by scanning at the start of the shift.",
        "Assign bundles to sewing lines.",
        "Record sewn / passed / failed / rework quantities.",
        "Raise quality checks for defective items.",
    ],
    procedures=[
        ("A. Receive a bundle from Cutting or Printing", [
            "Sidebar → <b>Scan Bundle</b>.",
            "Scan or type the barcode.",
            "Click <b>Receive at Sewing</b>. Status becomes <i>received_sewing</i>.",
        ]),
        ("B. Record sewing output", [
            "Sidebar → <b>Work Orders</b>, filter by <i>Sewing</i>.",
            "Click <b>Sewing →</b> on your work order.",
            "Fill: input qty, sewn qty, passed qty, failed qty, rework qty, rejected qty.",
            "Enter the line name (e.g. <i>Line A</i>) and defect reason if any failures.",
            "Click <b>Save record</b>.",
        ]),
        ("C. Submit a quality check", [
            "On the same screen (or via /quality endpoint), record a Quality Check with checked / passed / failed counts, defect type, defect reason, and severity (low / medium / high / critical).",
        ]),
    ],
    tips=[
        "Sewing input cannot exceed cutting (or printing) passed quantity. The ERP enforces this — if you get an error, check upstream numbers first.",
        "Track rework separately so finance can see the true labor cost.",
    ],
    warns=[
        "Do not submit a sewing record with more input than Cutting/Printing passed. The system will reject it and your record will not save.",
    ],
)

PACKAGING = department(
    n=9, name="Packaging Department", role="Packaging",
    email="packaging@example.com", color="#16a34a",
    pages=["Work Orders", "Packaging screen", "Packages"],
    overview=(
        "Packaging takes passed garments from Sewing and groups them into <b>Packages</b> (bag, box, "
        "or carton). Each package normally contains 60 pieces with a mix of sizes of the same model "
        "and color. Each package gets a unique number, barcode, QR code, and a printable label."
    ),
    daily=[
        "Receive sewn garments from Sewing.",
        "Pack into bags / boxes / cartons.",
        "Record packaging output and damaged pieces.",
        "Generate package QR/barcode labels and attach.",
    ],
    procedures=[
        ("A. Record a packaging run", [
            "Sidebar → <b>Work Orders</b>, filter by <i>Packaging</i>.",
            "Click <b>Packaging →</b> on your work order.",
            "Fill input qty, packed qty, damaged qty, and packaging material used.",
            "Click <b>Save packaging record</b>.",
        ]),
        ("B. Create a package with size breakdown", [
            "On the same screen, scroll to <b>New package</b>.",
            "Set color (e.g. <i>white</i>), capacity (default 60), package type (bag / box / carton).",
            "Add one row per size with the quantity, e.g. <i>S=10, M=15, L=20, XL=15</i> (total 60).",
            "Click <b>Create package</b>. A package number, barcode, and QR code are generated.",
            "Click <b>Print label</b> to open the printable label window and send to your label printer.",
        ]),
        ("C. Over-capacity packages (admin override)", [
            "If you legitimately need more than 60 pieces in one package, tick <b>Admin override capacity</b>.",
            "Only users with admin permission can override; others will get an error.",
        ]),
    ],
    tips=[
        "One package = one model + one color, but multiple sizes are allowed and encouraged for shipping mixes.",
        "Use the Scan Package screen to look up any package later and reprint a lost label.",
    ],
    warns=[
        "Packaging input cannot exceed Sewing passed quantity. The system enforces this rule.",
        "Damaged pieces during packaging must be recorded so finished-goods stock is accurate.",
    ],
)

FGS = department(
    n=10, name="Ready Product Storage", role="ReadyStorage",
    email="fgs@example.com", color="#0891b2",
    pages=["Scan Package", "Packages", "Finished Goods", "Shipments"],
    overview=(
        "Ready Product Storage receives finished packages from Packaging by scanning, stores them in "
        "the warehouse, marks them as reserved when Sales requests stock, and ships them to customers "
        "by scanning the package barcode at dispatch."
    ),
    daily=[
        "Receive incoming packages by scanning.",
        "Mark packages as reserved when Sales reserves stock.",
        "Build shipments and ship by scanning.",
        "Mark packages delivered once carrier confirms.",
    ],
    procedures=[
        ("A. Receive packages from Packaging", [
            "Sidebar → <b>Scan Package</b>.",
            "Scan the package barcode.",
            "Click <b>Receive at storage</b>. Status becomes <i>received_in_storage</i> and the package is added to finished-goods stock.",
        ]),
        ("B. Build and ship a shipment", [
            "Sidebar → <b>Shipments</b>.",
            "Pick the sales order to ship and click <b>Create shipment</b>.",
            "Enter the package ID (or scan its number) and click <b>Add package</b>. Repeat for every package in the shipment.",
            "Click <b>Ship</b>. The shipment status becomes <i>shipped</i> and every package status becomes <i>shipped</i>.",
            "When the carrier confirms delivery, click <b>Mark delivered</b>.",
        ]),
        ("C. Handle damaged packages", [
            "Open <b>Scan Package</b>, scan the damaged package.",
            "Click <b>Mark damaged</b>. The package is removed from sellable stock.",
            "Inform Packaging or Sewing of the issue.",
        ]),
    ],
    tips=[
        "The <b>Finished Goods</b> page shows both customer-bound stock and branded available stock in separate sections.",
    ],
    warns=[
        "Do not ship a package that is in status <i>packed</i>. It must first be received in storage so the chain of custody is complete.",
    ],
)

WASTE = department(
    n=11, name="Waste Department", role="Waste",
    email="waste@example.com", color="#a16207",
    pages=["Waste Dashboard"],
    overview=(
        "Waste is generated mostly by Cutting (fabric scraps) and to a lesser extent by Sewing "
        "defects, packaging damage, and accessories. You receive waste from the source departments, "
        "categorize it as sellable or non-sellable, sell sellable waste, and request management "
        "approval before disposing of non-sellable waste."
    ),
    daily=[
        "Receive new waste records from production.",
        "Sell sellable waste to recyclers / buyers.",
        "Request management approval to dispose of non-sellable waste.",
        "Mark waste as disposed once approval is granted.",
    ],
    procedures=[
        ("A. Receive a waste record", [
            "Sidebar → <b>Waste Dashboard</b>.",
            "Find rows in status <i>recorded</i>.",
            "Click <b>Receive</b>. Status becomes <i>received_by_waste_department</i>.",
        ]),
        ("B. Sell sellable waste", [
            "After receiving, the <b>Sell</b> action appears for sellable rows.",
            "Click it (or use the API to provide custom buyer / unit price).",
            "A WasteSale entry is created with total amount = qty × unit price.",
            "Status becomes <i>sold</i>.",
        ]),
        ("C. Request disposal of non-sellable waste", [
            "Click <b>Request disposal</b> on a non-sellable, received row.",
            "Enter a reason in the request form.",
            "Status changes to <i>pending_disposal_approval</i> and Management is notified.",
        ]),
        ("D. Confirm disposal", [
            "Once Management approves, the waste status becomes <i>disposal_approved</i>.",
            "After the physical disposal, mark it <i>disposed</i> (via the disposal request action).",
        ]),
    ],
    tips=[
        "Always set <b>Sellable</b> accurately when waste is first recorded. The flag drives the entire workflow.",
        "Attach a proof file (photo, certificate) to disposal requests where regulations require it.",
    ],
    warns=[
        "Non-sellable waste cannot be disposed without management approval. Trying to skip this step blocks the workflow.",
    ],
)

FINANCE = department(
    n=12, name="Finance Department", role="Finance",
    email="finance@example.com", color="#15803d",
    pages=["Finance Dashboard", "Invoices", "Payments", "Audit Logs (read)"],
    overview=(
        "Finance reads numbers from the system rather than entering production data. You generate "
        "invoices against sales orders, record customer payments, and review cost / profit reports "
        "that aggregate material cost, waste cost, waste income, and revenue."
    ),
    daily=[
        "Check the finance dashboard for revenue, payments, branded stock value, and waste totals.",
        "Issue invoices for shipped sales orders.",
        "Record incoming customer payments.",
        "Review profit per client order.",
        "Reconcile any discrepancies via the audit log.",
    ],
    procedures=[
        ("A. Create an invoice", [
            "Use the API or a dedicated UI screen: POST <code>/api/finance/invoices</code> with <code>{ sales_order_id, amount }</code>.",
            "The invoice number is generated automatically (e.g. <i>INV-2026-000001</i>) and status starts as <i>unpaid</i>.",
        ]),
        ("B. Record a payment", [
            "POST <code>/api/finance/payments</code> with <code>{ invoice_id, amount, payment_method, notes }</code>.",
            "The invoice status auto-updates to <i>partially_paid</i> or <i>paid</i> when the total reaches the invoice amount.",
        ]),
        ("C. Review profit on an order", [
            "GET <code>/api/finance/order-profit/&lt;sales_order_id&gt;</code> returns revenue, material cost, waste cost, and gross profit.",
            "Use this to validate margins before quoting similar orders.",
        ]),
        ("D. Review branded stock value", [
            "Sidebar → <b>Finance Dashboard</b> → see <i>Branded stock value</i> card.",
            "This is the cost-basis value of unsold branded inventory and rolls up on inventory changes automatically.",
        ]),
    ],
    tips=[
        "Branded-stock profit is recognized only after the item is sold via a branded-stock sale; before that, the value sits as inventory.",
        "Use the Audit Log (Admin section) to trace who issued a discount or modified a price.",
    ],
    warns=[
        "Do not edit production records directly. Cost reports rely on the original quantities; manual edits will break audit traceability.",
    ],
)

HR = department(
    n=13, name="HR Department", role="HR",
    email="hr@example.com", color="#7c2d12",
    pages=["Employees"],
    overview=(
        "HR maintains the employee directory: department assignment, position, salary, and status. "
        "Future modules will track attendance, overtime, operator efficiency, and bonuses."
    ),
    daily=[
        "Onboard new employees.",
        "Update salaries, positions, and statuses.",
        "Coordinate with Admin to link employees to ERP user accounts.",
    ],
    procedures=[
        ("A. Add a new employee", [
            "Sidebar → <b>Employees</b>.",
            "Fill full name, position, phone, salary, department.",
            "Click <b>Add</b>. The employee appears in the table below.",
        ]),
        ("B. Edit or deactivate an employee", [
            "Open the employee record (PATCH endpoint or future UI).",
            "Change status to <i>inactive</i> on termination — historical records remain intact.",
        ]),
        ("C. Link to a system user", [
            "Ask the Admin to create a User account (via Admin → Users) with the employee's email.",
            "Set the User's <code>employee_id</code> reference if your workflow requires it.",
        ]),
    ],
    tips=[
        "Keep department assignments accurate — operator performance reports filter by department.",
    ],
)

ADMIN = department(
    n=14, name="Management / Admin", role="Admin / Management",
    email="admin@example.com, mgr@example.com", color="#7e22ce",
    pages=["All pages", "Admin → Users / Departments / Audit Logs", "Management dashboard"],
    overview=(
        "Admin has full access to every page and endpoint. Management has read access to dashboards "
        "and approves models, waste disposal requests, and overrides (e.g. package over-capacity)."
    ),
    daily=[
        "Approve new models from Modeling.",
        "Approve waste disposal requests.",
        "Create / disable user accounts and assign roles.",
        "Monitor dashboards for late orders, defects, waste, and finance health.",
        "Review the audit log for unusual activity.",
    ],
    procedures=[
        ("A. Create a user account", [
            "Sidebar → <b>Admin → Users</b>.",
            "Fill name, email, password, pick role and department.",
            "Click <b>Create</b>. The new user can immediately log in.",
        ]),
        ("B. Approve a model", [
            "Sidebar → <b>Models</b>.",
            "Click <b>Approve</b> on the model row. Status becomes <i>approved</i> and it becomes available to Planning for branded production.",
        ]),
        ("C. Approve a waste disposal request", [
            "Use the API: POST <code>/api/waste/disposal/&lt;id&gt;/approve</code>.",
            "After approval, the Waste department can mark the waste disposed.",
        ]),
        ("D. Override package capacity", [
            "Only admins can tick <b>Admin override capacity</b> when creating a package over 60 pcs or mixing multiple models/colors.",
        ]),
        ("E. Review audit logs", [
            "Sidebar → <b>Admin → Audit Logs</b>.",
            "Each row shows: when, who, what action, on which entity, and the value JSON.",
            "Use it to investigate disputes or mistakes.",
        ]),
    ],
    tips=[
        "Use a separate Management account for approvals — keep Admin (full power) for system administration only.",
        "Disable demo accounts (sales@example.com etc.) in production via Admin → Users.",
    ],
    warns=[
        "Admin has unrestricted access. Limit how many people hold the Admin role.",
    ],
)


# ---------------------------------------------------------------------------
# Section: Troubleshooting
# ---------------------------------------------------------------------------

def section_troubleshooting():
    return [
        Paragraph("15. Troubleshooting &amp; FAQ", H1),

        Paragraph("Login fails / bounces back to login page", H2),
        Paragraph(
            "Check that your account is active (Admin → Users). Clear browser cache or open an "
            "incognito window. Verify the API is reachable at /api/auth/me using browser DevTools.",
            BODY,
        ),

        Paragraph("\"Sewing input exceeds upstream passed quantity\"", H2),
        Paragraph(
            "The number you entered as <i>input_qty</i> in Sewing is higher than the total passed "
            "quantity from Cutting (or Printing). Either reduce your input or ask Cutting/Printing "
            "to record more passed pieces first.",
            BODY,
        ),

        Paragraph("\"Package quantity exceeds capacity 60. Admin override required\"", H2),
        Paragraph(
            "The default package holds 60 pieces. To pack more, an admin user must tick <b>Admin "
            "override capacity</b> when creating the package.",
            BODY,
        ),

        Paragraph("Branded production rejected with \"requires an approved model\"", H2),
        Paragraph(
            "Branded-stock production can only use models in status <i>approved</i>. Open the model "
            "in Modeling, complete its BOM, and have Management approve it.",
            BODY,
        ),

        Paragraph("Bundle cannot be received at the next department", H2),
        Paragraph(
            "The bundle must first be sent from the previous department. Use the Scan Bundle screen "
            "in the sending department, then re-scan in the receiving department.",
            BODY,
        ),

        Paragraph("Reserve stock returns shortages", H2),
        Paragraph(
            "For branded-stock sales, the ERP reserves what's available and returns the gap as a "
            "shortage. Forward the shortage to Planning to schedule additional branded production.",
            BODY,
        ),

        Paragraph("Label window does not open / shows blank", H2),
        Paragraph(
            "Allow popups for the ERP URL in your browser. If popups are blocked, the label will "
            "open in the current tab instead — use the browser's Back button to return.",
            BODY,
        ),

        Paragraph("Who do I contact?", H2),
        bullets([
            "<b>Login / user issues:</b> your Admin.",
            "<b>Material shortages:</b> Planning, then Storage.",
            "<b>Quality issues:</b> log them in your department's QC screen and notify the line supervisor.",
            "<b>Finance discrepancies:</b> the Finance team, supplying the Sales Order or Production Order number.",
        ]),
    ]


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def build():
    out = Path(__file__).parent / "Milana_ERP_Training_Guide.pdf"
    doc = SimpleDocTemplate(
        str(out), pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=22 * mm, bottomMargin=22 * mm,
        title="Milana ERP — Department Training Guide",
        author="Milana ERP",
    )

    story: list = []
    story += cover()
    story += toc()
    story += section_getting_started()
    story += SALES
    story += MODELING
    story += PLANNING
    story += STORAGE
    story += CUTTING
    story += PRINTING
    story += SEWING
    story += PACKAGING
    story += FGS
    story += WASTE
    story += FINANCE
    story += HR
    story += ADMIN
    story += section_troubleshooting()

    doc.build(story, onFirstPage=page_footer, onLaterPages=page_footer)
    print(f"Wrote {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    build()
