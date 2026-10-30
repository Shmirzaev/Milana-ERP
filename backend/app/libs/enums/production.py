from enum import StrEnum


class SewingFactoryCode(StrEnum):
    MILANA = "MIL"
    BESTTEX = "BST"
    ECO_COTTON = "ECO"


class WorkOrderStatus(StrEnum):
    NEW = "new"
    PLANNING = "planning"
    WAITING = "waiting"
    PENDING = "pending"
    READY = "ready"
    COLLECTED = "collected"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    COMPLETED = "completed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class ProductionType(StrEnum):
    """Production order kinds observed across every current writer.

    The general production DTO intentionally accepts only client_order and
    branded_stock. Usluga creates service_order through its separate operation.
    """

    CLIENT_ORDER = "client_order"
    BRANDED_STOCK = "branded_stock"
    SERVICE_ORDER = "service_order"


class ProductionSourceType(StrEnum):
    """Production source discriminator constrained by the mapped DB CHECK."""

    STANDARD = "standard"
    USLUGA = "usluga"


class SewingOutputAssignmentTransitionStatus(StrEnum):
    """Target statuses emitted by Sewing output; not the full assignment vocabulary."""

    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
