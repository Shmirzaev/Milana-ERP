import unittest
from plan_catalog_qolip_sync import build

def master(code='XJ3062',q='4396',id='1'):
    return dict(old_id=id,model_no=code,qolip_no=q,product='Dress')
def old(code='XJ3062',v='V-5709',q='4396'):
    return dict(old_id=v,model_no=code,variant_no=v,sewing_model_ref=q,color='Blue')
def new(code='XJ3062',v='V-100',scope='standard'):
    return dict(id=1,code=code+'-'+v,catalog_scope=scope,general_details={'model_no':code,'variant_no':v})

class CatalogPlanTests(unittest.TestCase):
    def test_explicit_excluded_mixed_material_never_created(self):
        plan=build([master()],[old()],[new()])
        self.assertEqual(plan['creates'],[])
        self.assertEqual(plan['held'][0]['kind'],'excluded_or_invalid_variant')
    def test_cross_model_variant_held(self):
        plan=build([master('SJ4070','4090')],[old('SJ4070','V-5976','4090')],[new('SJ4004','V-5976')])
        self.assertTrue(any(h['kind']=='variant_number_other_model' for h in plan['held']))
        self.assertFalse(any(c['variant_no']=='V-5976' for c in plan['creates']))
    def test_variant_source_resolves_duplicate_master_qolip(self):
        plan=build([master(q='4396'),master(q='4400',id='2')],[old(v='V-100')],[new()])
        self.assertEqual(plan['qolip_updates'][0]['qolip_no'],'4396')
    def test_ambiguous_source_not_guessed(self):
        plan=build([master(q='4396'),master(q='4400',id='2')],[],[new()])
        self.assertEqual(plan['qolip_updates'],[])
        self.assertTrue(any(h['kind']=='ambiguous_qolip' for h in plan['held']))
    def test_usluga_and_legacy_untouched(self):
        legacy=new();legacy['code']='LEGACY-1'
        plan=build([master()],[],[new(scope='usluga'),legacy])
        self.assertEqual(plan['qolip_updates'],[])
    def test_idempotent_qolip_and_variant(self):
        row=new();row['general_details'].update(qolip_no='4396',mold_no='4396')
        plan=build([master()],[old(v='V-100')],[row])
        self.assertEqual(plan['qolip_updates'],[]);self.assertEqual(plan['creates'],[])

if __name__=='__main__': unittest.main()
