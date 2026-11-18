"""Explicit SSH launcher; private business evidence stays in ignored outputs."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/po0640-swap'
SOURCE=ROOT/'ops/swap_po0640_po0641.py'
SSH=['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10','-i',str(Path.home()/'.ssh/milana_erp_deploy_ed25519')]
RELEASE='20261116_130518'
MANIFEST='bc2e0d4bdbb38f6c06b9f3d5c75f3fdaa1fb5087240ca8f7b49d01318908ce40'


def remote(source,command='docker exec -i milana-backend-green python -'):
    result=subprocess.run(SSH+['admilana@172.16.10.4',command],input=source.encode(),capture_output=True)
    if result.returncode:
        (OUT/'error.txt').write_bytes(result.stderr+result.stdout)
        raise RuntimeError('Remote operation failed; inspect private outputs/po0640-swap/error.txt')
    return json.loads(result.stdout)


def release_gate():
    for host in ('172.16.10.4','172.16.10.5'):
        result=subprocess.check_output(SSH+['admilana@'+host,'readlink -f /opt/milana-erp/current; sha256sum /opt/milana-erp/current/SOURCE_MANIFEST.sha256']).decode().splitlines()
        assert result[0]=='/opt/milana-erp/releases/'+RELEASE and result[1].split()[0]==MANIFEST


def backup():
    # Credentials are transferred only between local processes on the backend VM.
    return remote('''import json,subprocess,os,hashlib
from datetime import datetime,timezone
def run(args,**kw):
 r=subprocess.run(args,capture_output=True,**kw)
 if r.returncode:raise RuntimeError('Backup failed, exit='+str(r.returncode))
 return r.stdout
probe='import json; from sqlalchemy.engine import make_url; from app.core.config import settings; u=make_url(settings.DATABASE_URL);print(json.dumps(dict(PGHOST=u.host,PGPORT=str(u.port or 5432),PGUSER=u.username,PGPASSWORD=u.password,PGDATABASE=u.database)))'
cfg=json.loads(run(['docker','exec','milana-backend-green','python','-c',probe]))
name='milana_erp_pre_po0640_swap_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')+'.dump'
directory='/opt/milana-erp/shared/backups'
cmd=['docker','run','--rm','--network','host','-v',directory+':/backup']
for k in cfg:cmd+=['-e',k]
run(cmd+['--entrypoint','sh','postgres:16-alpine','-c','umask 077; set -C; exec pg_dump --format=custom --no-owner --no-acl > /backup/'+name],env=dict(os.environ,**cfg))
listing=run(['docker','run','--rm','--network','none','-v',directory+':/backup:ro','postgres:16-alpine','pg_restore','--list','/backup/'+name])
count=sum(bool(l.strip()) and not l.startswith(b';') for l in listing.splitlines())
meta=json.loads(run(['docker','run','--rm','--user','0','--network','none','--read-only','-v',directory+':/backup:ro','--entrypoint','python','ghcr.io/shmirzaev/milana-erp-backend:20261116_130518','-c','import pathlib,json,hashlib;p=pathlib.Path("/backup/'+name+'");print(json.dumps(dict(bytes=p.stat().st_size,mode=oct(p.stat().st_mode&0o777),sha256=hashlib.sha256(p.read_bytes()).hexdigest())))']))
assert meta['bytes']>0 and meta['mode']=='0o600' and count>100
print(json.dumps(dict(path=directory+'/'+name,restore_objects=count,restore_list_sha256=hashlib.sha256(listing).hexdigest(),**meta)))
''','python3 -')


def verify_backup(expected):
    source='''import json,subprocess,hashlib
expected=EXPECTED
name=expected['path'].rsplit('/',1)[1]
base=['docker','run','--rm','--user','0','--network','none','--read-only','-v','/opt/milana-erp/shared/backups:/backup:ro']
listing=subprocess.check_output(base+['postgres:16-alpine','pg_restore','--list','/backup/'+name])
meta=json.loads(subprocess.check_output(base+['--entrypoint','python','ghcr.io/shmirzaev/milana-erp-backend:20261116_130518','-c','import json,pathlib,hashlib;p=pathlib.Path('+repr('/backup/'+name)+');print(json.dumps(dict(bytes=p.stat().st_size,mode=oct(p.stat().st_mode&0o777),sha256=hashlib.sha256(p.read_bytes()).hexdigest())))']))
assert all(meta[k]==expected[k] for k in ('bytes','mode','sha256'))
assert hashlib.sha256(listing).hexdigest()==expected['restore_list_sha256']
print(json.dumps({'backup_reverified':True}))
'''.replace('EXPECTED',repr(expected))
    assert remote(source,'python3 -')['backup_reverified']


if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True)
    mode=sys.argv[1];release_gate()
    source=SOURCE.read_text(encoding='utf-8');source_hash=hashlib.sha256(source.encode()).hexdigest()
    if mode=='backup':result=backup()
    else:
        expected=json.loads((OUT/'inspect.json').read_text()) if mode in ('rehearse','apply') else None
        saved_backup=json.loads((OUT/'backup.json').read_text()) if mode in ('rehearse','apply') else None
        if saved_backup:verify_backup(saved_backup)
        if mode=='apply':
            rehearsal=json.loads((OUT/'rehearse.json').read_text())
            assert rehearsal['rollback_verified'] and rehearsal['before']==expected['fingerprint'] and rehearsal['script_sha256']==source_hash
            for path in ('ops/swap_po0640_po0641.py','ops/run_po0640_swap.py'):
                committed=subprocess.check_output(['git','show','HEAD:'+path],cwd=ROOT).decode()
                assert committed.replace('\r\n','\n')==(ROOT/path).read_text(encoding='utf-8').replace('\r\n','\n')
        code=source+'\nprint(json.dumps(operation('+','.join(map(repr,[mode,expected,saved_backup,source_hash]))+'),default=str))\n'
        result=remote(code)
    (OUT/(mode+'.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('snapshot','preview','changes')}))
