# Planning and costing

Business-service group guide, relocated into models/ on 24 October 2026. The
whole-domain extraction of the planning group (requirements, forecasting,
costing, branded orders) now lives in this directory.

**Purpose:** Own material requirement estimates, forecast recommendations, branded planning and the costing request workflow.

**Engineering owner:** Ismail. **Reviewer:** Mirshoir.
**Business acceptance:** Shavkat with operators.
This owner covers the feature's routes, DTOs, enums, database definitions and tests.
See [team ownership](../../../../docs/TEAM_OWNERSHIP.md) for shared-layer coordination.

## Existing code to study first

- Routes: [planning.py](../../api/routes/planning.py), [forecasting.py](../../api/routes/forecasting.py), [price_calculation.py](../../api/routes/price_calculation.py).
- Services/helpers reused by this group: [planning_service.py](../planning_service.py), [forecasting_service.py](../forecasting_service.py), [price_calculation_service.py](../price_calculation_service.py), [branded_order_export_service.py](../branded_order_export_service.py).
- Existing SQLAlchemy schema models: [ForecastRecommendation](../../schemas/planning/forecasting.py#L10), [PriceCalculationRequest](../../schemas/planning/price_calculation.py#L9), [BrandedPlanningOrder](../../schemas/production/production.py#L22).
- Existing Pydantic contracts: [production.py](../../libs/dto/production/production.py), [forecast_recommendation_input.py](../../libs/dto/planning/forecast_recommendation_input.py), [forecast_recommendation_update.py](../../libs/dto/planning/forecast_recommendation_update.py), [forecast_recommendation_output.py](../../libs/dto/planning/forecast_recommendation_output.py), [price_calculation_request_input.py](../../libs/dto/planning/price_calculation_request_input.py), [price_calculation_request_update.py](../../libs/dto/planning/price_calculation_request_update.py), [price_calculation_request_output.py](../../libs/dto/planning/price_calculation_request_output.py), [branded_planning_order_input.py](../../libs/dto/planning/branded_planning_order_input.py), [material_requirement_output.py](../../libs/dto/planning/material_requirement_output.py).

These are source pointers, not permission to move entire mixed files. Trace the
particular operation and every caller/write before choosing what belongs here.

## Service files in this directory

| File | Responsibility | Transaction owner |
| --- | --- | --- |
| [branded_orders_service.py](branded_orders_service.py) | Branded planning orders: list, parties, customer search, creation, workbook export. | `create_branded_order` |
| [forecasting_recommendations_service.py](forecasting_recommendations_service.py) | Forecast recommendation lifecycle: reference checks, factory scope, payload, review. | `create_recommendation`, `update_recommendation` |
| [costing_service.py](costing_service.py) | Price calculation request lifecycle and the cutting, finance, purchasing and accessories contributions. | every write operation |
| [production_planning_service.py](production_planning_service.py) | Production orders planning opens for client sales orders and branded stock. | `create_client_order_production`, `create_branded_stock_production` |

### branded_orders_service.py

- input: the acting user, the validated `BrandedPlanningOrderIn` payload, the
  status filter, the customer search text and the order id
- output: `BrandedPlanningOrderOut` for creation and a list of that DTO for history;
  both HTTP endpoints declare the same response model. The export returns bytes.
- refusals: 404 for a missing customer or branded order; invalid party/status input
  is rejected at the typed HTTP boundary with 422. Party input preserves strip/lower
  normalization. The status query defaults to open and an explicit empty value
  selects every status; padded/uppercase status values are rejected, not normalized.
- records: one `branded_planning_orders` row and one `BrandedPlanningOrder`
  audit row per creation; the list keeps the batched model and cutting work
  order loads
- transaction owner: `create_branded_order`

The first operation uses [schema-owned insertion](../../schemas/planning/branded_order_persistence.py)
and the supplied Session. Numbering and audit remain participants in the same outer
service transaction. Canonical Planning enums are used by input/output DTOs,
the insertion command and the actual history frontend; derived cutting progress
is distinct from stored Production/WorkOrder status. Optional frontend progress
fields retain their not-started display fallback.

This does not migrate the alternate writer in `create_branded_stock_production`,
Production status, costing status, forecasting or every Planning table. Combined
database/browser verification and independent AI/human acceptance remain separate.

### forecasting_recommendations_service.py

- input: the validated `ForecastRecommendationIn` / `ForecastRecommendationPatch`
  payload, the acting user and the factory scope the user may act in
- output: creation returns enum-typed `ForecastRecommendationCreatedOut`;
  historical list/review keep their string-valued response contract
- refusals: 400 for a dangling reference, 403 when the recommendation has no
  factory-attributed model or the model is outside the factory scope, 404 when
  the recommendation does not exist in that scope
- records: one `forecast_recommendations` row and one `ForecastRecommendation`
  audit row per change
- transaction owner: `create_recommendation` and `update_recommendation`

Creation calls the focused schema-owned forecast insertion with the supplied
Session and validates its controlled result before the outer commit. The review
patch uses the canonical status enum with the same four accepted values and its
mapped write is schema-owned; the service keeps scope, audit and the commit.
Existing audit hooks, permissions and flush timing remain intact. Confidence and
object metadata stay extensible; malformed legacy source roots project to null
without storage repair. Historical response vocabularies and raw list-status
filtering remain separate follow-up work. Scoped reorder suggestions remain
excluded; both creation types require an attributed model.

### costing_service.py

- input: the validated department payload, the request id, the acting user and
  the list bounds
- output: the serialized price calculation request as a dict
- refusals: 403 when the acting user may not use that department, 404 for a
  missing request, 409 when a selling price is entered before cutting,
  purchasing and accessories are complete
- records: the request row, its audit row, the department notifications, and the
  completed selling price attached to the model variant
- transaction owner: every operation that writes; the department calculations in
  [price_calculation_service.py](../price_calculation_service.py) never commit

### production_planning_service.py

- input: the validated `ProductionOrderIn` payload and the acting user
- output: the created `ProductionOrder` row
- refusals: 400 for a mismatched production type, an unconfirmed sales order or
  a closed branded planning order, 404 for a missing sales order or branded
  planning order
- records: one `production_orders` row with its batches and work orders, the
  sales order status move for client work and one `ProductionOrder` audit row
- transaction owner: both operations
- production internals stay in [production_service.py](../production_service.py);
  this module only calls its public operations and does not add a second state
  machine

## When making a service file

Use snake_case_service.py filenames and operation names such as `create_*`, `record_*`,
`receive_*` or `approve_*`. A typed function is sufficient; a class is optional
when it owns real dependencies. Accept the Session, validated input and actor
explicitly. State the transaction owner, refusal rules and result contract.
Use the existing ORM definitions in schemas/ and DTOs in libs/dto/<feature>/;
keep fixed values in libs/enums/. See [DTO conventions](../../libs/dto/README.md).
Do not import routers, call an endpoint, or commit inside a helper owned by another
transaction. Do not create an interface/repository or generic CRUD class by default.

**First operation to study:** Reuse planning.py calculations and inspect their inventory availability assumptions. Separate proposed requirements from committed stock reservations and production quantities.

**DTOs and enums:** Forecast and costing workflow statuses; do not encode calculated prices or editable rates as enum values. Reuse Create/In, Update and Read/Out contracts
where they exist. Add action-specific input only for a real action. Do not generate
three DTOs for every table or expose privileged fields through generic updates.

## Remaining exceptions

- `GET /planning/material-requirements/{sales_order_id}` still calls
  [planning_service.py](../planning_service.py) directly. That module is the
  public requirements seam that Purchasing already imports, so it was left in
  place; the route only wraps the rows in the `MaterialRequirement` contract.
  Availability itself stays with Inventory.
- The forecast reads (dashboard, branded stock suggestions, item reorder
  suggestions) still call [forecasting_service.py](../forecasting_service.py)
  from the route. The calculations were already service-owned, so no forwarding
  service was added around them.
- The costing department calculations stay in
  [price_calculation_service.py](../price_calculation_service.py);
  [costing_service.py](costing_service.py) owns the request lifecycle around
  them, including the finance stage gate and the selling price propagation.
- `BrandedPlanningOrderIn` and `MaterialRequirement` moved out of
  [dto/production/production.py](../../libs/dto/production/production.py) into
  this group's DTO folder. `ProductionOrderIn` and `ProductionOrderOut` stay
  production-owned.

## Boundaries and verification

Read Catalog/Inventory through agreed query interfaces. Production owns actual execution and downstream plan reconciliation; Planning must not silently rewrite production facts.

Verify BOM totals, unit handling, availability, costing permissions and bounded queries. Visually compare the planning estimate and costing approval screens with the same fixture order.

## Migration steps

Follow [the shared sequence](../README.md#migration-sequence): study route/DB/rules
and callers -> agree one operation -> capture baseline tests -> extract -> test
old/new separately -> test the real UI on isolated data -> reviewed switch -> human
production verification -> remove old code. Keep one write path per request.
Record the test result, visual evidence, approver and cleanup condition in the task.
Visual success alone does not prove permissions, concurrency or data correctness.
