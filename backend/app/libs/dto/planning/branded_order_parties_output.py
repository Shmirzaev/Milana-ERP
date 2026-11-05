"""Selectable branded-order parties, with the company-only enum subset."""
from typing import Annotated

from pydantic import AfterValidator, WithJsonSchema

from app.libs.dto.common import SchemaModel
from app.libs.enums.planning import BrandedPlanningOrderType

COMPANY_TYPES = (
    BrandedPlanningOrderType.MILANA,
    BrandedPlanningOrderType.ECO_COTTON,
    BrandedPlanningOrderType.BESTTEX,
)


def require_company_type(value: BrandedPlanningOrderType) -> BrandedPlanningOrderType:
    if value not in COMPANY_TYPES:
        raise ValueError("Party type must be a company")
    return value


CompanyType = Annotated[
    BrandedPlanningOrderType,
    AfterValidator(require_company_type),
    WithJsonSchema({"type": "string", "enum": [value.value for value in COMPANY_TYPES]}),
]


class BrandedOrderCompanyOut(SchemaModel):
    type: CompanyType
    name: str


class BrandedOrderCustomerOut(SchemaModel):
    id: int
    name: str


class BrandedOrderPartiesOut(SchemaModel):
    companies: list[BrandedOrderCompanyOut]
    customers: list[BrandedOrderCustomerOut]
