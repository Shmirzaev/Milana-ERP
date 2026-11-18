"""Negative tests against actual rollback-rehearsal snapshots, without DB access."""
import ast
import copy
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
source=ast.parse((ROOT/'ops/swap_po0640_po0641.py').read_text())
namespace={'PACKAGES':(21328,21329,21330)}
selected=[node for node in source.body if isinstance(node,ast.FunctionDef) and node.name=='verify_delta']
exec(compile(ast.Module(body=selected,type_ignores=[]),'<reviewed-preservation-guard>','exec'),namespace)
evidence_available=all((ROOT/f'outputs/po0640-swap/{name}.json').exists() for name in ('inspect','rehearse'))
before=json.loads((ROOT/'outputs/po0640-swap/inspect.json').read_text())['snapshot'] if evidence_available else None
after=json.loads((ROOT/'outputs/po0640-swap/rehearse.json').read_text())['preview'] if evidence_available else None


@unittest.skipUnless(evidence_available,'Requires private owner-authorized rehearsal evidence')
class PreservationGuards(unittest.TestCase):
    def test_rehearsed_exchange_passes(self):
        namespace['verify_delta'](before,after)

    def rejected(self,table,field,value,index=0):
        changed=copy.deepcopy(after)
        changed[table][index][field]=value
        with self.assertRaises(AssertionError):namespace['verify_delta'](before,changed)

    def test_payroll_payload_change_rejected(self):
        self.rejected('payroll_qr_labels','payload','changed')

    def test_payroll_amount_change_rejected(self):
        self.rejected('payroll_records','total_amount','999.0')

    def test_stock_quantity_change_rejected(self):
        self.rejected('finished_goods_stock','quantity',999)

    def test_package_quantity_change_rejected(self):
        self.rejected('packages','total_quantity',999)

    def test_other_nastil_change_rejected(self):
        index=next(i for i,r in enumerate(after['production_batches']) if r['id']==921)
        self.rejected('production_batches','planned_quantity',999,index)

    def test_historic_print_snapshot_change_rejected(self):
        index=next(i for i,r in enumerate(after['package_print_run_members']) if r['id']==4304)
        self.rejected('package_print_run_members','snapshot',{},index)

    def test_original_po_plan_change_rejected(self):
        self.rejected('production_orders','planned_quantity',999)


if __name__=='__main__':unittest.main()
