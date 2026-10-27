"""Add isolated HR workspace tables and employee profile fields.

Revision ID: 0110_hr_workspace
Revises: 0109_reassign_121_122_ect
"""

from alembic import op
import sqlalchemy as sa


revision = "0110_hr_workspace"
down_revision = "0109_reassign_121_122_ect"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hr_org_units",
        sa.Column("factory_code", sa.String(3), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("department_id", sa.Integer(), nullable=True),
        sa.Column("manager_employee_id", sa.Integer(), nullable=True),
        sa.Column("unit_type", sa.String(24), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("code", sa.String(48), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["parent_id"], ["hr_org_units.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"]),
        sa.ForeignKeyConstraint(["manager_employee_id"], ["employees.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("factory_code", "unit_type", "name", "parent_id", name="uq_hr_org_unit_path"),
    )
    op.create_index("ix_hr_org_units_factory_code", "hr_org_units", ["factory_code"])
    op.create_index("ix_hr_org_units_parent_id", "hr_org_units", ["parent_id"])

    op.create_table(
        "hr_positions",
        sa.Column("factory_code", sa.String(3), nullable=False),
        sa.Column("org_unit_id", sa.Integer(), nullable=True),
        sa.Column("department_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("job_description", sa.Text(), nullable=True),
        sa.Column("required_skills_json", sa.JSON(), nullable=False),
        sa.Column("qualification_level", sa.String(80), nullable=True),
        sa.Column("grade_level", sa.String(80), nullable=True),
        sa.Column("salary_min", sa.Numeric(14, 2), nullable=True),
        sa.Column("salary_max", sa.Numeric(14, 2), nullable=True),
        sa.Column("approved_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["org_unit_id"], ["hr_org_units.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"]),
    )
    op.create_index("ix_hr_positions_factory_code", "hr_positions", ["factory_code"])
    op.create_index("ix_hr_positions_name", "hr_positions", ["name"])

    op.add_column("employees", sa.Column("manager_employee_id", sa.Integer(), nullable=True))
    op.add_column("employees", sa.Column("hr_position_id", sa.Integer(), nullable=True))
    op.add_column("employees", sa.Column("hr_profile_json", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False))
    op.create_foreign_key("fk_employees_manager_employee_id", "employees", "employees", ["manager_employee_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_employees_hr_position_id", "employees", "hr_positions", ["hr_position_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_employees_manager_employee_id", "employees", ["manager_employee_id"])
    op.create_index("ix_employees_hr_position_id", "employees", ["hr_position_id"])

    op.create_table(
        "hr_employee_documents",
        sa.Column("factory_code", sa.String(3), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("stored_name", sa.String(255), nullable=False, unique=True),
        sa.Column("content_type", sa.String(128), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column("uploaded_by", sa.Integer(), nullable=True),
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_hr_employee_documents_factory_code", "hr_employee_documents", ["factory_code"])
    op.create_index("ix_hr_employee_documents_employee_id", "hr_employee_documents", ["employee_id"])

    op.create_table(
        "hr_recruitment_candidates",
        sa.Column("factory_code", sa.String(3), nullable=False),
        sa.Column("position_id", sa.Integer(), nullable=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(64), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("source", sa.String(80), nullable=True),
        sa.Column("stage", sa.String(32), server_default="applied", nullable=False),
        sa.Column("applied_on", sa.Date(), nullable=True),
        sa.Column("interview_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["position_id"], ["hr_positions.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_hr_recruitment_candidates_factory_code", "hr_recruitment_candidates", ["factory_code"])

    op.create_table(
        "hr_calendar_events",
        sa.Column("factory_code", sa.String(3), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(48), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(24), server_default="scheduled", nullable=False),
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_hr_calendar_events_factory_code", "hr_calendar_events", ["factory_code"])
    op.create_index("ix_hr_calendar_events_starts_at", "hr_calendar_events", ["starts_at"])


def downgrade() -> None:
    op.drop_table("hr_calendar_events")
    op.drop_table("hr_recruitment_candidates")
    op.drop_table("hr_employee_documents")
    op.drop_index("ix_employees_hr_position_id", table_name="employees")
    op.drop_index("ix_employees_manager_employee_id", table_name="employees")
    op.drop_constraint("fk_employees_hr_position_id", "employees", type_="foreignkey")
    op.drop_constraint("fk_employees_manager_employee_id", "employees", type_="foreignkey")
    op.drop_column("employees", "hr_profile_json")
    op.drop_column("employees", "hr_position_id")
    op.drop_column("employees", "manager_employee_id")
    op.drop_table("hr_positions")
    op.drop_table("hr_org_units")
