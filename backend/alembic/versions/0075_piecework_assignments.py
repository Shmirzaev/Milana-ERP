"""Retain the abandoned duplicate piecework branch as a no-op placeholder.

Revision ID: 0075_piecework_assignments
Revises: 0074_cutting_nastilchi
"""

revision = "0075_piecework_assignments"
down_revision = "0074_cutting_nastilchi"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The canonical schema is created by 0080_piecework_assignments. This
    # revision remains only so installations that discovered the old branch
    # can converge on the merged migration graph without duplicate DDL.
    pass


def downgrade() -> None:
    pass
