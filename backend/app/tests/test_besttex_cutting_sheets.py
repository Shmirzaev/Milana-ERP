import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import SessionLocal
from app.models import Bundle, CuttingRecord, Department, Model, ProductionBatch, ProductionOrder, Role, User, WorkOrder


@pytest.fixture
def cuts():
    with SessionLocal() as db:
        departments = {row.code: row.id for row in db.query(Department)}
        model = db.query(Model).first()
        result = {}
        for factory in ("BST", "MIL", "ECO"):
            order = ProductionOrder(production_no=f"PO-QA-{factory}", production_type="branded_stock", model_id=model.id, planned_quantity=6)
            db.add(order); db.flush()
            cut = WorkOrder(production_order_id=order.id, department_id=departments["CUT"], operation="cutting")
            sew = WorkOrder(production_order_id=order.id, department_id=departments[factory], operation="sewing")
            db.add_all([cut, sew]); db.flush()
            record = CuttingRecord(work_order_id=cut.id, cut_pieces=6, passed_pieces=6,
                                   cutting_batch_no=f"CUT-QA-{factory}")
            db.add(record); db.flush()
            result[factory] = (order.id, record.id, cut.id)
        db.commit()
        return result


def reader(*, factory="BST", permissions=("besttex.cutting_sheets",), denied=False):
    with SessionLocal() as db:
        role = Role(name="Besttex reader test", permissions=list(permissions))
        user = User(name="Reader", email="reader@example.test", factory_code=factory, role=role,
                    password_hash="unused", access_policy={factory: {"allow": [], "deny": ["besttex.cutting_sheets"]}} if denied else None)
        db.add(user); db.commit()
        return {"Authorization": "Bearer " + create_access_token(user.id, extra={"factory_code": factory})}


def business_snapshot():
    with SessionLocal() as db:
        return {table.name: [tuple(map(repr, row)) for row in db.execute(select(table))]
                for table in Base.metadata.sorted_tables if table.name not in {"users"}}


def test_list_and_print_are_scoped_readonly_and_repeatable(client, cuts):
    headers = reader()
    before = business_snapshot()
    for _ in range(10):
        response = client.get("/api/besttex/cutting-orders", headers=headers)
        assert response.status_code == 200, response.text
        assert [row["cutting_record_id"] for row in response.json()["items"]] == [cuts["BST"][1]]
        sheet = client.get(f'/api/besttex/cutting-orders/{cuts["BST"][1]}/sheet', headers=headers)
        assert sheet.status_code == 200, sheet.text
        assert "text/html" in sheet.headers["content-type"]
        assert client.get(f'/api/besttex/cutting-orders/{cuts["MIL"][1]}/sheet', headers=headers).status_code == 404
        assert client.get(f'/api/besttex/cutting-orders/{cuts["ECO"][1]}/sheet', headers=headers).status_code == 404
    assert client.post(f'/api/cutting/records/{cuts["BST"][1]}/production-sheet', headers=headers).status_code == 403
    assert client.patch(f'/api/work-orders/{cuts["BST"][2]}', headers=headers, json={"status": "completed"}).status_code == 403
    assert client.post("/api/besttex/cutting-orders", headers=headers, json={}).status_code == 405
    assert business_snapshot() == before


@pytest.mark.parametrize("factory,permissions,denied", [("MIL", ("besttex.cutting_sheets",), False),
    ("ECO", ("besttex.cutting_sheets",), False), ("BST", (), False), ("BST", ("*",), True)])
def test_access_denials(client, cuts, factory, permissions, denied):
    headers = reader(factory=factory, permissions=permissions, denied=denied)
    assert client.get("/api/besttex/cutting-orders", headers=headers).status_code == 403
    assert client.get(f'/api/besttex/cutting-orders/{cuts["BST"][1]}/sheet', headers=headers).status_code == 403


def test_admin_search_paging_and_validation(client, auth_headers, cuts):
    response = client.get("/api/besttex/cutting-orders?q=BST&page_size=1", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    assert client.get("/api/besttex/cutting-orders?page=2&page_size=1", headers=auth_headers).json()["items"] == []
    assert client.get("/api/besttex/cutting-orders?q=%25", headers=auth_headers).json()["total"] == 0
    assert client.get("/api/besttex/cutting-orders?page_size=101", headers=auth_headers).status_code == 422


def test_exact_batch_route_and_approved_output(client, auth_headers, cuts):
    with SessionLocal() as db:
        order_id, record_id, cut_id = cuts["BST"]
        batch = ProductionBatch(production_order_id=order_id, batch_no="QA-OTHER", batch_index=1)
        db.add(batch); db.flush()
        record = db.get(CuttingRecord, record_id)
        record.production_batch_id = batch.id
        db.add(WorkOrder(production_order_id=order_id, production_batch_id=batch.id, operation="sewing",
                         department_id=db.query(Department.id).filter_by(code="ECO").scalar()))
        db.commit()
    assert client.get("/api/besttex/cutting-orders", headers=auth_headers).json()["total"] == 0
    assert client.get(f"/api/besttex/cutting-orders/{record_id}/sheet", headers=auth_headers).status_code == 404


def test_bundle_routing_overrides_stale_order_route_and_mixed_records_are_hidden(client, auth_headers, cuts):
    with SessionLocal() as db:
        model_id = db.query(Model.id).first()[0]
        for factory, destination in [("BST", "ECO"), ("MIL", "BST")]:
            order_id, record_id, _ = cuts[factory]
            db.add(Bundle(production_order_id=order_id, cutting_record_id=record_id, model_id=model_id,
                          bundle_no=f"QR-{factory}", barcode=f"QR-{factory}", color="White", size="S", quantity=6,
                          sewing_factory_code=destination))
        db.commit()
    rows = client.get("/api/besttex/cutting-orders", headers=auth_headers).json()["items"]
    assert [row["cutting_record_id"] for row in rows] == [cuts["MIL"][1]]
    assert client.get(f'/api/besttex/cutting-orders/{cuts["MIL"][1]}/sheet', headers=auth_headers).status_code == 200
    with SessionLocal() as db:
        db.add(Bundle(production_order_id=cuts["MIL"][0], cutting_record_id=cuts["MIL"][1], model_id=model_id,
                      bundle_no="QR-MIX", barcode="QR-MIX", color="White", size="M", quantity=1, sewing_factory_code="MIL"))
        db.commit()
    assert client.get("/api/besttex/cutting-orders", headers=auth_headers).json()["total"] == 0


def test_unapproved_cutting_does_not_appear(client, auth_headers, cuts):
    with SessionLocal() as db:
        db.get(CuttingRecord, cuts["BST"][1]).approval_status = "pending"
        db.commit()
    assert client.get("/api/besttex/cutting-orders", headers=auth_headers).json()["total"] == 0


def test_legacy_mismatched_batch_cannot_borrow_another_batch_destination(client, auth_headers, cuts):
    with SessionLocal() as db:
        order_id, record_id, cut_id = cuts["ECO"]
        batch = ProductionBatch(production_order_id=order_id, batch_no="ECO-LEGACY", batch_index=1)
        db.add(batch); db.flush()
        db.get(WorkOrder, cut_id).production_batch_id = batch.id
        db.add(Bundle(production_order_id=order_id, model_id=db.query(Model.id).first()[0],
                      bundle_no="UNRELATED-BST", barcode="UNRELATED-BST", color="White", size="S", quantity=6,
                      sewing_factory_code="BST"))
        db.commit()
    rows = client.get("/api/besttex/cutting-orders", headers=auth_headers).json()["items"]
    assert [row["cutting_record_id"] for row in rows] == [cuts["BST"][1]]
    assert client.get(f"/api/besttex/cutting-orders/{record_id}/sheet", headers=auth_headers).status_code == 404


def test_unrouted_legacy_bundle_uses_exact_sewing_route_for_list_and_print(client, auth_headers, cuts):
    with SessionLocal() as db:
        db.add(Bundle(production_order_id=cuts["BST"][0], cutting_record_id=cuts["BST"][1],
                      model_id=db.query(Model.id).first()[0], bundle_no="LEGACY-BST", barcode="LEGACY-BST",
                      color="White", size="S", quantity=6))
        db.commit()
    assert client.get("/api/besttex/cutting-orders", headers=auth_headers).json()["total"] == 1
    assert client.get(f'/api/besttex/cutting-orders/{cuts["BST"][1]}/sheet', headers=auth_headers).status_code == 200


def test_displayed_sales_reference_is_searchable(client, auth_headers, cuts):
    from app.models import SalesOrder
    with SessionLocal() as db:
        sale = SalesOrder(order_no="SO-CUSTOMER-REFERENCE", order_type="client_order")
        db.add(sale); db.flush()
        db.get(ProductionOrder, cuts["BST"][0]).sales_order_id = sale.id
        db.commit()
    result = client.get("/api/besttex/cutting-orders?q=CUSTOMER-REFERENCE", headers=auth_headers)
    assert result.status_code == 200, result.text
    assert result.json()["total"] == 1
    assert result.json()["items"][0]["order_no"] == "SO-CUSTOMER-REFERENCE"


def test_list_projects_group_and_exact_variant_photos_without_binary_data(client, auth_headers, cuts):
    from datetime import datetime, timezone
    from sqlalchemy import event
    from app.models import BrandedPlanningOrder, ModelImage, ProductionOrderItem
    from app.db.session import engine

    with SessionLocal() as db:
        base = Model(code="PIC100", name="Garment", details_json={"general": {"model_no": "PIC100"}})
        variant = Model(code="PIC100-123", name="Variant", details_json={"general": {"model_no": "PIC100", "variant_no": "123"}})
        sibling = Model(code="PIC100-124", name="Other variant", details_json={"general": {"model_no": "PIC100", "variant_no": "124"}})
        planning = BrandedPlanningOrder(order_no="BSO-QA-PHOTOS", ordered_for_type="milana", ordered_for_name="Milana")
        db.add_all([base, variant, sibling, planning]); db.flush()
        for model, kind, url in [(base, "model", "garment.jpg"), (variant, "material", "fabric-v123.jpg"), (sibling, "material", "wrong-v124.jpg")]:
            db.add(ModelImage(model_id=model.id, image_type=kind, file_name=url, file_url="/storage/model-files/" + url,
                              content_type="image/jpeg", file_data=b"not part of list payload"))
        order = db.get(ProductionOrder, cuts["BST"][0])
        order.model_id = variant.id; order.planning_order_id = planning.id
        order.estimated_material_code = "MAT-QA-COTTON"
        order.deadline = datetime(2026, 11, 1, tzinfo=timezone.utc)
        for size in ("50", "46", "48"):
            db.add(ProductionOrderItem(production_order_id=order.id, model_id=variant.id, color="White", size=size, planned_quantity=2))
        db.commit()
    statements = []
    def capture(_conn, _cursor, statement, *_args):
        statements.append(statement)
    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = client.get("/api/besttex/cutting-orders?q=BSO-QA-PHOTOS", headers=auth_headers)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert response.status_code == 200, response.text
    row = response.json()["items"][0]
    assert row["planning_order_no"] == "BSO-QA-PHOTOS"
    assert row["planning_order_name"] == "Milana"
    assert (row["model_no"], row["variant_no"]) == ("PIC100", "123")
    assert row["model_image_url"] == "/storage/model-files/garment.jpg"
    assert row["variant_image_url"] == "/storage/model-files/fabric-v123.jpg"
    assert row["size_summary"] == "46–50 (3)"
    assert row["material_label"] == "MAT-QA-COTTON"
    assert row["deadline"].startswith("2026-11-01")
    assert not any("model_images.file_data" in statement for statement in statements)
    assert "not part of list payload" not in response.text


def test_list_does_not_borrow_sibling_variant_picture(client, auth_headers, cuts):
    from app.models import ModelImage
    with SessionLocal() as db:
        model = db.get(Model, db.get(ProductionOrder, cuts["BST"][0]).model_id)
        model.details_json = {"general": {"model_no": "QA-MISSING", "variant_no": "10"}}
        db.add(ModelImage(model_id=model.id, image_type="material", file_name="fabric-v11.jpg",
                          file_url="/storage/model-files/fabric-v11.jpg", content_type="image/jpeg"))
        db.commit()
    response = client.get("/api/besttex/cutting-orders", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["items"][0]["variant_image_url"] is None


def test_letter_sizes_are_listed_without_an_alphabetical_range(client, auth_headers, cuts):
    from app.models import ProductionOrderItem
    with SessionLocal() as db:
        order = db.get(ProductionOrder, cuts["BST"][0])
        for size in ("S", "M", "XL"):
            db.add(ProductionOrderItem(production_order_id=order.id, model_id=order.model_id,
                                       color="White", size=size, planned_quantity=2))
        db.commit()
    row = client.get("/api/besttex/cutting-orders", headers=auth_headers).json()["items"][0]
    assert set(row["size_summary"].split(", ")) == {"S", "M", "XL"}


def test_record_without_own_bundles_cannot_print_sibling_record_bundles(client, auth_headers, cuts):
    with SessionLocal() as db:
        sibling = CuttingRecord(work_order_id=cuts["BST"][2], cut_pieces=2, passed_pieces=2, cutting_batch_no="CUT-SIBLING")
        db.add(sibling); db.flush()
        db.add(Bundle(production_order_id=cuts["BST"][0], cutting_record_id=sibling.id,
                      model_id=db.query(Model.id).first()[0], bundle_no="SIBLING-BST", barcode="SIBLING-BST",
                      color="White", size="S", quantity=2, sewing_factory_code="BST"))
        db.commit(); sibling_id = sibling.id
    rows = client.get("/api/besttex/cutting-orders", headers=auth_headers).json()["items"]
    assert [row["cutting_record_id"] for row in rows] == [sibling_id]
    assert client.get(f"/api/besttex/cutting-orders/{sibling_id}/sheet", headers=auth_headers).status_code == 200
    assert client.get(f'/api/besttex/cutting-orders/{cuts["BST"][1]}/sheet', headers=auth_headers).status_code == 404


def test_inconsistent_linked_bundle_batch_cannot_authorize_cutting_record(client, auth_headers, cuts):
    with SessionLocal() as db:
        batch = ProductionBatch(production_order_id=cuts["ECO"][0], batch_no="UNRELATED-LINK", batch_index=1)
        db.add(batch); db.flush()
        db.add(Bundle(production_order_id=cuts["ECO"][0], cutting_record_id=cuts["ECO"][1], production_batch_id=batch.id,
                      model_id=db.query(Model.id).first()[0], bundle_no="BAD-LINK-BST", barcode="BAD-LINK-BST",
                      color="White", size="S", quantity=6, sewing_factory_code="BST"))
        db.commit()
    rows = client.get("/api/besttex/cutting-orders", headers=auth_headers).json()["items"]
    assert [row["cutting_record_id"] for row in rows] == [cuts["BST"][1]]
    assert client.get(f'/api/besttex/cutting-orders/{cuts["ECO"][1]}/sheet', headers=auth_headers).status_code == 404


def test_unlinked_bundles_cannot_be_claimed_by_multiple_cutting_records(client, auth_headers, cuts):
    with SessionLocal() as db:
        sibling = CuttingRecord(work_order_id=cuts["BST"][2], cut_pieces=2, passed_pieces=2, cutting_batch_no="AMBIGUOUS-SIBLING")
        db.add(sibling); db.flush()
        db.add(Bundle(production_order_id=cuts["BST"][0], model_id=db.query(Model.id).first()[0],
                      bundle_no="UNLINKED-BST", barcode="UNLINKED-BST", color="White", size="S", quantity=6,
                      sewing_factory_code="BST"))
        db.commit(); sibling_id = sibling.id
    assert client.get("/api/besttex/cutting-orders", headers=auth_headers).json()["total"] == 0
    for record_id in [sibling_id, cuts["BST"][1]]:
        assert client.get(f"/api/besttex/cutting-orders/{record_id}/sheet", headers=auth_headers).status_code == 404


def test_access_provisioning_preserves_unrelated_rights_and_is_idempotent(monkeypatch):
    path = Path(__file__).resolve().parents[2] / "alembic/versions/0149_besttex_cutting_access.py"
    spec = importlib.util.spec_from_file_location("besttex_grant", path)
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    with SessionLocal() as db:
        account = User(name="Besttex", email="besttex@milanapremium.uz", password_hash="unused", factory_code="BST",
                       extra_permissions=["sewing.records"], access_policy={"BST": {"allow": ["sewing.flows"], "deny": ["finance.view"]},
                       "ECO": {"allow": ["payroll.view"], "deny": []}})
        other = User(name="Other", email="other-besttex@example.test", password_hash="unused", factory_code="BST", extra_permissions=[])
        db.add_all([account, other]); db.commit()
        monkeypatch.setattr(migration.op, "get_bind", lambda: db.connection())
        migration.upgrade(); db.commit(); db.expire_all()
        assert account.extra_permissions == ["sewing.records", "besttex.cutting_sheets"]
        assert account.access_policy["BST"] == {"allow": ["sewing.flows", "besttex.cutting_sheets"], "deny": ["finance.view"]}
        assert account.access_policy["ECO"] == {"allow": ["payroll.view"], "deny": []}
        assert other.extra_permissions == []
        first = (account.extra_permissions, account.access_policy)
        migration.upgrade(); db.commit(); db.expire_all()
        assert (account.extra_permissions, account.access_policy) == first
