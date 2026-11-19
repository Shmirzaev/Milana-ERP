"""Read-only package source balances; labels refer to configurable Nastils."""
from pydantic import BaseModel, Field

from app.libs.enums.packaging import PackagingDepartment


class PackageSourceSizeBalanceOut(BaseModel):
    size: str
    accepted: int | None
    packaged_qty: int = Field(ge=0)
    legacy_unknown_reserved_qty: int = Field(ge=0)
    remaining: int | None


class PackageSourceBalanceOut(BaseModel):
    packed_qty: int = Field(ge=0)
    packaged_qty: int = Field(ge=0)
    available_to_package: int = Field(ge=0)
    sewing_output_qty: int = Field(default=0, ge=0)
    available_input_qty: int = Field(default=0, ge=0)
    actual_size_verified: bool = False
    size_balances: list[PackageSourceSizeBalanceOut] = Field(default_factory=list)


class PackageSourceOut(PackageSourceBalanceOut):
    id: int
    batch_no: str
    batch_index: int
    name: str | None


class PackageSourcesOut(BaseModel):
    work_order_id: int
    production_order_id: int
    packaging_department: PackagingDepartment
    items: list[PackageSourceOut]
    unbatched_source: PackageSourceBalanceOut | None = None
