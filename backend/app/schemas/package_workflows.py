from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.schemas.tracking import PackageIn, PackageReceiveStorageIn

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]


class ManualSizeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    size: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]
    quantity: int = Field(gt=0, le=10000, strict=True)


class ManualPackageReceiptIn(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    request_key: UUID
    model_id: int = Field(gt=0, le=2_147_483_647)
    color: Text
    weight_kg: float = Field(ge=0.0001, le=10000, allow_inf_nan=False)
    count: int = Field(gt=0, le=200, strict=True)
    sizes: list[ManualSizeIn] = Field(default_factory=list, max_length=50)
    pack_quantities: list[Annotated[int, Field(gt=0, le=10000, strict=True)]] | None = Field(default=None, min_length=1, max_length=200)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)] | None = None
    warehouse_id: int | None = Field(default=None, gt=0, le=2_147_483_647)
    storage_cell: str | None = Field(default=None, max_length=32)
    storage_shelf: str | None = Field(default=None, max_length=8)


    @model_validator(mode="after")
    def validate_contents(self):
        if self.pack_quantities is not None:
            if self.sizes or len(self.pack_quantities) != self.count:
                raise ValueError("Enter one quantity per pack, without size quantities")
        elif not self.sizes:
            raise ValueError("Package quantities are required")
        return self


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


class PrintRunOut(BaseModel):
    id: int
    run_no: str
    code: str
    created_at: str
    received_at: str | None = None
    manual_receipt: bool
    count: int
    quantity: int
    package_ids: list[int]
    packages: list[dict[str, object]]


class PrintRunPageOut(BaseModel):
    rows: list[PrintRunOut]
    total: int
    page: int
    page_size: int
    has_more: bool
