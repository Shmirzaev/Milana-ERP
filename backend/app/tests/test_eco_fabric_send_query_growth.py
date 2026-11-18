from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.eco_transfers import router
from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import get_db
from app.schemas import EcoFabricDispatch, EcoFabricRoll, Item, Role, StockBatch, StockMovement, User, Warehouse


@pytest.fixture
def custody_api():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    with sessions.begin() as db:
        role = Role(name="Custody regression", permissions=["inventory.eco_transfers"])
        users = [User(name=f"Custody {factory}", email=f"custody-{factory.lower()}@synthetic.invalid",
                      password_hash="synthetic", role=role, factory_code=factory) for factory in ("MIL", "ECO")]
        db.add_all(users)
        db.flush()
        headers = {user.factory_code: {"Authorization": f"Bearer {create_access_token(user.id, {'factory_code': user.factory_code})}"}
                   for user in users}
        db.add_all([Warehouse(name="Custody warehouse", type="fabric_storage"),
                    Item(sku="CUSTODY-SHARED", name="Shared fabric", category="fabric", unit="kg")])

    def owned_session():
        with sessions() as db:
            yield db

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_db] = owned_session
    try:
        with TestClient(app) as client:
            yield client, headers, sessions, engine
    finally:
        engine.dispose()


@pytest.mark.parametrize("size", [1, 10, 50])
@pytest.mark.parametrize("distinct", [False, True])
def test_send_custody_read_growth(custody_api, size, distinct):
    client, headers, sessions, engine = custody_api
    with sessions() as db:
        warehouse = db.query(Warehouse).first()
        if distinct:
            batches = []
            for n in range(size):
                item = Item(sku=f"CUSTODY-{n}", name=f"Custody {n}", category="fabric", unit="kg")
                db.add(item)
                db.flush()
                batch = StockBatch(item_id=item.id, warehouse_id=warehouse.id, batch_no=f"CUSTODY-{n}",
                                   quantity=2, piece_count=1, roll_weights_kg=[1], unit="kg", cost_per_unit=0)
                db.add(batch)
                db.flush()
                batches.append(batch.id)
            codes = [f"B{bid}-R1" for bid in batches]
        else:
            item = db.query(Item).filter_by(category="fabric").first()
            batch = StockBatch(item_id=item.id, warehouse_id=warehouse.id, batch_no="CUSTODY-SHARED",
                               quantity=size + 1, piece_count=size, roll_weights_kg=[1] * size,
                               unit="kg", cost_per_unit=0)
            db.add(batch)
            db.flush()
            batches = [batch.id]
            codes = [f"B{batch.id}-R{n}" for n in range(1, size + 1)]
        db.commit()

    custody_reads = []
    availability_reads = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        sql = statement.lower()
        if " as scoped_in" in sql:
            availability_reads.append(statement)
        if (sql.lstrip().startswith("select") and "from eco_fabric_rolls" in sql
                and "returned_at is null" in sql and "group by" not in sql):
            custody_reads.append(statement)

    body_in = {"codes": codes, "request_key": str(uuid4())}
    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = client.post("/api/eco-fabric-transfers/send", headers=headers["MIL"], json=body_in)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sent_rolls"] == size
    assert float(body["sent_kg"]) == size
    assert [row["code"] for row in body["rows"]] == codes
    assert len(custody_reads) == 1
    assert len(availability_reads) == size
    replay = client.post("/api/eco-fabric-transfers/send", headers=headers["MIL"], json=body_in)
    assert replay.status_code == 200 and replay.json() == body
    with sessions() as db:
        assert db.query(EcoFabricRoll).filter(EcoFabricRoll.batch_id.in_(batches)).count() == size
        assert db.query(StockMovement).filter_by(reference_type="EcoFabricDispatch", reference_id=body["id"]).count() == size
        assert sum(float(db.get(StockBatch, bid).quantity) for bid in batches) == (size if distinct else 1)


def test_send_factory_refusals_and_late_failure_roll_back(custody_api):
    client, headers, sessions, _ = custody_api
    with sessions.begin() as db:
        warehouse = db.query(Warehouse).one()
        item = db.query(Item).one()
        batch = StockBatch(item_id=item.id, warehouse_id=warehouse.id, batch_no="CUSTODY-ROLLBACK",
                           quantity=1, piece_count=2, roll_weights_kg=[1, 1], unit="kg", cost_per_unit=0)
        db.add(batch)
        db.flush()
        batch_id = batch.id

    route = "/api/eco-fabric-transfers/send"
    body = {"codes": [f"B{batch_id}-R1", f"B{batch_id}-R2"], "request_key": str(uuid4())}
    assert client.post(route, json=body).status_code == 401
    assert client.post(route, headers=headers["ECO"], json=body).status_code == 403
    response = client.post(route, headers=headers["MIL"], json=body)
    assert response.status_code == 409 and response.json()["detail"] == "ecoTransfers.unavailable"
    with sessions() as db:
        assert db.get(StockBatch, batch_id).quantity == 1
        assert db.query(EcoFabricDispatch).count() == 0
        assert db.query(EcoFabricRoll).count() == 0
        assert db.query(StockMovement).count() == 0
