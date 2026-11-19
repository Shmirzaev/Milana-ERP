# Reservation plan readiness contract — 4 November 2026

The original candidate was based on `4e17b4aa`; the last confirmed integration
base is `a81f3743`. The exact combined revision still needs verification.
Inventory owner Ismail, reviewer Mirshoir.
This narrowly types the non-persisted material reservation plan readiness; it
is separate from the material reservation lifecycle and accessory-issue plan.
The row vocabulary is `ready`, `shortage`, `partial`; aggregate adds `no_bom`.
An empty BOM continues to report `no_bom` and `is_complete: true`. Arithmetic,
stock policy, storage, transaction boundaries, and JSON string values are unchanged.

This intentionally changes the OpenAPI response schemas from unrestricted strings
to enum references, and response DTO validation now rejects unknown readiness
values, including `no_bom` on a row. Clients generating types from OpenAPI may
need regeneration. Production status and audit consumers, frontend consumers and
legacy audit JSON/hash serialization require combined verification; no production
code or audit history is changed by this candidate. Internal producer contracts
define `ReservationRequirement`, `ReservationBatchSuggestionValue`,
`ReservationPlanRow`, `ReservationPlanSummary`, and `ReservationPlan` TypedDicts;
the requirement, suggestion, plan producer and service wrapper use those types.
The row reservation type and readiness statuses are canonical Enum instances,
and both response readiness fields carry precise Enum types. The stock-context
helper still accepts and returns broadly typed dictionaries; its boundaries and
downstream consumers remain to be reconciled rather than considered fully typed.

Automated, PostgreSQL, browser, persisted-data, stress and independent review gates
remain pending on the exact combined candidate. This record is not human acceptance,
merge or deployment authority. Preserve existing holds and operation ledger.
