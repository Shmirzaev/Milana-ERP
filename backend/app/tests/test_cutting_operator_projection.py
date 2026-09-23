from sqlalchemy import event

from app.tests.conftest import TestSessionLocal


def test_cutting_operator_options_load_only_response_and_factory_policy_fields(client, auth_headers):
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT") and "FROM users" in statement:
            statements.append(statement.lower())

    event.listen(TestSessionLocal.kw["bind"], "before_cursor_execute", capture)
    try:
        response = client.get("/api/cutting-passports/operators", headers=auth_headers)
    finally:
        event.remove(TestSessionLocal.kw["bind"], "before_cursor_execute", capture)

    assert response.status_code == 200, response.text
    assert all(set(row) == {"id", "name"} for row in response.json())
    operator_reads = [
        statement for statement in statements
        if "where users.is_active is 1 order by users.name asc, users.id asc" in statement
    ]
    assert len(operator_reads) == 1, statements
    selected = operator_reads[0].split(" from users", 1)[0]
    assert "users.name" in selected
    assert "users.factory_code" in selected
    assert "users.extra_permissions" in selected
    assert "users.access_policy" in selected
    assert "users.password_hash" not in selected
    assert "users.email" not in selected
