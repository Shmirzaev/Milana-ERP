"""Freeze per-target simulator edit baselines.

Revision ID: 0152_gate_edit_baseline
Revises: 0151_gate_enrollment
"""
from alembic import op
import sqlalchemy as sa

revision = "0152_gate_edit_baseline"
down_revision = "0151_gate_enrollment"
branch_labels = None
depends_on = None

COLUMNS = (
    ("baseline_revision", sa.Integer()),
    ("baseline_payload_hash", sa.String(64)),
    ("baseline_full_name", sa.String(255)),
    ("baseline_external_person_id", sa.String(64)),
    ("baseline_photo_sha256", sa.String(64)),
    ("baseline_profile_hash", sa.String(64)),
    ("desired_payload_hash", sa.String(64)),
)
BASELINE_CHECK = "(baseline_revision IS NULL AND baseline_payload_hash IS NULL AND baseline_full_name IS NULL AND baseline_external_person_id IS NULL AND baseline_photo_sha256 IS NULL AND baseline_profile_hash IS NULL AND desired_payload_hash IS NULL) OR (baseline_revision IS NOT NULL AND baseline_revision > 0 AND baseline_payload_hash IS NOT NULL AND length(baseline_payload_hash) = 64 AND baseline_full_name IS NOT NULL AND baseline_external_person_id IS NOT NULL AND baseline_photo_sha256 IS NOT NULL AND length(baseline_photo_sha256) = 64 AND baseline_profile_hash IS NOT NULL AND length(baseline_profile_hash) = 64 AND desired_payload_hash IS NOT NULL AND length(desired_payload_hash) = 64)"
PHOTO_CHECK = "(action = 'edit' AND photo_asset_id IS NULL) OR (action <> 'edit' AND photo_asset_id IS NOT NULL)"

def upgrade():
    op.alter_column("gate_operations", "photo_asset_id", existing_type=sa.Integer(), nullable=True)
    op.create_check_constraint("ck_gate_operation_photo_action", "gate_operations", PHOTO_CHECK)
    for name, type_ in COLUMNS:
        op.add_column("gate_targets", sa.Column(name, type_, nullable=True))
    op.create_check_constraint("ck_gate_target_edit_baseline", "gate_targets", BASELINE_CHECK)

def downgrade():
    bind = op.get_bind()
    edits = bind.execute(sa.text("SELECT EXISTS (SELECT 1 FROM gate_operations WHERE action = 'edit')")).scalar()
    baselines = bind.execute(sa.text("SELECT EXISTS (SELECT 1 FROM gate_targets WHERE " + " OR ".join(name + " IS NOT NULL" for name, _ in COLUMNS) + ")")).scalar()
    if edits or baselines:
        raise RuntimeError("Cannot downgrade gate edit history or baselines")
    op.drop_constraint("ck_gate_target_edit_baseline", "gate_targets", type_="check")
    for name, _ in reversed(COLUMNS):
        op.drop_column("gate_targets", name)
    op.drop_constraint("ck_gate_operation_photo_action", "gate_operations", type_="check")
    op.alter_column("gate_operations", "photo_asset_id", existing_type=sa.Integer(), nullable=False)
