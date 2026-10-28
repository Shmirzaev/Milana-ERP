"""Signature-based bootstrap guards for fresh-schema DDL.

Tracker DB06: a fresh schema can end up carrying *equivalent duplicate* unique
indexes and foreign keys, because migrations historically guarded new indexes by
**name** only. ``0025_material_reservations`` is the concrete case: its
``upgrade()`` creates ``UniqueConstraint("reservation_no",
name="uq_material_reservations_reservation_no")`` (line 57) and then asks
``_create_index_if_missing`` for a *separate* unique index over the same column
(line 61). A name-only guard cannot see that the table it just created already
enforces uniqueness, so a freshly migrated database keeps both objects.

This module provides the signature-based guard the row asks for:

* :func:`index_signature` hashes table + ordered columns + uniqueness + partial
  predicate into one comparable value, so "is this index already covered?" is
  answered by *meaning* rather than by *name*.
* :func:`equivalent_unique_object` finds an existing unique index **or** unique
  constraint with the same signature.
* :func:`create_index_if_missing_by_signature` is the guarded creation helper
  for fresh-bootstrap DDL. With ``create=None`` it is a pure read-only planner
  that reports what it *would* do and touches nothing.
* :func:`find_equivalent_duplicates` is a read-only catalog audit used to gather
  the exact-impact evidence tracker decision D2 requires before any deployed
  cleanup or candidate index migration is approved.

Applied migrations are immutable history and production has already run them, so
this module deliberately does **not** rewrite any existing revision. It is the
forward mechanism: new fresh-bootstrap DDL calls the guard, and the audit
reports what history left behind.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Callable, Iterable, Sequence

import sqlalchemy as sa

__all__ = [
    "DuplicateSignature",
    "IndexPlan",
    "create_index_if_missing_by_signature",
    "equivalent_unique_object",
    "find_equivalent_duplicates",
    "index_signature",
    "object_signatures",
]


def _canonical_columns(columns: Sequence[str] | str) -> list[str]:
    if isinstance(columns, str):
        columns = [columns]
    return [str(column).strip() for column in columns]


def _digest(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def index_signature(
    table: str,
    columns: Sequence[str] | str,
    *,
    unique: bool = False,
    where: str | None = None,
) -> str:
    """Return the comparable signature of an index over ``columns``.

    Two indexes share a signature when they enforce the same thing: same table,
    same ordered column list, same uniqueness, same partial-index predicate. A
    unique *constraint* and a unique *index* over the same single column share
    one signature, which is exactly the DB06 duplicate.
    """
    return _digest({
        "kind": "index",
        "table": str(table),
        "columns": _canonical_columns(columns),
        "unique": bool(unique),
        "where": None if where is None else str(where).strip(),
    })


def foreign_key_signature(
    table: str,
    columns: Sequence[str] | str,
    referred_table: str,
    referred_columns: Sequence[str] | str,
) -> str:
    """Return the comparable signature of a foreign key."""
    return _digest({
        "kind": "foreign_key",
        "table": str(table),
        "columns": _canonical_columns(columns),
        "referred_table": str(referred_table),
        "referred_columns": _canonical_columns(referred_columns),
    })


def object_signatures(inspector: sa.Inspector, table: str) -> dict[str, list[dict]]:
    """Group every catalog object on ``table`` by its signature.

    Unique constraints and unique indexes share one signature space, so a
    constraint and an index over the same column collide here - which is exactly
    the DB06 duplicate. A PostgreSQL unique constraint is backed by an index of
    the same name, and the inspector reports that index again with
    ``duplicates_constraint`` set; it is skipped so the constraint is counted
    once instead of appearing as a phantom duplicate of itself.
    """
    objects: list[dict] = []

    for constraint in inspector.get_unique_constraints(table):
        objects.append({
            "name": constraint.get("name"),
            "type": "unique_constraint",
            "table": table,
            "columns": _canonical_columns(constraint.get("column_names") or []),
            "where": None,
        })

    for index in inspector.get_indexes(table):
        if index.get("duplicates_constraint") or not index.get("unique"):
            continue
        options = index.get("dialect_options") or {}
        objects.append({
            "name": index.get("name"),
            "type": "index",
            "table": table,
            "columns": _canonical_columns(index.get("column_names") or []),
            "where": options.get("postgresql_where"),
        })

    for key in inspector.get_foreign_keys(table):
        objects.append({
            "name": key.get("name"),
            "type": "foreign_key",
            "table": table,
            "columns": _canonical_columns(key.get("constrained_columns") or []),
            "referred_table": key.get("referred_table"),
            "referred_columns": _canonical_columns(key.get("referred_columns") or []),
        })

    grouped: dict[str, list[dict]] = {}
    for obj in objects:
        if obj["type"] == "foreign_key":
            signature = foreign_key_signature(
                table, obj["columns"], obj["referred_table"], obj["referred_columns"]
            )
        else:
            signature = index_signature(
                table, obj["columns"], unique=True, where=obj["where"]
            )
        grouped.setdefault(signature, []).append(obj)

    # A unique constraint is the authoritative "covering" object, so order each
    # group with constraints first.
    for group in grouped.values():
        group.sort(key=lambda item: (item["type"] != "unique_constraint", item["name"] or ""))
    return grouped


def equivalent_unique_object(
    inspector: sa.Inspector,
    table: str,
    columns: Sequence[str] | str,
    *,
    where: str | None = None,
) -> dict | None:
    """Return an existing unique object already covering ``columns``, if any."""
    wanted = index_signature(table, columns, unique=True, where=where)
    group = object_signatures(inspector, table).get(wanted)
    return group[0] if group else None


@dataclass(frozen=True)
class IndexPlan:
    """What :func:`create_index_if_missing_by_signature` decided, read-only."""

    name: str
    table: str
    columns: tuple[str, ...]
    unique: bool
    action: str
    reason: str
    covered_by: str | None = None

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["columns"] = list(self.columns)
        return payload


def create_index_if_missing_by_signature(
    inspector: sa.Inspector,
    name: str,
    table: str,
    columns: Sequence[str] | str,
    *,
    unique: bool = False,
    where: str | None = None,
    create: Callable[..., None] | None = None,
) -> IndexPlan:
    """Create ``name`` only when no equivalent index or constraint exists.

    This is the signature-based replacement for a name-only
    ``_create_index_if_missing``. Three outcomes, in order:

    1. ``skipped_existing_name`` - an object with this name already exists.
    2. ``skipped_equivalent`` - a *differently named* object with the same
       signature already enforces this, so a second one is redundant. This is
       the DB06 fresh-bootstrap case: the table's own unique constraint already
       covers ``(reservation_no,)`` uniquely.
    3. ``created`` - nothing equivalent exists, so create it.

    ``create=None`` keeps the helper strictly read-only: it returns the decision
    without touching the database. Pass ``create=op.create_index`` to apply it.
    """
    columns = _canonical_columns(columns)
    grouped = object_signatures(inspector, table)

    for group in grouped.values():
        for existing in group:
            if existing["name"] == name:
                return IndexPlan(
                    name, table, tuple(columns), unique, "skipped_existing_name",
                    f"{name} already exists on {table}", covered_by=name,
                )

    wanted = index_signature(table, columns, unique=unique, where=where)
    covering = grouped.get(wanted)
    if unique and covering:
        kept = covering[0]
        return IndexPlan(
            name, table, tuple(columns), unique, "skipped_equivalent",
            f"{table}{tuple(columns)} is already uniquely enforced by "
            f"{kept['type']} {kept['name']}; a second unique index would "
            f"be redundant",
            covered_by=kept["name"],
        )

    if create is not None:
        create(name, table, columns, unique=unique, **(
            {"postgresql_where": where} if where is not None else {}
        ))
        return IndexPlan(name, table, tuple(columns), unique, "created",
                         f"no equivalent object existed; created {name}")

    return IndexPlan(name, table, tuple(columns), unique, "would_create",
                     f"no equivalent object existed; {name} is missing")


@dataclass(frozen=True)
class DuplicateSignature:
    """One redundant object sharing a signature with a kept object."""

    table: str
    signature: str
    columns: tuple[str, ...]
    kept: str
    kept_type: str
    redundant: str
    redundant_type: str

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["columns"] = list(self.columns)
        return payload


def find_equivalent_duplicates(
    inspector: sa.Inspector,
    tables: Iterable[str] | None = None,
) -> list[DuplicateSignature]:
    """Read-only audit: report equivalent duplicate unique objects per table.

    For each signature shared by more than one object, the first is reported as
    kept and the rest as redundant. This produces the exact-impact evidence
    decision D2 must approve before any deployed cleanup drops a redundant
    index; the audit itself never drops anything.
    """
    targets = list(tables) if tables is not None else inspector.get_table_names()
    duplicates: list[DuplicateSignature] = []
    for table in sorted(targets):
        for signature, group in sorted(object_signatures(inspector, table).items()):
            if len(group) < 2:
                continue
            kept, *redundant = group
            for extra in redundant:
                duplicates.append(DuplicateSignature(
                    table=table,
                    signature=signature,
                    columns=tuple(kept["columns"]),
                    kept=kept["name"],
                    kept_type=kept["type"],
                    redundant=extra["name"],
                    redundant_type=extra["type"],
                ))
    return duplicates
