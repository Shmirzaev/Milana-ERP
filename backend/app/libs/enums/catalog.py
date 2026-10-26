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
    """The fixed, non-persisted catalogue scope discriminator.

    It selects the owning paid-process table and the Eco Cotton access rule.
    It is not a database column, so it needs no schema and no migration.
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
