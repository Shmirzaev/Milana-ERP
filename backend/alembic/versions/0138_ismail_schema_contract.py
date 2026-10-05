"""Align HR indexes and remove seven proven duplicate catalog objects.

This forward revision never repairs business rows or reruns historical grants.
Production application requires catalog preflight, backup and approval (D2).
"""
from alembic import op
import sqlalchemy as sa

revision = "0138_ismail_schema_contract"
down_revision = "0137_perf34_shipment_indexes"
branch_labels = None
depends_on = None

HR_INDEXES = (
    ("hr_calendar_events", "employee_id"),
    ("hr_calendar_events", "event_type"),
    ("hr_employee_documents", "category"),
    ("hr_org_units", "department_id"),
    ("hr_org_units", "manager_employee_id"),
    ("hr_positions", "department_id"),
    ("hr_positions", "org_unit_id"),
    ("hr_recruitment_candidates", "position_id"),
    ("hr_recruitment_candidates", "stage"),
)
OWNER = "milana:0138_ismail_schema_contract"
REDUNDANT = "ix_material_reservations_reservation_no"
COVERING = "uq_material_reservations_reservation_no"
UNIQUE_PAIRS = (
    ("material_reservations", REDUNDANT, COVERING, "reservation_no"),
    ("branded_planning_orders", "ix_branded_planning_orders_order_no", "branded_planning_orders_order_no_key", "order_no"),
)
FK_PAIRS = (
    ("models", "models_brand_id_fkey", "fk_models_brand_id", "brand_id", "brands"),
    ("models", "models_collection_id_fkey", "fk_models_collection_id", "collection_id", "collections"),
    ("models", "models_constructor_employee_id_fkey", "fk_models_constructor_employee_id", "constructor_employee_id", "employees"),
    ("models", "models_designer_employee_id_fkey", "fk_models_designer_employee_id", "designer_employee_id", "employees"),
    ("sales_orders", "sales_orders_planning_estimate_submitted_by_fkey", "fk_sales_orders_planning_estimate_submitted_by_users", "planning_estimate_submitted_by", "users"),
)


def unique_index_plan(bind, table, redundant, covering):
    """Read-only exact catalog check; names alone never authorize a DROP."""
    if bind.dialect.name != "postgresql":
        raise RuntimeError("0138 catalog verification requires PostgreSQL")
    indexes = sa.inspect(bind).get_indexes(table)
    if not any(index["name"] == redundant for index in indexes):
        return "already_absent"
    equivalent = bind.execute(sa.text("""
        SELECT a.indisunique AND b.indisunique AND a.indisvalid AND b.indisvalid
          AND a.indisready AND b.indisready AND a.indimmediate = b.indimmediate
          AND NOT a.indisprimary AND NOT b.indisprimary
          AND a.indrelid = b.indrelid AND a.indkey = b.indkey
          AND a.indclass = b.indclass AND a.indcollation = b.indcollation
          AND a.indoption = b.indoption AND a.indnkeyatts = b.indnkeyatts
          AND a.indnatts = b.indnatts AND a.indnatts = 1
          AND a.indnullsnotdistinct = b.indnullsnotdistinct
          AND a.indpred IS NULL AND b.indpred IS NULL
          AND a.indexprs IS NULL AND b.indexprs IS NULL
          AND ia.relam = ib.relam
          AND c.contype = 'u'
          AND NOT EXISTS (SELECT 1 FROM pg_constraint d WHERE d.conindid = a.indexrelid)
        FROM pg_index a JOIN pg_index b ON b.indrelid = a.indrelid
        JOIN pg_class ia ON ia.oid = a.indexrelid
        JOIN pg_class ib ON ib.oid = b.indexrelid
        JOIN pg_constraint c ON c.conindid = b.indexrelid
        WHERE a.indexrelid = to_regclass(:redundant)
          AND b.indexrelid = to_regclass(:covering)
          AND a.indrelid = to_regclass(:table)
    """), {"redundant": redundant, "covering": covering, "table": table}).scalar()
    if equivalent is not True:
        raise RuntimeError("Refusing duplicate-index cleanup: catalog identity/coverage differs")
    return "drop_redundant"


def reservation_index_plan(bind):
    return unique_index_plan(bind, "material_reservations", REDUNDANT, COVERING)


def foreign_key_plan(bind, table, redundant, covering):
    if not any(key["name"] == redundant for key in sa.inspect(bind).get_foreign_keys(table)):
        return "already_absent"
    equivalent = bind.execute(sa.text("""
        SELECT a.confrelid = b.confrelid AND a.conkey = b.conkey AND a.confkey = b.confkey
          AND a.conpfeqop = b.conpfeqop AND a.conppeqop = b.conppeqop AND a.conffeqop = b.conffeqop
          AND a.confupdtype = b.confupdtype AND a.confdeltype = b.confdeltype
          AND a.confmatchtype = b.confmatchtype
          AND a.condeferrable = b.condeferrable AND a.condeferred = b.condeferred
          AND a.convalidated AND b.convalidated AND a.conislocal AND b.conislocal
          AND a.coninhcount = 0 AND b.coninhcount = 0 AND a.conparentid = 0 AND b.conparentid = 0
          AND a.confupdtype = 'a' AND a.confdeltype = 'a' AND a.confmatchtype = 's'
          AND NOT a.condeferrable
        FROM pg_constraint a JOIN pg_constraint b ON a.conrelid = b.conrelid
        WHERE a.contype = 'f' AND b.contype = 'f' AND a.conrelid = to_regclass(:table)
          AND a.conname = :redundant AND b.conname = :covering
    """), {"table": table, "redundant": redundant, "covering": covering}).scalar()
    if equivalent is not True:
        raise RuntimeError("Refusing duplicate-FK cleanup: catalog identity/actions differ")
    return "drop_redundant"


def upgrade():
    bind = op.get_bind()
    index_cleanup = [(table, redundant, unique_index_plan(bind, table, redundant, covering))
                     for table, redundant, covering, _ in UNIQUE_PAIRS]
    fk_cleanup = [(table, redundant, foreign_key_plan(bind, table, redundant, covering))
                  for table, redundant, covering, _, _ in FK_PAIRS]
    # Validate every existing same-name index before creating or dropping any.
    missing = []
    for table, column in HR_INDEXES:
        name = f"ix_{table}_{column}"
        existing = next((index for index in sa.inspect(bind).get_indexes(table) if index["name"] == name), None)
        if existing is None:
            missing.append((table, column, name))
        elif (existing["column_names"] != [column] or existing["unique"]
              or any((existing.get("dialect_options") or {}).values())):
            raise RuntimeError(f"Refusing schema alignment: unexpected index {name}")
    for table, column, name in missing:
        op.create_index(name, table, [column])
        bind.execute(sa.text(f'COMMENT ON INDEX "{name}" IS :owner'), {"owner": OWNER})
    for table, redundant, action in index_cleanup:
        if action == "drop_redundant":
            op.drop_index(redundant, table_name=table)
    for table, redundant, action in fk_cleanup:
        if action == "drop_redundant":
            op.drop_constraint(redundant, table, type_="foreignkey")


def downgrade():
    bind = op.get_bind()
    # Restore the canonical predecessor's redundant objects. This does not undo
    # unrelated prior manual schema customization; review live rollback separately.
    for table, redundant, _, column in UNIQUE_PAIRS:
        if not any(index["name"] == redundant for index in sa.inspect(bind).get_indexes(table)):
            op.create_index(redundant, table, [column], unique=True)
    for table, redundant, _, column, target in FK_PAIRS:
        if not any(key["name"] == redundant for key in sa.inspect(bind).get_foreign_keys(table)):
            op.create_foreign_key(redundant, table, target, [column], ["id"])
    # Preserve indexes that existed before this revision was applied.
    for table, column in reversed(HR_INDEXES):
        name = f"ix_{table}_{column}"
        owner = bind.execute(sa.text("SELECT obj_description(to_regclass(:name), 'pg_class')"), {"name": name}).scalar()
        if owner == OWNER:
            op.drop_index(name, table_name=table)
