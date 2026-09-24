"""separate existing paid operations by sewing factory

Revision ID: 0086_paid_operation_factories
Revises: 0085_supplier_archiving
"""

from copy import deepcopy
import json

from alembic import op
import sqlalchemy as sa


revision = "0086_paid_operation_factories"
down_revision = "0085_supplier_archiving"
branch_labels = None
depends_on = None


FACTORIES = ("milana", "besttex", "eco_cotton")
FACTORY_ALIASES = {
    "MIL": "milana",
    "MILANA": "milana",
    "SML": "milana",
    "BST": "besttex",
    "BESTTEX": "besttex",
    "BTX": "besttex",
    "ECO": "eco_cotton",
    "ECO COTTON": "eco_cotton",
    "ECO_COTTON": "eco_cotton",
    "ECOCOTTON": "eco_cotton",
}


def _validate_changed_details(details: dict, *, model_id: int | None) -> None:
    # Frozen migration-local copy of the live 64 KiB/16-container write bound.
    label = f"Model {model_id}" if model_id is not None else "Model"
    pending = [(details, 0)]
    while pending:
        value, parent_depth = pending.pop()
        if isinstance(value, (dict, list)):
            depth = parent_depth + 1
            if depth > 16:
                raise ValueError(f"{label} details_json cannot exceed 16 nested container levels")
            if isinstance(value, dict):
                if any(not isinstance(key, str) for key in value):
                    raise ValueError(f"{label} details_json must contain JSON-compatible values")
                pending.extend((child, depth) for child in value.values())
            else:
                pending.extend((child, depth) for child in value)
        elif value is not None and type(value) not in (str, bool, int, float):
            raise ValueError(f"{label} details_json must contain JSON-compatible values")
    try:
        serialized = json.dumps(details, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ValueError(f"{label} details_json must contain finite JSON-compatible values") from exc
    if len(serialized) > 64 * 1024:
        raise ValueError(f"{label} details_json cannot exceed 65536 UTF-8 bytes")


def _factory(row: object) -> str | None:
    if not isinstance(row, dict):
        return None
    raw = row.get("sewingFactory", row.get("sewing_factory", row.get("factory")))
    normalized = " ".join(str(raw or "").strip().upper().replace("-", " ").replace("_", " ").split())
    return FACTORY_ALIASES.get(normalized) or FACTORY_ALIASES.get(normalized.replace(" ", "_"))


def _unique_id(base: str, used_ids: set[str]) -> str:
    candidate = base
    suffix = 2
    while candidate in used_ids:
        candidate = f"{base}-{suffix}"
        suffix += 1
    used_ids.add(candidate)
    return candidate


def _expand_details(details: object, *, model_id: int | None = None) -> dict | None:
    if not isinstance(details, dict):
        return None
    key = "paid_operations" if "paid_operations" in details else "paidOperations" if "paidOperations" in details else None
    rows = details.get(key) if key else None
    if not isinstance(rows, list) or not rows:
        return None

    used_ids = {
        str(row.get("id"))
        for row in rows
        if isinstance(row, dict) and row.get("id") not in (None, "")
    }
    expanded: list[object] = []
    changed = False
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or _factory(row):
            expanded.append(deepcopy(row))
            continue
        changed = True
        source_id = str(row.get("id") or f"legacy-operation-{index + 1}")
        for factory in FACTORIES:
            clone = deepcopy(row)
            clone["id"] = _unique_id(f"{source_id}--{factory}", used_ids)
            clone["sewingFactory"] = factory
            clone["legacySourceId"] = source_id
            clone.pop("sewing_factory", None)
            clone.pop("factory", None)
            expanded.append(clone)

    if not changed:
        return None
    migrated = deepcopy(details)
    migrated["paid_operations"] = expanded
    migrated.pop("paidOperations", None)
    _validate_changed_details(migrated, model_id=model_id)
    return migrated


def _collapse_details(details: object, *, model_id: int | None = None) -> dict | None:
    if not isinstance(details, dict):
        return None
    rows = details.get("paid_operations")
    if not isinstance(rows, list) or not rows:
        return None

    collapsed: list[object] = []
    restored_sources: set[str] = set()
    changed = False
    for row in rows:
        if not isinstance(row, dict):
            collapsed.append(deepcopy(row))
            continue
        source_id = str(row.get("legacySourceId") or row.get("legacy_source_id") or "").strip()
        if not source_id:
            collapsed.append(deepcopy(row))
            continue
        changed = True
        if source_id in restored_sources:
            continue
        restored_sources.add(source_id)
        restored = deepcopy(row)
        restored["id"] = source_id
        restored.pop("sewingFactory", None)
        restored.pop("sewing_factory", None)
        restored.pop("legacySourceId", None)
        restored.pop("legacy_source_id", None)
        collapsed.append(restored)

    if not changed:
        return None
    reverted = deepcopy(details)
    reverted["paid_operations"] = collapsed
    _validate_changed_details(reverted, model_id=model_id)
    return reverted


def _rewrite_models(transform) -> None:
    models = sa.table(
        "models",
        sa.column("id", sa.Integer()),
        sa.column("details_json", sa.JSON()),
    )
    bind = op.get_bind()
    for model_id, details in bind.execute(sa.select(models.c.id, models.c.details_json)):
        updated = transform(details, model_id=int(model_id))
        if updated is not None:
            bind.execute(models.update().where(models.c.id == model_id).values(details_json=updated))


def upgrade() -> None:
    _rewrite_models(_expand_details)


def downgrade() -> None:
    _rewrite_models(_collapse_details)
