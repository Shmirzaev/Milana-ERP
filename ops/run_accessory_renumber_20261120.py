"""Exact-source SSH runner for the owner-authorized batch label correction."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/accessories-batch-numbers-20261120"
RELEASE = "20261120_040300"
MANIFEST = "7e888254a16e7c8ff277d99c4eff29a8a0f40c149aa3229987074232badcabb7"
CONTAINER = "milana-backend-blue"
QA = "milana-accessory-renumber-20261120-qa"
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-i", str(Path.home() / ".ssh/milana_erp_deploy_ed25519")]
PATHS = ("ops/renumber_accessories_20261120.py", "ops/run_accessory_renumber_20261120.py",
         "backend/app/schemas/inventory/batch_identity_persistence.py")


def remote(code, command="python3 -", host="172.16.10.4"):
    result = subprocess.run(SSH + ["admilana@" + host, command], input=code.encode(), capture_output=True)
    if result.returncode:
        (OUT / "last-error.txt").write_bytes(result.stderr + result.stdout)
        raise RuntimeError("Remote operation refused/failed; inspect private last-error.txt")
    return json.loads(result.stdout)


def release_gate():
    code = f'''import pathlib,subprocess,hashlib,json
p=pathlib.Path('/opt/milana-erp/current').resolve()
assert p.name=={RELEASE!r},'Active source release changed'
assert hashlib.sha256((p/'SOURCE_MANIFEST.sha256').read_bytes()).hexdigest()=={MANIFEST!r}
assert subprocess.run(['sha256sum','-c','--quiet','SOURCE_MANIFEST.sha256'],cwd=p,capture_output=True).returncode==0
print(json.dumps(dict(release=p.name,verified=True)))
'''
    return {host: remote(code, host=host) for host in ("172.16.10.4", "172.16.10.5")}


def build_plan():
    code = '''import json
from sqlalchemy import create_engine,text
from app.core.config import settings
with create_engine(settings.DATABASE_URL).connect() as c:
 c.execute(text('SET TRANSACTION READ ONLY'))
 rows=[dict(r) for r in c.execute(text("SELECT b.id,b.batch_no AS old,b.item_id,b.old_code AS source_key,i.sku FROM stock_batches b JOIN items i ON i.id=b.item_id WHERE b.batch_no LIKE 'MIL-OPEN26-%' AND b.warehouse_id=2 AND i.category IN ('accessory','packaging') ORDER BY b.id")).mappings()]
 occupied={str(r[0]) for r in c.execute(text("SELECT batch_no FROM stock_batches UNION SELECT internal_batch_no FROM stock_batches WHERE internal_batch_no IS NOT NULL"))}
 assert len(rows)==759 and {r['id'] for r in rows}==set(range(2189,2948))
 available=(str(n) for n in range(1000,10000) if str(n) not in occupied)
 for row in rows:row['new']=next(available)
 print(json.dumps(rows))
'''
    plan = remote(code, f"docker exec -i {CONTAINER} python -")
    source = ROOT.parent / "accessories-opening-20261118/outputs/accessories-opening-20261118/manifest.json"
    raw = source.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "5d0d727e6b3032c0d24aa7550e5a3778bc1b7a67e8f5809690c387a86189a30d"
    original = {r["batch_no"]: r for r in json.loads(raw)["rows"] if r["status"] == "ready"}
    for row in plan:
        match = original[row["old"]]
        assert (row["sku"], row["source_key"]) == (match["sku"], match["source_key"])
    return plan


def backup():
    code = '''import subprocess,json,os,hashlib
from datetime import datetime,timezone
def run(args,**kw):
 r=subprocess.run(args,capture_output=True,**kw)
 if r.returncode:raise RuntimeError('Backup command failed')
 return r.stdout
probe='import json;from sqlalchemy.engine import make_url;from app.core.config import settings;u=make_url(settings.DATABASE_URL);print(json.dumps(dict(PGHOST=u.host,PGPORT=str(u.port or 5432),PGUSER=u.username,PGPASSWORD=u.password,PGDATABASE=u.database)))'
cfg=json.loads(run(['docker','exec',container,'python','-c',probe]))
name='milana_erp_pre_accessory_renumber_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')+'.dump'
directory='/opt/milana-erp/shared/backups'
cmd=['docker','run','--rm','--network','host','-v',directory+':/backup']
for key in cfg:cmd+=['-e',key]
run(cmd+['--entrypoint','sh','postgres:16-alpine','-c','umask 077; set -C; exec pg_dump --format=custom --no-owner --no-acl > /backup/'+name],env=dict(os.environ,**cfg))
listing=run(['docker','run','--rm','--network','none','-v',directory+':/backup:ro','postgres:16-alpine','pg_restore','--list','/backup/'+name])
image=run(['docker','inspect','-f','{{.Image}}',container]).decode().strip()
meta=json.loads(run(['docker','run','--rm','--user','0','--network','none','--read-only','-v',directory+':/backup:ro','--entrypoint','python',image,'-c','import pathlib,json,hashlib;p=pathlib.Path("/backup/'+name+'");print(json.dumps(dict(bytes=p.stat().st_size,mode=oct(p.stat().st_mode&0o777),sha256=hashlib.sha256(p.read_bytes()).hexdigest())))']))
objects=sum(bool(x.strip()) and not x.startswith(b';') for x in listing.splitlines())
assert meta['bytes']>0 and meta['mode']=='0o600' and objects>100
print(json.dumps(dict(path=directory+'/'+name,restore_objects=objects,restore_list_sha256=hashlib.sha256(listing).hexdigest(),**meta)))
'''
    return remote("container=" + repr(CONTAINER) + "\n" + code)


def verify_backup(saved):
    code = '''import subprocess,json,pathlib,hashlib,re
from datetime import datetime,timezone
name=pathlib.PurePosixPath(saved['path']).name
assert re.fullmatch(r'milana_erp_pre_accessory_renumber_[0-9]{8}_[0-9]{6}[.]dump',name)
captured=datetime.strptime(name.removeprefix('milana_erp_pre_accessory_renumber_').removesuffix('.dump'),'%Y%m%d_%H%M%S').replace(tzinfo=timezone.utc)
assert 0<=(datetime.now(timezone.utc)-captured).total_seconds()<=1800,'Backup freshness expired'
base=['docker','run','--rm','--network','none','--read-only','-v','/opt/milana-erp/shared/backups:/backup:ro']
listing=subprocess.check_output(base+['postgres:16-alpine','pg_restore','--list','/backup/'+name])
image=subprocess.check_output(['docker','inspect','-f','{{.Image}}',container]).decode().strip()
meta=json.loads(subprocess.check_output(base+['--user','0','--entrypoint','python',image,'-c','import json,pathlib,hashlib;p=pathlib.Path('+repr('/backup/'+name)+');print(json.dumps(dict(bytes=p.stat().st_size,mode=oct(p.stat().st_mode&0o777),sha256=hashlib.sha256(p.read_bytes()).hexdigest())))']))
assert all(meta[k]==saved[k] for k in ('bytes','mode','sha256'))
assert hashlib.sha256(listing).hexdigest()==saved['restore_list_sha256']
print(json.dumps(dict(backup_reverified=True)))
'''
    return remote("saved=" + repr(saved) + "\ncontainer=" + repr(CONTAINER) + "\n" + code)


def program(plan, sha):
    helper = (ROOT / PATHS[2]).read_text(encoding="utf-8")
    module = "app.schemas.inventory.batch_identity_persistence"
    bootstrap = "import sys,types\nm=types.ModuleType(" + repr(module) + ");sys.modules[m.__name__]=m\nexec(" + repr(helper) + ",m.__dict__)\n"
    source = (ROOT / PATHS[0]).read_text(encoding="utf-8")
    return "from __future__ import annotations\n" + bootstrap + source.replace("from __future__ import annotations\n", "") + "\nplan=" + repr(plan) + "\nplan_sha=" + repr(sha) + "\n"


def qa(plan, sha, hashes):
    saved = json.loads((OUT / "backup.json").read_text())
    verify_backup(saved)
    tests = '''
args=dict(plan_sha=plan_sha)
results={'inspect':operation(plan,mode='inspect',**args)}
try:operation(plan,mode='apply',plan_sha='wrong')
except ValueError:pass
else:raise AssertionError('Wrong hash accepted')
changed=json.loads(json.dumps(plan));changed[0]['new']='9999'
try:operation(changed,mode='apply',**args)
except ValueError:pass
else:raise AssertionError('Changed plan accepted')
results['refusals_passed']=True
for key,value in (('id',0),('new',plan[1]['new']),('sku','WRONG'),('source_key','WRONG')):
 changed=json.loads(json.dumps(plan));changed[0][key]=value
 try:operation(changed,mode='apply',plan_sha=digest(changed))
 except ValueError:pass
 else:raise AssertionError('Tampered identity/duplicate target accepted: '+key)
 assert operation(plan,mode='inspect',**args)['ready']
engine=create_engine(os.environ['ACCESSORY_RENUMBER_QA_DATABASE_URL'],poolclass=NullPool)
try:
 for column in ('batch_no','internal_batch_no'):
  with engine.begin() as conn:
   probe=conn.execute(text('SELECT id,'+column+' FROM stock_batches WHERE id NOT BETWEEN 2189 AND 2947 ORDER BY id LIMIT 1')).first()
   conn.execute(text('UPDATE stock_batches SET '+column+'=:label WHERE id=:id'),dict(label=plan[0]['new'],id=probe[0]))
  try:
   try:operation(plan,mode='apply',**args)
   except ValueError as e:assert str(e)=='Target number already exists'
   else:raise AssertionError('Existing label collision accepted: '+column)
  finally:
   with engine.begin() as conn:conn.execute(text('UPDATE stock_batches SET '+column+'=:label WHERE id=:id'),dict(label=probe[1],id=probe[0]))
  assert operation(plan,mode='inspect',**args)['ready']
finally:engine.dispose()
results['identity_and_collision_refusals_passed']=True
try:operation(plan,mode='apply',fail_after=3,**args)
except ValueError as e:assert str(e)=='Deliberate isolated correction fault'
else:raise AssertionError('Fault not raised')
assert operation(plan,mode='inspect',**args)['ready']
results['fault_rollback_verified']=True
results['rehearse']=operation(plan,mode='rehearse',**args)
results['apply']=operation(plan,mode='apply',**args)
results['verify']=operation(plan,mode='verify',**args)
results['retry']=operation(plan,mode='apply',**args)
assert results['retry']['already_applied']
assert results['verify']['preserved_facts']==results['inspect']['preserved_facts']
print(json.dumps(results))
'''
    payload = program(plan, sha) + tests
    outer = '''import subprocess,json,secrets,os,time
def run(args,**kw):
 r=subprocess.run(args,capture_output=True,**kw)
 if r.returncode:raise RuntimeError('QA failed: '+r.stderr.decode(errors='replace')[-2500:])
 return r.stdout
assert subprocess.run(['docker','inspect',qa],capture_output=True).returncode!=0,'QA name occupied'
image=run(['docker','inspect','-f','{{.Image}}',container]).decode().strip()
password=secrets.token_urlsafe(32)
env=dict(os.environ,POSTGRES_PASSWORD=password)
run(['docker','run','-d','--name',qa,'--network','none','--label','milana.operation=MILANA_ACCESSORIES_BATCH_NUMBERS_20261120','-e','POSTGRES_PASSWORD','-e','POSTGRES_DB=milana_accessories_renumber_20261120','-v','/opt/milana-erp/shared/backups:/backup:ro','postgres:16-alpine'],env=env)
try:
 for n in range(60):
  if subprocess.run(['docker','exec',qa,'pg_isready','-h','127.0.0.1','-U','postgres','-d','milana_accessories_renumber_20261120'],capture_output=True).returncode==0:break
  time.sleep(1)
 else:raise RuntimeError('Private database not ready')
 run(['docker','exec','--user','0',qa,'pg_restore','-U','postgres','-d','milana_accessories_renumber_20261120','--no-owner','--no-acl','--exit-on-error','/backup/'+saved['path'].rsplit('/',1)[1]])
 env['ACCESSORY_RENUMBER_QA_DATABASE_URL']='postgresql+psycopg2://postgres:'+password+'@127.0.0.1:5432/milana_accessories_renumber_20261120'
 env['DATABASE_URL']=env['ACCESSORY_RENUMBER_QA_DATABASE_URL']
 result=run(['docker','run','--rm','-i','--network','container:'+qa,'-e','ENV=test','-e','DATABASE_URL','-e','ACCESSORY_RENUMBER_QA_DATABASE_URL','--entrypoint','python',image,'-'],input=payload.encode(),env=env)
 print(result.decode())
finally:
 assert run(['docker','inspect','-f','{{index .Config.Labels "milana.operation"}}',qa]).decode().strip()=='MILANA_ACCESSORIES_BATCH_NUMBERS_20261120'
 run(['docker','rm','-f',qa])
'''
    result = remote("qa=" + repr(QA) + "\ncontainer=" + repr(CONTAINER) + "\nsaved=" + repr(saved) + "\npayload=" + repr(payload) + "\n" + outer)
    return {**result, "plan_sha256": sha, "source_hashes": hashes,
            "backup_path": saved["path"], "backup_sha256": saved["sha256"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("plan", "backup", "qa", "inspect", "apply", "verify"))
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    release_gate()
    if args.mode == "plan":
        check_path = OUT / "plan.json"
        if check_path.exists():
            raise ValueError("Plan is already frozen; do not overwrite")
        result = build_plan()
    elif args.mode == "backup":
        result = backup()
    else:
        plan = json.loads((OUT / "plan.json").read_text(encoding="utf-8"))
        sha = hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":")).encode()).hexdigest()
        hashes = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in PATHS}
        if args.mode == "qa":
            result = qa(plan, sha, hashes)
        else:
            if args.mode == "apply":
                saved = json.loads((OUT / "backup.json").read_text())
                verify_backup(saved)
                evidence = json.loads((OUT / "qa.json").read_text())
                assert evidence["refusals_passed"] and evidence["identity_and_collision_refusals_passed"] and evidence["fault_rollback_verified"] and evidence["rehearse"]["rollback_verified"] and evidence["retry"]["already_applied"]
                assert evidence["plan_sha256"] == sha and evidence["source_hashes"] == hashes
                assert (evidence["backup_path"], evidence["backup_sha256"]) == (saved["path"], saved["sha256"])
                for path in PATHS:
                    committed = subprocess.check_output(["git", "show", "HEAD:" + path], cwd=ROOT).decode()
                    assert committed.replace("\r\n", "\n") == (ROOT / path).read_text(encoding="utf-8").replace("\r\n", "\n"), "Uncommitted operation source"
            result = remote(program(plan, sha) + "\nprint(json.dumps(operation(plan,mode=" + repr(args.mode) + ",plan_sha=plan_sha)))\n", f"docker exec -i {CONTAINER} python -")
    (OUT / (args.mode + ".json")).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"batches": len(result)} if isinstance(result, list) else {k: v for k, v in result.items() if k not in ("apply", "verify", "retry", "rehearse")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
