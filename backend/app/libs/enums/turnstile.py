from enum import Enum

class GateAction(str, Enum):
    ENROLL = "enroll"
    EDIT = "edit"
    PHOTO = "photo"
    REVOKE = "revoke"

class GateMode(str, Enum):
    DISABLED = "disabled"
    SIMULATOR = "simulator"
    HIKVISION = "hikvision"


class LiveGateAction(str, Enum):
    OBSERVE = "observe"
    ENROLL = "enroll"
    EDIT = "edit"
    PHOTO = "photo"
    REVOKE = "revoke"
    RESTORE = "restore"
    DELETE = "delete"


class LiveGateState(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    DISPATCHING = "dispatching"
    SUCCEEDED = "succeeded"
    CONFLICT = "conflict"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


class LiveGateOutcome(str, Enum):
    READBACK = "readback"
    REFUSED = "refused"
    UNKNOWN = "unknown"


class LiveWriteStep(str, Enum):
    CREATE_BLOCKED_PERSON = "create_blocked_person"
    UPLOAD_FACE = "upload_face"
    ACTIVATE_ACCESS = "activate_access"
    MODIFY_PROFILE = "modify_profile"
    DELETE_PROFILE = "delete_profile"


class HikvisionUserType(str, Enum):
    NORMAL = "normal"
    VISITOR = "visitor"
    BLOCKED = "blackList"

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
