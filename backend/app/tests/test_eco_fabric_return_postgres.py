"""Eco return against a guarded, migrated, disposable PostgreSQL database."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.libs.dto.inventory.eco_fabric_transfer_input import ReturnIn
from app.models import audit_service
from app.models.inventory.transfers_service import eco_return_fabric
from app.schemas import AuditLog, EcoFabricDispatch, EcoFabricRoll, Item, StockBatch, StockMovement, User, Warehouse
from app.tests.pg_approved_instance import (
    ApprovedInstanceUnavailable, create_target_database, finalize_target,
    load_approved_instance, require_or_skip, target_engine,
)

Sessions = sessionmaker(autoflush=False, expire_on_commit=False)


@pytest.fixture(scope="module")
def return_pg_engine():
    try:
        instance = load_approved_instance()
    except ApprovedInstanceUnavailable as error:
        require_or_skip(error)
    target = create_target_database(instance)
    engine = None
    try:
        engine = target_engine(target, options="-cstatement_timeout=20000 -clock_timeout=10000")
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(settings, "DATABASE_URL", engine.url.render_as_string(hide_password=False).replace("%", "%%"))
            patch.setattr(sa, "engine_from_config", lambda *args, **kwargs: engine)
            command.upgrade(Config(str(Path(__file__).resolve().parents[2] / "alembic.ini")), "head")
        Sessions.configure(bind=engine)
        yield engine
    finally:
        Sessions.configure(bind=None)
        finalize_target(target, engine)


@pytest.fixture
def pg_return(return_pg_engine):
    token = uuid4().hex
    with Sessions.begin() as db:
        user = User(name="Return operator", email=token + "@example.invalid", password_hash="unused")
        item = Item(sku=token, name="Fabric", category="fabric", unit="kg")
        warehouse = Warehouse(name=token, type="fabric_storage")
        db.add_all([user, item, warehouse]); db.flush()
        batch = StockBatch(item_id=item.id, warehouse_id=warehouse.id, batch_no=token,
                           quantity=0, piece_count=1, roll_weights_kg=[15], unit="kg", cost_per_unit=0,
                           archived_at=datetime.now(timezone.utc), archived_by=user.id)
        dispatch = EcoFabricDispatch(request_key=str(uuid4()), created_by=user.id,
                                     operator_name=user.name, remaining_inventory=[{"snapshot": token}])
        db.add_all([batch, dispatch]); db.flush()
        row = EcoFabricRoll(dispatch_id=dispatch.id, batch_id=batch.id, roll_number=1,
                            fabric_name=item.name, batch_no=batch.batch_no, quantity=15, unit="kg")
        db.add(row); db.flush()
        return {"user": user.id, "batch": batch.id, "dispatch": dispatch.id,
                "row": row.id, "snapshot": [{"snapshot": token}], "key": str(uuid4())}


def do_return(case):
    with Sessions() as db:
        return eco_return_fabric(db, ReturnIn(code=f'B{case["batch"]}-R1',
            dispatch_id=case["dispatch"], request_key=case["key"]), db.get(User, case["user"]))


def assert_return(case, expected):
    with Sessions() as db:
        batch = db.get(StockBatch, case["batch"])
        row = db.get(EcoFabricRoll, case["row"])
        movements = db.query(StockMovement).filter_by(reference_type="EcoFabricReturn", reference_id=row.id).all()
        audits = db.query(AuditLog).filter_by(entity_type="EcoFabricRoll", entity_id=row.id, action="return").all()
        assert db.get(EcoFabricDispatch, case["dispatch"]).remaining_inventory == case["snapshot"]
        assert batch.roll_weights_kg == [15] and batch.piece_count == 1
        if expected:
            assert batch.quantity == Decimal("15") and batch.archived_at is None and batch.archived_by is None
            assert row.return_key == case["key"] and row.returned_by == case["user"] and row.returned_at
            assert len(movements) == len(audits) == 1 and audits[0].entry_hash
            assert movements[0].movement_type == "return" and movements[0].quantity == Decimal("15")
        else:
            assert batch.quantity == 0 and batch.archived_at and batch.archived_by == case["user"]
            assert row.returned_at is None and row.return_key is None
            assert not movements and not audits


def test_postgres_finalized_audit_failure_rolls_back_then_retry(pg_return, monkeypatch):
    original = audit_service._finalize_postgres_audits
    def fail_after_finalization(db):
        original(db)
        db.flush()
        assert db.get(EcoFabricRoll, pg_return["row"]).returned_at
        assert db.query(StockMovement).filter_by(reference_type="EcoFabricReturn", reference_id=pg_return["row"]).count() == 1
        assert db.query(AuditLog).filter_by(entity_type="EcoFabricRoll", entity_id=pg_return["row"]).one().entry_hash
        raise RuntimeError("injected after audit finalization")
    with monkeypatch.context() as patch:
        patch.setattr(audit_service, "_finalize_postgres_audits", fail_after_finalization)
        with pytest.raises(RuntimeError, match="injected after audit"):
            do_return(pg_return)
    assert_return(pg_return, False)
    do_return(pg_return)
    assert_return(pg_return, True)


def test_postgres_same_key_concurrent_return_replays_once(pg_return):
    barrier = Barrier(2)
    def run(_):
        barrier.wait(timeout=10)
        return do_return(pg_return)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert results[0] == results[1]
    assert_return(pg_return, True)
