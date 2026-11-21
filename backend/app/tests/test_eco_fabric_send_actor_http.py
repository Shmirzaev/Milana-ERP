"""Characterize authorized cross-actor replay and factory refusal for Eco send."""

from uuid import uuid4

from app.core.security import create_access_token
from app.schemas import AuditLog, EcoFabricDispatch, EcoFabricRoll, Item, Role, StockBatch, StockMovement, User, Warehouse
from app.tests.test_eco_fabric_send_query_growth import custody_api  # noqa: F401


def test_send_cross_actor_replay_and_factory_refusal(custody_api):
    client, headers, sessions, _ = custody_api
    with sessions.begin() as db:
        role = db.query(Role).one()
        other = User(name="Second MIL operator", email="second-mil@synthetic.invalid", password_hash="synthetic",
                     role=role, factory_code="MIL")
        item, warehouse = db.query(Item).one(), db.query(Warehouse).one()
        batch = StockBatch(item_id=item.id, warehouse_id=warehouse.id, batch_no="ACTOR-REPLAY", quantity=2,
                           piece_count=2, roll_weights_kg=[1, 1], unit="kg", cost_per_unit=0)
        db.add_all([other, batch])
        db.flush()
        other_headers = {"Authorization": f"Bearer {create_access_token(other.id, {'factory_code': 'MIL'})}"}
        batch_id = batch.id
    route = "/api/eco-fabric-transfers/send"
    body = {"codes": [f"B{batch_id}-R1"], "request_key": str(uuid4())}
    original = client.post(route, headers=headers["MIL"], json=body)
    assert original.status_code == 200, original.text
    replay = client.post(route, headers=other_headers, json=body)
    assert replay.status_code == 200 and replay.json() == original.json()
    changed = client.post(route, headers=other_headers, json={**body, "codes": [f"B{batch_id}-R2"]})
    assert changed.status_code == 409 and changed.json()["detail"] == "ecoTransfers.changedRequest"
    denied = client.post(route, headers=headers["ECO"], json=body)
    assert denied.status_code == 403 and denied.json()["detail"] == "ecoTransfers.milanaOnly"
    with sessions() as db:
        dispatch = db.query(EcoFabricDispatch).filter_by(request_key=body["request_key"]).one()
        assert dispatch.operator_name == original.json()["operator_name"]
        assert db.get(StockBatch, batch_id).quantity == 1
        assert db.query(EcoFabricRoll).filter_by(dispatch_id=dispatch.id).count() == 1
        assert db.query(StockMovement).filter_by(reference_type="EcoFabricDispatch", reference_id=dispatch.id).count() == 1
        assert db.query(AuditLog).filter_by(entity_type="EcoFabricDispatch", entity_id=dispatch.id, action="send").count() == 1
