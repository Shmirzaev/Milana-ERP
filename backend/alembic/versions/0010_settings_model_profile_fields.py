"""settings and model metadata fields

Revision ID: 0010_settings_model_fields
Revises: 0009_package_batch_link
Create Date: 2026-05-23
"""

from alembic import op
import sqlalchemy as sa


revision = "0010_settings_model_fields"
down_revision = "0009_package_batch_link"
branch_labels = None
depends_on = None


def _has_column(inspector, table: str, column: str) -> bool:
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "system_settings" not in tables:
        op.create_table(
            "system_settings",
            sa.Column("key", sa.String(length=64), nullable=False),
            sa.Column("value_json", sa.JSON(), nullable=False),
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("key"),
        )
        op.create_index(op.f("ix_system_settings_key"), "system_settings", ["key"], unique=True)

    if "models" in tables:
        model_columns = {
            "brand_id": sa.Column("brand_id", sa.Integer(), nullable=True),
            "collection_id": sa.Column("collection_id", sa.Integer(), nullable=True),
            "product_type": sa.Column("product_type", sa.String(length=64), nullable=True),
            "season": sa.Column("season", sa.String(length=64), nullable=True),
            "constructor_employee_id": sa.Column("constructor_employee_id", sa.Integer(), nullable=True),
            "designer_employee_id": sa.Column("designer_employee_id", sa.Integer(), nullable=True),
        }
        for name, column in model_columns.items():
            if not _has_column(inspector, "models", name):
                op.add_column("models", column)

        if bind.dialect.name != "sqlite":
            existing_fks = {fk.get("name") for fk in inspector.get_foreign_keys("models")}
            fk_defs = [
                ("fk_models_brand_id", "brand_id", "brands"),
                ("fk_models_collection_id", "collection_id", "collections"),
                ("fk_models_constructor_employee_id", "constructor_employee_id", "employees"),
                ("fk_models_designer_employee_id", "designer_employee_id", "employees"),
            ]
            for fk_name, column_name, target_table in fk_defs:
                if fk_name not in existing_fks:
                    op.create_foreign_key(fk_name, "models", target_table, [column_name], ["id"])

    if "model_images" in tables:
        if not _has_column(inspector, "model_images", "file_name"):
            op.add_column("model_images", sa.Column("file_name", sa.String(length=255), nullable=True))
        if not _has_column(inspector, "model_images", "content_type"):
            op.add_column("model_images", sa.Column("content_type", sa.String(length=128), nullable=True))

    if "collections" in tables:
        op.execute("UPDATE collections SET year = 2024 WHERE year IS NULL")
        if bind.dialect.name != "sqlite":
            op.alter_column("collections", "year", existing_type=sa.Integer(), nullable=False, server_default="2024")


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "models" in tables:
        if bind.dialect.name != "sqlite":
            for fk_name in [
                "fk_models_designer_employee_id",
                "fk_models_constructor_employee_id",
                "fk_models_collection_id",
                "fk_models_brand_id",
            ]:
                try:
                    op.drop_constraint(fk_name, "models", type_="foreignkey")
                except Exception:
                    pass
        for name in [
            "designer_employee_id",
            "constructor_employee_id",
            "season",
            "product_type",
            "collection_id",
            "brand_id",
        ]:
            if _has_column(inspector, "models", name):
                op.drop_column("models", name)

    if "model_images" in tables:
        for name in ["content_type", "file_name"]:
            if _has_column(inspector, "model_images", name):
                op.drop_column("model_images", name)

    if "system_settings" in tables:
        op.drop_index(op.f("ix_system_settings_key"), table_name="system_settings")
        op.drop_table("system_settings")
