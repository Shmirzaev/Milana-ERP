from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Any

from fastapi import HTTPException

from app.libs.dto.catalog.model_input import PaidOperationIn
from app.libs.enums.catalog import PaidOperationFactory, normalize_paid_operation_factory_value
from app.libs.types.catalog import ModelCreateDetails
from app.schemas import User


FACTORY_BY_DEPARTMENT_CODE = {
    "MIL": "milana",
    "BST": "besttex",
    "ECO": "eco_cotton",
}
def normalize_paid_operation_factory(value: object) -> str | None:
    normalized = normalize_paid_operation_factory_value(value)
    return normalized.value if normalized else None


def paid_operation_factory(row: object) -> str | None:
    if not isinstance(row, dict):
        return None
    return normalize_paid_operation_factory(
        row.get("sewingFactory", row.get("sewing_factory", row.get("factory", row.get("company"))))
    )


def has_explicit_paid_operation_factory(row: object) -> bool:
    if not isinstance(row, dict):
        return False
    return any(row.get(key) not in (None, "") for key in ("sewingFactory", "sewing_factory", "factory"))


def paid_operation_legacy_source_id(row: object) -> str | None:
    if not isinstance(row, dict):
        return None
    value = row.get("legacySourceId", row.get("legacy_source_id"))
    normalized = str(value or "").strip()
    return normalized or None


def _rows_for_factory(rows: list[dict[str, Any]], factory: str | None) -> list[dict[str, Any]]:
    overridden_legacy_ids = {
        source_id
        for row in rows
        if has_explicit_paid_operation_factory(row) and paid_operation_factory(row) == factory
        for source_id in [paid_operation_legacy_source_id(row)]
        if source_id
    }
    return [
        row
        for row in rows
        if (
            (has_explicit_paid_operation_factory(row) and paid_operation_factory(row) == factory)
            or (
                not has_explicit_paid_operation_factory(row)
                and str(row.get("id") if isinstance(row, dict) else "") not in overridden_legacy_ids
            )
        )
    ]


def paid_operations_from_details(details: object) -> list[dict[str, Any]]:
    if not isinstance(details, dict):
        return []
    rows = details.get("paid_operations", details.get("paidOperations", []))
    return rows if isinstance(rows, list) else []


def sewing_master_factory_scope(user: User) -> str | None:
    role_name = str(user.role.name if user.role else "").strip().lower()
    department_code = str(user.department.code if user.department else "").strip().upper()
    granted = [*(user.role.permissions if user.role and user.role.permissions else []), *(user.extra_permissions or [])]
    if "*" in granted or "sewing" not in role_name:
        return None
    return FACTORY_BY_DEPARTMENT_CODE.get(department_code)


def filter_paid_operations_for_factory(details: object, factory: str | None) -> dict | None:
    if not isinstance(details, dict):
        return deepcopy(details)
    scoped = deepcopy(details)
    if not factory:
        return scoped
    key = "paid_operations" if "paid_operations" in scoped else "paidOperations" if "paidOperations" in scoped else None
    if not key:
        return scoped
    rows = paid_operations_from_details(scoped)
    scoped[key] = _rows_for_factory(rows, factory)
    return scoped


def merge_scoped_paid_operations(existing_details: object, incoming_details: object, factory: str) -> dict:
    existing = deepcopy(existing_details) if isinstance(existing_details, dict) else {}
    incoming = deepcopy(incoming_details) if isinstance(incoming_details, dict) else {}
    incoming_key = "paid_operations" if "paid_operations" in incoming else "paidOperations" if "paidOperations" in incoming else None
    if not incoming_key:
        return incoming

    incoming_rows = paid_operations_from_details(incoming)
    forbidden = [
        row
        for row in incoming_rows
        if has_explicit_paid_operation_factory(row) and paid_operation_factory(row) != factory
    ]
    if forbidden:
        raise HTTPException(403, "A sewing master cannot change another sewing factory's paid operations")

    hidden_rows = [
        deepcopy(row)
        for row in paid_operations_from_details(existing)
        if not has_explicit_paid_operation_factory(row) or paid_operation_factory(row) != factory
    ]
    incoming["paid_operations"] = incoming_rows + hidden_rows
    incoming.pop("paidOperations", None)
    return incoming


def merge_scoped_model_create_operations(
    details: ModelCreateDetails,
    factory: PaidOperationFactory,
) -> ModelCreateDetails:
    """Apply the CREATE factory policy while paid-operation rows stay typed."""

    if details.has_paid_operations:
        rows = details.paid_operations
    elif details.has_paid_operations_alias:
        rows = details.paidOperations
    else:
        return details
    incoming_rows = rows or []
    if any(row.factory_was_explicit and row.resolved_factory_hint != factory for row in incoming_rows):
        raise HTTPException(403, "A sewing master cannot change another sewing factory's paid operations")
    # CREATE has no existing Model JSON to preserve. Match the prior scoped
    # merge's canonical-key result and null-to-empty-list behavior.
    return replace(
        details,
        has_paid_operations=True,
        paid_operations=incoming_rows,
        has_paid_operations_alias=False,
        paidOperations=None,
    )


def merge_scoped_paid_operation_update(
    existing_details: object,
    incoming_details: object,
    rows: list[PaidOperationIn],
    factory: str | None,
) -> dict:
    """Merge typed PATCH rows with opaque stored rows, serializing at JSON output."""
    incoming = deepcopy(incoming_details) if isinstance(incoming_details, dict) else {}
    key = "paid_operations" if "paid_operations" in incoming else "paidOperations" if "paidOperations" in incoming else None
    if key is None:
        return incoming

    if not factory:
        incoming[key] = [row.model_dump(exclude_unset=True, mode="json") for row in rows]
        return incoming

    forbidden = [
        row for row in rows
        if row.factory_was_explicit and row.resolved_factory_hint != factory
    ]
    if forbidden:
        raise HTTPException(403, "A sewing master cannot change another sewing factory's paid operations")
    serialized = [row.model_dump(exclude_unset=True, mode="json") for row in rows]
    hidden_rows = [
        deepcopy(row)
        for row in paid_operations_from_details(existing_details)
        if not has_explicit_paid_operation_factory(row) or paid_operation_factory(row) != factory
    ]
    incoming["paid_operations"] = serialized + hidden_rows
    incoming.pop("paidOperations", None)
    return incoming


def filter_operation_rows(rows: list[dict[str, Any]], factory_code: str | None) -> list[dict[str, Any]]:
    if factory_code is None:
        return rows
    factory = normalize_paid_operation_factory(factory_code)
    return _rows_for_factory(rows, factory)


def replace_factory_paid_operations(details: object, rows: list[PaidOperationIn], factory: str | None) -> dict:
    """Replace one factory's template, retaining other factories' effective rows.

    Materialize old shared rows for the other factories so clearing this factory
    cannot make its deleted legacy operations reappear on the next load.
    """
    result = deepcopy(details) if isinstance(details, dict) else {}
    incoming: list[dict]
    if factory:
        if any(
            row.factory_was_explicit and row.resolved_factory_hint != factory
            for row in rows
        ):
            raise HTTPException(403, "Cannot change another sewing factory's paid operations")
        incoming = [row.model_dump(exclude_unset=True, mode="json") for row in rows]
        for row in incoming:
            row["sewingFactory"] = factory
        existing = paid_operations_from_details(details)
        hidden = [deepcopy(row) for row in existing
                  if has_explicit_paid_operation_factory(row) and paid_operation_factory(row) != factory]
        used_ids = {str(row.get("id", "")) for row in [*incoming, *hidden]}
        for other in FACTORY_BY_DEPARTMENT_CODE.values():
            if other == factory:
                continue
            for row in _rows_for_factory(existing, other):
                if has_explicit_paid_operation_factory(row):
                    continue
                copy = deepcopy(row)
                source_id = str(row.get("id", ""))
                base = f"{source_id}--{other}"
                identity, suffix = base, 2
                while identity in used_ids:
                    identity, suffix = f"{base}-{suffix}", suffix + 1
                used_ids.add(identity)
                copy.update(id=identity, legacySourceId=source_id, sewingFactory=other)
                hidden.append(copy)
        incoming.extend(hidden)
    else:
        incoming = [row.model_dump(exclude_unset=True, mode="json") for row in rows]
    result["paid_operations"] = incoming
    result.pop("paidOperations", None)
    return result
