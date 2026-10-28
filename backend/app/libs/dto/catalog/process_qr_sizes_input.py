from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, field_validator


class ProcessQrSizesIn(BaseModel):
    sizes: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]] = Field(
        min_length=1, max_length=40,
    )

    @field_validator("sizes")
    @classmethod
    def unique_sizes(cls, values: list[str]) -> list[str]:
        if len({value.casefold() for value in values}) != len(values):
            raise ValueError("Sizes must be unique")
        return values
