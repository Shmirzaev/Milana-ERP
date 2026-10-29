import json
import socket
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

_local = threading.local()
_original_connect, _original_connect_ex = socket.socket.connect, socket.socket.connect_ex
_original_socketpair = socket.socketpair
def _no_network(sock, *args, **kwargs):
 if getattr(_local, 'socketpair', False):
  return _original_connect(sock, *args, **kwargs)
 raise AssertionError('network disabled for offline reservation checks')
def _local_socketpair(*args, **kwargs):
 _local.socketpair = True
 try: return _original_socketpair(*args, **kwargs)
 finally: _local.socketpair = False
socket.socket.connect = _no_network
socket.socket.connect_ex = _no_network
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from app.libs.dto.inventory.material_reservation_input import MaterialReservationIn
from app.libs.dto.inventory.reservation_type_selection import DeferredReservationType
from app.libs.enums.inventory import MaterialReservationType
from app.models import inventory_service as inv
from app.models.inventory import reservations_service as facade
from app.models.idempotency_service import request_fingerprint
socket.socket.connect, socket.socket.connect_ex = _original_connect, _original_connect_ex

BASE={'production_order_id':1,'item_id':2,'reserved_quantity':1,'unit':'kg'}
class DB:
 def __init__(self): self.events=[]
 def get(self,cls,id): self.events.append('order'); return SimpleNamespace(id=id,sales_order_id=None)
 def flush(self): self.events.append('flush')
 def commit(self): self.events.append('commit')
 def refresh(self,row): self.events.append('refresh')
item=SimpleNamespace(id=2,category='accessory',unit='kg',sku='SYNTHETIC')
def locks(db,lines): db.events.append('lock'); return {},{2:item}
def context(db,lines,batches,preloaded_items): db.events.append('read'); return {2:item},{},{},{(2,None):10.0}
def insert(db,**kw): db.events.append('insert'); return SimpleNamespace(id=123,**kw)

class Checks(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.network = (patch.object(socket.socket,'connect',_no_network),patch.object(socket.socket,'connect_ex',_no_network),patch.object(socket,'socketpair',_local_socketpair))
  for guard in cls.network: guard.start()
 @classmethod
 def tearDownClass(cls):
  for guard in reversed(cls.network): guard.stop()

 def test_actual_route_body_and_permission_order(self):
  from app.api.routes.inventory import router
  actual=next(r for r in router.routes if getattr(r,'path',None)=='/inventory/reservations' and 'POST' in r.methods)
  dependencies={d.name:d.call for d in actual.dependant.dependencies}
  app=FastAPI(); app.add_api_route(actual.path,actual.endpoint,methods=['POST'],response_model=actual.response_model,status_code=201)
  db=DB(); user=SimpleNamespace(id=9); seen=[]
  app.dependency_overrides[dependencies['db']]=lambda:db
  app.dependency_overrides[dependencies['current']]=lambda:user
  def create(actual_db,payload,actual_user,idempotency_key):
   self.assertIs(actual_db,db); self.assertIs(actual_user,user)
   seen.append((payload.legacy_request_payload()['reservation_type'],payload.reservation_type_selection(),idempotency_key))
   raise HTTPException(400,'domain reached')
  with patch.object(facade,'create_material_reservation',create):
   client=TestClient(app)
   for raw in [' material ','', 'unknown']:
    response=client.post('/inventory/reservations',headers={'Idempotency-Key':'test-key'},json={**BASE,'reservation_type':raw})
    self.assertEqual((response.status_code,response.json()['detail']),(400,'domain reached'))
    self.assertEqual(seen[-1][0],raw); self.assertEqual(seen[-1][2],'test-key')
   self.assertEqual(client.post('/inventory/reservations',json={**BASE,'reservation_type':None}).status_code,422)
   def deny(): raise HTTPException(403,'denied')
   app.dependency_overrides[dependencies['current']]=deny
   self.assertEqual(client.post('/inventory/reservations',json={**BASE,'reservation_type':'unknown'}).status_code,403)
   self.assertEqual(len(seen),3)

 def test_lazy_line_precedence_and_schema_session(self):
  db=DB(); captured=[]
  def write(actual_db, **kwargs):
   self.assertIs(actual_db,db)
   captured.append(kwargs)
   return SimpleNamespace(id=len(captured), **kwargs)
  class Explodes:
   def __str__(self): raise AssertionError('type resolved too early')
  with patch.object(inv,'_lock_reservation_resources',locks),patch.object(inv,'_reservation_read_context',context),patch.object(inv,'next_material_reservation_nos',lambda db,n:['n']*n),patch.object(inv.material_reservation_persistence,'insert_material_reservation',write):
   with self.assertRaises(HTTPException) as raised:
    inv.create_material_reservations(db,production_order_id=1,lines=[{'item_id':2,'quantity':0,'reservation_type':Explodes()}],user_id=9)
   self.assertEqual((raised.exception.status_code,raised.exception.detail),(400,'Reservation line #1 quantity must be greater than zero'))
   self.assertEqual(db.events,['order','lock','read']); self.assertEqual(captured,[])
   result=inv.create_material_reservations(db,production_order_id=1,lines=[{'item_id':2,'quantity':3,'unit':'kg'},{'item_id':2,'reserved_quantity':4,'unit':'kg','reservation_type':' material '}],user_id=9)
   self.assertEqual(len(result),2)
   self.assertEqual([r['reservation_type'] for r in captured],[MaterialReservationType.ACCESSORY,MaterialReservationType.MATERIAL])
   self.assertEqual(db.events.count('flush'),1)
   self.assertNotIn('commit',db.events)
   with self.assertRaises(HTTPException) as raised:
    inv.create_material_reservations(db,production_order_id=1,lines=[{'item_id':2,'quantity':6,'unit':'kg'},{'item_id':2,'quantity':5,'unit':'kg'}],user_id=9)
   self.assertEqual(raised.exception.status_code,409)
   self.assertEqual(len(captured),2)

 def test_dto_and_copy(self):
  for raw,choice in [(' material ',MaterialReservationType.MATERIAL),(' accessory ',MaterialReservationType.ACCESSORY),('',DeferredReservationType.FALLBACK),('   ',DeferredReservationType.INVALID),('unknown',DeferredReservationType.INVALID)]:
   for dto in [MaterialReservationIn(**BASE,reservation_type=raw),MaterialReservationIn.model_validate_json(json.dumps({**BASE,'reservation_type':raw}))]:
    self.assertEqual(dto.reservation_type_selection(),choice)
    self.assertEqual(dto.legacy_request_payload(mode='json')['reservation_type'],raw)
    copy=dto.model_copy(update={'reservation_type':' packaging '})
    self.assertEqual(copy.reservation_type_selection(),MaterialReservationType.PACKAGING)
    self.assertEqual(copy.legacy_request_payload(mode='json')['reservation_type'],' packaging ')
    self.assertEqual(dto.legacy_request_payload(mode='json')['reservation_type'],raw)
  self.assertEqual(MaterialReservationIn(**BASE).legacy_request_payload(mode='json')['reservation_type'],'material')
  with self.assertRaises(ValidationError): MaterialReservationIn(**BASE,reservation_type=None)
  with self.assertRaises(ValidationError): MaterialReservationIn.model_validate({**BASE,'reservation_type':b'material'},strict=True)
  self.assertEqual(MaterialReservationIn(**BASE,reservation_type=b'material').legacy_request_payload()['reservation_type'],'material')
  dto=MaterialReservationIn(**BASE,reservation_type='bad'); dto.reservation_type=' accessory '
  self.assertEqual(dto.reservation_type_selection(),MaterialReservationType.ACCESSORY)
  self.assertEqual(dto.legacy_request_payload()['reservation_type'],' accessory ')
  constructed=MaterialReservationIn.model_construct(**BASE,reservation_type='invalid')
  self.assertEqual(constructed.reservation_type_selection(),DeferredReservationType.INVALID)

 def test_http_facade_replay_and_audit(self):
  saved={}; events=[]; db=DB(); user=SimpleNamespace(id=9)
  def replay(db,*,scope,key,payload):
   events.append(('replay',payload['reservation_type']))
   if key not in saved: return None
   if saved[key][0] != request_fingerprint(payload): raise HTTPException(409,'Idempotency-Key was already used with a different request payload')
   return saved[key][1]
  def store(db,*,scope,key,payload,response,user,status_code): saved[key]=(request_fingerprint(payload),response)
  def audit(db,user,action,entity,entity_id,**kwargs): events.append(('audit',action,kwargs['new_value']))
  app=FastAPI()
  @app.post('/reserve',status_code=201)
  def route(body: MaterialReservationIn, key: str='test'):
   return facade.create_material_reservation(db,body,user,key)
  client=TestClient(app)
  with patch.object(facade.inventory_access,'require_item',lambda *a:events.append(('access','item'))),patch.object(facade.inventory_access,'require_batch',lambda *a:events.append(('access','batch'))),patch.object(facade,'replay_idempotent_response',replay),patch.object(facade,'store_idempotent_response',store),patch.object(facade,'log_action',audit),patch.object(facade,'reservation_payload',lambda r:{'id':r.id,'reservation_type':r.reservation_type.value}),patch.object(inv,'_lock_reservation_resources',locks),patch.object(inv,'_reservation_read_context',context),patch.object(inv,'next_material_reservation_nos',lambda db,n:['number']*n),patch.object(inv.material_reservation_persistence,'insert_material_reservation',insert):
   for index, raw in enumerate([' material ',' accessory ','']):
    response=client.post('/reserve',params={'key':str(index)},json={**BASE,'reservation_type':raw})
    self.assertEqual(response.status_code,201,response.text)
    expected='accessory' if raw in (' accessory ','') else 'material'
    self.assertEqual(response.json()['reservation_type'],expected)
    legacy_payload={**BASE,'reserved_quantity':1.0,'stock_batch_id':None,'warehouse_id':None,'reservation_type':raw,'notes':None}
    self.assertEqual(saved[str(index)][0],request_fingerprint(legacy_payload))
    prior=list(db.events); audit_count=len([e for e in events if e[0]=='audit'])
    repeat=client.post('/reserve',params={'key':str(index)},json={**BASE,'reservation_type':raw})
    self.assertEqual(repeat.json(),response.json()); self.assertEqual(db.events,prior)
    self.assertEqual(len([e for e in events if e[0]=='audit']),audit_count)
    conflict=client.post('/reserve',params={'key':str(index)},json={**BASE,'reservation_type':raw+' '})
    self.assertEqual(conflict.status_code,409)
   for raw in ['   ','unknown']:
    before=len(events); commits=db.events.count('commit')
    response=client.post('/reserve',params={'key':'fail-'+raw},json={**BASE,'reservation_type':raw})
    self.assertEqual((response.status_code,response.json()['detail']),(400,'Invalid reservation_type'))
    changes=events[before:]; self.assertEqual([v[1] for v in changes if v[0]=='audit'],['failed_create_material_reservation'])
    audit_row=next(v[2] for v in changes if v[0]=='audit')
    self.assertEqual(audit_row['payload']['reservation_type'],raw); self.assertEqual(db.events.count('commit'),commits+1)
   before=len(events)
   response=client.post('/reserve',json={**BASE,'reservation_type':None})
   self.assertEqual(response.status_code,422); self.assertEqual(len(events),before)

if __name__ == '__main__': unittest.main()
