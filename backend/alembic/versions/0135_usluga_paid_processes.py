"""Start a separate, empty reusable catalog for manually entered Usluga processes."""
from alembic import op
import sqlalchemy as sa

revision = "0135_usluga_paid_processes"
down_revision = "0134_packaging_returns"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "usluga_paid_processes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("factory_code", sa.String(3), nullable=False),
        sa.Column("code", sa.String(32), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("normalized_key", sa.String(64), nullable=False),
        sa.Column("section", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("factory_code", "normalized_key", "section", name="uq_usluga_paid_process_identity"),
    )
    op.create_index("ix_usluga_paid_processes_factory_code", "usluga_paid_processes", ["factory_code"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT count(*) FROM usluga_paid_processes")).scalar():
        raise RuntimeError("Preserve saved Usluga processes; use application rollback")
    op.drop_table("usluga_paid_processes")
