"""Full-history filtering must precede pagination and preserve access scope."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.schemas import Department, Role, ManualPackageReceipt, Model, Package, PackagePrintRun, PackagePrintRunMember, User
from app.core.security import create_access_token
from app.tests.conftest import TestSessionLocal, test_engine

URL = "/api/packages/print-runs"


def seed_history():
    marker = uuid4().hex[:8]
    with TestSessionLocal() as db:
        user_id = db.query(User.id).first()[0]
        model = Model(code=f"OLD{marker}-6316", name="Older warehouse model", category="T-shirt")
        db.add(model)
        receipt = ManualPackageReceipt(receipt_no=f"REC-{marker}", created_by=user_id,
                                       evidence={}, evidence_hash="0" * 64)
        db.add(receipt)
        db.flush()
        ids = []
        for index in range(105):
            pkg = Package(package_no=f"PKG-{marker}-{index:03}", barcode=f"QR-{marker}-{index}",
                          model_id=model.id, color="white", total_quantity=12, manual_receipt_id=receipt.id)
            db.add(pkg)
            db.flush()
            run = PackagePrintRun(run_no=f"PRN-{marker}-{index:03}", code=f"RUN:{marker}:{index}",
                                  packaging_department_code="PKG", created_by=user_id, package_ids=[pkg.id],
                                  deleted_package_ids=[], created_at=datetime(2026, 10, 29, 19, 0, tzinfo=timezone.utc),
                                  received_at=datetime(2026, 10, 30, tzinfo=timezone.utc) if index % 2 else None)
            db.add(run)
            db.flush()
            db.add(PackagePrintRunMember(run_id=run.id, package_id=pkg.id,
                                        snapshot={"package_no": pkg.package_no, "model_id": model.id, "quantity": 12}))
            ids.append(run.id)
        db.commit()
        return marker, ids


def test_search_finds_old_run_and_pack_before_paging(client, auth_headers):
    marker, ids = seed_history()
    for query in [f"PRN-{marker}-000", f"PKG-{marker}-000", f"old{marker}-V-6316"]:
        result = client.get(URL, headers=auth_headers, params={"page": 1, "page_size": 50, "q": query})
        assert result.status_code == 200, result.text
        body = result.json()
        if query.startswith("old"):
            assert body["total"] == 105
        else:
            assert body["total"] == 1
            assert [r["id"] for r in body["rows"]] == [ids[0]]
    page = client.get(URL, headers=auth_headers, params={"page": 3, "page_size": 50}).json()
    assert [r["id"] for r in page["rows"]] == list(reversed(ids))[-5:]
    assert page["has_more"] is False


def test_combined_receipt_and_tashkent_day_filters(client, auth_headers):
    marker, ids = seed_history()
    for status, expected in [("received", 52), ("pending", 53)]:
        body = client.get(URL, headers=auth_headers, params={"page": 1, "q": marker,
                          "receipt_status": status, "created_from": "2026-10-30", "created_to": "2026-10-30"}).json()
        assert body["total"] == expected
        assert all(bool(r["received_at"]) is (status == "received") for r in body["rows"])
    previous = client.get(URL, headers=auth_headers, params={"page": 1, "created_to": "2026-10-29"}).json()
    assert previous["total"] == 0  # 19:00 UTC is midnight of the following Tashkent day.
    with TestSessionLocal() as db:
        db.get(PackagePrintRun, ids[0]).created_at = datetime(2026, 10, 30, 19, tzinfo=timezone.utc)
        db.commit()
    boundary = client.get(URL, headers=auth_headers, params={"page": 1, "created_to": "2026-10-30"}).json()
    assert boundary["total"] == 104


@pytest.mark.parametrize("params", [{"receipt_status": "shipped"}, {"q": "x" * 121},
                                    {"created_from": "bad-date"}, {"page": 0}, {"page_size": 101}])
def test_invalid_filter_inputs(client, auth_headers, params):
    assert client.get(URL, headers=auth_headers, params=params).status_code == 422


def test_reversed_date_range_is_refused(client, auth_headers):
    assert client.get(URL, headers=auth_headers, params={"created_from": "2026-11-02",
                                                       "created_to": "2026-10-01"}).status_code == 400


def test_filtered_list_is_bounded_and_read_only(client, auth_headers):
    marker, ids = seed_history()
    writes = []
    selects = []

    def capture(_conn, _cursor, statement, *_args):
        sql = statement.lstrip().upper()
        if sql.startswith(("UPDATE ", "INSERT ", "DELETE ")):
            writes.append(statement)
        if sql.startswith("SELECT"):
            selects.append(statement)

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        for _ in range(10):
            response = client.get(URL, headers=auth_headers, params={"q": marker, "page": 1, "page_size": 50})
            assert response.status_code == 200
            assert response.json()["total"] == len(ids)
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)
    assert not writes
    assert len(selects) <= 50  # auth, count, page, bulk members, bulk model labels per request.


def test_search_treats_wildcards_literally_and_excludes_retired(client, auth_headers):
    _, ids = seed_history()
    for query in ["%", "_"]:
        body = client.get(URL, headers=auth_headers, params={"page": 1, "q": query}).json()
        assert body["total"] == 0
    with TestSessionLocal() as db:
        db.get(PackagePrintRun, ids[0]).deleted_at = datetime.now(timezone.utc)
        db.commit()
    body = client.get(URL, headers=auth_headers, params={"page": 1}).json()
    assert body["total"] == 104


def test_search_ignores_deleted_members_retained_for_accounting(client, auth_headers):
    marker, ids = seed_history()
    with TestSessionLocal() as db:
        run = db.get(PackagePrintRun, ids[0])
        retained_id = run.package_ids[0]
        run.deleted_package_ids = [retained_id]
        db.get(Package, retained_id).status = "shipped"
        # An active sibling keeps the run visible; the retired shipped member is retained.
        sibling = db.get(PackagePrintRun, ids[1]).package_ids[0]
        run.package_ids = [retained_id, sibling]
        db.add(PackagePrintRunMember(run_id=run.id, package_id=sibling,
                                    snapshot={"package_no": "ACTIVE-SIBLING", "quantity": 12}))
        db.commit()
    body = client.get(URL, headers=auth_headers, params={"page": 1, "q": f"PKG-{marker}-000"}).json()
    assert body["total"] == 0


def test_filtered_search_keeps_department_scope_and_permission_denial(client, auth_headers):
    marker, ids = seed_history()
    with TestSessionLocal() as db:
        db.get(PackagePrintRun, ids[0]).packaging_department_code = "ECP"
        department = db.query(Department).filter_by(code="PKG").one()
        role = Role(name=f"filter-reader-{marker}", permissions=["packaging.packages"])
        denied_role = Role(name=f"filter-denied-{marker}", permissions=[])
        db.add_all([role, denied_role])
        db.flush()
        reader = User(name="Filter reader", email=f"filter-{marker}@test.local", password_hash="unused",
                      department_id=department.id, role_id=role.id, factory_code="MIL")
        denied = User(name="Denied reader", email=f"denied-{marker}@test.local", password_hash="unused",
                      department_id=department.id, role_id=denied_role.id, factory_code="MIL")
        db.add_all([reader, denied])
        db.flush()
        token = create_access_token(str(reader.id))
        denied_token = create_access_token(str(denied.id))
        db.commit()
    params = {"page": 1, "q": marker, "receipt_status": "pending", "created_from": "2026-10-30"}
    body = client.get(URL, headers={"Authorization": f"Bearer {token}"}, params=params).json()
    assert body["total"] == 52
    assert ids[0] not in [r["id"] for r in body["rows"]]
    assert client.get(URL, headers={"Authorization": f"Bearer {denied_token}"}, params=params).status_code == 403
    assert client.get(URL, params=params).status_code == 401
