"""Read-only matching of compact order labels against preserved legacy references."""
import re

from sqlalchemy import or_


def order_reference_contains(column, pattern: str):
    normal_match = column.ilike(pattern)
    compact = re.fullmatch(r"(SO|PO|USL|PR|PUR)-([0-9]{4})", pattern.strip("%"), re.IGNORECASE)
    if not compact:
        return normal_match
    prefix, digits = compact.groups()
    # Old generators used exactly four year digits and six sequence digits.
    # Return every matching historical year; the original reference and row ID
    # remain in the response so selection never rewrites an order identity.
    legacy_pattern = f"{prefix}-____-{int(digits):06d}"
    return or_(normal_match, column.ilike(legacy_pattern))
