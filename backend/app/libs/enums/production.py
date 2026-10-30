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


class SewingOutputAssignmentTransitionStatus(StrEnum):
    """Target statuses emitted by Sewing output; not the full assignment vocabulary."""

    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
