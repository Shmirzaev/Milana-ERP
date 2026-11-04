"""The narrow Planning action; does not expose general work-order updates."""
from pydantic import BaseModel, ConfigDict, field_validator

from app.libs.enums.production import CuttingDepartmentCode, CuttingFactoryLockReason


class ProductionCuttingFactoryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cutting_department_code: CuttingDepartmentCode

    @field_validator("cutting_department_code", mode="before")
    @classmethod
    def normalize_department(cls, value):
        return value.strip().upper() if isinstance(value, str) else value


class ProductionCuttingFactoryOut(BaseModel):
    production_order_id: int
    cutting_department_code: CuttingDepartmentCode
    available_departments: list[CuttingDepartmentCode]
    can_change: bool
    lock_reason: CuttingFactoryLockReason | None = None
    changed: bool = False
