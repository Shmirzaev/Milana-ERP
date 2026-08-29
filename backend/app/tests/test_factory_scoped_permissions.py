from app.core.security import hash_password


MILANA_ROLE_PERMISSION = "planning.production"
ECO_PERMISSIONS = [
    "cutting.records",
    "cutting.bundles",
    "usluga.view",
    "usluga.manage",
]
ECO_SCOPED_TOKENS = [f"factory:ECO:{permission}" for permission in ECO_PERMISSIONS]


def _login_json(client, factory_code: str):
    response = client.post(
        "/api/auth/login-json",
        json={
            "email": "multi.factory.planner@example.com",
            "password": "MultiFactoryPlanner!2026",
            "factory_code": factory_code,
        },
    )
    assert response.status_code == 200, response.text


def test_secondary_factory_uses_only_its_scoped_permissions(client):
    from app.db.session import SessionLocal
    from app.models import Department, Role, User

    db = SessionLocal()
    try:
        role = db.query(Role).filter(Role.name == "Planning").one()
        department = db.query(Department).filter(Department.code == "PLN").one()
        user = User(
            name="Multi Factory Planner",
            email="multi.factory.planner@example.com",
            password_hash=hash_password("MultiFactoryPlanner!2026"),
            role_id=role.id,
            department_id=department.id,
            factory_code="MIL",
            extra_permissions=ECO_SCOPED_TOKENS,
            is_active=True,
        )
        db.add(user)
        db.commit()
    finally:
        db.close()

    _login_json(client, "MIL")
    milana = client.get("/api/auth/me")
    assert milana.status_code == 200, milana.text
    assert milana.json()["factory_code"] == "MIL"
    assert milana.json()["assigned_factory_code"] == "MIL"
    assert milana.json()["available_factories"] == ["MIL", "ECO"]
    assert MILANA_ROLE_PERMISSION in milana.json()["permissions"]
    assert "usluga.manage" not in milana.json()["permissions"]

    _login_json(client, "ECO")
    eco = client.get("/api/auth/me")
    assert eco.status_code == 200, eco.text
    assert eco.json()["factory_code"] == "ECO"
    assert eco.json()["assigned_factory_code"] == "MIL"
    assert eco.json()["available_factories"] == ["MIL", "ECO"]
    assert eco.json()["permissions"] == ECO_PERMISSIONS
    assert MILANA_ROLE_PERMISSION not in eco.json()["permissions"]
    assert "usluga.handover" not in eco.json()["permissions"]
    assert "sewing.records" not in eco.json()["permissions"]
    assert "packaging.records" not in eco.json()["permissions"]
    assert "attendance.view" not in eco.json()["permissions"]
    assert "admin.users" not in eco.json()["permissions"]
    assert "*" not in eco.json()["permissions"]

    assert client.get("/api/inbox?dept=ECT").status_code == 200
    assert client.get("/api/usluga/models").status_code == 200
    assert client.get("/api/usluga/orders").status_code == 200
    operators = client.get("/api/cutting-passports/operators")
    assert operators.status_code == 200, operators.text
    assert any(row["name"] == "Multi Factory Planner" for row in operators.json())
    assert all(set(row) == {"id", "name"} for row in operators.json())
    assert client.get("/api/inbox?dept=ECO").status_code == 403
    assert client.get("/api/inbox?dept=ECP").status_code == 403
    assert client.get("/api/attendance/overview").status_code == 403
    assert client.get("/api/users").status_code == 403


def test_cutting_operator_options_are_limited_to_selected_factory(client):
    from app.db.session import SessionLocal
    from app.models import Department, Role, User

    db = SessionLocal()
    try:
        cutting_role = db.query(Role).filter(Role.name == "Cutting").one()
        ect = db.query(Department).filter(Department.code == "ECT").one()
        mil_only = User(
            name="MIL Only Cutting Operator",
            email="mil.only.cutting.operator@example.com",
            password_hash=hash_password("MilOnlyCutting!2026"),
            role_id=cutting_role.id,
            department_id=ect.id,
            factory_code="MIL",
            extra_permissions=[],
            is_active=True,
        )
        eco_operator = User(
            name="ECO Cutting Operator",
            email="eco.cutting.operator@example.com",
            password_hash=hash_password("EcoCuttingOperator!2026"),
            role_id=cutting_role.id,
            department_id=ect.id,
            factory_code="ECO",
            extra_permissions=[],
            is_active=True,
        )
        db.add_all([mil_only, eco_operator])
        db.commit()
    finally:
        db.close()

    login = client.post(
        "/api/auth/login-json",
        json={
            "email": "eco.cutting.operator@example.com",
            "password": "EcoCuttingOperator!2026",
            "factory_code": "ECO",
        },
    )
    assert login.status_code == 200, login.text

    response = client.get("/api/cutting-passports/operators")
    assert response.status_code == 200, response.text
    names = {row["name"] for row in response.json()}
    assert "ECO Cutting Operator" in names
    assert "MIL Only Cutting Operator" not in names
    assert client.get("/api/users").status_code == 403


def test_unscoped_secondary_factory_login_is_rejected(client):
    from app.db.session import SessionLocal
    from app.models import User

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "planning@example.com").one()
        user.extra_permissions = []
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/api/auth/login-json",
        json={
            "email": "planning@example.com",
            "password": "demo12345",
            "factory_code": "ECO",
        },
    )
    assert response.status_code == 403
