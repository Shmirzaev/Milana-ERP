from pydantic import BaseModel, Field, field_validator

MAX_INT4 = 2_147_483_647


def _required_text(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} is required")
    return normalized


class OrgUnitIn(BaseModel):
    parent_id: int | None = Field(default=None, gt=0, le=MAX_INT4)
    department_id: int | None = Field(default=None, gt=0, le=MAX_INT4)
    manager_employee_id: int | None = Field(default=None, gt=0, le=MAX_INT4)
    unit_type: str = Field(pattern="^(company|factory|department|section|team)$")
    name: str = Field(min_length=1, max_length=160)
    code: str | None = Field(default=None, max_length=48)
    sort_order: int = 0

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _required_text(value, "Organization unit name")

