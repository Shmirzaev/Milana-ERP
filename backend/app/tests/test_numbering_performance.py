import inspect

from sqlalchemy import event

import app.services.numbering as numbering
from app.services.numbering import next_model_variant_no
from app.tests.conftest import TestSessionLocal


def test_variant_number_preview_does_not_hydrate_all_model_json() -> None:
    statements: list[str] = []

    def record_statement(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        statements.append(str(statement))

    with TestSessionLocal() as db:
        bind = db.get_bind()
        event.listen(bind, "before_cursor_execute", record_statement)
        try:
            result = next_model_variant_no(db)
        finally:
            event.remove(bind, "before_cursor_execute", record_statement)

    assert result.startswith("V-")
    model_selects = [statement for statement in statements if "FROM models" in statement]
    assert len(model_selects) == 1
    normalized = " ".join(model_selects[0].split()).lower()
    assert normalized.startswith("select models.id")
    assert " limit " in normalized
    assert "details_json" not in normalized


def test_numbering_service_uses_scoped_advisory_locks() -> None:
    source = inspect.getsource(numbering)

    assert "pg_advisory_xact_lock" in source
    assert "LOCK TABLE" not in source
    assert "query(Model.code, Model.details_json).all()" not in source
