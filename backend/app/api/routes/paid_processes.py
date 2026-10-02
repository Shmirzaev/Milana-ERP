from uuid import uuid4
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from app.core.deps import DbSession, require_permissions
from app.models import User
from app.models.paid_process import PaidProcess, UslugaPaidProcess
from app.services.audit import log_action
from app.services.factory_scope import selected_factory_code
from app.services.paid_process_catalog import SECTIONS, normalized_key, normalized_name

router = APIRouter(prefix="/paid-processes", tags=["paid-processes"])


class PaidProcessIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    section: str

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        value = " ".join(value.split())
        if not value:
            raise ValueError("Enter a process name")
        return value

    @field_validator("section")
    @classmethod
    def valid_section(cls, value):
        if value not in SECTIONS:
            raise ValueError("Unknown paid process section")
        return value


def output(row):
    return {"id": row.id, "code": row.code, "name": row.name, "section": row.section}


def process_model(current, catalog_scope):
    if catalog_scope == "usluga":
        if selected_factory_code(current) != "ECO":
            raise HTTPException(status_code=403, detail="Usluga processes require Eco Cotton")
        return UslugaPaidProcess
    return PaidProcess


@router.get("")
def list_processes(db: DbSession, search: str = Query("", max_length=255),
                   catalog_scope: Literal["standard", "usluga"] = "standard",
                   current: User = Depends(require_permissions("payroll.manage", "modeling.models", "*"))):
    model = process_model(current, catalog_scope)
    query = db.query(model).filter(model.factory_code == selected_factory_code(current))
    needle = normalized_name(search)
    if needle:
        escaped = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.filter(or_(model.normalized_name.contains(escaped, autoescape=False, escape="\\"),
                                 model.code.ilike(f"%{escaped}%", escape="\\")))
    rows = query.order_by(model.normalized_name, model.section, model.id).limit(51).all()
    return {"items": [output(row) for row in rows[:50]], "has_more": len(rows) > 50}


@router.post("")
def create_process(payload: PaidProcessIn, db: DbSession,
                   catalog_scope: Literal["standard", "usluga"] = "standard",
                   current: User = Depends(require_permissions("payroll.manage", "modeling.models", "*"))):
    model = process_model(current, catalog_scope)
    prefix = "UOP" if catalog_scope == "usluga" else "OP"
    identity = {"factory_code": selected_factory_code(current), "normalized_key": normalized_key(payload.name),
                "section": payload.section}
    existing = db.query(model).filter_by(**identity).first()
    if existing:
        return output(existing)
    row = model(**identity, normalized_name=normalized_name(payload.name), name=payload.name, code=f"{prefix}-{uuid4().hex[:12].upper()}")
    try:
        db.add(row)
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.query(model).filter_by(**identity).first()
        if existing:
            return output(existing)
        raise
    # Database-generated identity gives new catalogue entries a short stable code.
    row.code = f"{prefix}-{row.id:04d}"
    log_action(db, current, "create", model.__name__, row.id, new_value=output(row))
    db.commit()
    return output(row)
