"""Daily-report writers follow sewing's work-order then parent lock order."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from queue import Queue
from time import monotonic, sleep
from uuid import uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.api.routes.sewing_daily_reports import create_report, delete_report, update_report
from app.schemas import (
    Department,
    Model,
    ProductionOrder,
    SewingDailyReport,
    SewingFlow,
    User,
    WorkOrder,
)
from app.libs.dto.production.sewing_daily_report import SewingDailyReportCreate, SewingDailyReportUpdate
from app.tests.conftest import TestSessionLocal
from app.tests.test_fresh_migration_bootstrap import postgres_migrations  # noqa: F401


def _case(sessions, *, two_work_orders=False):
    marker = uuid4().hex
    with sessions.begin() as db:
        model = Model(code=f"WF12-{marker}", name="WF12 synthetic model")
        department = Department(name=f"WF12 sewing {marker}", code=f"W{marker[:8]}")
        actor = User(
            name="WF12 sewing reporter",
            email=f"wf12-{marker}@example.invalid",
            password_hash="unused",
            factory_code="MIL",
            extra_permissions=["sewing.workspace"],
        )
        flow = SewingFlow(
            factory_code="MIL",
            name=f"WF12 line {marker}",
            code=f"WF12-{marker[:8]}",
            capacity_per_day=100,
            is_active=True,
        )
        db.add_all([model, department, actor, flow])
        db.flush()
        order = ProductionOrder(
            production_no=f"WF12-{marker}",
            production_type="branded_stock",
            model_id=model.id,
            status="sewing",
            planned_quantity=10,
        )
        db.add(order)
        db.flush()
        work_orders = [
            WorkOrder(
                production_order_id=order.id,
                department_id=department.id,
                sewing_flow_id=flow.id,
                operation="sewing",
                status="in_progress",
                planned_input_qty=10,
                planned_output_qty=10,
            )
            for _ in range(2 if two_work_orders else 1)
        ]
        db.add_all(work_orders)
        db.flush()
        report = SewingDailyReport(
            report_date=date(2026, 9, 20),
            sewing_flow_id=flow.id,
            work_order_id=work_orders[0].id,
            production_order_id=order.id,
            line_code=flow.code,
            line_name=flow.name,
            order_no=order.production_no,
            production_no=order.production_no,
            sewn_qty=2,
            defective_qty=0,
            created_by=actor.id,
        )
        db.add(report)
        db.flush()
        return {
            "actor_id": actor.id,
            "flow_id": flow.id,
            "order_id": order.id,
            "report_id": report.id,
            "work_order_ids": [row.id for row in work_orders],
        }


def _create_payload(case, work_order_id, *, sewn_qty=3):
    return SewingDailyReportCreate(
        report_date=date(2026, 9, 21),
        sewing_flow_id=case["flow_id"],
        work_order_id=work_order_id,
        sewn_qty=sewn_qty,
    )


def _update_payload(*, sewn_qty=3):
    return SewingDailyReportUpdate(
        report_date=date(2026, 9, 20),
        sewn_qty=sewn_qty,
        defective_qty=0,
    )


def test_same_parent_capacity_covers_reports_from_different_work_orders():
    case = _case(TestSessionLocal, two_work_orders=True)
    with TestSessionLocal() as db:
        create_report(
            _create_payload(case, case["work_order_ids"][1], sewn_qty=8),
            db,
            db.get(User, case["actor_id"]),
        )
    with TestSessionLocal() as db, pytest.raises(HTTPException) as rejected:
        create_report(
            _create_payload(case, case["work_order_ids"][1], sewn_qty=1),
            db,
            db.get(User, case["actor_id"]),
        )
    assert rejected.value.status_code == 400
    with TestSessionLocal() as db:
        assert db.query(SewingDailyReport).filter_by(production_order_id=case["order_id"]).count() == 2


@pytest.fixture
def report_lock_postgres_sessions(postgres_migrations):
    command.upgrade(postgres_migrations.config, "head")
    return sessionmaker(bind=postgres_migrations.engine, expire_on_commit=False, autoflush=False)


@pytest.mark.parametrize("operation", ["create", "update", "delete"])
def test_postgres_report_write_waits_for_work_order_before_parent(report_lock_postgres_sessions, operation):
    sessions = report_lock_postgres_sessions
    case = _case(sessions)
    worker_pid = Queue()

    def write_report():
        with sessions() as db:
            assert db.bind.dialect.name == "postgresql"
            worker_pid.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            actor = db.get(User, case["actor_id"])
            if operation == "create":
                create_report(_create_payload(case, case["work_order_ids"][0]), db, actor)
            elif operation == "update":
                update_report(case["report_id"], _update_payload(), db, actor)
            else:
                delete_report(case["report_id"], db, actor)

    with sessions() as holder, ThreadPoolExecutor(max_workers=1) as workers:
        assert holder.bind.dialect.name == "postgresql"
        holder_pid = holder.execute(text("SELECT pg_backend_pid()")).scalar_one()
        work_order = (
            holder.query(WorkOrder)
            .filter(WorkOrder.id == case["work_order_ids"][0])
            .with_for_update(of=WorkOrder)
            .one()
        )
        future = workers.submit(write_report)
        pid = worker_pid.get(timeout=10)
        try:
            deadline = monotonic() + 10
            while monotonic() < deadline:
                if holder_pid in holder.execute(
                    text("SELECT unnest(pg_blocking_pids(:pid))"),
                    {"pid": pid},
                ).scalars().all():
                    break
                if future.done():
                    pytest.fail("Report writer completed without waiting for the locked work order")
                sleep(0.02)
            else:
                pytest.fail("Report writer did not visibly wait for the locked work order")

            parent = holder.execute(
                text("SELECT id FROM production_orders WHERE id=:id FOR UPDATE NOWAIT"),
                {"id": case["order_id"]},
            ).scalar_one()
            assert parent == case["order_id"]
            work_order.notes = "sewing writer committed first"
            holder.get(ProductionOrder, case["order_id"]).status = "sewing"
            holder.commit()
        finally:
            if holder.in_transaction():
                holder.rollback()
        future.result(timeout=20)

    with sessions() as db:
        assert db.get(WorkOrder, case["work_order_ids"][0]).notes == "sewing writer committed first"
        report_count = db.query(SewingDailyReport).filter_by(production_order_id=case["order_id"]).count()
        assert report_count == {"create": 2, "update": 1, "delete": 0}[operation]
