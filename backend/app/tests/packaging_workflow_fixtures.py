"""Synthetic disposable fixtures for connected-browser factory workflow QA only."""
from uuid import uuid4

from app.schemas import (Department, Model, PackagingReceipt, PackagingRecord, ProductionBatch,
                         ProductionOrder, ProductionOrderItem, SewingRecord, WorkOrder)


def seed_packaging_workflow(db):
    """Caller owns isolated DB transaction; never call against production."""
    marker = uuid4().hex[:8]
    departments = {}
    for code in ('SEW', 'PKG'):
        department = db.query(Department).filter_by(code=code).one_or_none()
        if department is None:
            department = Department(code=code, name=f'QA {code}')
            db.add(department); db.flush()
        departments[code] = department.id
    model = Model(code=f'QA-PKG-{marker}', name='QA selectable Packaging', product_type='shirt')
    db.add(model); db.flush()
    result = {}
    for scenario, quantities, packed in [('automatic', [95], [0]), ('legacy_later', [80, 70, 90], [35, 40, 0])]:
        order = ProductionOrder(production_no=f'QA-PKG-{scenario}-{marker}', model_id=model.id,
            production_type='branded_stock', planned_quantity=sum(quantities), status='packaging')
        db.add(order); db.flush()
        db.add(ProductionOrderItem(production_order_id=order.id, model_id=model.id, color='white',
                                  size='M', planned_quantity=sum(quantities)))
        sewing = WorkOrder(production_order_id=order.id, operation='sewing', department_id=departments['SEW'],
            status='completed', planned_input_qty=sum(quantities), planned_output_qty=sum(quantities),
            actual_input_qty=sum(quantities), actual_output_qty=sum(quantities), passed_qty=sum(quantities))
        packaging = WorkOrder(production_order_id=order.id, operation='packaging', department_id=departments['PKG'],
            status='ready', planned_input_qty=sum(quantities), planned_output_qty=sum(quantities),
            actual_input_qty=sum(packed), actual_output_qty=sum(packed), passed_qty=sum(packed))
        db.add_all([sewing, packaging]); db.flush()
        batches = []
        for index, (quantity, saved) in enumerate(zip(quantities, packed), 1):
            batch = ProductionBatch(production_order_id=order.id, batch_no=f'QA-{marker}-{scenario}-{index}',
                batch_index=index, name=f'QA Nastil {index}', planned_quantity=quantity)
            db.add(batch); db.flush()
            batches.append(batch.id)
            db.add(SewingRecord(work_order_id=sewing.id, production_batch_id=batch.id,
                                input_qty=quantity, sewn_qty=quantity, passed_qty=quantity))
            if saved:
                db.add(PackagingRecord(work_order_id=packaging.id, production_batch_id=batch.id,
                                       input_qty=saved, packed_qty=saved))
        if scenario == 'legacy_later':
            db.add(PackagingReceipt(work_order_id=packaging.id, source_work_order_id=sewing.id,
                production_order_id=order.id, production_batch_id=batches[0], packaging_department_code='PKG',
                quantity=20, receive_method='manual'))
        result[scenario] = dict(order_id=order.id, work_order_id=packaging.id, sewing_work_order_id=sewing.id,
            batch_ids=batches, sewing_output=sum(quantities), packing_input=sum(packed),
            queue_remaining=sum(quantities)-sum(packed), saved_output=packed,
            production_no=order.production_no, model_id=model.id)
    db.flush()
    return result
