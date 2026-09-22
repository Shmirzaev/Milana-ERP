import base64
import hashlib
from html.parser import HTMLParser
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.orm import selectinload
from app.db.session import SessionLocal
from app.models import Bundle, Model, ModelImage, ProductionBatch
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
