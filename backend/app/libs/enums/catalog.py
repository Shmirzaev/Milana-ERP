"""Fixed catalogue vocabulary shared by DTOs, services and schema persistence.

These are the stored strings the catalogue writes and branches on. The values
keep their existing spelling and case, and the columns stay `String`; the
services still own every permission and business rule.
"""

from enum import Enum


class CollectionStatus(str, Enum):
    """Allowed new collection states; historical rows may retain other values."""

    DRAFT = "draft"
    APPROVED = "approved"
    ARCHIVED = "archived"


class CatalogScope(str, Enum):
    """The fixed catalogue scope vocabulary, including persisted Model scope.

    It selects the owning paid-process table and the Eco Cotton access rule.
    Model.catalog_scope stores these values in its existing String(16) column,
    with a CHECK constraint and the standard default. This enum does not alter
    that storage, its constraints or its values; no migration is introduced.
    """

    STANDARD = "standard"
    USLUGA = "usluga"


class PaidProcessSection(str, Enum):
    SEWING = "sewing"
    CUTTING = "cutting"
    PACKAGING = "packaging"
    CLEANING = "cleaning"
    PRESSING = "pressing"
    CONTROL = "control"
    STORAGE = "storage"
    TIKUV = "tikuv"
    TRANSFER = "transfer"
    SNAPS = "snaps"
    BUTTONS = "buttons"
    CORD = "cord"
    SORTING = "sorting"


PAID_PROCESS_SECTION_VALUES = frozenset(section.value for section in PaidProcessSection)


class BomMaterialRole(str, Enum):
    """The fixed BOM material-role vocabulary.

    A manual Usluga fabric is either the main material or a secondary one. The
    stored column stays `String`; the role is written only for a manual material,
    so an inventory-linked row keeps a null role.
    """

    MAIN = "main"
    SECONDARY = "secondary"


BOM_MATERIAL_ROLE_VALUES = frozenset(role.value for role in BomMaterialRole)
