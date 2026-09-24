from __future__ import annotations

from uuid import uuid4

from sqlalchemy import event

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import (
    FinishedGoodsStock,
    Model,
    Role,
    SalesOrder,
    SalesOrderItem,
    User,
)
from app.services.forecasting import (
    _branded_demand_groups,
    _branded_stock_analysis,
    branded_stock_suggestions,
)
from app.tests.conftest import TestSessionLocal


def _insert_factory_demand_rows() -> dict[str, int]:
    db = TestSessionLocal()
    try:
        marker = uuid4().hex[:8].upper()
        model_ids: dict[str, int] = {}
        for factory_code in ("MIL", "BST", "ECO", None):
            label = factory_code or "UNASSIGNED"
            model = Model(
                code=f"FC-FORECAST-{label}-{marker}",
                name=f"Forecast {label} {marker}",
                factory_code=factory_code,
                status="approved",
            )
            db.add(model)
            db.flush()
            model_ids[label] = int(model.id)

            stock = FinishedGoodsStock(
                model_id=model.id,
                color=f"{label}-{marker}",
                size="M",
                quantity=0,
                available_qty=0,
                reserved_qty=0,
                sold_qty=0,
                cost_per_piece=0,
                selling_price=0,
                status="available",
            )
            order = SalesOrder(
                order_no=f"FC-FORECAST-{label}-{marker}",
                order_type="branded_stock_sale",
                status="ready",
                total_amount=100,
            )
            db.add_all([stock, order])
            db.flush()
            db.add(
                SalesOrderItem(
                    sales_order_id=order.id,
                    model_id=model.id,
                    finished_goods_stock_id=stock.id,
                    color=stock.color,
                    size=stock.size,
                    quantity=100,
                    unit_price=1,
                    source_type="from_stock",
                )
            )
        db.commit()
        return model_ids
    finally:
        db.close()


def _forecast_view_headers(*, extra_permissions=(), super_admin: bool = False) -> dict[str, str]:
    marker = uuid4().hex[:8]
    with SessionLocal() as db:
        permissions = ["forecasting.view"]
        if super_admin:
            permissions.extend(["*", "admin.super"])
        role = Role(
            name=f"Forecast scope {marker}",
            permissions=permissions,
        )
        db.add(role)
        db.flush()
        user = User(
            name=f"Forecast scope {marker}",
            email=f"forecast-scope-{marker}@example.invalid",
            password_hash="unused-forecast-scope-hash",
            role_id=role.id,
            factory_code="MIL",
            extra_permissions=list(extra_permissions),
            is_active=True,
        )
        db.add(user)
        db.commit()
        token = create_access_token(int(user.id), {"factory_code": "MIL"})
    return {"Authorization": f"Bearer {token}"}


def test_branded_suggestions_api_scopes_secondary_factory_grants(client):
    model_ids = _insert_factory_demand_rows()
    headers = _forecast_view_headers(extra_permissions=["factory:ECO:forecasting.view"])

    response = client.get("/api/forecasting/branded-stock-suggestions", headers=headers)

    assert response.status_code == 200, response.text
    visible_model_ids = {row["model_id"] for row in response.json()}
    assert model_ids["MIL"] in visible_model_ids
    assert model_ids["ECO"] in visible_model_ids
    assert model_ids["BST"] not in visible_model_ids
    assert model_ids["UNASSIGNED"] not in visible_model_ids


def test_branded_suggestions_api_super_admin_sees_all_attributed_factories(client):
    model_ids = _insert_factory_demand_rows()
    headers = _forecast_view_headers(super_admin=True)

    response = client.get("/api/forecasting/branded-stock-suggestions", headers=headers)

    assert response.status_code == 200, response.text
    visible_model_ids = {row["model_id"] for row in response.json()}
    assert visible_model_ids.issuperset({model_ids["MIL"], model_ids["BST"], model_ids["ECO"]})
    assert model_ids["UNASSIGNED"] not in visible_model_ids


def test_branded_forecast_scope_filters_factories_and_unassigned_models():
    model_ids = _insert_factory_demand_rows()
    db = TestSessionLocal()
    try:
        expected = {
            "MIL": {model_ids["MIL"]},
            "BST": {model_ids["BST"]},
            "ECO": {model_ids["ECO"]},
        }
        for factory_code, expected_ids in expected.items():
            groups = _branded_demand_groups(db, factory_codes=[factory_code])
            assert {key[0] for key in groups} == expected_ids

            suggestions = branded_stock_suggestions(db, factory_codes=[factory_code])
            assert {row["model_id"] for row in suggestions} == expected_ids

        all_factory_groups = _branded_demand_groups(
            db,
            factory_codes=("MIL", "BST", "ECO"),
        )
        assert {key[0] for key in all_factory_groups} == {
            model_ids["MIL"],
            model_ids["BST"],
            model_ids["ECO"],
        }
        assert model_ids["UNASSIGNED"] not in {key[0] for key in all_factory_groups}
    finally:
        db.close()


def test_branded_forecast_none_scope_preserves_global_direct_service_behavior():
    model_ids = _insert_factory_demand_rows()
    db = TestSessionLocal()
    try:
        groups = _branded_demand_groups(db)
        assert {key[0] for key in groups} == set(model_ids.values())

        suggestions = branded_stock_suggestions(db)
        assert {row["model_id"] for row in suggestions} == set(model_ids.values())
    finally:
        db.close()


def test_branded_factory_scope_adds_no_select_round_trips():
    _insert_factory_demand_rows()
    db = TestSessionLocal()
    try:
        select_counts = []
        for factory_codes in (None, ("MIL",)):
            statements = []

            def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
                if statement.lstrip().upper().startswith("SELECT"):
                    statements.append(statement)

            event.listen(db.bind, "before_cursor_execute", capture)
            try:
                _branded_stock_analysis(db, factory_codes=factory_codes)
            finally:
                event.remove(db.bind, "before_cursor_execute", capture)
            select_counts.append(len(statements))

        assert select_counts[0] == select_counts[1]
    finally:
        db.close()


def test_scoped_branded_sales_can_resolve_factory_through_finished_stock_reference():
    db = TestSessionLocal()
    try:
        marker = uuid4().hex[:8].upper()
        model = Model(
            code=f"FC-FORECAST-STOCK-REF-{marker}",
            name=f"Forecast stock reference {marker}",
            factory_code="ECO",
            status="approved",
        )
        db.add(model)
        db.flush()
        stock = FinishedGoodsStock(
            model_id=model.id,
            color=f"STOCK-REF-{marker}",
            size="L",
            quantity=0,
            available_qty=0,
            reserved_qty=0,
            sold_qty=0,
            cost_per_piece=0,
            selling_price=0,
            status="available",
        )
        order = SalesOrder(
            order_no=f"FC-FORECAST-STOCK-REF-{marker}",
            order_type="branded_stock_sale",
            status="ready",
            total_amount=75,
        )
        db.add_all([stock, order])
        db.flush()
        db.add(
            SalesOrderItem(
                sales_order_id=order.id,
                model_id=None,
                finished_goods_stock_id=stock.id,
                color=stock.color,
                size=stock.size,
                quantity=75,
                unit_price=1,
                source_type="from_stock",
            )
        )
        db.commit()

        groups = _branded_demand_groups(db, factory_codes=("ECO",))
        assert len(groups) == 1
        assert next(iter(groups))[0] == model.id
    finally:
        db.close()

