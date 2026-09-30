"""Read-only post-application checks, including public inventory API visibility."""
import ast
import json
from decimal import Decimal
from pathlib import Path
from run_fabric_reconciliation import OUT, ROOT, remote


def main():
    before = json.loads((OUT/'production-snapshot.json').read_text(encoding='utf-8'))
    after = json.loads((OUT/'post-apply-snapshot.json').read_text(encoding='utf-8'))
    result = json.loads((OUT/'application-result.json').read_text())
    plan = json.loads((OUT/'reconciliation-plan.json').read_text(encoding='utf-8'))
    # Reuse only the pure verification function, without loading application settings locally.
    tree = ast.parse((ROOT/'ops/apply_fabric_reconciliation.py').read_text())
    definition = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'verify_after')
    namespace = {'Decimal': Decimal}
    from collections import Counter
    namespace['Counter'] = Counter
    exec(compile(ast.Module(body=[definition], type_ignores=[]), '<read-only verification>', 'exec'), namespace)
    checks = namespace['verify_after'](before, after, result['changes'])
    batches = {b['id']: b for b in after['batches']}
    unchanged = [p for p in plan['plans'] if p['status'] == 'unchanged']
    assert all(sum(Decimal(batches[bid]['quantity']) for bid in p['erp_ids']) == Decimal(p['target_kg']) for p in unchanged)
    for c in result['changes']:
        assert Decimal(batches[c['id']]['quantity']) == Decimal(plan['plans'][c['plan_index']]['target_kg'])
    code = '''import json
from decimal import Decimal
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from app.core.security import create_access_token
token=create_access_token('1')
health={}
for url in ['http://172.16.10.4:8000/health','http://172.16.10.5:3000/login','https://erp.milanapremium.uz/health','https://erp.milanapremium.uz/login']:
 with urlopen(Request(url,method='HEAD' if url.endswith('/login') else 'GET'),timeout=25) as r:
  assert r.status==200
  health[url]=r.status
rows={}
counts={}
for archived in [False,True]:
 page=1
 while True:
  qs=urlencode(dict(group='materials',include_total='true',archived=str(archived).lower(),page=page,page_size=500))
  req=Request('https://erp.milanapremium.uz/api/inventory/batches?'+qs,headers={'Authorization':'Bearer '+token})
  with urlopen(req,timeout=30) as r:
   assert r.status==200
   data=json.load(r)
  for b in data['rows']:
   rows[b['id']]=b
  counts[str(archived)]=data['total']
  if page*data['page_size']>=data['total']:break
  page+=1
for c in EXPECTED:
 b=rows[c['id']]
 assert Decimal(str(b['quantity']))==Decimal(c['after_kg'])
 assert Decimal(str(b['available_quantity']))>=0
 if c['action']=='archive':assert b['archived_at']
print(json.dumps(dict(health=health,api_verified_changes=len(EXPECTED),api_rows=len(rows),api_view_counts=counts)))
'''
    code = 'EXPECTED='+repr(result['changes'])+'\n'+code
    api = remote(code, 'docker exec -i milana-backend-green python -')
    checks.update(api)
    checks.update({'unchanged_matches_verified':len(unchanged), 'applied_targets_verified':len(result['changes']),
                   'full_inventory_match':False, 'unresolved_batch_groups':89, 'erp_absent_from_source':69,
                   'incomplete_supplemental_rows':26, 'remaining_roll_differences':49,
                   'capture_time':after['snapshot_time']})
    (OUT/'live-verification.json').write_text(json.dumps(checks, indent=2), encoding='utf-8')
    print(json.dumps(checks))


if __name__ == '__main__':
    main()
