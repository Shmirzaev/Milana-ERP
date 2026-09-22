from uuid import uuid4

from app.models import Item, PurchaseRequest, PurchaseRequestLine
from app.tests.conftest import TestSessionLocal


def _purchase_requests(count: int) -> tuple[list[int], int]:
    marker = uuid4().hex[:8]
    with TestSessionLocal() as db:
        baseline = db.query(PurchaseRequest).count()
        item = db.query(Item).order_by(Item.id).first()
        assert item is not None
        requests = [
            PurchaseRequest(
                request_no=f"PERF35-PR-{marker}-{index:04d}",
                status="pending_approval",
                notes=f"pagination row {index}",
            )
            for index in range(count)
        ]
        db.add_all(requests)
        db.flush()
        db.add_all(
            [
                PurchaseRequestLine(
                    purchase_request_id=request.id,
                    item_id=item.id,
                    required_quantity=1,
                    requested_quantity=1,
                    unit=item.unit,
                    available_quantity=0,
                    shortage_quantity=1,
                )
                for request in requests
            ]
        )
        db.commit()
        return [int(request.id) for request in requests], baseline


def test_purchase_request_pages_bound_rows_and_preserve_legacy_array(client, auth_headers):
    created_ids, baseline = _purchase_requests(205)
    expected_total = baseline + len(created_ids)

    first = client.get(
        "/api/purchasing/requests?page=1&page_size=100",
        headers=auth_headers,
    )
    assert first.status_code == 200, first.text
    first_page = first.json()
    assert first_page["total"] == expected_total
    assert first_page["page"] == 1
    assert first_page["page_size"] == 100
    assert first_page["has_more"] is True
    assert len(first_page["rows"]) == 100
    assert [row["id"] for row in first_page["rows"][:3]] == list(reversed(created_ids[-3:]))
    assert all(len(row["lines"]) == 1 for row in first_page["rows"])

    final_page_number = (expected_total + 99) // 100
    final = client.get(
        f"/api/purchasing/requests?page={final_page_number}&page_size=100",
        headers=auth_headers,
    )
    assert final.status_code == 200, final.text
    final_page = final.json()
    assert final_page["page"] == final_page_number
    assert final_page["has_more"] is False
    assert len(final_page["rows"]) == expected_total - ((final_page_number - 1) * 100)

    legacy = client.get("/api/purchasing/requests", headers=auth_headers)
    assert legacy.status_code == 200, legacy.text
    assert isinstance(legacy.json(), list)
    assert len(legacy.json()) == expected_total
    assert [row["id"] for row in legacy.json()[:3]] == list(reversed(created_ids[-3:]))


def test_purchase_request_page_size_is_bounded(client, auth_headers):
    response = client.get(
        "/api/purchasing/requests?page=1&page_size=501",
        headers=auth_headers,
    )
    assert response.status_code == 422, response.text
