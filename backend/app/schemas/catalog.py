from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from app.schemas.common import ORMModel
from app.schemas.inventory import ItemComposition, ItemOut


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
    extra_permissions: list[str] = Field(default_factory=list)
    is_active: bool = True


class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    role_id: Optional[int] = None
    department_id: Optional[int] = None
    extra_permissions: Optional[list[str]] = None
    is_active: Optional[bool] = None


class UserOut(ORMModel):
    id: int
    name: str
    email: str
    role_id: Optional[int] = None
    department_id: Optional[int] = None
    extra_permissions: list[str] = Field(default_factory=list)
    is_active: bool
    last_login_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    created_at: datetime
    password_setup_email_sent: Optional[bool] = None
    password_setup_email_error: Optional[str] = None


class PasswordSetupEmailStatusOut(BaseModel):
    available: bool
    message: Optional[str] = None


# Customers / Suppliers
class PartyIn(BaseModel):
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None


class PartyOut(ORMModel):
    id: int
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None


# Brand / Collection / Model
class BrandIn(BaseModel):
    name: str
    description: Optional[str] = None
    logo_url: Optional[str] = None
    is_active: bool = True


class BrandOut(ORMModel):
    id: int
    name: str
    description: Optional[str] = None
    logo_url: Optional[str] = None
    is_active: bool


class CollectionIn(BaseModel):
    brand_id: int
    name: str
    season: Optional[str] = None
    year: int
    description: Optional[str] = None
    status: str = "draft"


class CollectionOut(ORMModel):
    id: int
    brand_id: int
    name: str
    season: Optional[str] = None
    year: int
    description: Optional[str] = None
    status: str


class ModelImageIn(BaseModel):
    file_url: str
    file_name: Optional[str] = None
    content_type: Optional[str] = None
    image_type: Optional[str] = None
    is_primary: bool = False


class ModelImageOut(ORMModel):
    id: int
    file_url: str
    file_name: Optional[str] = None
    content_type: Optional[str] = None
    image_type: Optional[str] = None
    is_primary: bool
    created_at: datetime


class ModelSizeIn(BaseModel):
    size: str
    measurement_json: Optional[dict] = None


class ModelSizeOut(ORMModel):
    id: int
    size: str
    measurement_json: Optional[dict] = None


class ModelColorIn(BaseModel):
    color_name: str
    color_code: Optional[str] = None


class ModelColorOut(ORMModel):
    id: int
    color_name: str
    color_code: Optional[str] = None


class ModelBOMIn(BaseModel):
    item_id: int
    stock_batch_id: Optional[int] = None
    size: Optional[str] = None
    color: Optional[str] = None
    photo_url: Optional[str] = None
    quantity_per_piece: float
    unit: str
    waste_percent: float = 0


class ModelBOMUpdate(BaseModel):
    item_id: Optional[int] = None
    stock_batch_id: Optional[int] = None
    size: Optional[str] = None
    color: Optional[str] = None
    photo_url: Optional[str] = None
    quantity_per_piece: Optional[float] = None
    unit: Optional[str] = None
    waste_percent: Optional[float] = None


class ModelBOMOut(ORMModel):
    id: int
    item_id: int
    item: Optional[ItemOut] = None
    stock_batch_id: Optional[int] = None
    stock_batch_no: Optional[str] = None
    stock_batch_image_url: Optional[str] = None
    stock_batch_color: Optional[str] = None
    size: Optional[str] = None
    color: Optional[str] = None
    photo_url: Optional[str] = None
    quantity_per_piece: float
    unit: str
    waste_percent: float


class ModelIn(BaseModel):
    code: str
    name: str
    category: Optional[str] = None
    description: Optional[str] = None
    brand_id: Optional[int] = None
    collection_id: Optional[int] = None
    product_type: Optional[str] = None
    season: Optional[str] = None
    constructor_employee_id: Optional[int] = None
    designer_employee_id: Optional[int] = None
    details_json: Optional[dict] = None
    status: str = "draft"
    sam_minutes: float = 0


class ModelVariantCreateIn(BaseModel):
    variant_no: str = Field(min_length=1, max_length=64)
    fabric_item_id: Optional[int] = Field(default=None, gt=0)
    color: Optional[str] = Field(default=None, max_length=128)
    picture_url: Optional[str] = None
    # Accepted temporarily so older clients can be normalized to the batch's
    # master fabric item without retaining the physical batch on the model.
    stock_batch_id: Optional[int] = Field(default=None, gt=0)


class ModelVariantUpdateIn(ModelVariantCreateIn):
    pass


class ModelOut(ORMModel):
    id: int
    code: str
    name: str
    category: Optional[str] = None
    description: Optional[str] = None
    brand_id: Optional[int] = None
    collection_id: Optional[int] = None
    product_type: Optional[str] = None
    season: Optional[str] = None
    constructor_employee_id: Optional[int] = None
    designer_employee_id: Optional[int] = None
    details_json: Optional[dict] = None
    status: str
    sam_minutes: float = 0
    material_composition: list[ItemComposition] = Field(default_factory=list)
    created_by: Optional[int] = None
    approved_by: Optional[int] = None
    approved_at: Optional[datetime] = None
    created_at: datetime


class ModelDetail(ModelOut):
    images: list[ModelImageOut] = []
    sizes: list[ModelSizeOut] = []
    colors: list[ModelColorOut] = []
    bom: list[ModelBOMOut] = []
