"""Explicit launcher; private before-images stay in ignored outputs."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/bst-assignable-20261104'
SSH = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', '-i',
       str(Path.home() / '.ssh/milana_erp_deploy_ed25519')]
RELEASE = '20261103_094602'
MANIFEST = 'ee765f999e782193878390897873c7b5865749460d4d776cf321fcd28490f8a9'
IMAGE = 'ghcr.io/shmirzaev/milana-erp-backend@sha256:f7467a79c4b513cc62d11b5106161f21430cf1e1e4bde739949e5bbcecbfa655'


def remote(source, command='docker exec -i milana-backend-blue python -'):
    response = subprocess.run(SSH + ['admilana@172.16.10.4', command],
                              input=source.encode(), capture_output=True)
    if response.returncode:
        (OUT / 'error.txt').write_bytes(response.stderr)
        raise RuntimeError('Remote command failed; inspect outputs/bst-assignable-20261104/error.txt')
    return json.loads(response.stdout)


def release_gate():
    for host in ('172.16.10.4', '172.16.10.5'):
        data = subprocess.check_output(SSH + ['admilana@' + host,
            'readlink -f /opt/milana-erp/current; sha256sum /opt/milana-erp/current/SOURCE_MANIFEST.sha256'])
        lines = data.decode().splitlines()
        assert lines[0] == '/opt/milana-erp/releases/' + RELEASE
        assert lines[1].split()[0] == MANIFEST


def backup_gate(backup):
    code = '''import hashlib,json,subprocess
expected=EXPECTED
name=expected['path'].rsplit('/',1)[1]
cmd=['docker','run','--rm','--user','0','--network','none','--read-only','-v','/opt/milana-erp/shared/backups:/backup:ro']
listing=subprocess.check_output(cmd+['postgres:16-alpine','pg_restore','--list','/backup/'+name])
meta=json.loads(subprocess.check_output(cmd+['--entrypoint','python',IMAGE,'-c','import pathlib,json,hashlib;p=pathlib.Path('+repr('/backup/'+name)+');print(json.dumps(dict(bytes=p.stat().st_size,mode=oct(p.stat().st_mode & 0o777),sha256=hashlib.sha256(p.read_bytes()).hexdigest())))']))
assert all(meta[k]==expected[k] for k in ('bytes','mode','sha256'))
assert hashlib.sha256(listing).hexdigest()==expected['restore_list_sha256']
print(json.dumps({'verified':True}))
'''.replace('EXPECTED', repr(backup)).replace('IMAGE', repr(IMAGE))
    assert remote(code, 'python3 -')['verified']


if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    action = sys.argv[1]
    assert action in ('inspect', 'backup', 'rehearse', 'apply', 'verify')
    release_gate()
    if action == 'backup':
        source = (ROOT / 'ops/backup_fabric_reconciliation.py').read_text()
        source = source.replace('milana_erp_pre_fabric_reconcile_', 'milana_erp_pre_bst_assignable_')
        source = source.replace('ghcr.io/shmirzaev/milana-erp-backend:20261005_070406', IMAGE)
        result = remote(source, 'python3 -')
    else:
        source = (ROOT / 'ops/close_bst_assignable_20261104.py').read_text(encoding='utf-8')
        source_hash = hashlib.sha256(source.encode()).hexdigest()
        expected = json.loads((OUT / ('apply.json' if action == 'verify' else 'inspect.json')).read_text()) if action != 'inspect' else None
        backup = json.loads((OUT / 'backup.json').read_text()) if action in ('rehearse', 'apply') else None
        if backup:
            backup_gate(backup)
        if action == 'apply':
            rehearsal = json.loads((OUT / 'rehearse.json').read_text())
            assert rehearsal['rollback_verified'] and rehearsal['source_sha256'] == source_hash
            assert rehearsal['before'] == expected['fingerprint']
            for path in ('ops/close_bst_assignable_20261104.py', 'ops/run_bst_assignable_20261104.py'):
                committed = subprocess.check_output(['git', 'show', 'HEAD:' + path], cwd=ROOT).decode()
                assert committed.replace('\r\n', '\n') == (ROOT / path).read_text(encoding='utf-8')
        code = source + '\nprint(json.dumps(operation(' + ','.join(map(repr,
            [action, expected, backup])) + '),default=str))\n'
        result = remote(code)
        result['source_sha256'] = source_hash
    (OUT / (action + '.json')).write_text(json.dumps(result, indent=2, default=str), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k not in ('snapshot', 'queues')}, default=str))
