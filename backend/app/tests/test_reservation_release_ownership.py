"""SQLite-only release ownership and rollback checks."""
from uuid import uuid4
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from sqlalchemy import event
from app.db.session import SessionLocal
from app.libs.enums.inventory import MaterialReservationStatus
from app.models.inventory import reservations_service, reservation_release_service
from app.models import inventory_service
from app.schemas import AuditLog, Item, MaterialReservation, Model, ProductionOrder, User
from app.schemas.inventory import material_reservation_persistence


@pytest.mark.parametrize('reserved,consumed,released,expected', [
    (10,0,0,'reserved'), (10,2,0,'partially_consumed'), (10,10,0,'consumed'),
    (10,2,8,'released'), (10,0,10,'released'), (10,10-5e-10,0,'consumed'),
])
def test_shared_status_calculation_preserves_consume_and_cutting_behavior(reserved,consumed,released,expected):
    row=SimpleNamespace(reserved_quantity=reserved,consumed_quantity=consumed,released_quantity=released,status='reserved')
    inventory_service._set_reservation_status(row)
    assert row.status==expected


def _row(db, consumed=0, released=0, status='reserved'):
    token=uuid4().hex[:12]
    model=Model(code='RELM-'+token,name='release model',status='approved')
    item=Item(sku='RELI-'+token,name='release item',category='fabric',unit='kg')
    db.add_all([model,item]); db.flush()
    order=ProductionOrder(production_no='RELP-'+token,production_type='branded_stock',model_id=model.id,planned_quantity=1)
    db.add(order); db.flush()
    row=MaterialReservation(reservation_no='RELR-'+token,production_order_id=order.id,item_id=item.id,
                            reserved_quantity=10,consumed_quantity=consumed,released_quantity=released,
                            unit='kg',status=status,reservation_type='material',source='manual')
    db.add(row); db.commit(); return row.id


@pytest.mark.parametrize('consumed,released,status,expected_released,expected_status', [
    (0,0,'reserved',10,'released'), (4,0,'partially_consumed',6,'released'),
    (4,2,'partially_consumed',6,'released'), (10,0,'reserved',0,'consumed'),
    (4,6,'partially_consumed',6,'released'),
])
def test_release_calculation_schema_owner_and_rollback(monkeypatch,consumed,released,status,expected_released,expected_status):
    with SessionLocal() as db:
        assert db.bind.dialect.name=='sqlite'
        row_id=_row(db,consumed,released,status); writes=[]
        original=material_reservation_persistence.apply_reservation_release
        def capture(actual_db,reservation,**kwargs):
            assert actual_db is db and reservation is db.get(MaterialReservation,row_id)
            assert isinstance(kwargs['status'],MaterialReservationStatus)
            writes.append(kwargs.copy()); return original(actual_db,reservation,**kwargs)
        monkeypatch.setattr(material_reservation_persistence,'apply_reservation_release',capture)
        result=inventory_service.release_material_reservation(db,row_id)
        assert result.id==row_id and result.status==expected_status and float(result.released_quantity)==expected_released
        assert len(writes)==1 and writes[0]['status'].value==expected_status
        assert (writes[0]['released_quantity'] is None)==(consumed+released==10)
        db.rollback()
    with SessionLocal() as db:
        result=db.get(MaterialReservation,row_id)
        assert result.status==status and float(result.released_quantity)==released


@pytest.mark.parametrize('status',['cancelled','released','consumed'])
def test_terminal_refusal_has_no_write(monkeypatch,status):
    with SessionLocal() as db:
        row_id=_row(db,status=status)
        def unexpected(*args,**kwargs): raise AssertionError('unexpected schema write')
        monkeypatch.setattr(material_reservation_persistence,'apply_reservation_release',unexpected)
        with pytest.raises(HTTPException) as error: reservation_release_service.release_material_reservation(db,row_id)
        assert (error.value.status_code,error.value.detail)==(409,'Reservation is already '+status)
        with pytest.raises(HTTPException) as missing: reservation_release_service.release_material_reservation(db,999999999)
        assert (missing.value.status_code,missing.value.detail)==(404,'Material reservation not found')


def test_facade_commits_release_and_audit_once():
    with SessionLocal() as db:
        row_id=_row(db,consumed=2,status='partially_consumed'); actor=db.get(User,1); commits=[]
        def committed(session): commits.append(session)
        event.listen(db,'after_commit',committed)
        try: body=reservations_service.release_material_reservation(db,row_id,actor)
        finally: event.remove(db,'after_commit',committed)
        assert body['status']==MaterialReservationStatus.RELEASED and float(body['released_quantity'])==8
        assert commits==[db]
    with SessionLocal() as db:
        row=db.get(MaterialReservation,row_id)
        audit=db.query(AuditLog).filter_by(action='release_material_reservation',entity_type='MaterialReservation',entity_id=row_id).one()
        assert row.status=='released' and float(row.released_quantity)==8
        assert audit.user_id==1 and audit.new_value_json=={'released_quantity':8.0,'status':'released'}


def test_audit_failure_rolls_back_release(monkeypatch):
    with SessionLocal() as db:
        row_id=_row(db); actor=db.get(User,1)
        def fail(*args,**kwargs): raise RuntimeError('audit fault')
        monkeypatch.setattr(reservations_service,'log_action',fail)
        with pytest.raises(RuntimeError,match='audit fault'): reservations_service.release_material_reservation(db,row_id,actor)
        db.rollback()
    with SessionLocal() as db:
        row=db.get(MaterialReservation,row_id)
        assert row.status=='reserved' and float(row.released_quantity)==0
        assert db.query(AuditLog).filter_by(action='release_material_reservation',entity_id=row_id).count()==0


def test_materials_only_actor_cannot_release_accessory_before_write():
    with SessionLocal() as db:
        row_id=_row(db)
        row=db.get(MaterialReservation,row_id)
        row.item.category='accessory'
        actor=User(name='Material-only release',email=uuid4().hex+'@example.com',password_hash='unused',
                   extra_permissions=['inventory.materials_only'],factory_code='MIL')
        db.add(actor); db.commit()
        with pytest.raises(HTTPException) as error:
            reservations_service.release_material_reservation(db,row_id,actor)
        assert (error.value.status_code,error.value.detail)==(403,'Only material inventory is available to this user')
        assert row.status=='reserved' and float(row.released_quantity)==0
        assert db.query(AuditLog).filter_by(action='release_material_reservation',entity_id=row_id).count()==0
