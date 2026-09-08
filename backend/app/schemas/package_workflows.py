from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.tracking import PackageIn, PackageReceiveStorageIn

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]


class ManualSizeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    size: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]
    quantity: int = Field(gt=0, le=10000, strict=True)


class ManualPackageReceiptIn(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    request_key: UUID
    model_id: int = Field(gt=0)
    color: Text
    weight_kg: float = Field(ge=0.0001, le=10000, allow_inf_nan=False)
    count: int = Field(gt=0, le=200, strict=True)
    sizes: list[ManualSizeIn] = Field(min_length=1, max_length=50)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)]
    warehouse_id: int | None = Field(default=None, gt=0)
    storage_cell: str | None = Field(default=None, max_length=32)
    storage_shelf: str | None = Field(default=None, max_length=8)


class PrintRunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID
    package_ids: list[int] = Field(min_length=1, max_length=200)


class PrintRunCreatePackagesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID
    packages: list[PackageIn] = Field(min_length=1, max_length=200)


class PrintRunReceiveIn(PackageReceiveStorageIn):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=128)
