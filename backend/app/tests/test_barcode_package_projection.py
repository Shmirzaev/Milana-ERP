from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.api.routes.barcode import package_qr
from app.models import Model, Package, ProductionOrder
from app.tests.conftest import TestSessionLocal


def test_package_qr_projects_only_response_fields_and_preserves_not_found():
    marker = uuid4().hex
    with TestSessionLocal() as db:
        model = Model(code=f"QR-PROJECTION-{marker}", name="QR projection model")
        db.add(model)
        db.flush()
        production_order = ProductionOrder(
            production_no=f"QR-PROJECTION-{marker}",
            production_type="client_order",
            model_id=model.id,
        )
        db.add(production_order)
        db.flush()
        package = Package(
            package_no=f"PKG-PROJECTION-{marker}",
            barcode=f"BAR-PROJECTION-{marker}",
            qr_code_url=f"/qr/{marker}",
            production_order_id=production_order.id,
            model_id=model.id,
            color="navy",
            total_quantity=12,
            notes="unused package note" * 20,
        )
        db.add(package)
        db.commit()

        statements = []

        def capture(_conn, _cursor, statement, _params, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement.lower())

        event.listen(db.get_bind(), "before_cursor_execute", capture)
        try:
            result = package_qr(package.package_no, db, None)
        finally:
            event.remove(db.get_bind(), "before_cursor_execute", capture)

        with pytest.raises(HTTPException) as exc_info:
            package_qr(f"missing-{marker}", db, None)

    assert result == {
        "qr_code_url": f"/qr/{marker}",
        "barcode": f"BAR-PROJECTION-{marker}",
        "package_no": f"PKG-PROJECTION-{marker}",
    }
    assert exc_info.value.status_code == 404
    package_query = next(sql for sql in statements if "from packages" in sql)
    selected_columns = package_query.split(" from packages", 1)[0]
    assert "packages.qr_code_url" in selected_columns
    assert "packages.barcode" in selected_columns
    assert "packages.package_no" in selected_columns
    assert "packages.notes" not in selected_columns
    assert "packages.items" not in package_query
