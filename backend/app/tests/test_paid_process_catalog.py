import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.db.session import SessionLocal
from app.models import AuditLog
from app.models.paid_process import PaidProcess
from app.services.paid_process_catalog import normalized_key, normalized_name, process_section
from app.tests.test_payroll import _create_user_with_permissions


def _create(client, headers, name, section="sewing", **extra):
    return client.post("/api/paid-processes", headers=headers, json={"name": name, "section": section, **extra})


def test_catalog_deduplicates_name_and_preserves_section_identity_without_rates(client, auth_headers):
    first = _create(client, auth_headers, "  Pocket   Sewing ", rate=123, rate_per_piece=456, factory_code="ECO")
    assert first.status_code == 200, first.text
    for name in ("pocket sewing", "POCKET\tSEWING", "Ｐｏｃｋｅｔ Sewing"):
        again = _create(client, auth_headers, name)
        assert again.status_code == 200, again.text
        assert again.json() == first.json()
    same_name_other_section = _create(client, auth_headers, "pocket sewing", "control")
    assert same_name_other_section.json()["id"] != first.json()["id"]
    assert first.json()["name"] == "Pocket Sewing"
    assert first.json()["code"].startswith("OP-")
    assert set(first.json()) == {"id", "code", "name", "section"}
    with SessionLocal() as db:
        saved = db.get(PaidProcess, first.json()["id"])
        assert saved.factory_code == "MIL"
        assert saved.normalized_name == "pocket sewing"
        assert db.query(AuditLog).filter(AuditLog.entity_type == "PaidProcess", AuditLog.entity_id == saved.id).count() == 1


def test_catalog_isolates_factory_and_allows_code_search(client, auth_headers):
    mil = _create_user_with_permissions(client, auth_headers, email="catalog-mil@example.com", permissions=["payroll.manage"], factory_code="MIL")
    eco = _create_user_with_permissions(client, auth_headers, email="catalog-eco@example.com", permissions=["payroll.manage"], factory_code="ECO")
    a = _create(client, mil, "Exact scope process").json()
    b = _create(client, eco, "Exact scope process").json()
    assert a["id"] != b["id"]
    assert a["code"] != b["code"]
    for headers, expected, hidden in ((mil, a, b), (eco, b, a)):
        rows = client.get("/api/paid-processes", headers=headers, params={"search": "exact scope"}).json()["items"]
        assert rows == [expected]
        assert client.get("/api/paid-processes", headers=headers, params={"search": expected["code"].lower()}).json()["items"] == [expected]
        assert client.get("/api/paid-processes", headers=headers, params={"search": hidden["code"]}).json()["items"] == []


def test_catalog_search_escapes_percent_underscore_and_backslash(client, auth_headers):
    expected = {}
    for name in ("100% inspection", "a_b join", "a\\b join", "ordinary seam", "axb join", "1000 inspection"):
        result = _create(client, auth_headers, name)
        assert result.status_code == 200, result.text
        expected[name] = result.json()
    for search, name in (("%", "100% inspection"), ("_", "a_b join"), ("\\", "a\\b join")):
        result = client.get("/api/paid-processes", headers=auth_headers, params={"search": search})
        assert result.status_code == 200, result.text
        assert result.json()["items"] == [expected[name]]


@pytest.mark.parametrize("permissions,allowed", [(["payroll.manage"], True), (["modeling.models"], True), (["payroll.scan"], False), (["payroll.view"], False)])
def test_catalog_permissions(client, auth_headers, permissions, allowed):
    headers = _create_user_with_permissions(client, auth_headers, email="catalog-access@example.com", permissions=permissions)
    assert client.get("/api/paid-processes", headers=headers).status_code == (200 if allowed else 403)
    assert _create(client, headers, "Scoped seam").status_code == (200 if allowed else 403)


@pytest.mark.parametrize("name,section", [(" ", "sewing"), ("Name", "unknown"), ("x" * 256, "control")])
def test_catalog_rejects_invalid_identity(client, auth_headers, name, section):
    response = _create(client, auth_headers, name, section)
    assert response.status_code == 422, response.text
    with SessionLocal() as db:
        assert db.query(PaidProcess).count() == 0


@pytest.mark.parametrize("name", ["ß" * 255, "\ufdfa" * 255])
def test_catalog_preserves_expanding_unicode_names(client, auth_headers, name):
    result = _create(client, auth_headers, name)
    assert result.status_code == 200, result.text
    with SessionLocal() as db:
        row = db.get(PaidProcess, result.json()["id"])
        assert row.normalized_name == normalized_name(name)
        assert row.normalized_key == normalized_key(name)
        assert len(row.normalized_key) == 64
        assert isinstance(PaidProcess.__table__.c.normalized_name.type, sa.Text)


@pytest.mark.parametrize("source,expected", [("Контроль", "control"), ("Tikuv", "tikuv"), ("control", "control"), ("cutting", "cutting"), ("Глажка", "pressing"), ("buttons", "buttons")])
def test_catalog_resolves_real_source_stage(source, expected):
    assert process_section({"section": "sewing", "sourceStage": source}) == expected


def test_catalog_migration_deduplicates_scope_and_preserves_every_model_snapshot():
    path = Path(__file__).parents[2] / "alembic" / "versions" / "0118_paid_process_catalog.py"
    spec = importlib.util.spec_from_file_location("paid_process_catalog_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    models = sa.Table("models", metadata, sa.Column("id", sa.Integer, primary_key=True), sa.Column("catalog_scope", sa.String), sa.Column("details_json", sa.JSON))
    metadata.create_all(engine)
    first = {"general": {"model_no": "XJ5614"}, "paid_operations": [
        {"id": "original-op-1", "name": "Pocket seam", "section": "sewing", "sewingFactory": "milana", "price": 100},
        {"id": "original-op-2", "name": "  POCKET  SEAM ", "section": "sewing", "sewingFactory": "milana", "price": 250},
        {"id": "original-op-3", "name": "Control check", "section": "sewing", "sourceStage": "Контроль", "sewingFactory": "besttex", "price": 500},
        {"id": "shared-op", "name": "Shared seam", "section": "sewing", "price": 12},
        {"id": "invalid-factory", "name": "Invalid scoped seam", "section": "sewing", "sewingFactory": "unknown-factory", "price": 18},
        {"id": "oversized-normalization", "name": "\ufdfa" * 255, "section": "sewing", "price": 24},
    ]}
    second = {"paidOperations": [{"id": "second-op", "name": "pocket seam", "section": "sewing", "sewingFactory": "milana", "price": 900}]}
    service = {"paid_operations": [{"name": "Usluga private operation", "price": 888}]}
    snapshots = deepcopy([first, second, service])
    with engine.begin() as connection:
        connection.execute(models.insert(), [{"id": index + 1, "catalog_scope": "usluga" if index == 2 else "standard", "details_json": row} for index, row in enumerate(snapshots)])
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            rows = connection.execute(sa.text("SELECT factory_code, normalized_name, normalized_key, section, code FROM paid_processes ORDER BY id")).mappings().all()
            assert {(r["factory_code"], r["normalized_name"], r["section"]) for r in rows} == {
                ("MIL", "pocket seam", "sewing"), ("BST", "control check", "control"),
                ("MIL", "shared seam", "sewing"), ("BST", "shared seam", "sewing"), ("ECO", "shared seam", "sewing"),
                ("MIL", normalized_name("\ufdfa" * 255), "sewing"), ("BST", normalized_name("\ufdfa" * 255), "sewing"), ("ECO", normalized_name("\ufdfa" * 255), "sewing"),
            }
            assert len({row["code"] for row in rows}) == len(rows)
            assert all(row["normalized_key"] == normalized_key(row["normalized_name"]) for row in rows)
            assert connection.execute(sa.select(models.c.details_json).order_by(models.c.id)).scalars().all() == snapshots
            with pytest.raises(RuntimeError, match="Preserve"):
                migration.downgrade()
