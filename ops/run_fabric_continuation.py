"""Explicit prepare / backup / apply for the confirmed follow-up scope."""
import argparse
import base64
import hashlib
import json
import zlib
from run_fabric_reconciliation import ROOT, OUT, remote, collect_images


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','backup','apply']);args=parser.parse_args()
    if args.action=='prepare':
        plan=json.loads((OUT/'continuation-plan.json').read_text(encoding='utf-8'))
        virtual={'workbooks':plan['workbooks'],'plans':[{'status':'prepared','action':a['kind'],'sources':a['sources']} for a in plan['actions']]}
        images=collect_images(virtual)
        assert sum(str(i) in images for i,a in enumerate(plan['actions']) if a['ref'].startswith('S'))==15
        ph=hashlib.sha256(json.dumps(plan,sort_keys=True,ensure_ascii=True).encode()).hexdigest()
        payload={'plan':plan,'plan_sha256':ph,'images':images,
                 'snapshot':json.loads((OUT/'continuation-before.json').read_text(encoding='utf-8'))}
        (OUT/'continuation-payload.json').write_text(json.dumps(payload),encoding='utf-8')
        print(json.dumps({'actions':len(plan['actions']),'images':len(images),'plan_sha256':ph}))
    elif args.action=='backup':
        result=remote((ROOT/'ops/backup_fabric_reconciliation.py').read_text(),'python3 -')
        (OUT/'continuation-backup.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
    else:
        payload=json.loads((OUT/'continuation-payload.json').read_text())
        payload['backup']=json.loads((OUT/'continuation-backup.json').read_text())
        code='import json,base64,zlib,types,sys\n'
        for name in ('fabric_reconciliation_snapshot','apply_fabric_reconciliation','apply_fabric_continuation'):
            source=(ROOT/'ops'/f'{name}.py').read_text(encoding='utf-8')
            code+=f'm=types.ModuleType({name!r}); sys.modules[{name!r}]=m; exec({source!r},m.__dict__)\n'
        encoded=base64.b64encode(zlib.compress(json.dumps(payload).encode(),6)).decode()
        code+=f'payload=json.loads(zlib.decompress(base64.b64decode({encoded!r})))\n'
        code+='from app.db.session import engine\nfrom fabric_reconciliation_snapshot import capture\nfrom apply_fabric_continuation import apply\nprint(json.dumps(apply(engine,capture,payload)))\n'
        result=remote(code,'docker exec -i milana-backend-green python -')
        filename='continuation-replay.json' if result.get('already_applied') else 'continuation-result.json'
        (OUT/filename).write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in result.items() if k not in ('changes','backup')}))


if __name__=='__main__':main()
