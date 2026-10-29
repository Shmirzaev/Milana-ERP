"""Committed per-size conservation under competing real PostgreSQL transactions."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.routes.shipments import _ship_verified_packages
from app.libs.dto.fulfillment.shipment_review import ShipmentQuantityReview
from app.models.fulfillment.shipment_allocation_service import attach_package_claim
from app.models.package_dispatch_service import select_dispatch_quantity
from app.models.shipment_review_service import locked_shipment
from app.schemas import (FinishedGoodsStock, LegacyStockReceipt, Model, Package, PackageItem,
                         Shipment, ShipmentPackage, ShipmentScanLog, User)
from app.schemas.fulfillment.shipment_allocation import save_package_claim
from app.tests.test_password_change_races import password_change_postgres_sessions  # noqa: F401


def fixture(sessions):
    marker=uuid4().hex
    with sessions() as db:
        actor=User(name='QA allocation actor',email=marker+'@qa.local',password_hash='unused')
        model=Model(code=marker,name='Allocation QA',status='approved')
        receipt=LegacyStockReceipt(source_system='QA',source_warehouse_id='QA',source_record_id=marker,
                                   source_checksum='a'*64,source_payload={'quantity':60})
        db.add_all([actor,model,receipt]);db.flush()
        package=Package(package_no=marker,barcode=marker,model_id=model.id,color='White',capacity=60,
                        total_quantity=60,status='received_in_storage',legacy_receipt_id=receipt.id)
        shipments=[Shipment(shipment_no=f'{marker}-{i}',status='created',notes='QA recipient') for i in range(3)]
        db.add_all([package,*shipments]);db.flush()
        items=[]
        for size in ('46','48','50','52','54','56'):
            item=PackageItem(package_id=package.id,model_id=model.id,color='White',size=size,quantity=10)
            items.append(item);db.add(item)
            db.add(FinishedGoodsStock(package_id=package.id,model_id=model.id,color='White',size=size,
                                     quantity=10,available_qty=10,reserved_qty=0,sold_qty=0,status='available'))
        db.flush()
        save_package_claim(db,shipments[0],package.id,{str(i.id):4 for i in items},None)
        db.add(ShipmentScanLog(shipment_id=shipments[0].id,package_id=package.id,scanned_code=marker,scan_result='matched'))
        db.commit()
        return package.id,[s.id for s in shipments],[i.id for i in items],actor.id


@pytest.mark.parametrize('competing', ['attach','edit','dispatch'])
def test_postgres_open_claim_races_conserve_each_size(password_change_postgres_sessions,competing):
    sessions,_=password_change_postgres_sessions
    pid,sids,items,uid=fixture(sessions)
    barrier=Barrier(2)

    def run(index):
        with sessions() as db:
            sid=sids[index+1] if competing=='attach' else sids[0 if index==0 else 1]
            sh=locked_shipment(db,sid)
            # Load before the barrier as real scanner callers do. The service
            # must refresh this object after obtaining the contended pack lock.
            package=db.get(Package,pid)
            user=db.get(User,uid)
            barrier.wait(timeout=10)
            try:
                if index==0 and competing=='edit':
                    select_dispatch_quantity(db,sh,pid,ShipmentQuantityReview(
                        expected_quantity=24,keep_remainder=True,reason='Claim six per size',
                        items=[{'item_id':iid,'quantity':6} for iid in items]),user)
                    result=36
                elif index==0 and competing=='dispatch':
                    _ship_verified_packages(db,sh,user)
                    result=24
                else:
                    result=attach_package_claim(db,sh,package).quantity
                db.commit()
                return 200,result
            except HTTPException as rejected:
                db.rollback()
                return rejected.status_code,0

    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(run,range(2)))
    assert all(status in {200,409} for status,_ in results),results
    if competing=='attach':
        assert sorted(results)==[(200,36),(409,0)],results
    elif competing=='dispatch':
        assert results==[(200,24),(200,36)],results
    else:
        assert results in ([(200,36),(200,24)],[(409,0),(200,36)]),results
    with sessions() as db:
        package=db.get(Package,pid)
        claims=db.query(ShipmentPackage,Shipment).join(Shipment,Shipment.id==ShipmentPackage.shipment_id).filter(
            ShipmentPackage.package_id==pid,Shipment.status.in_(['created','draft'])).all()
        for iid in items:
            sold=(package.dispatched_quantities or {}).get(str(iid),0)
            assert sold+sum(sh.dispatch_snapshot['package_quantities'][str(pid)][str(iid)] for _,sh in claims)==10
        assert (package.dispatched_quantity or 0)+sum(link.quantity for link,_ in claims)==60
        assert sum(s.sold_qty for s in db.query(FinishedGoodsStock).filter_by(package_id=pid))==(24 if competing=='dispatch' else 0)


@pytest.mark.parametrize('status',['damaged','shipped'])
def test_postgres_attach_refreshes_readiness_after_wait(password_change_postgres_sessions,status):
    sessions,_=password_change_postgres_sessions
    pid,sids,_,_=fixture(sessions)
    with sessions() as stale:
        package=stale.get(Package,pid)
        sh=locked_shipment(stale,sids[1])
        with sessions() as writer:
            current=writer.query(Package).filter_by(id=pid).with_for_update().one()
            current.status=status
            writer.commit()
        assert package.status=='received_in_storage'
        with pytest.raises(HTTPException) as rejected:
            attach_package_claim(stale,sh,package)
        assert rejected.value.status_code==409
        stale.rollback()
    with sessions() as db:
        assert db.query(ShipmentPackage).filter_by(shipment_id=sids[1]).count()==0
