"""Typed waste status filter with the existing empty-as-unfiltered adapter."""
from typing import Annotated

from pydantic import BeforeValidator

from app.libs.enums.inventory import WasteStatus


def normalize_optional_waste_status(value: object) -> object:
    return None if value == "" else value


WasteStatusFilter = Annotated[WasteStatus | None, BeforeValidator(normalize_optional_waste_status)]
