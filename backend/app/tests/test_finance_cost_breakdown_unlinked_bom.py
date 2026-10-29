"""Descriptive BOM rows cannot be priced without an inventory item link."""
from decimal import Decimal
from uuid import uuid4

import pytest

from app.models.finance_service import cost_breakdown
from app.schemas import AuditLog, Item, Model, ModelBOM, ProductionOrder, StockBatch, Warehouse
from app.tests.conftest import TestSessionLocal


@pytest.mark.parametrize('linked,descriptive', [(True, False), (True, True), (False, True)])
def test_cost_breakdown_keeps_priced_components_and_ignores_descriptive_rows(client, auth_headers, linked, descriptive):
    suffix=uuid4().hex
    with TestSessionLocal() as db:
        baseline=cost_breakdown(db)
        model=Model(code='COST-'+suffix,name='Cost breakdown fixture',status='approved')
        db.add(model)
        db.flush()
        db.add(ProductionOrder(production_no='COST-'+suffix,production_type='branded_stock',
                               model_id=model.id,planned_quantity=10))
        if linked:
            fabric=Item(sku='FAB-'+suffix,name='Priced fabric',category='fabric',unit='kg',default_cost=2)
            packaging=Item(sku='PKG-'+suffix,name='Priced packaging',category='packaging',unit='pcs',default_cost=Decimal('0.25'))
            db.add_all([fabric,packaging])
            db.flush()
            warehouse=db.query(Warehouse).first()
            for index,cost in enumerate([1,3]):
                db.add(StockBatch(item_id=fabric.id,batch_no=f'COST-{suffix}-{index}',quantity=1,
                                  unit='kg',cost_per_unit=cost,warehouse_id=warehouse.id))
                db.flush()
            db.add_all([
                ModelBOM(model_id=model.id,item_id=fabric.id,quantity_per_piece=Decimal('0.5'),unit='kg',waste_percent=10),
                ModelBOM(model_id=model.id,item_id=packaging.id,quantity_per_piece=1,unit='pcs',waste_percent=0),
            ])
        if descriptive:
            db.add(ModelBOM(model_id=model.id,item_id=None,material_name='Unlinked historical fabric',
                            quantity_per_piece=999,unit='kg',waste_percent=99))
        db.commit()
        tables=(ModelBOM,ProductionOrder,Item,StockBatch,AuditLog)
        before=tuple(db.query(table).count() for table in tables)

    response=client.get('/api/finance/cost-breakdown',headers=auth_headers)
    assert response.status_code==200,response.text
    assert response.json()=={
        'fabric_cost':baseline['fabric_cost']+(16.5 if linked else 0),
        'accessories_cost':baseline['accessories_cost']+(2.5 if linked else 0),
        'labor_cost':baseline['labor_cost'],
        'total_cogs':baseline['total_cogs']+(19 if linked else 0),
    }
    with TestSessionLocal() as db:
        assert tuple(db.query(table).count() for table in tables)==before
        if descriptive:
            assert db.query(ModelBOM).filter_by(model_id=model.id,item_id=None).count()==1
