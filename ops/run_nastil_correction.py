"""Explicit launcher for CUT-251; private evidence stays in ignored outputs."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/nastil-0271'
SSH = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', '-i',
       str(Path.home() / '.ssh/milana_erp_deploy_ed25519'), 'admilana@172.16.10.4']
RELEASE = '20261013_100631'
MANIFEST = '00709a9051255e73b8f1d345ce9717dfd2232bedb80609849e788170a1869777'


def remote(source, command='docker exec -i milana-backend-green python -'):
    response = subprocess.run(SSH + [command], input=source.encode(), capture_output=True)
    if response.returncode:
        (OUT / 'error.txt').write_bytes(response.stderr)
        raise RuntimeError('Remote command failed; inspect private outputs/nastil-0271/error.txt')
    return json.loads(response.stdout)


def verify_release():
    for host in ('172.16.10.4', '172.16.10.5'):
        result = subprocess.check_output(SSH[:-1] + ['admilana@' + host,
            'readlink -f /opt/milana-erp/current; sha256sum /opt/milana-erp/current/SOURCE_MANIFEST.sha256'])
        lines = result.decode().splitlines()
        assert lines[0] == '/opt/milana-erp/releases/' + RELEASE
        assert lines[1].split()[0] == MANIFEST


def verify_backup(backup):
    code = '''import hashlib,json,subprocess
expected=EXPECTED
name=expected['path'].rsplit('/',1)[1]
cmd=['docker','run','--rm','--user','0','--network','none','--read-only','-v','/opt/milana-erp/shared/backups:/backup:ro']
listing=subprocess.check_output(cmd+['postgres:16-alpine','pg_restore','--list','/backup/'+name])
meta=json.loads(subprocess.check_output(cmd+['--entrypoint','python','ghcr.io/shmirzaev/milana-erp-backend:RELEASE','-c','import pathlib,json,hashlib;p=pathlib.Path('+repr('/backup/'+name)+');print(json.dumps(dict(bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())))']))
assert meta['bytes']==expected['bytes'] and meta['sha256']==expected['sha256']
assert hashlib.sha256(listing).hexdigest()==expected['restore_list_sha256']
print(json.dumps({'verified':True}))
'''.replace('EXPECTED', repr(backup)).replace('RELEASE', RELEASE)
    assert remote(code, 'python3 -')['verified']


if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    action = sys.argv[1]
    verify_release()
    if action == 'backup':
        source = (ROOT / 'ops/backup_fabric_reconciliation.py').read_text()
        source = source.replace('milana-backend-blue', 'milana-backend-green')
        source = source.replace('milana_erp_pre_fabric_reconcile_', 'milana_erp_pre_nastil0271_')
        source = source.replace('20261005_070406', RELEASE)
        result = remote(source, 'python3 -')
    else:
        route_source = (ROOT / 'backend/app/api/routes/production.py').read_text(encoding='utf-8')
        function = next(n for n in ast.parse(route_source).body
                        if isinstance(n, ast.FunctionDef) and n.name == 'update_usluga_bundle_size_counts')
        function_source = '\n'.join(route_source.splitlines()[function.lineno-1:function.end_lineno])
        source_hash = hashlib.sha256(function_source.encode()).hexdigest()
        operation_source = (ROOT / 'ops/correct_nastil_0271.py').read_text(encoding='utf-8')
        operation_hash = hashlib.sha256(operation_source.encode()).hexdigest()
        expected = json.loads((OUT / 'inspect.json').read_text()) if action != 'inspect' else None
        backup = json.loads((OUT / 'backup.json').read_text()) if action != 'inspect' else None
        if backup:
            verify_backup(backup)
        if action == 'apply':
            for path, source in [('backend/app/api/routes/production.py', route_source),
                                 ('ops/correct_nastil_0271.py', operation_source)]:
                committed = subprocess.check_output(['git', 'show', 'HEAD:' + path], cwd=ROOT).decode()
                assert committed.replace('\r\n', '\n') == source
            rehearsal = json.loads((OUT / 'rehearse.json').read_text())
            assert rehearsal['rollback_verified'] and rehearsal['operation_hash'] == operation_hash
            assert rehearsal['source_hash'] == source_hash and rehearsal['before'] == expected['fingerprint']
        code = operation_source + '\nprint(json.dumps(operation(' + ','.join(map(repr, [
            action, function_source, source_hash, expected, backup,
        ])) + '),default=str))\n'
        result = remote(code)
        result.update(source_hash=source_hash, operation_hash=operation_hash)
    (OUT / (action + '.json')).write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'changed'}))
