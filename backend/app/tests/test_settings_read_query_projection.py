from sqlalchemy import event

from app.api.routes.settings import _SCHEMAS, get_settings
from app.models import SystemSetting
from app.tests.conftest import TestSessionLocal


def test_settings_read_uses_one_projected_select_and_preserves_defaults():
    with TestSessionLocal() as db:
        existing = {
            row.key: row.value_json
            for row in db.query(SystemSetting).filter(SystemSetting.key.in_(_SCHEMAS)).all()
        }
        expected = {
            key: schema(**existing[key]).model_dump() if isinstance(existing.get(key), dict)
            else schema().model_dump()
            for key, schema in _SCHEMAS.items()
        }
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().lower().startswith("select"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            result = get_settings(db, None)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert result == expected
    assert len(statements) == 1, statements
    selected_columns = statements[0].split(" from ", 1)[0]
    assert 'system_settings."key"' in selected_columns, statements[0]
    assert "system_settings.value_json" in selected_columns, statements[0]
    assert "system_settings.id" not in selected_columns, statements[0]
    assert "system_settings.created_at" not in selected_columns, statements[0]
    assert "system_settings.updated_at" not in selected_columns, statements[0]
