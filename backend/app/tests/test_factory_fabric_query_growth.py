"""Real ORM query-growth and legacy read parity for factory fabric transfers."""
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.inventory import factory_fabric_transfers_service as service
from app.models.inventory_service import available_reservation_item_capacity, reserved_stock_for_batch
from app.schemas import Item, Role, StockBatch, User, Warehouse
from app.schemas.inventory.eco_inventory import FactoryFabricTransfer, FactoryFabricTransferLine
from app.tests.test_eco_inventory_postgres import pg_case as pg_case


@pytest.mark.parametrize("distinct", [False, True])
def test_factory_reads_growth_and_parity(distinct):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    with sessions() as db:
        role = Role(name="factory growth", permissions=["*"])
        actor = User(name="reader", email="reader@synthetic.invalid", password_hash="unused", role=role, factory_code="MIL")
        db.add(actor)
        db.flush()
        for i in range(50):
            if i == 0 or distinct:
                item = Item(sku=f"factory-{i}", name=f"fabric {i}", category="fabric", unit="kg", default_cost=0, reorder_level=0)
                warehouse = Warehouse(name=f"warehouse {i}", type="fabric_storage")
                operator = User(name=f"operator {i}", email=f"operator{i}@synthetic.invalid", password_hash="unused", role=role, factory_code="MIL")
                db.add_all([item, warehouse, operator])
                db.flush()
            batch = StockBatch(item_id=item.id, warehouse_id=warehouse.id, batch_no=f"batch-{i}", quantity=Decimal("100"), unit="kg", cost_per_unit=0, qc_status="passed")
            transfer = FactoryFabricTransfer(dispatched_by=operator.id)
            db.add_all([batch, transfer])
            db.flush()
            if i % 3:
                db.add(FactoryFabricTransferLine(transfer_id=transfer.id, source_batch_id=batch.id, item_id=item.id,
                    item_name=item.name, batch_no=batch.batch_no, unit="kg", quantity=Decimal("1"), received_quantity=Decimal("0")))
        db.commit()
        actor_id = actor.id
    counts = {"source": [], "list": []}
    for size in (1, 10, 50):
        with sessions() as db:
            actor = db.get(User, actor_id)
            # Load authorization before counting; both services still execute their checks.
            _ = actor.role.permissions
            for name, call in (("source", lambda: service.source_batches(db, actor, limit=size)),
                               ("list", lambda: service.list_transfers(db, actor, limit=size))):
                statements = []
                def capture(_conn, _cursor, statement, _params, _context, _many):
                    if statement.lstrip().upper().startswith("SELECT"):
                        statements.append(statement)
                event.listen(engine, "before_cursor_execute", capture)
                try:
                    actual = call()
                finally:
                    event.remove(engine, "before_cursor_execute", capture)
                counts[name].append(len(statements))
                assert len(actual) == size
                if name == "list":
                    transfers = db.query(FactoryFabricTransfer).order_by(FactoryFabricTransfer.id.desc()).limit(size).all()
                    expected = [service.transfer_output(db, transfer).model_dump(mode="json") for transfer in transfers]
                    assert [row.model_dump(mode="json") for row in actual] == expected
                else:
                    for row in actual:
                        batch = db.get(StockBatch, row.id)
                        expected = min(Decimal(batch.quantity) - Decimal(str(reserved_stock_for_batch(db, batch.id))),
                            Decimal(str(available_reservation_item_capacity(db, batch.item_id, batch.warehouse_id))).quantize(Decimal("0.0001")))
                        assert row.available_quantity == max(Decimal(0), expected)
    assert max(counts["source"]) <= min(counts["source"]) + 1
    assert max(counts["list"]) <= min(counts["list"]) + 1
    engine.dispose()


def test_source_mixed_claims_movements_and_filters():
    from datetime import datetime, timezone
    from app.schemas import EcoFabricRoll, MaterialReservation, ProductionOrder, StockMovement

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    with sessions() as db:
        role = Role(name="mixed", permissions=["*"])
        actor = User(name="reader", email="mixed@synthetic.invalid", password_hash="unused", role=role, factory_code="MIL")
        item = Item(sku="mixed", name="Blue cotton", category="fabric", unit="kg", default_cost=0, reorder_level=0)
        first = Warehouse(name="first", type="fabric_storage")
        second = Warehouse(name="second", type="fabric_storage")
        db.add_all([actor, item, first, second])
        db.flush()
        batches = []
        for i in range(6):
            batch = StockBatch(item_id=item.id, warehouse_id=(first.id if i != 1 else second.id),
                batch_no=f"MIX-{i}", color=None, quantity=Decimal("10"), unit="kg", cost_per_unit=0,
                qc_status="pending" if i == 2 else "passed",
                archived_at=datetime(2026, 1, 1, tzinfo=timezone.utc) if i == 3 else None)
            batches.append(batch)
            db.add(batch)
        db.flush()
        standard = ProductionOrder(production_no="standard-mixed", production_type="client_order", model_id=1)
        usluga = ProductionOrder(production_no="usluga-mixed", production_type="client_order", model_id=1,
                                 source_type="usluga", fabric_batch_id=batches[4].id)
        db.add_all([standard, usluga])
        db.flush()
        for i, (status, warehouse, batch, reserved, consumed, released) in enumerate([
            ("reserved", None, None, 7, 0, 0),
            ("partially_consumed", first.id, batches[0].id, 5, 1, 1),
            ("reserved", second.id, None, Decimal("2.1250"), 0, 0),
            ("cancelled", first.id, None, 9, 0, 0),
            ("released", first.id, None, 9, 0, 9),
            ("consumed", first.id, None, 9, 9, 0),
        ]):
            db.add(MaterialReservation(reservation_no=f"mixed-{i}", production_order_id=standard.id,
                item_id=item.id, warehouse_id=warehouse, stock_batch_id=batch,
                reserved_quantity=reserved, consumed_quantity=consumed, released_quantity=released,
                status=status, unit="kg"))
        for kind, source, target, quantity in [
            ("produce", None, first.id, 4), ("issue", first.id, None, 2),
            ("transfer", first.id, second.id, 3), ("return", None, None, 1),
            ("produce", None, None, Decimal("0.1250")), ("issue", None, None, Decimal("0.1250")),
        ]:
            db.add(StockMovement(item_id=item.id, movement_type=kind, from_warehouse_id=source,
                                 to_warehouse_id=target, quantity=quantity, unit="kg"))
        # Batch-linked movements are already reflected in the batch balance.
        db.add(StockMovement(item_id=item.id, batch_id=batches[0].id, movement_type="issue",
                             from_warehouse_id=first.id, quantity=Decimal("8.1234"), unit="kg"))
        db.add(EcoFabricRoll(dispatch_id=1, batch_id=batches[5].id, roll_number=1,
                             fabric_name=item.name, batch_no=batches[5].batch_no,
                             quantity=1, unit="kg"))
        db.commit()
        actor_id, eligible_ids = actor.id, [batches[1].id, batches[0].id]
    with sessions() as db:
        actor = db.get(User, actor_id)
        rows = service.source_batches(db, actor)
        assert [row.id for row in rows] == eligible_ids
        assert [row.available_quantity for row in rows] == [Decimal("10"), Decimal("7")]
        assert all(row.color is None for row in rows)
        for row in rows:
            batch = db.get(StockBatch, row.id)
            expected = min(Decimal(batch.quantity) - Decimal(str(reserved_stock_for_batch(db, batch.id))),
                Decimal(str(available_reservation_item_capacity(db, batch.item_id, batch.warehouse_id))).quantize(Decimal("0.0001")))
            assert row.available_quantity == max(Decimal(0), expected)
        # One fresh statement matches the legacy aggregates, including after an earlier line changes stock.
        from app.models.inventory.line_availability_service import line_availability
        from app.models.inventory_service import available_stock_for_item
        for warehouse_id in (None, 1, 2):
            batch = db.get(StockBatch, eligible_ids[0])
            for _ in range(2):
                statements = []
                def capture_line(_conn, _cursor, statement, _params, _context, _many):
                    if statement.lstrip().upper().startswith("SELECT"):
                        statements.append(statement)
                event.listen(engine, "before_cursor_execute", capture_line)
                try:
                    reserved, capacity = line_availability(db, batch.id, batch.item_id, warehouse_id, global_capacity=True)
                finally:
                    event.remove(engine, "before_cursor_execute", capture_line)
                assert len(statements) == 1
                assert reserved == reserved_stock_for_batch(db, batch.id)
                assert capacity == available_reservation_item_capacity(db, batch.item_id, warehouse_id)
                _, local = line_availability(db, batch.id, batch.item_id, warehouse_id, global_capacity=False)
                assert local == available_stock_for_item(db, batch.item_id, warehouse_id)
                batch.quantity -= Decimal("0.125")
                db.flush()
        assert [r.id for r in service.source_batches(db, actor, offset=1, limit=1)] == eligible_ids[1:]
        assert [r.id for r in service.source_batches(db, actor, q="  MIX-0  ")] == eligible_ids[1:]
        assert service.source_batches(db, actor, q="missing") == []
        fractional_item = Item(sku="fractional", name="fractional fabric", category="fabric", unit="kg", default_cost=0, reorder_level=0)
        db.add(fractional_item)
        db.flush()
        fractional_batch = StockBatch(item_id=fractional_item.id, warehouse_id=1, batch_no="FRACTIONAL",
                                      quantity=Decimal("1.2345"), unit="kg", cost_per_unit=0, qc_status="passed")
        db.add(fractional_batch)
        db.flush()
        db.add(MaterialReservation(reservation_no="fractional", production_order_id=1, item_id=fractional_item.id,
                                   warehouse_id=None, reserved_quantity=Decimal("0.1111"), unit="kg", status="reserved"))
        db.flush()
        fractional_rows = service.source_batches(db, actor, q="FRACTIONAL")
        assert len(fractional_rows) == 1
        assert fractional_rows[0].available_quantity == Decimal("1.1234")
        legacy = available_reservation_item_capacity(db, fractional_item.id, fractional_batch.warehouse_id)
        assert fractional_rows[0].available_quantity == Decimal(str(legacy)).quantize(Decimal("0.0001"))
        actor.role.permissions = []
        with pytest.raises(HTTPException) as denied:
            service.source_batches(db, actor)
        assert denied.value.status_code == 403
        actor.role.permissions = ["*"]
        actor.factory_code = "ECO"
        with pytest.raises(HTTPException) as wrong_factory:
            service.source_batches(db, actor)
        assert wrong_factory.value.status_code == 403
    engine.dispose()


@pytest.mark.parametrize("distinct", [False, True])
def test_dispatch_batches_custody_reads_and_replay(distinct):
    from app.libs.dto.inventory.eco_inventory_input import FactoryFabricDispatchIn
    from app.models.idempotency_service import bind_idempotency_identity
    from app.schemas import StockMovement

    custody_counts = []
    for size in (1, 10, 50):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        sessions = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
        with sessions() as db:
            role = Role(name="dispatch", permissions=["*"])
            actor = User(name="sender", email="sender@synthetic.invalid", password_hash="unused", role=role, factory_code="MIL")
            db.add(actor)
            db.flush()
            ids = []
            for i in range(size):
                if i == 0 or distinct:
                    item = Item(sku=f"dispatch-{i}", name=f"fabric {i}", category="fabric", unit="kg", default_cost=0, reorder_level=0)
                    warehouse = Warehouse(name=f"warehouse {i}", type="fabric_storage")
                    db.add_all([item, warehouse])
                    db.flush()
                batch = StockBatch(item_id=item.id, warehouse_id=warehouse.id, batch_no=f"dispatch-{i}",
                                   quantity=Decimal("10"), unit="kg", cost_per_unit=0, qc_status="passed")
                db.add(batch)
                db.flush()
                ids.append(batch.id)
            db.commit()
            actor_id = actor.id
        with sessions() as db:
            actor = db.get(User, actor_id)
            bind_idempotency_identity(db, actor)
            payload = FactoryFabricDispatchIn(request_key=f"dispatch-{size}", lines=[
                {"source_batch_id": batch_id, "quantity": "1"} for batch_id in reversed(ids)])
            custody_statements = []
            availability_statements = []
            def capture(_conn, _cursor, statement, _params, _context, _many):
                if statement.lstrip().upper().startswith("SELECT") and "FROM eco_fabric_rolls" in statement:
                    custody_statements.append(statement)
                if " AS scoped_in" in statement:
                    availability_statements.append(statement)
            event.listen(engine, "before_cursor_execute", capture)
            try:
                result = service.dispatch(db, payload, actor)
            finally:
                event.remove(engine, "before_cursor_execute", capture)
            custody_counts.append(len(custody_statements))
            assert len(availability_statements) == size
            assert [line.source_batch_id for line in result.lines] == ids
            assert all(line.quantity == Decimal("1") for line in result.lines)
            assert all(db.get(StockBatch, batch_id).quantity == Decimal("9") for batch_id in ids)
            assert db.query(StockMovement).filter_by(reference_type="FactoryFabricTransfer").count() == size
            assert service.dispatch(db, payload, actor).model_dump(mode="json") == result.model_dump(mode="json")
            assert db.query(StockMovement).filter_by(reference_type="FactoryFabricTransfer").count() == size
        engine.dispose()
    assert custody_counts == [1, 1, 1]


def test_dispatch_custody_refusal_preserves_guard_order_and_rolls_back():
    from app.libs.dto.inventory.eco_inventory_input import FactoryFabricDispatchIn
    from app.models.idempotency_service import bind_idempotency_identity
    from app.schemas import EcoFabricRoll, StockMovement

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    with sessions() as db:
        role = Role(name="dispatch refusal", permissions=["*"])
        actor = User(name="sender", email="refusal@synthetic.invalid", password_hash="unused", role=role, factory_code="MIL")
        item = Item(sku="refusal", name="fabric", category="fabric", unit="kg", default_cost=0, reorder_level=0)
        warehouse = Warehouse(name="refusal warehouse", type="fabric_storage")
        db.add_all([actor, item, warehouse])
        db.flush()
        first = StockBatch(item_id=item.id, warehouse_id=warehouse.id, batch_no="first", quantity=10,
                           unit="kg", cost_per_unit=0, qc_status="pending")
        second = StockBatch(item_id=item.id, warehouse_id=warehouse.id, batch_no="second", quantity=10,
                            unit="kg", cost_per_unit=0, qc_status="passed")
        db.add_all([first, second])
        db.flush()
        db.add(EcoFabricRoll(dispatch_id=1, batch_id=second.id, roll_number=1, fabric_name="fabric",
                             batch_no="second", quantity=1, unit="kg"))
        db.commit()
        actor_id, first_id, second_id = actor.id, first.id, second.id
    with sessions() as db:
        actor = db.get(User, actor_id)
        bind_idempotency_identity(db, actor)
        payload = FactoryFabricDispatchIn(request_key="refusal", lines=[
            {"source_batch_id": first_id, "quantity": "1"},
            {"source_batch_id": second_id, "quantity": "1"}])
        with pytest.raises(HTTPException) as first_error:
            service.dispatch(db, payload, actor)
        assert first_error.value.detail == "Fabric must pass quality inspection before dispatch to ECO COTTON"
        db.rollback()
        db.get(StockBatch, first_id).qc_status = "passed"
        db.commit()
        with pytest.raises(HTTPException) as second_error:
            service.dispatch(db, payload, actor)
        assert second_error.value.detail == "Return outstanding fabric through the existing Eco custody register first"
        db.rollback()
        assert db.query(FactoryFabricTransfer).count() == 0
        assert db.query(StockMovement).count() == 0
        assert [db.get(StockBatch, batch_id).quantity for batch_id in (first_id, second_id)] == [Decimal("10"), Decimal("10")]
    engine.dispose()


def test_dispatch_line_availability_rechecks_committed_stock_in_transaction(pg_case):
    from app.models.inventory.line_availability_service import line_availability

    sessions, (_, source_id) = pg_case
    with sessions.begin() as db:
        source = db.get(StockBatch, source_id)
        unrelated = StockBatch(
            item_id=source.item_id,
            warehouse_id=source.warehouse_id,
            batch_no="PG-SHARED-CAPACITY",
            quantity=Decimal("25"),
            unit="kg",
            qc_status="passed",
        )
        db.add(unrelated)
        db.flush()
        unrelated_id = unrelated.id

    with sessions.begin() as dispatch_db:
        source = dispatch_db.query(StockBatch).filter_by(id=source_id).with_for_update(of=StockBatch).one()
        args = (source.id, source.item_id, source.warehouse_id)
        assert line_availability(dispatch_db, *args, global_capacity=True) == (0.0, 125.0)
        source.quantity = Decimal("80")
        dispatch_db.flush()

        with sessions.begin() as other_db:
            other_db.get(StockBatch, unrelated_id).quantity = Decimal("5")

        assert line_availability(dispatch_db, *args, global_capacity=True) == (0.0, 85.0)
        assert available_reservation_item_capacity(dispatch_db, source.item_id, source.warehouse_id) == 85.0
