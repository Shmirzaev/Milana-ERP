"""Exercise account provisioning locks on real disposable PostgreSQL."""
from alembic import command
from datetime import date
from sqlalchemy.orm import sessionmaker

from app.models import Bundle, Department, Model, ProductionOrder, Role, SewingAssignment, SewingFlow, User, WorkOrder
from app.services.sewing_band_setup import configure_eco_bands
from app.tests.test_fresh_migration_bootstrap import postgres_migrations  # noqa: F401


def test_band_provisioning_outer_join_lock_and_retry(postgres_migrations):
    command.upgrade(postgres_migrations.config, "head")
    sessions = sessionmaker(bind=postgres_migrations.engine, expire_on_commit=False)
    with sessions() as db:
        role = Role(name="Band QA Admin", permissions=["*"])
        db.add(role); db.flush()
        actor = User(name="QA", email="qa@example.test", password_hash="unused", role_id=role.id)
        db.add(actor)
        for n in range(1, 21):
            if not db.query(SewingFlow).filter_by(code=f"ECO-BAND-{n:02}", factory_code="ECO").first():
                db.add(SewingFlow(code=f"ECO-BAND-{n:02}", name=f"{n}-Band", factory_code="ECO"))
        db.flush()
        assert len(configure_eco_bands(db, actor)["create"]) == 10
        result = configure_eco_bands(db, actor, "Fixture!123456", apply=True)
        assert len(result["create"]) == 10
        db.commit()
        # Existing users eagerly load nullable role/department joins; PostgreSQL
        # must lock only users, never the nullable side of these outer joins.
        retry = configure_eco_bands(db, actor, "Unused!123456", apply=True)
        assert len(retry["keep"]) == 10 and retry["create"] == []
        assert db.query(SewingFlow).filter_by(factory_code="ECO", is_active=True).count() == 10
        assert db.query(User).filter(User.sewing_band_id.isnot(None)).count() == 10
        db.rollback()

    # Exercise the real receipt -> daily progress -> final output handoff using
    # PostgreSQL row/advisory locks, not SQLite's no-op FOR UPDATE behavior.
    from app.api.routes.sewing_bands import ReceiveIn, receive, record_output
    from app.api.routes.sewing_daily_reports import create_report
    from app.schemas.production import SewingRecordIn
    from app.schemas.sewing_daily_report import SewingDailyReportCreate
    from app.services.idempotency import bind_idempotency_identity
    from app.services.sewing_band_progress import band_board
    with sessions() as db:
        band = db.query(User).filter_by(email="band1@milanapremium.uz").one()
        sewing = db.query(Department).filter_by(code="ECO").one()
        packing = db.query(Department).filter_by(code="ECP").one()
        model = Model(code="BAND-PG", name="Band PostgreSQL QA")
        db.add_all([packing, model]); db.flush()
        order = ProductionOrder(production_no="BAND-PG-01", model_id=model.id, production_type="branded_stock", planned_quantity=20, status="in_progress")
        db.add(order); db.flush()
        work = WorkOrder(production_order_id=order.id, department_id=sewing.id, operation="sewing", status="in_progress", planned_input_qty=20, planned_output_qty=20)
        downstream = WorkOrder(production_order_id=order.id, department_id=packing.id, operation="packaging", status="waiting", planned_input_qty=20, planned_output_qty=20)
        bundle = Bundle(bundle_no="BAND-PG-01", barcode="BAND-PG-01", production_order_id=order.id, model_id=model.id, color="white", size="M", quantity=20, sewing_factory_code="ECO", next_department_id=sewing.id, status="created")
        db.add_all([work, downstream, bundle]); db.commit()
        bind_idempotency_identity(db, band)
        assert receive(ReceiveIn(code=bundle.barcode), db, band)["received_count"] == 1
        assignment = db.query(SewingAssignment).filter_by(work_order_id=work.id).one()
        payload = SewingDailyReportCreate(report_date=date.today(), sewing_flow_id=band.sewing_band_id, work_order_id=work.id, sewing_assignment_id=assignment.id, sewn_qty=20)
        create_report(payload, db, band, "pg-report")
        assert work.passed_qty == 0 and assignment.completed_qty == 0
        job = band_board(db, [band.sewing_band_id])[0]["jobs"][0]
        assert job["line_finished"] and job["awaiting_final"]
        output = SewingRecordIn(work_order_id=work.id, sewing_assignment_id=assignment.id, input_qty=0, sewn_qty=20, passed_qty=20)
        result = record_output(assignment.id, output, db, band, "pg-output")
        assert record_output(assignment.id, output, db, band, "pg-output") == result
        db.refresh(work); db.refresh(downstream); db.refresh(assignment)
        assert work.passed_qty == 20 and assignment.completed_qty == 20
        assert work.status == "completed" and downstream.status == "in_progress"
        assert downstream.passed_qty == 0 and downstream.actual_output_qty == 0
