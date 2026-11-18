"""SSH transport, backup, isolated restored-copy QA and exact-source apply gate."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/accessories-opening-20261118"
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-i", str(Path.home() / ".ssh/milana_erp_deploy_ed25519")]
RELEASE = "20261116_130518"
MANIFEST = "bc2e0d4bdbb38f6c06b9f3d5c75f3fdaa1fb5087240ca8f7b49d01318908ce40"
QA = "milana-accessories-opening-20261118-qa"


def remote(source, command="python3 -", host="172.16.10.4"):
    result = subprocess.run(SSH + ["admilana@" + host, command], input=source.encode(), capture_output=True)
    if result.returncode:
        (OUT / "last-error.txt").write_bytes(result.stderr + result.stdout)
        raise RuntimeError("Remote operation failed; inspect private outputs/accessories-opening-20261118/last-error.txt")
    return json.loads(result.stdout)


def release_gate():
    code = f'''import subprocess,json,pathlib,hashlib
p=pathlib.Path('/opt/milana-erp/current').resolve()
assert str(p)=='/opt/milana-erp/releases/{RELEASE}'
assert hashlib.sha256((p/'SOURCE_MANIFEST.sha256').read_bytes()).hexdigest()=='{MANIFEST}'
r=subprocess.run(['sha256sum','-c','--quiet','SOURCE_MANIFEST.sha256'],cwd=p,capture_output=True)
assert r.returncode==0,'Source manifest check failed'
print(json.dumps({{'release':p.name,'manifest_verified':True}}))
'''
    return {host: remote(code, host=host) for host in ("172.16.10.4", "172.16.10.5")}


def backup():
    return remote('''import json,subprocess,os,hashlib
from datetime import datetime,timezone
def run(args,**kw):
 r=subprocess.run(args,capture_output=True,**kw)
 if r.returncode:raise RuntimeError('Backup failed, exit='+str(r.returncode))
 return r.stdout
probe='import json; from sqlalchemy.engine import make_url; from app.core.config import settings; u=make_url(settings.DATABASE_URL);print(json.dumps(dict(PGHOST=u.host,PGPORT=str(u.port or 5432),PGUSER=u.username,PGPASSWORD=u.password,PGDATABASE=u.database)))'
cfg=json.loads(run(['docker','exec','milana-backend-green','python','-c',probe]))
name='milana_erp_pre_accessories_opening_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')+'.dump'
directory='/opt/milana-erp/shared/backups'
cmd=['docker','run','--rm','--network','host','-v',directory+':/backup']
for k in cfg:cmd+=['-e',k]
run(cmd+['--entrypoint','sh','postgres:16-alpine','-c','umask 077; set -C; exec pg_dump --format=custom --no-owner --no-acl > /backup/'+name],env=dict(os.environ,**cfg))
listing=run(['docker','run','--rm','--network','none','-v',directory+':/backup:ro','postgres:16-alpine','pg_restore','--list','/backup/'+name])
objects=sum(bool(x.strip()) and not x.startswith(b';') for x in listing.splitlines())
image=run(['docker','inspect','-f','{{.Image}}','milana-backend-green']).decode().strip()
meta=json.loads(run(['docker','run','--rm','--user','0','--network','none','--read-only','-v',directory+':/backup:ro','--entrypoint','python',image,'-c','import pathlib,json,hashlib;p=pathlib.Path("/backup/'+name+'");print(json.dumps(dict(bytes=p.stat().st_size,mode=oct(p.stat().st_mode&0o777),sha256=hashlib.sha256(p.read_bytes()).hexdigest())))']))
assert meta['bytes']>0 and meta['mode']=='0o600' and objects>100
print(json.dumps(dict(path=directory+'/'+name,restore_objects=objects,restore_list_sha256=hashlib.sha256(listing).hexdigest(),**meta)))
''')


def verify_backup(saved):
    return remote('''import json,subprocess,pathlib,hashlib,re
from datetime import datetime,timezone
saved=SAVED
name=pathlib.PurePosixPath(saved['path']).name
assert re.fullmatch(r'milana_erp_pre_accessories_opening_[0-9]{8}_[0-9]{6}[.]dump',name)
captured=datetime.strptime(name.removeprefix('milana_erp_pre_accessories_opening_').removesuffix('.dump'),'%Y%m%d_%H%M%S').replace(tzinfo=timezone.utc)
age=(datetime.now(timezone.utc)-captured).total_seconds()
assert 0<=age<=1800,'Backup is older than the 30-minute apply gate'
base=['docker','run','--rm','--network','none','--read-only','-v','/opt/milana-erp/shared/backups:/backup:ro']
listing=subprocess.check_output(base+['postgres:16-alpine','pg_restore','--list','/backup/'+name])
image=subprocess.check_output(['docker','inspect','-f','{{.Image}}','milana-backend-green']).decode().strip()
meta=json.loads(subprocess.check_output(base+['--user','0','--entrypoint','python',image,'-c','import json,pathlib,hashlib;p=pathlib.Path('+repr('/backup/'+name)+');print(json.dumps(dict(bytes=p.stat().st_size,mode=oct(p.stat().st_mode&0o777),sha256=hashlib.sha256(p.read_bytes()).hexdigest())))']))
assert all(meta[k]==saved[k] for k in ('bytes','mode','sha256'))
assert hashlib.sha256(listing).hexdigest()==saved['restore_list_sha256']
print(json.dumps({'backup_reverified':True}))
'''.replace("SAVED", repr(saved)))


def qa(manifest, source, sha, source_hashes):
    saved = json.loads((OUT / "backup.json").read_text())
    verify_backup(saved)
    tests = '''
results={}
args=dict(valuation_approved=True,manifest_sha256=manifest_sha,expected_manifest_sha256=manifest_sha)
results['inspect']=operation(manifest,mode='inspect',**args)
for denied in (dict(valuation_approved=False),dict(manifest_sha256='wrong')):
 attempt=dict(args);attempt.update(denied)
 try:operation(manifest,mode='apply',**attempt)
 except ValueError:pass
 else:raise AssertionError('Required refusal did not occur')
results['refusals_passed']=True
changed=json.loads(json.dumps(manifest))
for row in changed['rows']:
 if row['status']=='ready':
  row['quantity']=str(Decimal(row['quantity'])+1)
  break
try:operation(changed,mode='apply',**args)
except ValueError:pass
else:raise AssertionError('Altered manifest was accepted')
results['altered_manifest_refused']=True
try:operation(manifest,mode='apply',fail_after=3,**args)
except ValueError as e:assert str(e)=='Deliberate isolated rollback fault'
else:raise AssertionError('Fault not raised')
assert operation(manifest,mode='inspect',**args)['ready']
results['fault_rollback_verified']=True
results['rehearse']=operation(manifest,mode='rehearse',**args)
results['apply']=operation(manifest,mode='apply',**args)
results['verify']=operation(manifest,mode='verify',**args)
results['retry']=operation(manifest,mode='apply',**args)
assert results['retry']['already_applied']
assert results['inspect']['existing_accessories_fingerprint']==results['verify']['existing_accessories_fingerprint']
results['source_sha256']=source_sha
results['manifest_sha256']=manifest_sha
results['source_hashes']=source_hashes
results['backup_path']=qa_backup['path']
results['backup_sha256']=qa_backup['sha256']
print(json.dumps(results,default=str))
'''
    program = source + "\nmanifest=json.loads(" + repr(json.dumps(manifest, ensure_ascii=False)) + ")\nmanifest_sha=" + repr(sha) + "\nsource_sha=" + repr(hashlib.sha256(source.encode()).hexdigest()) + "\nsource_hashes=" + repr(source_hashes) + "\nqa_backup=" + repr(saved) + "\n" + tests
    outer = '''import subprocess,json,secrets,os,time
def run(args,**kw):
 r=subprocess.run(args,capture_output=True,**kw)
 if r.returncode:raise RuntimeError('Isolated QA command failed: '+r.stderr.decode(errors='replace')[-2500:])
 return r.stdout
assert subprocess.run(['docker','inspect',qa],capture_output=True).returncode!=0,'QA name already exists'
password=secrets.token_urlsafe(32)
env=dict(os.environ,POSTGRES_PASSWORD=password)
image=run(['docker','inspect','-f','{{.Image}}','milana-backend-green']).decode().strip()
run(['docker','run','-d','--name',qa,'--network','none','--label','milana.operation=MILANA_ACCESSORIES_OPENING_20261118','-e','POSTGRES_PASSWORD','-e','POSTGRES_DB=milana_accessories_20261118','-v','/opt/milana-erp/shared/backups:/backup:ro','postgres:16-alpine'],env=env)
try:
 for n in range(60):
  if subprocess.run(['docker','exec',qa,'pg_isready','-h','127.0.0.1','-U','postgres','-d','milana_accessories_20261118'],capture_output=True).returncode==0:break
  time.sleep(1)
 else:raise RuntimeError('Private PostgreSQL did not become ready')
 run(['docker','exec','--user','0',qa,'pg_restore','-U','postgres','-d','milana_accessories_20261118','--no-owner','--no-acl','--exit-on-error','/backup/'+backup_path.rsplit('/',1)[1]])
 env['ACCESSORY_QA_DATABASE_URL']='postgresql+psycopg2://postgres:'+password+'@127.0.0.1:5432/milana_accessories_20261118'
 env['DATABASE_URL']=env['ACCESSORY_QA_DATABASE_URL']
 result=run(['docker','run','--rm','-i','--network','container:'+qa,'-e','ENV=test','-e','DATABASE_URL','-e','ACCESSORY_QA_DATABASE_URL','--entrypoint','python',image,'-'],input=program.encode(),env=env)
 print(result.decode())
finally:
 label=run(['docker','inspect','-f','{{index .Config.Labels "milana.operation"}}',qa]).decode().strip()
 assert label=='MILANA_ACCESSORIES_OPENING_20261118'
 run(['docker','rm','-f',qa])
'''
    outer = "qa=" + repr(QA) + "\nprogram=" + repr(program) + "\nbackup_path=" + repr(saved["path"]) + "\n" + outer
    # Placeholder replacement is explicit; never interpolate source into a shell.
    return remote(outer)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["inspect", "backup", "qa", "apply", "verify"])
    parser.add_argument("--approve-provisional-zero", action="store_true")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    release_gate()
    source = (ROOT / "ops/import_accessories_opening_20261118.py").read_text(encoding="utf-8")
    manifest_bytes = (OUT / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    sha = hashlib.sha256(manifest_bytes).hexdigest()
    operation_names = ("build_accessories_opening_20261118.py", "import_accessories_opening_20261118.py", "run_accessories_opening_20261118.py", "test_accessories_opening_20261118.py")
    source_hashes = {name: hashlib.sha256((ROOT / "ops" / name).read_bytes()).hexdigest() for name in operation_names}
    if args.mode == "backup":
        result = backup()
    elif args.mode == "qa":
        result = qa(manifest, source, sha, source_hashes)
    else:
        if args.mode == "apply":
            if not args.approve_provisional_zero:
                raise ValueError("Owner-approved provisional valuation must be explicitly enabled")
            saved = json.loads((OUT / "backup.json").read_text())
            verify_backup(saved)
            evidence = json.loads((OUT / "qa.json").read_text())
            assert evidence["fault_rollback_verified"] and evidence["rehearse"]["rollback_verified"] and evidence["retry"]["already_applied"]
            assert evidence["source_sha256"] == hashlib.sha256(source.encode()).hexdigest()
            assert evidence["manifest_sha256"] == sha and evidence["source_hashes"] == source_hashes
            assert evidence["backup_path"] == saved["path"] and evidence["backup_sha256"] == saved["sha256"]
            for item in manifest["sources"]:
                original = Path.home() / "Downloads" / "Telegram Desktop" / item["file"]
                assert hashlib.sha256(original.read_bytes()).hexdigest() == item["sha256"], "Original workbook changed"
            for name in operation_names:
                path = "ops/" + name
                committed = subprocess.check_output(["git", "show", "HEAD:" + path], cwd=ROOT).decode()
                assert committed.replace("\r\n", "\n") == (ROOT / path).read_text(encoding="utf-8").replace("\r\n", "\n"), "Uncommitted operation source"
        code = source + "\nprint(json.dumps(operation(" + repr(manifest) + ",mode=" + repr(args.mode) + ",valuation_approved=" + repr(args.approve_provisional_zero) + ",manifest_sha256=" + repr(sha) + ",expected_manifest_sha256=" + repr(sha) + "),default=str))\n"
        result = remote(code, "docker exec -i milana-backend-green python -")
    (OUT / (args.mode + ".json")).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in {"item_ids", "batch_ids", "apply", "verify", "retry", "rehearse"}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
