from datetime import date

import pytest

from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import SessionLocal
from app.models import Bundle, Department, ProductionBatch, ProductionOrder, Role, SewingAssignment, SewingDailyReport, SewingFlow, User, WorkOrder
from app.services.sewing_band_setup import BAND_PERMISSIONS, configure_eco_bands


@pytest.fixture
def bands():
    with SessionLocal() as db:
        dept = db.query(Department).filter(Department.code == "ECO").one()
        role = Role(name="Band test", permissions=BAND_PERMISSIONS)
        db.add(role); db.flush()
        flows, users, jobs, bundles = [], [], [], []
        for n in (1, 2):
            flow = SewingFlow(factory_code="ECO", code=f"TEST-BAND-{n}", name=f"Test band {n}")
            db.add(flow); db.flush(); flows.append(flow.id)
            user = User(name=f"Test band {n}", email=f"testband{n}@example.com", password_hash=hash_password("Fixture!123456"), factory_code="ECO", role_id=role.id, department_id=dept.id, sewing_band_id=flow.id)
            db.add(user); db.flush(); users.append(user.id)
            po = ProductionOrder(production_no=f"BAND-TEST-{n}", production_type="branded_stock", model_id=1, planned_quantity=100, status="in_progress")
            db.add(po); db.flush()
            wo = WorkOrder(production_order_id=po.id, department_id=dept.id, operation="sewing", status="in_progress", planned_input_qty=100, planned_output_qty=100, sewing_flow_id=flow.id)
            db.add(wo); db.flush()
            assignment = SewingAssignment(work_order_id=wo.id, sewing_flow_id=flow.id, quantity=100)
            db.add(assignment); db.flush(); jobs.append((wo.id, assignment.id, po.id))
            bundle = Bundle(bundle_no=f"BAND-BUNDLE-{n}", barcode=f"BAND-BAR-{n}", production_order_id=po.id, model_id=1, color="white", size="M", quantity=100, sewing_factory_code="ECO", next_department_id=dept.id, status="created")
            db.add(bundle); db.flush(); bundles.append(bundle.id)
        admin_id = db.query(User.id).filter(User.email == "admin@example.com").scalar()
        db.commit()
    return {"flows": flows, "users": users, "jobs": jobs, "bundles": bundles,
            "headers": [{"Authorization": "Bearer " + create_access_token(uid, {"factory_code": "ECO"})} for uid in users],
            "admin": {"Authorization": "Bearer " + create_access_token(admin_id, {"factory_code": "ECO"})}}


def report_body(bands, n=0, qty=40, **changes):
    return {"report_date": date.today().isoformat(), "sewing_flow_id": bands["flows"][n],
            "work_order_id": bands["jobs"][n][0], "sewing_assignment_id": bands["jobs"][n][1],
            "sewn_qty": qty, **changes}


@pytest.mark.parametrize("path", ["/api/work-orders", "/api/inbox?dept=ECO", "/api/production-orders", "/api/bundles/lookup?code=BAND-BAR-2", "/api/sewing-flows", "/api/users", "/api/search?q=test", "/api/payroll/records"])
def test_band_cannot_bypass_workspace_through_legacy_routes(client, bands, path):
    assert client.get(path, headers=bands["headers"][0]).status_code == 403


def test_reports_scoped_and_progress_never_credits_production(client, bands):
    h = bands["headers"][0]
    own = client.post("/api/sewing-daily-reports", json=report_body(bands), headers=h)
    assert own.status_code == 201, own.text
    other = client.post("/api/sewing-daily-reports", json=report_body(bands, 1), headers=h)
    assert other.status_code == 403
    client.post("/api/sewing-daily-reports", json=report_body(bands, 1), headers=bands["headers"][1])
    rows = client.get("/api/sewing-daily-reports", headers=h).json()["rows"]
    assert len(rows) == 1 and rows[0]["id"] == own.json()["id"]
    for route in ("", "/export.xlsx", "/export.pdf", "/line-context"):
        assert client.get(f"/api/sewing-daily-reports{route}?sewing_flow_id={bands['flows'][1]}", headers=h).status_code == 403
    done = client.post("/api/sewing-daily-reports", json=report_body(bands, qty=60), headers=h)
    assert done.status_code == 201, done.text
    board = client.get("/api/sewing-bands", headers=h).json()
    assert len(board) == 1 and len(board[0]["jobs"]) == 1
    job = board[0]["jobs"][0]
    assert job["reported_qty"] == 100 and job["line_finished"] and job["awaiting_final"]
    assert client.get(f"/api/sewing-daily-reports/line-context?sewing_flow_id={bands['flows'][0]}", headers=h).json()["active_work_orders"] == []
    with SessionLocal() as db:
        wo = db.get(WorkOrder, bands["jobs"][0][0]); assignment = db.get(SewingAssignment, bands["jobs"][0][1])
        assert (wo.passed_qty, wo.actual_output_qty, assignment.completed_qty) == (0, 0, 0)
        assert assignment.status == "planned"
    corrected = client.patch(f"/api/sewing-daily-reports/{done.json()['id']}", json={"report_date": date.today().isoformat(), "sewn_qty": 30}, headers=h)
    assert corrected.status_code == 200, corrected.text
    assert not client.get("/api/sewing-bands", headers=h).json()[0]["jobs"][0]["line_finished"]
    assert len(client.get(f"/api/sewing-daily-reports/line-context?sewing_flow_id={bands['flows'][0]}", headers=h).json()["active_work_orders"]) == 1
    assert client.patch(f"/api/sewing-daily-reports/{done.json()['id']}", json={"report_date": date.today().isoformat(), "sewn_qty": 20}, headers=bands["headers"][1]).status_code == 403
    assert client.delete(f"/api/sewing-daily-reports/{done.json()['id']}", headers=bands["headers"][1]).status_code == 403


def test_erp_floor_contains_only_owned_assignments_and_own_quantities(client, bands):
    with SessionLocal() as db:
        # A shared work order's totals must not leak into a band's floor quantity.
        db.get(WorkOrder, bands["jobs"][0][0]).passed_qty = 70
        db.get(SewingAssignment, bands["jobs"][0][1]).quantity = 40
        db.get(Bundle, bands["bundles"][0]).status = "received_sewing"
        db.commit()
    response = client.get("/api/sewing-bands/orders?sewing_flow_id=" + str(bands["flows"][1]), headers=bands["headers"][0])
    assert response.status_code == 200, response.text
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["work_order_id"] == bands["jobs"][0][0]
    assert rows[0]["sewing_assignment_id"] == bands["jobs"][0][1]
    assert rows[0]["planned_output_qty"] == 40 and rows[0]["passed_qty"] == 0
    assert rows[0]["received_qty"] == 40
    assert "model_image_url" in rows[0] and "material_image_url" in rows[0]
    assert client.get("/api/sewing-bands/orders", headers=bands["admin"]).status_code == 403


def test_two_piece_progress_counts_pairs_across_days(client, bands):
    h = bands["headers"][0]
    for top, bottom in ((100, 0), (0, 60)):
        r = client.post("/api/sewing-daily-reports", json=report_body(bands, qty=top + bottom, top_qty=top, bottom_qty=bottom), headers=h)
        assert r.status_code == 201, r.text
    job = client.get("/api/sewing-bands", headers=h).json()[0]["jobs"][0]
    assert job["reported_qty"] == 60 and not job["line_finished"]
    over = client.post("/api/sewing-daily-reports", json=report_body(bands, qty=41, top_qty=0, bottom_qty=41), headers=h)
    assert over.status_code == 400


def test_receipt_is_automatic_repeat_safe_and_rejects_other_band(client, bands):
    h = bands["headers"][0]
    before = client.post("/api/sewing-bands/receive", json={"code": "BAND-BAR-2"}, headers=h)
    assert before.status_code == 409, before.text
    response = client.post("/api/sewing-bands/receive", json={"code": "BAND-BAR-1"}, headers=h)
    assert response.status_code == 200, response.text
    assert response.json()["received_count"] == 1
    again = client.post("/api/sewing-bands/receive", json={"code": "BAND-BAR-1"}, headers=h)
    assert again.status_code == 200 and again.json()["already_accepted"]
    with SessionLocal() as db:
        assert db.get(Bundle, bands["bundles"][0]).status == "received_sewing"
        assert db.get(Bundle, bands["bundles"][1]).status == "created"
        assert db.get(SewingAssignment, bands["jobs"][0][1]).quantity == 100


def test_unassigned_manual_receipt_claims_only_own_band(client, bands):
    wid, aid, poid = bands["jobs"][0]
    with SessionLocal() as db:
        db.delete(db.get(SewingAssignment, aid)); db.get(WorkOrder, wid).sewing_flow_id = None; db.commit()
    r = client.post("/api/sewing-bands/receive", json={"production_order_id": poid}, headers=bands["headers"][0])
    assert r.status_code == 200, r.text
    job = client.get("/api/sewing-bands", headers=bands["headers"][0]).json()[0]["jobs"][0]
    assert job["quantity"] == 100 and job["work_order_id"] == wid
    assert client.post("/api/sewing-bands/receive", json={"code": "BAND-BAR-1"}, headers=bands["headers"][1]).status_code == 409


def test_manager_short_finish_and_reopen_preserve_output(client, bands):
    aid = bands["jobs"][0][1]
    body = {"reason": "Cutting shortfall"}
    assert client.post(f"/api/sewing-bands/{aid}/finish", json=body, headers=bands["headers"][0]).status_code == 403
    r = client.post(f"/api/sewing-bands/{aid}/finish", json=body, headers=bands["admin"])
    assert r.status_code == 200, r.text
    job = client.get("/api/sewing-bands", headers=bands["headers"][0]).json()[0]["jobs"][0]
    assert job["line_finished"] and job["actual_qty"] == 0
    r = client.post(f"/api/sewing-bands/{aid}/finish", json={**body, "finished": False}, headers=bands["admin"])
    assert r.status_code == 200
    assert not client.get("/api/sewing-bands", headers=bands["headers"][0]).json()[0]["jobs"][0]["line_finished"]


def test_final_output_is_only_explicit_and_cannot_cross_band(client, bands):
    wid, aid, _ = bands["jobs"][0]
    body = {"work_order_id": wid, "sewing_assignment_id": aid, "input_qty": 0, "sewn_qty": 25, "passed_qty": 25}
    assert client.post(f"/api/sewing-bands/{aid}/output", json=body, headers=bands["headers"][1]).status_code == 404
    receive = client.post("/api/sewing-bands/receive", json={"code": "BAND-BAR-1"}, headers=bands["headers"][0])
    assert receive.status_code == 200, receive.text
    headers = {**bands["headers"][0], "Idempotency-Key": "final-output-retry"}
    r = client.post(f"/api/sewing-bands/{aid}/output", json=body, headers=headers)
    assert r.status_code == 200, r.text
    repeated = client.post(f"/api/sewing-bands/{aid}/output", json=body, headers=headers)
    assert repeated.status_code == 200 and repeated.json() == r.json()
    with SessionLocal() as db:
        assert db.get(WorkOrder, wid).passed_qty == 25
        assert db.get(SewingAssignment, aid).completed_qty == 25
        assert db.query(SewingDailyReport).count() == 0


def test_setup_preserves_history_and_password_on_retry(bands):
    with SessionLocal() as db:
        for n in range(1, 21):
            if not db.query(SewingFlow).filter(SewingFlow.code == f"ECO-BAND-{n:02}", SewingFlow.factory_code == "ECO").first():
                db.add(SewingFlow(code=f"ECO-BAND-{n:02}", name=f"{n}-Band", factory_code="ECO"))
        db.flush()
        # Fixture-only test lines are not part of production provisioning.
        for fid in bands["flows"]:
            db.get(SewingFlow, fid).is_active = False
        actor = db.query(User).filter(User.email == "admin@example.com").one()
        result = configure_eco_bands(db, actor, "Fixture!123456", apply=True)
        assert len(result["create"]) == 10
        assert db.query(SewingFlow).filter(SewingFlow.factory_code == "ECO", SewingFlow.is_active.is_(True)).count() == 10
        configure_eco_bands(db, actor, "Different!123456", apply=True)
        user = db.query(User).filter(User.email == "band1@milanapremium.uz").one()
        assert verify_password("Fixture!123456", user.password_hash)
        assert db.query(SewingAssignment).count() >= 2
        db.rollback()


def test_daily_report_network_retry_does_not_double_count(client, bands):
    h = {**bands["headers"][0], "Idempotency-Key": "daily-report-retry"}
    first = client.post("/api/sewing-daily-reports", json=report_body(bands), headers=h)
    repeat = client.post("/api/sewing-daily-reports", json=report_body(bands), headers=h)
    assert first.status_code == repeat.status_code == 201
    assert first.json()["id"] == repeat.json()["id"]
    assert client.get("/api/sewing-bands", headers=h).json()[0]["jobs"][0]["reported_qty"] == 40


@pytest.mark.parametrize("url", [False, True])
def test_batch_scanner_formats_auto_assign_to_own_band(client, bands, url):
    wid, aid, poid = bands["jobs"][0]
    with SessionLocal() as db:
        batch = ProductionBatch(production_order_id=poid, batch_no="B01", batch_index=1, planned_quantity=100)
        db.add(batch); db.flush(); bid = batch.id
        db.get(Bundle, bands["bundles"][0]).production_batch_id = bid
        db.get(SewingAssignment, aid).production_batch_id = bid
        db.commit()
    code = f"https://erp.milanapremium.uz/bundles/scan/sewing?batch={bid}" if url else f"SEWING_BATCH:{bid}"
    r = client.post("/api/sewing-bands/receive", json={"code": code}, headers=bands["headers"][0])
    assert r.status_code == 200, r.text
    assert r.json()["received_count"] == 1


def test_other_factory_bundle_and_inactive_band_are_blocked(client, bands):
    with SessionLocal() as db:
        db.get(Bundle, bands["bundles"][0]).sewing_factory_code = "MIL"
        db.commit()
    r = client.post("/api/sewing-bands/receive", json={"code": "BAND-BAR-1"}, headers=bands["headers"][0])
    assert r.status_code == 403
    with SessionLocal() as db:
        db.get(SewingFlow, bands["flows"][0]).is_active = False
        db.commit()
    assert client.get("/api/sewing-bands", headers=bands["headers"][0]).status_code == 403
