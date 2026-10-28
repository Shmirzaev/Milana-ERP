"""add an indexed generated key for model-family pagination

Revision ID: 0084_model_group_key
Revises: 0083_employee_number
"""

from alembic import op


revision = "0084_model_group_key"
down_revision = "0083_employee_number"
branch_labels = None
depends_on = None


GROUP_KEY_SQL = r"""
CASE
    WHEN btrim(
        coalesce(
            nullif(btrim(details_json -> 'general' ->> 'model_no'), ''),
            nullif(btrim(details_json -> 'general' ->> 'modelNo'), ''),
            CASE
                WHEN strpos(reverse(btrim(coalesce(code, ''))), '-') > 1
                 AND strpos(reverse(btrim(coalesce(code, ''))), '-') < length(btrim(coalesce(code, '')))
                THEN substr(
                    btrim(coalesce(code, '')),
                    1,
                    length(btrim(coalesce(code, ''))) - strpos(reverse(btrim(coalesce(code, ''))), '-')
                )
                ELSE btrim(coalesce(code, ''))
            END,
            ''
        )
    ) <> ''
    THEN 'model:' || lower(
        regexp_replace(
            btrim(
                coalesce(
                    nullif(btrim(details_json -> 'general' ->> 'model_no'), ''),
                    nullif(btrim(details_json -> 'general' ->> 'modelNo'), ''),
                    CASE
                        WHEN strpos(reverse(btrim(coalesce(code, ''))), '-') > 1
                         AND strpos(reverse(btrim(coalesce(code, ''))), '-') < length(btrim(coalesce(code, '')))
                        THEN substr(
                            btrim(coalesce(code, '')),
                            1,
                            length(btrim(coalesce(code, ''))) - strpos(reverse(btrim(coalesce(code, ''))), '-')
                        )
                        ELSE btrim(coalesce(code, ''))
                    END,
                    ''
                )
            ),
            '\s+',
            ' ',
            'g'
        )
    )
    WHEN btrim(coalesce(name, '')) <> '' THEN
        'name:' || lower(regexp_replace(btrim(name), '\s+', ' ', 'g'))
    ELSE 'id:' || id::text
END
"""


def upgrade() -> None:
    # Fail safely instead of waiting indefinitely behind an active production
    # transaction. Alembic wraps the migration in one transaction, so these
    # limits apply only to this upgrade attempt.
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("SET LOCAL statement_timeout = '120s'")
    op.execute(
        "ALTER TABLE models "
        "ADD COLUMN is_legacy_import boolean GENERATED ALWAYS AS "
        "((coalesce(details_json ->> 'legacy_import', 'false')) = 'true') STORED"
    )
    op.execute(
        "ALTER TABLE models "
        f"ADD COLUMN model_group_key text GENERATED ALWAYS AS ({GROUP_KEY_SQL}) STORED"
    )
    op.execute(
        "CREATE INDEX ix_models_model_group_key_id "
        "ON models (is_legacy_import, model_group_key, id DESC)"
    )


def downgrade() -> None:
    op.drop_index("ix_models_model_group_key_id", table_name="models")
    op.drop_column("models", "model_group_key")
    op.drop_column("models", "is_legacy_import")
