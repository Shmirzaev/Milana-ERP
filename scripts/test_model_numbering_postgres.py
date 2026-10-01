"""Read-only PostgreSQL identity regression using inline fixtures, never stored rows."""
import importlib.util
import json
from pathlib import Path

from sqlalchemy import select, text

from app.db.session import SessionLocal
from app.models import Model
from app.services import numbering


def main():
    path = Path(numbering.__file__).resolve().parents[2] / "alembic/versions/0084_model_group_key.py"
    spec = importlib.util.spec_from_file_location("model_group_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    # Code and metadata are independent identities. Empty first metadata keys,
    # whitespace, leading zeros, look-alikes and family boundaries must retain
    # the existing PostgreSQL behavior, even when the stored key is broader.
    cases = [
        ("XJ3201", {}, True),
        ("ХJ-003201-123", {}, True),
        ("XJ3201-V-999", {"model_no": "PJ1253"}, True),
        ("SPECIAL", {"model_no": "XJ3201"}, True),
        ("SPECIAL", {"modelNo": "ХJ-003201"}, True),
        ("SPECIAL", {"model_no": None, "modelNo": "XJ3201"}, True),
        ("SPECIAL", {"model_no": "", "modelNo": "XJ3201"}, False),
        ("SPECIAL", {"model_no": " ", "modelNo": "XJ3201"}, False),
        ("SPECIAL", {"model_no": " XJ3201 "}, False),
        ("SPECIAL", {"model_no": "XJ3201", "modelNo": "PJ1253"}, True),
        ("SPECIAL", {"model_no": "PJ1253", "modelNo": "XJ3201"}, False),
        ("XJ32010-1", {}, False),
        ("XJ3201A-1", {}, False),
        ("PJ3201-1", {}, False),
        ("XJ7641", {}, False),
        ("SPECIAL", {"model_no": "XJ3201-1"}, False),
        ("SPECIAL", {"model_no": "xj003201"}, True),
    ]
    fixtures = [
        {"id": i, "code": code, "name": "Fixture", "details_json": {"general": general}}
        for i, (code, general, _) in enumerate(cases, 1)
    ]
    expected = [i for i, (_, _, occupied) in enumerate(cases, 1) if occupied]
    with SessionLocal() as db:
        assert db.bind.dialect.name == "postgresql"
        db.execute(text("SET TRANSACTION READ ONLY"))
        db.execute(text("SET LOCAL statement_timeout = '10s'"))
        query = select(Model.id).where(numbering._model_number_occupied_clause(db, "XJ", 3201)).order_by(Model.id)
        compiled = str(query.compile(dialect=db.bind.dialect, compile_kwargs={"literal_binds": True}))
        sql = f"""WITH fixture AS (
            SELECT * FROM jsonb_to_recordset(CAST(:fixtures AS jsonb))
            AS f(id integer, code text, name text, details_json jsonb)
        ), models AS (
            SELECT *, {migration.GROUP_KEY_SQL} AS model_group_key FROM fixture
        ) {compiled}"""
        actual = list(db.execute(text(sql), {"fixtures": json.dumps(fixtures)}).scalars())
        assert actual == expected, (actual, expected)
    print(f"PostgreSQL model-number collision regression: {len(cases)} inline fixtures passed (read-only).")


if __name__ == "__main__":
    main()
