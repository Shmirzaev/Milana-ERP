"""Join the released ECO and preserved turnstile migration histories."""

revision = "0155_eco_gate_merge"
down_revision = ("0154_eco_receipt_details", "0153_gate_revoke_tombstone")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
