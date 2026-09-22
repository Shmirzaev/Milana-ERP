from app.schemas.common import SchemaModel


class HrPositionOut(SchemaModel):
    id: int
    org_unit_id: int | None = None
    department_id: int | None = None
    department_name: str | None = None
    name: str
    job_description: str | None = None
    required_skills: list[str]
    qualification_level: str | None = None
    grade_level: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    approved_count: int
    occupied_count: int
    vacant_count: int
    is_active: bool


class HrPositionPageOut(SchemaModel):
    rows: list[HrPositionOut]
    total: int
    page: int
    page_size: int
    has_more: bool
