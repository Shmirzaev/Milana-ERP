from sqlalchemy import event
from urllib.parse import quote

from app.db.session import SessionLocal
from app.tests.test_traceability_forecasting import _create_traceable_package


def test_package_traceability_lookup_projects_package_payload_fields(client, auth_headers):
    created = _create_traceable_package(client, auth_headers)
    package = created["package"]
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select") and "from packages" in normalized:
            statements.append(normalized)

    event.listen(SessionLocal.kw["bind"], "before_cursor_execute", capture)
    try:
        response = client.get(f"/api/traceability/package/{package['id']}", headers=auth_headers)
    finally:
        event.remove(SessionLocal.kw["bind"], "before_cursor_execute", capture)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["package"]["id"] == package["id"]
    assert payload["package"]["package_no"] == package["package_no"]
    lookup_reads = [
        statement for statement in statements
        if "where packages.id = ?" in statement and " limit ? offset ?" in statement
    ]
    assert len(lookup_reads) == 1
    selected_columns = lookup_reads[0].split(" from packages", 1)[0]
    assert "packages.package_no" in selected_columns
    assert "packages.storage_cell" in selected_columns
    assert "packages.notes" not in selected_columns


def test_composite_package_qr_lookup_uses_one_ranked_package_select(client, auth_headers):
    created = _create_traceable_package(client, auth_headers)
    package = created["package"]
    composite_code = f"PACKAGE:missing|{package['barcode']}"
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select") and "from packages" in normalized:
            statements.append(normalized)

    event.listen(SessionLocal.kw["bind"], "before_cursor_execute", capture)
    try:
        response = client.get(
            f"/api/traceability/package/barcode/{quote(composite_code, safe='')}",
            headers=auth_headers,
        )
    finally:
        event.remove(SessionLocal.kw["bind"], "before_cursor_execute", capture)

    assert response.status_code == 200, response.text
    assert response.json()["package"]["id"] == package["id"]
    lookup_reads = [statement for statement in statements if "order by case" in statement]
    assert len(lookup_reads) == 1, statements
    assert "packages.barcode = ?" in lookup_reads[0]
    assert "packages.package_no = ?" in lookup_reads[0]
