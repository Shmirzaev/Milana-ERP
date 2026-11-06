def _material_context(client, auth_headers):
    items = client.get("/api/inventory/items?group=materials", headers=auth_headers)
    warehouses = client.get("/api/inventory/warehouses", headers=auth_headers)
    assert items.status_code == 200, items.text
    assert warehouses.status_code == 200, warehouses.text
    item = next(row for row in items.json() if row["category"] == "fabric" and row["unit"] == "kg")
    warehouse = next(row for row in warehouses.json() if row["type"] == "fabric_storage")
    return item, warehouse


def test_receive_material_persists_individual_roll_weights(client, auth_headers):
    item, warehouse = _material_context(client, auth_headers)
    response = client.post(
        "/api/inventory/receive",
        json={
            "item_id": item["id"],
            "batch_no": "ROLL-WEIGHTS-NEW-001",
            "quantity": 35.5,
            "piece_count": 2,
            "roll_weights_kg": [15.5, 20],
            "roll_lengths_m": [42.125, None],
            "unit": "kg",
            "cost_per_unit": 1,
            "warehouse_id": warehouse["id"],
            "qc_status": "passed",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["piece_count"] == 2
    assert response.json()["roll_weights_kg"] == [15.5, 20.0]
    assert response.json()["roll_lengths_m"] == [42.125, None]
    assert response.json()["length_m"] is None
    batch_id = response.json()["id"]
    listed = client.get("/api/inventory/batches?group=materials", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    assert next(row for row in listed.json() if row["id"] == batch_id)["roll_lengths_m"] == [42.125, None]
    changed_count = client.put(
        f"/api/inventory/batches/{batch_id}/roll-weights",
        json={"roll_weights_kg": [35.5]}, headers=auth_headers,
    )
    assert changed_count.status_code == 409, changed_count.text
    changed_count = client.patch(
        f"/api/inventory/batches/{batch_id}",
        json={"piece_count": 1}, headers=auth_headers,
    )
    assert changed_count.status_code == 409, changed_count.text


def test_existing_material_requires_matching_total_before_roll_weights_save(client, auth_headers):
    item, warehouse = _material_context(client, auth_headers)
    receive = client.post(
        "/api/inventory/receive",
        json={
            "item_id": item["id"],
            "batch_no": "ROLL-WEIGHTS-OLD-001",
            "quantity": 30,
            "piece_count": 2,
            "unit": "kg",
            "cost_per_unit": 1,
            "warehouse_id": warehouse["id"],
            "qc_status": "passed",
        },
        headers=auth_headers,
    )
    assert receive.status_code == 201, receive.text
    assert receive.json()["roll_lengths_m"] == []
    batch_id = receive.json()["id"]

    mismatch = client.put(
        f"/api/inventory/batches/{batch_id}/roll-weights",
        json={"roll_weights_kg": [10, 15]},
        headers=auth_headers,
    )
    assert mismatch.status_code == 409, mismatch.text

    saved = client.put(
        f"/api/inventory/batches/{batch_id}/roll-weights",
        json={"roll_weights_kg": [12.25, 17.75]},
        headers=auth_headers,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["piece_count"] == 2
    assert saved.json()["roll_weights_kg"] == [12.25, 17.75]


def test_receive_meter_material_preserves_total_without_kg_weights(client, auth_headers):
    item, warehouse = _material_context(client, auth_headers)
    response = client.post(
        "/api/inventory/receive",
        json={
            "item_id": item["id"], "batch_no": "TOTAL-LENGTH-M-001",
            "quantity": 123.45, "piece_count": 3, "unit": "m",
            "roll_weights_kg": [], "roll_lengths_m": [],
            "cost_per_unit": 2, "warehouse_id": warehouse["id"], "qc_status": "passed",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    batch = response.json()
    assert batch["quantity"] == 123.45
    assert batch["unit"] == "m"
    assert batch["piece_count"] == 3
    assert batch["roll_weights_kg"] == []
    assert batch["roll_lengths_m"] == []
    assert batch["length_m"] is None  # Length per roll, not the batch total.
    listed = client.get("/api/inventory/batches?group=materials", headers=auth_headers)
    saved = next(row for row in listed.json() if row["id"] == batch["id"])
    assert saved["quantity"] == 123.45
    assert saved["unit"] == "m"
    assert saved["roll_weights_kg"] == []
    invalid = client.post(
        "/api/inventory/receive",
        json={
            "item_id": item["id"], "batch_no": "TOTAL-LENGTH-M-INVALID",
            "quantity": 123.45, "piece_count": 1, "unit": "m",
            "roll_weights_kg": [123.45], "cost_per_unit": 2,
            "warehouse_id": warehouse["id"], "qc_status": "passed",
        },
        headers=auth_headers,
    )
    assert invalid.status_code == 400, invalid.text
