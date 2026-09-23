from sqlalchemy import event

from app.db.session import SessionLocal
from app.tests.test_production_flow import _create_bundle_for_scan


def test_bundle_qr_lookup_selects_only_response_fields(client, auth_headers):
    bundle = _create_bundle_for_scan(client, auth_headers)
    with SessionLocal() as db:
        engine = db.get_bind()

    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = client.get(f"/api/barcode/bundle/{bundle['bundle_no']}", headers=auth_headers)
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "qr_code_url": f"/api/barcode/bundle-image/{bundle['id']}",
        "barcode": bundle["barcode"],
        "bundle_no": bundle["bundle_no"],
    }
    bundle_reads = [statement for statement in statements if " from bundles " in statement]
    assert len(bundle_reads) == 1, statements
    selected_columns = bundle_reads[0].split(" from bundles ", 1)[0]
    for field in ("id", "barcode", "bundle_no"):
        assert f"bundles.{field}" in selected_columns
    for field in ("notes", "status", "quantity"):
        assert f"bundles.{field}" not in selected_columns
