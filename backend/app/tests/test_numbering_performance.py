import inspect
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import event

import app.services.numbering as numbering
from app.models import Package, SystemSetting
from app.services.numbering import _next, next_model_variant_no
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


def test_retired_label_floor_reads_only_setting_value_json() -> None:
    year = datetime.now(timezone.utc).year
    prefix = f"PKG-PROJECTION-{uuid4().hex[:8].upper()}"
    key = f"retired_number:{prefix}:{year}"
    statements: list[str] = []

    with TestSessionLocal() as db:
        db.add(SystemSetting(key=key, value_json={"number": 17}))
        db.flush()
        legacy_sql = str(
            db.query(SystemSetting)
            .filter_by(key=key)
            .statement.compile(dialect=db.bind.dialect)
        ).lower()
        bind = db.get_bind()

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany) -> None:
            if statement.lstrip().lower().startswith("select"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(bind, "before_cursor_execute", capture)
        try:
            result = _next(db, Package, "package_no", prefix)
        finally:
            event.remove(bind, "before_cursor_execute", capture)

    assert result == f"{prefix}-{year}-000018"
    setting_read = next(statement for statement in statements if " from system_settings " in statement)
    assert setting_read.startswith("select system_settings.value_json ")
    assert "system_settings.created_at" not in setting_read
    assert 'system_settings."key"' in legacy_sql
    assert "system_settings.created_at" in legacy_sql
