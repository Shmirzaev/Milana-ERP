"""Generic production-order creation only accepts its two standard order types."""

from datetime import datetime, timezone

import pytest

from app.db.session import SessionLocal
from app.api.routes.planning import router as planning_router
from app.api.routes.production import router as production_router
from app.schemas import AuditLog, ProductionOrder
from app.libs.dto.production.production import (
    BrandedStockProductionOrderCreateOut,
    ClientOrderProductionOrderCreateOut,
    ProductionOrderIn,
    ProductionOrderDetail,
    ProductionOrderOut,
    StandardProductionOrderCreateDetail,
)
from app.libs.enums.production import ProductionSourceType, ProductionType


def _write_counts() -> tuple[int, int]:
    with SessionLocal() as db:
        return db.query(ProductionOrder).count(), db.query(AuditLog).count()


@pytest.mark.parametrize("production_type", ["service_order", "other", "", None])
def test_generic_production_order_rejects_unsupported_type_before_writes(
    client, auth_headers, production_type,
):
    payload = {"production_type": production_type, "model_id": 1}
    before = _write_counts()

    unauthenticated = client.post("/api/production-orders", json=payload)
    assert unauthenticated.status_code == 401, unauthenticated.text
    assert _write_counts() == before

    rejected = client.post("/api/production-orders", headers=auth_headers, json=payload)
    assert rejected.status_code == 422, rejected.text
    assert _write_counts() == before


def test_generic_production_type_openapi_vocabulary():
    choices = ProductionOrderIn.model_json_schema()["properties"]["production_type"]["enum"]
    assert choices == ["client_order", "branded_stock"]


def test_production_type_contract_is_enum_typed_without_widening_creation_subset():
    value = ProductionOrderIn(production_type="branded_stock", model_id=1)
    assert value.production_type is ProductionType.BRANDED_STOCK
    assert ProductionOrderIn.model_fields["production_type"].annotation is ProductionType

    with pytest.raises(ValueError, match="client_order or branded_stock"):
        ProductionOrderIn(production_type=ProductionType.SERVICE_ORDER, model_id=1)

    output_fields = ProductionOrderOut.model_fields
    assert output_fields["production_type"].annotation is str
    assert output_fields["source_type"].annotation is ProductionSourceType
    legacy_read = ProductionOrderOut.model_validate({
        "id": 1,
        "production_no": "LEGACY-1",
        "production_type": "historic-import-kind",
        "model_id": 1,
        "status": "historically-stored",
        "planned_quantity": 1,
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    })
    assert legacy_read.production_type == "historic-import-kind"
    assert legacy_read.model_dump(mode="json")["production_type"] == "historic-import-kind"
    legacy_detail = ProductionOrderDetail.model_validate({
        "id": 4,
        "production_no": "LEGACY-DETAIL-1",
        "production_type": "historic-detail-kind",
        "model_id": 1,
        "status": "historically-stored",
        "planned_quantity": 1,
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    })
    assert legacy_detail.production_type == "historic-detail-kind"
    assert legacy_detail.model_dump(mode="json")["production_type"] == "historic-detail-kind"
    assert ProductionOrderDetail.model_fields["production_type"].annotation is str
    output_schema = ProductionOrderOut.model_json_schema()
    output_properties = output_schema["properties"]
    assert output_properties["production_type"]["type"] == "string"
    assert "enum" not in output_properties["production_type"]

    def enum_values(name):
        prop = output_properties[name]
        if "enum" in prop:
            return prop["enum"]
        if "$ref" in prop:
            definition_name = prop["$ref"].rsplit("/", 1)[-1]
            return output_schema["$defs"][definition_name]["enum"]
        return prop["enum"]

    assert enum_values("source_type") == ["standard", "usluga"]

    create_fields = BrandedStockProductionOrderCreateOut.model_fields
    assert create_fields["production_type"].annotation is ProductionType
    assert create_fields["source_type"].annotation is ProductionSourceType
    create_schema = BrandedStockProductionOrderCreateOut.model_json_schema()
    assert create_schema["properties"]["production_type"]["enum"] == ["branded_stock"]
    assert create_schema["properties"]["source_type"]["enum"] == ["standard"]
    create_read = BrandedStockProductionOrderCreateOut.model_validate({
        "id": 2,
        "production_no": "PO-000002",
        "production_type": "branded_stock",
        "model_id": 1,
        "status": "planning",
        "planned_quantity": 1,
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    })
    assert create_read.production_type is ProductionType.BRANDED_STOCK
    assert create_read.source_type is ProductionSourceType.STANDARD
    with pytest.raises(ValueError, match="branded-stock create output"):
        BrandedStockProductionOrderCreateOut.model_validate({
            "id": 3,
            "production_no": "USL-000001",
            "production_type": "service_order",
            "model_id": 1,
            "status": "new",
            "planned_quantity": 1,
            "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        })
    with pytest.raises(ValueError, match="branded-stock create output requires standard source"):
        BrandedStockProductionOrderCreateOut.model_validate({
            "id": 5,
            "production_no": "PO-000005",
            "production_type": "branded_stock",
            "source_type": "usluga",
            "model_id": 1,
            "status": "planning",
            "planned_quantity": 1,
            "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        })

    client_create_fields = ClientOrderProductionOrderCreateOut.model_fields
    assert client_create_fields["production_type"].annotation is ProductionType
    assert client_create_fields["source_type"].annotation is ProductionSourceType
    client_create_schema = ClientOrderProductionOrderCreateOut.model_json_schema()
    assert client_create_schema["properties"]["production_type"]["enum"] == ["client_order"]
    assert client_create_schema["properties"]["source_type"]["enum"] == ["standard"]
    client_create = ClientOrderProductionOrderCreateOut.model_validate({
        "id": 6,
        "production_no": "PO-000006",
        "production_type": "client_order",
        "source_type": "standard",
        "model_id": 1,
        "status": "planning",
        "planned_quantity": 1,
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    })
    assert client_create.production_type is ProductionType.CLIENT_ORDER
    with pytest.raises(ValueError, match="client-order create output"):
        ClientOrderProductionOrderCreateOut.model_validate({
            "id": 7,
            "production_no": "PO-000007",
            "production_type": "branded_stock",
            "model_id": 1,
            "status": "planning",
            "planned_quantity": 1,
            "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        })

    generic_create_fields = StandardProductionOrderCreateDetail.model_fields
    assert generic_create_fields["production_type"].annotation is ProductionType
    assert generic_create_fields["source_type"].annotation is ProductionSourceType
    generic_create_schema = StandardProductionOrderCreateDetail.model_json_schema()
    assert generic_create_schema["properties"]["production_type"]["enum"] == [
        "client_order", "branded_stock",
    ]
    assert generic_create_schema["properties"]["source_type"]["enum"] == ["standard"]
    generic_create = StandardProductionOrderCreateDetail.model_validate({
        "id": 8,
        "production_no": "PO-000008",
        "production_type": "branded_stock",
        "source_type": "standard",
        "model_id": 1,
        "status": "planning",
        "planned_quantity": 1,
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    })
    assert generic_create.production_type is ProductionType.BRANDED_STOCK
    for created, expected_type in (
        (create_read, "branded_stock"),
        (client_create, "client_order"),
        (generic_create, "branded_stock"),
    ):
        assert created.source_type is ProductionSourceType.STANDARD
        wire = created.model_dump(mode="json")
        assert wire["production_type"] == expected_type
        assert wire["source_type"] == "standard"
        assert type(wire["production_type"]) is str
        assert type(wire["source_type"]) is str
        omitted_source = type(created).model_validate({
            key: value for key, value in wire.items() if key != "source_type"
        })
        assert omitted_source.source_type is ProductionSourceType.STANDARD
    with pytest.raises(ValueError, match="standard production-order create output"):
        StandardProductionOrderCreateDetail.model_validate({
            "id": 9,
            "production_no": "USL-000009",
            "production_type": "service_order",
            "source_type": "usluga",
            "model_id": 1,
            "status": "new",
            "planned_quantity": 1,
            "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        })

    branded_create_route = next(
        route for route in planning_router.routes
        if getattr(route, "path", None) == "/planning/create-branded-production"
    )
    assert branded_create_route.response_model is BrandedStockProductionOrderCreateOut
    client_create_route = next(
        route for route in planning_router.routes
        if getattr(route, "path", None) == "/planning/create-production-order"
    )
    assert client_create_route.response_model is ClientOrderProductionOrderCreateOut
    generic_create_route = next(
        route for route in production_router.routes
        if getattr(route, "path", None) == "/production-orders"
        and "POST" in getattr(route, "methods", set())
    )
    assert generic_create_route.response_model is StandardProductionOrderCreateDetail
    detail_get_route = next(
        route for route in production_router.routes
        if getattr(route, "path", None) == "/production-orders/{pid}"
        and "GET" in getattr(route, "methods", set())
    )
    assert detail_get_route.response_model is ProductionOrderDetail
