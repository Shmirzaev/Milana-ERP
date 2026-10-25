# Planning: DTO contracts

**Engineer:** Ismail. **Reviewer:** Mirshoir. **Business acceptance:** Shavkat.

Existing Pydantic definitions in this group:

- [forecast_recommendation_input.py](forecast_recommendation_input.py) — `ForecastRecommendationIn` and the `RecommendationType` vocabulary.
- [forecast_recommendation_update.py](forecast_recommendation_update.py) — `ForecastRecommendationPatch` and the `RecommendationStatus` vocabulary.
- [forecast_recommendation_output.py](forecast_recommendation_output.py) — `ForecastRecommendationOut`.
- [price_calculation_request_input.py](price_calculation_request_input.py) — `PriceCalculationCreateIn`.
- [price_calculation_request_update.py](price_calculation_request_update.py) — the cutting, finance, purchasing and accessory contribution payloads.
- [price_calculation_request_output.py](price_calculation_request_output.py) — `PriceCalculationRequestOut` and `PriceCalculationAccessoryOut`.
- [branded_planning_order_input.py](branded_planning_order_input.py) — `BrandedPlanningOrderIn`.
- [material_requirement_output.py](material_requirement_output.py) — `MaterialRequirement`.

These describe accepted inputs and returned data. They do not execute database
writes, implement permissions or manage transactions. Field names, bounds,
defaults and the accepted vocabulary are unchanged by the split; the former
`forecasting.py` and `price_calculation.py` modules were replaced by these
per-entity files once every caller moved.

`BrandedPlanningOrderIn` and `MaterialRequirement` used to live in
[../production/production.py](../production/production.py). They are planning
contracts and now live here; `ProductionOrderIn` and `ProductionOrderOut` stay
production-owned.

Before adding a file, find the existing contract and its router/service callers.
Keep creation fields/defaults, allowed update fields and response filtering distinct.
For updates preserve omitted versus explicit null; do not apply creation defaults.
Add action/query contracts only for actual operations. New <entity>_input.py, <entity>_update.py or
<entity>_output.py files are useful when the feature needs them, not a quota for every table.

Reuse shared bases from ../common.py and existing fixed values. Test validation,
serialization, denied/privileged fields and the consuming workflow; then perform
the required visual and release acceptance checks.

See [DTO rules](../README.md), [business services](../../../models/README.md),
[database definitions](../../../schemas/README.md) and
[ownership](../../../../../docs/TEAM_OWNERSHIP.md).
