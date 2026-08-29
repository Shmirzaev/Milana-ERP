"""add isolated Eco Cotton Usluga flow and managed attendance devices

Revision ID: 0105_eco_usluga_attendance
Revises: 0104_purchase_batch_images
Create Date: 2026-08-19
"""

from alembic import op
import sqlalchemy as sa


revision = "0105_eco_usluga_attendance"
down_revision = "0104_purchase_batch_images"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("models", sa.Column("catalog_scope", sa.String(length=16), server_default="standard", nullable=False))
    op.add_column("models", sa.Column("factory_code", sa.String(length=3), nullable=True))
    op.create_check_constraint("ck_models_catalog_scope", "models", "catalog_scope IN ('standard', 'usluga')")
    op.create_check_constraint("ck_models_usluga_factory", "models", "catalog_scope <> 'usluga' OR factory_code = 'ECO'")
    op.create_index("ix_models_catalog_scope", "models", ["catalog_scope"])
    op.create_index("ix_models_factory_code", "models", ["factory_code"])

    op.add_column("production_orders", sa.Column("source_type", sa.String(length=16), server_default="standard", nullable=False))
    op.add_column("production_orders", sa.Column("service_customer_name", sa.String(length=255), nullable=True))
    op.add_column("production_orders", sa.Column("service_customer_reference", sa.String(length=128), nullable=True))
    op.add_column("production_orders", sa.Column("service_material_description", sa.Text(), nullable=True))
    op.add_column("production_orders", sa.Column("service_material_usage_kg", sa.Numeric(14, 4), nullable=True))
    op.add_column("production_orders", sa.Column("service_material_notes", sa.Text(), nullable=True))
    op.add_column("production_orders", sa.Column("service_handover_recipient", sa.String(length=255), nullable=True))
    op.add_column("production_orders", sa.Column("service_handover_notes", sa.Text(), nullable=True))
    op.add_column("production_orders", sa.Column("handed_over_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("production_orders", sa.Column("handed_over_by", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_production_orders_handed_over_by_users", "production_orders", "users", ["handed_over_by"], ["id"])
    op.create_check_constraint("ck_production_orders_source_type", "production_orders", "source_type IN ('standard', 'usluga')")
    op.create_check_constraint(
        "ck_production_orders_service_material_usage_nonnegative",
        "production_orders",
        "service_material_usage_kg IS NULL OR service_material_usage_kg >= 0",
    )
    op.create_index("ix_production_orders_source_type", "production_orders", ["source_type"])

    op.add_column("attendance_devices", sa.Column("certificate_sha256", sa.String(length=64), nullable=True))
    op.add_column("attendance_devices", sa.Column("connector_token_hash", sa.String(length=64), nullable=True))
    op.add_column("attendance_devices", sa.Column("sync_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False))
    op.add_column("attendance_devices", sa.Column("configured_by", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_attendance_devices_configured_by_users", "attendance_devices", "users", ["configured_by"], ["id"])
    op.create_index("ix_attendance_devices_connector_token_hash", "attendance_devices", ["connector_token_hash"], unique=True)

    op.drop_constraint("ck_packages_status", "packages", type_="check")
    op.create_check_constraint(
        "ck_packages_status",
        "packages",
        "status IN ('packed', 'handed_over', 'received_in_storage', 'reserved', 'shipped', 'delivered', 'damaged')",
    )

    # No account is changed. Administrators can assign this role to the new
    # Eco Cotton service-order staff after local approval.
    op.execute(
        """
        INSERT INTO roles (name, permissions, created_at, updated_at)
        SELECT 'Eco Cotton Usluga',
               '["usluga.view", "usluga.manage", "usluga.handover", "planning.production"]',
               CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        WHERE NOT EXISTS (SELECT 1 FROM roles WHERE lower(name) = 'eco cotton usluga')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM roles
        WHERE lower(name) = 'eco cotton usluga'
          AND NOT EXISTS (SELECT 1 FROM users WHERE users.role_id = roles.id)
        """
    )
    op.drop_constraint("ck_packages_status", "packages", type_="check")
    op.create_check_constraint(
        "ck_packages_status",
        "packages",
        "status IN ('packed', 'received_in_storage', 'reserved', 'shipped', 'delivered', 'damaged')",
    )
    op.drop_index("ix_attendance_devices_connector_token_hash", table_name="attendance_devices")
    op.drop_constraint("fk_attendance_devices_configured_by_users", "attendance_devices", type_="foreignkey")
    op.drop_column("attendance_devices", "configured_by")
    op.drop_column("attendance_devices", "sync_enabled")
    op.drop_column("attendance_devices", "connector_token_hash")
    op.drop_column("attendance_devices", "certificate_sha256")

    op.drop_index("ix_production_orders_source_type", table_name="production_orders")
    op.drop_constraint("ck_production_orders_service_material_usage_nonnegative", "production_orders", type_="check")
    op.drop_constraint("ck_production_orders_source_type", "production_orders", type_="check")
    op.drop_constraint("fk_production_orders_handed_over_by_users", "production_orders", type_="foreignkey")
    for column in (
        "handed_over_by", "handed_over_at", "service_handover_notes", "service_handover_recipient",
        "service_material_notes", "service_material_usage_kg", "service_material_description",
        "service_customer_reference", "service_customer_name", "source_type",
    ):
        op.drop_column("production_orders", column)

    op.drop_index("ix_models_factory_code", table_name="models")
    op.drop_index("ix_models_catalog_scope", table_name="models")
    op.drop_constraint("ck_models_usluga_factory", "models", type_="check")
    op.drop_constraint("ck_models_catalog_scope", "models", type_="check")
    op.drop_column("models", "factory_code")
    op.drop_column("models", "catalog_scope")
