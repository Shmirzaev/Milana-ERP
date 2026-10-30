"""Internal contracts for the catalog model operations.

`NormalizedBomCreate` is the one shape the BOM create operation hands to the
schema-owned insert. The business service has already decided what the row
holds, and the material role is the canonical enum member or nothing at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import NotRequired, TypedDict

from app.libs.dto.catalog.model_input import PaidOperationIn
from app.libs.enums.catalog import BomMaterialRole, CatalogScope, CollectionStatus, PaidOperationFactory
from app.libs.enums.factory import FactoryCode


class BrandUpdateCommand(TypedDict):
    """Decided PATCH fields: absent optional keys leave stored values unchanged."""

    name: str
    description: NotRequired[str | None]
    logo_url: NotRequired[str | None]
    is_active: NotRequired[bool]


class CustomerUpdateCommand(TypedDict):
    """Validated customer fields; absent optional keys leave values unchanged."""

    name: str
    phone: NotRequired[str | None]
    email: NotRequired[str | None]
    address: NotRequired[str | None]
    notes: NotRequired[str | None]


class SupplierUpdateCommand(TypedDict):
    """Validated supplier fields; absent optional keys leave values unchanged."""

    name: str
    phone: NotRequired[str | None]
    email: NotRequired[str | None]
    address: NotRequired[str | None]
    notes: NotRequired[str | None]


class CollectionUpdateFields(TypedDict, total=False):
    """Raw partial fields from Collection PATCH before status normalization."""

    brand_id: int
    name: str
    season: str | None
    year: int
    description: str | None
    status: str


class CollectionUpdateCommand(TypedDict, total=False):
    """Validated partial fields passed to Collection persistence.

    Canonical status values are enum-typed. The separate passthrough field is
    only for an explicitly resubmitted, unchanged historical database value.
    """

    brand_id: int
    name: str
    season: str | None
    year: int
    description: str | None
    status: CollectionStatus
    unchanged_legacy_status: str


@dataclass(frozen=True)
class NormalizedBomCreate:
    """The decided content of one BOM row, ready for the mapped write.

    The material role is a canonical member or `None`: a manual material carries
    the role, an inventory-linked row carries none.
    """

    item_id: int | None
    material_name: str | None
    material_role: BomMaterialRole | None
    stock_batch_id: int | None
    size: str | None
    color: str | None
    photo_url: str | None
    quantity_per_piece: float
    unit: str
    waste_percent: float


class NormalizedBomUpdate(TypedDict, total=False):
    """Fields the catalog service has decided to write to an existing BOM row.

    Missing keys mean unchanged; present keys with ``None`` mean explicitly
    cleared. This contract is intentionally distinct from the create payload.
    """

    item_id: int | None
    material_name: str | None
    material_role: BomMaterialRole | None
    stock_batch_id: int | None
    size: str | None
    color: str | None
    photo_url: str | None
    quantity_per_piece: float | None
    unit: str | None
    waste_percent: float | None


class StockBatchBomRelinkCommand(TypedDict):
    """Inventory-requested Catalog linkage update, scoped by stock batch."""

    stock_batch_id: int
    item_id: int


@dataclass(frozen=True)
class ModelCreateCommand:
    """Validated Model CREATE input consumed by catalog business policy.

    Paid-operation rows remain typed through service policy and serialize only
    in the schema-owned JSON persistence operation. `status` remains raw because Model.status
    has legacy importer/PATCH values and no established closed vocabulary.
    """

    code: str
    name: str
    catalog_scope: CatalogScope
    factory_scope: PaidOperationFactory | None
    category: str | None
    description: str | None
    brand_id: int | None
    collection_id: int | None
    product_type: str | None
    season: str | None
    constructor_employee_id: int | None
    designer_employee_id: int | None
    details_json: ModelCreateDetails
    status: str
    sam_minutes: float
    automatic_model_prefix: str | None


@dataclass(frozen=True)
class ModelCreateDetails:
    """Open model metadata with recognized paid-operation keys kept typed."""

    metadata: dict[str, object]
    has_paid_operations: bool
    paid_operations: list[PaidOperationIn] | None
    has_paid_operations_alias: bool
    paidOperations: list[PaidOperationIn] | None


@dataclass(frozen=True)
class ModelApprovalInheritance:
    """Approval projection copied from the already-locked approved family."""

    approved_by: int | None
    approved_at: datetime | None


@dataclass(frozen=True)
class ModelInsert:
    """All mapped Model CREATE values after service policy has decided them."""

    code: str
    name: str
    catalog_scope: CatalogScope
    factory_code: FactoryCode | None
    category: str | None
    description: str | None
    brand_id: int | None
    collection_id: int | None
    product_type: str | None
    season: str | None
    constructor_employee_id: int | None
    designer_employee_id: int | None
    details_json: ModelCreateDetails
    status: str
    sam_minutes: float
    created_by: int | None
    approval_inheritance: ModelApprovalInheritance | None = None
