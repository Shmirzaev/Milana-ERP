# Backend service and schema-model map

Source inspected: `3eea897ec076ed42c7cbdeb8e097a72f48285838`. Folder scaffolding authorized on 24 October 2026.
Inventory coverage: **47 route files, 87 service/helper files and 97 mapped classes**.
These counts exclude __init__.py and README guides. This is a source-navigation and
proposed ownership map; per-operation behavior, writers, callers and transaction
boundaries still need tracing before extraction. It does not claim full isolation.

## Service destinations

All twelve directories now have README.md guides. A source file appears more than
once when it mixes responsibilities; move the relevant operation, not the whole file.
The links below show current source locations. Database definitions target schemas/
after ALL existing schemas/ DTOs, callers and shims migrate to libs/dto/. Then move
models/ mappings and registration without changing database tables. Do not relabel
source links as migrated before the files actually move. No domain directory is
needed simply to mirror services.

| Destination | Existing routes to inspect | Existing services/helpers to inspect |
| --- | --- | --- |
| [Identity and access](../backend/app/services/identity/README.md) | `auth.py`, `admin.py`, `catalog.py` | `credentials.py`, `factory_scope.py`, `password_reset.py`, `user_access.py` |
| [Catalog and partners](../backend/app/services/catalog/README.md) | `catalog.py`, `partners.py`, `usluga.py`, `paid_processes.py`, `process_qr_setup.py` | `model_family_images.py`, `model_identity.py`, `model_images.py`, `paid_process_catalog.py`, `paid_operations.py`, `variant_display.py` |
| [Purchasing](../backend/app/services/purchasing/README.md) | `purchasing.py` | `purchasing.py` |
| [Sales](../backend/app/services/sales/README.md) | `sales.py`, `usluga.py` | `ready_stock_sales.py` |
| [Material inventory](../backend/app/services/inventory/README.md) | `inventory.py`, `eco_transfers.py`, `fabric_scans.py`, `stocktake.py`, `waste.py` | `inventory.py`, `inventory_access.py`, `inventory_reports.py`, `material_rolls.py`, `stocktake.py`, `eco_transfer_pdf.py` |
| [Planning and costing](../backend/app/services/planning/README.md) | `planning.py`, `forecasting.py`, `price_calculation.py` | `planning.py`, `forecasting.py`, `price_calculation.py`, `branded_order_export.py` |
| [Production execution](../backend/app/services/production/README.md) | `production.py`, `production_extra.py`, `bundles.py`, `cutting_passports.py`, `sewing_bands.py`, `sewing_corrections.py`, `sewing_daily_reports.py`, `sewing_flows.py`, `usluga.py` | `bundles.py`, `cutting_batch_delete.py`, `cutting_batch_guard.py`, `cutting_fabric_usage.py`, `cutting_material_assignment.py`, `cutting_passport_reports.py`, `cutting_passport_usage.py`, `cutting_sewing_factory.py`, `cutting_sheet.py`, `deferred_cutting_usage.py`, `first_grade.py`, `passport_nastil.py`, `passport_sizes.py`, `production.py`, `production_sizes.py`, `sewing_band_progress.py`, `sewing_band_setup.py`, `sewing_daily_report_exports.py`, `sewing_input.py`, `sewing_scope.py`, `process_qr_export.py` |
| [Packaging](../backend/app/services/packaging/README.md) | `packages.py`, `package_workflows.py`, `packaging_reports.py`, `usluga_packaging.py`, `production.py` | `packages.py`, `package_workflows.py`, `package_identity.py`, `legacy_package_identity.py`, `package_label_pages.py`, `package_corrections.py`, `packaging_corrections.py`, `packaging_report_exports.py`, `packaging_reports.py`, `packaging_scope.py` |
| [Warehouse and shipping](../backend/app/services/fulfillment/README.md) | `finished_goods.py`, `warehouse_reservations.py`, `shipments.py`, `packages.py`, `package_workflows.py` | `finished_goods.py`, `package_dispatch.py`, `package_returns.py`, `packages.py`, `package_workflows.py`, `warehouse_packages.py`, `warehouse_report.py`, `shipment_review.py`, `shipment_reopen.py`, `shipment_invoice.py`, `shipment_invoice_excel.py` |
| [Finance](../backend/app/services/finance/README.md) | `finance.py`, `sales.py`, `partners.py`, `shipments.py` | `finance.py`, `payments.py`, `shipment_invoice.py`, `shipment_review.py` |
| [People, attendance and payroll](../backend/app/services/people/README.md) | `hr.py`, `hr_workspace.py`, `attendance.py`, `payroll.py`, `admin.py` | `attendance_event_policy.py`, `attendance_reports.py`, `employee_aliases.py`, `employee_export.py`, `employee_names.py`, `employee_reconciliation.py`, `payroll_factory_scope.py`, `payroll_labels.py`, `payroll_reports.py` |
| [Tasks and notifications](../backend/app/services/work_management/README.md) | `tasks.py`, `notifications.py` | `notifications.py` |

## Shared infrastructure and projections

Additional route files: `barcode.py`, `dashboards.py`, `inbox.py`, `process_tracking.py`, `search.py`, `settings.py`, `super_data.py`, `traceability.py`.

Additional service/helper files: `audit.py`, `barcode.py`, `dashboard_overview.py`, `department_dashboards.py`, `department_repairs.py`, `email.py`, `idempotency.py`, `image_storage.py`, `label_images.py`, `numbering.py`, `print_response.py`, `traceability.py`, `workflow.py`.

Every existing route/service file is covered above or here. Dilmurod coordinates
platform helpers; each feature owner remains responsible for its business queries.
Keep audit/idempotency/storage/email/numbering helpers focused. Cross-feature inbox,
dashboard, search and traceability projections should not own writes. Privileged
super_data and repair operations require their explicit maintenance rules; never
turn unrestricted table CRUD into the ordinary service API.

workflow.py mixes orchestration, stock consumption and invoice issuance. Extract
those rules into Inventory/Finance and retain only the agreed coordinating entry
point. Other mixed files include catalog/admin (accounts and reference data), usluga
(models and orders), packages (contents, receiving and shipping), and sales (orders,
shipments and invoices). A folder alone does not fix those dependencies.

## Existing database models

Each class below has one proposed primary home. This does NOT move its file, change
its table or prove that current writes already follow that ownership. Operations
spanning several groups need one agreed transaction owner and public handoff.
support denotes existing audit, idempotency, settings or shared order-reference
infrastructure; it is not a new required folder or catch-all business service.

<details>
<summary>All 97 existing mapped classes and proposed ownership</summary>

| Existing SQLAlchemy class | Current model file | Proposed group |
| --- | --- | --- |
| [AttendanceDevice](../backend/app/models/attendance.py#L11) | `attendance.py` | `people` |
| [AttendancePerson](../backend/app/models/attendance.py#L39) | `attendance.py` | `people` |
| [AttendanceEvent](../backend/app/models/attendance.py#L66) | `attendance.py` | `people` |
| [Brand](../backend/app/models/catalog.py#L13) | `catalog.py` | `catalog` |
| [Collection](../backend/app/models/catalog.py#L21) | `catalog.py` | `catalog` |
| [Model](../backend/app/models/catalog.py#L33) | `catalog.py` | `catalog` |
| [CollectionModel](../backend/app/models/catalog.py#L111) | `catalog.py` | `catalog` |
| [ModelImage](../backend/app/models/catalog.py#L117) | `catalog.py` | `catalog` |
| [ModelSize](../backend/app/models/catalog.py#L129) | `catalog.py` | `catalog` |
| [ModelColor](../backend/app/models/catalog.py#L137) | `catalog.py` | `catalog` |
| [ModelBOM](../backend/app/models/catalog.py#L145) | `catalog.py` | `catalog` |
| [Role](../backend/app/models/core.py#L9) | `core.py` | `identity` |
| [Department](../backend/app/models/core.py#L15) | `core.py` | `people` |
| [User](../backend/app/models/core.py#L21) | `core.py` | `identity` |
| [Employee](../backend/app/models/core.py#L43) | `core.py` | `people` |
| [AuditLog](../backend/app/models/core.py#L75) | `core.py` | `support` |
| [Notification](../backend/app/models/core.py#L88) | `core.py` | `work_management` |
| [PasswordResetToken](../backend/app/models/core.py#L99) | `core.py` | `identity` |
| [SystemSetting](../backend/app/models/core.py#L110) | `core.py` | `support` |
| [IdempotencyRecord](../backend/app/models/core.py#L116) | `core.py` | `support` |
| [CuttingPassport](../backend/app/models/cutting_passport.py#L14) | `cutting_passport.py` | `production` |
| [EcoFabricDispatch](../backend/app/models/eco_transfer.py#L8) | `eco_transfer.py` | `inventory` |
| [EcoFabricRoll](../backend/app/models/eco_transfer.py#L17) | `eco_transfer.py` | `inventory` |
| [FabricScan](../backend/app/models/fabric_scan.py#L10) | `fabric_scan.py` | `inventory` |
| [ForecastRecommendation](../backend/app/models/forecasting.py#L10) | `forecasting.py` | `planning` |
| [HrOrgUnit](../backend/app/models/hr.py#L11) | `hr.py` | `people` |
| [HrPosition](../backend/app/models/hr.py#L27) | `hr.py` | `people` |
| [HrEmployeeDocument](../backend/app/models/hr.py#L44) | `hr.py` | `people` |
| [HrRecruitmentCandidate](../backend/app/models/hr.py#L60) | `hr.py` | `people` |
| [HrCalendarEvent](../backend/app/models/hr.py#L91) | `hr.py` | `people` |
| [Item](../backend/app/models/inventory.py#L9) | `inventory.py` | `inventory` |
| [Warehouse](../backend/app/models/inventory.py#L31) | `inventory.py` | `inventory` |
| [StockBatch](../backend/app/models/inventory.py#L38) | `inventory.py` | `inventory` |
| [StockMovement](../backend/app/models/inventory.py#L75) | `inventory.py` | `inventory` |
| [MaterialReservation](../backend/app/models/inventory.py#L97) | `inventory.py` | `inventory` |
| [ManualAccessoryIssue](../backend/app/models/inventory.py#L144) | `inventory.py` | `inventory` |
| [BusinessOrderAlias](../backend/app/models/order_reference.py#L7) | `order_reference.py` | `support` |
| [ManualPackageReceipt](../backend/app/models/package_workflows.py#L10) | `package_workflows.py` | `fulfillment` |
| [PackagePrintRun](../backend/app/models/package_workflows.py#L19) | `package_workflows.py` | `packaging` |
| [PackagePrintRunMember](../backend/app/models/package_workflows.py#L38) | `package_workflows.py` | `packaging` |
| [PaidProcess](../backend/app/models/paid_process.py#L7) | `paid_process.py` | `catalog` |
| [UslugaPaidProcess](../backend/app/models/paid_process.py#L18) | `paid_process.py` | `catalog` |
| [Customer](../backend/app/models/partners.py#L7) | `partners.py` | `catalog` |
| [Supplier](../backend/app/models/partners.py#L16) | `partners.py` | `catalog` |
| [PayrollPeriod](../backend/app/models/payroll.py#L11) | `payroll.py` | `people` |
| [PayrollRecord](../backend/app/models/payroll.py#L36) | `payroll.py` | `people` |
| [PayrollQrLabel](../backend/app/models/payroll.py#L89) | `payroll.py` | `people` |
| [PayrollAdjustment](../backend/app/models/payroll.py#L142) | `payroll.py` | `people` |
| [PriceCalculationRequest](../backend/app/models/price_calculation.py#L9) | `price_calculation.py` | `planning` |
| [BrandedPlanningOrder](../backend/app/models/production.py#L22) | `production.py` | `planning` |
| [ProductionOrder](../backend/app/models/production.py#L49) | `production.py` | `production` |
| [ProductionOrderMaterial](../backend/app/models/production.py#L114) | `production.py` | `production` |
| [ProductionBatch](../backend/app/models/production.py#L142) | `production.py` | `production` |
| [ProductionOrderItem](../backend/app/models/production.py#L164) | `production.py` | `production` |
| [WorkOrder](../backend/app/models/production.py#L181) | `production.py` | `production` |
| [CuttingRecord](../backend/app/models/production.py#L240) | `production.py` | `production` |
| [CuttingMaterialUsage](../backend/app/models/production.py#L310) | `production.py` | `production` |
| [CuttingBeikaMaterialUsage](../backend/app/models/production.py#L340) | `production.py` | `production` |
| [PrintingRecord](../backend/app/models/production.py#L375) | `production.py` | `production` |
| [SewingRecord](../backend/app/models/production.py#L395) | `production.py` | `production` |
| [SewingReplacementRequest](../backend/app/models/production.py#L423) | `production.py` | `production` |
| [PackagingRecord](../backend/app/models/production.py#L458) | `production.py` | `packaging` |
| [PackagingReceipt](../backend/app/models/production.py#L479) | `production.py` | `fulfillment` |
| [QualityCheck](../backend/app/models/production.py#L502) | `production.py` | `production` |
| [PurchaseRequest](../backend/app/models/purchasing.py#L9) | `purchasing.py` | `purchasing` |
| [PurchaseRequestLine](../backend/app/models/purchasing.py#L39) | `purchasing.py` | `purchasing` |
| [PurchaseOrder](../backend/app/models/purchasing.py#L71) | `purchasing.py` | `purchasing` |
| [PurchaseOrderLine](../backend/app/models/purchasing.py#L100) | `purchasing.py` | `purchasing` |
| [SalesOrder](../backend/app/models/sales.py#L9) | `sales.py` | `sales` |
| [SalesOrderItem](../backend/app/models/sales.py#L45) | `sales.py` | `sales` |
| [Shipment](../backend/app/models/sales.py#L81) | `sales.py` | `fulfillment` |
| [ShipmentPackage](../backend/app/models/sales.py#L106) | `sales.py` | `fulfillment` |
| [ShipmentScanLog](../backend/app/models/sales.py#L119) | `sales.py` | `fulfillment` |
| [Invoice](../backend/app/models/sales.py#L132) | `sales.py` | `finance` |
| [Payment](../backend/app/models/sales.py#L148) | `sales.py` | `finance` |
| [SewingAssignment](../backend/app/models/sewing_assignment.py#L13) | `sewing_assignment.py` | `production` |
| [SewingDailyReport](../backend/app/models/sewing_daily_report.py#L11) | `sewing_daily_report.py` | `production` |
| [SewingFlow](../backend/app/models/sewing_flow.py#L8) | `sewing_flow.py` | `production` |
| [PackageQuantityAdjustment](../backend/app/models/shipment_review.py#L9) | `shipment_review.py` | `fulfillment` |
| [WarehouseStocktake](../backend/app/models/stocktake.py#L9) | `stocktake.py` | `inventory` |
| [WarehouseStocktakeRow](../backend/app/models/stocktake.py#L18) | `stocktake.py` | `inventory` |
| [Task](../backend/app/models/tasks.py#L9) | `tasks.py` | `work_management` |
| [Bundle](../backend/app/models/tracking.py#L9) | `tracking.py` | `production` |
| [BundleScanLog](../backend/app/models/tracking.py#L41) | `tracking.py` | `production` |
| [Package](../backend/app/models/tracking.py#L54) | `tracking.py` | `packaging` |
| [LegacyStockReceipt](../backend/app/models/tracking.py#L128) | `tracking.py` | `fulfillment` |
| [PackageBarcodeAlias](../backend/app/models/tracking.py#L157) | `tracking.py` | `packaging` |
| [PackageItem](../backend/app/models/tracking.py#L176) | `tracking.py` | `packaging` |
| [PackageBatchAllocation](../backend/app/models/tracking.py#L190) | `tracking.py` | `packaging` |
| [PackageScanLog](../backend/app/models/tracking.py#L203) | `tracking.py` | `packaging` |
| [PackageChangeRequest](../backend/app/models/tracking.py#L214) | `tracking.py` | `packaging` |
| [FinishedGoodsStock](../backend/app/models/tracking.py#L233) | `tracking.py` | `fulfillment` |
| [StockReservation](../backend/app/models/tracking.py#L262) | `tracking.py` | `fulfillment` |
| [WarehousePackReservation](../backend/app/models/tracking.py#L276) | `tracking.py` | `fulfillment` |
| [WasteRecord](../backend/app/models/waste.py#L9) | `waste.py` | `inventory` |
| [WasteSale](../backend/app/models/waste.py#L26) | `waste.py` | `inventory` |
| [WasteDisposalRequest](../backend/app/models/waste.py#L37) | `waste.py` | `inventory` |

</details>

## DTOs and file creation

The group READMEs point to current schema files, which are migration sources.
Move existing Create/In, Update and Read/Out contracts and action inputs into
libs/dto/<feature>/ with their callers; keep one definition per DTO. Inline HR,
attendance and stocktake inputs go to the same target during their operation refactor. Preserve validators,
omitted/null handling, aliases and response filtering.

Use the [layer guides](../backend/app/README.md) for file conventions and
[the migration sequence](../backend/app/services/README.md#migration-sequence) for
technical testing, visual testing, production acceptance and cleanup.
