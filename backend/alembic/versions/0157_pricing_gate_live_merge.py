"""Join deployed variant pricing and additive guarded turnstile storage.

No business rows or existing migration definitions are changed by this merge.
"""

revision = "0157_pricing_gate_live_merge"
down_revision = ("0156_variant_price_workflow", "0156_gate_live_integration")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
