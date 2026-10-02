"""Follow-up balances use normal handlers without rewriting historical usage."""
import sys
from pathlib import Path
from decimal import Decimal
import pytest
from sqlalchemy.orm import Session
from app.db import session as sm
from app.models import User, StockBatch, StockMovement, MaterialReservation, ProductionOrder, Item
from app.tests.test_fabric_reconciliation_apply import setup_rows

sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'ops'))
from apply_fabric_reconciliation import AtomicSession
from apply_fabric_continuation import execute


def base(actions):
    return {'new_items':[],'reservation_releases':[],'actions':actions,'workbooks':[]}


def edit(bid,values):
    return {'ref':'R001','kind':'update','id':bid,'values':values,'sources':[]}


def receipt(iid):
    return {'ref':'S001','kind':'receive','item_ref':iid,'batch_no':'','supplier_id':None,
       'quantity':'5.5','piece_count':1,'cost_per_unit':'0','color':None,'color_code':None,
       'received_date':None,'sources':[]}


def test_remaining_roll_count_preserves_original_weights_and_ledger():
    aid,iid,ids=setup_rows()
    with AtomicSession(bind=sm.engine,expire_on_commit=False) as db:
        movements=db.query(StockMovement).count()
        execute(db,db.get(User,aid),base([edit(ids[0],{'piece_count':1})]),'1'*64,{})
        b=db.get(StockBatch,ids[0]);assert b.piece_count==1 and b.roll_weights_kg==[4,6]
        assert b.quantity==10 and db.query(StockMovement).count()==movements
        Session.commit(db)


def test_blank_supplier_and_batch_are_not_replaced_with_invented_identity():
    aid,iid,ids=setup_rows()
    with AtomicSession(bind=sm.engine,expire_on_commit=False) as db:
        changes,_,_=execute(db,db.get(User,aid),base([receipt(iid)]),'2'*64,{})
        b=db.get(StockBatch,changes[0]['id'])
        assert b.batch_no=='' and b.supplier_id is None and b.piece_count==1
        assert b.quantity==Decimal('5.5') and b.roll_weights_kg==[]
        Session.commit(db)


def test_material_correction_retains_old_batch_and_movement_identity():
    aid,iid,ids=setup_rows()
    p=base([edit(ids[0],{'quantity':'0','piece_count':0}),receipt('NEW-FABRIC')])
    p['new_items']=[{'sku':'NEW-FABRIC','name':'Exact source fabric','category':'fabric','unit':'kg'}]
    with AtomicSession(bind=sm.engine,expire_on_commit=False) as db:
        old=[(m.id,m.item_id,m.quantity) for m in db.query(StockMovement).all()]
        changes,items,_=execute(db,db.get(User,aid),p,'3'*64,{})
        assert db.get(StockBatch,ids[0]).item_id==iid
        assert db.get(StockBatch,ids[0]).archived_at is not None
        assert db.get(StockBatch,changes[1]['id']).item_id==items['NEW-FABRIC']
        assert all((db.get(StockMovement,mid).item_id,db.get(StockMovement,mid).quantity)==(item,qty) for mid,item,qty in old)
        Session.commit(db)


def test_zero_physical_stock_releases_only_unconsumed_reservation():
    aid,iid,ids=setup_rows()
    with Session(sm.engine,expire_on_commit=False) as db:
        po=ProductionOrder(production_no='PO-FOLLOWUP-TEST',production_type='branded_stock',model_id=1,planned_quantity=1);db.add(po);db.flush()
        r=MaterialReservation(reservation_no='FOLLOWUP-TEST',production_order_id=po.id,item_id=iid,
             stock_batch_id=ids[0],warehouse_id=1,reserved_quantity=10,consumed_quantity=6,
             released_quantity=0,unit='kg',status='partially_consumed',source='manual')
        db.add(r);db.commit();rid=r.id
    p=base([edit(ids[0],{'quantity':'0','piece_count':0})])
    p['reservation_releases']=[{'id':rid,'batch_id':ids[0],'remaining_kg':'4','before':{'consumed_quantity':'6'},
                                'ref':'C001','reason':'User-confirmed zero physical stock'}]
    with AtomicSession(bind=sm.engine,expire_on_commit=False) as db:
        execute(db,db.get(User,aid),p,'4'*64,{})
        r=db.get(MaterialReservation,rid)
        assert r.status=='released' and r.released_quantity==4 and r.consumed_quantity==6
        assert db.get(StockBatch,ids[0]).quantity==0
        Session.commit(db)


def test_late_failure_rolls_back_new_master_and_earlier_stock_changes():
    aid,iid,ids=setup_rows()
    p=base([edit(ids[0],{'quantity':'0'}),receipt('BAD-MATERIAL')])
    p['new_items']=[{'sku':'ROLLBACK-MASTER','name':'Rollback master','category':'fabric','unit':'kg'}]
    with pytest.raises(Exception):
        with AtomicSession(bind=sm.engine) as db:
            execute(db,db.get(User,aid),p,'5'*64,{})
            Session.commit(db)
    with Session(sm.engine) as db:
        assert db.get(StockBatch,ids[0]).quantity==10
        assert db.query(Item).filter_by(sku='ROLLBACK-MASTER').count()==0
