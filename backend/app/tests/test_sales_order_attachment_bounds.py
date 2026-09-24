from copy import deepcopy

import pytest

from app.models import AuditLog, SalesOrder
from app.tests.conftest import TestSessionLocal


_STORAGE_PREFIX = "/storage/sales-order-files/"
_MAX_URL_LENGTH = 512
_MAX_NAME_LENGTH = 255
_MAX_CONTENT_TYPE_LENGTH = 128
_MAX_ROWS = 50


def _attachment(file_url=f"{_STORAGE_PREFIX}artwork.pdf", **fields):
    return {"file_url": file_url, **fields}


def _payload(attachments=None, **overrides):
    return {
        "order_type": "client_order",
        "items": [],
        **({"printing_attachments": attachments} if attachments is not None else {}),
        **overrides,
    }


def _write_counts() -> tuple[int, int]:
    with TestSessionLocal() as db:
        return (
            db.query(SalesOrder).count(),
            db.query(AuditLog).filter_by(entity_type="SalesOrder").count(),
        )


@pytest.mark.parametrize(
    "attachment",
    [
        _attachment("https://example.test/artwork.pdf"),
        _attachment(f"{_STORAGE_PREFIX}../secret.pdf"),
        _attachment(f"{_STORAGE_PREFIX}folder/artwork.pdf"),
        _attachment(f"{_STORAGE_PREFIX}folder\\artwork.pdf"),
        _attachment(f"{_STORAGE_PREFIX}artwork.pdf#fragment"),
        _attachment(f"{_STORAGE_PREFIX}{'a' * _MAX_URL_LENGTH}"),
        _attachment(file_name="n" * (_MAX_NAME_LENGTH + 1)),
        _attachment(content_type="t" * (_MAX_CONTENT_TYPE_LENGTH + 1)),
    ],
)
def test_sales_order_create_rejects_invalid_attachment_without_writes(
    client,
    auth_headers,
    attachment,
):
    before = _write_counts()

    response = client.post(
        "/api/sales-orders",
        headers=auth_headers,
        json=_payload([attachment]),
    )

    assert response.status_code == 422, response.text
    assert _write_counts() == before


def test_sales_order_create_rejects_more_than_50_attachments_without_writes(client, auth_headers):
    before = _write_counts()
    attachments = [_attachment(f"{_STORAGE_PREFIX}file-{index}.pdf") for index in range(51)]

    response = client.post(
        "/api/sales-orders",
        headers=auth_headers,
        json=_payload(attachments),
    )

    assert response.status_code == 422, response.text
    assert _write_counts() == before


def test_sales_order_create_accepts_attachment_boundaries_and_resigns_storage_path(client, auth_headers):
    before = _write_counts()
    exact_url = _STORAGE_PREFIX + "a" * (_MAX_URL_LENGTH - len(_STORAGE_PREFIX))
    attachments = [
        _attachment(exact_url, file_name="n" * _MAX_NAME_LENGTH, content_type="t" * _MAX_CONTENT_TYPE_LENGTH),
    ] + [_attachment(f"{_STORAGE_PREFIX}file-{index}.pdf") for index in range(_MAX_ROWS - 1)]

    response = client.post(
        "/api/sales-orders",
        headers=auth_headers,
        json=_payload(attachments),
    )

    assert response.status_code == 201, response.text
    returned = response.json()["printing_attachments"]
    assert len(returned) == _MAX_ROWS
    assert returned[0]["file_url"].startswith(exact_url + "?")
    assert "sig=" in returned[0]["file_url"]
    with TestSessionLocal() as db:
        saved = db.get(SalesOrder, response.json()["id"])
        assert saved.printing_attachments[0]["file_url"] == exact_url
        assert len(saved.printing_attachments) == _MAX_ROWS
    assert _write_counts()[0] == before[0] + 1


def test_sales_order_create_keeps_existing_reference_error_precedence(client, auth_headers):
    before = _write_counts()

    response = client.post(
        "/api/sales-orders",
        headers=auth_headers,
        json=_payload(
            [_attachment("https://example.test/artwork.pdf")],
            customer_id=2_147_483_647,
        ),
    )

    assert response.status_code == 404, response.text
    assert _write_counts() == before


def test_sales_order_attachment_validation_keeps_auth_and_missing_order_precedence(client, auth_headers):
    before = _write_counts()
    invalid = _payload([_attachment("https://example.test/artwork.pdf")])

    unauthenticated = client.post("/api/sales-orders", json=invalid)
    missing = client.patch(
        "/api/sales-orders/2147483647",
        headers=auth_headers,
        json={"printing_attachments": invalid["printing_attachments"]},
    )

    assert unauthenticated.status_code == 401, unauthenticated.text
    assert missing.status_code == 404, missing.text
    assert _write_counts() == before


def test_sales_order_patch_rejects_changed_invalid_attachments_without_writes(client, auth_headers):
    created = client.post("/api/sales-orders", headers=auth_headers, json=_payload())
    assert created.status_code == 201, created.text
    order_id = created.json()["id"]
    old_attachments = [_attachment(legacy_key={"keep": True})]
    with TestSessionLocal() as db:
        db.get(SalesOrder, order_id).printing_attachments = deepcopy(old_attachments)
        db.commit()
    before_counts = _write_counts()

    response = client.patch(
        f"/api/sales-orders/{order_id}",
        headers=auth_headers,
        json={"printing_attachments": [_attachment("https://example.test/new.pdf")]},
    )

    assert response.status_code == 422, response.text
    assert _write_counts() == before_counts
    with TestSessionLocal() as db:
        assert db.get(SalesOrder, order_id).printing_attachments == old_attachments


def test_sales_order_patch_preserves_unchanged_legacy_attachments(client, auth_headers):
    created = client.post("/api/sales-orders", headers=auth_headers, json=_payload())
    assert created.status_code == 201, created.text
    order_id = created.json()["id"]
    legacy = [
        {"file_url": "/legacy/sales-artwork.pdf", "legacy_key": {"retained": True}},
    ]
    with TestSessionLocal() as db:
        db.get(SalesOrder, order_id).printing_attachments = deepcopy(legacy)
        db.commit()

    unrelated = client.patch(
        f"/api/sales-orders/{order_id}",
        headers=auth_headers,
        json={"notes": "Unrelated metadata edit"},
    )
    assert unrelated.status_code == 200, unrelated.text
    with TestSessionLocal() as db:
        assert db.get(SalesOrder, order_id).printing_attachments == legacy

    echoed = [_attachment("/legacy/sales-artwork.pdf?exp=123&sig=legacy")]
    unchanged = client.patch(
        f"/api/sales-orders/{order_id}",
        headers=auth_headers,
        json={"printing_attachments": echoed},
    )
    assert unchanged.status_code == 200, unchanged.text
    with TestSessionLocal() as db:
        assert db.get(SalesOrder, order_id).printing_attachments == legacy
