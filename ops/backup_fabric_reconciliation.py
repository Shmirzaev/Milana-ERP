"""Run on backend VM; credentials stay in memory and are never printed."""
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone


def run(args, **kwargs):
    result = subprocess.run(args, capture_output=True, **kwargs)
    if result.returncode:
        raise RuntimeError('Backup command failed, exit=' + str(result.returncode))
    return result.stdout


probe = ('import json; from sqlalchemy.engine import make_url; from app.core.config import settings; '
         'u=make_url(settings.DATABASE_URL); print(json.dumps(dict(PGHOST=u.host,PGPORT=str(u.port or 5432),'
         'PGUSER=u.username,PGPASSWORD=u.password,PGDATABASE=u.database)))')
cfg = json.loads(run(['docker', 'exec', 'milana-backend-blue', 'python', '-c', probe]))
name = 'milana_erp_pre_fabric_reconcile_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S') + '.dump'
directory = '/opt/milana-erp/shared/backups'
env = dict(os.environ, **cfg)
command = ['docker', 'run', '--rm', '--network', 'host', '-v', directory+':/backup']
for key in cfg:
    command += ['-e', key]
command += ['--entrypoint', 'sh', 'postgres:16-alpine', '-c',
            'umask 077; set -C; exec pg_dump --format=custom --no-owner --no-acl > /backup/' + name]
run(command, env=env)
# Validate and hash inside the container, since the backup is deliberately root-only.
listing = run(['docker', 'run', '--rm', '--network', 'none', '-v', directory+':/backup:ro',
               'postgres:16-alpine', 'pg_restore', '--list', '/backup/'+name])
objects = sum(bool(line.strip()) and not line.startswith(b';') for line in listing.splitlines())
metadata = json.loads(run(['docker', 'run', '--rm', '--user', '0', '--network', 'none', '--read-only',
    '-v', directory+':/backup:ro', '--entrypoint', 'python',
    'ghcr.io/shmirzaev/milana-erp-backend:20261005_070406', '-c',
    'import json,hashlib,pathlib; p=pathlib.Path("/backup/'+name+'"); '
    'print(json.dumps(dict(bytes=p.stat().st_size,mode=oct(p.stat().st_mode & 0o777),sha256=hashlib.sha256(p.read_bytes()).hexdigest())))']))
assert metadata['bytes'] > 0 and objects > 100 and metadata['mode'] == '0o600'
print(json.dumps(dict(path=directory+'/'+name, restore_objects=objects,
                     restore_list_sha256=hashlib.sha256(listing).hexdigest(), **metadata)))
