from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from fastapi.encoders import jsonable_encoder
import pytest

from app.api.routes.eco_transfers import dispatch_data
from app.models import EcoFabricDispatch, EcoFabricRoll, StockBatch, User
from app.tests.conftest import TestSessionLocal
from app.tests.test_fabric_scans import fabric_batch  # noqa: F401
from app.tests.test_package_query_growth import _captured_get


@pytest.fixture
def history(fabric_batch):
    ids = []
    with TestSessionLocal() as db:
        actor = db.query(User).first()
        batch = db.get(StockBatch, fabric_batch)
        batch.piece_count = 100
        batch.roll_weights_kg = [1, 2] * 50
        batch.quantity = 100
        for index in range(50):
            dispatch = EcoFabricDispatch(
                request_key=str(uuid4()), created_by=actor.id, operator_name=f"Dispatcher {index}",
                sent_at=datetime(2026, 9, 1 + index % 2, tzinfo=timezone.utc),
                remaining_inventory=[{"note": "historical snapshot", "padding": "x" * 1000}],
            )
            db.add(dispatch)
            db.flush()
            ids.append(dispatch.id)
            for part in range(2):
                db.add(EcoFabricRoll(
                    dispatch_id=dispatch.id, batch_id=batch.id, roll_number=index * 2 + part + 1,
                    fabric_name="Synthetic fabric", batch_no=batch.batch_no, color="Blue",
                    quantity=Decimal(part + 1), unit="kg",
                    returned_at=datetime(2026, 9, 3, tzinfo=timezone.utc) if part else None,
                    return_operator_name="Returning operator" if part else None,
                ))
        db.commit()
    return ids


def test_eco_history_query_count_does_not_grow_per_dispatch(client, auth_headers, history):
    counts = []
    for size in (1, 10, 50):
        response, statements = _captured_get(client, auth_headers, f"/api/eco-fabric-transfers?page_size={size}")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 50 and len(body["items"]) == size
        assert body["outstanding_rolls"] == 50 and float(body["outstanding_kg"]) == 50
        counts.append(len(statements))
    print(f"Eco history SELECTs for 1/10/50 dispatches: {counts}")
    assert counts == [5, 5, 5], counts


def test_eco_history_keeps_payload_order_date_and_global_totals(client, auth_headers, history):
    with TestSessionLocal() as db:
        dispatches = db.query(EcoFabricDispatch).order_by(EcoFabricDispatch.sent_at.desc(), EcoFabricDispatch.id.desc()).all()
        expected = jsonable_encoder([dispatch_data(db, row) for row in dispatches])
        snapshots = {row.id: row.remaining_inventory for row in dispatches}
    response = client.get("/api/eco-fabric-transfers?page=2&page_size=10", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()["items"] == expected[10:20]
    dated = client.get("/api/eco-fabric-transfers?report_date=2026-09-02&page_size=100", headers=auth_headers)
    assert dated.json()["total"] == 25
    assert dated.json()["items"] == expected[:25]
    assert dated.json()["outstanding_rolls"] == 50  # Existing all-date custody total.
    for item in response.json()["items"]:
        assert (item["sent_rolls"], item["outstanding_rolls"]) == (2, 1)
        assert [row["id"] for row in item["rows"]] == sorted(row["id"] for row in item["rows"])
        assert (float(item["sent_kg"]), float(item["outstanding_kg"])) == (3, 1)
    with TestSessionLocal() as db:
        assert {row.id: row.remaining_inventory for row in db.query(EcoFabricDispatch)} == snapshots


def test_eco_history_handles_empty_pages_and_childless_dispatch(client, auth_headers, history):
    response, statements = _captured_get(client, auth_headers, "/api/eco-fabric-transfers?page=7&page_size=10")
    assert response.status_code == 200 and response.json()["items"] == []
    assert len(statements) == 4
    with TestSessionLocal() as db:
        dispatch = EcoFabricDispatch(request_key=str(uuid4()), created_by=db.query(User.id).first()[0],
                                     operator_name="Empty", sent_at=datetime(2026, 9, 4, tzinfo=timezone.utc))
        db.add(dispatch)
        db.commit()
        dispatch_id = dispatch.id
    body = client.get("/api/eco-fabric-transfers?page_size=1", headers=auth_headers).json()
    item = body["items"][0]
    assert item["id"] == dispatch_id and item["rows"] == []
    assert item["sent_rolls"] == item["outstanding_rolls"] == item["sent_kg"] == item["outstanding_kg"] == 0
    assert client.get("/api/eco-fabric-transfers?page_size=101", headers=auth_headers).status_code == 422
