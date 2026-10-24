# Planning and costing

Documentation scaffold authorized on 24 October 2026. No Python package or business
logic has been created here. The files below are destinations for approved work.

**Purpose:** Own material requirement estimates, forecast recommendations, branded planning and the costing request workflow.

**Engineering owner:** Ismail. **Reviewer:** Mirshoir.
**Business acceptance:** Shavkat with operators.
This owner covers the feature's routes, DTOs, enums, database definitions and tests.
See [team ownership](../../../../docs/TEAM_OWNERSHIP.md) for shared-layer coordination.

## Existing code to study first

- Routes: [planning.py](../../api/routes/planning.py), [forecasting.py](../../api/routes/forecasting.py), [price_calculation.py](../../api/routes/price_calculation.py).
- Services/helpers: [planning.py](../planning.py), [forecasting.py](../forecasting.py), [price_calculation.py](../price_calculation.py), [branded_order_export.py](../branded_order_export.py).
- Existing SQLAlchemy schema models: [ForecastRecommendation](../../models/forecasting.py#L10), [PriceCalculationRequest](../../models/price_calculation.py#L9), [BrandedPlanningOrder](../../models/production.py#L22).
- Existing Pydantic contracts: [production.py](../../schemas/production.py), [forecasting.py](../../schemas/forecasting.py), [price_calculation.py](../../schemas/price_calculation.py).

These are source pointers, not permission to move entire mixed files. Trace the
particular operation and every caller/write before choosing what belongs here.

## When making a service file

| Proposed file | Responsibility |
| --- | --- |
| `requirements.py` | Bom-based material estimates. |
| `forecasting.py` | Forecast recommendations. |
| `costing.py` | Department contributions to price calculations. |
| `branded_orders.py` | Branded planning requests and exports. |

Use snake_case filenames and operation names such as `create_*`, `record_*`,
`receive_*` or `approve_*`. A typed function is sufficient; a class is optional
when it owns real dependencies. Accept the Session, validated input and actor
explicitly. State the transaction owner, refusal rules and result contract.
Use the existing ORM models. Migrate existing schemas/ DTOs to libs/dto/<feature>/
with their callers; keep fixed values in libs/enums/. See [DTO conventions](../../libs/dto/README.md).
Do not import routers, call an endpoint, or commit inside a helper owned by another
transaction. Do not create an interface/repository or generic CRUD class by default.

**Import collision:** `app/services/planning.py` already exists. Keep this directory documentation-only until its coordinated conversion is approved. Adding `__init__.py` now can shadow that module; creating child Python modules without a package conversion is not a working import strategy. Preserve or explicitly migrate every existing caller and export.

**First operation to study:** Reuse planning.py calculations and inspect their inventory availability assumptions. Separate proposed requirements from committed stock reservations and production quantities.

**DTOs and enums:** Forecast and costing workflow statuses; do not encode calculated prices or editable rates as enum values. Reuse Create/In, Update and Read/Out contracts
where they exist. Add action-specific input only for a real action. Do not generate
three DTOs for every table or expose privileged fields through generic updates.

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
