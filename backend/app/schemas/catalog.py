from datetime import datetime
from typing import Optional
from pydantic import BaseModel

from app.schemas.common import ORMModel


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
    password: str
    role_id: Optional[int] = None
    department_id: Optional[int] = None
    is_active: bool = True


class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    role_id: Optional[int] = None
    department_id: Optional[int] = None
    is_active: Optional[bool] = None


class UserOut(ORMModel):
    id: int
    name: str
    email: str
    role_id: Optional[int] = None
    department_id: Optional[int] = None
    is_active: bool
    created_at: datetime


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
    year: Optional[int] = None
    description: Optional[str] = None
    status: str = "draft"


class CollectionOut(ORMModel):
    id: int
    brand_id: int
    name: str
    season: Optional[str] = None
    year: Optional[int] = None
    description: Optional[str] = None
    status: str


class ModelImageIn(BaseModel):
    file_url: str
    is_primary: bool = False


class ModelImageOut(ORMModel):
    id: int
    file_url: str
    is_primary: bool


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
    size: Optional[str] = None
    color: Optional[str] = None
    quantity_per_piece: float
    unit: str
    waste_percent: float = 0


class ModelBOMOut(ORMModel):
    id: int
    item_id: int
    size: Optional[str] = None
    color: Optional[str] = None
    quantity_per_piece: float
    unit: str
    waste_percent: float


class ModelIn(BaseModel):
    code: str
    name: str
    category: Optional[str] = None
    description: Optional[str] = None
    status: str = "draft"
    sam_minutes: float = 0


class ModelOut(ORMModel):
    id: int
    code: str
    name: str
    category: Optional[str] = None
    description: Optional[str] = None
    status: str
    sam_minutes: float = 0
    created_by: Optional[int] = None
    approved_by: Optional[int] = None
    approved_at: Optional[datetime] = None
    created_at: datetime


class ModelDetail(ModelOut):
    images: list[ModelImageOut] = []
    sizes: list[ModelSizeOut] = []
    colors: list[ModelColorOut] = []
    bom: list[ModelBOMOut] = []
