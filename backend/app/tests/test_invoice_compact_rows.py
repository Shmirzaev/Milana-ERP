"""Shipment Excel item heights remain compact across different pack selections."""
from copy import deepcopy
from io import BytesIO

from openpyxl import load_workbook
import pytest

from app.models.shipment_invoice_excel_service import shipment_invoice_workbook
from app.models.shipment_invoice_service import build_invoice_rows, render_shipment_invoice


def compact_document(description, package_count):
    packages = [{"package_no": f"PACK-{index}", "quantity": 6, "weight_kg": "2.50"}
                for index in range(package_count)]
    lines = [{"package_no": package["package_no"], "model_no": f"MODEL-{index}",
              "variant_no": "4678", "description": description if index == 0 else "Туника 3/4",
              "size": "48", "quantity": 6, "unit_price": "8.30", "amount": "49.80"}
             for index, package in enumerate(packages)]
    # A split pack must keep its existing shared quantity/weight cells.
    lines[0].update(model_no="=1+1", quantity=4, amount="33.20")
    lines.insert(1, {**lines[0], "model_no": "OTHER", "description": "Other model", "quantity": 2, "amount": "16.60"})
    return {"shipment_no": "COMPACT-QA", "package_details": packages, "lines": lines,
            "invoice_rows": build_invoice_rows(lines, packages), "invoice_layout_version": 2,
            "packages_count": package_count, "quantity": package_count * 6,
            "total_weight_kg": str(package_count * 2.5), "amount": str(package_count * 49.8)}


@pytest.mark.parametrize("language", ["en", "ru", "uz"])
@pytest.mark.parametrize("prices", [True, False])
def test_compact_height_is_independent_of_description_and_pack_selection(language, prices):
    for package_count in (3, 100):
        for description in ("Халат", 'Халат "Большая пуговица" Великан — длинное описание модели ' * 4):
            document = compact_document(description, package_count)
            before = deepcopy(document)
            html_before = render_shipment_invoice(document, language, show_prices=prices)
            sheet = load_workbook(BytesIO(shipment_invoice_workbook(document, language, show_prices=prices))).active
            rows = document["invoice_rows"]
            assert {sheet.row_dimensions[row].height for row in range(10, 10 + len(rows))} == {24}
            for row in range(10, 10 + len(rows)):
                for cell in sheet[row][:11]:
                    if cell.value is not None:
                        assert not cell.alignment.wrap_text  # XLSX omits false alignment flags.
                        assert not cell.alignment.shrink_to_fit
                        assert cell.font.sz == 10
            assert sheet["D10"].value == description
            assert sheet["B10"].value == "=1+1" and sheet["B10"].data_type == "s"
            assert sheet["G10"].value == 4 and sheet["G10"].data_type == "n"
            assert sheet["H10"].value == 2.5 and sheet["H10"].number_format == '#,##0.00'
            assert {"F10:F11", "H10:H11", "I10:I11"} <= {str(merged) for merged in sheet.merged_cells}
            total = 10 + len(rows)
            assert sheet.cell(total, 6).value == package_count
            assert sheet.cell(total, 7).value == package_count * 6
            assert sheet.cell(total, 11).value == (pytest.approx(package_count * 49.8) if prices else None)
            assert document == before
            assert render_shipment_invoice(document, language, show_prices=prices) == html_before


def test_description_width_follows_longest_text_instead_of_other_columns():
    from app.models.shipment_invoice_service import invoice_column_widths
    from openpyxl.utils import get_column_letter

    document = compact_document('Пижама "Новый Год"', 3)
    previous = invoice_column_widths(document["invoice_rows"])
    for index in range(4, 11):
        previous[index] *= 10 / 7.5
    sheet = load_workbook(BytesIO(shipment_invoice_workbook(document, "ru"))).active
    widths = [sheet.column_dimensions[get_column_letter(column)].width for column in range(1, 12)]
    assert widths[:3] == previous[:3]
    assert 14 <= widths[3] < 30
    assert all(widths[index] < previous[index] for index in range(4, 11))
    longer = deepcopy(document)
    longer['invoice_rows'][-1]['description'] = 'Халат "Большая пуговица" Великан с длинным рукавом'
    longer_sheet = load_workbook(BytesIO(shipment_invoice_workbook(longer, "ru"))).active
    assert longer_sheet.column_dimensions['D'].width > widths[3]
    # An unrelated size breakdown must not add spare width to the description.
    document['invoice_rows'][0]['sizes'] = [{'size': ' / '.join(str(n) for n in range(40, 80)), 'quantity': 6}]
    sizes_sheet = load_workbook(BytesIO(shipment_invoice_workbook(document, "ru"))).active
    assert sizes_sheet.column_dimensions['D'].width == widths[3]
    assert sizes_sheet.column_dimensions['E'].width > widths[4]


def test_description_width_measures_glyphs_not_just_character_count():
    def width(description):
        document = compact_document(description, 1)
        document['invoice_rows'][1]['description'] = ''
        return load_workbook(BytesIO(shipment_invoice_workbook(document, 'en'))).active.column_dimensions['D'].width

    assert width('W' * 30) > width('i' * 30)
