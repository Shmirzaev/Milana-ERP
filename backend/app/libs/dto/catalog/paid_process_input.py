from pydantic import BaseModel, Field, field_validator

from app.models.paid_process_catalog_service import SECTIONS


class PaidProcessIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    section: str

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        value = " ".join(value.split())
        if not value:
            raise ValueError("Enter a process name")
        return value

    @field_validator("section")
    @classmethod
    def valid_section(cls, value):
        if value not in SECTIONS:
            raise ValueError("Unknown paid process section")
        return value
