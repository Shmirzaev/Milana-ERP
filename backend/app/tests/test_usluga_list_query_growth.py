from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes import usluga
from app.db.session import SessionLocal
from app.models import (
    Department,
    Model,
    ModelColor,
    ModelImage,
    ModelSize,
    Package,
    ProductionOrder,
    ProductionOrderItem,
    WorkOrder,
)


def _eco_user():
    return SimpleNamespace(
        role=SimpleNamespace(name=""),
        extra_permissions=[],
        factory_code="ECO",
        session_factory_code="ECO",
    )


def _select_trace(db, call):
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        result = call()
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)
    return result, statements


def _order_set(db, count):
    suffix = uuid4().hex[:8]
    status = f"perf22-{suffix}"
    models = [
        Model(
            code=f"PERF22-M-{suffix}-{number}",
            name=f"Usluga list model {number}",
            catalog_scope="usluga",
            factory_code="ECO",
            category="Service",
            status="approved",
        )
        for number in range(2 if count > 1 else 1)
    ]
    orphan_model = Model(
        code=f"PERF22-ORPHAN-{suffix}",
        name="Legacy non-Usluga model",
        catalog_scope="standard",
        factory_code="MIL",
        status="approved",
    )
    db.add_all([*models, orphan_model])
    db.flush()
    db.add_all([
        *[
            ModelImage(
                model_id=model.id,
                file_url=f"/storage/model-files/perf22-{suffix}-{number}.webp",
                file_name=f"perf22-{number}.webp",
                content_type="image/webp",
                file_data=b"binary-image-must-stay-deferred",
                image_type="model",
                is_primary=True,
            )
            for number, model in enumerate(models)
        ],
        *[ModelSize(model_id=model.id, size="M") for model in models],
        *[ModelColor(model_id=model.id, color_name="Natural") for model in models],
    ])
    department_id = db.query(Department.id).filter(Department.code == "ECP").scalar()
    orders = [
        ProductionOrder(
            production_no=f"PERF22-PO-{suffix}-{number:04d}",
            production_type="service_order",
            source_type="usluga",
            model_id=(
                orphan_model.id
                if count == 401 and number == count - 1
                else models[number % len(models)].id
            ),
            status=status,
            planned_quantity=1,
            service_customer_name=f"Customer {number}",
        )
        for number in range(count)
    ]
    db.add_all(orders)
    db.flush()
    db.add_all([
        *[
            ProductionOrderItem(
                production_order_id=order.id,
                model_id=order.model_id,
                color="Natural",
                size="M",
                planned_quantity=1,
                printing_required=False,
            )
            for order in orders
        ],
        *[
            WorkOrder(
                production_order_id=order.id,
                department_id=department_id,
                operation="packaging",
                status="completed",
                planned_input_qty=1,
                planned_output_qty=1,
                passed_qty=1,
            )
            for order in orders
        ],
        *[
            Package(
                package_no=f"PERF22-PKG-{suffix}-{number:04d}",
                barcode=f"PERF22-BC-{suffix}-{number:04d}",
                packaging_department_code="ECP",
                production_order_id=order.id,
                model_id=order.model_id,
                color="Natural",
                total_quantity=1,
                capacity=60,
                status="packed",
            )
            for number, order in enumerate(orders)
        ],
    ])
    db.commit()
    return status, [order.id for order in orders]


@pytest.mark.parametrize(("order_count", "expected_selects"), [(1, 8), (50, 8), (401, 11)])
def test_usluga_order_list_preloads_are_chunk_bounded_without_image_blobs(order_count, expected_selects):
    with SessionLocal() as db:
        status, order_ids = _order_set(db, order_count)
    with SessionLocal() as db:
        payload, statements = _select_trace(
            db,
            lambda: usluga.list_usluga_orders(db, _eco_user(), status=status),
        )

    assert len(statements) == expected_selects
    assert [row["id"] for row in payload] == list(reversed(order_ids))
    assert all(row["items"] == [{
        "id": row["items"][0]["id"],
        "color": "Natural",
        "size": "M",
        "planned_quantity": 1,
    }] for row in payload)
    assert all(row["work_orders"][0]["operation"] == "packaging" for row in payload)
    assert all(row["package_count"] == 1 and row["package_quantity"] == 1 for row in payload)
    assert "file_data" not in "\n".join(statements).lower()
    if order_count == 401:
        assert payload[0]["model"] is None
        assert all(row["model"]["image_url"].endswith(".webp") for row in payload[1:])
        assert len({row["model"]["id"] for row in payload[1:]}) == 2


def test_usluga_order_list_preserves_status_filter_and_empty_result():
    with SessionLocal() as db:
        status, order_ids = _order_set(db, 2)
    with SessionLocal() as db:
        payload = usluga.list_usluga_orders(db, _eco_user(), status=status)
        empty, statements = _select_trace(
            db,
            lambda: usluga.list_usluga_orders(db, _eco_user(), status=f"missing-{status}"),
        )

    assert [row["id"] for row in payload] == list(reversed(order_ids))
    assert empty == []
    assert len(statements) == 1


def test_usluga_order_list_chunks_distinct_models_and_assets_at_400():
    suffix = uuid4().hex[:8]
    status = f"perf22-models-{suffix}"
    with SessionLocal() as db:
        models = [
            Model(
                code=f"PERF22-DISTINCT-{suffix}-{number:04d}",
                name=f"Distinct model {number}",
                catalog_scope="usluga",
                factory_code="ECO",
                status="approved",
            )
            for number in range(401)
        ]
        db.add_all(models)
        db.flush()
        db.add_all([
            *[
                ModelImage(
                    model_id=model.id,
                    file_url=f"/storage/model-files/perf22-distinct-{suffix}-{number}.webp",
                    file_data=b"distinct-binary-image-must-stay-deferred",
                    image_type="model",
                    is_primary=True,
                )
                for number, model in enumerate(models)
            ],
            *[ModelSize(model_id=model.id, size="L") for model in models],
            *[ModelColor(model_id=model.id, color_name="Blue") for model in models],
        ])
        orders = [
            ProductionOrder(
                production_no=f"PERF22-DISTINCT-PO-{suffix}-{number:04d}",
                production_type="service_order",
                source_type="usluga",
                model_id=model.id,
                status=status,
                planned_quantity=1,
            )
            for number, model in enumerate(models)
        ]
        db.add_all(orders)
        db.commit()
        order_ids = [int(order.id) for order in orders]

    with SessionLocal() as db:
        payload, statements = _select_trace(
            db,
            lambda: usluga.list_usluga_orders(db, _eco_user(), status=status),
        )

    assert len(statements) == 15
    assert [row["id"] for row in payload] == list(reversed(order_ids))
    assert all(row["model"]["sizes"] == ["L"] for row in payload)
    assert all(row["model"]["colors"] == ["Blue"] for row in payload)
    assert all(row["model"]["image_url"].endswith(".webp") for row in payload)
    assert "file_data" not in "\n".join(statements).lower()


def test_usluga_order_list_matches_scalar_payloads_for_mixed_rows():
    with SessionLocal() as db:
        original_status, order_ids = _order_set(db, 4)
        status_a = f"{original_status}-a"
        status_b = f"{original_status}-b"
        orders = (
            db.query(ProductionOrder)
            .filter(ProductionOrder.id.in_(order_ids))
            .order_by(ProductionOrder.id)
            .all()
        )
        for number, order in enumerate(orders):
            order.status = status_a if number % 2 == 0 else status_b
        work_orders = (
            db.query(WorkOrder)
            .filter(WorkOrder.production_order_id.in_(order_ids))
            .order_by(WorkOrder.production_order_id)
            .all()
        )
        for work_order, state in zip(work_orders, ("completed", "waiting", "in_progress", "rejected")):
            work_order.status = state
            work_order.passed_qty = 1 if state == "completed" else 0
        second_package = db.query(Package).filter(Package.production_order_id == orders[1].id).one()
        db.delete(second_package)
        db.add_all([
            ProductionOrderItem(
                production_order_id=orders[2].id,
                model_id=orders[2].model_id,
                color="Black",
                size="L",
                planned_quantity=2,
                printing_required=False,
            ),
            Package(
                package_no=f"PERF22-MIXED-PKG-{uuid4().hex[:8]}",
                barcode=f"PERF22-MIXED-BC-{uuid4().hex[:8]}",
                packaging_department_code="ECP",
                production_order_id=orders[2].id,
                model_id=orders[2].model_id,
                color="Black",
                total_quantity=2,
                capacity=60,
                status="damaged",
            ),
        ])
        db.commit()

    for status in (status_a, status_b):
        with SessionLocal() as db:
            scalar_orders = (
                db.query(ProductionOrder)
                .filter(
                    ProductionOrder.source_type == "usluga",
                    ProductionOrder.status == status,
                )
                .order_by(ProductionOrder.id.desc())
                .all()
            )
            expected = [usluga._order_payload(db, order) for order in scalar_orders]
        with SessionLocal() as db:
            actual = usluga.list_usluga_orders(db, _eco_user(), status=status)

        assert actual == expected


def test_usluga_order_list_pagination_has_total_and_preserves_order():
    with SessionLocal() as db:
        status, order_ids = _order_set(db, 5)
    with SessionLocal() as db:
        payload, statements = _select_trace(
            db,
            lambda: usluga.list_usluga_orders(
                db, _eco_user(), status=status, page=2, page_size=2
            ),
        )

    assert payload["total"] == 5
    assert payload["page"] == 2
    assert payload["page_size"] == 2
    assert [row["id"] for row in payload["rows"]] == list(reversed(order_ids))[2:4]
    # One count plus bounded parent/child/model reads; no query may contain
    # an unbounded parent SELECT.
    assert any("count" in statement.lower() for statement in statements)
    parent = [statement.lower() for statement in statements if "production_orders" in statement.lower()]
    assert parent and all(" limit " in statement for statement in parent if "count" not in statement)


def test_usluga_order_list_legacy_response_remains_unpaged():
    with SessionLocal() as db:
        status, _ = _order_set(db, 501)
    with SessionLocal() as db:
        payload = usluga.list_usluga_orders(db, _eco_user(), status=status)

    assert isinstance(payload, list)
    assert len(payload) == 501
