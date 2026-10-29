import math


def swap_nonfinite_amount(value: object) -> object:
    """Replace a nonfinite number with a serializable stand-in before validation.

    FastAPI echoes the offending input into the 422 body, and `inf`/`nan` cannot be
    JSON-encoded, so rejecting such a value directly makes the error response itself
    fail to serialize and the caller sees a 500 instead of a validation error.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool) and not math.isfinite(value):
        return "non-finite number"
    return value
