def test_models_list(client, auth_headers):
    r = client.get("/api/models?q=T-SHIRT-001", headers=auth_headers)
    assert r.status_code == 200
    items = r.json()
    assert any(m["code"] == "T-SHIRT-001" for m in items)


def test_modeling_role_can_list_bom_items_without_inventory_access(client):
    login = client.post(
        "/api/auth/token",
        data={"username": "modeling@example.com", "password": "demo12345"},
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    inventory = client.get("/api/inventory/items", headers=headers)
    assert inventory.status_code == 403, inventory.text

    response = client.get("/api/models/bom-items", headers=headers)
    assert response.status_code == 200, response.text
    items = response.json()
    assert any(item["category"] == "fabric" for item in items)
    assert all(item["is_active"] is True for item in items)
    assert {item["category"] for item in items} <= {
        "fabric",
        "semi_finished",
        "accessory",
        "packaging",
    }


def test_models_list_hides_internal_legacy_import_identities(client, auth_headers):
    from uuid import uuid4

    code = f"LEGACY-INTERNAL-{uuid4().hex[:10]}"
    created = client.post(
        "/api/models",
        json={
            "code": code,
            "name": "Internal legacy stock identity",
            "category": "Legacy finished goods",
            "status": "approved",
            "details_json": {"legacy_import": True},
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text

    visible = client.get(
        "/api/models/variant-groups",
        params={"q": code, "include_total": "true"},
        headers=auth_headers,
    )
    assert visible.status_code == 200, visible.text
    assert visible.json()["total"] == 0

    internal = client.get(
        "/api/models/variant-groups",
        params={
            "q": code,
            "include_total": "true",
            "include_legacy_import": "true",
        },
        headers=auth_headers,
    )
    assert internal.status_code == 200, internal.text
    assert internal.json()["total"] == 1


def test_model_search_matches_latin_and_cyrillic_lookalike_codes(client, auth_headers):
    from uuid import uuid4

    suffix = uuid4().hex[:8].upper()
    latin_prefix = f"PJ-X{suffix}"
    cyrillic_prefix = f"РJ-X{suffix}"
    expected_model_numbers = {
        f"{latin_prefix}/4",
        f"{latin_prefix}/5",
        f"{latin_prefix}/6",
        cyrillic_prefix,
    }
    created_ids = set()

    for slash_variant in ("4", "5", "6"):
        model_no = f"{latin_prefix}/{slash_variant}"
        created = client.post(
            "/api/models",
            json={
                "code": model_no,
                "name": "Latin-code search model",
                "status": "approved",
                "details_json": {"general": {"model_no": model_no}},
            },
            headers=auth_headers,
        )
        assert created.status_code == 201, created.text
        created_ids.add(created.json()["id"])

    for variant_no in ("194", "196"):
        created = client.post(
            "/api/models",
            json={
                "code": f"{cyrillic_prefix}-{variant_no}",
                "name": "Cyrillic-code search model",
                "status": "approved",
                "details_json": {
                    "general": {
                        "model_no": cyrillic_prefix,
                        "variant_no": variant_no,
                    }
                },
            },
            headers=auth_headers,
        )
        assert created.status_code == 201, created.text
        created_ids.add(created.json()["id"])

    for parameter in ("q", "code"):
        for query in (latin_prefix, cyrillic_prefix):
            response = client.get(
                "/api/models/variant-groups",
                params={parameter: query, "include_total": "true", "page_size": 20},
                headers=auth_headers,
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["total"] == 4
            assert {row["group_model_no"] for row in body["rows"]} == expected_model_numbers

    for query in (latin_prefix, cyrillic_prefix):
        response = client.get(
            "/api/search",
            params={"q": query, "limit_per_type": 100},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        found_ids = {
            row["id"]
            for row in response.json()
            if row["type"] == "Model"
        }
        assert created_ids <= found_ids


def test_model_variant_groups_compact_payload_keeps_models_page_fields(client, auth_headers):
    from uuid import uuid4

    suffix = uuid4().hex[:8].upper()
    model_no = f"COMPACT-X{suffix}"
    created_ids = []
    for variant_no in ("10", "20"):
        details = {
            "general": {
                "model_no": model_no,
                "variant_no": variant_no,
                "variant_fabric": f"Fabric {variant_no}",
                "internal_note": "not needed by the models list",
            },
            "translation": {"en": "Compact dress", "ru": "Компактное платье"},
            "composition": [{"name": "Cotton", "percentage": 100}],
            "operations": [{"name": "Heavy operation detail", "minutes": 12}],
            "costing": {"notes": "Heavy costing detail"},
        }
        created = client.post(
            "/api/models",
            json={
                "code": f"{model_no}-{variant_no}",
                "name": "Compact dress",
                "category": "dress",
                "description": "Full detail description",
                "status": "draft",
                "sam_minutes": 18,
                "details_json": details,
            },
            headers=auth_headers,
        )
        assert created.status_code == 201, created.text
        created_ids.append(created.json()["id"])

    picture_url = f"/storage/model-files/compact-{suffix}.webp"
    image = client.post(
        f"/api/models/{created_ids[-1]}/images",
        json={
            "file_url": picture_url,
            "file_name": f"compact-{suffix}.webp",
            "content_type": "image/webp",
            "image_type": "model",
            "is_primary": True,
        },
        headers=auth_headers,
    )
    assert image.status_code == 201, image.text

    compact_response = client.get(
        "/api/models/variant-groups",
        params={
            "q": model_no,
            "include_total": "true",
            "page_size": 10,
            "compact": "true",
        },
        headers=auth_headers,
    )
    assert compact_response.status_code == 200, compact_response.text
    compact_page = compact_response.json()
    assert compact_page["total"] == 1
    assert compact_page["page"] == 1
    assert compact_page["page_size"] == 10
    compact = compact_page["rows"][0]

    assert compact["id"] == created_ids[-1]
    assert compact["code"] == f"{model_no}-20"
    assert compact["name"] == "Compact dress"
    assert compact["category"] == "dress"
    assert compact["status"] == "draft"
    assert compact["sam_minutes"] == 18
    assert compact["created_at"]
    assert compact["group_key"] == f"model:{model_no.casefold()}"
    assert compact["group_model_no"] == model_no
    assert compact["group_name"] == "Compact dress"
    assert compact["details_json"] == {
        "general": {"model_no": model_no, "variant_no": "20"},
        "translation": {"en": "Compact dress", "ru": "Компактное платье"},
        "composition": [{"name": "Cotton", "percentage": 100}],
    }
    assert compact["material_composition"] == []
    assert compact["primary_image"]["file_url"] == picture_url
    assert compact["primary_image_url"] == picture_url
    assert compact["image_count"] == 1
    assert compact["variant_count"] == 2
    assert [variant["model_id"] for variant in compact["variants"]] == created_ids
    assert [variant["variant_no"] for variant in compact["variants"]] == ["10", "20"]
    assert [variant["fabric"] for variant in compact["variants"]] == ["Fabric 10", "Fabric 20"]
    assert "description" not in compact
    assert "operations" not in compact["details_json"]
    assert "costing" not in compact["details_json"]

    default_response = client.get(
        "/api/models/variant-groups",
        params={"q": model_no, "include_total": "true", "page_size": 10},
        headers=auth_headers,
    )
    assert default_response.status_code == 200, default_response.text
    default = default_response.json()["rows"][0]
    assert default["description"] == "Full detail description"
    assert default["details_json"]["operations"] == [
        {"name": "Heavy operation detail", "minutes": 12}
    ]
    assert default["details_json"]["costing"] == {"notes": "Heavy costing detail"}


def test_variant_search_expands_the_full_model_family_and_keeps_family_picture(client, auth_headers):
    from uuid import uuid4

    suffix = uuid4().hex[:8].upper()
    model_no = f"FAMILY-{suffix}"
    variant_no = f"2042-{suffix}"
    base = client.post(
        "/api/models",
        json={
            "code": model_no,
            "name": "Family search model",
            "category": "dress",
            "status": "approved",
            "details_json": {"general": {"model_no": model_no}},
        },
        headers=auth_headers,
    )
    assert base.status_code == 201, base.text
    base_id = base.json()["id"]

    family_picture = f"/storage/model-files/family-{suffix}.jpg"
    base_image = client.post(
        f"/api/models/{base_id}/images",
        json={
            "file_url": family_picture,
            "file_name": f"family-{suffix}.jpg",
            "content_type": "image/jpeg",
            "image_type": "model",
            "is_primary": True,
        },
        headers=auth_headers,
    )
    assert base_image.status_code == 201, base_image.text

    variant = client.post(
        "/api/models",
        json={
            "code": f"{model_no}-{variant_no}",
            "name": "Family search model",
            "category": "dress",
            "status": "approved",
            "details_json": {
                "general": {
                    "model_no": model_no,
                    "variant_no": variant_no,
                }
            },
        },
        headers=auth_headers,
    )
    assert variant.status_code == 201, variant.text
    variant_id = variant.json()["id"]
    variant_picture = f"/storage/model-files/variant-{suffix}.jpg"
    variant_image = client.post(
        f"/api/models/{variant_id}/images",
        json={
            "file_url": variant_picture,
            "file_name": f"variant-{suffix}.jpg",
            "content_type": "image/jpeg",
            "image_type": "model",
            "is_primary": True,
        },
        headers=auth_headers,
    )
    assert variant_image.status_code == 201, variant_image.text

    response = client.get(
        "/api/models/variant-groups",
        params={"q": variant_no, "include_total": "true", "page_size": 10},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert len(body["rows"]) == 1
    group = body["rows"][0]
    assert group["group_model_no"] == model_no
    assert group["primary_image_url"] == family_picture
    assert group["variant_count"] == 1
    assert [row["model_id"] for row in group["variants"]] == [variant_id]
    assert group["variants"][0]["picture_url"] == variant_picture


def test_model_variant_group_pagination_keeps_groups_whole_and_ordered(client, auth_headers):
    from uuid import uuid4

    suffix = uuid4().hex[:8].upper()
    expected_ids: dict[str, list[int]] = {}
    for group_suffix, variants in (("A", ("1", "2")), ("B", ("1",)), ("C", ("1", "2"))):
        model_no = f"PAGE-X{suffix}-{group_suffix}"
        expected_ids[model_no] = []
        for variant_no in variants:
            created = client.post(
                "/api/models",
                json={
                    "code": f"{model_no}-{variant_no}",
                    "name": f"Pagination group {group_suffix}",
                    "category": "dress",
                    "status": "draft",
                    "details_json": {
                        "general": {
                            "model_no": model_no,
                            "variant_no": variant_no,
                        }
                    },
                },
                headers=auth_headers,
            )
            assert created.status_code == 201, created.text
            expected_ids[model_no].append(created.json()["id"])

    pages = []
    for page_number in (1, 2, 3, 4):
        response = client.get(
            "/api/models/variant-groups",
            params={
                "q": suffix,
                "include_total": "true",
                "page": page_number,
                "page_size": 1,
                "compact": "true",
            },
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 3
        assert body["page"] == page_number
        assert body["page_size"] == 1
        pages.append(body["rows"])

    assert [rows[0]["group_model_no"] for rows in pages[:3]] == [
        f"PAGE-X{suffix}-C",
        f"PAGE-X{suffix}-B",
        f"PAGE-X{suffix}-A",
    ]
    assert pages[3] == []
    for rows in pages[:3]:
        assert len(rows) == 1
        group = rows[0]
        assert [variant["model_id"] for variant in group["variants"]] == expected_ids[
            group["group_model_no"]
        ]
    returned_model_ids = [
        variant["model_id"]
        for rows in pages[:3]
        for variant in rows[0]["variants"]
    ]
    assert len(returned_model_ids) == len(set(returned_model_ids)) == 5


def test_model_variant_group_search_fields_filter_before_pagination(client, auth_headers):
    from uuid import uuid4

    suffix = uuid4().hex[:8].upper()
    target_model_no = f"OFFPAGE-X{suffix}"
    target = client.post(
        "/api/models",
        json={
            "code": f"{target_model_no}-919",
            "name": f"Hidden page product {suffix}",
            "category": f"Search category {suffix}",
            "status": "draft",
            "details_json": {
                "general": {
                    "model_no": target_model_no,
                    "variant_no": "919",
                }
            },
        },
        headers=auth_headers,
    )
    assert target.status_code == 201, target.text

    for index in range(3):
        decoy = client.post(
            "/api/models",
            json={
                "code": f"NEWER-{suffix}-{index}",
                "name": f"Newer model {index}",
                "category": "Decoy",
                "status": "draft",
            },
            headers=auth_headers,
        )
        assert decoy.status_code == 201, decoy.text

    unfiltered = client.get(
        "/api/models/variant-groups",
        params={"include_total": "true", "page": 1, "page_size": 1},
        headers=auth_headers,
    )
    assert unfiltered.status_code == 200, unfiltered.text
    assert unfiltered.json()["rows"][0]["id"] != target.json()["id"]

    searches = (
        {"code": "919"},
        {"name": f"product {suffix}".lower()},
        {"category": f"category {suffix}".lower()},
    )
    for search_params in searches:
        response = client.get(
            "/api/models/variant-groups",
            params={
                **search_params,
                "include_total": "true",
                "page": 1,
                "page_size": 1,
                "compact": "true",
            },
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 1
        assert len(body["rows"]) == 1
        assert body["rows"][0]["id"] == target.json()["id"]
        assert body["rows"][0]["group_model_no"] == target_model_no


def test_planning_user_can_create_brand_and_duplicate_is_rejected(client):
    from uuid import uuid4

    login = None
    for password in ("demo12345", "PlanningResetPassword123!"):
        login = client.post(
            "/api/auth/token",
            data={"username": "planning@example.com", "password": password},
        )
        if login.status_code == 200:
            break
    assert login is not None and login.status_code == 200, login.text if login else "No login response"
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    name = f"Planning Brand {uuid4().hex[:8]}"

    created = client.post(
        "/api/brands",
        json={"name": f"  {name}  ", "description": "Created from planning"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["name"] == name
    assert created.json()["is_active"] is True

    duplicate = client.post(
        "/api/brands",
        json={"name": name.lower()},
        headers=headers,
    )
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["detail"] == "Brand already exists"


def test_create_model_and_approve(client, auth_headers):
    r = client.post("/api/models", json={
        "code": "HOODIE-001", "name": "Pullover Hoodie", "category": "hoodie", "status": "draft",
    }, headers=auth_headers)
    assert r.status_code == 201, r.text
    mid = r.json()["id"]
    assert r.json()["code"] == "HOODIE001"
    assert r.json()["details_json"]["general"]["model_no"] == "HOODIE001"
    assert "variant_no" not in r.json()["details_json"]["general"]

    variants = client.get(f"/api/models/{mid}/variants", headers=auth_headers)
    assert variants.status_code == 200, variants.text
    assert variants.json() == []

    groups = client.get(
        "/api/models/variant-groups",
        params={"q": "HOODIE-001", "include_total": "true"},
        headers=auth_headers,
    )
    assert groups.status_code == 200, groups.text
    group = next(row for row in groups.json()["rows"] if row["id"] == mid)
    assert group["variant_count"] == 0
    assert group["variants"] == []

    r2 = client.post(f"/api/models/{mid}/approve", headers=auth_headers)
    assert r2.status_code == 200
    assert r2.json()["status"] == "approved"


def test_create_model_ignores_empty_default_variant_from_form(client, auth_headers):
    r = client.post(
        "/api/models",
        json={
            "code": "TJ-2300",
            "name": "Base model only",
            "status": "draft",
            "details_json": {
                "general": {
                    "model_no": "TJ-2300",
                    "variant_no": "",
                    "variantNo": "",
                }
            },
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    mid = r.json()["id"]
    general = r.json()["details_json"]["general"]
    assert r.json()["code"] == "TJ2300"
    assert general["model_no"] == "TJ2300"
    assert "variant_no" not in general
    assert "variantNo" not in general

    variants = client.get(f"/api/models/{mid}/variants", headers=auth_headers)
    assert variants.status_code == 200, variants.text
    assert variants.json() == []


def test_clone_model_copies_full_plm_details(client, auth_headers):
    items = client.get("/api/inventory/items", headers=auth_headers).json()
    assert items
    item_id = items[0]["id"]

    create = client.post(
        "/api/models",
        json={
            "code": "CLONE-BASE-1001",
            "name": "Clone Base",
            "category": "dress",
            "description": "Original model notes",
            "status": "approved",
            "sam_minutes": 18,
            "details_json": {
                "general": {"model_no": "CLONE-BASE", "variant_no": "1001", "note": "keep note"},
                "translation": {"ru": "Clone RU", "uz": "Clone UZ"},
                "costing": {"labor_pct": 14, "target_margin_pct": 25},
                "paid_operations": [{"id": "op-1", "name": "Sew", "selected": True}],
            },
        },
        headers=auth_headers,
    )
    assert create.status_code == 201, create.text
    model_id = create.json()["id"]

    assert client.post(
        f"/api/models/{model_id}/sizes",
        json={"size": "M", "measurement_json": {"chest": 92}},
        headers=auth_headers,
    ).status_code == 201
    assert client.post(
        f"/api/models/{model_id}/colors",
        json={"color_name": "Black", "color_code": "#000000"},
        headers=auth_headers,
    ).status_code == 201
    assert client.post(
        f"/api/models/{model_id}/bom",
        json={"item_id": item_id, "size": "M", "color": "Black", "quantity_per_piece": 1.25, "unit": "m", "waste_percent": 3},
        headers=auth_headers,
    ).status_code == 201
    assert client.post(
        f"/api/models/{model_id}/images",
        json={"file_url": "https://example.com/model.png", "file_name": "model.png", "content_type": "image/png", "image_type": "model", "is_primary": True},
        headers=auth_headers,
    ).status_code == 201

    cloned = client.post(f"/api/models/{model_id}/clone", headers=auth_headers)
    assert cloned.status_code == 201, cloned.text
    cloned_body = cloned.json()
    assert cloned_body["id"] != model_id
    assert cloned_body["code"] == "CLONE-BASE-1001-COPY"
    assert cloned_body["name"] == "Clone Base Copy"
    assert cloned_body["status"] == "draft"

    detail = client.get(f"/api/models/{cloned_body['id']}", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    data = detail.json()
    assert data["details_json"]["general"]["model_no"] == "CLONE-BASE-1001"
    assert data["details_json"]["general"]["variant_no"] == "COPY"
    assert data["details_json"]["general"]["note"] == "keep note"
    assert data["details_json"]["translation"]["ru"] == "Clone RU"
    assert data["details_json"]["costing"]["target_margin_pct"] == 25
    assert len(data["sizes"]) == 1
    assert data["sizes"][0]["measurement_json"]["chest"] == 92
    assert len(data["colors"]) == 1
    assert data["colors"][0]["color_name"] == "Black"
    assert len(data["bom"]) == 1
    assert data["bom"][0]["item_id"] == item_id
    assert len(data["images"]) == 1
    assert data["images"][0]["file_url"] == "https://example.com/model.png"

    second_clone = client.post(f"/api/models/{model_id}/clone", headers=auth_headers)
    assert second_clone.status_code == 201, second_clone.text
    assert second_clone.json()["code"] == "CLONE-BASE-1001-COPY-2"


def test_model_payloads_include_material_composition(client, auth_headers):
    item = client.post(
        "/api/inventory/items",
        json={
            "sku": "FAB-MODEL-COMP",
            "name": "Composition fabric",
            "category": "fabric",
            "unit": "kg",
            "default_cost": 2.5,
            "reorder_level": 0,
            "track_batch": True,
            "is_active": True,
            "composition": [
                {"name": "Cotton", "percentage": 92},
                {"name": "Elastane", "percentage": 8},
            ],
        },
        headers=auth_headers,
    )
    assert item.status_code == 201, item.text
    item_id = item.json()["id"]

    model = client.post(
        "/api/models",
        json={
            "code": "COMP-MODEL-001",
            "name": "Composition Model",
            "category": "blouse",
            "status": "draft",
        },
        headers=auth_headers,
    )
    assert model.status_code == 201, model.text
    model_id = model.json()["id"]

    bom = client.post(
        f"/api/models/{model_id}/bom",
        json={"item_id": item_id, "quantity_per_piece": 0.42, "unit": "kg", "waste_percent": 2},
        headers=auth_headers,
    )
    assert bom.status_code == 201, bom.text

    detail = client.get(f"/api/models/{model_id}", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    detail_body = detail.json()
    expected = [{"name": "Cotton", "percentage": 92.0}, {"name": "Elastane", "percentage": 8.0}]
    assert detail_body["material_composition"] == expected
    assert detail_body["bom"][0]["item"]["composition"] == expected

    listing = client.get("/api/models?q=COMP-MODEL-001&include_total=true", headers=auth_headers)
    assert listing.status_code == 200, listing.text
    row = next(row for row in listing.json()["rows"] if row["id"] == model_id)
    assert "material_composition" not in row
    assert "bom" not in row


def test_variant_picture_uses_attached_material_image_without_bom(client, auth_headers):
    from uuid import uuid4

    suffix = uuid4().hex[:8].upper()
    model_no = f"EXCEL-{suffix}"
    model = client.post(
        "/api/models",
        json={
            "code": f"{model_no}-4053",
            "name": "",
            "status": "draft",
            "details_json": {
                "general": {
                    "model_no": model_no,
                    "variant_no": "4053",
                    "variant_fabric": "Супрем",
                }
            },
        },
        headers=auth_headers,
    )
    assert model.status_code == 201, model.text
    model_id = model.json()["id"]

    model_picture = f"/storage/model-files/model-{suffix}.png"
    material_picture = f"/storage/model-files/material-{suffix}.png"
    assert client.post(
        f"/api/models/{model_id}/images",
        json={
            "file_url": model_picture,
            "file_name": f"model-{suffix}.png",
            "content_type": "image/png",
            "image_type": "model",
            "is_primary": True,
        },
        headers=auth_headers,
    ).status_code == 201
    assert client.post(
        f"/api/models/{model_id}/images",
        json={
            "file_url": material_picture,
            "file_name": f"material-{suffix}.png",
            "content_type": "image/png",
            "image_type": "material",
            "is_primary": False,
        },
        headers=auth_headers,
    ).status_code == 201

    variants = client.get(f"/api/models/{model_id}/variants", headers=auth_headers)
    assert variants.status_code == 200, variants.text
    assert len(variants.json()) == 1
    assert variants.json()[0]["fabric"] == "Супрем"
    assert variants.json()[0]["picture_url"] == material_picture

    groups = client.get(
        "/api/models/variant-groups",
        params={"q": model_no, "include_total": "true", "page_size": 10},
        headers=auth_headers,
    )
    assert groups.status_code == 200, groups.text
    assert groups.json()["total"] == 1
    assert groups.json()["rows"][0]["primary_image_url"] == model_picture
    assert groups.json()["rows"][0]["variants"][0]["picture_url"] == material_picture

    mislabeled_upload = client.post(
        f"/api/models/{model_id}/bom-photo/upload",
        files={
            "file": (
                "download.jpg",
                __import__("base64").b64decode(
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
                ),
                "image/jpeg",
            )
        },
        headers=auth_headers,
    )
    assert mislabeled_upload.status_code == 201, mislabeled_upload.text
    replacement_picture = mislabeled_upload.json()["file_url"]
    assert replacement_picture.endswith(".webp")
    updated = client.patch(
        f"/api/models/{model_id}/variants/{model_id}",
        json={"variant_no": "4053", "picture_url": replacement_picture},
        headers=auth_headers,
    )
    assert updated.status_code == 200, updated.text
    variants = client.get(f"/api/models/{model_id}/variants", headers=auth_headers)
    assert variants.status_code == 200, variants.text
    assert variants.json()[0]["fabric_item_id"] is None
    assert variants.json()[0]["picture_url"] == replacement_picture


def test_model_variant_groups_keep_underlying_model_ids(client, auth_headers):
    from uuid import uuid4

    suffix = uuid4().hex[:8].upper()
    model_no = f"VAR-GROUP-{suffix}"

    item = client.post(
        "/api/inventory/items",
        json={
            "sku": f"FAB-VAR-GROUP-{suffix}",
            "name": f"Variant fabric {suffix}",
            "category": "fabric",
            "unit": "kg",
            "default_cost": 2.5,
            "reorder_level": 0,
            "track_batch": True,
            "is_active": True,
            "composition": [{"name": "Cotton", "percentage": 100}],
            "image_url": f"/storage/model-files/variant-fabric-{suffix}.webp",
        },
        headers=auth_headers,
    )
    assert item.status_code == 201, item.text
    item_id = item.json()["id"]
    edit_item = client.post(
        "/api/inventory/items",
        json={
            "sku": f"FAB-VAR-EDIT-{suffix}",
            "name": f"Edited variant fabric {suffix}",
            "category": "fabric",
            "unit": "kg",
            "default_cost": 3,
            "reorder_level": 0,
            "track_batch": True,
            "is_active": True,
            "composition": [{"name": "Viscose", "percentage": 100}],
            "image_url": f"/storage/model-files/variant-fabric-edit-{suffix}.webp",
        },
        headers=auth_headers,
    )
    assert edit_item.status_code == 201, edit_item.text
    edit_item_id = edit_item.json()["id"]

    created_ids = []
    for variant_no, color in [("V-1", "Moss"), ("V-2", "Navy")]:
        model = client.post(
            "/api/models",
            json={
                "code": f"{model_no}-{variant_no}",
                "name": "Grouped robe",
                "category": "robe",
                "status": "draft",
                "details_json": {"general": {"model_no": model_no, "variant_no": variant_no}},
            },
            headers=auth_headers,
        )
        assert model.status_code == 201, model.text
        model_id = model.json()["id"]
        created_ids.append(model_id)
        bom = client.post(
            f"/api/models/{model_id}/bom",
            json={
                "item_id": item_id if variant_no == "V-1" else edit_item_id,
                "color": color,
                "photo_url": f"/storage/model-files/{variant_no.lower()}-{suffix}.webp",
                "quantity_per_piece": 0.42,
                "unit": "kg",
                "waste_percent": 2,
            },
            headers=auth_headers,
        )
        assert bom.status_code == 201, bom.text

    variants = client.get(f"/api/models/{created_ids[0]}/variants", headers=auth_headers)
    assert variants.status_code == 200, variants.text
    variant_rows = variants.json()
    assert [row["model_id"] for row in variant_rows] == created_ids
    assert [row["variant_no"] for row in variant_rows] == ["V-1", "V-2"]
    assert "Variant fabric" in variant_rows[0]["fabric"]
    assert "Moss" in variant_rows[0]["fabric"]
    assert variant_rows[0]["picture_url"].startswith("/storage/model-files/")

    inherited_update = client.patch(
        f"/api/models/{created_ids[0]}/variants/{created_ids[1]}",
        json={"variant_no": "V-2"},
        headers=auth_headers,
    )
    assert inherited_update.status_code == 200, inherited_update.text
    inherited_detail = client.get(f"/api/models/{created_ids[1]}", headers=auth_headers)
    assert inherited_detail.status_code == 200, inherited_detail.text
    inherited_bom = inherited_detail.json()["bom"][0]
    assert inherited_bom["item_id"] == item_id
    assert inherited_bom["color"] == "Navy"
    assert inherited_bom["photo_url"] == f"/storage/model-files/v-2-{suffix}.webp"

    custom_picture = f"/storage/model-files/custom-variant-{suffix}.webp"
    edited_custom_picture = f"/storage/model-files/custom-variant-edit-{suffix}.webp"
    created_variant = client.post(
        f"/api/models/{created_ids[0]}/variants",
        json={"variant_no": "V-3", "color": "Brown", "picture_url": custom_picture},
        headers=auth_headers,
    )
    assert created_variant.status_code == 201, created_variant.text
    created_variant_body = created_variant.json()
    created_ids.append(created_variant_body["id"])
    assert created_variant_body["code"] == f"{model_no}-V-3"
    assert created_variant_body["name"] == "Grouped robe"
    assert created_variant_body["details_json"]["general"]["model_no"] == model_no
    assert created_variant_body["details_json"]["general"]["variant_no"] == "V-3"
    assert created_variant_body["details_json"]["general"]["variant_fabric_item_id"] == item_id
    assert "variant_stock_batch_id" not in created_variant_body["details_json"]["general"]
    assert "Variant fabric" in created_variant_body["details_json"]["general"]["variant_fabric"]

    created_variant_detail = client.get(f"/api/models/{created_variant_body['id']}", headers=auth_headers)
    assert created_variant_detail.status_code == 200, created_variant_detail.text
    created_variant_bom = created_variant_detail.json()["bom"][0]
    assert created_variant_bom["item_id"] == item_id
    assert created_variant_bom["stock_batch_id"] is None
    assert created_variant_bom["stock_batch_no"] is None
    assert created_variant_bom["stock_batch_color"] is None
    assert created_variant_bom["color"] == "Brown"
    assert created_variant_bom["photo_url"] == custom_picture
    created_variant_material_images = [
        row for row in created_variant_detail.json()["images"] if row["image_type"] == "material"
    ]
    assert created_variant_material_images
    assert created_variant_material_images[-1]["file_url"] == custom_picture

    variants = client.get(f"/api/models/{created_ids[0]}/variants", headers=auth_headers)
    assert variants.status_code == 200, variants.text
    variant_rows = variants.json()
    assert [row["model_id"] for row in variant_rows] == created_ids
    assert [row["variant_no"] for row in variant_rows] == ["V-1", "V-2", "V-3"]
    assert "Variant fabric" in variant_rows[2]["fabric"]
    assert variant_rows[2]["picture_url"] == custom_picture
    assert variant_rows[2]["fabric_item_id"] == item_id
    assert variant_rows[2]["color"] == "Brown"
    assert "Brown" in variant_rows[2]["fabric"]
    assert variant_rows[2]["stock_batch_id"] is None

    rejected_create = client.post(
        f"/api/models/{created_ids[0]}/variants",
        json={"variant_no": "V-BLOCKED", "fabric_item_id": edit_item_id},
        headers=auth_headers,
    )
    assert rejected_create.status_code == 400, rejected_create.text
    assert rejected_create.json()["detail"] == "Variant material must match the parent model material"

    preserved_variant = client.patch(
        f"/api/models/{created_ids[0]}/variants/{created_variant_body['id']}",
        json={"variant_no": "V-3A", "fabric_item_id": item_id},
        headers=auth_headers,
    )
    assert preserved_variant.status_code == 200, preserved_variant.text
    preserved_detail = client.get(f"/api/models/{created_variant_body['id']}", headers=auth_headers)
    assert preserved_detail.status_code == 200, preserved_detail.text
    assert preserved_detail.json()["bom"][0]["photo_url"] == custom_picture

    rejected_update = client.patch(
        f"/api/models/{created_ids[0]}/variants/{created_variant_body['id']}",
        json={"variant_no": "V-4", "fabric_item_id": edit_item_id},
        headers=auth_headers,
    )
    assert rejected_update.status_code == 400, rejected_update.text
    assert rejected_update.json()["detail"] == "Variant material must match the parent model material"

    updated_variant = client.patch(
        f"/api/models/{created_ids[0]}/variants/{created_variant_body['id']}",
        json={
            "variant_no": "V-4",
            "color": "Burgundy",
            "picture_url": edited_custom_picture,
        },
        headers=auth_headers,
    )
    assert updated_variant.status_code == 200, updated_variant.text
    updated_variant_body = updated_variant.json()
    created_ids[-1] = updated_variant_body["id"]
    assert updated_variant_body["code"] == f"{model_no}-V-4"
    assert updated_variant_body["details_json"]["general"]["variant_no"] == "V-4"
    assert updated_variant_body["details_json"]["general"]["variant_fabric_item_id"] == item_id
    assert "variant_stock_batch_id" not in updated_variant_body["details_json"]["general"]
    assert "Variant fabric" in updated_variant_body["details_json"]["general"]["variant_fabric"]

    updated_variant_detail = client.get(f"/api/models/{updated_variant_body['id']}", headers=auth_headers)
    assert updated_variant_detail.status_code == 200, updated_variant_detail.text
    updated_variant_bom = updated_variant_detail.json()["bom"][0]
    assert updated_variant_bom["item_id"] == item_id
    assert updated_variant_bom["stock_batch_id"] is None
    assert updated_variant_bom["stock_batch_no"] is None
    assert updated_variant_bom["stock_batch_color"] is None
    assert updated_variant_bom["color"] == "Burgundy"
    assert updated_variant_bom["photo_url"] == edited_custom_picture
    updated_variant_material_images = [
        row for row in updated_variant_detail.json()["images"] if row["image_type"] == "material"
    ]
    assert updated_variant_material_images
    assert updated_variant_material_images[-1]["file_url"] == edited_custom_picture

    variants = client.get(f"/api/models/{created_ids[0]}/variants", headers=auth_headers)
    assert variants.status_code == 200, variants.text
    variant_rows = variants.json()
    assert [row["model_id"] for row in variant_rows] == created_ids
    assert [row["variant_no"] for row in variant_rows] == ["V-1", "V-2", "V-4"]
    assert "Variant fabric" in variant_rows[2]["fabric"]
    assert variant_rows[2]["picture_url"] == edited_custom_picture
    assert variant_rows[2]["fabric_item_id"] == item_id
    assert variant_rows[2]["color"] == "Burgundy"
    assert "Burgundy" in variant_rows[2]["fabric"]
    assert variant_rows[2]["stock_batch_id"] is None

    listed_models = client.get(f"/api/models?q={model_no}", headers=auth_headers)
    assert listed_models.status_code == 200, listed_models.text
    listed_variant = next(row for row in listed_models.json() if row["id"] == updated_variant_body["id"])
    assert "fabric_image_url" not in listed_variant

    groups = client.get(
        f"/api/models/variant-groups?include_total=true&q={model_no}",
        headers=auth_headers,
    )
    assert groups.status_code == 200, groups.text
    grouped_row = next(row for row in groups.json()["rows"] if row["group_model_no"] == model_no)
    assert grouped_row["variant_count"] == 3
    assert [row["model_id"] for row in grouped_row["variants"]] == created_ids

    deleted_variant = client.delete(
        f"/api/models/{created_ids[0]}/variants/{updated_variant_body['id']}",
        headers=auth_headers,
    )
    assert deleted_variant.status_code == 204, deleted_variant.text
    created_ids.pop()

    variants = client.get(f"/api/models/{created_ids[0]}/variants", headers=auth_headers)
    assert variants.status_code == 200, variants.text
    variant_rows = variants.json()
    assert [row["model_id"] for row in variant_rows] == created_ids
    assert [row["variant_no"] for row in variant_rows] == ["V-1", "V-2"]

    groups = client.get(
        f"/api/models/variant-groups?include_total=true&q={model_no}",
        headers=auth_headers,
    )
    assert groups.status_code == 200, groups.text
    grouped_row = next(row for row in groups.json()["rows"] if row["group_model_no"] == model_no)
    assert grouped_row["variant_count"] == 2
    assert [row["model_id"] for row in grouped_row["variants"]] == created_ids


def test_new_model_variants_receive_the_next_global_v_number(client, auth_headers):
    from uuid import uuid4

    suffix = uuid4().hex[:8].upper()
    model_no = f"AUTO-VAR-{suffix}"
    item = client.post(
        "/api/inventory/items",
        json={
            "sku": f"FAB-AUTO-VAR-{suffix}",
            "name": f"Automatic variant fabric {suffix}",
            "category": "fabric",
            "unit": "kg",
            "default_cost": 2.5,
            "reorder_level": 0,
            "track_batch": True,
            "is_active": True,
            "composition": [{"name": "Cotton", "percentage": 100}],
        },
        headers=auth_headers,
    )
    assert item.status_code == 201, item.text

    model = client.post(
        "/api/models",
        json={
            "code": model_no,
            "name": "Automatic variant numbering",
            "status": "draft",
            "details_json": {"general": {"model_no": model_no}},
        },
        headers=auth_headers,
    )
    assert model.status_code == 201, model.text
    model_id = model.json()["id"]
    bom = client.post(
        f"/api/models/{model_id}/bom",
        json={"item_id": item.json()["id"], "quantity_per_piece": 0.5, "unit": "kg"},
        headers=auth_headers,
    )
    assert bom.status_code == 201, bom.text

    legacy_high = client.post(
        "/api/models",
        json={
            "code": f"LEGACY-HIGH-{suffix}-V-17194",
            "name": "Legacy high variant",
            "status": "approved",
            "details_json": {
                "general": {
                    "model_no": f"LEGACY-HIGH-{suffix}",
                    "variant_no": "V-17194",
                }
            },
        },
        headers=auth_headers,
    )
    assert legacy_high.status_code == 201, legacy_high.text

    preview = client.get(f"/api/models/{model_id}/variants/next-number", headers=auth_headers)
    assert preview.status_code == 200, preview.text
    assert preview.json()["variant_no"] == "V-5648"

    first = client.post(
        f"/api/models/{model_id}/variants",
        json={"fabric_item_id": item.json()["id"]},
        headers=auth_headers,
    )
    assert first.status_code == 201, first.text
    assert first.json()["code"] == f"{model_no}-V-5648"
    assert first.json()["details_json"]["general"]["variant_no"] == "V-5648"

    deleted = client.delete(
        f"/api/models/{model_id}/variants/{first.json()['id']}",
        headers=auth_headers,
    )
    assert deleted.status_code == 204, deleted.text

    next_preview = client.get(f"/api/models/{model_id}/variants/next-number", headers=auth_headers)
    assert next_preview.status_code == 200, next_preview.text
    assert next_preview.json()["variant_no"] == "V-5649"

    second = client.post(
        f"/api/models/{model_id}/variants",
        json={"fabric_item_id": item.json()["id"]},
        headers=auth_headers,
    )
    assert second.status_code == 201, second.text
    assert second.json()["code"] == f"{model_no}-V-5649"
    assert second.json()["details_json"]["general"]["variant_no"] == "V-5649"


def test_model_number_removes_only_prefix_digit_separator(client, auth_headers):
    from uuid import uuid4

    suffix = uuid4().hex[:8].upper()
    item = client.post(
        "/api/inventory/items",
        json={
            "sku": f"FAB-MODEL-NO-{suffix}",
            "name": f"Model number fabric {suffix}",
            "category": "fabric",
            "unit": "kg",
            "default_cost": 1,
            "reorder_level": 0,
            "track_batch": True,
            "is_active": True,
            "composition": [{"name": "Cotton", "percentage": 100}],
        },
        headers=auth_headers,
    )
    assert item.status_code == 201, item.text

    created = client.post(
        "/api/models",
        json={
            "code": f"PJ-10{suffix[:2]}",
            "name": "Normalized model number",
            "status": "draft",
            "details_json": {"general": {"model_no": f"PJ-10{suffix[:2]}"}},
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    model = created.json()
    expected_model_no = f"PJ10{suffix[:2]}"
    assert model["code"] == expected_model_no
    assert model["details_json"]["general"]["model_no"] == expected_model_no

    bom = client.post(
        f"/api/models/{model['id']}/bom",
        json={"item_id": item.json()["id"], "quantity_per_piece": 0.4, "unit": "kg"},
        headers=auth_headers,
    )
    assert bom.status_code == 201, bom.text

    variant = client.post(
        f"/api/models/{model['id']}/variants",
        json={"variant_no": "V-9001"},
        headers=auth_headers,
    )
    assert variant.status_code == 201, variant.text
    assert variant.json()["code"] == f"{expected_model_no}-V-9001"
    assert variant.json()["details_json"]["general"]["model_no"] == expected_model_no

    renamed = client.patch(
        f"/api/models/{model['id']}",
        json={
            "code": f"XJ-20{suffix[:2]}",
            "name": "Normalized model number",
            "status": "draft",
            "details_json": {"general": {"model_no": f"XJ-20{suffix[:2]}"}},
        },
        headers=auth_headers,
    )
    assert renamed.status_code == 200, renamed.text
    expected_renamed_model_no = f"XJ20{suffix[:2]}"
    assert renamed.json()["code"] == expected_renamed_model_no
    assert renamed.json()["details_json"]["general"]["model_no"] == expected_renamed_model_no

    renamed_variant = client.get(f"/api/models/{variant.json()['id']}", headers=auth_headers)
    assert renamed_variant.status_code == 200, renamed_variant.text
    assert renamed_variant.json()["code"] == f"{expected_renamed_model_no}-V-9001"
    assert renamed_variant.json()["details_json"]["general"]["model_no"] == expected_renamed_model_no


def test_editing_model_number_renames_the_whole_variant_group(client, auth_headers):
    from uuid import uuid4

    suffix = uuid4().hex[:8].upper()
    old_model_no = f"OLD-X{suffix}"
    new_model_no = f"NEW-X{suffix}"
    created_ids = []
    for variant_no in ("101", "102", "103"):
        response = client.post(
            "/api/models",
            json={
                "code": f"{old_model_no}-{variant_no}",
                "name": "Rename group test",
                "status": "draft",
                "details_json": {"general": {"model_no": old_model_no, "variant_no": variant_no}},
            },
            headers=auth_headers,
        )
        assert response.status_code == 201, response.text
        created_ids.append(response.json()["id"])

    edited = client.patch(
        f"/api/models/{created_ids[0]}",
        json={
            "code": f"{new_model_no}-101",
            "name": "Rename group test",
            "status": "draft",
            "details_json": {"general": {"model_no": new_model_no, "variant_no": "101"}},
        },
        headers=auth_headers,
    )
    assert edited.status_code == 200, edited.text

    groups = client.get(
        "/api/models/variant-groups",
        params={"q": suffix, "include_total": "true", "page_size": 20},
        headers=auth_headers,
    )
    assert groups.status_code == 200, groups.text
    rows = groups.json()["rows"]
    assert len(rows) == 1
    assert rows[0]["group_model_no"] == new_model_no
    assert rows[0]["variant_count"] == 3
    assert [variant["variant_no"] for variant in rows[0]["variants"]] == ["101", "102", "103"]
    assert [variant["model_id"] for variant in rows[0]["variants"]] == created_ids

    for model_id, variant_no in zip(created_ids, ("101", "102", "103")):
        detail = client.get(f"/api/models/{model_id}", headers=auth_headers)
        assert detail.status_code == 200, detail.text
        assert detail.json()["code"] == f"{new_model_no}-{variant_no}"
        assert detail.json()["details_json"]["general"]["model_no"] == new_model_no
        assert detail.json()["details_json"]["general"]["variant_no"] == variant_no


def test_base_model_is_not_returned_as_a_variant(client, auth_headers):
    from uuid import uuid4

    suffix = uuid4().hex[:8].upper()
    model_no = f"BASE-MODEL-{suffix}"
    item = client.post(
        "/api/inventory/items",
        json={
            "sku": f"FAB-BASE-{suffix}",
            "name": f"Base fabric {suffix}",
            "category": "fabric",
            "unit": "kg",
            "default_cost": 2.5,
            "reorder_level": 0,
            "track_batch": True,
            "is_active": True,
            "composition": [{"name": "Cotton", "percentage": 100}],
        },
        headers=auth_headers,
    )
    assert item.status_code == 201, item.text

    model = client.post(
        "/api/models",
        json={
            "code": model_no,
            "name": "Model without variants",
            "category": "robe",
            "status": "draft",
            "details_json": {"general": {"model_no": model_no}},
        },
        headers=auth_headers,
    )
    assert model.status_code == 201, model.text
    model_id = model.json()["id"]
    bom = client.post(
        f"/api/models/{model_id}/bom",
        json={"item_id": item.json()["id"], "quantity_per_piece": 0.5, "unit": "kg"},
        headers=auth_headers,
    )
    assert bom.status_code == 201, bom.text

    variants = client.get(f"/api/models/{model_id}/variants", headers=auth_headers)
    assert variants.status_code == 200, variants.text
    assert variants.json() == []

    groups = client.get(
        f"/api/models/variant-groups?include_total=true&q={model_no}",
        headers=auth_headers,
    )
    assert groups.status_code == 200, groups.text
    group = next(row for row in groups.json()["rows"] if row["group_model_no"] == model_no)
    assert group["variant_count"] == 0
    assert group["variants"] == []

    created_variant = client.post(
        f"/api/models/{model_id}/variants",
        json={"variant_no": "V-1", "fabric_item_id": item.json()["id"]},
        headers=auth_headers,
    )
    assert created_variant.status_code == 201, created_variant.text

    variants = client.get(f"/api/models/{model_id}/variants", headers=auth_headers)
    assert variants.status_code == 200, variants.text
    assert [row["model_id"] for row in variants.json()] == [created_variant.json()["id"]]
    assert [row["variant_no"] for row in variants.json()] == ["V-1"]


def test_model_fabric_bom_normalizes_legacy_batch_to_master_item(client, auth_headers):
    from uuid import uuid4

    suffix = uuid4().hex[:8].upper()
    item = client.post(
        "/api/inventory/items",
        json={
            "sku": f"FAB-BOM-BATCH-{suffix}",
            "name": f"Batch BOM fabric {suffix}",
            "category": "fabric",
            "unit": "kg",
            "default_cost": 2.5,
            "reorder_level": 0,
            "track_batch": True,
            "is_active": True,
            "composition": [{"name": "Cotton", "percentage": 100}],
        },
        headers=auth_headers,
    )
    assert item.status_code == 201, item.text
    item_id = item.json()["id"]

    warehouses = client.get("/api/inventory/warehouses", headers=auth_headers)
    assert warehouses.status_code == 200, warehouses.text
    warehouse_id = next(row["id"] for row in warehouses.json() if row["type"] == "fabric_storage")

    receive = client.post(
        "/api/inventory/receive",
        json={
            "item_id": item_id,
            "batch_no": f"BOM-BATCH-{suffix}",
            "color": "Sky blue",
            "quantity": 20,
            "unit": "kg",
            "cost_per_unit": 2.5,
            "image_url": f"/storage/model-files/bom-batch-{suffix}.webp",
            "warehouse_id": warehouse_id,
            "qc_status": "passed",
        },
        headers=auth_headers,
    )
    assert receive.status_code == 201, receive.text
    batch = receive.json()

    model = client.post(
        "/api/models",
        json={
            "code": f"BOM-BATCH-MODEL-{suffix}",
            "name": "Batch BOM Model",
            "category": "blouse",
            "status": "draft",
        },
        headers=auth_headers,
    )
    assert model.status_code == 201, model.text
    model_id = model.json()["id"]

    bom = client.post(
        f"/api/models/{model_id}/bom",
        json={
            "item_id": item_id,
            "stock_batch_id": batch["id"],
            "quantity_per_piece": 0.42,
            "unit": "kg",
            "waste_percent": 2,
        },
        headers=auth_headers,
    )
    assert bom.status_code == 201, bom.text
    bom_id = bom.json()["id"]

    detail = client.get(f"/api/models/{model_id}", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    row = detail.json()["bom"][0]
    assert row["item_id"] == item_id
    assert row["stock_batch_id"] is None
    assert row["stock_batch_no"] is None
    assert row["stock_batch_image_url"] is None
    assert row["photo_url"] is None
    assert row["color"] is None

    update = client.patch(
        f"/api/models/{model_id}/bom/{bom_id}",
        json={"quantity_per_piece": 0.75, "waste_percent": 4, "size": "L", "color": "Navy"},
        headers=auth_headers,
    )
    assert update.status_code == 200, update.text

    updated_detail = client.get(f"/api/models/{model_id}", headers=auth_headers)
    assert updated_detail.status_code == 200, updated_detail.text
    updated_row = updated_detail.json()["bom"][0]
    assert updated_row["quantity_per_piece"] == 0.75
    assert updated_row["waste_percent"] == 4
    assert updated_row["size"] == "L"
    assert updated_row["color"] == "Navy"

    delete = client.delete(f"/api/models/{model_id}/bom/{bom_id}", headers=auth_headers)
    assert delete.status_code == 204, delete.text

    deleted_detail = client.get(f"/api/models/{model_id}", headers=auth_headers)
    assert deleted_detail.status_code == 200, deleted_detail.text
    assert deleted_detail.json()["bom"] == []


def test_brands_collections(client, auth_headers):
    r = client.get("/api/brands", headers=auth_headers)
    assert r.status_code == 200
    assert len(r.json()) >= 1
    r2 = client.get("/api/collections", headers=auth_headers)
    assert r2.status_code == 200
