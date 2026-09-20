from sqlalchemy import func, or_
from sqlalchemy.sql.elements import ColumnElement


def accepted_attendance_result(result_column) -> ColumnElement[bool]:
    """Match legacy missing results and explicit successful passages."""
    return or_(
        result_column.is_(None),
        func.lower(func.trim(result_column)) == "success",
    )
