"""Fresh snapshot and public API evidence after the follow-up data update."""
import ast
import json
from collections import defaultdict
from decimal import Decimal
from run_fabric_reconciliation import OUT, ROOT, remote
from reconcile_fabric_workbooks import read_sources, key


def main():
    before=json.loads((OUT/'continuation-before.json').read_text(encoding='utf-8'))
    after=json.loads((OUT/'continuation-after.json').read_text(encoding='utf-8'))
    plan=json.loads((OUT/'continuation-plan.json').read_text(encoding='utf-8'))
    result=json.loads((OUT/'continuation-result.json').read_text())
    tree=ast.parse((ROOT/'ops/apply_fabric_continuation.py').read_text())
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='verify')
    ns={'Decimal':Decimal};exec(compile(ast.Module(body=[node],type_ignores=[]),'<verification>','exec'),ns)
    checks=ns['verify'](before,after,plan,result['changes'],result['new_items'])
    records=read_sources(json.loads((OUT/'source-workbooks.json').read_text(encoding='utf-8')))
    targets=defaultdict(Decimal);actual=defaultdict(Decimal)
    for r in records:targets[(r['supplier_id'],key(r['batch_no']))]+=r['remaining_kg']
    for b in after['batches']:actual[(b['supplier_id'],key(b['batch_no']))]+=Decimal(b['quantity'])
    differences=[{'supplier_id':k[0],'batch':k[1],'excel_kg':str(v),'erp_kg':str(actual[k])} for k,v in targets.items() if actual[k]!=v]
    checks['detailed_source_groups']=len(targets)
    checks['detailed_source_kg_differences']=differences
    assert not differences, differences
    code='''import json
from decimal import Decimal
from urllib.request import Request,urlopen
from urllib.parse import urlencode
from app.core.security import create_access_token
headers={'Authorization':'Bearer '+create_access_token('1')}
def get(url,auth=False):
 with urlopen(Request(url,headers=headers if auth else {},method='HEAD' if url.endswith('/login') else 'GET'),timeout=30) as r:
  assert r.status==200
  return None if url.endswith('/login') else json.load(r)
health={}
for url in ['http://172.16.10.4:8000/health','http://172.16.10.5:3000/login','https://erp.milanapremium.uz/health','https://erp.milanapremium.uz/login']:
 get(url);health[url]=200
rows={}
for archived in [False,True]:
 page=1
 while True:
  data=get('https://erp.milanapremium.uz/api/inventory/batches?'+urlencode(dict(group='materials',archived=str(archived).lower(),include_total='true',page=page,page_size=500)),True)
  rows.update({r['id']:r for r in data['rows']})
  if page*data['page_size']>=data['total']:break
  page+=1
for c in EXPECTED:
 b=rows[c['id']]
 assert Decimal(str(b['quantity']))==Decimal(c['after_kg']) and b['piece_count']==c['after_rolls']
 assert Decimal(str(b['available_quantity']))>=0
for bid in KEPT:assert bid in rows
reservations=get('https://erp.milanapremium.uz/api/inventory/reservations?production_order_id=181',True)
r=next(r for r in reservations if r['id']==3)
assert r['status']=='released' and Decimal(str(r['consumed_quantity']))==176 and Decimal(str(r['released_quantity']))==24
planning=get('https://erp.milanapremium.uz/api/inventory/reservations/plan?production_order_id=181',True)
print(json.dumps(dict(health=health,api_verified_changes=len(EXPECTED),api_rows=len(rows),kept_batches_visible=len(KEPT),reservation_verified=True,planning_summary=planning.get('summary'))))
'''
    code='EXPECTED='+repr(result['changes'])+'\nKEPT='+repr(plan['preserved_ids'])+'\n'+code
    checks.update(remote(code,'docker exec -i milana-backend-green python -'))
    checks['capture_time']=after['snapshot_time']
    (OUT/'continuation-verification.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
    print(json.dumps(checks))


if __name__=='__main__':main()
