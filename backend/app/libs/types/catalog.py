"""Internal contracts for the catalog model operations.

`NormalizedBomCreate` is the one shape the BOM create operation hands to the
schema-owned insert. The business service has already decided what the row
holds, and the material role is the canonical enum member or nothing at all.
"""

from dataclasses import dataclass
from typing import TypedDict

from app.libs.enums.catalog import BomMaterialRole


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
