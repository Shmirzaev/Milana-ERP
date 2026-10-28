from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PkMixin, TimestampMixin


class AttendanceDevice(Base, PkMixin, TimestampMixin):
    """Read-only mirror metadata for an external attendance device."""

    __tablename__ = "attendance_devices"
    __table_args__ = (
        UniqueConstraint("factory_code", "device_key", name="uq_attendance_devices_factory_device_key"),
    )

    factory_code: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    device_key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    vendor: Mapped[str] = mapped_column(String(64), nullable=False, default="Hikvision")
    model: Mapped[str | None] = mapped_column(String(128))
    serial_no: Mapped[str | None] = mapped_column(String(128))
    source_host: Mapped[str | None] = mapped_column(String(255))
    certificate_sha256: Mapped[str | None] = mapped_column(String(64))
    connector_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    sync_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    configured_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    read_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    reported_person_count: Mapped[int | None] = mapped_column(Integer)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_people_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_event_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    people: Mapped[list["AttendancePerson"]] = relationship(back_populates="device", cascade="all, delete-orphan")


class AttendancePerson(Base, PkMixin, TimestampMixin):
    """Person profile mirrored from a device; intentionally separate from HR employees."""

    __tablename__ = "attendance_people"
    __table_args__ = (
        UniqueConstraint("device_id", "external_person_id", name="uq_attendance_people_device_person"),
    )

    factory_code: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("attendance_devices.id", ondelete="CASCADE"), nullable=False, index=True)
    external_person_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    user_type: Mapped[str | None] = mapped_column(String(32))
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    has_face: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    card_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    fingerprint_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    photo_file_name: Mapped[str | None] = mapped_column(String(255))
    photo_sha256: Mapped[str | None] = mapped_column(String(64))
    present_on_device: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true", index=True)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    device: Mapped[AttendanceDevice] = relationship(back_populates="people")


class AttendanceEvent(Base, PkMixin):
    """Immutable access event mirrored from a device."""

    __tablename__ = "attendance_events"
    __table_args__ = (
        UniqueConstraint("device_id", "event_uid", name="uq_attendance_events_device_event"),
    )

    factory_code: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("attendance_devices.id", ondelete="CASCADE"), nullable=False, index=True)
    person_id: Mapped[int | None] = mapped_column(ForeignKey("attendance_people.id", ondelete="SET NULL"), index=True)
    event_uid: Mapped[str] = mapped_column(String(160), nullable=False)
    external_person_id: Mapped[str | None] = mapped_column(String(64), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    verification_mode: Mapped[str | None] = mapped_column(String(64))
    result: Mapped[str | None] = mapped_column(String(32))
    door_no: Mapped[int | None] = mapped_column(Integer)
    reader_no: Mapped[int | None] = mapped_column(Integer)
    serial_no: Mapped[int | None] = mapped_column(Integer)
