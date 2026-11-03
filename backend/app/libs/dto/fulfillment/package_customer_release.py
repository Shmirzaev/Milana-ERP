from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

PackageIdentity = Annotated[int, Field(strict=True, gt=0, le=2147483647)]


class PackageCustomerReleaseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    package_ids: list[PackageIdentity] = Field(min_length=1, max_length=200)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]

    @field_validator("package_ids")
    @classmethod
    def distinct_packages(cls, values: list[int]) -> list[int]:
        if len(set(values)) != len(values):
            raise ValueError("Select distinct packs")
        return values


class PackageCustomerReleaseOut(BaseModel):
    package_ids: list[int]
    released_count: int


class PackageCustomerAccessOut(BaseModel):
    customer_names: list[str]
    released_for_any_customer: bool
    released_at: datetime | None = None
    released_by_name: str | None = None
    release_reason: str | None = None
    released_quantity: int | None = None
