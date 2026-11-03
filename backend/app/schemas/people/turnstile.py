from __future__ import annotations
from app.libs.types.turnstile_simulator import SimulatorEvidence
from datetime import datetime
from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum as SAEnum, ForeignKey, ForeignKeyConstraint, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, PkMixin
from app.libs.enums.turnstile import GateAction, GateMode, GateTargetState, GatePhotoValidation, GateBindingState, GateErrorCode

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
    __table_args__ = (UniqueConstraint("id", "employee_id", "factory_code", "revision", name="uq_gate_operation_scope"), ForeignKeyConstraint(["employee_id", "factory_code"], ["employees.id", "employees.factory_code"]), ForeignKeyConstraint(["photo_asset_id", "employee_id", "factory_code"], ["gate_photo_assets.id", "gate_photo_assets.employee_id", "gate_photo_assets.factory_code"]), CheckConstraint("revision > 0", name="ck_gate_operation_revision"), CheckConstraint("(action = 'edit' AND photo_asset_id IS NULL) OR (action <> 'edit' AND photo_asset_id IS NOT NULL)", name="ck_gate_operation_photo_action"))
    employee_id: Mapped[int] = mapped_column(Integer, nullable=False)
    factory_code: Mapped[str] = mapped_column(String(3), nullable=False)
    requested_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    action: Mapped[GateAction] = mapped_column(enum_type(GateAction), nullable=False)
    mode: Mapped[GateMode] = mapped_column(enum_type(GateMode), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    photo_asset_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    external_person_id: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    targets: Mapped[list["GateTarget"]] = relationship(back_populates="operation")

class GateTarget(Base, PkMixin):
    __tablename__ = "gate_targets"
    __table_args__ = (UniqueConstraint("operation_id", "device_id", name="uq_gate_target_operation_device"), ForeignKeyConstraint(["operation_id", "employee_id", "factory_code", "revision"], ["gate_operations.id", "gate_operations.employee_id", "gate_operations.factory_code", "gate_operations.revision"]), ForeignKeyConstraint(["binding_id", "employee_id", "factory_code", "device_id"], ["gate_employee_devices.id", "gate_employee_devices.employee_id", "gate_employee_devices.factory_code", "gate_employee_devices.device_id"]), CheckConstraint("revision > 0 AND attempts >= 0", name="ck_gate_target_counters"), CheckConstraint("(baseline_revision IS NULL AND baseline_payload_hash IS NULL AND baseline_full_name IS NULL AND baseline_external_person_id IS NULL AND baseline_photo_sha256 IS NULL AND baseline_profile_hash IS NULL AND desired_payload_hash IS NULL) OR (baseline_revision IS NOT NULL AND baseline_revision > 0 AND baseline_payload_hash IS NOT NULL AND length(baseline_payload_hash) = 64 AND baseline_full_name IS NOT NULL AND baseline_external_person_id IS NOT NULL AND baseline_photo_sha256 IS NOT NULL AND length(baseline_photo_sha256) = 64 AND baseline_profile_hash IS NOT NULL AND length(baseline_profile_hash) = 64 AND desired_payload_hash IS NOT NULL AND length(desired_payload_hash) = 64)", name="ck_gate_target_edit_baseline"))
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
    baseline_revision: Mapped[int | None] = mapped_column(Integer)
    baseline_payload_hash: Mapped[str | None] = mapped_column(String(64))
    baseline_full_name: Mapped[str | None] = mapped_column(String(255))
    baseline_external_person_id: Mapped[str | None] = mapped_column(String(64))
    baseline_photo_sha256: Mapped[str | None] = mapped_column(String(64))
    baseline_profile_hash: Mapped[str | None] = mapped_column(String(64))
    desired_payload_hash: Mapped[str | None] = mapped_column(String(64))
    observed_evidence: Mapped[SimulatorEvidence | None] = mapped_column(JSON)
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
