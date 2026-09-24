from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, literal, or_, select, union_all
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.sql import sqltypes
from sqlalchemy.sql.schema import Column, Table
from sqlalchemy.orm import Session

from app.core.deps import DbSession, require_super_admin
from app.db.base import Base
from app.models import User
from app.services.audit import log_action
from app.services.department_repairs import repair_department_name

router = APIRouter(prefix="/admin/super-data", tags=["super-admin-data"])


# Mutations in the data console are deliberately narrower than its read-only
# inspection surface.  Expanding this map requires a separate review of the
# target's business rules, factory scope, and audit semantics.
_EDITABLE_COLUMNS: dict[str, frozenset[str]] = {
    "departments": frozenset({"name"}),
}


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


class SuperDataTableDirectoryOut(BaseModel):
    name: str
    label: str
    columns: list[SuperDataColumnOut]


class SuperDataTablePageOut(BaseModel):
    rows: list[SuperDataTableOut]
    total: int
    page: int
    page_size: int
    has_more: bool


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


class DepartmentNameRepairIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str


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
        editable=column.name in _EDITABLE_COLUMNS.get(column.table.name, frozenset()),
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


def _table_row_counts(db: Session, tables: list[Table]) -> dict[str, int]:
    """Read all mapped-table row counts with one round trip.

    Each branch only selects a literal table name and its count, so this is
    portable across the supported PostgreSQL and SQLite test engines while
    avoiding one database round trip per table.
    """
    if not tables:
        return {}
    count_queries = [
        select(literal(table.name).label("table_name"), func.count().label("row_count")).select_from(table)
        for table in tables
    ]
    rows = db.execute(union_all(*count_queries)).all()
    return {str(table_name): int(row_count or 0) for table_name, row_count in rows}


def _table_directory(
    db: Session,
    tables: list[Table],
    *,
    page: int | None = None,
    page_size: int | None = None,
) -> list[SuperDataTableOut] | SuperDataTablePageOut:
    ordered_tables = sorted(tables, key=lambda item: item.name)
    paginated = page is not None or page_size is not None
    effective_page = page or 1
    effective_page_size = page_size or 50
    if paginated:
        start = (effective_page - 1) * effective_page_size
        selected_tables = ordered_tables[start:start + effective_page_size]
    else:
        selected_tables = ordered_tables
    row_counts = _table_row_counts(db, selected_tables)
    rows = [
        SuperDataTableOut(
            name=table.name,
            label=_table_name_label(table.name),
            row_count=row_counts.get(table.name, 0),
            columns=_table_columns(table),
        )
        for table in selected_tables
    ]
    if not paginated:
        return rows
    total = len(ordered_tables)
    return SuperDataTablePageOut(
        rows=rows,
        total=total,
        page=effective_page,
        page_size=effective_page_size,
        has_more=effective_page * effective_page_size < total,
    )


def _table_metadata_directory(tables: list[Table]) -> list[SuperDataTableDirectoryOut]:
    return [
        SuperDataTableDirectoryOut(
            name=table.name,
            label=_table_name_label(table.name),
            columns=_table_columns(table),
        )
        for table in sorted(tables, key=lambda item: item.name)
    ]


@router.get("/tables", response_model=list[SuperDataTableOut] | SuperDataTablePageOut)
def list_super_data_tables(
    db: DbSession,
    _: User = Depends(require_super_admin),
    page: Annotated[int | None, Query(ge=1)] = None,
    page_size: Annotated[int | None, Query(ge=1, le=200)] = None,
):
    return _table_directory(
        db,
        list(Base.metadata.sorted_tables),
        page=page,
        page_size=page_size,
    )


@router.get("/tables/directory", response_model=list[SuperDataTableDirectoryOut])
def list_super_data_table_directory(
    _: User = Depends(require_super_admin),
):
    return _table_metadata_directory(list(Base.metadata.sorted_tables))


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
    row_columns = [
        func.length(column).label(column.name) if _is_binary(column) else column
        for column in table.columns
    ]
    rows_stmt = select(*row_columns).order_by(pk.desc()).offset((safe_page - 1) * safe_size).limit(safe_size)
    if condition is not None:
        count_stmt = count_stmt.where(condition)
        rows_stmt = rows_stmt.where(condition)

    total = db.execute(count_stmt).scalar_one()
    rows = []
    for row in db.execute(rows_stmt).mappings().all():
        serialized = {}
        for column in table.columns:
            value = row[column.name]
            if _is_binary(column):
                serialized[column.name] = None if value is None else {"__binary": True, "size": int(value)}
            else:
                serialized[column.name] = _serialize_value(value)
        rows.append(serialized)
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
    allowed_columns = _EDITABLE_COLUMNS.get(table.name)
    if allowed_columns is None:
        raise HTTPException(403, "Data Console editing is not allowed for this table")

    disallowed = sorted(set(payload.values) - allowed_columns)
    if disallowed:
        raise HTTPException(403, f"Data Console editing is not allowed for: {', '.join(disallowed)}")
    if not payload.values:
        raise HTTPException(422, "At least one approved field is required")
    if table.name != "departments" or set(payload.values) != {"name"}:
        raise HTTPException(403, "Use an approved named repair operation")
    return _repair_department_name(row_id, payload.values["name"], db, current)


@router.patch("/repairs/departments/{row_id}/rename")
def rename_department_repair(
    row_id: int,
    payload: DepartmentNameRepairIn,
    db: DbSession,
    current: User = Depends(require_super_admin),
):
    """Named, validated repair endpoint used by the Data Console."""
    return _repair_department_name(row_id, payload.name, db, current)


def _repair_department_name(row_id: int, raw_name: object, db: Session, current: User) -> dict[str, Any]:
    try:
        department, previous_name = repair_department_name(db, row_id, raw_name)
        db.flush()
        log_action(
            db,
            current,
            "update",
            "SuperData:departments",
            row_id,
            old_value={"id": row_id, "name": previous_name, "code": department.code},
            new_value={"id": row_id, "name": department.name, "code": department.code},
        )
    except SQLAlchemyError as exc:
        _rollback_and_raise(db, exc, "Could not update department name")
    _commit_or_409(db, "Could not update department name")
    return _serialize_row(_row_for(db, _table_for("departments"), row_id))


@router.delete("/tables/{table_name}/rows/{row_id}", status_code=204)
def delete_super_data_row(
    table_name: str,
    row_id: int,
    db: DbSession,
    current: User = Depends(require_super_admin),
):
    _table_for(table_name)
    raise HTTPException(
        409,
        "Data Console delete is unavailable because no approved soft-delete field is configured",
    )
