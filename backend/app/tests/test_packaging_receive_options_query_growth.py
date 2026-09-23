import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, func, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.routes import production as production_routes
from app.core.model_search import model_code_contains
from app.db.base import Base
from app.models import (
    Department,
    Model,
    PackagingReceipt,
    ProductionBatch,
    ProductionOrder,
    SalesOrder,
    SewingRecord,
    User,
    WorkOrder,
)
from app.services.packaging_scope import packaging_department_for_order, packaging_work_order_department_code
from app.tests.conftest import TestSessionLocal


def _department(db, code: str) -> Department:
    return db.query(Department).filter(Department.code == code).one()


def _work_order(
    *,
    order_id: int,
    batch_id: int | None,
    department_id: int,
    operation: str,
) -> WorkOrder:
    return WorkOrder(
        production_order_id=order_id,
        production_batch_id=batch_id,
        department_id=department_id,
        operation=operation,
        status="waiting",
        planned_input_qty=0,
        planned_output_qty=0,
        actual_input_qty=0,
        actual_output_qty=0,
        passed_qty=0,
        failed_qty=0,
        rework_qty=0,
    )


def _receive_option_orders(count: int) -> None:
    marker = uuid4().hex[:8]
    with TestSessionLocal() as db:
        sewing_department = _department(db, "SEW")
        packaging_department = _department(db, "PKG")
        model = Model(code=f"PERF18-{marker}", name=f"Receive options {marker}")
        db.add(model)
        db.flush()
        for number in range(count):
            order = ProductionOrder(
                production_no=f"PERF18-{marker}-{number:04d}",
                production_type="branded_stock",
                model_id=model.id,
                planned_quantity=10,
                status="sewing",
            )
            db.add(order)
            db.flush()
            sewing = _work_order(
                order_id=order.id,
                batch_id=None,
                department_id=sewing_department.id,
                operation="sewing",
            )
            packaging = _work_order(
                order_id=order.id,
                batch_id=None,
                department_id=packaging_department.id,
                operation="packaging",
            )
            db.add_all([sewing, packaging])
            db.flush()
            db.add(SewingRecord(
                work_order_id=sewing.id,
                production_batch_id=None,
                input_qty=number + 10,
                sewn_qty=number + 10,
                passed_qty=number + 10,
                failed_qty=0,
                rejected_qty=0,
                rework_qty=0,
            ))
        db.commit()


def test_packaging_department_lookup_preserves_priority_with_one_projected_query():
    marker = uuid4().hex[:8]
    with TestSessionLocal() as db:
        model = Model(code=f"PERF18-SCOPE-{marker}", name=f"Packaging scope {marker}")
        db.add(model)
        db.flush()
        orders = [
            ProductionOrder(
                production_no=f"PERF18-SCOPE-PO-{marker}-{index}",
                production_type="branded_stock",
                model_id=model.id,
                planned_quantity=1,
            )
            for index in range(2)
        ]
        db.add_all(orders)
        db.flush()
        first_batch = ProductionBatch(
            production_order_id=orders[0].id,
            batch_no=f"PERF18-SCOPE-B1-{marker}",
            batch_index=1,
            planned_quantity=1,
        )
        other_batch = ProductionBatch(
            production_order_id=orders[0].id,
            batch_no=f"PERF18-SCOPE-B2-{marker}",
            batch_index=2,
            planned_quantity=1,
        )
        fallback_batch = ProductionBatch(
            production_order_id=orders[1].id,
            batch_no=f"PERF18-SCOPE-B3-{marker}",
            batch_index=1,
            planned_quantity=1,
        )
        latest_fallback_batch = ProductionBatch(
            production_order_id=orders[1].id,
            batch_no=f"PERF18-SCOPE-B4-{marker}",
            batch_index=2,
            planned_quantity=1,
        )
        requested_fallback_batch = ProductionBatch(
            production_order_id=orders[1].id,
            batch_no=f"PERF18-SCOPE-B5-{marker}",
            batch_index=3,
            planned_quantity=1,
        )
        db.add_all([first_batch, other_batch, fallback_batch, latest_fallback_batch, requested_fallback_batch])
        db.flush()
        pk, bp, ec = (_department(db, code).id for code in ("PKG", "BPK", "ECP"))
        db.add_all([
            _work_order(order_id=orders[0].id, batch_id=first_batch.id, department_id=bp, operation="packaging"),
            _work_order(order_id=orders[0].id, batch_id=None, department_id=pk, operation="packaging"),
            _work_order(order_id=orders[1].id, batch_id=fallback_batch.id, department_id=bp, operation="packaging"),
            _work_order(order_id=orders[1].id, batch_id=latest_fallback_batch.id, department_id=ec, operation="packaging"),
        ])
        db.flush()

        statements = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            assert packaging_department_for_order(db, orders[0].id, first_batch.id) == "BPK"
            assert packaging_department_for_order(db, orders[0].id, other_batch.id) == "PKG"
            assert packaging_department_for_order(db, orders[0].id) == "PKG"
            assert packaging_department_for_order(db, orders[1].id, requested_fallback_batch.id) == "ECP"
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

        assert len(statements) == 4, statements
        assert all("select departments.code" in statement for statement in statements)


@pytest.mark.parametrize("scope_count", [1, 50, 401])
def test_packaging_receive_options_has_bounded_query_and_result_growth(scope_count):
    _receive_option_orders(scope_count)
    with TestSessionLocal() as db:
        current = db.query(User).filter(User.email == "admin@example.com").one()
        statements: list[str] = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)
                assert len(statements) <= 20, (
                    f"{scope_count} receive scopes exceeded the 20-SELECT budget"
                )

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            rows = production_routes.packaging_receive_options(
                db,
                current,
                q=None,
                limit=10,
                packaging_department_code="PKG",
            )
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert len(rows) == min(scope_count, 10)
    assert [row["available_quantity"] for row in rows] == sorted(
        (row["available_quantity"] for row in rows),
        reverse=True,
    )


def test_packaging_receive_options_plan_has_no_correlated_target_probe():
    _receive_option_orders(50)
    with TestSessionLocal() as db:
        current = db.query(User).filter(User.email == "admin@example.com").one()
        statements: list[tuple[str, object]] = []

        def capture(_connection, _cursor, statement, parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append((statement, parameters))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            rows = production_routes.packaging_receive_options(
                db,
                current,
                q=None,
                limit=10,
                packaging_department_code="PKG",
            )
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

        plans = [
            db.connection().exec_driver_sql(
                f"EXPLAIN QUERY PLAN {statement}",
                parameters,
            ).all()
            for statement, parameters in statements
        ]

    assert len(rows) == 10
    assert len(statements) == 2
    plan_text = "\n".join(str(column) for plan in plans for row in plan for column in row)
    assert "CORRELATED" not in plan_text.upper()
    assert "SCALAR SUBQUERY" not in plan_text.upper()


def _scalar_receive_options(db, current, *, q, limit, packaging_department_code):
    department_code = production_routes.packaging_department_scope(
        current,
        packaging_department_code,
    )
    rows = (
        db.query(
            SewingRecord.work_order_id,
            WorkOrder.production_order_id,
            SewingRecord.production_batch_id,
            func.coalesce(func.sum(SewingRecord.passed_qty), 0),
        )
        .join(WorkOrder, WorkOrder.id == SewingRecord.work_order_id)
        .filter(WorkOrder.operation == "sewing", SewingRecord.passed_qty > 0)
        .group_by(
            SewingRecord.work_order_id,
            WorkOrder.production_order_id,
            SewingRecord.production_batch_id,
        )
        .all()
    )
    po_ids = sorted({int(row[1]) for row in rows})
    po_by_id = {
        int(po.id): po
        for po in db.query(ProductionOrder).filter(ProductionOrder.id.in_(po_ids)).all()
    } if po_ids else {}
    model_ids = sorted({int(po.model_id) for po in po_by_id.values()})
    model_by_id = {
        int(model.id): model
        for model in db.query(Model).filter(Model.id.in_(model_ids)).all()
    } if model_ids else {}
    batch_ids = sorted({int(row[2]) for row in rows if row[2] is not None})
    batch_by_id = {
        int(batch.id): batch
        for batch in db.query(ProductionBatch).filter(ProductionBatch.id.in_(batch_ids)).all()
    } if batch_ids else {}
    needle = str(q or "").strip().lower()
    options = []
    for source_work_order_id, production_order_id, production_batch_id, sewing_passed in rows:
        target = production_routes._packaging_target_work_order(
            db,
            int(production_order_id),
            production_batch_id,
        )
        if not target:
            continue
        if packaging_work_order_department_code(db, target) != department_code:
            continue
        _, received = production_routes._packaging_sewing_totals(
            db,
            int(source_work_order_id),
            production_batch_id,
        )
        available = max(0, int(sewing_passed or 0) - received)
        if available <= 0:
            continue
        po = po_by_id.get(int(production_order_id))
        model = model_by_id.get(int(po.model_id)) if po else None
        batch = batch_by_id.get(int(production_batch_id)) if production_batch_id is not None else None
        option = {
            "work_order_id": target.id,
            "source_work_order_id": int(source_work_order_id),
            "production_order_id": int(production_order_id),
            "production_batch_id": production_batch_id,
            "production_no": po.production_no if po else None,
            "order_no": po.order_no if po else None,
            "model_code": model.code if model else None,
            "model_name": model.name if model else None,
            "batch_no": batch.batch_no if batch else None,
            "batch_name": batch.name if batch else None,
            "sewing_passed": int(sewing_passed or 0),
            "received_quantity": received,
            "available_quantity": available,
        }
        if needle:
            haystack = " ".join(str(value or "") for value in option.values()).lower()
            if needle not in haystack and not model_code_contains(option.get("model_code"), needle):
                continue
        options.append(option)
    options.sort(key=lambda row: (-int(row["available_quantity"]), -int(row["work_order_id"])))
    return options[: max(1, min(int(limit or 100), 500))]


def _mixed_receive_options() -> None:
    marker = uuid4().hex[:8]
    with TestSessionLocal() as db:
        sewing_department = _department(db, "SEW")
        pkg_department = _department(db, "PKG")
        bpk_department = _department(db, "BPK")
        normalized_pkg_department = Department(
            name=f"Normalized packaging {marker}",
            code=f" pkg {marker}",
        )
        model = Model(code=f"АВ-{marker}", name=f"Literal %_ \\ {marker}")
        sale = SalesOrder(
            order_no=f"CLIENT-ALIAS-{marker}",
            order_type="client_order",
            status="production",
            total_amount=0,
        )
        empty_alias_sale = SalesOrder(
            order_no="",
            order_type="client_order",
            status="production",
            total_amount=0,
        )
        db.add_all([model, sale, empty_alias_sale, normalized_pkg_department])
        db.flush()
        # The production helper trims and uppercases a department code before
        # comparing it with the requested packaging scope.
        normalized_pkg_department.code = " pkg "

        exact_order = ProductionOrder(
            production_no=f"PROD-EXACT-{marker}",
            production_type="client_order",
            sales_order_id=sale.id,
            model_id=model.id,
            planned_quantity=100,
            status="sewing",
        )
        fallback_order = ProductionOrder(
            production_no=f"PROD-FALLBACK-{marker}",
            production_type="branded_stock",
            model_id=model.id,
            planned_quantity=100,
            status="sewing",
        )
        wrong_department_order = ProductionOrder(
            production_no=f"PROD-WRONG-{marker}",
            production_type="branded_stock",
            model_id=model.id,
            planned_quantity=100,
            status="sewing",
        )
        public_alias_order = ProductionOrder(
            production_no=f"  PUBLIC-ALIAS-{marker}  ",
            production_type="client_order",
            sales_order_id=empty_alias_sale.id,
            model_id=model.id,
            planned_quantity=100,
            status="sewing",
        )
        db.add_all([exact_order, fallback_order, wrong_department_order, public_alias_order])
        db.flush()
        exact_batch = ProductionBatch(
            production_order_id=exact_order.id,
            batch_no=f"EXACT-{marker}",
            batch_index=1,
            name="Exact batch",
            planned_quantity=100,
        )
        missing_target_batch = ProductionBatch(
            production_order_id=fallback_order.id,
            batch_no=f"FALLBACK-{marker}",
            batch_index=1,
            name="Fallback batch",
            planned_quantity=100,
        )
        wrong_batch = ProductionBatch(
            production_order_id=wrong_department_order.id,
            batch_no=f"WRONG-{marker}",
            batch_index=1,
            planned_quantity=100,
        )
        db.add_all([exact_batch, missing_target_batch, wrong_batch])
        db.flush()

        exact_source = _work_order(
            order_id=exact_order.id,
            batch_id=exact_batch.id,
            department_id=sewing_department.id,
            operation="sewing",
        )
        exact_target = _work_order(
            order_id=exact_order.id,
            batch_id=exact_batch.id,
            department_id=pkg_department.id,
            operation="packaging",
        )
        fallback_source = _work_order(
            order_id=fallback_order.id,
            batch_id=missing_target_batch.id,
            department_id=sewing_department.id,
            operation="sewing",
        )
        fallback_target = _work_order(
            order_id=fallback_order.id,
            batch_id=None,
            department_id=pkg_department.id,
            operation="packaging",
        )
        wrong_source = _work_order(
            order_id=wrong_department_order.id,
            batch_id=wrong_batch.id,
            department_id=sewing_department.id,
            operation="sewing",
        )
        wrong_target = _work_order(
            order_id=wrong_department_order.id,
            batch_id=None,
            department_id=bpk_department.id,
            operation="packaging",
        )
        public_source = _work_order(
            order_id=public_alias_order.id,
            batch_id=None,
            department_id=sewing_department.id,
            operation="sewing",
        )
        public_target = _work_order(
            order_id=public_alias_order.id,
            batch_id=None,
            department_id=normalized_pkg_department.id,
            operation="packaging",
        )
        db.add_all([
            exact_source,
            exact_target,
            fallback_source,
            fallback_target,
            wrong_source,
            wrong_target,
            public_source,
            public_target,
        ])
        db.flush()
        db.add_all([
            SewingRecord(
                work_order_id=exact_source.id,
                production_batch_id=exact_batch.id,
                input_qty=90,
                sewn_qty=90,
                passed_qty=90,
                failed_qty=0,
                rejected_qty=0,
                rework_qty=0,
            ),
            SewingRecord(
                work_order_id=public_source.id,
                production_batch_id=None,
                input_qty=50,
                sewn_qty=50,
                passed_qty=50,
                failed_qty=0,
                rejected_qty=0,
                rework_qty=0,
            ),
            SewingRecord(
                work_order_id=fallback_source.id,
                production_batch_id=missing_target_batch.id,
                input_qty=70,
                sewn_qty=70,
                passed_qty=70,
                failed_qty=0,
                rejected_qty=0,
                rework_qty=0,
            ),
            SewingRecord(
                work_order_id=wrong_source.id,
                production_batch_id=wrong_batch.id,
                input_qty=999,
                sewn_qty=999,
                passed_qty=999,
                failed_qty=0,
                rejected_qty=0,
                rework_qty=0,
            ),
            PackagingReceipt(
                packaging_department_code="BPK",
                work_order_id=exact_target.id,
                source_work_order_id=exact_source.id,
                production_order_id=exact_order.id,
                production_batch_id=exact_batch.id,
                quantity=15,
                receive_method="manual",
            ),
        ])
        db.commit()


@pytest.mark.parametrize("q", [None, "%_", "client-alias", "public-alias", "ab"])
def test_packaging_receive_options_match_scalar_fallback_search_and_department(q):
    _mixed_receive_options()
    with TestSessionLocal() as db:
        current = db.query(User).filter(User.email == "admin@example.com").one()
        expected = _scalar_receive_options(
            db,
            current,
            q=q,
            limit=2,
            packaging_department_code="PKG",
        )
    with TestSessionLocal() as db:
        current = db.query(User).filter(User.email == "admin@example.com").one()
        before_receipts = db.query(PackagingReceipt).count()
        actual = production_routes.packaging_receive_options(
            db,
            current,
            q=q,
            limit=2,
            packaging_department_code="PKG",
        )
        assert db.query(PackagingReceipt).count() == before_receipts

    assert actual == expected


@pytest.mark.parametrize("needle", ["%_", "_", "\\"])
def test_packaging_receive_options_escapes_literal_search_before_sql_limit(needle):
    """Wildcard-looking input must not hide a later literal match behind LIMIT."""
    _mixed_receive_options()
    _receive_option_orders(25)
    with TestSessionLocal() as db:
        current = db.query(User).filter(User.email == "admin@example.com").one()
        rows = production_routes.packaging_receive_options(
            db,
            current,
            q=needle,
            limit=1,
            packaging_department_code="PKG",
        )

    assert len(rows) == 1
    assert needle in (rows[0]["model_name"] or "")


@pytest.mark.parametrize(("stored_code", "should_raise"), [
    ("", False),
    ("pkg", False),
    (" pkg ", False),
    ("\tPKG\n", False),
    ("   ", True),
    ("OTHER", True),
])
def test_packaging_receive_options_normalizes_target_department(stored_code, should_raise):
    marker = uuid4().hex[:8]
    with TestSessionLocal() as db:
        sewing_department = _department(db, "SEW")
        invalid_department = Department(
            name=f"Invalid packaging {marker}",
            code=stored_code,
        )
        model = Model(code=f"PERF18-INVALID-{marker}", name="Invalid department")
        db.add_all([invalid_department, model])
        db.flush()
        order = ProductionOrder(
            production_no=f"PERF18-INVALID-{marker}",
            production_type="branded_stock",
            model_id=model.id,
            planned_quantity=10,
            status="sewing",
        )
        db.add(order)
        db.flush()
        source = _work_order(
            order_id=order.id,
            batch_id=None,
            department_id=sewing_department.id,
            operation="sewing",
        )
        target = _work_order(
            order_id=order.id,
            batch_id=None,
            department_id=invalid_department.id,
            operation="packaging",
        )
        db.add_all([source, target])
        db.flush()
        db.add(SewingRecord(
            work_order_id=source.id,
            production_batch_id=None,
            input_qty=10,
            sewn_qty=10,
            passed_qty=10,
            failed_qty=0,
            rejected_qty=0,
            rework_qty=0,
        ))
        db.commit()

    with TestSessionLocal() as db:
        current = db.query(User).filter(User.email == "admin@example.com").one()
        if should_raise:
            with pytest.raises(HTTPException, match="Packaging department must be"):
                production_routes.packaging_receive_options(
                    db,
                    current,
                    q=None,
                    limit=10,
                    packaging_department_code="PKG",
                )
        else:
            rows = production_routes.packaging_receive_options(
                db,
                current,
                q=None,
                limit=10,
                packaging_department_code="PKG",
            )
            assert len(rows) == 1
            assert rows[0]["work_order_id"] == target.id


@pytest.fixture
def receive_options_postgres_session():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL for the PostgreSQL receive-options query")
    url = make_url(raw_url)
    if (
        url.get_backend_name() != "postgresql"
        or url.host not in {"127.0.0.1", "localhost", "::1"}
        or url.query
    ):
        pytest.fail("Receive-options PostgreSQL test requires a loopback URL without overrides")
    schema = f"packaging_receive_options_{uuid4().hex}"
    engine = create_engine(
        url,
        connect_args={"options": f"-csearch_path={schema} -cstatement_timeout=20000"},
        isolation_level="READ COMMITTED",
    )
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def test_postgres_packaging_receive_options_executes_grouped_target_query(
    receive_options_postgres_session,
):
    sessions = receive_options_postgres_session
    marker = uuid4().hex[:8]
    with sessions() as db:
        sewing_department = Department(name="Sewing", code="SEW")
        packaging_department = Department(name="Packaging", code="PKG")
        model = Model(code=f"PERF18-PG-{marker}", name="PostgreSQL receive option")
        db.add_all([sewing_department, packaging_department, model])
        db.flush()
        order = ProductionOrder(
            production_no=f"PERF18-PG-{marker}",
            production_type="branded_stock",
            model_id=model.id,
            planned_quantity=5000,
            status="sewing",
        )
        db.add(order)
        db.flush()
        expected_first = None
        for index in range(50):
            batch = ProductionBatch(
                production_order_id=order.id,
                batch_no=f"PG-{index:02d}",
                batch_index=index + 1,
                planned_quantity=30 + index,
            )
            db.add(batch)
            db.flush()
            source = _work_order(
                order_id=order.id,
                batch_id=batch.id,
                department_id=sewing_department.id,
                operation="sewing",
            )
            target = _work_order(
                order_id=order.id,
                batch_id=batch.id,
                department_id=packaging_department.id,
                operation="packaging",
            )
            db.add_all([source, target])
            db.flush()
            db.add_all([
                SewingRecord(
                    work_order_id=source.id,
                    production_batch_id=batch.id,
                    input_qty=30 + index,
                    sewn_qty=30 + index,
                    passed_qty=30 + index,
                    failed_qty=0,
                    rejected_qty=0,
                    rework_qty=0,
                ),
                PackagingReceipt(
                    packaging_department_code="BPK",
                    work_order_id=target.id,
                    source_work_order_id=source.id,
                    production_order_id=order.id,
                    production_batch_id=batch.id,
                    quantity=7,
                    receive_method="manual",
                ),
            ])
            if index == 49:
                expected_first = {
                    "work_order_id": int(target.id),
                    "source_work_order_id": int(source.id),
                    "production_batch_id": int(batch.id),
                    "batch_no": batch.batch_no,
                }
        db.commit()

        current = SimpleNamespace(
            department=None,
            role=None,
            extra_permissions=[],
            access_policy=None,
            factory_code="MIL",
        )
        statements = []

        def capture(_connection, _cursor, statement, parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append((statement, parameters))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            rows = production_routes.packaging_receive_options(
                db,
                current,
                q=None,
                limit=10,
                packaging_department_code="PKG",
            )
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

        result_sql, result_parameters = statements[-1]
        explain = db.connection().exec_driver_sql(
            f"EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) {result_sql}",
            result_parameters,
        ).scalars().all()

    assert db.bind.dialect.name == "postgresql"
    assert len(statements) == 2
    assert len(rows) == 10
    assert expected_first is not None
    assert rows[0] == {
        "work_order_id": expected_first["work_order_id"],
        "source_work_order_id": expected_first["source_work_order_id"],
        "production_order_id": order.id,
        "production_batch_id": expected_first["production_batch_id"],
        "production_no": order.production_no,
        "order_no": order.production_no,
        "model_code": model.code,
        "model_name": model.name,
        "batch_no": expected_first["batch_no"],
        "batch_name": None,
        "sewing_passed": 79,
        "received_quantity": 7,
        "available_quantity": 72,
    }
    assert any(line.lstrip().startswith("Limit") for line in explain)
    assert not any("SubPlan" in line for line in explain)
    print("PERF18 PostgreSQL EXPLAIN\n" + "\n".join(explain))
