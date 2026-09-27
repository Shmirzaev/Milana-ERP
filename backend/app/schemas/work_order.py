from app.schemas.common import SchemaModel
from app.schemas.production import WorkOrderOut


class WorkOrderPageOut(SchemaModel):
    rows: list[WorkOrderOut]
    total: int
    page: int
    page_size: int
    has_more: bool
