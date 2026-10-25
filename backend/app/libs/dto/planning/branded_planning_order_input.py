from typing import Optional

from app.libs.dto.common import SchemaModel


class BrandedPlanningOrderIn(SchemaModel):
    ordered_for_type: str = "milana"
    customer_id: Optional[int] = None
    notes: Optional[str] = None
