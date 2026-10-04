"""PERF22-USLUGA: the usluga directory must be bounded and paginated.

The list route used to return every usluga order as a bare JSON array, so the
directory materialized the whole order history on each visit.  It now returns a
``{"items": [...], "total": n}`` envelope and accepts ``limit``/``offset``.

These tests pin the contract the frontend depends on:

* the response is an envelope, not a bare array;
* ``total`` is the true filtered total, never the page length;
* ``limit``/``offset`` slice the rows in the existing ``id DESC`` order;
* a hostile ``limit`` is clamped instead of raising.
"""

from __future__ import annotations

from app.tests.test_usluga import _create_usluga_order, _login_eco


def _seed_orders(client, count: int = 3) -> list[dict]:
    _login_eco(client)
    return [_create_usluga_order(client)[1] for _ in range(count)]


def test_orders_list_returns_paginated_envelope(client):
    _seed_orders(client, 3)

    response = client.get("/api/usluga/orders")

    assert response.status_code == 200, response.text
    body = response.json()
    # An envelope, not the bare array the directory used to receive.
    assert isinstance(body, dict)
    assert set(body) == {"items", "total", "limit", "offset"}
    assert isinstance(body["items"], list)
    assert isinstance(body["total"], int)


def test_orders_total_is_true_count_not_page_length(client):
    _seed_orders(client, 3)

    body = client.get("/api/usluga/orders?limit=2").json()

    assert len(body["items"]) == 2
    # The regression: total must be the real match count, not len(items).
    assert body["total"] == 3
    assert body["total"] != len(body["items"])


def test_orders_limit_and_offset_slice_in_existing_id_desc_order(client):
    orders = _seed_orders(client, 3)
    expected = [order["id"] for order in sorted(orders, key=lambda row: row["id"], reverse=True)]

    first = client.get("/api/usluga/orders?limit=2&offset=0").json()
    second = client.get("/api/usluga/orders?limit=2&offset=2").json()

    assert [row["id"] for row in first["items"]] == expected[:2]
    assert [row["id"] for row in second["items"]] == expected[2:]
    assert first["total"] == second["total"] == 3
    assert first["offset"] == 0 and second["offset"] == 2
    # The pages must not overlap or drop a row.
    assert set(row["id"] for row in first["items"]).isdisjoint(row["id"] for row in second["items"])
    assert first["items"] + second["items"]


def test_orders_page_payload_keeps_detail_fields(client):
    _seed_orders(client, 1)

    row = client.get("/api/usluga/orders?limit=1").json()["items"][0]

    # Rows are still built by the shared _order_payload serializer.
    assert row["work_orders"]
    assert [work["operation"] for work in row["work_orders"]] == ["cutting", "sewing", "packaging"]
    assert "ready_for_handover" in row
    assert "package_quantity" in row


def test_orders_hostile_limit_is_clamped_without_raising(client):
    _seed_orders(client, 2)

    huge = client.get("/api/usluga/orders?limit=100000000000000000000")
    zero = client.get("/api/usluga/orders?limit=0")
    negative_offset = client.get("/api/usluga/orders?limit=1&offset=-5")

    assert huge.status_code == 200, huge.text
    assert huge.json()["limit"] == 200
    assert zero.status_code == 200, zero.text
    assert zero.json()["limit"] == 1
    assert negative_offset.status_code == 200, negative_offset.text
    assert negative_offset.json()["offset"] == 0
    assert len(negative_offset.json()["items"]) == 1


def test_orders_status_filter_still_works_with_pagination(client):
    _seed_orders(client, 2)

    planning = client.get("/api/usluga/orders?status=planning").json()
    missing = client.get("/api/usluga/orders?status=sewing").json()
    paged = client.get("/api/usluga/orders?status=planning&limit=1").json()

    assert planning["total"] == 2
    assert all(row["status"] == "planning" for row in planning["items"])
    assert missing["total"] == 0 and missing["items"] == []
    assert paged["total"] == 2 and len(paged["items"]) == 1


def test_orders_search_is_applied_server_side_across_pages(client):
    models = []
    _login_eco(client)
    for _ in range(3):
        model, _order = _create_usluga_order(client)
        models.append(model)
    # The target is the first-created order, so the lowest id and therefore the
    # last row of the `id DESC` order: a bounded first page cannot see it.
    target_model = models[0]

    # The target is the oldest order, so a bounded first page cannot see it.
    first_page = client.get("/api/usluga/orders?limit=1&offset=0").json()
    assert target_model["id"] not in [row["model"]["id"] for row in first_page["items"]]

    # Server-side search still reaches it, and narrows the total to the real match.
    matched = client.get(
        "/api/usluga/orders",
        params={"search": target_model["code"], "limit": 1, "offset": 0},
    )

    assert matched.status_code == 200, matched.text
    body = matched.json()
    assert body["total"] == 1
    assert [row["model"]["id"] for row in body["items"]] == [target_model["id"]]


def test_orders_empty_directory_returns_empty_envelope(client):
    _login_eco(client)

    body = client.get("/api/usluga/orders").json()

    assert body == {"items": [], "total": 0, "limit": 50, "offset": 0}
