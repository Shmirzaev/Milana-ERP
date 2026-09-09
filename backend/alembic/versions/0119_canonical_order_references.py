"""Canonical four-digit order identities with permanent historical aliases."""
from collections import Counter
import json
import re

from alembic import op
import sqlalchemy as sa

revision = "0119_canonical_order_references"
down_revision = "0118_paid_process_catalog"
branch_labels = None
depends_on = None

PRIMARY = {
    "SO": ("sales_orders", "order_no"), "PO": ("production_orders", "production_no"),
    "USL": ("production_orders", "production_no"), "PR": ("purchase_requests", "request_no"),
    "PUR": ("purchase_orders", "po_no"),
}


def plan_namespace(namespace, records, blocked=()):
    """Pure deterministic preflight: preserve valid references, then unique suffixes."""
    records = sorted(records, key=lambda row: int(row["id"]))
    if len(records) > 9999:
        raise RuntimeError(f"{namespace}: more than 9999 orders cannot use four-digit references")
    used = set(blocked)
    assigned = {}
    candidates = {}
    for row in records:
        reference = str(row["reference"] or "")
        exact = re.fullmatch(rf"{namespace}-([0-9]{{4}})", reference)
        if exact and 1 <= int(exact[1]) <= 9999:
            number = int(exact[1])
            if number in used:
                raise RuntimeError(f"{namespace}: existing canonical identity collision")
            assigned[row["id"]] = number
            used.add(number)
            continue
        legacy = re.fullmatch(r"(?:SO|PO|USL|PR|PUR)-(?:[0-9]{4}-)?([0-9]+)(?:-[0-9]+)?", reference, re.I)
        if legacy and 1 <= int(legacy[1]) <= 9999:
            candidates[row["id"]] = int(legacy[1])
    counts = Counter(candidates.values())
    for entity_id, number in candidates.items():
        if counts[number] == 1 and number not in used:
            assigned[entity_id] = number
            used.add(number)
    free = (number for number in range(1, 10000) if number not in used)
    for row in records:
        if row["id"] not in assigned:
            number = next(free, None)
            if number is None:
                raise RuntimeError(f"{namespace}: four-digit namespace is exhausted")
            assigned[row["id"]] = number
    return [dict(namespace=namespace, entity_id=row["id"], reference=str(row["reference"] or ""),
                 canonical_reference=f"{namespace}-{assigned[row['id']]:04d}") for row in records]


def _public(reference):
    return "SO-" + reference[3:] if reference.startswith("PO-") else reference


def _managed_legacy(value):
    return isinstance(value, str) and bool(re.fullmatch(r"(?:SO|PO|USL|PR|PUR)-[0-9]{4}-[0-9]+(?:-[0-9]+)?", value))


def _payload_hints(payload):
    def positive(value):
        try:
            number = int(value)
            return number if number > 0 else None
        except (ValueError, TypeError):
            return None
    if not isinstance(payload, str):
        return None, None
    if payload.startswith("MW2*"):
        parts = payload.split("*")
        return positive(parts[1]) if len(parts) > 1 else None, positive(parts[14]) if len(parts) > 14 else None
    try:
        data = json.loads(payload)
    except (ValueError, TypeError):
        return None, None
    if not isinstance(data, dict):
        return None, None
    return positive(data.get("production_order_id", data.get("pid"))), positive(data.get("sales_order_id", data.get("soid")))


def rewrite_payroll_payload(payload, production_map, sales_map, ambiguous_sales=(), fail_unknown=False):
    """Change reference fields only; issued label/scan UID, quantities and rates survive."""
    if not isinstance(payload, str) or not payload:
        return payload
    if payload.startswith("MW2*"):
        parts = payload.split("*")
        original = list(parts)
        if len(parts) > 2:
            if fail_unknown and _managed_legacy(parts[2]) and parts[2] not in production_map:
                raise RuntimeError("Unknown managed production reference inside issued MW2 payload")
            parts[2] = production_map.get(parts[2], parts[2])
        if len(parts) > 15:
            if parts[15] in ambiguous_sales:
                raise RuntimeError("Ambiguous unlinked order reference inside issued MW2 payload")
            if fail_unknown and _managed_legacy(parts[15]) and parts[15] not in sales_map:
                raise RuntimeError("Unknown managed sales reference inside issued MW2 payload")
            parts[15] = sales_map.get(parts[15], parts[15])
        return "*".join(parts) if parts != original else payload
    try:
        data = json.loads(payload)
    except (ValueError, TypeError):
        return payload
    if not isinstance(data, dict):
        return payload
    changed = False
    for keys, mapping in ((["production_no", "productionNo", "po"], production_map),
                          (["sales_order_no", "salesOrderNo", "so"], sales_map)):
        for key in keys:
            old = data.get(key)
            if key in {"sales_order_no", "salesOrderNo", "so"} and isinstance(old, str) and old in ambiguous_sales:
                raise RuntimeError("Ambiguous unlinked order reference inside issued JSON payload")
            if fail_unknown and _managed_legacy(old) and old not in mapping:
                raise RuntimeError("Unknown managed order reference inside issued JSON payload")
            if isinstance(old, str) and old in mapping and mapping[old] != old:
                data[key] = mapping[old]
                changed = True
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")) if changed else payload


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '10s'")
        op.execute("SET LOCAL statement_timeout = '120s'")
        # Lock the whole dependent graph before taking the canonical mapping snapshot.
        op.execute("LOCK TABLE sales_orders, production_orders, purchase_requests, purchase_orders, "
                   "payroll_records, payroll_qr_labels, sewing_daily_reports, cutting_passports, "
                   "stock_batches, bundles IN SHARE ROW EXCLUSIVE MODE")
    metadata = sa.MetaData()
    names = {name for name, _ in PRIMARY.values()} | {
        "branded_planning_orders", "payroll_records", "payroll_qr_labels", "sewing_daily_reports",
        "cutting_passports", "stock_batches", "bundles",
    }
    tables = {name: sa.Table(name, metadata, autoload_with=bind) for name in names}
    originals = {name: [dict(row) for row in bind.execute(sa.select(table)).mappings()]
                 for name, table in tables.items() if name in {value[0] for value in PRIMARY.values()}}
    plans = []
    for namespace, (table_name, column) in PRIMARY.items():
        records = originals[table_name]
        if namespace in {"PO", "USL"}:
            records = [row for row in records if (row.get("source_type") == "usluga") == (namespace == "USL")]
        blocked = set()
        if namespace in {"PO", "USL"}:
            own_ids = {row["id"] for row in records}
            for row in originals[table_name]:
                match = re.fullmatch(rf"{namespace}-([0-9]{{4}})", str(row[column]))
                if row["id"] not in own_ids and match:
                    blocked.add(int(match[1]))
        plans.extend(plan_namespace(namespace, [dict(id=row["id"], reference=row[column]) for row in records], blocked))

    by_namespace = {namespace: {row["reference"]: row["canonical_reference"] for row in plans if row["namespace"] == namespace}
                    for namespace in PRIMARY}
    by_id = {namespace: {row["entity_id"]: row["canonical_reference"] for row in plans if row["namespace"] == namespace}
             for namespace in PRIMARY}
    production_map = {**by_namespace["PO"], **by_namespace["USL"]}
    production_ids = {**by_id["PO"], **by_id["USL"]}
    old_production = {row["id"]: row for row in originals["production_orders"]}
    public_map, public_ids, public_aliases = {}, {}, []
    for row in originals["production_orders"]:
        if row.get("sales_order_id") in by_id["SO"]:
            public_ids[row["id"]] = by_id["SO"][row["sales_order_id"]]
            continue
        old, new = _public(row["production_no"]), production_ids[row["id"]]
        if old in public_map and public_map[old] != new:
            raise RuntimeError("Ambiguous historical public production-order reference")
        public_map[old] = new
        public_ids[row["id"]] = new
        if old != new:
            public_aliases.append(dict(namespace="PUBLIC_PO", entity_id=row["id"], reference=old, canonical_reference=new))

    # Existing BSO numbers already follow the requested four-digit convention.
    # Reject unreviewed exceptions instead of silently changing planning identities.
    for (reference,) in bind.execute(sa.select(tables["branded_planning_orders"].c.order_no)):
        if not re.fullmatch(r"[0-9]{4}", str(reference)):
            raise RuntimeError("Branded planning contains a non-four-digit reference; review its mapping first")

    sales_map = dict(public_map)
    sales_map.update(by_namespace["SO"])
    ambiguous_sales = {key for key in public_map.keys() & by_namespace["SO"].keys()
                       if public_map[key] != by_namespace["SO"][key]}

    def mapped(value, mapping):
        return mapping.get(value, value) if isinstance(value, str) else value

    def row_refs(row):
        pid, sid = row.get("production_order_id"), row.get("sales_order_id")
        prod = production_ids.get(pid)
        sale = by_id["SO"].get(sid)
        if sale is None and pid in public_ids:
            sale = public_ids[pid]
        return prod, sale

    # Build every dependent update before the first mutation; ambiguous unlinked
    # references must fail the migration, not be silently assigned to another order.
    updates = []
    for name in ("payroll_records", "payroll_qr_labels", "sewing_daily_reports", "cutting_passports", "stock_batches"):
        table = tables[name]
        fields = [field for field in ("production_no", "sales_order_no", "order_no", "internal_batch_no", "payload",
                                      "production_order_id", "sales_order_id") if field in table.c]
        for row in bind.execute(sa.select(table.c.id, *(table.c[field] for field in fields))).mappings():
            context = dict(row)
            if name == "payroll_qr_labels":
                hinted_pid, hinted_sid = _payload_hints(row.get("payload"))
                if context.get("production_order_id") is None and hinted_pid in production_ids:
                    context["production_order_id"] = hinted_pid
                if context.get("sales_order_id") is None and hinted_sid in by_id["SO"]:
                    context["sales_order_id"] = hinted_sid
            prod, sale = row_refs(context)
            patch = {}
            generic_map = {**production_map, **by_namespace["PR"], **by_namespace["PUR"], **sales_map}
            for field, mapping in (("production_no", production_map), ("sales_order_no", sales_map),
                                   ("order_no", generic_map), ("internal_batch_no", by_namespace["PUR"])):
                if _managed_legacy(row.get(field)) and row[field] not in mapping:
                    raise RuntimeError(f"{name}: unknown managed order reference in {field}")
            for field in ("sales_order_no", "order_no"):
                if row.get(field) in ambiguous_sales and sale is None:
                    raise RuntimeError(f"{name}: ambiguous unlinked public/sales order reference")
            if "production_no" in fields and row["production_no"] is not None:
                patch["production_no"] = prod or mapped(row["production_no"], production_map)
            if "sales_order_no" in fields and row["sales_order_no"] is not None:
                patch["sales_order_no"] = sale or mapped(row["sales_order_no"], sales_map)
            if "order_no" in fields and row["order_no"] is not None:
                patch["order_no"] = sale or mapped(row["order_no"], generic_map)
            if "internal_batch_no" in fields and row["internal_batch_no"] is not None:
                patch["internal_batch_no"] = mapped(row["internal_batch_no"], by_namespace["PUR"])
            if name == "payroll_qr_labels" and row["payload"]:
                payload_sales = dict(sales_map)
                payload_prod = dict(production_map)
                unresolved = set(ambiguous_sales)
                old_po = old_production.get(context.get("production_order_id"))
                if sale and old_po:
                    old_public = _public(old_po["production_no"])
                    payload_sales[old_public] = sale
                    unresolved.discard(old_public)
                if context.get("sales_order_id") in by_id["SO"]:
                    for alias in plans:
                        if alias["namespace"] == "SO" and alias["entity_id"] == context["sales_order_id"]:
                            payload_sales[alias["reference"]] = alias["canonical_reference"]
                            unresolved.discard(alias["reference"])
                if sale and row.get("sales_order_no"):
                    payload_sales[row["sales_order_no"]] = sale
                    unresolved.discard(row["sales_order_no"])
                if prod and row.get("production_no"):
                    payload_prod[row["production_no"]] = prod
                patch["payload"] = rewrite_payroll_payload(row["payload"], payload_prod, payload_sales, unresolved, fail_unknown=True)
            patch = {key: value for key, value in patch.items() if value != row[key]}
            if patch:
                updates.append((name, row["id"], patch))

    aliases = op.create_table(
        "business_order_aliases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("namespace", sa.String(16), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("reference", sa.String(128), nullable=False),
        sa.Column("canonical_reference", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("namespace", "reference", name="uq_business_order_alias_reference"),
    )
    op.create_index("ix_business_order_alias_entity", "business_order_aliases", ["namespace", "entity_id"])
    changed = [row for row in plans if row["reference"] != row["canonical_reference"]]
    if changed or public_aliases:
        op.bulk_insert(aliases, changed + public_aliases)
    for row in changed:
        table_name, column = PRIMARY[row["namespace"]]
        table = tables[table_name]
        bind.execute(table.update().where(table.c.id == row["entity_id"]).values({column: f"__order_0119_{row['entity_id']}"}))
    for row in changed:
        table_name, column = PRIMARY[row["namespace"]]
        table = tables[table_name]
        bind.execute(table.update().where(table.c.id == row["entity_id"]).values({column: row["canonical_reference"]}))
    for table_name, entity_id, patch in updates:
        table = tables[table_name]
        bind.execute(table.update().where(table.c.id == entity_id).values(patch))
    bundles = tables["bundles"]
    bind.execute(bundles.update().values(qr_code_url=sa.literal("/api/barcode/bundle-image/") + sa.cast(bundles.c.id, sa.String)))


def downgrade():
    raise RuntimeError("Canonical order references require a reviewed rollback mapping; restore the pre-migration backup")
