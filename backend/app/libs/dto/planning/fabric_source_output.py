"""Planning sees source availability and pictures, without inventory prices."""
from app.libs.dto.production.cutting_passport_fabric_output import CuttingPassportFabricOut
from app.libs.enums.inventory import StockBatchQcStatus
from app.libs.enums.eco_inventory import EcoCatalogCategory


class PlanningFabricSourceOut(CuttingPassportFabricOut):
    image_url: str | None = None
    item_category: EcoCatalogCategory
    qc_status: StockBatchQcStatus
