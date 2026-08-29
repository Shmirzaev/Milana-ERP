from __future__ import annotations

import math
from collections.abc import Iterable

from fastapi import HTTPException


MATERIAL_CATEGORIES = {"fabric", "semi_finished"}
MAX_MATERIAL_ROLLS = 1000
WEIGHT_TOLERANCE_KG = 0.01


def normalize_material_roll_weights(
    *,
    item_category: str,
    unit: str,
    quantity: float,
    roll_weights_kg: Iterable[float] | None,
    piece_count: int | None = None,
    require_weights: bool = False,
) -> tuple[list[float], int | None]:
    """Validate optional per-roll weights and return normalized values.

    Existing API clients may omit roll weights. When weights are supplied, they
    become the source of truth for roll count and must equal the batch quantity.
    """
    raw_weights = list(roll_weights_kg or [])
    if not raw_weights:
        if require_weights:
            raise HTTPException(400, "At least one roll weight is required")
        return [], piece_count

    if str(item_category or "").strip().lower() not in MATERIAL_CATEGORIES:
        raise HTTPException(400, "Roll weights are only supported for materials")
    if str(unit or "").strip().lower() not in {"kg", "kilogram", "kilograms"}:
        raise HTTPException(400, "Material roll weights require kilogram units")
    if len(raw_weights) > MAX_MATERIAL_ROLLS:
        raise HTTPException(400, f"A batch cannot contain more than {MAX_MATERIAL_ROLLS} rolls")

    normalized: list[float] = []
    for index, value in enumerate(raw_weights, start=1):
        try:
            weight = float(value)
        except (TypeError, ValueError):
            raise HTTPException(400, f"Roll {index} weight must be a number") from None
        if not math.isfinite(weight) or weight <= 0:
            raise HTTPException(400, f"Roll {index} weight must be greater than zero")
        normalized.append(round(weight, 4))

    if piece_count not in (None, 0, len(normalized)):
        raise HTTPException(409, "Roll count does not match the number of roll weights")

    entered_total = round(sum(normalized), 4)
    expected_total = round(float(quantity), 4)
    if abs(entered_total - expected_total) > WEIGHT_TOLERANCE_KG:
        raise HTTPException(
            409,
            f"Roll weights total {entered_total:g} kg does not match batch quantity {expected_total:g} kg",
        )
    return normalized, len(normalized)
