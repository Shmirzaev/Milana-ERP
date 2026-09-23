from sqlalchemy import event

from app.api.routes.settings import _setting_for_update
from app.models import SystemSetting
from app.tests.conftest import TestSessionLocal


def test_settings_update_lock_read_selects_only_row_identity_and_value():
    created = False
    with TestSessionLocal() as db:
        row = db.query(SystemSetting).filter(SystemSetting.key == "financial").first()
        if row is None:
            row = SystemSetting(key="financial", value_json={"default_currency": "USD"})
            db.add(row)
            db.commit()
            created = True

        statements: list[str] = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            selected = _setting_for_update(db, "financial")
            assert selected is not None
            assert (selected.id, selected.key, selected.value_json) == (
                row.id,
                "financial",
                row.value_json,
            )
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
            if created:
                db.delete(row)
                db.commit()

    assert len(statements) == 1
    selected_columns = statements[0].split(" from system_settings", 1)[0]
    assert "system_settings.id" in selected_columns
    assert 'system_settings."key"' in selected_columns
    assert "system_settings.value_json" in selected_columns
    assert "system_settings.created_at" not in selected_columns
    assert "system_settings.updated_at" not in selected_columns
