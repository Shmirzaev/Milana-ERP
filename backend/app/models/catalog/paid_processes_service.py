"""Paid-operation definitions for the standard and usluga catalogues.

Contract for the paid-process catalogue operations:
* input: a search term, a catalogue scope and a validated `PaidProcessIn`
* output: the catalogue rows for the acting factory
* refusals: 403 "Usluga processes require Eco Cotton" when the actor is not in
  the Eco Cotton factory
* records: `paid_processes` and `usluga_paid_processes` rows plus the audit row
* transaction owner: `create_process`; `list_processes` only reads
"""

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.libs.dto.catalog.paid_process_input import PaidProcessIn
from app.libs.dto.catalog.paid_process_output import PaidProcessList, PaidProcessOut
from app.libs.enums.catalog import CatalogScope
from app.models.audit_service import log_action
from app.models.factory_scope_service import selected_factory_code
from app.models.paid_process_catalog_service import normalized_key, normalized_name
from app.schemas import User
from app.schemas.catalog.paid_process import PaidProcess, UslugaPaidProcess
from app.schemas.catalog.paid_process_persistence import (
    assign_paid_process_code,
    build_paid_process,
    insert_paid_process,
)

PaidProcessModel = type[PaidProcess] | type[UslugaPaidProcess]
PaidProcessRow = PaidProcess | UslugaPaidProcess


def _paid_process_payload(row: PaidProcessRow) -> PaidProcessOut:
    return PaidProcessOut(id=row.id, code=row.code, name=row.name, section=row.section)


def _paid_process_model(current: User, catalog_scope: CatalogScope) -> PaidProcessModel:
    if catalog_scope == CatalogScope.USLUGA:
        if selected_factory_code(current) != "ECO":
            raise HTTPException(status_code=403, detail="Usluga processes require Eco Cotton")
        return UslugaPaidProcess
    return PaidProcess


def list_processes(
    current: User,
    db: Session,
    search: str = "",
    catalog_scope: CatalogScope = CatalogScope.STANDARD,
) -> PaidProcessList:
    model = _paid_process_model(current, catalog_scope)
    query = db.query(model).filter(model.factory_code == selected_factory_code(current))
    needle = normalized_name(search)
    if needle:
        escaped = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.filter(or_(model.normalized_name.contains(escaped, autoescape=False, escape="\\"),
                                 model.code.ilike(f"%{escaped}%", escape="\\")))
    rows = query.order_by(model.normalized_name, model.section, model.id).limit(51).all()
    return PaidProcessList(items=[_paid_process_payload(row) for row in rows[:50]], has_more=len(rows) > 50)


def create_process(
    current: User,
    db: Session,
    payload: PaidProcessIn,
    catalog_scope: CatalogScope = CatalogScope.STANDARD,
) -> PaidProcessOut:
    model = _paid_process_model(current, catalog_scope)
    prefix = "UOP" if catalog_scope == CatalogScope.USLUGA else "OP"
    # The identity filter is a database query boundary, so it needs the raw value.
    identity = {"factory_code": selected_factory_code(current), "normalized_key": normalized_key(payload.name),
                "section": payload.section.value}
    existing = db.query(model).filter_by(**identity).first()
    if existing:
        return _paid_process_payload(existing)
    row = build_paid_process(
        model,
        factory_code=identity["factory_code"],
        normalized_key=identity["normalized_key"],
        section=payload.section,
        normalized_name=normalized_name(payload.name),
        name=payload.name,
        prefix=prefix,
    )
    try:
        insert_paid_process(db, row)
    except IntegrityError:
        db.rollback()
        existing = db.query(model).filter_by(**identity).first()
        if existing:
            return _paid_process_payload(existing)
        raise
    # Database-generated identity gives new catalogue entries a short stable code.
    assign_paid_process_code(row, prefix)
    created = _paid_process_payload(row)
    log_action(db, current, "create", model.__name__, row.id, new_value=created.model_dump(mode="json"))
    db.commit()
    return created
