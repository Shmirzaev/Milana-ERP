"""Factory correction regressions: synthetic local fixtures, no production writes."""
import pytest

from app.db.session import SessionLocal
from app.schemas import Department, ProductionBatch, WorkOrder
from app.tests.test_passport_get_scope import _actor, _headers, _passport


@pytest.mark.parametrize("factory", ["MIL", "ECO"])
def test_passport_open_resolves_real_cutting_work_order_and_preserves_scope(client, factory):
    refs = _passport(factory)
    pid, order_id, work_id = [row[1] for row in refs]
    headers = _headers(_actor(factory), factory)
    detail = client.get(f"/api/cutting-passports/{pid}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["cutting_work_order_id"] == work_id
    listing = client.get("/api/cutting-passports", headers=headers)
    assert listing.status_code == 200, listing.text
    assert next(row for row in listing.json() if row["id"] == pid)["cutting_work_order_id"] == work_id
    wrong = "ECO" if factory == "MIL" else "MIL"
    assert client.get(f"/api/cutting-passports/{pid}", headers=_headers(_actor(wrong), wrong)).status_code == 403


def test_unlinked_passport_has_no_cutting_link(client, auth_headers):
    pid = _passport(linked=False)[0][1]
    result = client.get(f"/api/cutting-passports/{pid}", headers=auth_headers)
    assert result.status_code == 200, result.text
    assert result.json()["cutting_work_order_id"] is None


def test_passport_link_chooses_its_own_nastil_and_never_another(client, auth_headers):
    refs = _passport()
    pid, order_id, parent_id = [row[1] for row in refs]
    with SessionLocal() as db:
        dept_id = db.query(Department.id).filter_by(code="CUT").scalar()
        target = ProductionBatch(production_order_id=order_id, batch_no="QA-1", batch_index=1,
                                 cutting_passport_id=pid, planned_quantity=20)
        other = ProductionBatch(production_order_id=order_id, batch_no="QA-2", batch_index=2, planned_quantity=20)
        db.add_all([target, other])
        db.flush()
        db.add(WorkOrder(production_order_id=order_id, production_batch_id=other.id,
                         department_id=dept_id, operation="cutting"))
        matching = WorkOrder(production_order_id=order_id, production_batch_id=target.id,
                             department_id=dept_id, operation="cutting")
        db.add(matching)
        db.commit()
        matching_id = matching.id
    assert client.get(f"/api/cutting-passports/{pid}", headers=auth_headers).json()["cutting_work_order_id"] == matching_id
    with SessionLocal() as db:
        db.delete(db.get(WorkOrder, matching_id))
        db.commit()
    assert client.get(f"/api/cutting-passports/{pid}", headers=auth_headers).json()["cutting_work_order_id"] == parent_id
    with SessionLocal() as db:
        db.delete(db.get(WorkOrder, parent_id))
        db.commit()
    assert client.get(f"/api/cutting-passports/{pid}", headers=auth_headers).json()["cutting_work_order_id"] is None


@pytest.mark.parametrize("language", ["en", "ru", "uz"])
@pytest.mark.parametrize("prices", [True, False])
def test_invoice_package_rows_use_one_sufficient_height_at_ten_points(language, prices):
    from copy import deepcopy
    from io import BytesIO
    from openpyxl import load_workbook
    from app.models.shipment_invoice_excel_service import shipment_invoice_workbook

    document = {"shipment_no": "QA-UNIFORM", "packages_count": 2, "quantity": 7, "amount": "17.50",
                "package_details": [{"package_no": "QA-SHORT", "quantity": 3, "weight_kg": "1.25"},
                                    {"package_no": "QA-LONG", "quantity": 4, "weight_kg": "1.50"}],
                "lines": [{"package_no": "QA-SHORT", "model_no": "QA-S", "description": "Short",
                           "size": "M", "quantity": 3, "unit_price": "2.50", "amount": "7.50"},
                          {"package_no": "QA-LONG", "model_no": "QA-L",
                           "description": "Long cotton garment description " * 8,
                           "size": "L", "quantity": 4, "unit_price": "2.50", "amount": "10.00"}]}
    before = deepcopy(document)
    sheet = load_workbook(BytesIO(shipment_invoice_workbook(document, language, show_prices=prices))).active
    assert sheet.row_dimensions[10].height == sheet.row_dimensions[11].height
    assert sheet.row_dimensions[10].height > 100, "The longest description must remain readable without shrinking"
    assert sheet["D10"].font.sz == sheet["D11"].font.sz == 10
    assert sheet["G12"].value == 7 and sheet["I12"].value == 2.75
    assert sheet["K12"].value == (17.5 if prices else None)
    assert sheet["D10"].alignment.wrap_text and not sheet["D10"].alignment.shrink_to_fit
    assert len(sheet._images) == 1
    assert sheet.print_title_rows == "$9:$9"
    assert document == before


def test_cutting_board_attributes_each_bundle_to_its_record_origin(client, auth_headers):
    from app.schemas import CuttingRecord
    from app.models.department_dashboards_service import cutting_board
    from app.tests.test_department_dashboards import DAY, order, bundle

    with SessionLocal() as db:
        po, mil_work, mil_record = order(db, "QA-MIXED-ORIGIN")
        eco_work = WorkOrder(production_order_id=po.id,
                            department_id=db.query(Department.id).filter_by(code="ECT").scalar(),
                            operation="cutting", status="in_progress")
        db.add(eco_work)
        db.flush()
        eco_record = CuttingRecord(work_order_id=eco_work.id, passed_pieces=30, approval_status="approved")
        db.add(eco_record)
        db.flush()
        bundle(db, po, mil_record, "QA-MIXED-MIL", quantity=20)
        bundle(db, po, eco_record, "QA-MIXED-ECO", factory="ECO", quantity=30)
        db.commit()
        mil = cutting_board(db, "CUT", DAY, DAY)
        eco = cutting_board(db, "ECT", DAY, DAY)
        assert mil["totals"] == {"bundles": 1, "pieces": 20, "orders": 1, "work_orders": 1}
        assert eco["totals"] == {"bundles": 1, "pieces": 30, "orders": 1, "work_orders": 1}
        assert sum(row["created_pieces"] for row in mil["factories"]) == 20
        assert sum(row["created_pieces"] for row in eco["factories"]) == 30
    inventory = client.get("/api/bundles/cutting-inventory?cutting_department_code=CUT", headers=auth_headers)
    assert inventory.status_code == 200, inventory.text
    assert inventory.json()["total_quantity"] == 20


@pytest.mark.parametrize("department", ["CUT", "ECT"])
def test_cutting_origin_keeps_legacy_unlinked_bundle_fallback(department):
    from app.schemas import Bundle
    from app.models.department_dashboards_service import cutting_board
    from app.tests.test_department_dashboards import DAY, order, bundle
    with SessionLocal() as db:
        po, work, record = order(db, f"QA-LEGACY-{department}", department)
        row = bundle(db, po, record, f"QA-LEGACY-{department}", quantity=17)
        row.cutting_record_id = None
        db.commit()
        assert db.get(Bundle, row.id).cutting_record_id is None
        for selected in ("CUT", "ECT"):
            totals = cutting_board(db, selected, DAY, DAY)["totals"]
            assert totals["pieces"] == (17 if selected == department else 0)
            assert totals["work_orders"] == 0, "A missing source record must not invent a Cutting job"


def test_navigation_projection_is_one_query_for_500_and_cannot_cross_factory():
    from types import SimpleNamespace
    from sqlalchemy import event
    from app.models.production.cutting_passport_navigation_service import passport_cutting_work_orders
    from app.schemas import User
    refs = _passport()
    _, oid, wid = [row[1] for row in refs]
    eco_refs = _passport("ECO")
    actor_id = _actor()
    with SessionLocal() as db:
        actor = db.get(User, actor_id)
        passports = [SimpleNamespace(id=number, production_order_id=oid) for number in range(1, 501)]
        queries = []
        def track(connection, cursor, statement, parameters, context, executemany):
            queries.append(statement)
        engine = db.get_bind()
        event.listen(engine, "before_cursor_execute", track)
        try:
            links = passport_cutting_work_orders(db, passports, {}, actor)
        finally:
            event.remove(engine, "before_cursor_execute", track)
        assert links == {number: wid for number in range(1, 501)}
        assert len(queries) == 1
        assert passport_cutting_work_orders(db, [SimpleNamespace(id=999, production_order_id=eco_refs[1][1])], {}, actor) == {}
