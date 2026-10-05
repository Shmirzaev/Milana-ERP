"""Explicit SSH launcher; evidence stays in ignored outputs."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/bso-cleanup'
SSH = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', '-i',
       str(Path.home()/'.ssh/milana_erp_deploy_ed25519'), 'admilana@172.16.10.4']


def remote(source, command='docker exec -i milana-backend-green python -'):
    result = subprocess.run(SSH + [command], input=source.encode(), capture_output=True)
    if result.returncode:
        (OUT / 'error.txt').write_bytes(result.stderr)
        raise RuntimeError('Remote command failed; inspect private outputs/bso-cleanup/error.txt')
    return json.loads(result.stdout)


def verify_backup(backup):
    code = '''import hashlib,json,pathlib,subprocess
expected=EXPECTED
name=pathlib.Path(expected['path']).name
directory='/opt/milana-erp/shared/backups'
cmd=['docker','run','--rm','--user','0','--network','none','--read-only','-v',directory+':/backup:ro']
meta=json.loads(subprocess.check_output(cmd+['--entrypoint','python','ghcr.io/shmirzaev/milana-erp-backend:20261005_043438','-c','import pathlib,json,hashlib;p=pathlib.Path('+repr('/backup/'+name)+');print(json.dumps(dict(bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())))']))
listing=subprocess.check_output(cmd+['postgres:16-alpine','pg_restore','--list','/backup/'+name])
assert meta['sha256']==expected['sha256'] and meta['bytes']==expected['bytes']
assert hashlib.sha256(listing).hexdigest()==expected['restore_list_sha256']
print(json.dumps({'verified':True}))
'''.replace('EXPECTED',repr(backup))
    assert remote(code, 'python3 -')['verified']


def verify_release():
    for host in ('172.16.10.4','172.16.10.5'):
        command = 'readlink -f /opt/milana-erp/current; sha256sum /opt/milana-erp/current/SOURCE_MANIFEST.sha256'
        result = subprocess.run(SSH[:-1]+['admilana@'+host,command],capture_output=True,check=True)
        lines = result.stdout.decode().splitlines()
        assert lines[0]=='/opt/milana-erp/releases/20261005_043438'
        assert lines[1].split()[0]=='f653cfef6db2b0dc2a58bd747f856cc784c5f16a62c782d2aad787093a81d465'


if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    action = sys.argv[1]
    if action == 'inspect':
        result = remote((ROOT/'ops/inspect_bso_cleanup.py').read_text())
        (OUT/'inspection.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps({k:result[k] for k in ('groups','counts','blocked','revision')}))
    elif action == 'backup':
        source = (ROOT/'ops/backup_fabric_reconciliation.py').read_text().replace('milana_erp_pre_fabric_reconcile_', 'milana_erp_pre_bso_cleanup_')
        result = remote(source, 'python3 -')
        (OUT/'backup.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result))
    elif action in ('plan', 'rehearse', 'apply'):
        source = (ROOT/'ops/delete_bso_through_0038.py').read_text()
        expected = json.loads((OUT/'plan.json').read_text()) if action != 'plan' else None
        backup = json.loads((OUT/'backup.json').read_text()) if action != 'plan' else None
        if backup:
            verify_backup(backup)
        if action == 'apply':
            verify_release()
            committed = subprocess.check_output(['git','show','HEAD:ops/delete_bso_through_0038.py'], cwd=ROOT)
            assert committed.decode().replace('\r\n','\n') == source, 'Uncommitted operation'
            rehearsal = json.loads((OUT/'rehearse.json').read_text())
            assert rehearsal['rollback_verified']
            assert rehearsal['source_sha256'] == hashlib.sha256(source.encode()).hexdigest()
            assert rehearsal['plan_sha256'] == hashlib.sha256(json.dumps(expected,sort_keys=True,default=str).encode()).hexdigest()
            assert json.loads((OUT/'archive.json').read_text())['archived_files'] > 0
        code = source + '\nprint(json.dumps(operation(' + repr(action) + ',' + repr(expected) + ',' + repr(backup) + '),default=str))\n'
        result = remote(code)
        if action == 'rehearse':
            result['source_sha256'] = hashlib.sha256(source.encode()).hexdigest()
            result['plan_sha256'] = hashlib.sha256(json.dumps(expected,sort_keys=True,default=str).encode()).hexdigest()
        (OUT/(action+'.json')).write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps({k:v for k,v in result.items() if k in ('counts','groups','retained_groups','deleted','audit_id','plan_sha256','rollback_verified','would_delete')}))
    elif action in ('archive', 'remove-media'):
        plan = json.loads((OUT/'plan.json').read_text())
        backup = json.loads((OUT/'backup.json').read_text())
        committed = json.loads((OUT/'apply.json').read_text()) if action == 'remove-media' else None
        if committed:
            assert json.loads((OUT/'verification.json').read_text())['targets_absent']
        source = (ROOT/'ops/archive_bso_cleanup_barcodes.py').read_text()
        code = source + '\nprint(json.dumps(archive_media(' + repr(plan) + ',' + repr(backup) + ',' + repr(committed) + ')))\n'
        command = ('docker run --rm -i --user 0 --network none --read-only '
                   '-v /opt/milana-erp/shared/backups:/backup '
                   '-v /app/storage/barcodes:/barcodes' + (':ro' if action == 'archive' else '') +
                   ' --entrypoint python ghcr.io/shmirzaev/milana-erp-backend:20261005_043438 -')
        result = remote(code, command)
        (OUT/(action+'.json')).write_text(json.dumps(result, indent=2))
        print(json.dumps(result))
    elif action == 'verify':
        plan = json.loads((OUT/'plan.json').read_text())
        committed = json.loads((OUT/'apply.json').read_text())
        source = (ROOT/'ops/delete_bso_through_0038.py').read_text()
        code = 'import json,types,sys\nm=types.ModuleType("bso_cleanup_operation");sys.modules[m.__name__]=m\nexec('+repr(source)+',m.__dict__)\n'
        code += (ROOT/'ops/verify_bso_cleanup.py').read_text()
        code += '\nprint(json.dumps(verify_cleanup('+repr(plan)+','+repr(committed)+'),default=str))\n'
        result = remote(code)
        (OUT/'verification.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result))
    else:
        raise ValueError('Unknown action')
