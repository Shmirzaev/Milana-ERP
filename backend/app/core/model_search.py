from sqlalchemy import func


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


def normalized_model_code_column(column):
    """Return a SQLite/PostgreSQL-compatible normalized model-code expression."""
    normalized = func.lower(column)
    for cyrillic_upper, cyrillic_lower, latin in _MODEL_CODE_CONFUSABLES:
        # SQLite lower() does not fold Cyrillic, while PostgreSQL does.
        normalized = func.replace(normalized, cyrillic_upper, latin)
        normalized = func.replace(normalized, cyrillic_lower, latin)
    return func.replace(normalized, "-", "")


def normalized_model_code_pattern(value: object) -> str:
    return f"%{normalized_model_code_key(value)}%"


def model_code_contains(value: object, query: object) -> bool:
    needle = normalized_model_code_key(query)
    return bool(needle) and needle in normalized_model_code_key(value)
