from __future__ import annotations

from copy import deepcopy
from typing import Any

from fastapi import HTTPException

from app.models import User


FACTORY_BY_DEPARTMENT_CODE = {
    "MIL": "milana",
    "BST": "besttex",
    "ECO": "eco_cotton",
}
FACTORY_ALIASES = {
    "MIL": "milana",
    "MILANA": "milana",
    "SML": "milana",
    "BST": "besttex",
    "BESTTEX": "besttex",
    "BTX": "besttex",
    "ECO": "eco_cotton",
    "ECO_COTTON": "eco_cotton",
    "ECOCOTTON": "eco_cotton",
}


def normalize_paid_operation_factory(value: object) -> str | None:
    normalized = str(value or "").strip().upper().replace("-", " ").replace("_", " ")
    normalized = " ".join(normalized.split())
    return FACTORY_ALIASES.get(normalized) or FACTORY_ALIASES.get(normalized.replace(" ", "_"))


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


def filter_operation_rows(rows: list[dict[str, Any]], factory_code: str | None) -> list[dict[str, Any]]:
    if factory_code is None:
        return rows
    factory = normalize_paid_operation_factory(factory_code)
    return _rows_for_factory(rows, factory)
