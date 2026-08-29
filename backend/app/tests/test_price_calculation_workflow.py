from datetime import datetime, timezone

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import CuttingPassport, Department, Model, ModelImage, ModelSize, Role, User


PASSWORD = "PriceWorkflow123!"


def _login(client, email: str) -> dict[str, str]:
    response = client.post("/api/auth/token", data={"username": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _setup_workflow_data(suffix: str):
    db = SessionLocal()
    try:
        storage_department = db.query(Department).filter(Department.code == "STR").one()
        finance_department = db.query(Department).filter(Department.code == "FIN").one()
        sales_department = db.query(Department).filter(Department.code == "SLS").one()
        cutting_department = db.query(Department).filter(Department.code == "CUT").one()
        purchasing_role = Role(name=f"Price workflow purchaser {suffix}", permissions=["purchasing.view"])
        finance_role = Role(name=f"Price workflow finance {suffix}", permissions=["finance.view"])
        sales_role = Role(name=f"Price workflow sales {suffix}", permissions=["sales.orders"])
        accessory_role = Role(name=f"Price workflow accessories {suffix}", permissions=["storage.items"])
        cutting_role = Role(name=f"Price workflow cutting {suffix}", permissions=["cutting.records"])
        outsider_role = Role(name=f"Price workflow outsider {suffix}", permissions=[])
        db.add_all([purchasing_role, finance_role, sales_role, accessory_role, cutting_role, outsider_role])
        db.flush()
        users = [
            User(name=f"Abbosbek {suffix}", email=f"abbosbek.price.{suffix}@example.com", password_hash=hash_password(PASSWORD), role_id=purchasing_role.id, department_id=storage_department.id),
            User(name=f"Finance price {suffix}", email=f"finance.price.{suffix}@example.com", password_hash=hash_password(PASSWORD), role_id=finance_role.id, department_id=finance_department.id),
            User(name=f"Sales price {suffix}", email=f"sales.price.{suffix}@example.com", password_hash=hash_password(PASSWORD), role_id=sales_role.id, department_id=sales_department.id),
            User(name=f"Accessory price {suffix}", email=f"accessory.price.{suffix}@example.com", password_hash=hash_password(PASSWORD), role_id=accessory_role.id, department_id=storage_department.id),
            User(name=f"Cutting price {suffix}", email=f"cutting.price.{suffix}@example.com", password_hash=hash_password(PASSWORD), role_id=cutting_role.id, department_id=cutting_department.id),
            User(name=f"Outsider price {suffix}", email=f"outsider.price.{suffix}@example.com", password_hash=hash_password(PASSWORD), role_id=outsider_role.id),
        ]
        db.add_all(users)
        model = Model(
            code=f"PC-TEST-{suffix}-GRAY",
            name="Price workflow model",
            category="T-shirt",
            details_json={"general": {"model_no": "PC-TEST", "variant_no": "GRAY"}},
            status="approved",
        )
        db.add(model)
        db.flush()
        db.add_all([ModelSize(model_id=model.id, size="S"), ModelSize(model_id=model.id, size="M")])
        model_image_url = f"/storage/model-files/price-model-{suffix}.webp"
        variant_image_url = f"/storage/model-files/price-variant-{suffix}.webp"
        db.add_all([
            ModelImage(model_id=model.id, file_url=model_image_url, file_name=f"price-model-{suffix}.webp", content_type="image/webp", image_type="model", is_primary=True),
            ModelImage(model_id=model.id, file_url=variant_image_url, file_name=f"price-variant-{suffix}.webp", content_type="image/webp", image_type="material", is_primary=False),
        ])
        passport = CuttingPassport(
            passport_no=f"PC-KROY-{suffix}",
            date=datetime.now(timezone.utc),
            model_code=model.code,
            size_range="S, M",
            fabric_width_m=1.8,
            lay_length_m=3.37,
            gramage=0.191,
            beka_per_piece_kg=0.005,
            other_beka_per_piece_kg=0.002,
        )
        db.add(passport)
        db.commit()
        return {"model_id": model.id, "kroy_no": passport.passport_no, "model_image_url": model_image_url, "variant_image_url": variant_image_url}
    finally:
        db.close()


def test_price_calculation_department_workflow_and_authorization(client):
    data = _setup_workflow_data("one")
    finance = _login(client, "finance.price.one@example.com")
    sales = _login(client, "sales.price.one@example.com")
    purchaser = _login(client, "abbosbek.price.one@example.com")
    accessories = _login(client, "accessory.price.one@example.com")
    cutting = _login(client, "cutting.price.one@example.com")
    outsider = _login(client, "outsider.price.one@example.com")

    assert client.post(
        "/api/price-calculation/requests",
        json={"model_id": data["model_id"]},
        headers=finance,
    ).status_code == 403

    created = client.post("/api/price-calculation/requests", json={"model_id": data["model_id"]}, headers=sales)
    assert created.status_code == 201, created.text
    request = created.json()
    request_id = request["id"]
    assert request["model_no"] == "PC-TEST"
    assert request["variant_no"] == "GRAY"
    assert request["model_sizes"] == ["S", "M"]
    assert request["kroy_no"] is None
    assert request["model_image_url"] == data["model_image_url"]
    assert request["variant_image_url"] == data["variant_image_url"]
    assert request["cutting_status"] == "new"
    assert request["purchasing_status"] == "new"
    assert request["overall_status"] == "new"
    assert request["cost_price"] is None
    assert request["packaging_cost"] == 0.1
    finance_queue = client.get("/api/price-calculation/requests", headers=finance)
    assert finance_queue.status_code == 200, finance_queue.text
    assert any(row["id"] == request_id for row in finance_queue.json())

    early_selling_price = client.patch(
        f"/api/price-calculation/requests/{request_id}/finance",
        json={"selling_price": 2.0},
        headers=finance,
    )
    assert early_selling_price.status_code == 409, early_selling_price.text

    assert client.get("/api/price-calculation/requests", headers=outsider).status_code == 403
    assert client.patch(
        f"/api/price-calculation/requests/{request_id}/cutting",
        json={"kroy_no": data["kroy_no"]},
        headers=outsider,
    ).status_code == 403
    assert client.patch(
        f"/api/price-calculation/requests/{request_id}/purchasing",
        json={"fabric_price": 4.5, "sewing_cost": 0.1674},
        headers=outsider,
    ).status_code == 403

    cutting_update = client.patch(
        f"/api/price-calculation/requests/{request_id}/cutting",
        json={"kroy_no": data["kroy_no"]},
        headers=cutting,
    )
    assert cutting_update.status_code == 200, cutting_update.text
    request = cutting_update.json()
    assert request["cutting_status"] == "complete"
    assert request["cutting_passport_id"] is not None
    assert request["fabric_width_m"] == 1.8
    assert request["lay_length_m"] == 3.37
    assert request["size_count"] == 2
    assert request["gramage"] == 0.191
    assert request["binding_kg_per_piece"] == 0.007

    purchasing_update = client.patch(
        f"/api/price-calculation/requests/{request_id}/purchasing",
        json={"fabric_price": 4.5, "sewing_cost": 0.1674},
        headers=purchaser,
    )
    assert purchasing_update.status_code == 200, purchasing_update.text
    request = purchasing_update.json()
    assert request["purchasing_status"] == "complete"
    assert request["fabric_width_m"] == 1.8
    assert request["size_count"] == 2
    assert request["cost_price"] is None

    partial_accessory = client.patch(
        f"/api/price-calculation/requests/{request_id}/accessories",
        json={"accessories": [{"name": "Label", "price": None}]},
        headers=accessories,
    )
    assert partial_accessory.status_code == 200, partial_accessory.text
    assert partial_accessory.json()["accessories_status"] == "in_progress"
    assert partial_accessory.json()["overall_status"] == "in_progress"
    assert partial_accessory.json()["cost_price"] is None

    completed_accessory = client.patch(
        f"/api/price-calculation/requests/{request_id}/accessories",
        json={"accessories": [{"name": "Label", "price": 0.05}]},
        headers=accessories,
    )
    assert completed_accessory.status_code == 200, completed_accessory.text
    request = completed_accessory.json()
    assert request["accessories_status"] == "complete"
    assert request["accessories"] == [{"name": "Label", "price": 0.05}]
    assert request["cost_price"] is not None
    assert request["overall_status"] == "in_progress"

    finalized = client.patch(
        f"/api/price-calculation/requests/{request_id}/finance",
        json={"selling_price": 2.0},
        headers=finance,
    )
    assert finalized.status_code == 200, finalized.text
    request = finalized.json()
    assert request["overall_status"] == "complete"
    assert request["difference"] is not None


def test_cutting_can_enter_details_manually_when_kroy_is_not_in_passports(client):
    data = _setup_workflow_data("two")
    sales = _login(client, "sales.price.two@example.com")
    cutting = _login(client, "cutting.price.two@example.com")
    created = client.post(
        "/api/price-calculation/requests",
        json={"model_id": data["model_id"]},
        headers=sales,
    )
    assert created.status_code == 201, created.text
    manual = client.patch(
        f"/api/price-calculation/requests/{created.json()['id']}/cutting",
        json={
            "kroy_no": "NOT-FOUND",
            "fabric_width_m": 1.72,
            "lay_length_m": 3.1,
            "size_count": 3,
            "gramage": 0.185,
            "binding_kg_per_piece": 0,
        },
        headers=cutting,
    )
    assert manual.status_code == 200, manual.text
    request = manual.json()
    assert request["cutting_status"] == "complete"
    assert request["cutting_passport_id"] is None
    assert request["kroy_no"] == "NOT-FOUND"
    assert request["fabric_width_m"] == 1.72
    assert request["binding_kg_per_piece"] == 0


def test_purchasing_cannot_change_cutting_kroy_number(client):
    data = _setup_workflow_data("three")
    sales = _login(client, "sales.price.three@example.com")
    purchaser = _login(client, "abbosbek.price.three@example.com")
    cutting = _login(client, "cutting.price.three@example.com")
    created = client.post(
        "/api/price-calculation/requests",
        json={"model_id": data["model_id"]},
        headers=sales,
    )
    assert created.status_code == 201, created.text
    cutting_update = client.patch(
        f"/api/price-calculation/requests/{created.json()['id']}/cutting",
        json={"kroy_no": data["kroy_no"]},
        headers=cutting,
    )
    assert cutting_update.status_code == 200, cutting_update.text
    denied = client.patch(
        f"/api/price-calculation/requests/{created.json()['id']}/purchasing",
        json={"kroy_no": "CHANGED", "fabric_price": 4.5, "sewing_cost": 0.2},
        headers=purchaser,
    )
    assert denied.status_code == 422, denied.text
