from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.libs.enums.production import SewingFactoryCode


class SewingManualReceiveIn(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    production_order_id: int
    # Explicit null retains legacy unbatched receipt; omitted batch is refused.
    production_batch_id: int | None
    model_id: int | None = None
    factory_code: SewingFactoryCode | None = None
    sewing_flow_id: int | None = Field(default=None, gt=0)

    @field_validator("factory_code", mode="before")
    @classmethod
    def normalize_factory(cls, value):
        return str(value or "").strip().upper() or None
