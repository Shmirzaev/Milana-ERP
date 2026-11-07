"""Durable, simulator-only turnstile enrollment records.

Revision ID: 0151_gate_enrollment
Revises: 0150_package_customer_release
"""
from alembic import op
from sqlalchemy import Column, Table, MetaData
from sqlalchemy.orm import DeclarativeBase
revision = "0151_gate_enrollment"
down_revision = "0154_eco_receipt_details"
branch_labels = None
depends_on = None
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
from datetime import datetime
from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum as SAEnum, ForeignKey, ForeignKeyConstraint, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    metadata = MetaData()
class PkMixin:
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
Table("employees", Base.metadata, Column("id", Integer, primary_key=True), Column("factory_code", String(3), nullable=False))
Table("attendance_devices", Base.metadata, Column("id", Integer, primary_key=True), Column("factory_code", String(3), nullable=False))
Table("users", Base.metadata, Column("id", Integer, primary_key=True))
def enum_type(cls):
    return SAEnum(cls, values_callable=lambda e: [x.value for x in e], native_enum=False, create_constraint=True, validate_strings=True, name="gate_" + cls.__name__.lower())

class GatePhotoAsset(Base, PkMixin):
    __tablename__ = "gate_photo_assets"
    __table_args__ = (UniqueConstraint("id", "employee_id", "factory_code", name="uq_gate_photo_scope"), ForeignKeyConstraint(["employee_id", "factory_code"], ["employees.id", "employees.factory_code"]), CheckConstraint("width > 0 AND height > 0", name="ck_gate_photo_dimensions"))
    employee_id: Mapped[int] = mapped_column(Integer, nullable=False)
    factory_code: Mapped[str] = mapped_column(String(3), nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    stored_name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    validation: Mapped[GatePhotoValidation] = mapped_column(enum_type(GatePhotoValidation), nullable=False, default=GatePhotoValidation.TECHNICAL_VALIDATED)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

class GateEmployeeDevice(Base, PkMixin):
    __tablename__ = "gate_employee_devices"
    __table_args__ = (UniqueConstraint("device_id", "external_person_id", name="uq_gate_binding_device_external"), UniqueConstraint("employee_id", "device_id", name="uq_gate_binding_employee_device"), UniqueConstraint("id", "employee_id", "factory_code", "device_id", name="uq_gate_binding_scope"), ForeignKeyConstraint(["employee_id", "factory_code"], ["employees.id", "employees.factory_code"]), ForeignKeyConstraint(["device_id", "factory_code"], ["attendance_devices.id", "attendance_devices.factory_code"]), CheckConstraint("desired_revision > 0", name="ck_gate_binding_revision"))
    employee_id: Mapped[int] = mapped_column(Integer, nullable=False)
    factory_code: Mapped[str] = mapped_column(String(3), nullable=False)
    device_id: Mapped[int] = mapped_column(Integer, nullable=False)
    external_person_id: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[GateBindingState] = mapped_column(enum_type(GateBindingState), nullable=False, default=GateBindingState.PENDING)
    desired_revision: Mapped[int] = mapped_column(Integer, nullable=False)

class GateOperation(Base, PkMixin):
    __tablename__ = "gate_operations"
    __table_args__ = (UniqueConstraint("id", "employee_id", "factory_code", "revision", name="uq_gate_operation_scope"), ForeignKeyConstraint(["employee_id", "factory_code"], ["employees.id", "employees.factory_code"]), ForeignKeyConstraint(["photo_asset_id", "employee_id", "factory_code"], ["gate_photo_assets.id", "gate_photo_assets.employee_id", "gate_photo_assets.factory_code"]), CheckConstraint("revision > 0", name="ck_gate_operation_revision"))
    employee_id: Mapped[int] = mapped_column(Integer, nullable=False)
    factory_code: Mapped[str] = mapped_column(String(3), nullable=False)
    requested_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    action: Mapped[GateAction] = mapped_column(enum_type(GateAction), nullable=False)
    mode: Mapped[GateMode] = mapped_column(enum_type(GateMode), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    photo_asset_id: Mapped[int] = mapped_column(Integer, nullable=False)
    external_person_id: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    targets: Mapped[list["GateTarget"]] = relationship(back_populates="operation")

class GateTarget(Base, PkMixin):
    __tablename__ = "gate_targets"
    __table_args__ = (UniqueConstraint("operation_id", "device_id", name="uq_gate_target_operation_device"), ForeignKeyConstraint(["operation_id", "employee_id", "factory_code", "revision"], ["gate_operations.id", "gate_operations.employee_id", "gate_operations.factory_code", "gate_operations.revision"]), ForeignKeyConstraint(["binding_id", "employee_id", "factory_code", "device_id"], ["gate_employee_devices.id", "gate_employee_devices.employee_id", "gate_employee_devices.factory_code", "gate_employee_devices.device_id"]), CheckConstraint("revision > 0 AND attempts >= 0", name="ck_gate_target_counters"))
    operation_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    binding_id: Mapped[int] = mapped_column(Integer, nullable=False)
    device_id: Mapped[int] = mapped_column(Integer, nullable=False)
    device_name: Mapped[str] = mapped_column(String(255), nullable=False)
    factory_code: Mapped[str] = mapped_column(String(3), nullable=False)
    employee_id: Mapped[int] = mapped_column(Integer, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[GateTargetState] = mapped_column(enum_type(GateTargetState), nullable=False, default=GateTargetState.QUEUED, index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[GateErrorCode | None] = mapped_column(enum_type(GateErrorCode))
    lease_token: Mapped[str | None] = mapped_column(String(64))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_evidence: Mapped[dict | None] = mapped_column(JSON)
    operation: Mapped[GateOperation] = relationship(back_populates="targets")

class GateSimulatorDevice(Base, PkMixin):
    __tablename__ = "gate_simulator_devices"
    __table_args__ = (UniqueConstraint("device_id", name="uq_gate_simulator_device"), ForeignKeyConstraint(["device_id", "factory_code"], ["attendance_devices.id", "attendance_devices.factory_code"]))
    device_id: Mapped[int] = mapped_column(Integer, nullable=False)
    factory_code: Mapped[str] = mapped_column(String(3), nullable=False)
    online: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    mode: Mapped[GateMode] = mapped_column(enum_type(GateMode), nullable=False, default=GateMode.DISABLED)

class GateSimulatorPerson(Base, PkMixin):
    __tablename__ = "gate_simulator_people"
    binding_id: Mapped[int] = mapped_column(ForeignKey("gate_employee_devices.id"), nullable=False, unique=True)
    external_person_id: Mapped[str] = mapped_column(String(64), nullable=False)
    accepted_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    accepted_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    photo_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    write_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __table_args__ = (CheckConstraint("accepted_revision > 0 AND write_count > 0", name="ck_gate_simulator_person_counters"),)

def upgrade():
    op.create_unique_constraint("uq_employees_id_factory", "employees", ["id", "factory_code"])
    op.create_unique_constraint("uq_attendance_devices_id_factory", "attendance_devices", ["id", "factory_code"])
    bind = op.get_bind()
    for table in (GatePhotoAsset, GateEmployeeDevice, GateOperation, GateTarget, GateSimulatorDevice, GateSimulatorPerson):
        table.__table__.create(bind)

def downgrade():
    bind = op.get_bind()
    for table in (GateSimulatorPerson, GateSimulatorDevice, GateTarget, GateOperation, GateEmployeeDevice, GatePhotoAsset):
        table.__table__.drop(bind)
    op.drop_constraint("uq_attendance_devices_id_factory", "attendance_devices", type_="unique")
    op.drop_constraint("uq_employees_id_factory", "employees", type_="unique")
