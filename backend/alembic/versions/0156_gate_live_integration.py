"""Physical integration storage, separate from synthetic device evidence."""
from datetime import datetime
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Column, Table, MetaData
from sqlalchemy.orm import DeclarativeBase
class Base(DeclarativeBase):
    metadata = MetaData()
class PkMixin:
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
for name, names in {
    "employees": ["id", "factory_code"], "attendance_devices": ["id", "factory_code"],
    "users": ["id"], "gate_employee_devices": ["id", "employee_id", "factory_code", "device_id"],
    "gate_photo_assets": ["id", "employee_id", "factory_code"],
}.items():
    Table(name, Base.metadata, *[Column(n, String(3) if n == "factory_code" else Integer, primary_key=n == "id") for n in names])
from enum import Enum
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
from sqlalchemy import Enum as SAEnum
def enum_type(cls):
    return SAEnum(cls, values_callable=lambda e: [x.value for x in e], native_enum=False, create_constraint=True, validate_strings=True, name="gate_" + cls.__name__.lower())


class GateLiveDevice(Base, PkMixin):
    __tablename__ = "gate_live_devices"
    __table_args__ = (
        UniqueConstraint("device_id", name="uq_gate_live_device"),
        ForeignKeyConstraint(["device_id", "factory_code"], ["attendance_devices.id", "attendance_devices.factory_code"]),
        CheckConstraint("config_revision > 0", name="ck_gate_live_config_revision"),
    )
    device_id: Mapped[int] = mapped_column(Integer, nullable=False)
    factory_code: Mapped[str] = mapped_column(String(3), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    writes_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    worker_token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    source_host: Mapped[str] = mapped_column(String(255), nullable=False)
    certificate_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    config_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    configuration: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)


class GateLiveProfile(Base, PkMixin):
    __tablename__ = "gate_live_profiles"
    binding_id: Mapped[int] = mapped_column(ForeignKey("gate_employee_devices.id"), nullable=False, unique=True)
    snapshot: Mapped[dict[str, object] | None] = mapped_column(JSON)
    profile_hash: Mapped[str | None] = mapped_column(String(64))
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    adopted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class GateLiveJob(Base, PkMixin):
    __tablename__ = "gate_live_jobs"
    __table_args__ = (
        UniqueConstraint("requested_by", "factory_code", "request_key", name="uq_gate_live_request"),
        ForeignKeyConstraint(["employee_id", "factory_code"], ["employees.id", "employees.factory_code"]),
        ForeignKeyConstraint(["device_id", "factory_code"], ["attendance_devices.id", "attendance_devices.factory_code"]),
        ForeignKeyConstraint(["binding_id", "employee_id", "factory_code", "device_id"], ["gate_employee_devices.id", "gate_employee_devices.employee_id", "gate_employee_devices.factory_code", "gate_employee_devices.device_id"]),
        ForeignKeyConstraint(["photo_asset_id", "employee_id", "factory_code"], ["gate_photo_assets.id", "gate_photo_assets.employee_id", "gate_photo_assets.factory_code"]),
        CheckConstraint("config_revision > 0", name="ck_gate_live_job_revision"),
        CheckConstraint("dispatch_count >= 0 AND dispatch_count <= 3 AND attempt_count >= 0 AND attempt_count <= 3", name="ck_gate_live_job_attempts"),
    )
    requested_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    factory_code: Mapped[str] = mapped_column(String(3), nullable=False)
    employee_id: Mapped[int] = mapped_column(Integer, nullable=False)
    device_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    binding_id: Mapped[int | None] = mapped_column(Integer)
    action: Mapped[LiveGateAction] = mapped_column(enum_type(LiveGateAction), nullable=False)
    state: Mapped[LiveGateState] = mapped_column(enum_type(LiveGateState), nullable=False, default=LiveGateState.QUEUED)
    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    config_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    baseline: Mapped[dict[str, object] | None] = mapped_column(JSON)
    desired_policy: Mapped[dict[str, object] | None] = mapped_column(JSON)
    photo_asset_id: Mapped[int | None] = mapped_column(Integer)
    photo_sha256: Mapped[str | None] = mapped_column(String(64))
    lease_token_hash: Mapped[str | None] = mapped_column(String(64))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dispatch_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result_history: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, default=list)
    result_hash: Mapped[str | None] = mapped_column(String(64))
    result: Mapped[dict[str, object] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# Frozen physical integration schema; never imports current application models.
from alembic import op
import sqlalchemy as sa
revision = "0156_gate_live_integration"
down_revision = "0155_eco_gate_merge"
branch_labels = None
depends_on = None

TABLES = (GateLiveDevice.__table__, GateLiveProfile.__table__, GateLiveJob.__table__)

def upgrade():
    for table in ("gate_operations", "gate_simulator_devices"):
        op.drop_constraint("gate_gatemode", table, type_="check")
        op.create_check_constraint("gate_gatemode", table, "mode IN ('disabled', 'simulator', 'hikvision')")
    op.add_column("gate_employee_devices", sa.Column("mode", sa.String(9), nullable=False, server_default="simulator"))
    op.create_check_constraint("gate_gatemode", "gate_employee_devices", "mode IN ('disabled', 'simulator', 'hikvision')")
    for table in TABLES:
        table.create(op.get_bind())

def downgrade():
    bind = op.get_bind()
    for table in TABLES:
        if bind.execute(sa.text("SELECT EXISTS (SELECT 1 FROM " + table.name + ")")).scalar():
            raise RuntimeError("Cannot downgrade retained live configuration, identity or operation evidence")
    if bind.execute(sa.text("SELECT EXISTS (SELECT 1 FROM gate_employee_devices WHERE mode <> 'simulator')")).scalar():
        raise RuntimeError("Cannot downgrade physical binding ownership")
    for table in reversed(TABLES):
        table.drop(bind)
    op.drop_constraint("gate_gatemode", "gate_employee_devices", type_="check")
    op.drop_column("gate_employee_devices", "mode")
    for table in ("gate_operations", "gate_simulator_devices"):
        if bind.execute(sa.text("SELECT EXISTS (SELECT 1 FROM " + table + " WHERE mode = 'hikvision')")).scalar():
            raise RuntimeError("Cannot downgrade physical mode history")
        op.drop_constraint("gate_gatemode", table, type_="check")
        op.create_check_constraint("gate_gatemode", table, "mode IN ('disabled', 'simulator')")
