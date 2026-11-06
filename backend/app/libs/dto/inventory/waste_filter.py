"""Typed waste status filter with the existing empty-as-unfiltered adapter."""
from typing import Annotated

from pydantic import BeforeValidator

from app.libs.enums.inventory import WasteStatus


def normalize_optional_waste_status(value: object) -> WasteStatus | None:
    if value is None or value == "":
        return None
    if isinstance(value, WasteStatus):
        return value
    if isinstance(value, str):
        return WasteStatus(value)
    raise ValueError("status must be a string")


WasteStatusFilter = Annotated[WasteStatus | None, BeforeValidator(normalize_optional_waste_status)]
