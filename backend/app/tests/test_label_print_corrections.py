from html import escape
import re

import pytest

from app.services.cutting_sheet import render_cutting_sheet_html
from app.services.package_label_pages import label_document
from app.models import BrandedPlanningOrder, Customer, CuttingRecord, Department, Model, ProductionOrder, SalesOrder, WorkOrder
from app.tests.conftest import TestSessionLocal


def test_package_pages_have_no_page_footer_and_keep_four_cards_per_page():
    cards = [f"<article class='label' data-qr='{n}'><!--label-ordinal--></article>" for n in range(6)]
    document = label_document("Labels", cards, "")
    assert "<footer class='page-number'>" not in document
    pages = re.findall(r"<section class='label-page'>(.*?)</section>", document)
    assert [page.count("<article class='label'") for page in pages] == [4, 2]
    assert re.findall(r"data-qr='(\d+)'", document) == list(map(str, range(6)))
    assert re.findall(r"class='label-ordinal'>(\d+)</b>", document) == list(map(str, range(1, 7)))


@pytest.mark.parametrize("source", ["sales", "planning", "service", "none", "internal"])
def test_cutting_sheet_prints_only_the_chosen_client(source):
    name = 'Client <A&B> "Factory"'
    with TestSessionLocal() as db:
        model = Model(code="CLIENT-SHEET", name="Sheet")
        customer = Customer(name=name)
        db.add_all([model, customer])
        db.flush()
        order = ProductionOrder(production_no="PO-CLIENT-SHEET", model_id=model.id, production_type="branded_stock")
        if source == "sales":
            sales = SalesOrder(order_no="SO-CLIENT-SHEET", customer_id=customer.id)
            db.add(sales)
            db.flush()
            order.sales_order_id = sales.id
        elif source in {"planning", "internal"}:
            planning = BrandedPlanningOrder(order_no="BSO-CLIENT-SHEET", ordered_for_type="customer" if source == "planning" else "milana", customer_id=customer.id if source == "planning" else None, ordered_for_name=name)
            db.add(planning)
            db.flush()
            order.planning_order_id = planning.id
        elif source == "service":
            order.source_type = "usluga"
            order.service_customer_name = name
        db.add(order)
        db.flush()
        work = WorkOrder(production_order_id=order.id, operation="cutting", department_id=db.query(Department).filter_by(code="CUT").one().id)
        db.add(work)
        db.flush()
        record = CuttingRecord(work_order_id=work.id)
        db.add(record)
        db.flush()
        html = render_cutting_sheet_html(db, record)
        if source in {"sales", "planning", "service"}:
            assert "Client / Клиент / Mijoz" in html
            assert escape(name, quote=True) in html
            assert name not in html
        else:
            assert "Client / Клиент / Mijoz" not in html
            assert escape(name, quote=True) not in html
