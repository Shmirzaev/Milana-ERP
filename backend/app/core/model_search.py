import sqlite3

from sqlalchemy import event, func
from sqlalchemy.engine import Engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement
from sqlalchemy.types import String


_MODEL_CODE_CONFUSABLES = (
    ("А", "а", "a"),
    ("В", "в", "b"),
    ("Е", "е", "e"),
    ("К", "к", "k"),
    ("М", "м", "m"),
    ("Н", "н", "h"),
    ("О", "о", "o"),
    ("Р", "р", "p"),
    ("С", "с", "c"),
    ("Т", "т", "t"),
    ("Х", "х", "x"),
    ("У", "у", "y"),
)
_MODEL_CODE_CONFUSABLE_TRANSLATION = str.maketrans(
    {
        character: latin
        for cyrillic_upper, cyrillic_lower, latin in _MODEL_CODE_CONFUSABLES
        for character in (cyrillic_upper, cyrillic_lower)
    }
)


def normalized_model_code_key(value: object) -> str:
    """Fold case, whitespace, dashes, and Latin/Cyrillic look-alikes."""
    return (
        " ".join(str(value or "").strip().casefold().split())
        .translate(_MODEL_CODE_CONFUSABLE_TRANSLATION)
        .replace("-", "")
    )


@event.listens_for(Engine, "connect")
def _register_sqlite_model_code_normalizer(dbapi_connection, _connection_record) -> None:
    if isinstance(dbapi_connection, sqlite3.Connection):
        dbapi_connection.create_function(
            "model_code_normalize",
            1,
            normalized_model_code_key,
            deterministic=True,
        )


class _NormalizedModelCode(FunctionElement):
    type = String()
    inherit_cache = True


def _nested_normalized_expression(column):
    normalized = func.lower(column)
    for cyrillic_upper, cyrillic_lower, latin in _MODEL_CODE_CONFUSABLES:
        normalized = func.replace(normalized, cyrillic_upper, latin)
        normalized = func.replace(normalized, cyrillic_lower, latin)
    return func.replace(normalized, "-", "")


@compiles(_NormalizedModelCode, "sqlite")
def _compile_normalized_model_code_sqlite(element, compiler, **kwargs) -> str:
    column = next(iter(element.clauses))
    return f"model_code_normalize({compiler.process(column, **kwargs)})"


@compiles(_NormalizedModelCode)
def _compile_normalized_model_code_default(element, compiler, **kwargs) -> str:
    column = next(iter(element.clauses))
    return compiler.process(_nested_normalized_expression(column), **kwargs)


def normalized_model_code_column(column):
    """Return a SQLite/PostgreSQL-compatible normalized model-code expression."""
    return _NormalizedModelCode(column)


def normalized_model_code_pattern(value: object) -> str:
    return f"%{normalized_model_code_key(value)}%"


def model_code_contains(value: object, query: object) -> bool:
    needle = normalized_model_code_key(query)
    return bool(needle) and needle in normalized_model_code_key(value)
