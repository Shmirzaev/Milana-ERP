"""Strict immutable recovery-image rehearsal on owned isolated schema0157 PG."""
import argparse
import json
import re
import secrets

import test_rollback_image_schema_0150 as shared

HEAD = "0157_package_allocation_items"
FIXTURE = """
from app.db.session import SessionLocal
from app.schemas import Model,ProductionOrder,ProductionBatch,Package,PackageItem,PackageBatchAllocation
with SessionLocal.begin() as db:
 model=Model(code='RECOVERY-STRICT',name='Owned recovery fixture')
 db.add(model);db.flush()
 order=ProductionOrder(production_no='RECOVERY-STRICT',production_type='branded_stock',model_id=model.id,planned_quantity=1)
 db.add(order);db.flush()
 batch=ProductionBatch(batch_no='RECOVERY-STRICT',production_order_id=order.id,planned_quantity=1)
 db.add(batch);db.flush()
 package=Package(package_no='RECOVERY-STRICT',barcode='RECOVERY-STRICT',production_order_id=order.id,production_batch_id=batch.id,
                 model_id=model.id,color='navy',total_quantity=1,capacity=1,status='packed')
 db.add(package);db.flush()
 matrix=[dict(model_id=model.id,color='navy',size='M',quantity=1)]
 db.add(PackageItem(package_id=package.id,**matrix[0]))
 db.add(PackageBatchAllocation(package_id=package.id,production_batch_id=batch.id,quantity=1,item_breakdown=matrix))
"""
VERIFY = """
from sqlalchemy import text
from app.db.session import SessionLocal
from app.schemas import Model,User,Package,PackageBatchAllocation
from app.models.packaging.recovery_guard_service import require_recovery_editable,RECOVERY_REFUSAL
from fastapi import HTTPException
with SessionLocal() as db:
 assert db.execute(text('SELECT version_num FROM alembic_version')).scalar_one()=='0157_package_allocation_items'
 assert db.query(Model).count()==1 and db.query(User).count()==0
 package=db.query(Package).one()
 row=db.query(PackageBatchAllocation).one()
 assert package.package_no=='RECOVERY-STRICT' and package.total_quantity==1
 assert row.item_breakdown==[dict(model_id=package.model_id,color='navy',size='M',quantity=1)]
 try:require_recovery_editable(package)
 except HTTPException as error:assert error.status_code==409 and error.detail==RECOVERY_REFUSAL
 else:raise AssertionError('Exact evidence mutation was permitted')
"""


def exercise(image, revision):
    shared.require_digest(image)
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Expected full reviewed source commit")
    docker = shared.OwnedDocker()
    backend = None
    try:
        docker.run("pull", image, timeout=180)
        config = json.loads(docker.run("image", "inspect", image))[0]["Config"]
        assert config["Cmd"] == shared.DEFAULT_CMD and not config.get("Entrypoint")
        assert config.get("Labels", {}).get("org.opencontainers.image.revision") == revision
        docker.run("pull", "postgres:17", timeout=180)
        docker.network = docker.run("network", "create", "--internal", "--label", f"{shared.LABEL}={docker.owner}",
                                    "rollback-0157-" + docker.owner)
        password, jwt, signing = [secrets.token_hex(32) for _ in range(3)]
        docker.hidden = [password, jwt, signing]
        pg = docker.create("rollback-pg-" + docker.owner, "postgres:17", alias="pg", env={
            "POSTGRES_USER": "rollback_qa", "POSTGRES_PASSWORD": password, "POSTGRES_DB": "rollback_qa"})
        shared.until(lambda: docker.run("exec", pg, "pg_isready", "-U", "rollback_qa", "-d", "rollback_qa"),
                     description="owned PostgreSQL")
        backend = docker.create("rollback-backend-" + docker.owner, image, alias="backend", env={
            "ENV": "production", "DEBUG": "false", "STARTUP_SCHEMA_SYNC": "false", "RUN_SEED_ON_STARTUP": "false",
            "SEED_DEMO_USERS": "false", "SEED_SAMPLE_DATA": "false", "IMPORT_LEGACY_MODELS": "false",
            "DATABASE_URL": f"postgresql+psycopg2://rollback_qa:{password}@pg:5432/rollback_qa",
            "JWT_SECRET": jwt, "FILE_SIGNING_SECRET": signing, "SHARED_STORE_URL": shared.COUNTER_URL,
            "SHARED_STORE_KEY_PREFIX": "rollback-0157-" + docker.owner,
            "CORS_ORIGINS": "https://rollback-qa.invalid", "FRONTEND_BASE_URL": "https://rollback-qa.invalid",
            "ERP_PUBLIC_BASE_URL": "https://rollback-qa.invalid", "TRUSTED_PROXY_CIDRS": "127.0.0.1/32",
            "FORWARDED_ALLOW_IPS": "", "WEB_CONCURRENCY": "2", "PORT": "10000",
        })
        marker = "startup: database migration head verified (" + HEAD + ")"

        def ready(minimum):
            workers = json.loads(docker.run("exec", backend, "python", "-c", shared.WORKERS))
            if len(workers) != 2 or docker.run("logs", backend).count(marker) < minimum:
                return False
            docker.run("exec", backend, "python", "-c", shared.PROBES + shared.STRICT)
            return workers

        first = shared.until(lambda: ready(2), seconds=120, description="two strict schema0157 workers")
        docker.run("exec", backend, "python", "-c", FIXTURE)

        def verify(expected_counter):
            docker.run("exec", backend, "python", "-c", VERIFY)
            output = docker.run("exec", backend, "python", "-c", shared.STRICT + shared.COUNTER)
            shared.assert_counter(output, expected_counter)

        verify(1)
        before = docker.run("logs", backend).count(marker)
        victim = first[0]
        docker.run("exec", backend, "python", "-c", f"import os,signal;os.kill({victim},signal.SIGKILL)")

        def replaced():
            workers = ready(before + 1)
            return workers if workers and victim not in workers and len(set(workers) - set(first)) == 1 else False

        replacement = shared.until(replaced, description="replacement child and strict0157 verification")
        verify(2)
        before = docker.run("logs", backend).count(marker)
        docker.run("restart", "--time", "15", backend)
        restarted = shared.until(lambda: ready(before + 2), seconds=120, description="full strict0157 restart")
        verify(3)
        print(json.dumps({"status": "PASS", "image": image, "revision": revision, "schema": HEAD,
                          "initial_workers": first, "replacement_workers": replacement, "restarted_workers": restarted,
                          "exact_fixture_preserved": True, "shared_counter_values": [1, 2, 3]}))
    except Exception:
        if backend:
            print("Owned backend diagnostics:\n" + docker.redact(docker.run("logs", backend)[-6000:]))
        raise
    finally:
        docker.cleanup()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    exercise(args.image, args.revision)
