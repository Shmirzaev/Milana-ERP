"""Focused PostgreSQL regression; run only in an empty disposable test database."""
import importlib.util
import os
from pathlib import Path
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.base import Base
from app.db.session import engine, SessionLocal
from app.db.seed import seed
from app.models import Model, User, Package, PackagePrintRun, PackagePrintRunMember, FinishedGoodsStock
from app.schemas.package_workflows import ManualPackageReceiptIn
from app.services.package_workflows import manual_receipt, delete_manual_run

assert os.environ.get("MANUAL_DELETE_DISPOSABLE") == "1"
assert engine.url.database.startswith("manual_delete_qa_") and engine.url.host.startswith("manual-delete-qa-")
assert engine.dialect.name == "postgresql"
with engine.connect() as c:
    assert c.execute(text("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")).scalar() == 0
Base.metadata.create_all(engine)
seed()
root = Path(__file__).resolve().parents[1] / "backend" / "alembic" / "versions"


def load(name):
    spec = importlib.util.spec_from_file_location(name, root / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Install the original production evidence triggers, preserving their exact SQL.
class TriggerOperations:
    def __init__(self, conn): self.conn = conn
    def get_bind(self): return self.conn
    def execute(self, sql): self.conn.execute(text(sql))
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def batch_alter_table(self, *args, **kwargs): return self
    def __getattr__(self, name): return lambda *args, **kwargs: None


with engine.begin() as c:
    original = load("0115_package_print_runs")
    original.op = TriggerOperations(c)
    original.upgrade()

with SessionLocal() as db:
    user = db.query(User).filter_by(email="admin@disposable.invalid").one()
    model = db.query(Model).filter_by(code="T-SHIRT-001").one()
    payload = ManualPackageReceiptIn(request_key=uuid4(), model_id=model.id, color="White", weight_kg=2,
                                     count=2, pack_quantities=[13, 17])
    run_data = manual_receipt(db, user, payload)["print_run"]
    uid = user.id
    db.commit()
ids = run_data["package_ids"]
rid = run_data["id"]


def rejected(sql, message):
    try:
        with engine.begin() as c: c.execute(text(sql))
    except DBAPIError as exc:
        assert message in str(exc.orig), str(exc.orig)
    else:
        raise AssertionError("Expected database rejection")


rejected(f"DELETE FROM package_print_run_members WHERE run_id={rid}", "immutable")
# Recreate the pre-change FK/columns, then apply the real migration.
with engine.begin() as c:
    c.execute(text("ALTER TABLE package_print_runs DROP COLUMN deleted_at"))
    c.execute(text("ALTER TABLE package_print_run_members ADD CONSTRAINT package_print_run_members_package_id_fkey FOREIGN KEY(package_id) REFERENCES packages(id)"))
    migration = load("0127_manual_pack_deletion")
    migration.op = Operations(MigrationContext.configure(c))
    migration.upgrade()
    migration.downgrade()
    migration.upgrade()

rejected(f"DELETE FROM packages WHERE id={ids[0]}", "Printed package must belong")
rejected(f"UPDATE package_print_run_members SET snapshot='{{}}'::json WHERE run_id={rid}", "immutable")
rejected(f"DELETE FROM package_print_runs WHERE id={rid}", "immutable")
rejected(f"INSERT INTO package_print_run_members(run_id,package_id,snapshot) VALUES ({rid},999999,'{{}}')", "existing package")
with SessionLocal() as db:
    run = db.query(PackagePrintRun).filter_by(id=rid).with_for_update().one()
    before = [(m.id, m.package_id, m.snapshot) for m in db.query(PackagePrintRunMember).filter_by(run_id=rid)]
    result = delete_manual_run(db, db.get(User, uid), run)
    assert result == {"deleted_count": 2}
    db.commit()
with SessionLocal() as db:
    assert db.query(Package).filter(Package.id.in_(ids)).count() == 0
    assert db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id.in_(ids)).count() == 0
    run = db.get(PackagePrintRun, rid)
    assert run.deleted_at is not None and run.package_ids == ids
    assert before == [(m.id, m.package_id, m.snapshot) for m in db.query(PackagePrintRunMember).filter_by(run_id=rid)]
    assert delete_manual_run(db, db.get(User, uid), run) == result
    db.commit()
with SessionLocal() as db:
    new_run = manual_receipt(db, db.get(User, uid), payload)["print_run"]
    db.commit()
    assert not set(ids).intersection(new_run["package_ids"])
    assert new_run["run_no"] != run_data["run_no"]
    assert not {p["package_no"] for p in run_data["packages"]}.intersection(p["package_no"] for p in new_run["packages"])
rejected(f"UPDATE package_print_runs SET deleted_at=NULL WHERE id={rid}", "cannot be changed")
rejected(f"DELETE FROM package_print_run_members WHERE run_id={rid}", "immutable")
rejected("DELETE FROM manual_package_receipts", "immutable")
try:
    with engine.begin() as c:
        migration.op = Operations(MigrationContext.configure(c))
        migration.downgrade()
except RuntimeError as exc:
    assert "Cannot downgrade after manual package deletion" in str(exc)
else:
    raise AssertionError("Unsafe downgrade was permitted")
print("POSTGRES_MANUAL_DELETE_PASSED: original failure reproduced; migration roundtrip; guarded deletion; immutable history; repeat delete; unsafe downgrade blocked")
