from copy import deepcopy

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import sessionmaker

from app.schemas import Model, ModelSize
from app.models.catalog import models_service
from app.tests.conftest import TestSessionLocal
from app.tests.test_catalog_family_operations_query_growth import catalog_postgres as catalog_postgres
from app.tests.test_paid_operation_factory_scope import _create_payroll_manager, _operation


def _model(code, *, variant="", operations=None, scope="standard", factory=None, legacy=False, alias=False):
    details = {"general": {"model_no": "QRBASE", "variant_no": variant}, "note": code}
    if operations is not None:
        details["paidOperations" if alias else "paid_operations"] = deepcopy(operations)
    if legacy:
        details["legacy_import"] = True
    with TestSessionLocal() as db:
        row = Model(code=code, name=code, catalog_scope=scope, factory_code=factory, details_json=details)
        db.add(row)
        db.flush()
        db.add(ModelSize(model_id=row.id, size="48"))
        db.commit()
        return row.id


def _read(client, headers, mid, *, projected=True, scope="standard"):
    prefix = "/api/usluga" if scope == "usluga" else "/api"
    response = client.get(f"{prefix}/models/{mid}", headers=headers,
                          params={"paid_operations_from_model": projected})
    assert response.status_code == 200, response.text
    return response.json()


def test_process_qr_uses_base_operations_preserves_variant_and_generic_get(client, auth_headers):
    base_ops = [_operation("base-op", "milana")]
    _model("QRBASE", operations=base_ops)
    mid = _model("QRBASE-V-1", variant="1", operations=[_operation("old-variant", "milana")])
    original = _read(client, auth_headers, mid, projected=False)
    projected = _read(client, auth_headers, mid)
    assert projected["details_json"]["paid_operations"] == base_ops
    assert {k: v for k, v in projected.items() if k != "details_json"} == {
        k: v for k, v in original.items() if k != "details_json"}
    assert projected["details_json"]["general"] == original["details_json"]["general"]
    assert projected["details_json"]["note"] == original["details_json"]["note"]
    assert _read(client, auth_headers, mid, projected=False) == original
    assert client.get(f"/api/models/{mid}", headers=auth_headers).json() == original


@pytest.mark.parametrize("operations", [None, []])
def test_empty_base_is_authoritative_over_populated_variant(client, auth_headers, operations):
    _model("QRBASE", operations=operations)
    mid = _model("QRBASE-V-1", variant="1", operations=[_operation("obsolete", "milana")], alias=True)
    details = _read(client, auth_headers, mid)["details_json"]
    assert details["paid_operations"] == []
    assert "paidOperations" not in details


def test_legacy_alias_and_factory_filter_apply_to_base(client, auth_headers):
    _model("QRBASE", operations=[_operation("mil", "milana"), _operation("bst", "besttex")], alias=True)
    mid = _model("QRBASE-V-1", variant="1", operations=[])
    headers = _create_payroll_manager(client, auth_headers, "BST")
    assert _read(client, headers, mid)["details_json"]["paid_operations"] == [_operation("bst", "besttex")]


def test_without_base_uses_selected_variant_not_sibling(client, auth_headers):
    own = [_operation("own", "milana")]
    mid = _model("QRBASE-V-1", variant="1", operations=own)
    _model("QRBASE-V-2", variant="2", operations=[_operation("sibling", "milana")])
    assert _read(client, auth_headers, mid)["details_json"]["paid_operations"] == own


def test_projection_excludes_other_factory_catalog_and_legacy_donors(client, auth_headers):
    own = [_operation("own", "milana")]
    mid = _model("QRBASE-V-1", variant="1", operations=own)
    _model("OTHER-FACTORY", factory="BST", operations=[_operation("bst", "besttex")])
    _model("USLUGA-BASE", scope="usluga", factory="ECO", operations=[_operation("eco", "eco_cotton")])
    _model("IMPORT-BASE", legacy=True, operations=[_operation("import", "milana")])
    assert _read(client, auth_headers, mid)["details_json"]["paid_operations"] == own


def test_requested_legacy_model_does_not_borrow_public_base(client, auth_headers):
    _model("QRBASE", operations=[_operation("public", "milana")])
    own = [_operation("import-own", "milana")]
    mid = _model("IMPORT-QRBASE-V-1", variant="1", legacy=True, operations=own)
    assert _read(client, auth_headers, mid)["details_json"]["paid_operations"] == own


def test_usluga_alias_uses_eco_base_and_keeps_catalog_denial(client, auth_headers):
    _model("QRBASE", operations=[_operation("standard", "milana")])
    eco = [_operation("eco", "eco_cotton")]
    _model("USL-QRBASE", scope="usluga", factory="ECO", operations=eco)
    mid = _model("USL-QRBASE-V-1", scope="usluga", factory="ECO", variant="1", operations=[])
    headers = _create_payroll_manager(client, auth_headers, "ECO")
    assert _read(client, headers, mid, scope="usluga")["details_json"]["paid_operations"] == eco
    assert client.get(f"/api/models/{mid}?paid_operations_from_model=true", headers=auth_headers).status_code == 404


def test_duplicate_base_uses_catalog_latest_representative(client, auth_headers):
    _model("FIRST-BASE", operations=[_operation("first", "milana")])
    last = [_operation("latest", "milana")]
    _model("LATEST-BASE", operations=last)
    mid = _model("QRBASE-V-1", variant="1", operations=[])
    assert _read(client, auth_headers, mid)["details_json"]["paid_operations"] == last


def test_postgres_projection_is_indexed_bounded_read_only(catalog_postgres):  # noqa: F811
    sessions = sessionmaker(bind=catalog_postgres, expire_on_commit=False)
    operations = [_operation("base", "milana")]
    with sessions.begin() as db:
        base = Model(code="QR-PG-BASE", name="Base", factory_code="MIL",
                     details_json={"general": {"model_no": "QR-PG"}, "paid_operations": operations})
        variant = Model(code="QR-PG-V-1", name="Variant", factory_code="MIL",
                        details_json={"general": {"model_no": "QR-PG", "variant_no": "1"}, "note": "keep", "paid_operations": []})
        excluded = Model(code="QR-PG-BST", name="Other factory", factory_code="BST",
                         details_json={"general": {"model_no": "QR-PG"}, "paid_operations": [_operation("wrong", "besttex")]})
        db.add_all([base, variant, excluded])
        db.add_all([Model(code=f"QR-PG-FILLER-{i}", name="Unrelated", factory_code="MIL") for i in range(100)])
        db.flush()
        mid = variant.id
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    with sessions() as db:
        db.execute(text("SET TRANSACTION READ ONLY"))
        original = db.get(Model, mid)
        before = db.execute(text("SELECT md5(string_agg(t::text, '' ORDER BY id)) FROM models t")).scalar_one()
        event.listen(catalog_postgres, "before_cursor_execute", capture)
        try:
            for _ in range(25):
                details = models_service._process_qr_paid_operation_details(db, original)
                assert details["paid_operations"] == operations
                assert details["general"]["variant_no"] == "1" and details["note"] == "keep"
        finally:
            event.remove(catalog_postgres, "before_cursor_execute", capture)
        assert len(statements) == 25
        assert all("models.model_group_key =" in sql and "models.factory_code =" in sql for sql in statements)
        assert db.execute(text("SELECT md5(string_agg(t::text, '' ORDER BY id)) FROM models t")).scalar_one() == before
