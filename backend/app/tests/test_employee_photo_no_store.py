"""Private employee images must not be retained by shared browsers."""
from io import BytesIO
from uuid import uuid4

import hashlib

import pytest
from PIL import Image

from app.core.config import settings
from app.schemas import Employee, HrEmployeeDocument, GatePhotoAsset, User
from app.libs.enums.turnstile import GateMode, GatePhotoValidation
from app.tests.attendance_operation_fixtures import attendance_database,ah,headers  # noqa:F401
from app.tests.test_attendance_photo_read_characterization import _profile


@pytest.fixture(params=['attendance','hr_document','turnstile'])
def private_photo(request,ah,tmp_path,monkeypatch):
    fmt='JPEG' if request.param=='turnstile' else 'WEBP'
    media='image/jpeg' if request.param=='turnstile' else 'image/webp'
    data=BytesIO();Image.new('RGB',(8,8),'purple').save(data,format=fmt);content=data.getvalue()
    filename=uuid4().hex+('.jpg' if request.param=='turnstile' else '.webp');(tmp_path/filename).write_bytes(content)
    if request.param=='attendance':
        monkeypatch.setattr(settings,'ATTENDANCE_PHOTOS_DIR',str(tmp_path))
        pid=_profile(ah,filename)
        return f'/api/attendance/people/{pid}/photo',content,media
    if request.param=='turnstile':
        monkeypatch.setattr(settings,'ENV','development')
        monkeypatch.setattr(settings,'TURNSTILE_PROVISIONING_MODE',GateMode.SIMULATOR)
        monkeypatch.setattr(settings,'TURNSTILE_PHOTOS_DIR',str(tmp_path))
        with ah[0]() as db:
            actor=db.get(User,ah[1]['hr']);actor.extra_permissions=['attendance.provision']
            employee=Employee(factory_code='MIL',full_name='Private turnstile employee photo')
            db.add(employee);db.flush()
            asset=GatePhotoAsset(employee_id=employee.id,factory_code='MIL',created_by=actor.id,
                                 stored_name=filename,sha256=hashlib.sha256(content).hexdigest(),
                                 width=8,height=8,content_type=media,validation=GatePhotoValidation.TECHNICAL_VALIDATED)
            db.add(asset);db.commit();asset_id=asset.id
        return f'/api/turnstile-access/photos/{asset_id}',content,media
    monkeypatch.setattr(settings,'HR_DOCUMENTS_DIR',str(tmp_path))
    with ah[0]() as db:
        employee=Employee(factory_code='MIL',full_name='Private employee photo')
        db.add(employee);db.flush()
        document=HrEmployeeDocument(factory_code='MIL',employee_id=employee.id,category='other',
                                    title='Employee photo',original_name='employee.webp',stored_name=filename,
                                    content_type='image/webp',size_bytes=len(content),uploaded_by=ah[1]['hr'])
        db.add(document);db.commit();did=document.id
    return f'/api/hr/documents/{did}/download',content,media


@pytest.mark.parametrize('ranged',[False,True])
def test_private_employee_photo_is_no_store(ah,private_photo,ranged):
    url,content,media=private_photo
    hdr={**headers(ah),**({'Range':'bytes=0-3'} if ranged else {})}
    response=ah[2].get(url,headers=hdr)
    assert response.status_code==(206 if ranged else 200)
    assert response.content==(content[:4] if ranged else content)
    assert response.headers['content-type']==media
    assert response.headers['cache-control']=='no-store'


def test_private_employee_photo_refuses_user_without_access(ah,private_photo):
    url,content,media=private_photo
    denied=ah[2].get(url,headers=headers(ah,'denied'))
    assert denied.status_code==403 and content not in denied.content
    assert ah[2].get(url).status_code==401
