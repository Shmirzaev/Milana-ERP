"""Local-only migration/immutable-history/concurrent-payroll regression.

HANDOFF_QA_DATABASE_URL must identify an empty loopback handoffs_contract_qa DB.
No production connection or business data is used.
"""
import importlib.util
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import MagicMock

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

url = make_url(os.environ["HANDOFF_QA_DATABASE_URL"])
assert url.host in {"localhost", "127.0.0.1"} and url.database == "handoffs_contract_qa"
os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)

from app.db.base import Base
from app.models import User, Role, Employee, PayrollQrLabel, PayrollRecord, PackagePrintRun, PackagePrintRunMember
from app.api.routes.payroll import record_numeric_work_scan, split_scanned_record
from app.schemas.payroll import PayrollNumericWorkScanIn, PayrollScanSplitIn

engine = create_engine(url)
assert not inspect(engine).get_table_names(), "Use an empty disposable QA database"
Base.metadata.create_all(engine)


def migration(filename):
    spec = importlib.util.spec_from_file_location("qa_migration", Path(__file__).parents[1] / "alembic/versions" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


revision = migration("0134_packaging_returns.py")
with engine.begin() as connection:
    # Reconstruct the immediately preceding production schema from current metadata.
    for column in ("returned_at", "returned_by", "return_reason"):
        connection.execute(text(f"ALTER TABLE package_print_runs DROP COLUMN {column}"))
    connection.execute(text("ALTER TABLE package_print_run_members DROP CONSTRAINT uq_package_print_run_member_run_package"))
    connection.execute(text("ALTER TABLE package_print_run_members ADD CONSTRAINT uq_package_print_run_member_package UNIQUE(package_id)"))
    connection.execute(text("ALTER TABLE packages DROP CONSTRAINT ck_packages_status"))
    connection.execute(text(f"ALTER TABLE packages ADD CONSTRAINT ck_packages_status CHECK (status IN ({revision.OLD_STATUSES}))"))
    # Install the real existing immutable-history functions/triggers without
    # rerunning historical table creation against current metadata.
    legacy = migration("0115_package_print_runs.py")
    legacy.op = MagicMock()
    legacy.op.get_bind.return_value = connection
    legacy.op.execute.side_effect = lambda sql: connection.execute(text(sql))
    legacy.upgrade()
    with Operations.context(MigrationContext.configure(connection)):
        revision.upgrade()
        revision.downgrade()
        revision.upgrade()
print("PASS: 0133 -> 0134 -> 0133 -> 0134 with original immutable evidence triggers")

Session = sessionmaker(engine, expire_on_commit=False)
with Session() as db:
    role = Role(name="QA", permissions=["*"])
    user = User(name="QA", email="handoffs@example.test", password_hash="unused", role=role, factory_code="MIL")
    employees = [Employee(full_name=f"Worker {n}", status="active", factory_code="MIL") for n in range(2)]
    label = PayrollQrLabel(factory_code="MIL", label_uid="QA-SPLIT", operation_name="Sew", quantity=20, rate_per_piece=100, currency="UZS", status="available")
    db.add_all([user, label, *employees]); db.commit()
    uid, employee_ids, label_id = user.id, [e.id for e in employees], label.id
    result = record_numeric_work_scan(PayrollNumericWorkScanIn(token=f"2{label.id:08d}", employee_id=employees[0].id), db, user)
    record_id = result["record"]["id"]

barrier = Barrier(2)


def split(_):
    with Session() as db:
        user = db.get(User, uid)
        barrier.wait()
        return split_scanned_record(record_id, PayrollScanSplitIn(parts=[
            {"employee_id": employee_ids[0], "quantity": 7}, {"employee_id": employee_ids[1], "quantity": 13},
        ]), db, user)


with ThreadPoolExecutor(max_workers=2) as pool:
    results = list(pool.map(split, range(2)))
assert [r["id"] for r in results[0]] == [r["id"] for r in results[1]]
with Session() as db:
    assert db.query(PayrollRecord).filter_by(status="recorded").count() == 2
    assert sum(r.total_amount for r in db.query(PayrollRecord).filter_by(status="recorded")) == 2000
    run = PackagePrintRun(run_no="QA-PRINT", code="PACKRUN:QA", packaging_department_code="PKG", package_ids=[123], created_by=uid)
    db.add(run); db.flush()
    db.add(PackagePrintRunMember(run_id=run.id, package_id=123, snapshot={"barcode": "old-qr", "quantity": 20}))
    db.commit(); run_id = run.id
print("PASS: simultaneous split requests credit exactly two allocations once")


def must_reject(statement):
    try:
        with engine.begin() as connection:
            connection.execute(text(statement), {"id": run_id, "uid": uid})
    except DBAPIError:
        return
    raise AssertionError("Immutable evidence change was accepted")


must_reject("UPDATE package_print_run_members SET snapshot='{}' WHERE run_id=:id")
must_reject("DELETE FROM package_print_run_members WHERE run_id=:id")
with engine.begin() as connection:
    connection.execute(text("UPDATE package_print_runs SET returned_at=now(), returned_by=:uid, return_reason='Wrong label' WHERE id=:id"), {"id": run_id, "uid": uid})
must_reject("UPDATE package_print_runs SET returned_at=NULL WHERE id=:id")
must_reject("UPDATE package_print_runs SET received_at=now() WHERE id=:id")
try:
    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        revision.downgrade()
except RuntimeError:
    pass
else:
    raise AssertionError("Downgrade after a return was accepted")
print("PASS: old print snapshots, return reason, receipt exclusion and post-return downgrade guards")
