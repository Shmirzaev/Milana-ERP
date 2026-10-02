"""Offline regression tests for reconciliation boundaries and ledger arithmetic."""
from copy import deepcopy
from decimal import Decimal
import unittest
from plan_fabric_reconciliation import build_plan
from preview_fabric_reconciliation import preview
from reconcile_fabric_workbooks import number, read_sources

def fixture():
    batch={'id':1,'item_id':87,'batch_no':'1234','supplier_id':2,'quantity':'100.0000',
           'piece_count':5,'unit':'kg','warehouse_id':1,'received_date':'2026-09-01',
           'archived_at':None,'roll_weights_kg':[20]*5,'roll_lengths_m':[100]*5,
           'image_url':'original.jpg','cost_per_unit':'6.1','qc_status':'passed'}
    snap={'items':[{'id':87,'name':'30/1P_CMP SUPREM','is_active':True},{'id':12,'name':'36/1 P_CMP 20 DEN 8% LYC SUPREM','is_active':True}],
          'batches':[batch],'suppliers':[{'id':2,'name':'Dinar'}],'movements':[{'id':1,'batch_id':1,'movement_type':'receive','quantity':'100'}],
          'reservations':[],'linked_rows':{},'fabric_scans':[]}
    row={'file':'source.xlsx','sheet':'Sheet1','row':3,'supplier_id':2,'group':'Dinar',
         'batch_no':'1234','fabric':'30/1 P_CMP SUPREM','date':'01,09,2026',
         'received_rolls':Decimal(5),'received_kg':Decimal(100),'used_rolls':Decimal(1),
         'used_kg':Decimal(20),'remaining_rolls':Decimal(4),'remaining_kg':Decimal(80),
         'color_code':'','color':'','issues':[]}
    return snap,row

class ReconciliationTests(unittest.TestCase):
    def source_fixture(self, cached):
        values=[None,'DINAR','01,09,2026',5,100,'1234',None,None,None,'30/1 P_CMP SUPREM',1,20,4,cached]
        evidence=[{'file':'Dinar.xlsx','sheets':[{'sheet':'Main','rows':[{'row':3,'values':values,'formulas':{}}]}]},
                  {'file':'Samo.xlsx','sheets':[{'sheet':'Samo','rows':[]}]},
                  {'file':'Saff.xlsx','sheets':[{'sheet':'Dana','rows':[]},{'sheet':'Extra','rows':[]},{'sheet':'Zuxra','rows':[]}]}]
        return read_sources(evidence)[0]

    def test_user_confirmed_remaining_kg_wins_over_arithmetic(self):
        r=self.source_fixture(125)
        self.assertEqual(r['remaining_kg'],Decimal(125))
        self.assertEqual(r['arithmetic_remaining_kg'],Decimal(80))

    def test_user_confirmed_zero_is_not_replaced(self):
        self.assertEqual(self.source_fixture(0)['remaining_kg'],Decimal(0))

    def test_blank_balance_uses_authorized_receipt_minus_usage(self):
        self.assertEqual(self.source_fixture(None)['remaining_kg'],Decimal(80))

    def test_positive_kg_does_not_invent_missing_roll_count(self):
        s,r=fixture();r['batch_no']='9999';r['remaining_rolls']=Decimal(0)
        p=build_plan([r],s);a,c=preview(s,{'plans':p})
        self.assertIsNone(a['batches'][-1]['piece_count'])

    def test_decimal_locale(self):
        self.assertEqual(number('23\u00a0840,54'),Decimal('23840.5400'))

    def test_adjustment_preserves_roll_history_and_links(self):
        s,r=fixture();s['linked_rows']={'production_order_materials:stock_batch_id':[{'id':1,'stock_batch_id':1}]}
        plans=build_plan([r],s);a,c=preview(s,{'plans':plans})
        self.assertEqual(plans[0]['action'],'adjust')
        self.assertEqual(a['batches'][0]['quantity'],'80.0000')
        self.assertEqual(a['batches'][0]['roll_weights_kg'],[20]*5)
        self.assertEqual(a['linked_rows'],s['linked_rows'])
        self.assertEqual(c['net_delta_kg'],'-20.0000')

    def test_reserved_shortfall_is_withheld(self):
        s,r=fixture();s['reservations']=[{'stock_batch_id':1,'status':'reserved','reserved_quantity':90,'consumed_quantity':0,'released_quantity':0}]
        self.assertEqual(build_plan([r],s)[0]['status'],'review')

    def test_linked_zero_cannot_archive(self):
        s,r=fixture();r['remaining_kg']=Decimal(0);s['linked_rows']={'cutting_records:fabric_batch_id':[{'id':1,'fabric_batch_id':1}]}
        self.assertEqual(build_plan([r],s)[0]['status'],'review')

    def test_zero_with_different_material_cannot_archive(self):
        s,r=fixture();r['remaining_kg']=Decimal(0);r['fabric']='36/1 P_CMP 20 DEN 8% LYC SUPREM'
        self.assertEqual(build_plan([r],s)[0]['status'],'review')

    def test_archive_is_not_hard_delete(self):
        s,r=fixture();r['remaining_kg']=Decimal(0);p=build_plan([r],s);a,c=preview(s,{'plans':p})
        self.assertEqual(len(a['batches']),1);self.assertIsNotNone(a['batches'][0]['archived_at'])
        self.assertEqual(c['hard_deletions'],0);self.assertEqual(a['movements'][-1]['quantity'],'100.0000')

    def test_missing_from_source_is_not_automatic_removal(self):
        s,r=fixture();p=build_plan([],s)
        self.assertEqual(p[0]['status'],'review');a,c=preview(s,{'plans':p});self.assertEqual(a,s)

    def test_supplier_collision_is_withheld(self):
        s,r=fixture();s['batches'][0]['supplier_id']=3
        self.assertEqual(build_plan([r],s)[0]['status'],'review')

    def test_multiple_active_batches_are_not_guessed(self):
        s,r=fixture();other=deepcopy(s['batches'][0]);other['id']=2;s['batches'].append(other)
        self.assertEqual(build_plan([r],s)[0]['status'],'review')

    def test_authoritative_balance_is_not_overridden_by_formula_warning(self):
        s,r=fixture();r['issues']=['Balance formula references another row or sheet']
        self.assertEqual(build_plan([r],s)[0]['status'],'prepared')
        self.assertEqual(build_plan([r],s)[0]['target_kg'],Decimal(80))

    def test_archived_receipt_is_not_silently_recreated(self):
        s,r=fixture();s['batches'][0]['quantity']='0';s['batches'][0]['archived_at']='2026-09-02'
        self.assertEqual(build_plan([r],s)[0]['status'],'review')

    def test_new_receipt_uses_remaining_not_gross(self):
        s,r=fixture();r['batch_no']='9999';p=build_plan([r],s);a,c=preview(s,{'plans':p})
        self.assertEqual(p[0]['action'],'receive');self.assertEqual(a['batches'][-1]['quantity'],'80.0000')
        self.assertEqual(a['batches'][-1]['piece_count'],4)
        self.assertEqual(a['batches'][-1]['qc_status'],'pending')

    def test_outstanding_eco_rolls_block_update(self):
        s,r=fixture();s['linked_rows']={'eco_fabric_rolls:batch_id':[{'id':1,'batch_id':1,'returned_at':None}]}
        self.assertEqual(build_plan([r],s)[0]['status'],'review')

    def test_stale_snapshot_rejected(self):
        s,r=fixture();p=deepcopy(build_plan([r],s));s['batches'][0]['quantity']='99'
        with self.assertRaises(ValueError):preview(s,{'plans':p})

    def test_other_suppliers_untouched(self):
        s,r=fixture();s['batches'][0]['supplier_id']=30
        self.assertEqual(build_plan([],s),[])

if __name__=='__main__':unittest.main()
