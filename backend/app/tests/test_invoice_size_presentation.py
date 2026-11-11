"""Invoice display preserves exact sizes and counts in both document formats."""
from copy import deepcopy
from io import BytesIO

from openpyxl import load_workbook
import pytest

from app.models.shipment_invoice_service import invoice_size_labels, render_shipment_invoice
from app.models.shipment_invoice_excel_service import shipment_invoice_workbook


@pytest.mark.parametrize("sizes,expected", [
    ([{"size": " 50 ", "quantity": 2}, {"size": "46", "quantity": 8},
      {"size": "48", "quantity": 4}], ["46 × 8", "48 × 4", "50 × 2"]),
    ([{"size": "3XL", "quantity": 1}, {"size": "XL", "quantity": 2},
      {"size": "S", "quantity": 3}, {"size": "M", "quantity": 4},
      {"size": "2XL", "quantity": 5}], ["S × 3", "M × 4", "XL × 2", "2XL × 5", "3XL × 1"]),
    ([{"size": " 50,46 , 48 ", "aggregate": True, "quantity": 60}],
     ["(46, 48, 50) × 60"]),
    ([{"size": "48–58", "aggregate": True, "quantity": 180}], ["(48–58) × 180"]),
    ([{"size": "L-48", "quantity": 10}, {"size": "S-44", "quantity": 5},
      {"size": "M-46", "quantity": 8}], ["S-44 × 5", "M-46 × 8", "L-48 × 10"]),
    ([{"size": "M", "color": "Red", "quantity": 4},
      {"size": "M", "color": "Blue", "quantity": 6}], ["Blue / M × 6", "Red / M × 4"]),
    ([{"size": "ASSORTED", "quantity": 12}, {"size": None, "quantity": 3}],
     ["ASSORTED × 12", "— × 3"]),
    ([{"size": "   ", "quantity": 3}], ["— × 3"]),
    ([], []),
])
def test_size_labels_are_consistent_sorted_and_do_not_invent_sizes(sizes, expected):
    before = deepcopy(sizes)
    assert invoice_size_labels(sizes) == expected
    assert sizes == before


@pytest.mark.parametrize("language", ["en", "ru", "uz"])
@pytest.mark.parametrize("prices", [True, False])
def test_print_and_excel_share_sizes_ten_pixel_type_and_retained_height(language, prices):
    document = {"shipment_no": "SIZE-QA", "packages_count": 1, "quantity": 60,
                "amount": "120.00", "invoice_layout_version": 2,
                "package_details": [{"package_no": "SIZE-QA", "weight_kg": "2.50"}],
                "lines": [{"package_no": "SIZE-QA", "model_no": "QA", "variant_no": "1",
                           "size_display": "50, 46, 48", "quantity": 60,
                           "unit_price": "2.00", "amount": "120.00"}]}
    before = deepcopy(document)
    html = render_shipment_invoice(document, language, show_prices=prices)
    sheet = load_workbook(BytesIO(shipment_invoice_workbook(document, language, show_prices=prices))).active
    assert '(46, 48, 50) × 60</span>' in html
    assert sheet["E10"].value == "(46, 48, 50) × 60"
    assert '.items{font-size:10px;' in html and '.signatures{' in html
    assert 'height:23.1pt' in html and sheet.row_dimensions[10].height == 23.1
    assert all(sheet.cell(row, col).font.sz == 7.5 for row in (9, 10) for col in range(1, 12))
    assert sheet["A13"].font.sz == sheet["F13"].font.sz == 7.5
    assert sheet["G11"].value == 60 and sheet["K11"].value == (120 if prices else None)
    assert document == before
