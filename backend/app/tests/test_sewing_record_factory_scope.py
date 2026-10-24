from uuid import uuid4

from app.core.security import create_access_token
from app.schemas import Department, Model, ProductionOrder, SewingRecord, WorkOrder
from app.tests.conftest import TestSessionLocal


def _factory_headers(factory_code: str) -> dict[str, str]:
    token = create_access_token(1, extra={"factory_code": factory_code})
    return {"Authorization": f"Bearer {token}"}


def test_sewing_record_detail_requires_selected_factory(client):
    with TestSessionLocal() as db:
        model = Model(code=f"SCOPE-{uuid4().hex[:8]}", name="Scope probe", product_type="shirt")
        db.add(model)
        db.flush()
        order = ProductionOrder(
            production_no=f"PO-SCOPE-{uuid4().hex[:8]}",
            model_id=model.id,
            production_type="branded_stock",
        )
        db.add(order)
        db.flush()
        work = WorkOrder(
            production_order_id=order.id,
            department_id=db.query(Department.id).filter_by(code="ECO").scalar(),
            operation="sewing",
        )
        db.add(work)
        db.flush()
        record = SewingRecord(work_order_id=work.id, input_qty=1, sewn_qty=1, passed_qty=1)
        db.add(record)
        db.commit()
        record_id = record.id

    path = f"/api/sewing/records/{record_id}"
    assert client.get(path, headers=_factory_headers("ECO")).status_code == 200
    assert client.get(path, headers=_factory_headers("MIL")).status_code == 403
    assert client.get(path, headers=_factory_headers("BST")).status_code == 403
