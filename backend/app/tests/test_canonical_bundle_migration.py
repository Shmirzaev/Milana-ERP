import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import BusinessOrderAlias
from app.services.numbering import next_bundle_no


path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0120_canonical_bundle_references.py"
spec = importlib.util.spec_from_file_location("canonical_bundle_migration", path)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


@pytest.fixture
def bundle_db():
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    bundles = sa.Table("bundles", metadata,
                       sa.Column("id", sa.Integer, primary_key=True),
                       sa.Column("bundle_no", sa.String(64), unique=True, nullable=False),
                       sa.Column("barcode", sa.String(64), unique=True),
                       sa.Column("qr_code_url", sa.String(512)),
                       sa.Column("production_order_id", sa.Integer),
                       sa.Column("quantity", sa.Integer))
    metadata.create_all(engine)
    BusinessOrderAlias.__table__.create(engine)
    yield engine, bundles
    engine.dispose()


def test_mapping_preserves_canonical_unique_suffixes_and_resolves_collisions():
    rows = [dict(id=1, reference="BND-0005"), dict(id=2, reference="BND-2026-000005"),
            dict(id=3, reference="BND-2025-000202"), dict(id=4, reference="BND-2026-000202"),
            dict(id=5, reference="Manual bundle"), dict(id=6, reference="BND-2026-100000"),
            dict(id=7, reference="BND-2026-000033")]
    plans = migration.plan_bundles(rows)
    assert plans == migration.plan_bundles(list(reversed(rows)))
    result = {row["entity_id"]: row["canonical_reference"] for row in plans}
    assert result[1] == "BND-0005" and result[7] == "BND-0033"
    assert len(set(result.values())) == len(rows)
    assert all(len(value) == 8 for value in result.values())
    assert result[3] != result[4]


def test_mapping_respects_deleted_identity_reservations_and_fails_at_capacity():
    aliases = [dict(entity_id=10000 + number, reference=f"BND-{number:04d}",
                    canonical_reference=f"BND-{number:04d}") for number in range(1, 10000)]
    with pytest.raises(RuntimeError, match="exhausted"):
        migration.plan_bundles([dict(id=1, reference="BND-2026-000001")], aliases)
    with pytest.raises(RuntimeError, match="more than 9999"):
        migration.plan_bundles([dict(id=number, reference=f"BND-2026-{number:06d}") for number in range(10000)])
    with pytest.raises(RuntimeError, match="conflicts with historical alias"):
        migration.plan_bundles([dict(id=1, reference="BND-0001")], aliases[:1])
    result = migration.plan_bundles([dict(id=1, reference="BND-2026-000001")], aliases[:1])
    assert result[0]["canonical_reference"] == "BND-0002"


def test_migration_canonicalizes_935_legacy_bundles_preserving_identity_and_links(bundle_db):
    engine, bundles = bundle_db
    with engine.begin() as connection:
        connection.execute(bundles.insert(), [dict(id=number, bundle_no=f"BND-2026-{number:06d}",
                                                   barcode=f"unchanged-{number}", qr_code_url="/storage/legacy.png",
                                                   production_order_id=19, quantity=23) for number in range(1, 936)])
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        rows = connection.execute(sa.select(bundles).order_by(bundles.c.id)).mappings().all()
        for row in rows:
            number = row["id"]
            assert row["bundle_no"] == f"BND-{number:04d}"
            assert row["barcode"] == f"unchanged-{number}"
            assert row["production_order_id"] == 19 and row["quantity"] == 23
            assert row["qr_code_url"] == f"/api/barcode/bundle-image/{number}"
        aliases = connection.execute(sa.select(BusinessOrderAlias.__table__)).mappings().all()
        assert len(aliases) == 1870
        for alias in aliases:
            number = alias["entity_id"]
            assert alias["canonical_reference"] == f"BND-{number:04d}"
            assert alias["reference"] in {f"BND-{number:04d}", f"BND-2026-{number:06d}"}
    with Session(engine) as db:
        db.execute(bundles.delete().where(bundles.c.id == 935))
        assert next_bundle_no(db) == "BND-0936"
        assert next_bundle_no(db) == "BND-0937"
        db.commit()
    with Session(engine) as db:
        assert next_bundle_no(db) == "BND-0938"


def test_generator_issues_9999_then_uses_only_unreserved_gaps_and_rejects_exhaustion(bundle_db):
    engine, _ = bundle_db
    with Session(engine) as db:
        db.add(BusinessOrderAlias(namespace="BND", entity_id=2, reference="BND-9998", canonical_reference="BND-9998"))
        db.flush()
        assert next_bundle_no(db) == "BND-9999"
        assert next_bundle_no(db) == "BND-0001"
        db.execute(BusinessOrderAlias.__table__.insert(), [dict(namespace="BND", entity_id=0,
                                                               reference=f"BND-{number:04d}", canonical_reference=f"BND-{number:04d}")
                                                         for number in range(2, 9998)])
        with pytest.raises(HTTPException) as error:
            next_bundle_no(db)
        assert error.value.status_code == 409
        assert db.query(BusinessOrderAlias).count() == 9999
        assert db.query(BusinessOrderAlias).filter_by(reference="BND-10000").first() is None


def test_failed_transaction_does_not_consume_bundle_number(bundle_db):
    engine, _ = bundle_db
    with Session(engine) as db:
        assert next_bundle_no(db) == "BND-0001"
        db.rollback()
        assert next_bundle_no(db) == "BND-0001"


def test_generator_never_reissues_old_canonical_shaped_alias(bundle_db):
    engine, _ = bundle_db
    with Session(engine) as db:
        db.add(BusinessOrderAlias(namespace="BND", entity_id=9, reference="BND-9999", canonical_reference="BND-0001"))
        db.flush()
        assert next_bundle_no(db) == "BND-0002"


def test_migration_alias_conflict_fails_before_any_bundle_changes(bundle_db):
    engine, bundles = bundle_db
    with engine.begin() as connection:
        connection.execute(bundles.insert(), dict(id=1, bundle_no="BND-0001", barcode="unchanged"))
        connection.execute(BusinessOrderAlias.__table__.insert(), dict(namespace="BND", entity_id=99,
                                                                       reference="BND-0001", canonical_reference="BND-0001"))
        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(RuntimeError, match="conflicts with historical alias"):
                migration.upgrade()
        row = connection.execute(sa.select(bundles)).mappings().one()
        assert row["bundle_no"] == "BND-0001" and row["barcode"] == "unchanged" and row["qr_code_url"] is None
        assert connection.scalar(sa.select(sa.func.count()).select_from(BusinessOrderAlias.__table__)) == 1
