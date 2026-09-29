from copy import deepcopy
from datetime import datetime, timedelta, timezone
from io import BytesIO
import pytest

from openpyxl import load_workbook

from app.api.routes.shipments import _invoice_print_details
from app.db.session import SessionLocal
from app.models import LegacyStockReceipt, Package, Shipment, ShipmentScanLog
from app.services.shipment_invoice import build_invoice_rows, render_shipment_invoice
from app.services.shipment_invoice_excel import shipment_invoice_workbook
from app.services.variant_display import format_variant_number
from app.tests.test_shipment_review import dispatch as dispatch, ship


def test_partial_weight_excel_shared_pack_and_literal_text():
    packages = [{"package_no": "A", "quantity": 7, "weight_kg": "12.50"}, {"package_no": "B", "quantity": 3, "weight_kg": None}]
    lines = [{"package_no": "A", "model_no": "=1+1", "description": "First", "size": "48", "quantity": 4, "amount": None},
             {"package_no": "A", "model_no": "OTHER", "size": "50", "quantity": 3, "amount": None},
             {"package_no": "B", "model_no": "LAST", "size": "52", "quantity": 3, "amount": None}]
    document = {"shipment_no": "TEST", "package_details": packages, "lines": lines, "invoice_rows": build_invoice_rows(lines, packages),
                "packages_count": 2, "quantity": 10, "total_weight_kg": None, "known_weight_kg": "12.50", "missing_weight_packages": 1,
                "invoice_layout_version": 2, "finance_posting_status": "pending_price"}
    original = deepcopy(document)
    for lang in ("en", "ru", "uz"):
        html = render_shipment_invoice(document, lang)
        assert html.count('class="numeric">12.50</td>') == 4
        sheet = load_workbook(BytesIO(shipment_invoice_workbook(document, lang))).active
        assert sheet["B10"].value == "=1+1" and sheet["B10"].data_type == "s"
        assert sheet["F13"].value == 2 and sheet["G13"].value == 10
        assert sheet["H13"].value == sheet["I13"].value == 12.5
        assert sheet["H12"].value == "—"
        assert "H10:H11" in sheet.merged_cells
    assert document == original


def test_invoice_scan_order_ignores_detached_and_duplicate_scans(client, auth_headers, dispatch):
    with SessionLocal() as db:
        first = db.get(Package, dispatch["package"])
        receipt = LegacyStockReceipt(source_system="TEST", source_warehouse_id="scan-order", source_record_id="second",
                                     source_checksum="b" * 64, source_payload={"quantity": 1})
        db.add(receipt); db.flush()
        second = Package(package_no="SCAN-SECOND", barcode="SCAN-SECOND", model_id=first.model_id,
                         legacy_receipt_id=receipt.id, color="navy", capacity=60, total_quantity=1, status="packed")
        db.add(second); db.flush()
        start = datetime.now(timezone.utc)
        original_scan = db.query(ShipmentScanLog).filter_by(shipment_id=dispatch["shipment"]).one()
        original_scan.scanned_at = start
        for offset, package, result in [(1, second, "matched"), (2, first, "detached"), (3, first, "matched"), (4, second, "matched")]:
            db.add(ShipmentScanLog(shipment_id=dispatch["shipment"], package_id=package.id, scanned_code=package.barcode,
                                  scan_result=result, scanned_at=start + timedelta(seconds=offset)))
        db.flush()
        document = {"package_details": [{"package_no": first.package_no}, {"package_no": second.package_no}], "lines": []}
        result = _invoice_print_details(db, db.get(Shipment, dispatch["shipment"]), document)
        assert [p["package_no"] for p in result["package_details"]] == [second.package_no, first.package_no]


def test_excel_endpoint_reuses_frozen_invoice_and_does_not_write(client, auth_headers, dispatch):
    base = f'/api/shipments/{dispatch["shipment"]}'
    assert client.get(base + "/invoice.xlsx", headers=auth_headers).status_code == 409
    ship(client, auth_headers, dispatch)
    with SessionLocal() as db:
        before = deepcopy(db.get(Shipment, dispatch["shipment"]).dispatch_snapshot)
    assert client.get(base + "/invoice.xlsx").status_code == 401
    response = client.get(base + "/invoice.xlsx?lang=uz", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert "spreadsheetml.sheet" in response.headers["content-type"]
    sheet = load_workbook(BytesIO(response.content)).active
    assert sheet["G11"].value == 8
    assert sheet["J10"].value == 10 and sheet["K10"].value == sheet["K11"].value == 80
    hidden_excel = client.get(base + "/invoice.xlsx?lang=uz&show_prices=false", headers=auth_headers)
    hidden_sheet = load_workbook(BytesIO(hidden_excel.content)).active
    assert hidden_sheet.max_column == 11 and hidden_sheet["G11"].value == 8
    assert hidden_sheet["J10"].value is hidden_sheet["K10"].value is hidden_sheet["K11"].value is None
    hidden_print = client.get(base + "/invoice/print?lang=uz&show_prices=false", headers=auth_headers)
    assert hidden_print.status_code == 200
    assert "80.00" not in hidden_print.text and "10.00" not in hidden_print.text
    assert 'show_prices=true' in hidden_print.text
    assert client.get(base + "/invoice/print?show_prices=false").status_code == 401
    with SessionLocal() as db:
        assert db.get(Shipment, dispatch["shipment"]).dispatch_snapshot == before


@pytest.mark.parametrize("raw,expected", [
    ("3596", "V-3596"), ("V-5865", "V-5865"), (" v = 0052 ", "V-0052"),
    ("V-V=6135", "V-6135"), ("Ф-2095", "V-Ф-2095"),
    (None, ""), ("", ""), ("—", ""), ("-", ""), ("V-", ""),
])
def test_variant_presentation_is_idempotent(raw, expected):
    assert format_variant_number(raw) == expected
    assert format_variant_number(expected) == expected


@pytest.mark.parametrize("lang", ["en", "ru", "uz"])
@pytest.mark.parametrize("historical", [False, True])
def test_invoice_pdf_excel_share_identity_metadata_notes_and_portrait_layout(lang, historical):
    from app.services.shipment_invoice import LABELS, invoice_notes
    document = {
        "supplier": "Milana Tex", "shipment_no": "SH-2026-000011", "customer": "Customer",
        "sales_order_no": None, "shipped_at": "2026-09-29T06:25:04Z", "warehouse_person": "Storage",
        "transport_details": {"driver_name": "Driver", "vehicle_info": "Truck", "cargo_name": "Carrier", "driver_phone": "Phone"},
        "package_details": [{"package_no": "A", "quantity": 60, "weight_kg": "29.96"}],
        "lines": [{"package_no": "A", "model_no": "PJ1095", "variant_no": "5865", "quantity": 60,
                   "description": "Original", "size": "ASSORTED", "amount": None}],
        "packages_count": 1, "quantity": 60, "invoice_layout_version": 1 if historical else 2,
        "historical_reconstruction": historical, "finance_posting_status": "pending_price",
    }
    original = deepcopy(document)
    html = render_shipment_invoice(document, lang)
    sheet = load_workbook(BytesIO(shipment_invoice_workbook(document, lang))).active
    labels = LABELS[lang]
    assert sheet["A1"].value == "Milana Tex"
    assert sheet["A2"].value == labels["title"]
    assert sheet["A3"].value == "SH-2026-000011"
    assert sheet["A4"].value == labels["shipment"] and sheet["C4"].value == document["shipment_no"]
    assert sheet["A5"].value == labels["date"] and sheet["C5"].value == "29/09/2026 11:25:04"
    assert sheet["C6"].value == "Customer" and sheet["C7"].value == "—"
    assert [sheet.cell(row, 6).value for row in range(4, 8)] == ["Driver", "Truck", "Carrier", "Phone"]
    assert sheet["C10"].value == "V-5865" and "<td>V-5865</td>" in html
    assert sheet.page_setup.orientation == "portrait" and sheet.page_setup.fitToWidth == 1
    assert len(sheet._images) == 1
    values = [cell.value for row in sheet for cell in row]
    for note in invoice_notes(document, lang):
        assert note in values and note in html
    assert f'{labels["issued"]}: Storage' in values and labels["received"] in values
    assert document == original


@pytest.mark.parametrize("lang", ["en", "ru", "uz"])
@pytest.mark.parametrize("price,amount", [("12345.67", "37037.01"), ("0.00", "0.00"), (None, None)])
def test_price_columns_and_hidden_exports_preserve_saved_amounts(lang, price, amount):
    from app.services.shipment_invoice import LABELS
    document = {
        "shipment_no": "PRICE-CHECK", "invoice_layout_version": 2, "packages_count": 1, "quantity": 3,
        "package_details": [{"package_no": "P", "quantity": 3, "weight_kg": "1.25"}],
        "lines": [{"package_no": "P", "model_no": "PJ1", "variant_no": "007", "size": "M", "quantity": 3,
                   "unit_price": price, "amount": amount}],
        "amount": "36500.00", "calculated_amount": amount, "adjustment_reason": "Agreed 36500 total <review>",
    }
    before = deepcopy(document)
    for visible in (True, False):
        html = render_shipment_invoice(document, lang, show_prices=visible)
        sheet = load_workbook(BytesIO(shipment_invoice_workbook(document, lang, show_prices=visible))).active
        assert sheet.max_column == 11
        assert f"<th scope='col'>{LABELS[lang]['price']}</th>" in html
        assert f"<th scope='col'>{LABELS[lang]['amount']}</th>" in html
        assert sheet["J9"].value == LABELS[lang]["price"] and sheet["K9"].value == LABELS[lang]["amount"]
        assert sheet["G11"].value == 3 and sheet["I11"].value == 1.25
        if visible:
            assert sheet["J10"].value == (float(price) if price is not None else "—")
            assert sheet["K10"].value == (float(amount) if amount is not None else "—")
            assert sheet["K11"].value == 36500
            assert "36\u00a0500.00" in html and "&lt;review&gt;" in html
        else:
            assert sheet["J10"].value is sheet["K10"].value is sheet["K11"].value is None
            assert sheet["J10"].border.left.style and sheet["K10"].border.right.style
            assert '<td class="numeric"></td><td class="numeric"></td></tr>' in html
            assert '<td></td><td class="numeric"></td></tr>' in html
            assert "36500" not in html and "36\u00a0500.00" not in html
            assert "Agreed" not in html
            assert not any("Agreed" in str(cell.value) for row in sheet for cell in row)
    assert document == before
