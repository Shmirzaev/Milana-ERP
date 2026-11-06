"""Logo upload HTTP/audit/file lifecycle on both database engines."""
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import sessionmaker

from app.api.routes import settings as routes
from app.core.security import create_access_token
from app.db.session import get_db
from app.main import app
from app.schemas import AuditLog, SystemSetting
from app.tests.test_settings_section_characterization import settings_session  # noqa: F401
from app.tests.test_settings_patch_integrity import settings_postgres  # noqa: F401


@pytest.fixture
def logo_http(settings_session, monkeypatch, tmp_path):
    db, actor = settings_session
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    def sessions():
        with factory() as session:
            yield session
    previous = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = sessions
    monkeypatch.setattr(routes.app_settings, 'MODEL_FILES_DIR', str(tmp_path))
    headers = {'Authorization': 'Bearer '+create_access_token(actor.id, {'factory_code':'MIL'})}
    try:
        yield db, actor, factory, TestClient(app), headers, tmp_path
    finally:
        app.dependency_overrides[get_db] = previous


def upload(h, color='blue', headers=None):
    buffer=BytesIO();Image.new('RGB',(12,9),color).save(buffer,format='PNG')
    return h[3].post('/api/settings/company-logo/upload',headers=h[4] if headers is None else headers,
                     files={'file':('test-logo.png',buffer.getvalue(),'image/png')})


@pytest.mark.parametrize('existing',[False,True])
def test_logo_preserves_company_fields_defaults_and_exact_audit(logo_http,existing):
    h=logo_http;db,actor,_,_,_,directory=h
    company={'name':'Editable factory','phone':'555','email':None,'logo_url':None,'address':'Keep address'}
    if existing:
        db.add(SystemSetting(key='company_info',value_json=company));db.commit()
    response=upload(h)
    assert response.status_code==201,response.text
    url=response.json()['logo_url'];assert set(response.json())=={'logo_url'}
    assert url.startswith('/storage/model-files/company_logo_') and url.endswith('.webp')
    assert (directory/url.rsplit('/',1)[1]).is_file()
    db.expire_all();row=db.query(SystemSetting).filter_by(key='company_info').one()
    expected=company if existing else routes.CompanyInfo().model_dump()
    assert row.value_json=={**expected,'logo_url':url}
    audit=db.query(AuditLog).filter_by(entity_type='SystemSetting',action='upload_logo',user_id=actor.id).one()
    assert audit.user_id==actor.id and audit.entity_id==row.id
    assert audit.new_value_json=={'logo_url':url} and audit.old_value_json is None


@pytest.mark.parametrize('fail_commit',[False,True])
def test_logo_keeps_previous_file_until_commit_and_preserves_it_on_failure(logo_http,monkeypatch,fail_commit):
    h=logo_http;db,_,factory,_,_,directory=h
    first=upload(h);assert first.status_code==201
    old_url=first.json()['logo_url'];old_path=directory/old_url.rsplit('/',1)[1]
    real_commit=factory.class_.commit
    def commit(session):
        assert old_path.is_file(),'Old logo must exist until commit'
        if fail_commit:raise RuntimeError('synthetic logo commit failure')
        return real_commit(session)
    monkeypatch.setattr(factory.class_,'commit',commit)
    if fail_commit:
        with pytest.raises(RuntimeError,match='synthetic logo commit failure'):upload(h,'green')
    else:
        second=upload(h,'green');assert second.status_code==201
        assert second.json()['logo_url']!=old_url
        assert not old_path.exists()
    db.expire_all();saved=db.query(SystemSetting).filter_by(key='company_info').one().value_json['logo_url']
    if fail_commit:
        assert old_path.is_file() and saved==old_url
        assert db.query(AuditLog).filter_by(action='upload_logo',user_id=h[1].id).count()==1
    else:assert saved==second.json()['logo_url']


def test_non_admin_can_read_but_cannot_upload_and_unauthenticated_is_refused(logo_http):
    h=logo_http;db,actor,_,client,headers,directory=h
    actor.extra_permissions=[];db.commit()
    assert client.get('/api/settings',headers=headers).status_code==200
    assert upload(h).status_code==403
    assert upload(h,headers={}).status_code==401
    assert db.query(SystemSetting).count()==0 and db.query(AuditLog).filter_by(user_id=actor.id).count()==0
    assert not list(Path(directory).rglob('*'))
