from app.libs.dto.planning.branded_planning_order_input import BrandedPlanningOrderIn
from app.libs.dto.production.production import ProductionOrderIn


class BrandedProductionIn(ProductionOrderIn):
    branded_order: BrandedPlanningOrderIn | None = None


class BrandedOrderWithProductionIn(BrandedPlanningOrderIn):
    production: ProductionOrderIn | None = None
