"""Canonical stored package classification; service actions use explicit subsets."""
from enum import Enum


class PackageStockKind(str, Enum):
    STANDARD = "standard"
    FIRST_GRADE = "first_grade"
    SECOND_GRADE = "second_grade"


class PackagingDepartment(str, Enum):
    MILANA = "PKG"
    BESTTEX = "BPK"
    ECO_COTTON = "ECP"


class PackageStatus(str, Enum):
    PACKED = "packed"
    RETURNED = "returned_to_packaging"
    HANDED_OVER = "handed_over"
    RECEIVED = "received_in_storage"
    RESERVED = "reserved"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    DAMAGED = "damaged"


class ManualPackageSource(str, Enum):
    PACKAGING = "manual_packaging"


class PackageScanType(str, Enum):
    PACKED = "packed"


class ManualRecoveryStatus(str, Enum):
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    UNAVAILABLE = "completed_unavailable"
