"""Actual receiving/update handlers must remain atomic and preserve history."""
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'ops'))
from apply_fabric_reconciliation import AtomicSession, execute_rows, assert_unchanged
from app.db import session as session_module
from app.models import Item, StockBatch, StockMovement, User, Warehouse
from app.api.routes.inventory import receive_stock
from app.schemas.inventory import StockBatchIn


def setup_rows():
    with Session(session_module.engine, expire_on_commit=False) as db:
        actor = db.query(User).filter_by(email='admin@example.com').one()
        warehouse = db.get(Warehouse, 1)
        assert warehouse.type == 'fabric_storage'
        item = Item(sku='RECONCILE-TEST', name='Reconciliation test fabric', category='fabric', unit='kg')
        db.add(item)
        db.commit()
        ids = []
        for name in ('CORRECT', 'DEPLETE'):
            row = receive_stock(StockBatchIn(item_id=item.id, batch_no=name, quantity=10,
                piece_count=2, roll_weights_kg=[4,6], unit='kg', warehouse_id=1,
                cost_per_unit=12.5, qc_status='passed'), db, actor, idempotency_key=None)
            ids.append(row['id'])
        return actor.id, item.id, ids


def make_plan(item_id, ids):
    common = {'status':'prepared','sources':[{'file':'fixture.xlsx','sheet':'Stock','row':2,
               'color':'Blue','color_code':'B01'}], 'linked_tables':[], 'supplier_id':None}
    return {'workbooks':[{'file':'fixture.xlsx','sha256':'fixture'}], 'plans':[
        {**common, 'action':'receive','batch_no':'NEW','item_id':item_id,'erp_ids':[],
         'before':[], 'target_kg':'5.5','current_kg':'0','received_date':'2026-09-01',
         'proposed_roll_count':None},
        {**common, 'action':'adjust','erp_ids':[ids[0]],'target_kg':'7','current_kg':'10'},
        {**common, 'action':'archive','erp_ids':[ids[1]],'target_kg':'0','current_kg':'10'},
    ]}


def test_handlers_commit_together_and_keep_receipt_roll_history():
    aid, iid, ids = setup_rows()
    plan = make_plan(iid, ids)
    with AtomicSession(bind=session_module.engine, expire_on_commit=False) as db:
        before_movements = db.query(StockMovement).count()
        changes = execute_rows(db, db.get(User,aid), plan, 'a'*64)
        assert len(changes) == 3
        corrected = db.get(StockBatch,ids[0])
        assert corrected.quantity == Decimal('7')
        assert corrected.roll_weights_kg == [4,6] and corrected.piece_count == 2
        assert corrected.cost_per_unit == Decimal('12.5') and corrected.qc_status == 'passed'
        depleted = db.get(StockBatch,ids[1])
        assert depleted.quantity == 0 and depleted.archived_at is not None
        assert depleted.roll_weights_kg == [4,6]
        new = db.get(StockBatch,changes[0]['id'])
        assert new.piece_count is None and new.roll_weights_kg == []
        assert new.qc_status == 'pending' and new.cost_per_unit == 0
        assert new.color == 'Blue' and new.color_code == 'B01'
        assert new.received_date.date().isoformat() == '2026-09-01'
        assert db.query(StockMovement).count() == before_movements+3
        Session.commit(db)
    with Session(session_module.engine) as db:
        assert db.get(StockBatch,ids[0]).quantity == 7
        assert db.get(StockBatch,ids[1]).archived_at is not None


def test_late_failure_rolls_back_earlier_receipt_and_adjustment():
    aid, iid, ids = setup_rows()
    plan = make_plan(iid, ids)
    plan['plans'][2]['linked_tables'] = ['cutting_records']
    with pytest.raises(ValueError, match='Unsafe archive'):
        with AtomicSession(bind=session_module.engine, expire_on_commit=False) as db:
            execute_rows(db, db.get(User,aid), plan, 'b'*64)
            Session.commit(db)
    with Session(session_module.engine) as db:
        assert db.query(StockBatch).filter_by(batch_no='NEW').count() == 0
        assert db.get(StockBatch,ids[0]).quantity == 10
        assert db.get(StockBatch,ids[1]).quantity == 10


def test_stale_quantity_aborts_instead_of_overwriting():
    aid, iid, ids = setup_rows()
    plan = make_plan(iid, ids)
    plan['plans'][1]['current_kg'] = '9'
    with pytest.raises(ValueError, match='Stale batch quantity'):
        with AtomicSession(bind=session_module.engine) as db:
            execute_rows(db, db.get(User,aid), plan, 'c'*64)
    with Session(session_module.engine) as db:
        assert db.query(StockBatch).filter_by(batch_no='NEW').count() == 0


def test_live_evidence_guard_checks_links_and_ignores_capture_time():
    assert_unchanged({'snapshot_time':'a','linked_rows':[]}, {'snapshot_time':'b','linked_rows':[]})
    with pytest.raises(ValueError, match='linked_rows'):
        assert_unchanged({'linked_rows':[]}, {'linked_rows':[{'id':1}]})
