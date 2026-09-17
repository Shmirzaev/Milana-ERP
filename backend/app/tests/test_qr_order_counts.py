from app.models import PayrollQrLabel
from app.tests.conftest import TestSessionLocal


def test_whole_order_counts_ignore_pagination_search_status_and_other_factories(client, auth_headers):
    with TestSessionLocal() as db:
        for factory, status, operation in [("MIL", "scanned", "A"), ("MIL", "available", "B"),
                ("MIL", "superseded", "C"), ("BST", "scanned", "D")]:
            db.add(PayrollQrLabel(label_uid=f"COUNT-{operation}", factory_code=factory, payload="test",
                production_no="PO-COUNT", status=status, operation_code=operation, quantity=10, rate_per_piece=1))
        db.commit()
    for query in ["limit=1", "limit=1&offset=1", "status=scanned", "search=B"]:
        response = client.get(f"/api/payroll/qr-labels?{query}", headers=auth_headers)
        assert response.status_code == 200, response.text
        count = next(row for row in response.json()["order_counts"] if row["order_no"] == "PO-COUNT")
        assert count == {"order_no": "PO-COUNT", "total": 2, "scanned": 1}
