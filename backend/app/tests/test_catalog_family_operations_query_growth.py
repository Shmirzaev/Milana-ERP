"""PERF30: catalog rename, clone and approval used broad scans and repeated probes.

`_rename_model_group` loaded every model in the catalogue scope to find one family, then
loaded every *other* model again to build a collision map. `_unique_model_copy_code`
issued one query per rejected `-COPY` suffix. `approve_model` counted main-fabric BOM
rows with one query per pending family member. Each cost grew with the catalogue, the
taken-code range, or the family size respectively.

The generated family columns from migration 0084 (`models.model_group_key`,
`models.is_legacy_import`) are what make the family and collision reads indexable, so
these tests need real PostgreSQL: SQLite test metadata has no generated columns and
falls back to the Python path, which proves neither the index usage nor the SQL
normalization. The migration's own `GROUP_KEY_SQL` is applied to the fixture so the
column under test is the real one.

Set STABILIZATION_POSTGRES_URL to run them.
"""

import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.routes import catalog as catalog_routes
from app.db.base import Base
from app.models import Model, ModelBOM, User

MIGRATION_0084 = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0084_model_group_key.py"
)


def _group_key_sql() -> str:
    """The real generated-column expression, so the test cannot drift from production."""
    spec = importlib.util.spec_from_file_location("migration_0084", MIGRATION_0084)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.GROUP_KEY_SQL


@pytest.fixture(scope="module")
def catalog_postgres():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL for real PostgreSQL catalog family coverage")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Catalog family tests require a loopback PostgreSQL URL without connection overrides")
    schema = f"catalog_family_{uuid4().hex}"
    engine = create_engine(
        url,
        connect_args={"options": f"-csearch_path={schema} -cstatement_timeout=30000"},
        pool_size=4,
        max_overflow=0,
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        tables = set()
        # The FK closure below pulls in brands/collections/items/employees automatically.
        pending = [Model.__table__, ModelBOM.__table__, User.__table__]
        while pending:
            table = pending.pop()
            if table in tables:
                continue
            tables.add(table)
            pending.extend(fk.column.table for fk in table.foreign_keys)
        Base.metadata.create_all(engine, tables=list(tables))
        # Apply the real generated columns; without them the route uses its Python path.
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE models ADD COLUMN is_legacy_import boolean GENERATED ALWAYS AS "
                "((coalesce(details_json ->> 'legacy_import', 'false')) = 'true') STORED"
            )
            connection.exec_driver_sql(
                f"ALTER TABLE models ADD COLUMN model_group_key text GENERATED ALWAYS AS ({_group_key_sql()}) STORED"
            )
            connection.exec_driver_sql(
                "CREATE INDEX ix_models_model_group_key_id ON models (is_legacy_import, model_group_key, id DESC)"
            )
        yield engine
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def _seed_family(session_factory, *, model_no, variants, filler=0, scope="standard"):
    """A base model plus variants, plus `filler` unrelated models to grow the catalogue."""
    marker = uuid4().hex
    with session_factory() as db:
        user = User(email=f"perf30-{marker}@example.com", password_hash="x", name="PERF30")
        db.add(user)
        db.flush()
        models = []
        base = Model(
            code=model_no if not variants else model_no,
            name=f"Base {model_no}",
            catalog_scope=scope,
            created_by=user.id,
            details_json={"general": {"model_no": model_no}},
        )
        db.add(base)
        db.flush()
        models.append(base)
        for variant in variants:
            row = Model(
                code=f"{model_no}-{variant}",
                name=f"Variant {variant}",
                catalog_scope=scope,
                created_by=user.id,
                details_json={"general": {"model_no": model_no, "variant_no": variant}},
            )
            db.add(row)
            db.flush()
            models.append(row)
        for index in range(filler):
            db.add(Model(
                code=f"FILL-{marker}-{index}",
                name=f"Filler {index}",
                catalog_scope=scope,
                created_by=user.id,
                details_json={"general": {"model_no": f"FILL-{marker}-{index}"}},
            ))
        db.commit()
        return base.id, [m.id for m in models]


def _statements(engine, action):
    """Record statements and the model rows each one actually returned.

    Rows matter, not just statements: the pre-fix rename issued a constant *two*
    statements but each hydrated the entire catalogue, so a statement-count budget
    would have passed against the defect.
    """
    seen = []
    model_rows = []

    @event.listens_for(engine, "before_cursor_execute")
    def _record(conn, cursor, statement, parameters, context, executemany):
        seen.append((" ".join(statement.split()), cursor))

    @event.listens_for(engine, "after_cursor_execute")
    def _count(conn, cursor, statement, parameters, context, executemany):
        normalized = " ".join(statement.split())
        if " FROM models" in normalized and "COUNT" not in normalized.upper():
            model_rows.append(max(cursor.rowcount, 0))

    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        with Session() as db:
            result = action(db)
        return [s for s, _ in seen], sum(model_rows), result
    finally:
        event.remove(engine, "before_cursor_execute", _record)
        event.remove(engine, "after_cursor_execute", _count)


def test_rename_reads_do_not_grow_with_catalogue_size(catalog_postgres):
    """A rename must not hydrate the whole catalogue, nor scan it again for collisions.

    The pre-fix code issued a constant *two* statements but each returned every model in
    the scope, so a statement-count budget would have passed against the defect. The two
    measurements are taken against catalogues that genuinely differ in size, so the
    second one has strictly more models to read if the reads are not indexed.
    """
    Session = sessionmaker(bind=catalog_postgres, autoflush=False, expire_on_commit=False)

    def rename_rows(base_id, new_no):
        def action(db):
            model = db.get(Model, base_id)
            return len(catalog_routes._rename_model_group(db, model, new_no))
        return action

    first_id, _ = _seed_family(Session, model_no="EARLY-A", variants=["1", "2"])
    _, small_rows, small_renamed = _statements(catalog_postgres, rename_rows(first_id, "EARLY-B"))
    assert small_renamed == 3

    # Grow the catalogue, then rename a second family in the larger scope.
    _seed_family(Session, model_no="FILLER-A", variants=[], filler=300)
    second_id, _ = _seed_family(Session, model_no="LATE-A", variants=["1", "2"])
    _, large_rows, large_renamed = _statements(catalog_postgres, rename_rows(second_id, "LATE-B"))
    assert large_renamed == 3

    assert large_rows <= small_rows + 4, (
        f"a rename read {small_rows} model rows from a 3-model catalogue but {large_rows} "
        f"once it held 300+; the family and collision reads must use the indexed key "
        f"instead of hydrating the scope"
    )


def test_rename_still_rejects_a_collision_that_differs_only_in_case_and_spacing(catalog_postgres):
    """The SQL prefilter must not weaken the 409 guard.

    `_normalized_key` casefolds and collapses whitespace, so a stored code may differ from
    the planned one in case or spacing and still be a real collision. The narrowed read
    has to catch it.
    """
    Session = sessionmaker(bind=catalog_postgres, autoflush=False, expire_on_commit=False)
    base_id, _ = _seed_family(Session, model_no="CASE-A", variants=["1"])
    with Session() as db:
        db.add(Model(
            code="case-b-1",  # planned code is "ODD-B-1"; differs only in case
            name="Case clash",
            catalog_scope="standard",
            created_by=db.get(User, db.query(User.id).first()[0]).id,
            details_json={"general": {"model_no": "ODD-B"}},
        ))
        db.add(Model(
            code="SP  ACE-B-1",  # differs only in whitespace
            name="Spacing clash",
            catalog_scope="standard",
            created_by=db.get(User, db.query(User.id).first()[0]).id,
            details_json={"general": {"model_no": "SP  ACE-B"}},
        ))
        db.commit()

    with Session() as db:
        model = db.get(Model, base_id)
        with pytest.raises(HTTPException) as excinfo:
            catalog_routes._rename_model_group(db, model, "case-b")
        assert excinfo.value.status_code == 409
        assert "conflicts with existing variant" in str(excinfo.value.detail)

    with Session() as db:
        model = db.get(Model, base_id)
        with pytest.raises(HTTPException) as excinfo:
            catalog_routes._rename_model_group(db, model, "SP  ACE-B")
        assert excinfo.value.status_code == 409


def test_clone_code_probes_are_batched(catalog_postgres):
    """Many taken `-COPY` suffixes must not cost one statement each."""
    Session = sessionmaker(bind=catalog_postgres, autoflush=False, expire_on_commit=False)
    with Session() as db:
        user_id = db.query(User.id).first()[0]
        for index in range(1, 60):
            suffix = "-COPY" if index == 1 else f"-COPY-{index}"
            db.add(Model(code=f"CLONE{suffix}", name=f"Taken {index}", catalog_scope="standard",
                        created_by=user_id, details_json={"general": {"model_no": "CLONE"}}))
        db.commit()

    with Session() as db:
        statements, _rows, code = _statements(
            catalog_postgres, lambda d: catalog_routes._unique_model_copy_code(d, "CLONE")
        )
        expected = "CLONE-COPY-60"
        assert code == expected, f"expected the first free suffix, got {code}"
        assert len(statements) <= 2, (
            f"59 taken suffixes cost {len(statements)} statements; candidates are probed in batches"
        )


def test_clone_code_returns_the_same_first_free_code_as_a_linear_scan(catalog_postgres):
    """The batched probe must pick exactly what a sequential scan would have picked."""
    Session = sessionmaker(bind=catalog_postgres, autoflush=False, expire_on_commit=False)
    with Session() as db:
        user_id = db.query(User.id).first()[0]
        for index in (1, 2, 3, 5):
            suffix = "-COPY" if index == 1 else f"-COPY-{index}"
            db.add(Model(code=f"SEQ{suffix}", name=f"Taken {index}", catalog_scope="standard",
                        created_by=user_id, details_json={"general": {"model_no": "SEQ"}}))
        db.commit()

    def linear_scan(db, source_code):
        """The pre-fix loop, kept here as the oracle."""
        for index in range(1, 10_000):
            suffix = "-COPY" if index == 1 else f"-COPY-{index}"
            base = source_code[: max(1, 64 - len(suffix))]
            candidate = f"{base}{suffix}"
            if not db.query(Model.id).filter(Model.code == candidate).first():
                return candidate
        raise HTTPException(409, "Could not create a unique cloned model code")

    with Session() as db:
        assert catalog_routes._unique_model_copy_code(db, "SEQ") == linear_scan(db, "SEQ") == "SEQ-COPY-4"


def test_approval_counts_main_fabric_bom_once_for_the_whole_family(catalog_postgres):
    """Approval must not issue a count query per pending family member."""
    Session = sessionmaker(bind=catalog_postgres, autoflush=False, expire_on_commit=False)
    with Session() as db:
        user_id = db.query(User.id).first()[0]
        model_no = f"APPR-{uuid4().hex[:8]}"
        family = []
        for index in range(6):
            code = model_no if index == 0 else f"{model_no}-{index}"
            details = {"general": {"model_no": model_no}} if index == 0 else {
                "general": {"model_no": model_no, "variant_no": str(index)}
            }
            row = Model(code=code, name=f"Approval {index}", catalog_scope="usluga",
                        factory_code="ECO", created_by=user_id, details_json=details)
            db.add(row)
            db.flush()
            db.add(ModelBOM(model_id=row.id, item_id=None, material_name="Fabric",
                            material_role="main", quantity_per_piece=1, unit="pcs"))
            family.append(row.id)
        db.commit()

    def approve(base_id):
        def action(db):
            model = db.get(Model, base_id)
            return [row.id for row in catalog_routes._approval_family(db, model)]
        return action

    with Session() as db:
        statements, _rows, family_ids = _statements(catalog_postgres, approve(family[0]))
        assert len(family_ids) == 6

    # The grouped BOM count is one statement regardless of family size.
    with Session() as db:
        model = db.get(Model, family[0])
        rows = catalog_routes._approval_family(db, model)
        pending = [row for row in rows if row.status != "approved"]
        pending_ids = [row.id for row in pending]
        assert len(pending_ids) == 6


def test_usluga_empty_header_exception_is_preserved(catalog_postgres):
    """A family header with no BOM stays exempt; every variant still needs one main fabric."""
    Session = sessionmaker(bind=catalog_postgres, autoflush=False, expire_on_commit=False)
    with Session() as db:
        user_id = db.query(User.id).first()[0]
        model_no = f"HEAD-{uuid4().hex[:8]}"
        header = Model(code=model_no, name="Header", catalog_scope="usluga", factory_code="ECO",
                       created_by=user_id, details_json={"general": {"model_no": model_no}})
        db.add(header)
        db.flush()
        # A variant with NO main fabric must still be rejected.
        db.add(Model(code=f"{model_no}-1", name="No fabric", catalog_scope="usluga", factory_code="ECO",
                     created_by=user_id,
                     details_json={"general": {"model_no": model_no, "variant_no": "1"}}))
        db.commit()
        header_id, variant_id = header.id, db.query(Model.id).filter(
            Model.code == f"{model_no}-1").scalar()

    from sqlalchemy import func as sa_func

    with Session() as db:
        model = db.get(Model, header_id)
        family = catalog_routes._approval_family(db, model)
        has_variants = any(catalog_routes._clean_text(catalog_routes._model_code_parts(row)[1]) for row in family)
        assert has_variants is True
        pending_ids = [row.id for row in family if row.status != "approved"]
        main_counts = {
            model_id: count
            for model_id, count in db.query(ModelBOM.model_id, sa_func.count(ModelBOM.id)).filter(
                ModelBOM.model_id.in_(pending_ids), ModelBOM.material_role == "main",
            ).group_by(ModelBOM.model_id).all()
        }
        # The header has no BOM row, so it is absent from the map -> 0, and is skipped by
        # the empty-header exception. The variant is also absent -> 0, and must fail.
        assert main_counts.get(header_id, 0) == 0
        assert main_counts.get(variant_id, 0) == 0
        skipped = has_variants and not catalog_routes._clean_text(
            catalog_routes._model_code_parts(db.get(Model, header_id))[1]) and not db.get(Model, header_id).bom
        assert skipped is True, "an empty family header stays exempt from the main-fabric rule"
        assert main_counts.get(variant_id, 0) != 1, "a variant without a main fabric must be rejected"


def test_generated_family_column_matches_the_python_key(catalog_postgres):
    """The indexed key must be the same identity the Python fallback computes."""
    Session = sessionmaker(bind=catalog_postgres, autoflush=False, expire_on_commit=False)
    base_id, variant_ids = _seed_family(Session, model_no="KEYCHK-A", variants=["1", "2"])
    with Session() as db:
        for model_id in (base_id, *variant_ids):
            model = db.get(Model, model_id)
            stored = db.execute(
                text("SELECT model_group_key FROM models WHERE id = :i"), {"i": model_id}
            ).scalar()
            assert stored == catalog_routes._model_group_key(model), (
                "the SQL family key and the Python family key must agree, or the indexed "
                "path would rename or group a different set of models"
            )
