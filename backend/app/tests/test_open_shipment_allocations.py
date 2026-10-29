"""Two open shipments own distinct pieces of the same physical package."""
import pytest

from app.db.session import SessionLocal
from app.schemas import FinishedGoodsStock, Package, PackageItem, Shipment, ShipmentPackage, StockReservation
from app.tests.test_shipment_review import dispatch  # noqa: F401


@pytest.fixture
def open_pack(dispatch):
    with SessionLocal() as db:
        package=db.get(Package,dispatch['package'])
        package.status='received_in_storage'
        package.total_quantity=60
        shipment=db.get(Shipment,dispatch['shipment'])
        shipment.sales_order_id=None
        shipment.notes='First warehouse recipient'
        for row in db.query(PackageItem).filter_by(package_id=package.id):row.quantity=30
        for row in db.query(FinishedGoodsStock).filter_by(package_id=package.id):
            row.quantity=row.available_qty=30
            row.reserved_qty=0
            row.status='available'
        db.query(StockReservation).filter_by(package_id=package.id).delete()
        db.query(ShipmentPackage).filter_by(package_id=package.id).one().quantity=60
        db.commit()
    return dispatch


def choose(client,headers,pack,sid,total_each,expected):
    return client.post(f'/api/shipments/{sid}/packages/{pack["package"]}/quantity',headers=headers,
        json=dict(expected_quantity=expected,keep_remainder=True,reason='Allocate partial package',
                  items=[dict(item_id=i,quantity=total_each) for i in pack['items']]))


def new_shipment(client,headers):
    response=client.post('/api/shipments',headers=headers,json={'notes':'Second warehouse recipient'})
    assert response.status_code==201,response.text
    return response.json()['id']


@pytest.mark.parametrize('second_first', [True, False])
def test_scan_remaining_before_first_dispatch_and_ship_second_first(client,auth_headers,open_pack,second_first):
    pack=open_pack;first=pack['shipment']
    response=choose(client,auth_headers,pack,first,12,60)
    assert response.status_code==200,response.text
    second=new_shipment(client,auth_headers)
    scan=client.post(f'/api/shipments/{second}/scan-package',headers=auth_headers,json={'code':'REVIEW-QR'})
    assert scan.status_code==200 and scan.json()['ok'],scan.text
    assert scan.json()['package_quantity']==36
    for sid, quantity in ((first,24),(second,36)):
        repeated=client.post(f'/api/shipments/{sid}/scan-package',headers=auth_headers,json={'code':'REVIEW-QR'})
        assert repeated.status_code==200 and repeated.json()['ok'],repeated.text
        assert repeated.json()['package_quantity']==quantity
    with SessionLocal() as db:
        assert db.get(Shipment,first).status=='created'
        assert db.get(Package,pack['package']).dispatched_quantity==0
        assert {r.shipment_id:r.quantity for r in db.query(ShipmentPackage).filter_by(package_id=pack['package'])}=={first:24,second:36}
    grow=choose(client,auth_headers,pack,first,15,24)
    assert grow.status_code==409,grow.text
    third=new_shipment(client,auth_headers)
    exhausted=client.post(f'/api/shipments/{third}/scan-package',headers=auth_headers,json={'code':'REVIEW-QR'})
    assert exhausted.status_code==200 and not exhausted.json()['ok'],exhausted.text
    with SessionLocal() as db:
        assert db.query(ShipmentPackage).filter_by(shipment_id=third).count()==0
    sequence=((second,36),(first,24)) if second_first else ((first,24),(second,36))
    frozen={}
    for sid,quantity in sequence:
        result=client.post(f'/api/shipments/{sid}/ship',headers=auth_headers)
        assert result.status_code==200,result.text
        invoice=client.get(f'/api/shipments/{sid}/invoice',headers=auth_headers).json()
        assert invoice['quantity']==quantity
        assert sum(row['quantity'] for row in invoice['lines'])==quantity
        frozen[sid]=invoice
    for sid,invoice in frozen.items():
        assert client.get(f'/api/shipments/{sid}/invoice',headers=auth_headers).json()==invoice
    with SessionLocal() as db:
        package=db.get(Package,pack['package'])
        assert package.total_quantity==package.dispatched_quantity==60
        assert sum(s.sold_qty for s in db.query(FinishedGoodsStock).filter_by(package_id=package.id))==60
        assert sum(s.available_qty+s.reserved_qty for s in db.query(FinishedGoodsStock).filter_by(package_id=package.id))==0


@pytest.mark.parametrize('release', ['detach','delete','reduce'])
def test_releasing_only_own_claim_and_stale_edit(client,auth_headers,open_pack,release):
    pack=open_pack; first=pack['shipment']
    assert choose(client,auth_headers,pack,first,12,60).status_code==200
    second=new_shipment(client,auth_headers)
    assert client.post(f'/api/shipments/{second}/scan-package',headers=auth_headers,json={'code':'REVIEW-QR'}).json()['ok']
    if release=='reduce':
        response=choose(client,auth_headers,pack,second,10,36)
        assert response.status_code==200,response.text
        stale=choose(client,auth_headers,pack,second,11,36)
        assert stale.status_code==409,stale.text
        expected=16
    elif release=='detach':
        response=client.post(f'/api/shipments/{second}/packages/{pack["package"]}/remove',headers=auth_headers,json={'reason':'Release selected pieces'})
        assert response.status_code==200,response.text
        expected=36
    else:
        # New manual shipments are allowed to be deleted before dispatch.
        with SessionLocal() as db:
            sh=db.get(Shipment,second);sh.dispatch_snapshot={**sh.dispatch_snapshot,'manual':True};db.commit()
        response=client.post(f'/api/shipments/{second}/delete',headers=auth_headers,json={'reason':'Mistaken test shipment'})
        assert response.status_code==200,response.text
        expected=36
    third=new_shipment(client,auth_headers)
    response=client.post(f'/api/shipments/{third}/scan-package',headers=auth_headers,json={'code':'REVIEW-QR'})
    assert response.status_code==200 and response.json()['ok'],response.text
    assert response.json()['package_quantity']==expected
    with SessionLocal() as db:
        assert db.query(ShipmentPackage).filter_by(shipment_id=first,package_id=pack['package']).one().quantity==24
        assert db.get(Package,pack['package']).dispatched_quantity==0


def test_claims_are_per_size_not_just_total_and_permission_checked(client,auth_headers,open_pack):
    pack=open_pack;first=pack['shipment']
    assert choose(client,auth_headers,pack,first,12,60).status_code==200
    second=new_shipment(client,auth_headers)
    assert client.post(f'/api/shipments/{second}/scan-package',headers=auth_headers,json={'code':'REVIEW-QR'}).json()['ok']
    assert choose(client,auth_headers,pack,second,10,36).status_code==200
    response=client.post(f'/api/shipments/{first}/packages/{pack["package"]}/quantity',headers=auth_headers,json={
        'expected_quantity':24,'keep_remainder':True,'reason':'Unbalanced sizes',
        'items':[{'item_id':pack['items'][0],'quantity':21},{'item_id':pack['items'][1],'quantity':3}]})
    assert response.status_code==409,response.text
    token=client.post('/api/auth/token',data={'username':'planning@example.com','password':'demo12345'}).json()['access_token']
    denied=choose(client,{'Authorization':'Bearer '+token},pack,first,10,24)
    assert denied.status_code==403,denied.text
    with SessionLocal() as db:
        assert db.query(ShipmentPackage).filter_by(shipment_id=first).one().quantity==24


@pytest.mark.parametrize('malformed', [None, {'bogus':24}, 'bad'])
def test_ambiguous_legacy_partial_claim_fails_closed(client,auth_headers,open_pack,malformed):
    pack=open_pack
    with SessionLocal() as db:
        db.query(ShipmentPackage).filter_by(shipment_id=pack['shipment']).one().quantity=24
        sh=db.get(Shipment,pack['shipment'])
        sh.dispatch_snapshot={} if malformed is None else {'package_quantities':{str(pack['package']):malformed}}
        db.commit()
    second=new_shipment(client,auth_headers)
    response=client.post(f'/api/shipments/{second}/scan-package',headers=auth_headers,json={'code':'REVIEW-QR'})
    assert response.status_code==409,response.text
    with SessionLocal() as db:
        assert db.query(ShipmentPackage).filter_by(shipment_id=second).count()==0


def test_direct_add_also_freezes_remainder(client,auth_headers,open_pack):
    pack=open_pack
    assert choose(client,auth_headers,pack,pack['shipment'],12,60).status_code==200
    second=new_shipment(client,auth_headers)
    response=client.post(f'/api/shipments/{second}/add-package?package_id={pack["package"]}',headers=auth_headers)
    assert response.status_code==200,response.text
    with SessionLocal() as db:
        assert db.query(ShipmentPackage).filter_by(shipment_id=second).one().quantity==36
        assert sum(db.get(Shipment,second).dispatch_snapshot['package_quantities'][str(pack['package'])].values())==36


def test_standalone_package_ship_cannot_bypass_open_claims(client,auth_headers,open_pack):
    pack=open_pack
    assert choose(client,auth_headers,pack,pack['shipment'],12,60).status_code==200
    second=new_shipment(client,auth_headers)
    assert client.post(f'/api/shipments/{second}/scan-package',headers=auth_headers,json={'code':'REVIEW-QR'}).json()['ok']
    response=client.post(f'/api/packages/{pack["package"]}/ship',headers=auth_headers)
    assert response.status_code==409,response.text
    with SessionLocal() as db:
        assert db.get(Package,pack['package']).status=='received_in_storage'
        assert sum(row.sold_qty for row in db.query(FinishedGoodsStock).filter_by(package_id=pack['package']))==0
        assert sum(link.quantity for link in db.query(ShipmentPackage).filter_by(package_id=pack['package']))==60
