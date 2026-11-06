"""Settings snapshot defaults and validation stay unchanged on both databases."""

import pytest
from pydantic import ValidationError

from app.api.routes import settings as routes
from app.schemas import AuditLog, SystemSetting
from app.tests.test_settings_section_characterization import settings_session  # noqa: F401
from app.tests.test_settings_patch_integrity import settings_postgres  # noqa: F401


def test_read_missing_sections_uses_defaults_without_writes(settings_session, monkeypatch):
    db, actor = settings_session

    def no_commit():
        raise AssertionError('Reading settings must not commit')

    monkeypatch.setattr(db, 'commit', no_commit)
    assert routes.get_settings(db, actor) == routes._default_payload()
    assert db.query(SystemSetting).count() == 0
    assert db.query(AuditLog).count() == 0


def test_read_preserves_editable_values_and_ignores_unknown_stored_fields(settings_session):
    db, actor = settings_session
    values = {'default_language': 'custom-language', 'timezone': 'Factory/Custom',
              'model_types': ['Editable model type'], 'legacy_extra': 'ignored'}
    db.add(SystemSetting(key='preferences', value_json=values))
    db.add(SystemSetting(key='unrelated_key', value_json={'keep': True}))
    db.commit()
    result = routes.get_settings(db, actor)
    assert result['preferences'] == {**routes.SystemPreferences().model_dump(),
                                     **{k:v for k,v in values.items() if k!='legacy_extra'}}
    assert set(result) == {'company_info','financial','preferences'}
    db.expire_all()
    assert db.query(SystemSetting).filter_by(key='preferences').one().value_json == values
    assert db.query(SystemSetting).filter_by(key='unrelated_key').one().value_json == {'keep': True}
    assert db.query(AuditLog).count() == 0


@pytest.mark.parametrize('value', [['legacy'], 'legacy scalar'])
def test_read_non_object_storage_uses_defaults(settings_session, value):
    db, actor = settings_session
    db.add(SystemSetting(key='financial', value_json=value));db.commit()
    assert routes.get_settings(db, actor)['financial'] == routes.FinancialSettings().model_dump()
    assert db.query(SystemSetting).filter_by(key='financial').one().value_json == value


def test_read_invalid_stored_value_keeps_validation_failure(settings_session):
    db, actor = settings_session
    db.add(SystemSetting(key='financial', value_json={'fiscal_year_start_month':0}));db.commit()
    with pytest.raises(ValidationError) as error:
        routes.get_settings(db, actor)
    assert error.value.errors()[0]['loc'] == ('fiscal_year_start_month',)
    assert db.query(SystemSetting).filter_by(key='financial').one().value_json == {'fiscal_year_start_month':0}
