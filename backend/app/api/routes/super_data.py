from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.sql import sqltypes
from sqlalchemy.sql.schema import Column, Table
from sqlalchemy.orm import Session

from app.core.deps import DbSession, require_super_admin
from app.db.base import Base
from app.models import User
from app.services.audit import log_action

router = APIRouter(prefix="/admin/super-data", tags=["super-admin-data"])


class SuperDataColumnOut(BaseModel):
    name: str
    type: str
    nullable: bool
    primary_key: bool
    foreign_key: str | None = None
    editable: bool


class SuperDataTableOut(BaseModel):
    name: str
    label: str
    row_count: int
    columns: list[SuperDataColumnOut]


class SuperDataRowsOut(BaseModel):
    table: str
    label: str
    columns: list[SuperDataColumnOut]
    rows: list[dict[str, Any]]
    total: int
    page: int
    page_size: int


class SuperDataUpdateIn(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


def _table_name_label(name: str) -> str:
    return name.replace("_", " ").title()


def _table_for(table_name: str) -> Table:
    table = Base.metadata.tables.get(table_name)
    if table is None:
        raise HTTPException(404, "Table not found")
    return table


def _pk_column(table: Table) -> Column:
    columns = list(table.primary_key.columns)
    if len(columns) != 1:
        raise HTTPException(400, "This table does not have a single-column primary key")
    return columns[0]


def _is_binary(column: Column) -> bool:
    return isinstance(column.type, sqltypes.LargeBinary)


def _column_out(column: Column) -> SuperDataColumnOut:
    foreign_key = None
    if column.foreign_keys:
        fk = next(iter(column.foreign_keys))
        foreign_key = f"{fk.column.table.name}.{fk.column.name}"
    return SuperDataColumnOut(
        name=column.name,
        type=str(column.type),
        nullable=bool(column.nullable),
        primary_key=bool(column.primary_key),
        foreign_key=foreign_key,
        editable=not column.primary_key and not _is_binary(column),
    )


def _table_columns(table: Table) -> list[SuperDataColumnOut]:
    return [_column_out(column) for column in table.columns]


def _serialize_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"__binary": True, "size": len(bytes(value))}
    if isinstance(value, dict):
        return {str(k): _serialize_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_serialize_value(v) for v in value]
    return str(value)


def _serialize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _serialize_value(value) for key, value in row.items()}


def _row_for(db: Session, table: Table, row_id: int) -> dict[str, Any]:
    pk = _pk_column(table)
    row = db.execute(select(table).where(pk == row_id)).mappings().first()
    if row is None:
        raise HTTPException(404, "Row not found")
    return dict(row)


def _parse_datetime(value: str) -> datetime:
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    return datetime.fromisoformat(raw)


def _coerce_value(column: Column, value: Any) -> Any:
    if value == "" and not isinstance(column.type, (sqltypes.String, sqltypes.Text, sqltypes.Unicode, sqltypes.UnicodeText)):
        value = None
    if value is None:
        if not column.nullable:
            raise HTTPException(400, f"{column.name} cannot be blank")
        return None

    try:
        if isinstance(column.type, sqltypes.Boolean):
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in {"true", "1", "yes", "y", "on"}:
                    return True
                if lowered in {"false", "0", "no", "n", "off"}:
                    return False
            raise ValueError("expected boolean")
        if isinstance(column.type, sqltypes.Integer):
            return int(value)
        if isinstance(column.type, sqltypes.Numeric):
            return Decimal(str(value))
        if isinstance(column.type, sqltypes.Float):
            return float(value)
        if isinstance(column.type, sqltypes.DateTime):
            if isinstance(value, datetime):
                return value
            if isinstance(value, str):
                return _parse_datetime(value)
            raise ValueError("expected ISO datetime")
        if isinstance(column.type, sqltypes.Date):
            if isinstance(value, date) and not isinstance(value, datetime):
                return value
            if isinstance(value, str):
                return date.fromisoformat(value.strip())
            raise ValueError("expected ISO date")
        if isinstance(column.type, sqltypes.Time):
            if isinstance(value, time):
                return value
            if isinstance(value, str):
                return time.fromisoformat(value.strip())
            raise ValueError("expected ISO time")
        if isinstance(column.type, sqltypes.JSON):
            if isinstance(value, str):
                return json.loads(value)
            return value
        if _is_binary(column):
            raise ValueError("binary columns are read-only in this console")
        return str(value) if isinstance(column.type, (sqltypes.String, sqltypes.Text, sqltypes.Unicode, sqltypes.UnicodeText)) else value
    except (ValueError, TypeError, InvalidOperation, json.JSONDecodeError) as exc:
        raise HTTPException(400, f"Invalid value for {column.name}: {exc}") from exc


def _search_condition(table: Table, query: str):
    search = query.strip()
    if not search:
        return None
    like = f"%{search}%"
    conditions = []
    for column in table.columns:
        if _is_binary(column):
            continue
        conditions.append(column.cast(sqltypes.String()).ilike(like))
    return or_(*conditions) if conditions else None


def _commit_or_409(db: Session, message: str) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, f"{message}: database relationship or unique constraint blocked the change") from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(400, f"{message}: {exc}") from exc


def _rollback_and_raise(db: Session, exc: SQLAlchemyError, message: str) -> None:
    db.rollback()
    if isinstance(exc, IntegrityError):
        raise HTTPException(409, f"{message}: database relationship or unique constraint blocked the change") from exc
    raise HTTPException(400, f"{message}: {exc}") from exc


@router.get("/tables", response_model=list[SuperDataTableOut])
def list_super_data_tables(
    db: DbSession,
    _: User = Depends(require_super_admin),
):
    out: list[SuperDataTableOut] = []
    for table in sorted(Base.metadata.sorted_tables, key=lambda item: item.name):
        row_count = db.execute(select(func.count()).select_from(table)).scalar_one()
        out.append(
            SuperDataTableOut(
                name=table.name,
                label=_table_name_label(table.name),
                row_count=int(row_count or 0),
                columns=_table_columns(table),
            )
        )
    return out


@router.get("/tables/{table_name}", response_model=SuperDataRowsOut)
def list_super_data_rows(
    table_name: str,
    db: DbSession,
    _: User = Depends(require_super_admin),
    page: int = 1,
    page_size: int = 50,
    q: str = "",
):
    table = _table_for(table_name)
    pk = _pk_column(table)
    safe_page = max(1, page)
    safe_size = max(1, min(page_size, 200))
    condition = _search_condition(table, q)

    count_stmt = select(func.count()).select_from(table)
    rows_stmt = select(table).order_by(pk.desc()).offset((safe_page - 1) * safe_size).limit(safe_size)
    if condition is not None:
        count_stmt = count_stmt.where(condition)
        rows_stmt = rows_stmt.where(condition)

    total = db.execute(count_stmt).scalar_one()
    rows = [_serialize_row(dict(row)) for row in db.execute(rows_stmt).mappings().all()]
    return SuperDataRowsOut(
        table=table.name,
        label=_table_name_label(table.name),
        columns=_table_columns(table),
        rows=rows,
        total=int(total or 0),
        page=safe_page,
        page_size=safe_size,
    )


@router.patch("/tables/{table_name}/rows/{row_id}")
def update_super_data_row(
    table_name: str,
    row_id: int,
    payload: SuperDataUpdateIn,
    db: DbSession,
    current: User = Depends(require_super_admin),
):
    table = _table_for(table_name)
    pk = _pk_column(table)
    before = _row_for(db, table, row_id)
    values: dict[str, Any] = {}
    for key, raw_value in payload.values.items():
        column = table.columns.get(key)
        if column is None:
            raise HTTPException(400, f"Unknown column: {key}")
        if column.primary_key:
            raise HTTPException(400, f"{key} is a primary key and cannot be edited here")
        if _is_binary(column):
            raise HTTPException(400, f"{key} is binary data and cannot be edited here")
        values[key] = _coerce_value(column, raw_value)

    if values:
        try:
            db.execute(update(table).where(pk == row_id).values(**values))
            after = _row_for(db, table, row_id)
            log_action(
                db,
                current,
                "update",
                f"SuperData:{table.name}",
                row_id,
                old_value=_serialize_row(before),
                new_value=_serialize_row(after),
            )
        except SQLAlchemyError as exc:
            _rollback_and_raise(db, exc, "Could not update row")
        _commit_or_409(db, "Could not update row")
    return _serialize_row(_row_for(db, table, row_id))


@router.delete("/tables/{table_name}/rows/{row_id}", status_code=204)
def delete_super_data_row(
    table_name: str,
    row_id: int,
    db: DbSession,
    current: User = Depends(require_super_admin),
):
    table = _table_for(table_name)
    pk = _pk_column(table)
    before = _row_for(db, table, row_id)
    try:
        db.execute(delete(table).where(pk == row_id))
        log_action(
            db,
            current,
            "delete",
            f"SuperData:{table.name}",
            row_id,
            old_value=_serialize_row(before),
        )
    except SQLAlchemyError as exc:
        _rollback_and_raise(db, exc, "Could not delete row")
    _commit_or_409(db, "Could not delete row")
