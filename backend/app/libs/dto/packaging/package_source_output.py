"""Read-only package source balances; labels refer to configurable Nastils."""
from pydantic import BaseModel, Field

from app.libs.enums.packaging import PackagingDepartment


class PackageSourceOut(BaseModel):
    id: int
    batch_no: str
    batch_index: int
    name: str | None
    packed_qty: int = Field(ge=0)
    packaged_qty: int = Field(ge=0)
    available_to_package: int = Field(ge=0)


class PackageSourcesOut(BaseModel):
    work_order_id: int
    production_order_id: int
    packaging_department: PackagingDepartment
    items: list[PackageSourceOut]
