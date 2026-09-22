from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes import price_calculation
from app.db.session import SessionLocal
from app.models import (
    CuttingPassport,
    Item,
    Model,
    ModelBOM,
    ModelImage,
    ModelSize,
    PriceCalculationRequest,
    StockBatch,
    User,
    Warehouse,
)


def _select_trace(db, call):
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        result = call()
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)
    return result, statements


def _request_set(db, count):
    suffix = uuid4().hex[:8]
    admin = db.query(User).filter_by(email="admin@example.com").one()
    models = [
        Model(
            code=f"PERF23-M-{suffix}-{number:04d}", name=f"Price model {number}",
            category="T-shirt", status="approved",
        )
        for number in range(count)
    ]
    db.add_all(models)
    db.flush()
    requests = [
        PriceCalculationRequest(model_id=model.id, created_by_id=admin.id)
        for model in models
    ]
    db.add_all([
        *requests,
        *[ModelSize(model_id=model.id, size="M") for model in models],
        *[
            ModelImage(
                model_id=model.id,
                file_url=f"/storage/model-files/perf23-model-{suffix}-{number}.webp",
                file_name=f"perf23-model-{number}.webp", content_type="image/webp",
                file_data=b"binary-model-image-must-stay-deferred",
                image_type="model", is_primary=True,
            )
            for number, model in enumerate(models)
        ],
        *[
            ModelImage(
                model_id=model.id,
                file_url=f"/storage/model-files/perf23-material-{suffix}-{number}.webp",
                file_name=f"perf23-material-{number}.webp", content_type="image/webp",
                file_data=b"binary-material-image-must-stay-deferred",
                image_type="material", is_primary=False,
            )
            for number, model in enumerate(models)
        ],
    ])
    db.commit()
    return admin.id, [request.id for request in requests]


@pytest.mark.parametrize(
    ("request_count", "expected_rows", "expected_selects"),
    [(1, 1, 4), (50, 50, 4), (501, 500, 4)],
)
def test_price_request_list_assets_are_selectin_chunked_without_blobs(
    request_count, expected_rows, expected_selects,
):
    with SessionLocal() as db:
        admin_id, request_ids = _request_set(db, request_count)
    with SessionLocal() as db:
        admin = db.get(User, admin_id)
        payload, statements = _select_trace(
            db, lambda: price_calculation.list_requests(db, admin),
        )

    assert len(statements) == expected_selects
    assert [row["id"] for row in payload] == list(reversed(request_ids))[:expected_rows]
    assert len(payload) == expected_rows
    assert all(row["model_sizes"] == ["M"] for row in payload)
    assert all("perf23-model" in row["model_image_url"] for row in payload)
    assert all("perf23-material" in row["variant_image_url"] for row in payload)
    assert "file_data" not in "\n".join(statements).lower()


def test_price_request_list_preserves_asset_fallbacks_and_calculated_payload():
    suffix = uuid4().hex[:8]
    with SessionLocal() as db:
        admin = db.query(User).filter_by(email="admin@example.com").one()
        fabric = Item(
            sku=f"PERF23-I-{suffix}", name="Price fabric", category="fabric", unit="kg",
            image_url=f"/storage/model-files/perf23-item-{suffix}.webp",
        )
        batch_fabric = Item(
            sku=f"PERF23-BI-{suffix}", name="Batch image fabric", category="fabric", unit="kg",
        )
        models = [
            Model(code=f"PERF23-P-{suffix}", name="Primary", category="T-shirt", status="approved"),
            Model(code=f"PERF23-T-{suffix}", name="Typed material", category="T-shirt", status="approved"),
            Model(code=f"PERF23-B-{suffix}", name="BOM photo", category="T-shirt", status="approved"),
            Model(code=f"PERF23-S-{suffix}", name="Batch fallback", category="T-shirt", status="approved"),
            Model(code=f"PERF23-I-{suffix}", name="Item fallback", category="T-shirt", status="approved"),
        ]
        db.add_all([fabric, batch_fabric, *models])
        db.flush()
        warehouse_id = db.query(Warehouse.id).order_by(Warehouse.id).first()[0]
        batch = StockBatch(
            item_id=batch_fabric.id, batch_no=f"PERF23-BATCH-{suffix}", quantity=1,
            unit="kg", cost_per_unit=1, warehouse_id=warehouse_id, qc_status="passed",
            image_url=f"/storage/model-files/perf23-batch-{suffix}.webp",
        )
        db.add(batch)
        db.flush()
        db.add_all([
            ModelSize(model_id=models[0].id, size="S"),
            ModelSize(model_id=models[0].id, size="M"),
            ModelSize(model_id=models[0].id, size="S"),
            ModelImage(
                model_id=models[0].id, file_url=f"/storage/model-files/perf23-primary-{suffix}.webp",
                file_name="primary.webp", content_type="image/webp", file_data=b"primary",
                image_type="model", is_primary=True,
            ),
            ModelImage(
                model_id=models[0].id, file_url=f"/storage/model-files/perf23-secondary-{suffix}.webp",
                file_name="secondary.webp", content_type="image/webp", file_data=b"secondary",
                image_type="material", is_primary=False,
            ),
            ModelImage(
                model_id=models[1].id, file_url=f"/storage/model-files/perf23-material-{suffix}.webp",
                file_name="material.webp", content_type="image/webp", file_data=b"material",
                image_type="material", is_primary=False,
            ),
            ModelBOM(
                model_id=models[2].id, item_id=fabric.id,
                photo_url=f"/storage/model-files/perf23-bom-{suffix}.webp",
                quantity_per_piece=1, unit="kg", waste_percent=0,
            ),
            ModelBOM(
                model_id=models[3].id, item_id=batch_fabric.id, stock_batch_id=batch.id,
                quantity_per_piece=1, unit="kg", waste_percent=0,
            ),
            ModelBOM(
                model_id=models[4].id, item_id=fabric.id,
                quantity_per_piece=1, unit="kg", waste_percent=0,
            ),
        ])
        passport = CuttingPassport(
            passport_no=f"PERF23-CP-{suffix}", date=datetime(2026, 9, 20, tzinfo=timezone.utc),
        )
        db.add(passport)
        db.flush()
        requests = [
            PriceCalculationRequest(
                model_id=model.id, created_by_id=admin.id,
                kroy_no=passport.passport_no if number == 0 else None,
                cutting_passport_id=passport.id if number == 0 else None,
                fabric_width_m=2 if number == 0 else None,
                lay_length_m=2 if number == 0 else None,
                size_count=2 if number == 0 else None,
                gramage=.5 if number == 0 else None,
                binding_kg_per_piece=.1 if number == 0 else None,
                fabric_price=4 if number == 0 else None,
                sewing_cost=1 if number == 0 else None,
                accessories_json=[{"name": "Label", "price": .5}] if number == 0 else [],
                selling_price=7 if number == 0 else None,
            )
            for number, model in enumerate(models)
        ]
        requests.append(PriceCalculationRequest(model_id=models[0].id, created_by_id=admin.id))
        db.add_all(requests)
        db.commit()
        admin_id = admin.id
        request_ids = [request.id for request in requests]

    with SessionLocal() as db:
        payload = price_calculation.list_requests(db, db.get(User, admin_id))
    by_id = {row["id"]: row for row in payload}
    assert [row["id"] for row in payload] == list(reversed(request_ids))
    assert by_id[request_ids[0]]["model_sizes"] == ["S", "M"]
    assert by_id[request_ids[0]]["model_image_url"] == f"/storage/model-files/perf23-primary-{suffix}.webp"
    assert by_id[request_ids[0]]["variant_image_url"] == f"/storage/model-files/perf23-secondary-{suffix}.webp"
    assert by_id[request_ids[1]]["variant_image_url"] == f"/storage/model-files/perf23-material-{suffix}.webp"
    assert by_id[request_ids[2]]["variant_image_url"] == f"/storage/model-files/perf23-bom-{suffix}.webp"
    assert by_id[request_ids[3]]["variant_image_url"] == f"/storage/model-files/perf23-batch-{suffix}.webp"
    assert by_id[request_ids[4]]["variant_image_url"] == f"/storage/model-files/perf23-item-{suffix}.webp"
    calculated = by_id[request_ids[0]]
    assert calculated["date"].date() == datetime(2026, 9, 20, tzinfo=timezone.utc).date()
    assert calculated["cutting_status"] == "complete"
    assert calculated["purchasing_status"] == "complete"
    assert calculated["accessories_status"] == "complete"
    assert calculated["overall_status"] == "complete"
    assert calculated["cost_price"] == 6.0
    assert calculated["difference"] == 1.0


def test_price_request_list_requires_authentication(client):
    response = client.get("/api/price-calculation/requests")
    assert response.status_code == 401


def test_price_request_list_enforces_bounded_limit(client, auth_headers):
    response = client.get(
        "/api/price-calculation/requests?limit=501",
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_price_request_list_http_pagination_shape(client, auth_headers):
    response = client.get(
        "/api/price-calculation/requests?page=1&page_size=2",
        headers=auth_headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"items", "total", "page", "page_size", "has_more"}
    assert payload["page"] == 1
    assert payload["page_size"] == 2
    assert len(payload["items"]) <= 2


def test_price_request_list_pagination_returns_metadata_and_disjoint_pages():
    with SessionLocal() as db:
        admin = db.query(User).filter_by(email="admin@example.com").one()
        _, request_ids = _request_set(db, 3)
        first = price_calculation.list_requests(db, admin, page=1, page_size=2)
        second = price_calculation.list_requests(db, admin, page=2, page_size=2)

    assert first["total"] >= 3
    assert first["page"] == 1
    assert first["page_size"] == 2
    assert first["has_more"] is True
    assert len(first["items"]) == 2
    assert second["page"] == 2
    assert second["has_more"] == (2 * second["page_size"] < second["total"])
    assert set(row["id"] for row in first["items"]).isdisjoint(row["id"] for row in second["items"])
    assert [row["id"] for row in first["items"] + second["items"]][:3] == list(reversed(request_ids))
