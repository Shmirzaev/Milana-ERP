"""Run this data-only import with pinned release and database guards."""
import hashlib
import json
import shlex
import sys
from pathlib import Path

import paramiko
import win32cred

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs' / 'sticker-held-20260922'
REMOTE = '/tmp/sticker-held-20260922'
CONTAINER = 'milana-backend-blue'
GUARD = '''set -eu
test "$(readlink -f /opt/milana-erp/current)" = /opt/milana-erp/releases/20260922_043845
test "$(sha256sum /opt/milana-erp/current/SOURCE_MANIFEST.sha256 | cut -d' ' -f1)" = 3cdfffe32807a4815d39ada8afc5f43ec5807aa5da6c2da168de3aa776fa4b7d
'''


def main():
    phase = sys.argv[1]
    cred = win32cred.CredRead('MilanaERP/production-linux-sudo', win32cred.CRED_TYPE_GENERIC)
    blob = cred['CredentialBlob']
    password = blob.decode('utf-16-le' if b'\x00' in blob else 'utf-8')
    client = paramiko.SSHClient()
    client.load_host_keys(str(Path.home() / '.ssh' / 'known_hosts'))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    host = '172.16.10.5' if phase == 'frontend-status' else '172.16.10.4'
    client.connect(host, username=cred.get('UserName') or 'admilana',
                   key_filename=str(Path.home() / '.ssh' / 'milana_erp_deploy_ed25519'),
                   look_for_keys=False, allow_agent=False, timeout=20)
    def upload(local, remote):
        with client.open_sftp() as sftp:
            sftp.put(str(local), remote)
    try:
        if phase in ('status', 'frontend-status'):
            command = 'cat /opt/milana-erp/runtime/slots.json'
        elif phase == 'classify':
            upload(OUT / 'extracted.json', REMOTE + '-candidates.json')
            upload(ROOT / 'ops' / 'classify_completed_pack_candidates.py', REMOTE + '-classifier.py')
            command = f'''docker cp {REMOTE}-candidates.json {CONTAINER}:{REMOTE}-candidates.json
docker cp {REMOTE}-classifier.py {CONTAINER}:{REMOTE}-classifier.py
docker exec -e PYTHONPATH=/app:/app/backend {CONTAINER} python {REMOTE}-classifier.py {REMOTE}-candidates.json --expected-database-host 172.16.10.3 --expected-database-name erp'''
        elif phase == 'backup':
            upload(ROOT / 'ops' / 'backup_sticker_20260922.py', REMOTE + '-backup.py')
            command = f'python3 {REMOTE}-backup.py 20260922_110000'
        elif phase == 'upload':
            bundle = OUT / 'bundle.zip'
            upload(bundle, REMOTE + '-bundle.zip')
            sha = hashlib.sha256(bundle.read_bytes()).hexdigest()
            command = f'''test "$(sha256sum {REMOTE}-bundle.zip | cut -d' ' -f1)" = {sha}
python3 -m zipfile -e {REMOTE}-bundle.zip {REMOTE}
docker cp {REMOTE} {CONTAINER}:/tmp/'''
        elif phase in ('dry-run', 'apply', 'verify'):
            manifest = OUT / 'manifest.json'
            sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
            count = len(json.loads(manifest.read_text(encoding='utf-8'))['rows'])
            command = f'docker exec -e PYTHONPATH=/app:/app/backend {CONTAINER} python {REMOTE}/import_sticker_held_20260922.py {REMOTE}/manifest.json --photo-root {REMOTE}/photos --expected-manifest-sha256 {sha} --expected-database-host 172.16.10.3 --expected-database-name erp --environment production --mode {phase}'
            if phase == 'apply':
                command += f' --confirm APPLY-{count}-COMPLETED-PACKS-TO-PRODUCTION'
        elif phase == 'inspect':
            upload(OUT / 'inspect.py', REMOTE + '-inspect.py')
            command = f'docker cp {REMOTE}-inspect.py {CONTAINER}:{REMOTE}-inspect.py\ndocker exec -e PYTHONPATH=/app:/app/backend {CONTAINER} python {REMOTE}-inspect.py'
        else:
            raise ValueError(phase)
        stdin, stdout, stderr = client.exec_command('sudo -S -p \'\' bash -lc ' + shlex.quote(GUARD + command), timeout=600)
        stdin.write(password + '\n')
        stdin.flush()
        output = stdout.read().decode('utf-8')
        error = stderr.read().decode('utf-8')
        code = stdout.channel.recv_exit_status()
        (OUT / (phase + '.json')).write_text(output, encoding='utf-8')
        if code:
            print(error)
            print(output)
            raise SystemExit(code)
        data = json.loads(output) if output.strip() else {}
        print(json.dumps({k:v for k,v in data.items() if k != 'rows' or not isinstance(v,list)}, ensure_ascii=False))
    finally:
        client.close()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
