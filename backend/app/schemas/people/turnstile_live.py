"""Physical integration storage, separate from synthetic device evidence."""
from datetime import datetime
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, PkMixin
from app.libs.enums.turnstile import LiveGateAction, LiveGateState
from app.schemas.people.turnstile import enum_type


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
