"""Shared, guarded SQLite/PostgreSQL HTTP fixtures for attendance operations."""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.schemas import AttendanceDevice, AttendanceEvent, AttendancePerson, Role, SystemSetting, User
from app.tests.conftest import TestSessionLocal
from app.tests.pg_approved_instance import (
    ApprovedInstanceUnavailable, create_target_database, finalize_target,
    load_approved_instance, require_or_skip, target_engine,
)


@pytest.fixture(scope='module',params=['sqlite','postgres'])
def attendance_database(request):
    if request.param=='sqlite':
        yield TestSessionLocal
        return
    try:instance=load_approved_instance()
    except ApprovedInstanceUnavailable as error:require_or_skip(error)
    target=create_target_database(instance);engine=None
    try:
        engine=target_engine(target,options='-ctimezone=UTC')
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine,expire_on_commit=False,autoflush=False)
    finally:finalize_target(target,engine)


@pytest.fixture
def ah(attendance_database):
    factory=attendance_database;marker=uuid4().hex;users={}
    with factory() as db:
        db.query(SystemSetting).filter(SystemSetting.key.like('att_src:%')).delete()
        db.query(AttendanceEvent).delete();db.query(AttendancePerson).delete();db.query(AttendanceDevice).delete()
        for name,code,permissions in [('hr','MIL',['hr.employees','attendance.view','attendance.manage']),
                                      ('denied','MIL',['finance.view']),('eco','ECO',['hr.employees','attendance.view','attendance.manage'])]:
            role=Role(name=f'Attendance {name} {marker}',permissions=permissions);db.add(role);db.flush()
            actor=User(name=name,email=f'{name}-{marker}@example.invalid',password_hash='unused',role_id=role.id,factory_code=code,is_active=True)
            db.add(actor);db.flush();users[name]=actor.id
        db.commit()
    def sessions():
        with factory() as db:yield db
    previous=app.dependency_overrides[get_db];app.dependency_overrides[get_db]=sessions
    try:yield factory,users,TestClient(app)
    finally:app.dependency_overrides[get_db]=previous


def headers(ah,actor='hr'):
    return {'Authorization':'Bearer '+create_access_token(ah[1][actor],{'factory_code':'ECO' if actor=='eco' else 'MIL'})}


def managed_payload(key='test-device'):
    return {'device_key':key,'name':' Test gate ','vendor':'Hikvision','source_host':'https://test-device.invalid/',
            'certificate_sha256':'AB'*32}
