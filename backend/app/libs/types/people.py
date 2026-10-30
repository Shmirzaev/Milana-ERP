"""Internal People operation contracts."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.libs.enums.factory import FactoryCode
from app.libs.enums.people import PayrollAdjustmentType


@dataclass(frozen=True)
class PayrollAdjustmentCreateCommand:
    """Normalized values passed from the business operation to its schema writer."""

    factory_code: FactoryCode
    payroll_period_id: int | None
    employee_id: int
    adjustment_type: PayrollAdjustmentType
    amount: Decimal
    currency: str
    reason: str
    created_by: int
    created_at: datetime
