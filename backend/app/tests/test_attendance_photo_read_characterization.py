"""Private photo body/cache and lookup/path refusals on both databases."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.api.routes import attendance
from app.core.config import settings
from app.schemas import AttendanceDevice, AttendancePerson, User
from app.tests.attendance_operation_fixtures import (
    attendance_database as attendance_database, ah as ah, headers,
)


def _profile(ah, filename, *, factory='MIL', present=True):
    with ah[0]() as db:
        device = AttendanceDevice(factory_code=factory, device_key=uuid4().hex, name='Photo test', read_only=True)
        db.add(device); db.flush()
        person = AttendancePerson(factory_code=factory, device_id=device.id, external_person_id='735',
                                  full_name='Synthetic photo', present_on_device=present,
                                  last_synced_at=datetime.now(timezone.utc), photo_file_name=filename)
        db.add(person); db.commit(); return person.id


def test_photo_read_private_body_cache_and_auth_contract(ah, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'ATTENDANCE_PHOTOS_DIR', str(tmp_path))
    content = b'RIFF synthetic test-only WEBP bytes'
    (tmp_path/'test.webp').write_bytes(content)
    person_id = _profile(ah, 'test.webp')
    url = f'/api/attendance/people/{person_id}/photo'
    response = ah[2].get(url, headers=headers(ah))
    assert response.status_code == 200 and response.content == content
    assert response.headers['content-type'] == 'image/webp'
    assert response.headers['cache-control'] == 'private, max-age=300'
    assert int(response.headers['content-length']) == len(content)
    assert ah[2].get(url).status_code == 401
    assert ah[2].get(url, headers=headers(ah, 'denied')).status_code == 403
    assert ah[2].get(url, headers=headers(ah, 'eco')).status_code == 404
    with ah[0]() as db:
        actor = db.get(User, ah[1]['hr'])
        def no_commit():
            raise AssertionError('Read operation must not commit')
        monkeypatch.setattr(db, 'commit', no_commit)
        direct = attendance.attendance_person_photo(person_id, db, actor)
        assert direct.headers['cache-control'] == 'private, max-age=300'
        assert not db.new and not db.dirty and not db.deleted


@pytest.mark.parametrize('case', ['historical', 'other_factory', 'no_name', 'missing', 'traversal', 'absolute', 'nested', 'symlink'])
def test_photo_read_refuses_historical_missing_and_unsafe_paths(ah, tmp_path, monkeypatch, case):
    root = tmp_path/'photos'; root.mkdir()
    outside = tmp_path/'outside.webp'; outside.write_bytes(b'outside test bytes')
    (root/'test.webp').write_bytes(b'inside test bytes')
    filename = 'test.webp'
    if case == 'no_name': filename = None
    elif case == 'missing': filename = 'missing.webp'
    elif case == 'traversal': filename = '../outside.webp'
    elif case == 'absolute': filename = str(outside)
    elif case == 'nested':
        (root/'nested').mkdir(); (root/'nested'/'photo.webp').write_bytes(b'nested')
        filename = 'nested/photo.webp'
    elif case == 'symlink':
        (root/'link.webp').symlink_to(outside); filename = 'link.webp'
    monkeypatch.setattr(settings, 'ATTENDANCE_PHOTOS_DIR', str(root))
    person_id = _profile(ah, filename, factory='ECO' if case == 'other_factory' else 'MIL', present=case != 'historical')
    response = ah[2].get(f'/api/attendance/people/{person_id}/photo', headers=headers(ah))
    assert (response.status_code, response.json()) == (404, {'detail': 'Attendance photo not found'})
    assert outside.read_bytes() == b'outside test bytes'
