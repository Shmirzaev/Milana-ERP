"""Create the twenty Eco Cotton sewing bands.

Revision ID: 0088_eco_cotton_sewing_bands
Revises: 0087_sewing_flow_factories
"""

from alembic import op
import sqlalchemy as sa


revision = "0088_eco_cotton_sewing_bands"
down_revision = "0087_sewing_flow_factories"
branch_labels = None
depends_on = None


LEGACY_ECO_LINES = (
    ("Bozorova Nargiza", "SEW-01", 600),
    ("Botirova Shaxnoza", "SEW-06", 200),
    ("Jalolova Nargiza", "SEW-07", 800),
    ("Akbarova Dilafruz", "SEW-09", 200),
    ("Maxmudova Nargiza - 1", "SEW-10", 400),
    ("Botirova Muxlisa", "SEW-12", 200),
    ("Maxmudova Nargiza - 2", "SEW-13", 200),
)


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            """
            SELECT id, capacity_per_day
            FROM sewing_flows
            WHERE factory_code = 'ECO'
            ORDER BY id
            """
        )
    ).fetchall()

    for row in rows:
        connection.execute(
            sa.text(
                """
                UPDATE sewing_flows
                SET name = :name, code = :code, updated_at = NOW()
                WHERE id = :flow_id
                """
            ),
            {
                "flow_id": int(row.id),
                "name": f"__ECO_BAND_NAME_{int(row.id)}",
                "code": f"__ECO_BAND_CODE_{int(row.id)}",
            },
        )

    for number in range(1, 21):
        if number <= len(rows):
            row = rows[number - 1]
            connection.execute(
                sa.text(
                    """
                    UPDATE sewing_flows
                    SET name = :name,
                        code = :code,
                        description = :description,
                        is_active = TRUE,
                        updated_at = NOW()
                    WHERE id = :flow_id
                    """
                ),
                {
                    "flow_id": int(row.id),
                    "name": f"{number}-Band",
                    "code": f"ECO-BAND-{number:02d}",
                    "description": f"Eco Cotton sewing band {number}-Band",
                },
            )
        else:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO sewing_flows
                        (factory_code, name, code, description, capacity_per_day,
                         supervisor_id, is_active, created_at, updated_at)
                    VALUES
                        ('ECO', :name, :code, :description, 200,
                         NULL, TRUE, NOW(), NOW())
                    """
                ),
                {
                    "name": f"{number}-Band",
                    "code": f"ECO-BAND-{number:02d}",
                    "description": f"Eco Cotton sewing band {number}-Band",
                },
            )

    for row in rows[20:]:
        connection.execute(
            sa.text(
                """
                UPDATE sewing_flows
                SET name = :name,
                    code = :code,
                    description = 'Archived extra Eco Cotton sewing line',
                    is_active = FALSE,
                    updated_at = NOW()
                WHERE id = :flow_id
                """
            ),
            {
                "flow_id": int(row.id),
                "name": f"Archived Eco Line {int(row.id)}",
                "code": f"ECO-ARCH-{int(row.id)}",
            },
        )


def downgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            """
            SELECT id
            FROM sewing_flows
            WHERE factory_code = 'ECO' AND code LIKE 'ECO-BAND-%'
            ORDER BY code
            """
        )
    ).fetchall()

    for number, row in enumerate(rows, start=1):
        if number <= len(LEGACY_ECO_LINES):
            name, code, capacity = LEGACY_ECO_LINES[number - 1]
            connection.execute(
                sa.text(
                    """
                    UPDATE sewing_flows
                    SET name = :name,
                        code = :code,
                        description = :description,
                        capacity_per_day = :capacity,
                        is_active = TRUE,
                        updated_at = NOW()
                    WHERE id = :flow_id
                    """
                ),
                {
                    "flow_id": int(row.id),
                    "name": name,
                    "code": code,
                    "description": f"ECO sewing flow {name}",
                    "capacity": capacity,
                },
            )
        else:
            connection.execute(
                sa.text(
                    """
                    UPDATE sewing_flows
                    SET name = :name,
                        code = :code,
                        description = 'Archived Eco Cotton sewing band',
                        is_active = FALSE,
                        updated_at = NOW()
                    WHERE id = :flow_id
                    """
                ),
                {
                    "flow_id": int(row.id),
                    "name": f"Archived Eco Band {number}",
                    "code": f"ECO-ARCH-BAND-{number:02d}",
                },
            )
