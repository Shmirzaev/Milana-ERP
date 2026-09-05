from app.models import WorkOrder
from app.tests.conftest import TestSessionLocal


def test_branded_history_uses_cutting_progress_across_all_productions(client, auth_headers):
    created = client.post("/api/planning/branded-orders", json={}, headers=auth_headers)
    assert created.status_code == 201
    group_id = created.json()["id"]

    def history():
        response = client.get("/api/planning/branded-orders", headers=auth_headers)
        assert response.status_code == 200
        return next(row for row in response.json() if row["id"] == group_id)

    assert history()["cutting_status"] == "not_started"
    production_ids = []
    for _ in range(2):
        response = client.post("/api/planning/create-branded-production", headers=auth_headers, json={
            "planning_order_id": group_id,
            "production_type": "branded_stock",
            "model_id": 1,
            "planned_quantity": 24,
            "items": [{"model_id": 1, "color": "white", "size": "M", "planned_quantity": 24}],
        })
        assert response.status_code == 201, response.text
        production_ids.append(response.json()["id"])
    assert history()["cutting_status"] == "not_started"

    def set_cutting(index, status, quantity):
        with TestSessionLocal() as db:
            work = db.query(WorkOrder).filter(
                WorkOrder.production_order_id == production_ids[index],
                WorkOrder.operation == "cutting",
            ).one()
            work.status = status
            work.actual_output_qty = quantity
            db.commit()

    set_cutting(0, "in_progress", 12)
    assert history()["cutting_status"] == "partial"
    assert history()["productions"][0]["cutting_status"] == "partial"
    set_cutting(0, "completed", 24)
    result = history()
    assert result["cutting_status"] == "partial"
    assert [row["cutting_status"] for row in result["productions"]] == ["completed", "not_started"]
    set_cutting(1, "completed", 24)
    assert history()["cutting_status"] == "completed"
    # Downstream status does not determine whether Cutting is finished.
    assert all(row["status"] != "completed" for row in history()["productions"])
    set_cutting(1, "in_progress", 0)
    assert history()["cutting_status"] == "partial"
    set_cutting(0, "cancelled", 24)
    assert history()["cutting_status"] == "not_started"


def test_branded_history_requires_authentication(client):
    assert client.get("/api/planning/branded-orders").status_code == 401
