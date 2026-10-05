"""Explicit prepare, validated backup, atomic application and immediate readback."""
import argparse
import ast
import base64
from decimal import Decimal
import hashlib
import json
import zlib
from run_fabric_reconciliation import ROOT, OUT, remote, collect_images


def modules():
    code='import json,base64,zlib,types,sys\n'
    for name in ('fabric_reconciliation_snapshot','apply_fabric_reconciliation','apply_fabric_continuation'):
        source=(ROOT/'ops'/f'{name}.py').read_text(encoding='utf-8')
        code+=f'm=types.ModuleType({name!r});sys.modules[{name!r}]=m;exec({source!r},m.__dict__)\n'
    return code


def main(action):
    if action=='capture':
        result=remote((ROOT/'ops/fabric_reconciliation_snapshot.py').read_text(),'docker exec -i milana-backend-blue python -')
        (OUT/'production-snapshot.json').write_text(json.dumps(result),encoding='utf-8')
        print(json.dumps(dict(captured=result['snapshot_time'],batches=len(result['batches']))))
    elif action=='prepare':
        plan=json.loads((OUT/'current-plan.json').read_text(encoding='utf-8'))
        virtual={'workbooks':plan['workbooks'],'plans':[{'status':'prepared','action':a['kind'],'sources':a['sources']} for a in plan['actions']]}
        images=collect_images(virtual)
        ph=hashlib.sha256(json.dumps(plan,sort_keys=True,ensure_ascii=True).encode()).hexdigest()
        payload=dict(plan=plan,plan_sha256=ph,images=images,snapshot=json.loads((OUT/'production-snapshot.json').read_text()))
        projected={b['id']:dict(b) for b in payload['snapshot']['batches']}
        for i,a in enumerate(plan['actions']):
            if a['kind']=='update':projected[a['id']].update(a['values'])
            else:projected[-i-1]=dict(supplier_id=a['supplier_id'],batch_no=a['batch_no'],quantity=a['quantity'],piece_count=a['piece_count'])
        norm=lambda v:''.join(str(v or '').upper().split())
        for o in plan['outcomes']:
            r=o['sources'][0]
            matched=[b for b in projected.values() if b['supplier_id']==r['supplier_id'] and norm(b['batch_no'])==norm(r['batch_no'])]
            assert sum(Decimal(b['quantity']) for b in matched)==Decimal(o['target_kg']),o['ref']
            live=[b for b in matched if Decimal(b['quantity'])>0]
            assert sum(b['piece_count'] or 0 for b in live)==Decimal(o['target_rolls']),o['ref']
        (OUT/'current-payload.json').write_text(json.dumps(payload),encoding='utf-8')
        print(json.dumps(dict(actions=len(plan['actions']),images=len(images),plan_sha256=ph)))
    elif action=='backup':
        result=remote((ROOT/'ops/backup_fabric_reconciliation.py').read_text(),'python3 -')
        (OUT/'current-backup.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result))
    elif action=='apply':
        payload=json.loads((OUT/'current-payload.json').read_text())
        payload['backup']=json.loads((OUT/'current-backup.json').read_text())
        for book in payload['plan']['workbooks']:
            from run_fabric_reconciliation import SOURCE
            assert hashlib.sha256((SOURCE/book['file']).read_bytes()).hexdigest()==book['sha256']
        code=modules()
        encoded=base64.b64encode(zlib.compress(json.dumps(payload).encode())).decode()
        code+=f'payload=json.loads(zlib.decompress(base64.b64decode({encoded!r})))\n'
        code+='from app.db.session import engine\nfrom fabric_reconciliation_snapshot import capture\nfrom apply_fabric_continuation import apply\nprint(json.dumps(apply(engine,capture,payload)))\n'
        result=remote(code,'docker exec -i milana-backend-blue python -')
        name='current-replay.json' if result.get('already_applied') else 'current-result.json'
        (OUT/name).write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in result.items() if k not in ('changes','backup')}))
    elif action=='verify':
        result=json.loads((OUT/'current-result.json').read_text())
        payload=json.loads((OUT/'current-payload.json').read_text())
        after=remote((ROOT/'ops/fabric_reconciliation_snapshot.py').read_text(),'docker exec -i milana-backend-blue python -')
        (OUT/'current-after.json').write_text(json.dumps(after),encoding='utf-8')
        tree=ast.parse((ROOT/'ops/apply_fabric_continuation.py').read_text())
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='verify')
        scope={'Decimal':Decimal}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'<readback>','exec'),scope)
        checks=scope['verify'](payload['snapshot'],after,payload['plan'],result['changes'],result['new_items'])
        code='''import json
from decimal import Decimal
from urllib.request import Request,urlopen
from urllib.parse import urlencode
from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.services.audit import verify_audit_hash_chain
from sqlalchemy import text
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
with SessionLocal() as db:
 start=db.execute(text("SELECT min(id) FROM audit_logs WHERE new_value_json->>'plan_sha256'=:h"),{'h':PLAN_HASH}).scalar_one()
 audit=verify_audit_hash_chain(db,start_id=start)
 assert audit['ok'],audit
 numbers=dict(db.execute(text('SELECT id,production_no FROM production_orders WHERE id=ANY(:ids)'),{'ids':ORDER_IDS}).all()) if ORDER_IDS else {}
plans=[{'production_order':numbers[oid],'summary':get('https://erp.milanapremium.uz/api/inventory/reservations/plan?production_order_id='+str(oid),True)['summary']} for oid in ORDER_IDS]
print(json.dumps(dict(health=health,api_verified_changes=len(EXPECTED),api_rows=len(rows),audit_chain=audit,planning=plans)))
'''
        code='EXPECTED='+repr(result['changes'])+'\nPLAN_HASH='+repr(result['plan_sha256'])+'\nORDER_IDS='+repr(sorted({r['production_order_id'] for r in result['released_reservations']}))+'\n'+code
        checks.update(remote(code,'docker exec -i milana-backend-blue python -'))
        (OUT/'current-verification.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
        print(json.dumps(checks))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['capture','prepare','backup','apply','verify'])
    main(parser.parse_args().action)
