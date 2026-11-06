"""Shared create/update attachment storage retains nullable metadata."""
from urllib.parse import parse_qs, urlsplit

import pytest

from app.core.signing import verify_path
from app.db.session import SessionLocal
from app.libs.dto.sales.sales_order_input import SalesOrderPrintingAttachment
from app.models.sales.orders_service import _attachments_for_storage
from app.schemas import SalesOrder
from app.tests.test_sales_update_old_behavior import seed


@pytest.mark.parametrize("metadata", [{}, {"file_name": None, "content_type": None}])
@pytest.mark.parametrize("operation", ["create", "update"])
def test_attachment_metadata_survives_create_and_update(client, auth_headers, metadata, operation):
    path = "/storage/sales-order-files/nullable.png"
    attachment = {"file_url": path + "?exp=1&sig=expired", **metadata}
    if operation == "create":
        response = client.post("/api/sales-orders", headers=auth_headers,
                               json={"printing_attachments": [attachment]})
        expected_status = 201
    else:
        order_id = seed(SessionLocal)[0]
        response = client.patch(f"/api/sales-orders/{order_id}", headers=auth_headers,
                                json={"printing_attachments": [attachment]})
        expected_status = 200
    assert response.status_code == expected_status, response.text
    body = response.json()
    received = body["printing_attachments"][0]
    assert received["file_name"] is None and received["content_type"] is None
    signed = urlsplit(received["file_url"])
    query = parse_qs(signed.query)
    assert signed.path == path and verify_path(path, query["exp"][0], query["sig"][0])
    with SessionLocal() as db:
        stored = db.get(SalesOrder, body["id"]).printing_attachments
        assert stored == [{"file_url": path, "file_name": None, "content_type": None}]


def test_empty_url_and_null_list_keep_existing_storage_shape():
    assert _attachments_for_storage(None) == []
    assert _attachments_for_storage([SalesOrderPrintingAttachment(file_url="")]) == [
        {"file_url": "", "file_name": None, "content_type": None}
    ]
