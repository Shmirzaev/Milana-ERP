from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.db.session import SessionLocal
from app.models import LegacyStockReceipt, Model, Package, SalesOrderItem, Shipment
from app.services.shipment_invoice import build_invoice_rows, invoice_model_identity, render_shipment_invoice
from app.tests.test_shipment_review import dispatch as dispatch, ship


def test_transport_metadata_create_update_clear_and_validation(client, auth_headers):
    transport = {"driver_name": "  Driver <name>  ", "vehicle_info": "Truck example", "cargo_name": "Carrier", "driver_phone": "+998 example"}
    created = client.post("/api/shipments", headers=auth_headers, json={"notes": "Warehouse exit", "transport_details": transport})
    assert created.status_code == 201, created.text
    sid = created.json()["id"]
    assert created.json()["transport_details"]["driver_name"] == "Driver <name>"
    base = f"/api/shipments/{sid}"
    changed = client.patch(base, headers=auth_headers, json={"transport_details": {"cargo_name": "New carrier"}})
    assert changed.status_code == 200, changed.text
    assert changed.json()["transport_details"]["driver_name"] is None
    assert changed.json()["transport_details"]["cargo_name"] == "New carrier"
    assert client.patch(base, headers=auth_headers, json={"transport_details": {"password": "invalid"}}).status_code == 422
    assert client.patch(base, headers=auth_headers, json={"transport_details": {"driver_phone": "x" * 51}}).status_code == 422
    assert client.patch(base, headers=auth_headers, json={"transport_details": ["not-object"]}).status_code == 422
    assert client.patch(base, headers=auth_headers, json={"transport_details": None}).status_code == 200
    with SessionLocal() as db:
        assert db.get(Shipment, sid).transport_details is None


def test_dispatch_freezes_reference_fields_transport_weights_and_identity(client, auth_headers, dispatch):
    with SessionLocal() as db:
        package = db.get(Package, dispatch["package"])
        package.weight_kg = Decimal("2.35")
        model = db.get(Model, package.model_id)
        model.code = "PJ1142-V-3599"; model.name = "Cotton garment"; model.details_json = {}
        db.commit()
    base = f'/api/shipments/{dispatch["shipment"]}'
    transport = {"driver_name": "Synthetic driver", "vehicle_info": "Synthetic vehicle", "cargo_name": "Carrier", "driver_phone": "+998 example"}
    assert client.patch(base, headers=auth_headers, json={"transport_details": transport}).status_code == 200
    ship(client, auth_headers, dispatch)
    first = client.get(base + "/invoice", headers=auth_headers).json()
    assert len(first["invoice_rows"]) == 1
    row = first["invoice_rows"][0]
    assert (row["model_no"], row["variant_no"], row["description"]) == ("PJ1142", "V-3599", "Cotton garment")
    assert row["quantity"] == 8 and row["pack_count"] == 1 and Decimal(row["weight_kg"]) == Decimal("2.35")
    assert first["transport_details"] == transport and Decimal(first["total_weight_kg"]) == Decimal("2.35")
    assert client.patch(base, headers=auth_headers, json={"transport_details": {"driver_name": "Changed"}}).status_code == 409
    with SessionLocal() as db:
        package = db.get(Package, dispatch["package"])
        package.weight_kg = 9
        model = db.get(Model, package.model_id)
        model.code = "CHANGED-V-99"; model.name = "Changed name"
        db.get(Shipment, dispatch["shipment"]).transport_details = {"driver_name": "Changed directly"}
        db.commit()
    assert client.get(base + "/invoice", headers=auth_headers).json() == first
    for lang in ["en", "ru", "uz"]:
        html = client.get(base + f"/invoice/print?lang={lang}", headers=auth_headers).text
        assert "Ombor hisob-fakturasi" in html and "Milana Tex" in html
        assert "PJ1142-V-3599" not in html and "PJ1142" in html and "V-3599" in html
        assert "Synthetic driver" in html and "Changed directly" not in html
        assert "48 (4)" in html and "48 (4.00)" not in html


def test_mixed_pack_model_or_price_rows_share_weight_without_proportional_guess():
    common = {"package_no": "MIXED", "model_code": "PJ100-V-1", "model_no": "PJ100", "variant_no": "V-1", "description": "Shirt", "color": "White"}
    lines = [{**common, "size": "48", "quantity": 3, "unit_price": "10.00", "amount": "30.00"},
             {**common, "size": "50", "quantity": 2, "unit_price": "10.00", "amount": "20.00"},
             {**common, "size": "52", "quantity": 1, "unit_price": "12.00", "amount": "12.00"},
             {**common, "model_no": "OTHER", "variant_no": "V-2", "size": "54", "quantity": 2, "unit_price": None, "amount": None}]
    packages = [{"package_no": "MIXED", "quantity": 8, "weight_kg": "2.35"}]
    rows = build_invoice_rows(lines, packages)
    assert len(rows) == 3 and sum(row["quantity"] for row in rows) == 8
    assert sum(row["pack_count"] for row in rows) == 1
    assert [row["weight_kg"] for row in rows] == ["2.35", None, None]
    assert rows[0]["package_rowspan"] == 3 and rows[0]["amount"] == "50.00"
    html = render_shipment_invoice({"shipment_no": "TEST", "lines": lines, "package_details": packages,
        "invoice_rows": rows, "invoice_layout_version": 2, "quantity": 8, "packages_count": 1,
        "amount": "62.00", "total_weight_kg": "2.35", "pricing_complete": False}, "uz")
    assert html.count('rowspan="3"') == 3  # Pack, Kg, Jami Kg; not one weight per model.
    assert "0.78" not in html and "0.79" not in html


def test_legacy_source_identity_unknown_weight_and_prices_remain_explicit(client, auth_headers, dispatch):
    with SessionLocal() as db:
        package = db.get(Package, dispatch["package"])
        model = db.get(Model, package.model_id)
        model.code = "LEGACY-STICKER-INTERNAL"
        model.details_json = {"legacy_import": True}
        model.name = "Warehouse identity"
        receipt = db.get(LegacyStockReceipt, dispatch["receipt"])
        receipt.source_payload = {"model_number": "XJ3142", "article": "V-43", "product": "Legacy garment"}
        line = db.query(SalesOrderItem).filter_by(sales_order_id=dispatch["order"]).one()
        line.color = "Unmatched"; line.size = "Unmatched"
        db.commit()
    base = f'/api/shipments/{dispatch["shipment"]}'
    doc = client.get(base + "/preparation", headers=auth_headers).json()["review"]
    assert doc["amount"] is None and doc["total_weight_kg"] is None
    assert doc["missing_weight_packages"] == 1
    assert doc["invoice_rows"][0]["model_no"] == "XJ3142"
    assert doc["invoice_rows"][0]["variant_no"] == "V-43"
    assert doc["invoice_rows"][0]["description"] == "Legacy garment"
    html = render_shipment_invoice(doc, "en")
    assert "LEGACY-STICKER-INTERNAL" not in html
    assert ">—</td>" in html and "Some package weights are unknown" in html
    assert "Price unavailable" in html


@pytest.mark.parametrize("code,details,expected", [
    ("PJ1142-V-3599", {}, ("PJ1142", "V-3599")),
    ("PJ1142-3599", {}, ("PJ1142", "3599")),
    ("INTERNAL", {"general": {"modelNo": "PJ1142", "variantNo": "V-3599"}}, ("PJ1142", "V-3599")),
    ("LEGACY-STICKER-X", {"legacy_original_model_no": "XJ3142", "legacy_original_variant_no": "V-43"}, ("XJ3142", "V-43")),
])
def test_invoice_model_identity_respects_catalog_and_legacy_conventions(code, details, expected):
    assert invoice_model_identity(SimpleNamespace(code=code, details_json=details)) == expected
