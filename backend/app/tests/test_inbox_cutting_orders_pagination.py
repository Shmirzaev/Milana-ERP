"""CUT/ECT inbox cards page before expensive card context hydration."""

from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import event

from app.api.routes import inbox
from app.models import Department, Model, ProductionBatch, ProductionOrder, WorkOrder
from app.tests.conftest import TestSessionLocal, test_engine


def _enable_inbox_access(monkeypatch):
    monkeypatch.setattr(inbox, "require_operational_department_access", lambda *_args: None)
    monkeypatch.setattr(inbox, "user_permissions", lambda _user: ["*"])


def test_cutting_order_page_has_exact_total_and_sql_row_limit(monkeypatch):
    _enable_inbox_access(monkeypatch)
    suffix = uuid4().hex[:8].upper()
    with TestSessionLocal() as db:
        department = db.query(Department).filter_by(code="CUT").one()
        model = Model(code=f"CUT-PAGE-{suffix}", name="Cutting inbox page model")
        db.add(model)
        db.flush()
        production_order = ProductionOrder(
            production_no=f"CUT-PAGE-{suffix}",
            production_type="client_order",
            model_id=model.id,
            status="new",
            planned_quantity=401,
        )
        db.add(production_order)
        db.flush()
        batches = [
            ProductionBatch(
                production_order_id=production_order.id,
                batch_no=f"B{index + 1:04d}",
                batch_index=index + 1,
                planned_quantity=1,
            )
            for index in range(401)
        ]
        db.add_all(batches)
        db.flush()
        db.add_all([
            WorkOrder(
                production_order_id=production_order.id,
                production_batch_id=batch.id,
                department_id=department.id,
                operation="cutting",
                status="pending",
                planned_output_qty=1,
            )
            for batch in batches
        ])
        db.commit()

    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(" ".join(statement.lower().split()))

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        with TestSessionLocal() as db:
            first = inbox.cutting_order_page(db, SimpleNamespace(department_id=None), dept="CUT")
            second = inbox.cutting_order_page(db, SimpleNamespace(department_id=None), dept="CUT", offset=50)
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)

    assert first["total"] == second["total"] == 401
    assert len(first["rows"]) == len(second["rows"]) == 50
    assert first["has_more"] and second["has_more"]
    assert {row["id"] for row in first["rows"]}.isdisjoint(row["id"] for row in second["rows"])
    assert all(row["production_order_id"] == production_order.id for row in first["rows"])
    work_order_selects = [
        statement for statement in statements
        if " from work_orders " in statement and " join production_orders " in statement
        and " limit ? offset ?" in statement
    ]
    assert len(work_order_selects) == 2
    assert not any(statement.startswith(("insert", "update", "delete")) for statement in statements)


def test_cutting_order_page_preserves_auth_and_legacy_inbox(client, auth_headers):
    path = "/api/inbox/cutting-orders?dept=CUT"
    assert client.get(path).status_code == 401
    assert client.get(f"{path}&limit=101", headers=auth_headers).status_code == 422
    assert client.get(f"{path}&offset=-1", headers=auth_headers).status_code == 422
    assert client.get("/api/inbox/cutting-orders?dept=SEW", headers=auth_headers).status_code == 404
    page = client.get(f"{path}&limit=1", headers=auth_headers)
    assert page.status_code == 200, page.text
    assert page.json()["limit"] == 1
    legacy = client.get("/api/inbox?dept=CUT", headers=auth_headers)
    assert legacy.status_code == 200, legacy.text
    assert "cutting_work_orders" in legacy.json()


def test_cutting_search_matches_displayed_fields_before_paging_and_keeps_latest_passport(client, auth_headers):
    from datetime import datetime, timezone
    from app.models import BrandedPlanningOrder, CuttingPassport, Item, ModelBOM
    marker = uuid4().hex[:8]
    with TestSessionLocal() as db:
        department = db.query(Department).filter_by(code="CUT").one()
        model = Model(code=f"UNSEARCHABLE-{marker}", name="Футболка",
                      details_json={"general": {"modelNo": "Model Needle", "variantNo": "27"}})
        other_model = Model(code=f"UNRELATED-{marker}", name="Other")
        plan = BrandedPlanningOrder(order_no=f"PLAN-{marker}", ordered_for_type="milana", ordered_for_name="Client Alpha")
        unselected = Item(sku=f"UNSELECTED-{marker}", name="Not displayed", category="fabric", unit="kg")
        selected = Item(sku=f"COTTON-BLUE-{marker}", name="Chosen fabric", category="fabric", unit="kg", image_url="/chosen.png")
        db.add_all([model, other_model, plan, unselected, selected]); db.flush()
        db.add_all([ModelBOM(model_id=model.id, item_id=item.id, quantity_per_piece=1, unit="kg")
                    for item in [unselected, selected]])
        target = ProductionOrder(production_no=f"MATCH-{marker}", production_type="branded_stock", model_id=model.id,
                                 planning_order_id=plan.id, planned_quantity=3, status="new")
        unrelated = ProductionOrder(production_no=f"OTHER-{marker}", production_type="branded_stock",
                                    model_id=other_model.id, planned_quantity=60, status="new")
        db.add_all([target, unrelated]); db.flush()
        targets = [WorkOrder(production_order_id=target.id, department_id=department.id, operation="cutting",
                             status="pending", planned_output_qty=1) for _ in range(3)]
        db.add_all(targets); db.flush()
        db.add_all([WorkOrder(production_order_id=unrelated.id, department_id=department.id, operation="cutting",
                              status="pending", planned_output_qty=1) for _ in range(60)])
        db.add(WorkOrder(production_order_id=target.id, department_id=department.id, operation="cutting", status="cancelled"))
        passports = [CuttingPassport(passport_no=f"PASS-{marker}-{index}", date=datetime.now(timezone.utc),
                                    production_order_id=target.id) for index in range(2)]
        db.add_all(passports); db.commit()
        target_ids = sorted([row.id for row in targets], reverse=True)
        latest_passport_id = passports[-1].id

    # The matching cards are beyond the initial unfiltered page.
    initial = client.get("/api/inbox/cutting-orders?dept=CUT&limit=50", headers=auth_headers)
    assert initial.status_code == 200
    assert not set(target_ids).intersection(row["id"] for row in initial.json()["rows"])
    for phrase in ["needle", "V-27", "ФУТБОЛКА", "alpha cotton-blue", "chosen needle"]:
        response = client.get("/api/inbox/cutting-orders", params={"dept": "CUT", "q": phrase, "limit": 2, "offset": 1}, headers=auth_headers)
        assert response.status_code == 200, response.text
        page = response.json()
        assert page["total"] == 3 and not page["has_more"]
        assert [row["id"] for row in page["rows"]] == target_ids[1:]
        assert all(row["cutting_passport_id"] == latest_passport_id for row in page["rows"])
    for absent in ["unsearchable", "unselected", "%", "alpha missing"]:
        response = client.get("/api/inbox/cutting-orders", params={"dept": "CUT", "q": absent}, headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["total"] == 0 and response.json()["rows"] == []
    core = client.get("/api/inbox/department-orders?dept=CUT&limit=100", headers=auth_headers)
    assert core.status_code == 200, core.text
    assert all(row["cutting_passport_id"] == latest_passport_id for row in core.json()["rows"] if row.get("id") in target_ids)


def test_cutting_pages_enforce_stage_and_selected_factory(client):
    from app.core.security import create_access_token
    from app.models import Role, User
    with TestSessionLocal() as db:
        role = Role(name="Cutting paging reader", permissions=["cutting.records"])
        denied_role = Role(name="No cutting paging", permissions=["storage.packages"])
        db.add_all([role, denied_role]); db.flush()
        actor = User(name="Cutting reader", email="cutting-page@example.invalid", password_hash="unused", role_id=role.id, factory_code="MIL")
        denied = User(name="No cutting", email="no-cutting-page@example.invalid", password_hash="unused", role_id=denied_role.id, factory_code="MIL")
        db.add_all([actor, denied]); db.commit()
        allowed_headers = {"Authorization": f"Bearer {create_access_token(actor.id, {'factory_code': 'MIL'})}"}
        denied_headers = {"Authorization": f"Bearer {create_access_token(denied.id, {'factory_code': 'MIL'})}"}
    for path in ["cutting-orders", "department-orders"]:
        assert client.get(f"/api/inbox/{path}?dept=CUT", headers=allowed_headers).status_code == 200
        assert client.get(f"/api/inbox/{path}?dept=ECT", headers=allowed_headers).status_code == 403
        assert client.get(f"/api/inbox/{path}?dept=CUT", headers=denied_headers).status_code == 403


def test_paged_eco_cutting_keeps_open_usluga_after_partial_handoff(client):
    from app.tests.test_usluga import _login_eco, _create_usluga_order
    _login_eco(client)
    _, order = _create_usluga_order(client, quantity=12)
    with TestSessionLocal() as db:
        production = db.get(ProductionOrder, order["id"])
        cutting = db.query(WorkOrder).filter_by(production_order_id=production.id, operation="cutting").one()
        sewing = db.query(WorkOrder).filter_by(production_order_id=production.id, operation="sewing").one()
        production.status = "sewing"
        cutting.status = sewing.status = "in_progress"
        sewing.actual_input_qty = 5
        cutting_id = cutting.id
        db.commit()
    for endpoint in ["department-orders", "cutting-orders"]:
        response = client.get(f"/api/inbox/{endpoint}?dept=ECT")
        assert response.status_code == 200, response.text
        assert cutting_id in {row["id"] for row in response.json()["rows"]}
