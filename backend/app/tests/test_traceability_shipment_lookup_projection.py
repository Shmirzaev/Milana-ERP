from uuid import uuid4

from sqlalchemy import event

from app.api.routes.traceability import _find_shipment
from app.models import Shipment
from app.tests.conftest import TestSessionLocal


def test_shipment_lookup_projects_traceability_fields_and_preserves_lookup_forms():
    marker = uuid4().hex
    with TestSessionLocal() as db:
        by_number = Shipment(
            shipment_no=f"TRACE-PROJECTION-{marker}",
            status="shipped",
            notes="shipment note",
            dispatch_snapshot={"manual": True},
            transport_details={"driver": "unused by traceability"},
        )
        numeric_number = Shipment(shipment_no="999999999", status="created")
        db.add_all([by_number, numeric_number])
        db.commit()
        shipment_id = by_number.id
        numeric_number_id = numeric_number.id

        statements = []

        def capture(_conn, _cursor, statement, _params, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.get_bind(), "before_cursor_execute", capture)
        try:
            found_by_number = _find_shipment(db, by_number.shipment_no)
            found_by_id = _find_shipment(db, str(shipment_id))
            numeric_fallback = _find_shipment(db, "999999999")
            missing = _find_shipment(db, f"missing-{marker}")
        finally:
            event.remove(db.get_bind(), "before_cursor_execute", capture)

    assert found_by_number.id == found_by_id.id == shipment_id
    assert numeric_fallback.id == numeric_number_id
    assert missing is None
    shipment_queries = [sql for sql in statements if "from shipments" in sql]
    assert len(shipment_queries) == 5
    for statement in shipment_queries:
        projection = statement.split(" from shipments", 1)[0]
        assert "shipments.shipment_no" in projection
        assert "shipments.status" in projection
        assert "shipments.notes" in projection
        assert "shipments.transport_details" not in projection
        assert "shipments.dispatch_snapshot" not in projection
