"""Pin audit and stale-form behavior; partial updates/locks use the integrity suite."""

from uuid import uuid4

import pytest
from sqlalchemy.orm import sessionmaker

from app.api.routes import settings as routes
from app.schemas import AuditLog, SystemSetting, User
from app.tests.conftest import TestSessionLocal
from app.tests.test_settings_patch_integrity import settings_postgres  # noqa: F401


@pytest.fixture(params=["sqlite", "postgres"])
def settings_session(request):
    factory = TestSessionLocal if request.param == "sqlite" else sessionmaker(
        bind=request.getfixturevalue("settings_postgres"), expire_on_commit=False,
    )
    with factory() as db:
        db.query(SystemSetting).delete()
        actor = User(name="Settings characterization", email=f"settings-{uuid4().hex}@example.com",
                     password_hash="unused", extra_permissions=["*"])
        db.add(actor)
        db.commit()
        yield db, actor


def test_section_save_preserves_raw_audit_and_editable_values(settings_session):
    db, actor = settings_session
    original = {"default_currency": "CUSTOM", "fiscal_year_start_month": 4, "legacy_field": "retired"}
    db.add(SystemSetting(key="financial", value_json=original))
    db.commit()
    saved = routes.save_settings_section("financial", {"default_currency": "OTHER"}, db, actor)
    assert saved == {"default_currency": "OTHER", "fiscal_year_start_month": 4}
    row = db.query(SystemSetting).filter_by(key="financial").one()
    audit = db.query(AuditLog).filter_by(user_id=actor.id).one()
    assert (audit.action, audit.entity_type, audit.entity_id) == ("update", "SystemSetting", row.id)
    assert audit.old_value_json == original
    assert audit.new_value_json == {"financial": saved}
    assert row.value_json == saved


def test_stale_full_section_save_is_last_writer_wins(settings_session):
    db, actor = settings_session
    initial = {"default_currency": "USD", "fiscal_year_start_month": 1}
    company = {"name": "Keep this company"}
    db.add_all([SystemSetting(key="financial", value_json=initial),
                SystemSetting(key="company_info", value_json=company)])
    db.commit()
    tab_one, tab_two = dict(initial), dict(initial)
    tab_one["default_currency"] = "UZS"
    tab_two["fiscal_year_start_month"] = 6
    assert routes.save_settings_section("financial", tab_one, db, actor) == tab_one
    assert routes.save_settings_section("financial", tab_two, db, actor) == tab_two
    db.expire_all()
    assert db.query(SystemSetting).filter_by(key="financial").one().value_json == tab_two
    assert db.query(SystemSetting).filter_by(key="company_info").one().value_json == company
    assert db.query(AuditLog).filter_by(user_id=actor.id).count() == 2
