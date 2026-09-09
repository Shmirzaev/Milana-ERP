import base64
from io import BytesIO
from urllib.parse import quote

from PIL import Image
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.session import SessionLocal
from app.main import app
from app.models import Bundle, CuttingRecord, ProductionOrder, WorkOrder
from app.services import barcode
from app.services.bundles import bundle_qr_payload
from app.services.cutting_sheet import render_cutting_sheet_html
from app.tests.test_production_flow import _create_bundle_for_scan


def test_bundle_image_and_print_use_canonical_order_keep_old_scan_identity(client, auth_headers, monkeypatch):
    bundle = _create_bundle_for_scan(client, auth_headers)
    bid = bundle["id"]
    image_url = f"/api/barcode/bundle-image/{bid}"
    assert bundle["qr_code_url"] == image_url
    with SessionLocal() as db:
        saved = db.get(Bundle, bid)
        po = db.get(ProductionOrder, saved.production_order_id)
        po.production_no = "PO-2026-000202"
        saved.qr_code_url = "/storage/barcodes/old-bundle-snapshot.png"
        db.commit()
        old_payload = bundle_qr_payload(db, saved)
    old_image = client.get(image_url, headers=auth_headers)
    assert old_image.status_code == 200
    encoded_payloads = []
    original_add_data = barcode.qrcode.QRCode.add_data

    def capture_data(qr, data, *args, **kwargs):
        encoded_payloads.append(data)
        return original_add_data(qr, data, *args, **kwargs)

    monkeypatch.setattr(barcode.qrcode.QRCode, "add_data", capture_data)
    with SessionLocal() as db:
        po = db.get(ProductionOrder, bundle["production_order_id"])
        po.production_no = "PO-0202"  # Result of the canonical-reference migration.
        db.commit()
        expected = bundle_qr_payload(db, db.get(Bundle, bid))
    assert expected == f"BUNDLE:{bundle['bundle_no']}|{bundle['barcode']}|PO:PO-0202"
    canonical = client.get(image_url, headers=auth_headers)
    assert canonical.status_code == 200
    assert canonical.headers["content-type"] == "image/png"
    assert canonical.headers["cache-control"] == "private, no-store"
    assert encoded_payloads == [expected]
    assert canonical.content != old_image.content
    image = Image.open(BytesIO(canonical.content))
    assert image.format == "PNG" and image.width == image.height and image.width > 100
    assert canonical.content == barcode.qr_png_bytes(expected)

    detail = client.get(f"/api/bundles/{bid}", headers=auth_headers)
    lookup = client.get(f"/api/barcode/bundle/{bundle['bundle_no']}", headers=auth_headers)
    assert detail.json()["qr_code_url"] == lookup.json()["qr_code_url"] == image_url
    encoded_payloads.clear()
    printed = client.get(f"/api/bundles/{bid}/label", headers=auth_headers)
    assert printed.status_code == 200
    assert encoded_payloads == [expected]
    assert "PO-2026-000202" not in printed.text
    assert base64.b64encode(canonical.content).decode() in printed.text
    # Printing/image GETs do not mutate the bundle or rewrite old static files.
    with SessionLocal() as db:
        saved = db.get(Bundle, bid)
        assert saved.qr_code_url == "/storage/barcodes/old-bundle-snapshot.png"
        assert saved.bundle_no == bundle["bundle_no"] and saved.barcode == bundle["barcode"]
    # Existing physical labels still resolve through their original bundle/barcode.
    for payload in (old_payload, expected):
        resolved = client.get(f"/api/bundles/lookup?code={quote(payload, safe='')}", headers=auth_headers)
        assert resolved.status_code == 200 and resolved.json()["id"] == bid


def test_bundle_image_works_with_browser_cookie_and_requires_auth(client, auth_headers):
    bundle = _create_bundle_for_scan(client, auth_headers)
    image_url = bundle["qr_code_url"]
    token = auth_headers["Authorization"].removeprefix("Bearer ")
    with TestClient(app) as browser:
        assert browser.get(image_url).status_code == 401
        browser.cookies.set(settings.AUTH_COOKIE_NAME, token)
        assert browser.get(image_url).status_code == 200
        assert browser.get("/api/barcode/bundle-image/2147483647").status_code == 404


def test_cutting_sheet_renders_current_canonical_reference(client, auth_headers):
    bundle = _create_bundle_for_scan(client, auth_headers)
    with SessionLocal() as db:
        po = db.get(ProductionOrder, bundle["production_order_id"])
        po.production_no = "PO-0202"
        work = db.query(WorkOrder).filter_by(production_order_id=po.id, operation="cutting").first()
        record = CuttingRecord(work_order_id=work.id, cut_pieces=50, passed_pieces=50)
        db.add(record)
        db.flush()
        sheet = render_cutting_sheet_html(db, record, [bundle["id"]])
        assert po.order_no in sheet
        assert "PO-2026-000202" not in sheet
