# Backend service and schema-model map

Source inspected: `3eea897ec076ed42c7cbdeb8e097a72f48285838`. Folder scaffolding authorized on 24 October 2026.
Original inventory coverage: **47 route files, 87 service/helper files and 97 mapped classes**.
The service relocation also includes PR #304's sewing_progress_service.py (88 services/helpers).
These counts exclude __init__.py and README guides. This is a source-navigation and
proposed ownership map; per-operation behavior, writers, callers and transaction
boundaries still need tracing before extraction. It does not claim full isolation.

## Service destinations

All twelve directories now have README.md guides. A source file appears more than
once when it mixes responsibilities; move the relevant operation, not the whole file.
The links below show current source locations. Services/helpers now live in
models/*_service.py; route files and existing ORM mapping files keep their names. Database definitions target schemas/
after ALL existing schemas/ DTOs, callers and shims migrate to libs/dto/. Then move
only models/ ORM mappings and registration without changing database tables. Do not relabel
source links as migrated before the files actually move. Business-group guides describe intended operation boundaries; their directories
remain documentation-only until individual extractions are approved.

| Destination | Existing routes to inspect | Existing models/helpers to inspect |
| --- | --- | --- |
| [Identity and access](../backend/app/models/identity/README.md) | `auth.py`, `admin.py`, `catalog.py` | `credentials_service.py`, `factory_scope_service.py`, `password_reset_service.py`, `user_access_service.py` |
| [Catalog and partners](../backend/app/models/catalog/README.md) | `catalog.py`, `partners.py`, `usluga.py`, `paid_processes.py`, `process_qr_setup.py` | `model_family_images_service.py`, `model_identity_service.py`, `model_images_service.py`, `paid_process_catalog_service.py`, `paid_operations_service.py`, `variant_display_service.py` |
| [Purchasing](../backend/app/models/purchasing/README.md) | `purchasing.py` | `purchasing_service.py` |
| [Sales](../backend/app/models/sales/README.md) | `sales.py`, `usluga.py` | `ready_stock_sales_service.py` |
| [Material inventory](../backend/app/models/inventory/README.md) | `inventory.py`, `eco_transfers.py`, `fabric_scans.py`, `stocktake.py`, `waste.py` | `inventory_service.py`, `inventory_access_service.py`, `inventory_reports_service.py`, `material_rolls_service.py`, `stocktake_service.py`, `eco_transfer_pdf_service.py` |
| [Planning and costing](../backend/app/models/planning/README.md) | `planning.py`, `forecasting.py`, `price_calculation.py` | `planning_service.py`, `forecasting_service.py`, `price_calculation_service.py`, `branded_order_export_service.py` |
| [Production execution](../backend/app/models/production/README.md) | `production.py`, `production_extra.py`, `bundles.py`, `cutting_passports.py`, `sewing_bands.py`, `sewing_corrections.py`, `sewing_daily_reports.py`, `sewing_flows.py`, `usluga.py` | `bundles_service.py`, `cutting_batch_delete_service.py`, `cutting_batch_guard_service.py`, `cutting_fabric_usage_service.py`, `cutting_material_assignment_service.py`, `cutting_passport_reports_service.py`, `cutting_passport_usage_service.py`, `cutting_sewing_factory_service.py`, `cutting_sheet_service.py`, `deferred_cutting_usage_service.py`, `first_grade_service.py`, `passport_nastil_service.py`, `passport_sizes_service.py`, `production_service.py`, `production_sizes_service.py`, `sewing_band_progress_service.py`, `sewing_band_setup_service.py`, `sewing_daily_report_exports_service.py`, `sewing_input_service.py`, `sewing_progress_service.py`, `sewing_scope_service.py`, `process_qr_export_service.py` |
| [Packaging](../backend/app/models/packaging/README.md) | `packages.py`, `package_workflows.py`, `packaging_reports.py`, `usluga_packaging.py`, `production.py` | `packages_service.py`, `package_workflows_service.py`, `package_identity_service.py`, `legacy_package_identity_service.py`, `package_label_pages_service.py`, `package_corrections_service.py`, `packaging_corrections_service.py`, `packaging_report_exports_service.py`, `packaging_reports_service.py`, `packaging_scope_service.py` |
| [Warehouse and shipping](../backend/app/models/fulfillment/README.md) | `finished_goods.py`, `warehouse_reservations.py`, `shipments.py`, `packages.py`, `package_workflows.py` | `finished_goods_service.py`, `package_dispatch_service.py`, `package_returns_service.py`, `packages_service.py`, `package_workflows_service.py`, `warehouse_packages_service.py`, `warehouse_report_service.py`, `shipment_review_service.py`, `shipment_reopen_service.py`, `shipment_invoice_service.py`, `shipment_invoice_excel_service.py` |
| [Finance](../backend/app/models/finance/README.md) | `finance.py`, `sales.py`, `partners.py`, `shipments.py` | `finance_service.py`, `payments_service.py`, `shipment_invoice_service.py`, `shipment_review_service.py` |
| [People, attendance and payroll](../backend/app/models/people/README.md) | `hr.py`, `hr_workspace.py`, `attendance.py`, `payroll.py`, `admin.py` | `attendance_event_policy_service.py`, `attendance_reports_service.py`, `employee_aliases_service.py`, `employee_export_service.py`, `employee_names_service.py`, `employee_reconciliation_service.py`, `payroll_factory_scope_service.py`, `payroll_labels_service.py`, `payroll_reports_service.py` |
| [Tasks and notifications](../backend/app/models/work_management/README.md) | `tasks.py`, `notifications.py` | `notifications_service.py` |

## Shared infrastructure and projections

Additional route files: `barcode.py`, `dashboards.py`, `inbox.py`, `process_tracking.py`, `search.py`, `settings.py`, `super_data.py`, `traceability.py`.

Additional service/helper files: `audit_service.py`, `barcode_service.py`, `dashboard_overview_service.py`, `department_dashboards_service.py`, `department_repairs_service.py`, `email_service.py`, `idempotency_service.py`, `image_storage_service.py`, `label_images_service.py`, `numbering_service.py`, `print_response_service.py`, `traceability_service.py`, `workflow_service.py`.

Every existing route/service file is covered above or here. Dilmurod coordinates
platform helpers; each feature owner remains responsible for its business queries.
Keep audit/idempotency/storage/email/numbering helpers focused. Cross-feature inbox,
dashboard, search and traceability projections should not own writes. Privileged
super_data and repair operations require their explicit maintenance rules; never
turn unrestricted table CRUD into the ordinary service API.

workflow_service.py mixes orchestration, stock consumption and invoice issuance. Extract
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
[the migration sequence](../backend/app/models/README.md#migration-sequence) for
technical testing, visual testing, production acceptance and cleanup.
