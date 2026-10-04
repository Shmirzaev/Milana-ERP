"""PERF40 / PERF35-PURCHASING / PERF39-MODEL: finish the three partial rows.

Each of these rows was blocked on a file its owner did not hold. These tests
pin the behaviour that was actually added, and each one fails against the code
as it stood before the change.
"""
from decimal import Decimal
from uuid import uuid4

import pytest

from app.models import Item, PurchaseOrder, PurchaseOrderLine, Supplier, Employee
from app.tests.conftest import TestSessionLocal


# ---------------------------------------------------------------- PERF40
# The primitive existed; the call site did not. `upload_company_logo` wrote a
# new managed file on every upload and never removed the old one, so replacing
# the company logo leaked the previous image and all its thumbnails forever.


def test_discard_replaced_managed_image_removes_file_and_thumbnails(tmp_path):
    from app.services.image_storage import (
        PREBUILT_THUMBNAIL_SIZES,
        discard_replaced_managed_image,
    )

    root = tmp_path / "model-files"
    (root / "_thumbs").mkdir(parents=True)
    # The managed-name pattern is `<prefix>_<32 hex chars>.webp`.
    name = f"company_logo_{uuid4().hex}.webp"
    image = root / name
    image.write_bytes(b"old-logo")
    # `prebuild_webp_thumbnails` writes `f"{size}_{source_file_name}.webp"`, and
    # `source_file_name` already ends in `.webp` - so the real on-disk thumbnail
    # name carries a doubled extension. Match the writer exactly.
    for size in PREBUILT_THUMBNAIL_SIZES:
        (root / "_thumbs" / f"{size}_{name}.webp").write_bytes(b"thumb")

    url = f"/storage/model-files/{name}"
    assert discard_replaced_managed_image(url, storage_root=root) is True
    assert not image.exists()
    for size in PREBUILT_THUMBNAIL_SIZES:
        assert not (root / "_thumbs" / f"{size}_{name}.webp").exists()


def test_discard_refuses_a_path_outside_the_storage_root(tmp_path):
    from app.services.image_storage import discard_replaced_managed_image

    root = tmp_path / "model-files"
    root.mkdir()
    outside = tmp_path / "elsewhere.webp"
    outside.write_bytes(b"not ours")
    # Traversal must be refused, not followed.
    assert discard_replaced_managed_image(
        "/storage/model-files/../elsewhere.webp", storage_root=root
    ) is False
    assert outside.exists()


def test_discard_refuses_an_unmanaged_url(tmp_path):
    from app.services.image_storage import discard_replaced_managed_image

    root = tmp_path / "model-files"
    root.mkdir()
    assert discard_replaced_managed_image(
        "https://cdn.example.com/logo.png", storage_root=root
    ) is False
    assert discard_replaced_managed_image(None, storage_root=root) is False


# ------------------------------------------------------ PERF35-PURCHASING
# The row was blocked because the orders route accepted no status/limit/offset,
# so the receiving screen could not page and silently showed a truncated list.


@pytest.fixture
def order_batch():
    """More orders than one page holds, so truncation would be observable."""
    marker = uuid4().hex[:8]
    with TestSessionLocal() as db:
        supplier = Supplier(name=f"PERF35-P supplier {marker}")
        db.add(supplier)
        db.flush()
        item = Item(sku=f"PERF35-P-{marker}", name="Perf35 purchasing item",
                    category="material", unit="pcs")
        db.add(item)
        db.flush()
        order_ids = []
        for i in range(7):
            order = PurchaseOrder(po_no=f"PERF35-PO-{marker}-{i:03d}",
                                  supplier_id=supplier.id, status="draft")
            db.add(order)
            db.flush()
            db.add(PurchaseOrderLine(purchase_order_id=order.id, item_id=item.id,
                                     ordered_quantity=Decimal("5"), unit_cost=Decimal("2"),
                                     unit="pcs"))
            order_ids.append(order.id)
        db.commit()
    yield order_ids


def test_orders_route_returns_envelope_with_exact_total(client, auth_headers, order_batch):
    response = client.get("/api/purchasing/orders?limit=3&offset=0", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"items", "total", "limit", "offset"}
    assert len(body["items"]) == 3
    assert body["total"] >= 7
    assert body["limit"] == 3
    assert body["offset"] == 0


def test_orders_pages_reach_rows_past_the_first_page(client, auth_headers, order_batch):
    first = client.get("/api/purchasing/orders?limit=3&offset=0", headers=auth_headers).json()
    second = client.get("/api/purchasing/orders?limit=3&offset=3", headers=auth_headers).json()
    first_ids = {row["id"] for row in first["items"]}
    second_ids = {row["id"] for row in second["items"]}
    assert not (first_ids & second_ids), "pages must not overlap"


def test_orders_status_filter_narrows_page_and_total(client, auth_headers, order_batch):
    response = client.get("/api/purchasing/orders?limit=50&status=draft", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] >= 7
    assert all(row["status"] == "draft" for row in body["items"])

    empty = client.get("/api/purchasing/orders?status=no-such-status", headers=auth_headers).json()
    assert empty["items"] == []
    assert empty["total"] == 0


def test_orders_rejects_hostile_paging_params(client, auth_headers, order_batch):
    assert client.get("/api/purchasing/orders?limit=0", headers=auth_headers).status_code == 422
    assert client.get("/api/purchasing/orders?offset=-1", headers=auth_headers).status_code == 422
    assert client.get("/api/purchasing/orders?limit=99999", headers=auth_headers).status_code == 422


def test_orders_page_still_carries_lines(client, auth_headers, order_batch):
    """The receiving screen resolves `lines` off each order; the page must
    keep the joinedload or every receive dialog breaks."""
    body = client.get("/api/purchasing/orders?limit=1", headers=auth_headers).json()
    assert body["items"], "expected at least one order"
    assert body["items"][0]["lines"], "orders must still be returned with their lines"


# ----------------------------------------------------------- PERF39-MODEL
# The row was blocked because /api/employees had no search, so the model page
# could not bound the employee list it loads for a constructor/designer picker.


@pytest.fixture
def employee_batch():
    with TestSessionLocal() as db:
        for i in range(6):
            db.add(Employee(
                factory_code="MIL",
                employee_no=f"PERF39-{i:03d}",
                full_name=f"Perf39modeller {i:03d}",
                position="Constructor" if i % 2 == 0 else "Designer",
            ))
        db.commit()


def test_employees_unfiltered_still_returns_everything(client, auth_headers, employee_batch):
    """Backward compatibility: with no params this must be the full list."""
    response = client.get("/api/employees", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert isinstance(response.json(), list)
    assert len(response.json()) >= 6


def test_employees_search_narrows_the_list(client, auth_headers, employee_batch):
    response = client.get("/api/employees?q=Perf39modeller%20001", headers=auth_headers)
    assert response.status_code == 200, response.text
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["full_name"] == "Perf39modeller 001"


def test_employees_search_matches_position(client, auth_headers, employee_batch):
    response = client.get("/api/employees?q=Designer", headers=auth_headers)
    assert response.status_code == 200, response.text
    rows = response.json()
    assert rows, "expected the position search to match seeded employees"
    assert all(row.get("position") == "Designer" for row in rows)


def test_employees_limit_bounds_the_list(client, auth_headers, employee_batch):
    response = client.get("/api/employees?limit=2", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert len(response.json()) == 2


def test_employees_rejects_hostile_limit(client, auth_headers, employee_batch):
    assert client.get("/api/employees?limit=0", headers=auth_headers).status_code == 422
    assert client.get("/api/employees?limit=999999", headers=auth_headers).status_code == 422
