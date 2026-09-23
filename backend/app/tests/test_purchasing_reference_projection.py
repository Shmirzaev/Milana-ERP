"""Purchasing reference validation needs only identifier columns."""
import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.models import Supplier, Warehouse
from app.services.purchasing import _require_supplier, _require_warehouse
from app.tests.conftest import TestSessionLocal


def test_supplier_and_warehouse_existence_checks_project_ids():
    with TestSessionLocal() as db:
        supplier = Supplier(name="Projection test supplier")
        warehouse = Warehouse(name="Projection test warehouse", type="fabric_storage")
        db.add_all([supplier, warehouse])
        db.commit()
        supplier_id = int(supplier.id)
        warehouse_id = int(warehouse.id)

    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().lower().startswith("select"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(TestSessionLocal.kw["bind"], "before_cursor_execute", capture)
    try:
        with TestSessionLocal() as db:
            assert _require_supplier(db, supplier_id) is None
            assert _require_warehouse(db, warehouse_id) is None
    finally:
        event.remove(TestSessionLocal.kw["bind"], "before_cursor_execute", capture)

    supplier_reads = [sql for sql in statements if " from suppliers " in sql]
    warehouse_reads = [sql for sql in statements if " from warehouses " in sql]
    assert len(supplier_reads) == len(warehouse_reads) == 1
    assert supplier_reads[0].startswith("select suppliers.id as suppliers_id from suppliers ")
    assert warehouse_reads[0].startswith("select warehouses.id as warehouses_id from warehouses ")

    with TestSessionLocal() as db:
        with pytest.raises(HTTPException) as missing_supplier:
            _require_supplier(db, 2_147_483_647)
        assert missing_supplier.value.status_code == 404
        with pytest.raises(HTTPException) as missing_warehouse:
            _require_warehouse(db, 2_147_483_647)
        assert missing_warehouse.value.status_code == 404
