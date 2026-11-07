"""Preserve simulator revocation evidence.

Revision ID: 0153_gate_revoke_tombstone
Revises: 0152_gate_edit_baseline
"""
from alembic import op
import sqlalchemy as sa

revision = "0153_gate_revoke_tombstone"
down_revision = "0152_gate_edit_baseline"
branch_labels = None
depends_on = None

OLD_CHECK = "(action = 'edit' AND photo_asset_id IS NULL) OR (action <> 'edit' AND photo_asset_id IS NOT NULL)"
NEW_CHECK = "(action IN ('edit', 'revoke') AND photo_asset_id IS NULL) OR (action IN ('enroll', 'photo') AND photo_asset_id IS NOT NULL)"


def upgrade():
    op.add_column("gate_simulator_people", sa.Column("present", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.drop_constraint("ck_gate_operation_photo_action", "gate_operations", type_="check")
    op.create_check_constraint("ck_gate_operation_photo_action", "gate_operations", NEW_CHECK)


def downgrade():
    bind = op.get_bind()
    operations = bind.execute(sa.text("SELECT EXISTS (SELECT 1 FROM gate_operations WHERE action = 'revoke')")).scalar()
    tombstones = bind.execute(sa.text("SELECT EXISTS (SELECT 1 FROM gate_simulator_people WHERE present = false)")).scalar()
    evidence = bind.execute(sa.text("SELECT EXISTS (SELECT 1 FROM gate_targets WHERE observed_evidence ->> 'action' = 'revoke')")).scalar()
    if operations or tombstones or evidence:
        raise RuntimeError("Cannot downgrade revocation history or evidence")
    op.drop_constraint("ck_gate_operation_photo_action", "gate_operations", type_="check")
    op.create_check_constraint("ck_gate_operation_photo_action", "gate_operations", OLD_CHECK)
    op.drop_column("gate_simulator_people", "present")
