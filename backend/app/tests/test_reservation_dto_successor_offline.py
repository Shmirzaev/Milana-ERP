import unittest
from collections import UserDict
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from pydantic import ValidationError
from app.libs.dto.inventory.material_reservation_input import MaterialReservationIn as New
from app.libs.dto.inventory.reservation_type_selection import DeferredReservationType
from app.libs.enums.inventory import MaterialReservationType
base={'production_order_id':1,'item_id':2,'reserved_quantity':1,'unit':'kg'}
class Checks(unittest.TestCase):
 def test_mapping_and_attributes_red_control(self):
  for raw in [' material ','','unknown',' accessory ','   ']:
   for make,kwargs in [(lambda d:UserDict(d),{}),(lambda d:SimpleNamespace(**d),{'from_attributes':True})]:
    value=make({**base,'reservation_type':raw})
    new=New.model_validate(value,**kwargs)
    self.assertEqual(new.legacy_request_payload()['reservation_type'],raw)
    if raw in ['unknown','   ']: self.assertIs(new.reservation_type_selection(),DeferredReservationType.INVALID)
    if raw=='': self.assertIs(new.reservation_type_selection(),DeferredReservationType.FALLBACK)
 def test_copy_assignment_construct_are_canonical(self):
  o=New(**base,reservation_type=' material ')
  for raw,canonical,choice in [(' accessory ',MaterialReservationType.ACCESSORY,MaterialReservationType.ACCESSORY),('',None,DeferredReservationType.FALLBACK),('unknown',None,DeferredReservationType.INVALID)]:
   c=o.model_copy(update={'reservation_type':raw})
   self.assertEqual(c.reservation_type,canonical); self.assertEqual(c.legacy_request_payload()['reservation_type'],raw); self.assertEqual(c.reservation_type_selection(),choice)
   c.reservation_type=raw
   self.assertEqual(c.reservation_type,canonical); self.assertEqual(c.legacy_request_payload()['reservation_type'],raw)
   c=New.model_construct(**base,reservation_type=raw)
   self.assertEqual(c.reservation_type,canonical); self.assertEqual(c.legacy_request_payload()['reservation_type'],raw)
  self.assertEqual(o.legacy_request_payload()['reservation_type'],' material ')
  c=o.model_copy(update={'reservation_type':123})
  self.assertIsNone(c.reservation_type); self.assertEqual(c.legacy_request_payload()['reservation_type'],123)
  self.assertIs(c.reservation_type_selection(),DeferredReservationType.INVALID)
  o.reservation_type=123
  self.assertIsNone(o.reservation_type); self.assertEqual(o.legacy_request_payload()['reservation_type'],123)
  class Deferred:
   def __str__(self): raise AssertionError('coerced too early')
  value=Deferred(); c=o.model_copy(update={'reservation_type':value})
  self.assertIsNone(c.reservation_type); self.assertIs(c.legacy_request_payload()['reservation_type'],value)
  o.reservation_type=value; self.assertIsNone(o.reservation_type)
 def test_strict_bytes_json_and_existing_instance(self):
  for raw in [b' material ',b'',b'unknown']:
   o=New.model_validate({**base,'reservation_type':raw})
   self.assertEqual(o.legacy_request_payload()['reservation_type'],raw.decode())
   with self.assertRaises(ValidationError): New.model_validate({**base,'reservation_type':raw},strict=True)
   self.assertIs(New.model_validate(o),o)
  with self.assertRaises(ValidationError): New(**base,reservation_type=None)
 def test_concurrent_capture(self):
  raws=[' material ',' accessory ','','unknown','   ']*30
  def parse(raw): return New.model_validate(UserDict({**base,'reservation_type':raw})).legacy_request_payload()['reservation_type']
  with ThreadPoolExecutor(max_workers=4) as pool: self.assertEqual(list(pool.map(parse,raws)),raws)
 def test_attribute_read_once(self):
  class Input:
   production_order_id=1; item_id=2; reserved_quantity=1; unit='kg'; reads=0
   @property
   def reservation_type(self):
    self.reads+=1
    if self.reads>1: raise AssertionError('read twice')
    return 'unknown'
  value=Input(); result=New.model_validate(value,from_attributes=True)
  self.assertEqual(value.reads,1); self.assertIs(result.reservation_type_selection(),DeferredReservationType.INVALID)
if __name__=='__main__': unittest.main()
