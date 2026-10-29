"""Print-run persistence against the approved disposable PostgreSQL fixture."""
from uuid import uuid4

from app.models.package_workflows_service import create_run
from app.schemas import (
    AuditLog, Department, Model, Package, PackageItem, PackagePrintRun,
    PackagePrintRunMember, PackagingRecord, ProductionOrder, User, WorkOrder,
)
from app.tests.test_customer_create_postgres import chain, customer_pg_sessions  # noqa: F401


def test_print_run_persistence_roundtrips_on_approved_postgres(customer_pg_sessions):
    sessions = customer_pg_sessions
    marker = uuid4().hex
    with sessions.begin() as db:
        department = db.query(Department).filter_by(code="PKG").one_or_none()
        if department is None:
            department = Department(name="Packaging", code="PKG")
            db.add(department)
            db.flush()
        model = Model(
            code=f"PRINT-RUN-{marker}",
            name=f"Print run persistence {marker}",
            product_type="shirt",
        )
        db.add(model)
        db.flush()
        order = ProductionOrder(
            production_no=f"PRINT-RUN-PO-{marker}",
            production_type="branded_stock",
            source_type="standard",
            model_id=model.id,
            planned_quantity=2,
            status="packaging",
        )
        db.add(order)
        db.flush()
        work_order = WorkOrder(
            production_order_id=order.id,
            department_id=department.id,
            operation="packaging",
            status="completed",
            planned_input_qty=2,
            planned_output_qty=2,
            actual_input_qty=2,
            actual_output_qty=2,
            passed_qty=2,
        )
        db.add(work_order)
        db.flush()
        db.add(PackagingRecord(
            work_order_id=work_order.id,
            input_qty=2,
            packed_qty=2,
            package_count=2,
            total_packed_quantity=2,
        ))
        actor = User(
            name="Print run persistence QA",
            email=f"print-run-{marker}@example.invalid",
            password_hash="unused",
        )
        db.add(actor)
        packages = [
            Package(
                package_no=f"PRINT-RUN-PKG-{marker}-{index}",
                barcode=f"PRINT-RUN-BC-{marker}-{index}",
                production_order_id=order.id,
                model_id=model.id,
                color="navy",
                total_quantity=1,
                capacity=1,
                status="packed",
                packaging_department_code="PKG",
                items=[PackageItem(model_id=model.id, color="navy", size="M", quantity=1)],
            )
            for index in range(2)
        ]
        db.add_all(packages)
        db.flush()
        run = create_run(db, actor, packages)
        run_id = int(run.id)
        package_ids = [int(package.id) for package in packages]
        actor_id = int(actor.id)

    with sessions() as db:
        persisted = db.get(PackagePrintRun, run_id)
        members = (
            db.query(PackagePrintRunMember)
            .filter_by(run_id=run_id)
            .order_by(PackagePrintRunMember.id)
            .all()
        )
        audit = db.query(AuditLog).filter_by(
            action="create_print_run", entity_id=run_id,
        ).one()
        assert persisted.package_ids == package_ids
        assert persisted.created_by == actor_id
        assert persisted.packaging_department_code == "PKG"
        assert persisted.received_by is None and persisted.received_at is None
        assert [member.package_id for member in members] == package_ids
        assert all(member.snapshot["quantity"] == 1 for member in members)
        assert audit.new_value_json["package_ids"] == package_ids
    chain(sessions)
