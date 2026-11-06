from pydantic import BaseModel, Field, field_validator

from app.libs.enums.catalog import PAID_PROCESS_SECTION_VALUES, PaidProcessSection


class PaidProcessIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    section: PaidProcessSection

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        value = " ".join(value.split())
        if not value:
            raise ValueError("Enter a process name")
        return value

    @field_validator("section", mode="before")
    @classmethod
    def valid_section(cls, value):
        # The raw request value is checked before the enum parses it, so the
        # refusal keeps its own message instead of the enum's member list.
        if not isinstance(value, str) or value not in PAID_PROCESS_SECTION_VALUES:
            raise ValueError("Unknown paid process section")
        return value
