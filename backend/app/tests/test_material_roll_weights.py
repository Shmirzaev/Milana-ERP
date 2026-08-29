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
