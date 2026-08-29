"""add isolated read-only attendance mirror

Revision ID: 0102_attendance_mirror
Revises: 0101_payroll_factory_scope
"""

from alembic import op
import sqlalchemy as sa


revision = "0102_attendance_mirror"
down_revision = "0101_payroll_factory_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "attendance_devices",
        sa.Column("factory_code", sa.String(length=3), nullable=False),
        sa.Column("device_key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("vendor", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("serial_no", sa.String(length=128), nullable=True),
        sa.Column("source_host", sa.String(length=255), nullable=True),
        sa.Column("read_only", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("reported_person_count", sa.Integer(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_people_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_event_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("factory_code IN ('MIL', 'BST', 'ECO')", name="ck_attendance_devices_factory_code"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("factory_code", "device_key", name="uq_attendance_devices_factory_device_key"),
    )
    op.create_index("ix_attendance_devices_factory_code", "attendance_devices", ["factory_code"])

    op.create_table(
        "attendance_people",
        sa.Column("factory_code", sa.String(length=3), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("external_person_id", sa.String(length=64), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("user_type", sa.String(length=32), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_valid", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("has_face", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("card_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("fingerprint_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("photo_file_name", sa.String(length=255), nullable=True),
        sa.Column("photo_sha256", sa.String(length=64), nullable=True),
        sa.Column("present_on_device", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("factory_code IN ('MIL', 'BST', 'ECO')", name="ck_attendance_people_factory_code"),
        sa.ForeignKeyConstraint(["device_id"], ["attendance_devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_id", "external_person_id", name="uq_attendance_people_device_person"),
    )
    op.create_index("ix_attendance_people_factory_code", "attendance_people", ["factory_code"])
    op.create_index("ix_attendance_people_device_id", "attendance_people", ["device_id"])
    op.create_index("ix_attendance_people_external_person_id", "attendance_people", ["external_person_id"])
    op.create_index("ix_attendance_people_present_on_device", "attendance_people", ["present_on_device"])

    op.create_table(
        "attendance_events",
        sa.Column("factory_code", sa.String(length=3), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=True),
        sa.Column("event_uid", sa.String(length=160), nullable=False),
        sa.Column("external_person_id", sa.String(length=64), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("verification_mode", sa.String(length=64), nullable=True),
        sa.Column("result", sa.String(length=32), nullable=True),
        sa.Column("door_no", sa.Integer(), nullable=True),
        sa.Column("reader_no", sa.Integer(), nullable=True),
        sa.Column("serial_no", sa.Integer(), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.CheckConstraint("factory_code IN ('MIL', 'BST', 'ECO')", name="ck_attendance_events_factory_code"),
        sa.ForeignKeyConstraint(["device_id"], ["attendance_devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["person_id"], ["attendance_people.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_id", "event_uid", name="uq_attendance_events_device_event"),
    )
    op.create_index("ix_attendance_events_factory_code", "attendance_events", ["factory_code"])
    op.create_index("ix_attendance_events_device_id", "attendance_events", ["device_id"])
    op.create_index("ix_attendance_events_person_id", "attendance_events", ["person_id"])
    op.create_index("ix_attendance_events_external_person_id", "attendance_events", ["external_person_id"])
    op.create_index("ix_attendance_events_occurred_at", "attendance_events", ["occurred_at"])
    op.create_index("ix_attendance_events_factory_occurred", "attendance_events", ["factory_code", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_attendance_events_factory_occurred", table_name="attendance_events")
    op.drop_table("attendance_events")
    op.drop_table("attendance_people")
    op.drop_table("attendance_devices")

