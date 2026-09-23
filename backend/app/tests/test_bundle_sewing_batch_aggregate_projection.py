from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import event

from app.api.routes.bundles import _sewing_batch_payload
from app.models import Bundle, Model, ProductionBatch, ProductionOrder
from app.tests.conftest import TestSessionLocal


def test_sewing_batch_payload_aggregates_bundle_rows_in_database():
    marker = uuid4().hex
    with TestSessionLocal() as db:
        model = Model(
            code=f"SEW-AGG-{marker}",
            name=f"Sewing aggregate {marker}",
            product_type="shirt",
            status="approved",
        )
        db.add(model)
        db.flush()
        order = ProductionOrder(
            production_no=f"SEW-AGG-PO-{marker}",
            production_type="client_order",
            model_id=model.id,
            planned_quantity=20,
            status="sewing",
        )
        db.add(order)
        db.flush()
        batch = ProductionBatch(
            production_order_id=order.id,
            batch_no=f"AGG-{marker[:12]}",
            batch_index=1,
            name="Aggregate test",
            planned_quantity=20,
        )
        db.add(batch)
        db.flush()
        db.add_all(
            [
                Bundle(
                    bundle_no=f"SEW-AGG-BND-{marker}-{index}",
                    barcode=f"SEW-AGG-BC-{marker}-{index}",
                    production_order_id=order.id,
                    production_batch_id=batch.id,
                    model_id=model.id,
                    color="navy",
                    size="M",
                    quantity=quantity,
                    status=status,
                )
                for index, (status, quantity) in enumerate(
                    (("created", 3), ("created", 4), ("sent_to_sewing", 4), ("cancelled", 10))
                )
            ]
        )
        db.commit()

        statements: list[str] = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select"):
                statements.append(normalized)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            payload = _sewing_batch_payload(
                db,
                SimpleNamespace(id=batch.id, production_order_id=order.id),
            )
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert payload["bundle_count"] == 3
    assert payload["quantity"] == 11
    assert payload["status_counts"] == {"created": 2, "sent_to_sewing": 1}

    bundle_query = next(statement for statement in statements if " from bundles " in statement)
    assert "group by bundles.status" in bundle_query
    assert "count(bundles.id)" in bundle_query
    assert "sum(bundles.quantity)" in bundle_query
    assert "bundles.bundle_no" not in bundle_query
