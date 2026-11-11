"""Rehearse an exact published HR candidate/recovery image on owned PostgreSQL.

Uses the existing ownership-checked Docker harness, real image CMD and strict
security checks. No host ports, mounted source or factory endpoints are used.
"""
import argparse
import json
import re
import secrets

import test_rollback_image_schema_0150 as harness

HEAD = "0157_pricing_gate_live_merge"
SEED = """
from app.db.session import SessionLocal
from app.schemas import User,Model,Employee,AttendanceDevice,PriceCalculationRequest
from sqlalchemy import text
with SessionLocal.begin() as db:
 u=User(name='Owned recovery QA',email='owned@example.invalid',password_hash='unused',factory_code='MIL',extra_permissions=['*','admin.super'])
 m=Model(code='OWNED-RECOVERY',name='Owned recovery QA',status='approved',selling_price=7.30,selling_price_currency='USD',selling_price_source='catalog')
 e=Employee(full_name='Owned recovery QA',employee_no='999999991',factory_code='MIL',status='active')
 d=AttendanceDevice(factory_code='MIL',device_key='owned-recovery',name='Owned recovery QA',source_host='127.0.0.1',certificate_sha256='c'*64,read_only=True)
 db.add_all([u,m,e,d]);db.flush()
 db.add(PriceCalculationRequest(model_id=m.id,created_by_id=u.id,active_model_id=m.id,factory_code='MIL',workflow_state='approved',revision=7,approval_snapshot_json={'selling_price':7.30,'preserve':'approved'}))
 db.execute(text("INSERT INTO gate_live_devices (device_id,factory_code,enabled,writes_enabled,worker_token_hash,source_host,certificate_sha256,config_revision,configuration) VALUES (:device,'MIL',false,false,:hash,'127.0.0.1',:pin,1,'{}')"),{'device':d.id,'hash':'b'*64,'pin':'c'*64})
 db.execute(text("INSERT INTO gate_live_jobs (requested_by,factory_code,employee_id,device_id,action,state,request_key,request_hash,request,config_revision,dispatched,dispatch_count,attempt_count,result_history) VALUES (:actor,'MIL',:employee,:device,'observe','queued','owned-recovery',:hash,'{}',1,false,0,0,'[]')"),{'actor':u.id,'employee':e.id,'device':d.id,'hash':'a'*64})
"""
CHECK = r"""
import json,urllib.request,urllib.error
from sqlalchemy import text
from app.db.session import SessionLocal
from app.schemas import User,Employee
from app.core.security import create_access_token
def facts():
 with SessionLocal() as db:
  db.execute(text('SET TRANSACTION READ ONLY'))
  result={}
  for table in db.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")).scalars():
   assert table.replace('_','').isalnum()
   result[table]=list(db.execute(text('SELECT count(*), md5(COALESCE(string_agg(row_json, chr(10) ORDER BY row_json),\'\')) FROM (SELECT row_to_json(t)::text row_json FROM "'+table+'" t) s')).one())
  return result
with SessionLocal() as db:
 db.execute(text('SET TRANSACTION READ ONLY'))
 assert db.execute(text('SELECT version_num FROM alembic_version')).scalar_one()=='0157_pricing_gate_live_merge'
 token=create_access_token(db.query(User).filter_by(email='owned@example.invalid').one().id)
 employee=db.query(Employee).filter_by(employee_no='999999991').one().id
before=facts()
headers={'Authorization':'Bearer '+token}
for path in ['/api/sales-orders','/api/models','/api/price-calculation/requests']:
 with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:10000'+path,headers=headers),timeout=10) as response: assert response.status==200
url='http://127.0.0.1:10000/api/turnstile-live/employees/'+str(employee)
if LIVE_ROUTES:
 with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=10) as response:
  context=json.load(response);assert context['enabled'] is False and context['devices']==[]
else:
 try: urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=10);raise AssertionError('Recovery unexpectedly includes live routes')
 except urllib.error.HTTPError as error: assert error.code==404
assert facts()==before,'Read probes changed database rows'
print(json.dumps(before,sort_keys=True))
"""


def exercise(image, revision, live_routes=False):
    harness.require_digest(image)
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Use the full reviewed source revision")
    docker = harness.OwnedDocker()
    backend = None
    try:
        docker.run("pull", image, timeout=300)
        config = json.loads(docker.run("image", "inspect", image))[0]["Config"]
        assert config["Cmd"] == harness.DEFAULT_CMD and not config.get("Entrypoint")
        assert config["Labels"]["org.opencontainers.image.revision"] == revision
        docker.run("pull", "postgres:16", timeout=300)
        docker.network = docker.run("network", "create", "--internal", "--label",
            f"{harness.LABEL}={docker.owner}", "hr-recovery-" + docker.owner)
        password, jwt, signing = [secrets.token_hex(32) for _ in range(3)]
        docker.hidden = [password, jwt, signing]
        pg = docker.create("hr-recovery-pg-" + docker.owner, "postgres:16", alias="pg",
            env={"POSTGRES_USER":"rollback_qa", "POSTGRES_PASSWORD":password, "POSTGRES_DB":"rollback_qa"})
        harness.until(lambda: docker.run("exec", pg, "pg_isready", "-U", "rollback_qa", "-d", "rollback_qa"), description="owned PG16")
        env = dict(ENV="production", DEBUG="false", STARTUP_SCHEMA_SYNC="false", RUN_SEED_ON_STARTUP="false",
            SEED_DEMO_USERS="false", SEED_SAMPLE_DATA="false", IMPORT_LEGACY_MODELS="false",
            DATABASE_URL=f"postgresql+psycopg2://rollback_qa:{password}@pg:5432/rollback_qa",
            JWT_SECRET=jwt, FILE_SIGNING_SECRET=signing, SHARED_STORE_URL=harness.COUNTER_URL,
            SHARED_STORE_KEY_PREFIX="hr-recovery-"+docker.owner, CORS_ORIGINS="https://rollback-qa.invalid",
            FRONTEND_BASE_URL="https://rollback-qa.invalid", ERP_PUBLIC_BASE_URL="https://rollback-qa.invalid",
            TRUSTED_PROXY_CIDRS="127.0.0.1/32", FORWARDED_ALLOW_IPS="", WEB_CONCURRENCY="2",
            PORT="10000", RELEASE_ID="owned-hr-recovery", TURNSTILE_PROVISIONING_MODE="disabled")
        backend = docker.create("hr-recovery-api-"+docker.owner, image, alias="backend", env=env)
        marker = "startup: database migration head verified ("+HEAD+")"
        def ready(count):
            workers = json.loads(docker.run("exec", backend, "python", "-c", harness.WORKERS))
            if len(workers) != 2 or docker.run("logs", backend).count(marker) < count:
                return False
            docker.run("exec", backend, "python", "-c", harness.PROBES)
            return workers
        first = harness.until(lambda: ready(2), seconds=120, description="two strict 0157 workers")
        docker.run("exec", backend, "python", "-c", harness.STRICT)
        docker.run("exec", backend, "python", "-c", SEED)
        check = "LIVE_ROUTES="+repr(live_routes)+"\n"+CHECK
        baseline = docker.run("exec", backend, "python", "-c", check)
        for expected in (1, 2):
            harness.assert_counter(docker.run("exec", backend, "python", "-c", harness.STRICT+harness.COUNTER), expected)
        before = docker.run("logs", backend).count(marker)
        victim = first[0]
        docker.run("exec", backend, "python", "-c", f"import os,signal;os.kill({victim},signal.SIGKILL)")
        def recovered():
            workers = ready(before+1)
            return workers if workers and victim not in workers and len(set(workers)-set(first)) == 1 else False
        replacement = harness.until(recovered, seconds=90, description="replacement strict 0157 worker")
        harness.assert_counter(docker.run("exec", backend, "python", "-c", harness.STRICT+harness.COUNTER), 3)
        assert docker.run("exec", backend, "python", "-c", check) == baseline
        before = docker.run("logs", backend).count(marker)
        docker.run("restart", "--time", "15", backend)
        restarted = harness.until(lambda: ready(before+2), seconds=120, description="restarted strict 0157 workers")
        harness.assert_counter(docker.run("exec", backend, "python", "-c", harness.STRICT+harness.COUNTER), 4)
        assert docker.run("exec", backend, "python", "-c", check) == baseline
        print(json.dumps(dict(status="PASS", image=image, revision=revision, schema=HEAD,
            initial=first, replacement=replacement, restarted=restarted, live_routes=live_routes,
            facts=json.loads(baseline), shared_counter_values=[1,2,3,4])))
    except Exception:
        if backend:
            print(docker.redact(docker.run("logs", backend)[-5000:]))
        raise
    finally:
        docker.cleanup()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--live-routes", action="store_true")
    args = parser.parse_args()
    exercise(args.image, args.revision, args.live_routes)
