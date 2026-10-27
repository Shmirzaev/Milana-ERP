"""Internal Eco fabric custody ledger; grant only the existing Mubina account."""
from alembic import op
import sqlalchemy as sa

revision = "0130_eco_fabric_transfers"
down_revision = "0129_user_access_policy"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("eco_fabric_dispatches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_key", sa.String(36), nullable=False, unique=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("operator_name", sa.String(128), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("remaining_inventory", sa.JSON(), nullable=False))
    op.create_table("eco_fabric_rolls",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dispatch_id", sa.Integer(), sa.ForeignKey("eco_fabric_dispatches.id"), nullable=False),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("stock_batches.id"), nullable=False),
        sa.Column("roll_number", sa.Integer(), nullable=False),
        sa.Column("fabric_name", sa.String(255), nullable=False),
        sa.Column("batch_no", sa.String(64), nullable=False),
        sa.Column("color", sa.String(64)),
        sa.Column("quantity", sa.Numeric(14, 4), nullable=False),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("returned_at", sa.DateTime(timezone=True)),
        sa.Column("returned_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("return_operator_name", sa.String(128)),
        sa.Column("return_key", sa.String(36), unique=True),
        sa.CheckConstraint("quantity > 0 AND roll_number > 0", name="ck_eco_fabric_roll_positive"))
    op.create_index("ix_eco_fabric_rolls_dispatch_id", "eco_fabric_rolls", ["dispatch_id"])
    op.create_index("ix_eco_fabric_rolls_batch_id", "eco_fabric_rolls", ["batch_id"])
    op.create_index("uq_eco_fabric_roll_out", "eco_fabric_rolls", ["batch_id", "roll_number"], unique=True,
                    postgresql_where=sa.text("returned_at IS NULL"), sqlite_where=sa.text("returned_at IS NULL"))
    users = sa.table("users", sa.column("id", sa.Integer), sa.column("email", sa.String),
                     sa.column("extra_permissions", sa.JSON), sa.column("access_policy", sa.JSON))
    connection = op.get_bind()
    for user in connection.execute(sa.select(users).where(sa.func.lower(users.c.email) == "mubina@milanapremium.uz")).mappings():
        key = "inventory.eco_transfers"
        grants = list(dict.fromkeys([*(user["extra_permissions"] or []), key]))
        policy = dict(user["access_policy"] or {})
        if "MIL" in policy:
            mil = dict(policy["MIL"])
            mil["allow"] = list(dict.fromkeys([*mil.get("allow", []), key]))
            mil["deny"] = [x for x in mil.get("deny", []) if x != key]
            policy["MIL"] = mil
        connection.execute(users.update().where(users.c.id == user["id"]).values(
            extra_permissions=grants, access_policy=policy or None))


def downgrade():
    if op.get_bind().execute(sa.text("SELECT COUNT(*) FROM eco_fabric_dispatches")).scalar_one():
        raise RuntimeError("Preserve custody history and reconcile outstanding fabric before downgrade")
    op.drop_table("eco_fabric_rolls")
    op.drop_table("eco_fabric_dispatches")
    # Preserve explicit account grants; revocation requires a reviewed access change.
