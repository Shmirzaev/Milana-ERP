from typing import Annotated
from fastapi import APIRouter, Depends, Header
from fastapi.responses import FileResponse
from app.core.deps import CurrentUser, DbSession
from app.libs.dto.people.turnstile_live import (LiveAdoptInput, LiveClaimOutput, LiveDeviceInput,
    LiveJobOutput, LiveRequestInput, LiveResolutionInput, LiveResultInput, LiveDispatchInput, LiveContextOutput)
from app.models.people import turnstile_live_service as service
from app.schemas.people.turnstile_live import GateLiveDevice

router = APIRouter(prefix="/turnstile-live", tags=["turnstile-live"])


def worker(db: DbSession, x_turnstile_worker_token: Annotated[str | None, Header()] = None) -> GateLiveDevice:
    return service.worker_identity(db, x_turnstile_worker_token)


Worker = Annotated[GateLiveDevice, Depends(worker)]
RequestKey = Annotated[str | None, Header(alias="Idempotency-Key")]
LeaseToken = Annotated[str, Header(alias="X-Turnstile-Lease")]


@router.get("/employees/{employee_id}", response_model=LiveContextOutput)
def context(employee_id: int, db: DbSession, actor: CurrentUser):
    return service.context(db, actor, employee_id)


@router.put("/devices/{device_id}")
def configure(device_id: int, payload: LiveDeviceInput, db: DbSession, actor: CurrentUser):
    return service.configure_device(db, actor, device_id, payload)


@router.post("/employees/{employee_id}/jobs", status_code=202, response_model=LiveJobOutput)
def submit(employee_id: int, payload: LiveRequestInput, db: DbSession, actor: CurrentUser, idempotency_key: RequestKey = None):
    return service.submit(db, actor, employee_id, payload, idempotency_key)


@router.post("/employees/{employee_id}/adopt")
def adopt(employee_id: int, payload: LiveAdoptInput, db: DbSession, actor: CurrentUser):
    return service.adopt(db, actor, employee_id, payload)


@router.get("/jobs/{job_id}", response_model=LiveJobOutput)
def job(job_id: int, db: DbSession, actor: CurrentUser):
    return service.get_job(db, actor, job_id)


@router.get("/employees/{employee_id}/request", response_model=LiveJobOutput | None)
def receipt(employee_id: int, db: DbSession, actor: CurrentUser, idempotency_key: RequestKey = None):
    return service.request_receipt(db, actor, employee_id, idempotency_key)


@router.post("/jobs/{job_id}/resolve", response_model=LiveJobOutput)
def resolve(job_id: int, payload: LiveResolutionInput, db: DbSession, actor: CurrentUser):
    return service.resolve_uncertain(db, actor, job_id, payload)


@router.post("/worker/claim", response_model=LiveClaimOutput | None)
def claim(db: DbSession, identity: Worker):
    return service.claim(db, identity)


@router.post("/worker/jobs/{job_id}/dispatch")
def dispatch(job_id: int, payload: LiveDispatchInput, db: DbSession, identity: Worker, lease: LeaseToken):
    return service.permit_dispatch(db, identity, job_id, lease, payload.step)


@router.post("/jobs/{job_id}/retry-unsent", response_model=LiveJobOutput)
def retry_unsent(job_id: int, db: DbSession, actor: CurrentUser):
    return service.retry_unsent(db, actor, job_id)


@router.post("/worker/jobs/{job_id}/result", response_model=LiveJobOutput)
def result(job_id: int, payload: LiveResultInput, db: DbSession, identity: Worker):
    return service.record_result(db, identity, job_id, payload)


@router.get("/worker/jobs/{job_id}/photo")
def photo(job_id: int, db: DbSession, identity: Worker, lease: LeaseToken):
    path = service.worker_photo(db, identity, job_id, lease)
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "no-store"})
