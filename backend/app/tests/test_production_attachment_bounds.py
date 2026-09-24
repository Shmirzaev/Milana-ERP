import base64
from copy import deepcopy

import pytest

from app.models import AuditLog, BrandedPlanningOrder, ProductionOrder
from app.tests.conftest import TestSessionLocal


_STORAGE_PREFIX = "/storage/sales-order-files/"


def _attachment(file_url=f"{_STORAGE_PREFIX}po_print_0123456789abcdef0123456789abcdef.pdf", **fields):
    return {"file_url": file_url, **fields}


def _branded_payload(attachments):
    return {
        "production_type": "branded_stock",
        "model_id": 1,
        "planned_quantity": 1,
        "printing_attachments": attachments,
        "items": [{"model_id": 1, "color": "white", "size": "M", "planned_quantity": 1}],
    }


def _write_counts():
    with TestSessionLocal() as db:
        return {
            "production_orders": db.query(ProductionOrder).count(),
            "planning_orders": db.query(BrandedPlanningOrder).count(),
            "audit_rows": db.query(AuditLog).count(),
        }


@pytest.mark.parametrize(
    "bad_attachment",
    [
        _attachment("https://example.test/artwork.pdf"),
        _attachment(f"{_STORAGE_PREFIX}../secret.pdf"),
        _attachment(f"{_STORAGE_PREFIX}folder/artwork.pdf"),
        _attachment(f"{_STORAGE_PREFIX}folder\\artwork.pdf"),
        _attachment(f"{_STORAGE_PREFIX}artwork.pdf#fragment"),
        _attachment(f"{_STORAGE_PREFIX}artwork.pdf?sig=token#fragment"),
        _attachment(f"{_STORAGE_PREFIX}{'a' * 490}"),
        _attachment(f"{_STORAGE_PREFIX}artwork.pdf?sig={'a' * 600}"),
        _attachment(file_name="n" * 256),
        _attachment(content_type="t" * 129),
    ],
)
def test_production_order_create_rejects_invalid_attachment_without_writes(client, auth_headers, bad_attachment):
    before = _write_counts()

    response = client.post(
        "/api/production-orders",
        json=_branded_payload([bad_attachment]),
        headers=auth_headers,
    )

    assert response.status_code == 422, response.text
    assert _write_counts() == before


def test_production_order_create_rejects_more_than_50_attachments_without_writes(client, auth_headers):
    before = _write_counts()
    attachments = [_attachment(f"{_STORAGE_PREFIX}file-{index}.pdf") for index in range(51)]

    response = client.post(
        "/api/production-orders",
        json=_branded_payload(attachments),
        headers=auth_headers,
    )

    assert response.status_code == 422, response.text
    assert _write_counts() == before


def test_branded_planning_create_validates_before_planning_order_write(client, auth_headers):
    before = _write_counts()

    response = client.post(
        "/api/planning/create-branded-production",
        json=_branded_payload([_attachment("https://example.test/artwork.pdf")]),
        headers=auth_headers,
    )

    assert response.status_code == 422, response.text
    assert _write_counts() == before


def test_production_order_patch_rejects_invalid_change_without_writes(client, auth_headers):
    created = client.post(
        "/api/planning/create-branded-production",
        json=_branded_payload([_attachment()]),
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    order_id = created.json()["id"]
    before_counts = _write_counts()
    with TestSessionLocal() as db:
        before_attachments = deepcopy(db.get(ProductionOrder, order_id).printing_attachments)

    response = client.patch(
        f"/api/production-orders/{order_id}",
        json={"printing_attachments": [_attachment(f"{_STORAGE_PREFIX}../changed.pdf")]},
        headers=auth_headers,
    )

    assert response.status_code == 422, response.text
    assert _write_counts() == before_counts
    with TestSessionLocal() as db:
        assert db.get(ProductionOrder, order_id).printing_attachments == before_attachments


def test_patch_preserves_unchanged_legacy_attachments_and_unknown_keys(client, auth_headers):
    created = client.post(
        "/api/planning/create-branded-production",
        json=_branded_payload([]),
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    order_id = created.json()["id"]
    legacy = [
        {"file_url": f"/legacy/old-{index}.pdf", "legacy_key": {"index": index}}
        for index in range(51)
    ]
    with TestSessionLocal() as db:
        db.get(ProductionOrder, order_id).printing_attachments = deepcopy(legacy)
        db.commit()

    unrelated = client.patch(
        f"/api/production-orders/{order_id}",
        json={"printing_instructions": "Updated instructions"},
        headers=auth_headers,
    )
    assert unrelated.status_code == 200, unrelated.text
    with TestSessionLocal() as db:
        assert db.get(ProductionOrder, order_id).printing_attachments == legacy

    echoed = [{"file_url": f"{row['file_url']}?exp=123&sig=legacy"} for row in legacy]
    echoed_update = client.patch(
        f"/api/production-orders/{order_id}",
        json={"printing_attachments": echoed},
        headers=auth_headers,
    )
    assert echoed_update.status_code == 200, echoed_update.text
    with TestSessionLocal() as db:
        assert db.get(ProductionOrder, order_id).printing_attachments == legacy


def test_production_order_create_accepts_all_attachment_boundaries(client, auth_headers):
    exact_url = _STORAGE_PREFIX + "a" * (512 - len(_STORAGE_PREFIX))
    attachments = [
        _attachment(
            exact_url,
            file_name="n" * 255,
            content_type="t" * 128,
        ),
    ] + [_attachment(f"{_STORAGE_PREFIX}file-{index}.pdf") for index in range(49)]

    response = client.post(
        "/api/production-orders",
        json=_branded_payload(attachments),
        headers=auth_headers,
    )

    assert response.status_code == 201, response.text
    assert len(response.json()["printing_attachments"]) == 50
    assert response.json()["printing_attachments"][0]["file_url"] == exact_url


def test_signed_upload_path_is_stored_bare_and_resigned_on_read(client, auth_headers):
    upload = client.post(
        "/api/production-orders/printing-attachments/upload",
        files={"file": ("attachment.png", _VALID_PNG, "image/png")},
        headers=auth_headers,
    )
    assert upload.status_code == 201, upload.text
    uploaded = upload.json()
    assert "sig=" in uploaded["file_url"]

    created = client.post(
        "/api/planning/create-branded-production",
        json=_branded_payload([uploaded]),
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    bare_path = uploaded["file_url"].split("?", 1)[0]
    assert created.json()["printing_attachments"][0]["file_url"] == bare_path

    read_back = client.get(f"/api/production-orders/{created.json()['id']}", headers=auth_headers)
    assert read_back.status_code == 200, read_back.text
    assert read_back.json()["printing_attachments"][0]["file_url"].startswith(bare_path + "?")
    assert "sig=" in read_back.json()["printing_attachments"][0]["file_url"]


_VALID_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)
