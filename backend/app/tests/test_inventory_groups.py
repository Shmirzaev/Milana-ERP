def test_inventory_stock_groups_separate_materials_and_accessories(client, auth_headers):
    material_response = client.get("/api/inventory/stock?group=materials", headers=auth_headers)
    accessory_response = client.get("/api/inventory/stock?group=accessories", headers=auth_headers)

    assert material_response.status_code == 200, material_response.text
    assert accessory_response.status_code == 200, accessory_response.text

    material_skus = {row["item_sku"] for row in material_response.json()}
    accessory_skus = {row["item_sku"] for row in accessory_response.json()}

    assert "FAB-COT-001" in material_skus
    assert "FAB-POL-001" in material_skus
    assert "ACC-BTN-001" not in material_skus
    assert "ACC-BTN-001" in accessory_skus
    assert "ACC-ZIP-001" in accessory_skus
    assert "FAB-COT-001" not in accessory_skus


def test_inventory_item_groups_follow_same_split(client, auth_headers):
    material_response = client.get("/api/inventory/items?group=materials", headers=auth_headers)
    accessory_response = client.get("/api/inventory/items?group=accessories", headers=auth_headers)

    assert material_response.status_code == 200, material_response.text
    assert accessory_response.status_code == 200, accessory_response.text

    material_categories = {row["category"] for row in material_response.json()}
    accessory_categories = {row["category"] for row in accessory_response.json()}

    assert material_categories <= {"fabric", "semi_finished"}
    assert accessory_categories <= {"accessory", "packaging"}


def test_inventory_stock_search_filters_within_group(client, auth_headers):
    material_response = client.get("/api/inventory/stock?group=materials&q=cot", headers=auth_headers)
    accessory_response = client.get("/api/inventory/stock?group=accessories&q=zip", headers=auth_headers)
    crossed_response = client.get("/api/inventory/stock?group=accessories&q=fab", headers=auth_headers)

    assert material_response.status_code == 200, material_response.text
    assert accessory_response.status_code == 200, accessory_response.text
    assert crossed_response.status_code == 200, crossed_response.text

    material_skus = {row["item_sku"] for row in material_response.json()}
    accessory_skus = {row["item_sku"] for row in accessory_response.json()}
    crossed_skus = {row["item_sku"] for row in crossed_response.json()}

    assert "FAB-COT-001" in material_skus
    assert "FAB-POL-001" not in material_skus
    assert "ACC-ZIP-001" in accessory_skus
    assert "ACC-BTN-001" not in accessory_skus
    assert all(not sku.startswith("FAB-") for sku in crossed_skus)
