import unittest
import warnings
from app.libs.dto.inventory.material_reservation_input import MaterialReservationIn
from app.libs.dto.inventory.reservation_type_selection import DeferredReservationType
from app.libs.enums.inventory import MaterialReservationType
BASE={'production_order_id':1,'item_id':2,'reserved_quantity':1,'unit':'kg','reservation_type':' material '}
class Checks(unittest.TestCase):
 def test_copy_update(self):
  with warnings.catch_warnings():
   warnings.simplefilter('ignore')
   for raw,choice in [('unknown',DeferredReservationType.INVALID),(' accessory ',MaterialReservationType.ACCESSORY),('',DeferredReservationType.FALLBACK)]:
    result=MaterialReservationIn(**BASE).copy(update={'reservation_type':raw})
    self.assertEqual(result.legacy_request_payload()['reservation_type'],raw)
    self.assertEqual(result.reservation_type_selection(),choice)
    self.assertEqual(result.reservation_type,choice if isinstance(choice,MaterialReservationType) else None)
 def test_copy_include_exclude_deep(self):
  with warnings.catch_warnings():
   warnings.simplefilter('ignore')
   value=MaterialReservationIn(**BASE)
   for options in [{'exclude':{'reservation_type'}},{'include':{'item_id'}},{'include':{'item_id','reservation_type'}},{'exclude':{'reservation_type'},'update':{'reservation_type':'unknown'}},{'include':{'item_id'},'update':{'reservation_type':''}},{'deep':True}]:
    copied=value.copy(**options); payload=copied.legacy_request_payload()
    if 'reservation_type' not in copied.__dict__:
     self.assertNotIn('reservation_type',payload); self.assertIs(copied.reservation_type_selection(),DeferredReservationType.FALLBACK)
    else:
     expected=options.get('update',{}).get('reservation_type',' material ')
     self.assertEqual(payload['reservation_type'],expected)
   raw=['invalid']; copied=value.copy(update={'reservation_type':raw},deep=True)
   self.assertEqual(copied.legacy_request_payload()['reservation_type'],raw)
   self.assertIsNot(copied.legacy_request_payload()['reservation_type'],raw)
   self.assertIsNone(copied.reservation_type)
if __name__=='__main__': unittest.main()
