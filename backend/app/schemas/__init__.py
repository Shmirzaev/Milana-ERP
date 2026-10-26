from app.schemas.inventory.eco_transfer import EcoFabricDispatch, EcoFabricRoll
from app.schemas.catalog.paid_process import PaidProcess
from app.schemas.order_reference import BusinessOrderAlias
from app.schemas.core import (
    Role, Department, User, Employee, AuditLog, Notification, PasswordResetToken, SystemSetting, IdempotencyRecord,
)
from app.schemas.catalog.partners import Customer, Supplier
from app.schemas.catalog.catalog import (
    Brand, Collection, CollectionModel, Model, ModelImage, ModelSize, ModelColor, ModelBOM,
)
from app.schemas.inventory.inventory import (
    Item, Warehouse, StockBatch, StockMovement, MaterialReservation, ManualAccessoryIssue,
)
from app.schemas.purchasing.purchasing import (
    PurchaseRequest, PurchaseRequestLine, PurchaseOrder, PurchaseOrderLine,
)
from app.schemas.sales.sales import (
    SalesOrder, SalesOrderItem, Shipment, ShipmentPackage, ShipmentScanLog, Invoice, Payment,
)
from app.schemas.production.production import (
    BrandedPlanningOrder, ProductionOrder, ProductionOrderMaterial, ProductionBatch, ProductionOrderItem,
    WorkOrder, public_production_order_no, CuttingRecord, CuttingMaterialUsage,
    CuttingBeikaMaterialUsage, PrintingRecord, SewingRecord,
    SewingReplacementRequest, PackagingRecord, PackagingReceipt, QualityCheck,
)
from app.schemas.production.tracking import (
    Bundle, BundleScanLog, Package, PackageItem, PackageBatchAllocation, PackageScanLog,
    PackageChangeRequest, PackageBarcodeAlias, LegacyStockReceipt, FinishedGoodsStock, StockReservation, WarehousePackReservation,
)
from app.schemas.planning.forecasting import ForecastRecommendation
from app.schemas.inventory.waste import WasteRecord, WasteSale, WasteDisposalRequest
from app.schemas.work_management.tasks import Task
from app.schemas.production.sewing_flow import SewingFlow
from app.schemas.production.sewing_assignment import SewingAssignment
from app.schemas.production.sewing_daily_report import SewingDailyReport
from app.schemas.production.cutting_passport import CuttingPassport
from app.schemas.people.payroll import PayrollPeriod, PayrollRecord, PayrollQrLabel, PayrollAdjustment
from app.schemas.people.attendance import AttendanceDevice, AttendancePerson, AttendanceEvent
from app.schemas.people.hr import HrOrgUnit, HrPosition, HrEmployeeDocument, HrRecruitmentCandidate, HrCalendarEvent
from app.schemas.planning.price_calculation import PriceCalculationRequest
from app.schemas.inventory.stocktake import WarehouseStocktake, WarehouseStocktakeRow
from app.schemas.packaging.package_workflows import ManualPackageReceipt, PackagePrintRun, PackagePrintRunMember
from app.schemas.fulfillment.shipment_review import PackageQuantityAdjustment

from app.schemas.inventory.fabric_scan import FabricScan

__all__ = [
    "EcoFabricDispatch", "EcoFabricRoll",
    "FabricScan",
    "PaidProcess",
    "BusinessOrderAlias",
    "Role", "Department", "User", "Employee", "AuditLog", "Notification", "PasswordResetToken", "SystemSetting",
    "IdempotencyRecord",
    "Customer", "Supplier",
    "Brand", "Collection", "CollectionModel", "Model", "ModelImage", "ModelSize", "ModelColor", "ModelBOM",
    "Item", "Warehouse", "StockBatch", "StockMovement", "MaterialReservation", "ManualAccessoryIssue",
    "PurchaseRequest", "PurchaseRequestLine", "PurchaseOrder", "PurchaseOrderLine",
    "SalesOrder", "SalesOrderItem", "Shipment", "ShipmentPackage", "ShipmentScanLog", "Invoice", "Payment",
    "BrandedPlanningOrder", "ProductionOrder", "ProductionOrderMaterial", "ProductionBatch", "ProductionOrderItem",
    "WorkOrder", "public_production_order_no", "CuttingRecord", "CuttingMaterialUsage",
    "CuttingBeikaMaterialUsage", "PrintingRecord",
    "SewingRecord", "SewingReplacementRequest", "PackagingRecord", "PackagingReceipt", "QualityCheck",
    "Bundle", "BundleScanLog", "Package", "PackageItem", "PackageBatchAllocation", "PackageScanLog",
    "PackageChangeRequest", "PackageBarcodeAlias", "LegacyStockReceipt",
    "FinishedGoodsStock", "StockReservation", "WarehousePackReservation",
    "ForecastRecommendation",
    "WasteRecord", "WasteSale", "WasteDisposalRequest",
    "Task",
    "SewingFlow",
    "SewingAssignment",
    "SewingDailyReport",
    "CuttingPassport",
    "PayrollPeriod", "PayrollRecord", "PayrollQrLabel", "PayrollAdjustment",
    "AttendanceDevice", "AttendancePerson", "AttendanceEvent",
    "HrOrgUnit", "HrPosition", "HrEmployeeDocument", "HrRecruitmentCandidate", "HrCalendarEvent",
    "PriceCalculationRequest",
    "WarehouseStocktake", "WarehouseStocktakeRow",
    "ManualPackageReceipt", "PackagePrintRun", "PackagePrintRunMember",
    "PackageQuantityAdjustment",
]
