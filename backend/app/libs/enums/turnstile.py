from enum import Enum

class GateAction(str, Enum):
    ENROLL = "enroll"
    EDIT = "edit"
    PHOTO = "photo"
    REVOKE = "revoke"

class GateMode(str, Enum):
    DISABLED = "disabled"
    SIMULATOR = "simulator"

class GateTargetState(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    VERIFYING = "verifying"
    SUCCEEDED = "succeeded"
    WAITING = "waiting"
    FAILED = "failed"
    CONFLICT = "conflict"
    UNCERTAIN = "uncertain"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"

class GatePhotoValidation(str, Enum):
    TECHNICAL_VALIDATED = "technical_validated"

class GateBindingState(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    REVOKED = "revoked"

class GateErrorCode(str, Enum):
    DEVICE_OFFLINE = "device_offline"
    IDENTITY_CONFLICT = "identity_conflict"
    PAYLOAD_CONFLICT = "payload_conflict"
    STALE_REVISION = "stale_revision"
    LEASE_EXPIRED = "lease_expired"
    SIMULATOR_ERROR = "simulator_error"
