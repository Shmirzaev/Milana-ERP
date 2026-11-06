from fastapi import APIRouter, File, UploadFile
from fastapi.responses import FileResponse

from app.core.deps import CurrentUser, DbSession
from app.libs.dto.people.turnstile_output import GatePhotoOutput
from app.models.people.turnstile_photo_service import read_photo, upload_photo

router = APIRouter(prefix="/turnstile-access", tags=["turnstile-access"])


@router.post("/employees/{employee_id}/photos", response_model=GatePhotoOutput, status_code=201)
async def create_photo(employee_id: int, file: UploadFile = File(...), *, db: DbSession, actor: CurrentUser):
    return await upload_photo(db, actor, employee_id, file)


@router.get("/photos/{asset_id}")
def get_photo(asset_id: int, *, db: DbSession, actor: CurrentUser):
    return FileResponse(read_photo(db, actor, asset_id), media_type="image/jpeg", headers={"Cache-Control": "no-store"})
