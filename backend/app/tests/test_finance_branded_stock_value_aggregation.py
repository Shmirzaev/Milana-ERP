from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import AuditLog, Brand, FinishedGoodsStock, Model, Role, User
from app.services.finance import branded_stock_value


def _seed_branded_stock(count: int) -> Decimal:
    marker = uuid4().hex[:10].upper()
    with SessionLocal() as db:
        model = Model(code=f"FIN-STOCK-{marker}", name=f"Finance stock {marker}")
        brand = Brand(name=f"Finance stock brand {marker}")
        db.add_all([model, brand])
        db.flush()
        rows = [
            FinishedGoodsStock(
                model_id=model.id,
                brand_id=brand.id,
                color="black",
                size=str(index),
                quantity=index + 1,
                available_qty=index + 1,
                cost_per_piece="0.1000",
                selling_price="1.00",
                status="available",
            )
            for index in range(count)
        ]
        # These rows establish that the historical filters are still applied.
        rows.extend([
            FinishedGoodsStock(
                model_id=model.id,
                brand_id=None,
                color="black",
                size="unbranded",
                quantity=99,
                available_qty=99,
                cost_per_piece="99.0000",
                selling_price="99.00",
                status="available",
            ),
            FinishedGoodsStock(
                model_id=model.id,
                brand_id=brand.id,
                color="black",
                size="sold",
                quantity=99,
                available_qty=99,
                cost_per_piece="99.0000",
                selling_price="99.00",
                status="sold",
            ),
        ])
        db.add_all(rows)
        db.commit()
    return Decimal(count * (count + 1)) / Decimal(2) * Decimal("0.1000")


def _read_value() -> tuple[float, list[str]]:
    with SessionLocal() as db:
        statements: list[str] = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select"):
                statements.append(normalized)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            value = branded_stock_value(db)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
    return value, statements


@pytest.mark.parametrize("count", [1, 50, 401])
def test_branded_stock_value_aggregates_in_one_bounded_sql_query(count):
    baseline, _ = _read_value()
    expected_delta = _seed_branded_stock(count)

    value, statements = _read_value()

    assert value == pytest.approx(baseline + float(expected_delta))
    assert len(statements) == 1, statements
    assert "sum(" in statements[0], statements
    assert "finished_goods_stock.available_qty" in statements[0], statements
    assert "finished_goods_stock.cost_per_piece" in statements[0], statements


def test_branded_stock_value_endpoint_auth_and_no_writes(client, auth_headers):
    _seed_branded_stock(3)
    with SessionLocal() as db:
        denied_role = Role(name=f"No finance report {uuid4().hex}", permissions=[])
        db.add(denied_role)
        db.flush()
        denied_user = User(
            name="Denied branded stock reader",
            email=f"denied-branded-stock-{uuid4().hex}@example.com",
            password_hash="unused-finance-report-hash",
            role_id=denied_role.id,
            factory_code="MIL",
            extra_permissions=[],
            is_active=True,
        )
        db.add(denied_user)
        db.commit()
        denied_headers = {"Authorization": f"Bearer {create_access_token(denied_user.id)}"}
        before = (db.query(FinishedGoodsStock).count(), db.query(AuditLog).count())

    response = client.get("/api/finance/branded-stock-value", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json() == {"value": None, "currency": None}
    assert client.get("/api/finance/branded-stock-value", headers=denied_headers).status_code == 403
    assert client.get("/api/finance/branded-stock-value").status_code == 401

    with SessionLocal() as db:
        after = (db.query(FinishedGoodsStock).count(), db.query(AuditLog).count())
    assert after == before
