from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, StringConstraints, field_validator

from app.core.deps import DbSession, require_permissions
from app.models import Model, ModelSize, User
from app.services.audit import log_action


router = APIRouter(tags=["catalog"])


class ProcessQrSizesIn(BaseModel):
    sizes: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]] = Field(
        min_length=1, max_length=40,
    )

    @field_validator("sizes")
    @classmethod
    def unique_sizes(cls, values: list[str]) -> list[str]:
        if len({value.casefold() for value in values}) != len(values):
            raise ValueError("Sizes must be unique")
        return values


@router.post("/models/{mid}/process-qr-sizes", status_code=201)
def add_process_qr_model_sizes(
    mid: int,
    payload: ProcessQrSizesIn,
    db: DbSession,
    current: User = Depends(require_permissions("payroll.manage", "modeling.models", "*")),
):
    # The standard catalog is shared across factories, as on the GET resolver.
    # Query arguments must never expose the separate Eco Cotton Usluga catalog.
    model = db.query(Model).filter(
        Model.id == mid,
        Model.catalog_scope == "standard",
    ).with_for_update().one_or_none()
    if model is None:
        raise HTTPException(404, "Model not found")
    # Lock the parent before checking children so concurrent setup requests
    # cannot both observe an empty model and insert their own sets.
    if db.query(ModelSize.id).filter(ModelSize.model_id == mid).first() is not None:
        raise HTTPException(409, "Model already has sizes. Refresh to use the saved sizes.")
    for size in payload.sizes:
        db.add(ModelSize(model_id=mid, size=size))
    log_action(
        db, current, "process_qr_sizes_added", "model", mid,
        old_value={"sizes": []}, new_value={"sizes": payload.sizes},
    )
    db.commit()
    return {"model_id": mid, "sizes": payload.sizes, "resolution": "own"}
