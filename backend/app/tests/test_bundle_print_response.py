import base64
import hashlib
from html.parser import HTMLParser
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.orm import selectinload
from app.db.session import SessionLocal
from app.models import Bundle, Model, ModelImage, ProductionBatch, ProductionOrder
from app.api.routes import bundles as bundle_routes
from app.services.label_images import material_label_image_src
from app.tests.test_production_flow import _create_bundle_for_scan


class LabelParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.styles = []
        self.scripts = []
        self.buttons = []
        self.active = None
        self.invalid_attributes = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        self.invalid_attributes.extend(name for name, _ in attrs if name == "style" or name.startswith("on"))
        if tag in ("style", "script"):
            self.active = []
            (self.styles if tag == "style" else self.scripts).append(self.active)
        if tag == "button":
            self.buttons.append(attributes)

    def handle_data(self, data):
        if self.active is not None:
            self.active.append(data)

    def handle_endtag(self, tag):
        if tag in ("style", "script"):
            self.active = None


def assert_print_policy(response):
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/html")
    policy = response.headers["content-security-policy"]
    directives = dict(part.strip().split(" ", 1) for part in policy.split(";") if part.strip())
    assert "unsafe-inline" not in policy and "unsafe-hashes" not in policy
    assert directives["script-src-attr"] == directives["style-src-attr"] == "'none'"
    assert directives["font-src"] == "'self' data:"
    assert directives["img-src"] == "'self' data: blob:"
    assert directives["object-src"] == directives["frame-ancestors"] == "'none'"
    parser = LabelParser()
    parser.feed(response.text)
    assert parser.invalid_attributes == []
    assert parser.buttons == [{"type": "button", "id": "print-labels"}]
    assert len(parser.styles) == len(parser.scripts) == 1
    for kind, blocks in (("style", parser.styles), ("script", parser.scripts)):
        content = "".join(blocks[0])
        digest = base64.b64encode(hashlib.sha256(content.encode("utf-8")).digest()).decode("ascii")
        assert directives[f"{kind}-src"] == f"'sha256-{digest}'"
    script = "".join(parser.scripts[0])
    assert 'getElementById("print-labels").addEventListener("click"' in script
    assert "window.print();" in script
    style = "".join(parser.styles[0])
    assert "@media print" in style and "button{display:none}" in style
    assert "data:image/png;base64," in response.text
    return directives


@pytest.mark.parametrize("bundle_count", [1, 50, 200])
def test_bundle_label_context_has_constant_reference_reads_and_scalar_parity(client, auth_headers, bundle_count):
    source = _create_bundle_for_scan(client, auth_headers)
    with SessionLocal() as db:
        original = db.get(Bundle, source["id"])
        bundles = [original]
        for index in range(1, bundle_count):
            bundles.append(
                Bundle(
                    bundle_no=f"PERF12-B-{uuid4().hex[:16]}-{index}",
                    barcode=f"PERF12-BC-{uuid4().hex[:16]}-{index}",
                    production_order_id=original.production_order_id,
                    production_batch_id=original.production_batch_id,
                    sales_order_id=original.sales_order_id,
                    model_id=original.model_id,
                    color=original.color,
                    size=original.size,
                    quantity=original.quantity,
                    status=original.status,
                    created_by=original.created_by,
                )
            )
        db.add_all(bundles[1:])
        db.flush()
        scalar = bundle_routes._label_context(db, bundles[0])
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            context = bundle_routes._bundle_label_reference_context(db, bundles)
            batched = bundle_routes._label_context(db, bundles[0], context)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert batched == scalar
    assert len(statements) <= 8, statements
    assert all("file_data" not in statement.lower() for statement in statements)
    normalized = [statement.lower() for statement in statements]
    production_order_reads = [statement for statement in normalized if "production_orders.production_no" in statement]
    assert production_order_reads, normalized
    assert all("production_orders.production_no" in statement for statement in production_order_reads)
    assert all("production_orders.sales_order_id" in statement for statement in production_order_reads)
    assert all("production_orders.printing_attachments" not in statement for statement in production_order_reads)
    assert not any(" from production_order_materials " in statement for statement in normalized)


@pytest.mark.parametrize("bundle_count", [1, 50, 200])
def test_bundle_label_sheet_batches_qr_references_and_bounds_rendering(
    client,
    auth_headers,
    monkeypatch,
    bundle_count,
):
    source = _create_bundle_for_scan(client, auth_headers)
    with SessionLocal() as db:
        original = db.get(Bundle, source["id"])
        bundles = [original]
        for index in range(1, bundle_count):
            bundles.append(Bundle(
                bundle_no=f"PERF12-QR-{uuid4().hex[:16]}-{index}",
                barcode=f"PERF12-QR-BC-{uuid4().hex[:16]}-{index}",
                production_order_id=original.production_order_id,
                production_batch_id=original.production_batch_id,
                sales_order_id=original.sales_order_id,
                model_id=original.model_id,
                color=original.color,
                size=original.size,
                quantity=original.quantity,
                status=original.status,
                created_by=original.created_by,
            ))
        db.add_all(bundles[1:])
        db.commit()
        bundle_ids = [int(bundle.id) for bundle in bundles]
        bundle_nos = [bundle.bundle_no for bundle in bundles]
        bind = db.bind

    qr_payloads = []
    monkeypatch.setattr(
        bundle_routes,
        "qr_png_data_uri",
        lambda payload: qr_payloads.append(payload) or "data:image/png;base64,AA==",
    )
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(bind, "before_cursor_execute", capture)
    try:
        response = client.get(
            "/api/bundles/label-sheet/by-ids",
            params={"ids": ",".join(str(bundle_id) for bundle_id in bundle_ids)},
            headers=auth_headers,
        )
    finally:
        event.remove(bind, "before_cursor_execute", capture)

    assert response.status_code == 200, response.text
    assert response.text.count("class='label'") == bundle_count
    assert len(qr_payloads) == bundle_count
    assert bundle_nos[0] in response.text and bundle_nos[-1] in response.text
    assert len(statements) == 7, statements


def test_batched_bundle_qr_keeps_orphan_scalar_parity(monkeypatch):
    with SessionLocal() as db:
        order = ProductionOrder(
            production_no=f"PERF12-QR-ORPHAN-{uuid4().hex[:12]}",
            production_type="branded_stock",
            model_id=1,
            planned_quantity=1,
        )
        db.add(order)
        db.flush()
        batch = ProductionBatch(
            production_order_id=order.id,
            batch_no="ORPHAN",
            batch_index=1,
            planned_quantity=1,
        )
        db.add(batch)
        db.flush()
        orphan = Bundle(
            bundle_no="PERF12-ORPHAN",
            barcode="PERF12-ORPHAN-BC",
            production_order_id=2_147_483_647,
            production_batch_id=batch.id,
            model_id=1,
            color="white",
            size="M",
            quantity=1,
        )
        scalar = bundle_routes.bundle_qr_payload(db, orphan)
        monkeypatch.setattr(bundle_routes, "qr_png_data_uri", lambda payload: payload)
        batched = bundle_routes._qr_data_uri_for_bundle(
            db,
            orphan,
            {
                "production_orders": {},
                "batches": {int(batch.id): batch},
            },
        )

    assert scalar == batched == "BUNDLE:PERF12-ORPHAN|PERF12-ORPHAN-BC"


@pytest.mark.parametrize("bundle_count", [1, 50, 200])
@pytest.mark.parametrize("sheet_scope", ["production-order", "batch"])
def test_scoped_bundle_label_sheets_reuse_their_bounded_bundle_query(
    client,
    auth_headers,
    monkeypatch,
    bundle_count,
    sheet_scope,
):
    suffix = uuid4().hex[:12].upper()
    with SessionLocal() as db:
        order = ProductionOrder(
            production_no=f"PERF12-SHEET-{suffix}",
            production_type="branded_stock",
            model_id=1,
            status="packaging",
            planned_quantity=bundle_count,
        )
        db.add(order)
        db.flush()
        batch = ProductionBatch(
            production_order_id=order.id,
            batch_no=f"BT-{suffix}",
            batch_index=1,
            planned_quantity=bundle_count,
        )
        db.add(batch)
        db.flush()
        bundles = [
            Bundle(
                bundle_no=f"PERF12-SCOPE-{suffix}-{index:04d}",
                barcode=f"PERF12-SCOPE-BC-{suffix}-{index:04d}",
                production_order_id=order.id,
                production_batch_id=batch.id,
                model_id=1,
                color="white",
                size="M",
                quantity=1,
                status="created",
            )
            for index in range(bundle_count)
        ]
        db.add_all(bundles)
        db.commit()
        order_id = int(order.id)
        batch_id = int(batch.id)
        expected_ids = [int(bundle.id) for bundle in bundles]
        expected_numbers = [bundle.bundle_no for bundle in bundles]

    monkeypatch.setattr(
        bundle_routes,
        "_qr_data_uri_for_bundle",
        lambda _db, _bundle, *_args: "data:image/png;base64,AA==",
    )
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    route = (
        f"/api/bundles/label-sheet/by-production-order/{order_id}"
        if sheet_scope == "production-order"
        else f"/api/bundles/label-sheet/by-batch/{batch_id}"
    )
    bind = SessionLocal.kw["bind"]
    event.listen(bind, "before_cursor_execute", capture)
    try:
        response = client.get(route, headers=auth_headers)
    finally:
        event.remove(bind, "before_cursor_execute", capture)

    assert response.status_code == 200, response.text
    assert response.text.count("class='label'") == bundle_count
    assert expected_numbers[0] in response.text
    assert expected_numbers[-1] in response.text
    bundle_selects = [statement for statement in statements if " from bundles " in statement]
    assert len(bundle_selects) == 1, bundle_selects

    by_ids = client.get(
        "/api/bundles/label-sheet/by-ids?ids=" + ",".join(str(bundle_id) for bundle_id in expected_ids),
        headers=auth_headers,
    )
    assert by_ids.status_code == 200, by_ids.text
    assert response.text == by_ids.text


def test_bundle_label_sheet_enforces_output_cap_before_loading(client, auth_headers):
    exact_ids = ",".join(str(900_000 + index) for index in range(200))
    exact = client.get(
        f"/api/bundles/label-sheet/by-ids?ids={exact_ids}",
        headers=auth_headers,
    )
    assert exact.status_code == 404, exact.text

    too_many_ids = f"{exact_ids},999999"
    too_many = client.get(
        f"/api/bundles/label-sheet/by-ids?ids={too_many_ids}",
        headers=auth_headers,
    )
    assert too_many.status_code == 413, too_many.text
    assert too_many.json()["detail"] == "A label sheet may contain at most 200 bundles"


def test_bundle_label_image_projection_does_not_lazy_load_file_data(client, auth_headers):
    source = _create_bundle_for_scan(client, auth_headers)
    with SessionLocal() as db:
        bundle = db.get(Bundle, source["id"])
        db.add(ModelImage(
            model_id=bundle.model_id,
            file_url="https://cdn.example.test/material.png",
            content_type="image/png",
            file_data=b"should-not-be-selected",
            image_type="material",
            is_primary=True,
        ))
        db.flush()
        model = (
            db.query(Model)
            .options(selectinload(Model.images).load_only(
                ModelImage.id,
                ModelImage.model_id,
                ModelImage.file_url,
                ModelImage.file_name,
                ModelImage.content_type,
                ModelImage.image_type,
                ModelImage.is_primary,
            ))
            .filter(Model.id == bundle.model_id)
            .one()
        )
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            assert material_label_image_src(model) == "https://cdn.example.test/material.png"
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert all("file_data" not in statement.lower() for statement in statements)


def test_all_bundle_label_routes_allow_exact_style_script_and_embedded_fonts(client, auth_headers, monkeypatch):
    bundle = _create_bundle_for_scan(client, auth_headers)
    # Include font data in the style hash rather than opening styles globally.
    from app.api.routes import bundles
    monkeypatch.setattr(bundles, "_unicode_label_font_css", lambda: "@font-face{font-family:Fixture;src:url(data:font/ttf;base64,AA==)}")
    with SessionLocal() as db:
        batch = ProductionBatch(production_order_id=bundle["production_order_id"], batch_no="CSP-FIXTURE", batch_index=99)
        db.add(batch)
        db.flush()
        db.get(Bundle, bundle["id"]).production_batch_id = batch.id
        batch_id = batch.id
        db.commit()
    routes = [f"/api/bundles/{bundle['id']}/label",
              f"/api/bundles/label-sheet/by-ids?ids={bundle['id']}",
              f"/api/bundles/label-sheet/by-production-order/{bundle['production_order_id']}",
              f"/api/bundles/label-sheet/by-batch/{batch_id}"]
    for route in routes:
        response = client.get(route, headers=auth_headers)
        assert_print_policy(response)
        assert "data:font/ttf;base64,AA==" in response.text
    ordinary = client.get(f"/api/bundles/{bundle['id']}", headers=auth_headers)
    assert ordinary.status_code == 200
    assert "script-src" not in ordinary.headers["content-security-policy"]
    assert "style-src" not in ordinary.headers["content-security-policy"]


def test_bundle_label_escapes_user_content_without_extending_allowed_script(client, auth_headers):
    bundle = _create_bundle_for_scan(client, auth_headers)
    with SessionLocal() as db:
        saved = db.get(Bundle, bundle["id"])
        saved.color = "</style><script>alert(1)</script>"
        db.commit()
    response = client.get(f"/api/bundles/{bundle['id']}/label", headers=auth_headers)
    assert_print_policy(response)
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text
