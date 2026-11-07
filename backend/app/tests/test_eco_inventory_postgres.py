"""Real row-lock/migration gates. SQLite cannot substitute for these checks."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import os
from threading import Barrier
from uuid import uuid4
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy import create_engine, func
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from app.db.base import Base
from app.libs.dto.inventory.eco_inventory_input import FactoryFabricDispatchIn, FactoryFabricReceiptIn, EcoMaterialReceiveIn
from app.models.factory_scope_service import bind_session_factory
from app.models.idempotency_service import bind_idempotency_identity
from app.models.inventory import factory_fabric_transfers_service as transfers
from app.schemas import Item, Role, StockBatch, User, Warehouse
from app.schemas.inventory.eco_inventory import EcoMaterialBatch, EcoMaterialMovement, FactoryFabricTransferLine
from app.tests.test_eco_schema_migrations import NEW_TABLES, migration
from app.libs.dto.inventory.eco_accessory_input import EcoAccessoryPlanIn, EcoAccessoryDecisionIn, EcoAccessoryIssueIn
from app.libs.enums.eco_accessories import EcoAccessoryStatus
from app.libs.enums.production import SewingFactoryCode
from app.models.inventory import eco_accessory_service as accessories
from app.schemas import AuditLog, BrandedPlanningOrder, Bundle, Department, Model, ProductionBatch, ProductionOrder, SewingAssignment, SewingFlow, SewingRecord, WorkOrder
from app.schemas.inventory.eco_accessory import EcoAccessoryAllocation, EcoAccessoryPlan


def test_first_accessory_receipt_serializes_with_catalog_unit_edit(pg_case):
    from app.libs.dto.inventory.item_input import ItemIn
    from app.models.inventory import eco_inventory_service as eco, stock_service
    sessions, (user_id, _) = pg_case
    with sessions() as db:
        item = Item(sku="PG-ECO-UNIT", name="Race button", category="accessory", unit="pcs")
        db.add(item); db.commit(); item_id = item.id
    barrier = Barrier(2)
    def operation(receive):
        with sessions() as db:
            user = actor(db, user_id, "ECO")
            barrier.wait(timeout=10)
            try:
                if receive:
                    eco.receive_stock(db, EcoMaterialReceiveIn(request_key="first-accessory", item_id=item_id,
                        kind="accessory", batch_no="FIRST", unit="pcs", quantity="5"), user)
                else:
                    stock_service.update_item(db, item_id, ItemIn(sku="PG-ECO-UNIT", name="Race button",
                        category="accessory", unit="kg"), user)
                return True
            except HTTPException as failure:
                db.rollback()
                assert failure.status_code in {400, 409}
                return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(operation, (True, False)))
    assert sum(results) == 1
    with sessions() as db:
        stock = db.query(EcoMaterialBatch).filter_by(item_id=item_id).first()
        if stock:
            assert stock.unit == db.get(Item, item_id).unit == "pcs"
        else:
            assert db.get(Item, item_id).unit == "kg"


@pytest.fixture
def pg_case():
    raw = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw:
        pytest.skip("Real PostgreSQL ECO migration/concurrency gate needs STABILIZATION_POSTGRES_URL")
    url = make_url(raw)
    if (url.get_backend_name() != "postgresql" or url.host not in {"localhost", "127.0.0.1", "::1"}
            or url.query or not (url.database or "").endswith(("_ci", "_qa"))):
        pytest.fail("ECO concurrency gates require an explicitly disposable loopback *_ci or *_qa database")
    schema = f"eco_feature_{uuid4().hex}"
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema} -clock_timeout=10000 -cstatement_timeout=20000"}, pool_size=4, max_overflow=0)
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        Base.metadata.create_all(engine, tables=[t for t in Base.metadata.sorted_tables if t.name not in NEW_TABLES])
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                migration("0150_eco_inventory_transfers.py").upgrade()
                migration("0151_eco_accessory_approval.py").upgrade()
                migration("0154_eco_receipt_details.py").upgrade()
        sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        with sessions() as db:
            role = Role(name="Super Admin", permissions=["*"])
            warehouse = Warehouse(name="Milana test store", type="fabric_storage")
            item = Item(sku="PG-ECO-FABRIC", name="PG fabric", category="fabric", unit="kg")
            db.add_all([role, warehouse, item]); db.flush()
            user = User(email="pg-eco@example.invalid", name="PG review actor", password_hash="unused-test-hash", role_id=role.id, factory_code="MIL")
            db.add(user); db.flush()
            batch = StockBatch(item_id=item.id, batch_no="PG-ECO-B1", quantity=100, unit="kg", cost_per_unit=0, warehouse_id=warehouse.id, qc_status="passed")
            db.add(batch); db.commit()
            ids = user.id, batch.id
        yield sessions, ids
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def actor(db, user_id, factory):
    user = db.get(User, user_id)
    bind_session_factory(user, factory)
    bind_idempotency_identity(db, user)
    return user


def test_competing_dispatch_cannot_overdraw_source(pg_case):
    sessions, (user_id, batch_id) = pg_case
    barrier = Barrier(2)
    def dispatch(index):
        with sessions() as db:
            user = actor(db, user_id, "MIL")
            barrier.wait(timeout=10)
            try:
                result = transfers.dispatch(db, FactoryFabricDispatchIn(request_key=f"competing-{index}",
                    lines=[{"source_batch_id": batch_id, "quantity": "70"}]), user)
                return result.id
            except HTTPException as error:
                db.rollback()
                assert error.status_code == 409
                return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(dispatch, range(2)))
    assert sum(result is not None for result in results) == 1
    with sessions() as db:
        assert db.get(StockBatch, batch_id).quantity == Decimal("30")


@pytest.mark.parametrize("same_key", [False, True])
def test_concurrent_receipts_conserve_in_transit_stock(pg_case, same_key):
    sessions, (user_id, batch_id) = pg_case
    with sessions() as db:
        dispatch = transfers.dispatch(db, FactoryFabricDispatchIn(request_key="send",
            lines=[{"source_batch_id": batch_id, "quantity": "30"}]), actor(db, user_id, "MIL"))
        transfer_id, line_id = dispatch.id, dispatch.lines[0].id
    barrier = Barrier(2)
    def receive(index):
        with sessions() as db:
            user = actor(db, user_id, "ECO")
            barrier.wait(timeout=10)
            try:
                return transfers.receive(db, transfer_id, FactoryFabricReceiptIn(request_key="same" if same_key else f"receipt-{index}",
                    lines=[{"line_id": line_id, "quantity": "20"}]), user).id
            except HTTPException as error:
                db.rollback()
                assert error.status_code == 409
                return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(receive, range(2)))
    assert sum(result is not None for result in results) == (2 if same_key else 1)
    with sessions() as db:
        assert db.query(func.sum(EcoMaterialBatch.quantity)).scalar() == Decimal("20")
        assert db.get(FactoryFabricTransferLine, line_id).received_quantity == Decimal("20")
        assert db.query(EcoMaterialMovement).count() == 1
        assert db.get(StockBatch, batch_id).quantity == Decimal("70")


def accessory_case(sessions, user_id, *, orders=2):
    """Bootstrap only disposable rows; all accessory transitions use public services."""
    from app.models.inventory import eco_inventory_service
    with sessions() as db:
        user = actor(db, user_id, "ECO")
        department = Department(code="ECO", name="ECO approval test")
        item = Item(sku="PG-ECO-BUTTON", name="PG shared accessory", category="accessory", unit="pcs")
        db.add_all([department, item]); db.flush()
        order_ids = []
        for index in range(orders):
            model = Model(code=f"PG-ECO-MODEL-{index}", name=f"PG ECO model {index}")
            bso = BrandedPlanningOrder(order_no=f"BSO-PG-ECO-{index}", ordered_for_type="eco_cotton", ordered_for_name="ECO")
            db.add_all([model, bso]); db.flush()
            order = ProductionOrder(production_no=f"PO-PG-ECO-{index}", production_type="branded_stock",
                planning_order_id=bso.id, model_id=model.id, planned_quantity=10, status="cutting")
            db.add(order); db.flush()
            db.add(WorkOrder(production_order_id=order.id, department_id=department.id, operation="sewing",
                planned_input_qty=10, planned_output_qty=10))
            order_ids.append(order.id)
        db.commit()
        received = eco_inventory_service.receive_stock(db, EcoMaterialReceiveIn(request_key="pg-accessory-receive",
            item_id=item.id, kind="accessory", batch_no="PG-ACCESSORY-100", quantity="100"), user)
        return item.id, received.batch.id, order_ids


def pending_accessory_plan(sessions, user_id, order_id, item_id, *, quantity="70"):
    with sessions() as db:
        user = actor(db, user_id, "ECO")
        draft = accessories.save_plan(db, user, order_id, EcoAccessoryPlanIn(revision=0,
            lines=[{"item_id": item_id, "quantity": quantity}]))
        return accessories.submit_plan(db, user, order_id, EcoAccessoryDecisionIn(revision=draft.revision))


def test_factory_union_queries_and_approval_gate_keep_actual_batch_scope(pg_case):
    from app.models.inventory_service import ensure_accessories_issued_for_sewing
    sessions, (user_id, _) = pg_case
    _, stock_id, (order_id,) = accessory_case(sessions, user_id, orders=1)
    with sessions() as db:
        user = actor(db, user_id, "ECO")
        order = db.get(ProductionOrder, order_id)
        shared = Department(code="SEW", name="Shared sewing")
        eco = SewingFlow(factory_code="ECO", code="PG-ECO-LINE", name="PG ECO line")
        mil = SewingFlow(factory_code="MIL", code="PG-MIL-LINE", name="PG MIL line")
        db.add_all([shared, eco, mil]); db.flush()
        batches = [ProductionBatch(production_order_id=order.id, batch_no=f"PG-{index}", batch_index=index,
                    planned_quantity=10) for index in range(1, 5)]
        db.add_all(batches); db.flush()
        direct = db.query(WorkOrder).filter_by(production_order_id=order.id).one()
        direct.department_id = shared.id; direct.production_batch_id = batches[0].id; direct.sewing_flow_id = eco.id
        split_mil = WorkOrder(production_order_id=order.id, production_batch_id=batches[1].id,
            department_id=shared.id, operation="sewing", sewing_flow_id=eco.id, planned_output_qty=10)
        split_eco = WorkOrder(production_order_id=order.id, production_batch_id=batches[2].id,
            department_id=shared.id, operation="sewing", sewing_flow_id=mil.id, planned_output_qty=10)
        db.add_all([split_mil, split_eco]); db.flush()
        db.add_all([SewingAssignment(work_order_id=split_mil.id, production_batch_id=batches[1].id,
                                    sewing_flow_id=mil.id, quantity=10, status="planned"),
                    SewingAssignment(work_order_id=split_eco.id, production_batch_id=batches[2].id,
                                    sewing_flow_id=eco.id, quantity=10, status="in_progress"),
                    Bundle(bundle_no="PG-ECO-ALIAS", barcode="PG-ECO-ALIAS", production_order_id=order.id,
                        production_batch_id=batches[3].id, model_id=order.model_id, color="black", size="M",
                        quantity=10, sewing_factory_code=" eco cotton ", status="created")])
        db.commit()
        batch_ids = [batch.id for batch in batches]
        assert accessories.canonical_sewing_factory(" eco cotton ") is SewingFactoryCode.ECO_COTTON
        assert accessories.canonical_sewing_factory("BTX") is SewingFactoryCode.BESTTEX
        assert accessories.direct_sewing_factory(db, direct.id) is SewingFactoryCode.ECO_COTTON
        assert accessories.direct_sewing_factory(db, split_mil.id) is None
        assert accessories.direct_sewing_factory(db, split_eco.id) is None
        assert db.query(ProductionOrder.id).filter(ProductionOrder.id == order.id, accessories.eco_order_condition()).scalar() == order.id
        assert accessories.accessory_gate_factories(db, order.id, batch_ids[0]) == {SewingFactoryCode.ECO_COTTON}
        assert accessories.accessory_gate_factories(db, order.id, batch_ids[1]) == {SewingFactoryCode.MILANA}
        assert accessories.accessory_gate_factories(db, order.id, batch_ids[2]) == {SewingFactoryCode.ECO_COTTON}
        assert accessories.accessory_gate_factories(db, order.id, batch_ids[3]) == {SewingFactoryCode.ECO_COTTON}
        assert set(db.scalars(accessories.sewing_assignment_work_ids({SewingFactoryCode.ECO_COTTON}, batch_ids[0]))) == {direct.id}
        assert set(db.scalars(accessories.sewing_assignment_work_ids({SewingFactoryCode.ECO_COTTON}, batch_ids[1]))) == set()
        assert set(db.scalars(accessories.sewing_assignment_work_ids({SewingFactoryCode.ECO_COTTON}, batch_ids[2]))) == {split_eco.id}
        for batch_id in (batch_ids[0], batch_ids[2], batch_ids[3]):
            with pytest.raises(HTTPException, match="approvalRequired"):
                ensure_accessories_issued_for_sewing(db, order.id, production_batch_id=batch_id)
            expected_blocked = {direct.id} if batch_id == batch_ids[0] else {split_eco.id} if batch_id == batch_ids[2] else set()
            assert {work.id for work in db.query(WorkOrder).filter_by(production_order_id=order.id) if work.is_blocked} == expected_blocked
            db.rollback()
        assert ensure_accessories_issued_for_sewing(db, order.id, production_batch_id=batch_ids[1])["is_complete"]
        assert not db.get(WorkOrder, split_mil.id).is_blocked
        draft = accessories.save_plan(db, user, order.id, EcoAccessoryPlanIn(revision=0, lines=[]))
        pending = accessories.submit_plan(db, user, order.id, EcoAccessoryDecisionIn(revision=draft.revision))
        accessories.approve_plan(db, user, order.id, EcoAccessoryDecisionIn(revision=pending.revision))
        for batch_id in batch_ids:
            assert ensure_accessories_issued_for_sewing(db, order.id, production_batch_id=batch_id)["is_complete"]
        assert db.get(EcoMaterialBatch, stock_id).quantity == 100
        assert db.get(EcoMaterialBatch, stock_id).reserved_quantity == 0
        assert db.query(EcoAccessoryAllocation).count() == db.query(SewingRecord).count() == 0


def test_competing_model_approvals_cannot_overallocate_accessories(pg_case):
    sessions, (user_id, milana_batch_id) = pg_case
    item_id, stock_id, order_ids = accessory_case(sessions, user_id)
    plans = [pending_accessory_plan(sessions, user_id, order_id, item_id) for order_id in order_ids]
    barrier = Barrier(2)
    def approve(index):
        with sessions() as db:
            user = actor(db, user_id, "ECO")
            barrier.wait(timeout=10)
            try:
                return accessories.approve_plan(db, user, order_ids[index],
                    EcoAccessoryDecisionIn(revision=plans[index].revision)).production_order_id
            except HTTPException as failure:
                db.rollback()
                assert failure.status_code == 409 and failure.detail == "ecoAccessories.shortage"
                return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(approve, range(2)))
    assert sum(result is not None for result in results) == 1
    with sessions() as db:
        stock = db.get(EcoMaterialBatch, stock_id)
        assert (stock.quantity, stock.reserved_quantity) == (Decimal("100"), Decimal("70"))
        allocations = db.query(EcoAccessoryAllocation).all()
        assert len(allocations) == 1 and allocations[0].quantity == 70 and allocations[0].issued_quantity == 0
        persisted = db.query(EcoAccessoryPlan).order_by(EcoAccessoryPlan.production_order_id).all()
        assert sorted(plan.status for plan in persisted) == [EcoAccessoryStatus.APPROVED.value, EcoAccessoryStatus.PENDING.value]
        for index, plan in enumerate(persisted):
            assert plan.revision == plans[index].revision + (1 if plan.status == EcoAccessoryStatus.APPROVED else 0)
        assert db.query(EcoMaterialMovement).filter_by(kind="issue").count() == 0
        assert db.get(StockBatch, milana_batch_id).quantity == 100
        assert all(order.planned_quantity == 10 for order in db.query(ProductionOrder))
        assert all(work.actual_input_qty == work.actual_output_qty == 0 for work in db.query(WorkOrder))


@pytest.mark.parametrize("same_key", [False, True])
def test_concurrent_approved_accessory_issue_deducts_once(pg_case, same_key):
    sessions, (user_id, milana_batch_id) = pg_case
    item_id, stock_id, (order_id,) = accessory_case(sessions, user_id, orders=1)
    pending = pending_accessory_plan(sessions, user_id, order_id, item_id)
    with sessions() as db:
        approved = accessories.approve_plan(db, actor(db, user_id, "ECO"), order_id,
            EcoAccessoryDecisionIn(revision=pending.revision))
    allocation_id = approved.lines[0].allocations[0].id
    payload = EcoAccessoryIssueIn(revision=approved.revision, lines=[{"allocation_id": allocation_id, "quantity": "70"}])
    barrier = Barrier(2)
    def issue(index):
        with sessions() as db:
            user = actor(db, user_id, "ECO")
            barrier.wait(timeout=10)
            try:
                result = accessories.issue_plan(db, user, order_id, payload, "pg-issue-same" if same_key else f"pg-issue-{index}")
                return result.model_dump(mode="json")
            except HTTPException as failure:
                db.rollback()
                assert not same_key and failure.status_code == 409 and failure.detail == "ecoAccessories.stale"
                return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(issue, range(2)))
    success = [result for result in results if result is not None]
    assert len(success) == (2 if same_key else 1)
    if same_key: assert success[0] == success[1]
    with sessions() as db:
        stock = db.get(EcoMaterialBatch, stock_id)
        allocation = db.get(EcoAccessoryAllocation, allocation_id)
        plan = db.get(EcoAccessoryPlan, approved.id)
        assert (stock.quantity, stock.reserved_quantity) == (Decimal("30"), Decimal("0"))
        assert allocation.quantity == allocation.issued_quantity == 70
        assert plan.status == EcoAccessoryStatus.ISSUED and plan.revision == approved.revision + 1
        movements = db.query(EcoMaterialMovement).filter_by(kind="issue").all()
        assert len(movements) == 1 and movements[0].quantity == 70
        assert (movements[0].reference_type, movements[0].reference_id, movements[0].production_order_id) == ("EcoAccessoryPlan", plan.id, order_id)
        assert db.query(EcoMaterialMovement).filter_by(kind="receive").one().quantity - movements[0].quantity == stock.quantity
        assert stock.reserved_quantity == allocation.quantity - allocation.issued_quantity
        assert db.query(AuditLog).filter_by(action="issue", entity_type="EcoAccessoryPlan").count() == 1
        assert db.get(StockBatch, milana_batch_id).quantity == 100
        assert db.query(SewingRecord).count() == 0
        assert db.get(ProductionOrder, order_id).planned_quantity == 10
        assert all(work.actual_input_qty == work.actual_output_qty == 0 for work in db.query(WorkOrder))
