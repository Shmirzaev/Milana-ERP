"""Catalog contract compatibility module.

The catalog contracts live in the entity-named modules next to this file:
``brand_input``/``brand_output``, ``collection_input``/``collection_output``,
``party_input``/``party_output``, ``model_input``/``model_output`` and the
model child contracts. The identity-owned User/Role/Department contracts stay
here unchanged, and the catalog contracts are re-exported so the historical
``app.libs.dto.catalog.catalog`` import path keeps working for callers that
are not part of this change.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.libs.dto.catalog.brand_input import BrandIn
from app.libs.dto.catalog.brand_output import BrandOut
from app.libs.dto.catalog.collection_input import CollectionIn
from app.libs.dto.catalog.collection_output import CollectionOut
from app.libs.dto.catalog.model_bom_input import ModelBOMIn
from app.libs.dto.catalog.model_bom_output import ModelBOMOut
from app.libs.dto.catalog.model_bom_update import ModelBOMUpdate
from app.libs.dto.catalog.model_color_input import ModelColorIn
from app.libs.dto.catalog.model_color_output import ModelColorOut
from app.libs.dto.catalog.model_image_input import ModelImageIn
from app.libs.dto.catalog.model_image_output import ModelImageOut
from app.libs.dto.catalog.model_input import (
    ModelDetailsUpdateIn,
    ModelIn,
    ModelPaidOperationsIn,
    ModelUpdateIn,
    ModelVariantCreateIn,
    ModelVariantUpdateIn,
)
from app.libs.dto.catalog.model_output import (
    ModelDetail,
    ModelOptionOut,
    ModelOptionPage,
    ModelOut,
    ModelSellingPriceOut,
    ModelSummaryOut,
)
from app.libs.dto.catalog.model_size_input import ModelSizeIn
from app.libs.dto.catalog.model_size_output import ModelSizeOut
from app.libs.dto.catalog.paid_process_input import PaidProcessIn
from app.libs.dto.catalog.party_input import PartyIn
from app.libs.dto.catalog.party_output import PartyOut
from app.libs.dto.catalog.process_qr_sizes_input import ProcessQrSizesIn
from app.libs.dto.common import ORMModel
from app.libs.dto.identity.user_access import AccessPolicy

__all__ = [
    "BrandIn",
    "BrandOut",
    "CollectionIn",
    "CollectionOut",
    "DepartmentIn",
    "DepartmentOut",
    "ModelBOMIn",
    "ModelBOMOut",
    "ModelBOMUpdate",
    "ModelColorIn",
    "ModelColorOut",
    "ModelDetail",
    "ModelImageIn",
    "ModelImageOut",
    "ModelIn",
    "ModelDetailsUpdateIn",
    "ModelUpdateIn",
    "ModelOptionOut",
    "ModelOptionPage",
    "ModelOut",
    "ModelPaidOperationsIn",
    "ModelSellingPriceOut",
    "ModelSizeIn",
    "ModelSizeOut",
    "ModelSummaryOut",
    "ModelVariantCreateIn",
    "ModelVariantUpdateIn",
    "PaidProcessIn",
    "PartyIn",
    "PartyOut",
    "ProcessQrSizesIn",
    "RoleIn",
    "RoleOut",
    "UserIn",
    "UserOut",
    "UserUpdate",
]


# Roles / Departments / Users
class RoleIn(BaseModel):
    name: str
    permissions: list[str] = []


class RoleOut(ORMModel):
    id: int
    name: str
    permissions: list[str]


class DepartmentIn(BaseModel):
    name: str
    code: str


class DepartmentOut(ORMModel):
    id: int
    name: str
    code: str


class UserIn(BaseModel):
    name: str
    email: str
    password: Optional[str] = None
    role_id: Optional[int] = None
    department_id: Optional[int] = None
    factory_code: str = "MIL"
    extra_permissions: list[str] = Field(default_factory=list)
    access_policy: AccessPolicy | None = None
    is_active: bool = True


class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    role_id: Optional[int] = None
    department_id: Optional[int] = None
    factory_code: Optional[str] = None
    extra_permissions: Optional[list[str]] = None
    access_policy: AccessPolicy | None = None
    is_active: Optional[bool] = None


class UserOut(ORMModel):
    id: int
    name: str
    email: str
    role_id: Optional[int] = None
    department_id: Optional[int] = None
    factory_code: str = "MIL"
    extra_permissions: list[str] = Field(default_factory=list)
    access_policy: AccessPolicy | None = None
    is_active: bool
    last_login_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    created_at: datetime
