# Shared Sewing output implementation candidate

Date: 2026-10-30  
Checkout: `refactor-sewing-output-20261030`  
Branch: `codex/refactor-sewing-output-20261030`  
Base: `693f7f473c3c26a72dd3994cb0b7478809501d84` / tree `f266e9f3f29dd695f346a5c9cdffbb8d20fc05a6`

This packet records the uncommitted source candidate and its limits. It does not claim PostgreSQL execution, UI acceptance, domain completion, merge, deployment, or stored-data compatibility. The candidate was built within the approved Sewing output boundary in the source audit and complete-write addendum in `.codex-work/refactor-handoff/`.

## Operation and ownership boundary

`POST /api/sewing/records` in `backend/app/api/routes/production.py` and `POST /api/sewing-bands/{aid}/output` in `backend/app/api/routes/sewing_bands.py` now delegate to `app.models.production.sewing_service.record_sewing_output` on the supplied `Session`. The routes retain authentication dependencies and translate the service's expected `SewingOutputError` to HTTP errors. The band-specific operation context is passed as the URL assignment id; the service retains band ownership, assignment/batch correspondence, received-bundle capacity, and WorkOrder-before-assignment refresh checks. The idempotency service retains `sewing:output` scope, fingerprinting and advisory lock behavior. The operation still owns one final `db.commit()` followed by refresh and `{"id": int}`.

The business service composes existing workflow, accessory, input, department, audit, notification and idempotency rules. Added schema-owned writers in `schemas/production/sewing_output_persistence.py` apply SewingRecord values, WorkOrder counters and assignment accounting, accessory blocking, WorkOrder department/input/plans/transitions and ProductionOrder status. `schemas/inventory/waste_persistence.py` owns WasteRecord insertion, including the existing no-op when defect quantity is zero. Existing schema-owned Core persistence remains responsible for audit, notifications and idempotency. No helper commits or opens a second application Session.

The single-operation sequence preserves idempotency serialization before the factory WorkOrder lock, then accessory-gate synchronization/flush and refusal, assignment/batch and quantity validation, SewingRecord flush, counter/input updates, conditional waste, Packaging department and plan effects, workflow/ProductionOrder status, notifications, audit, optional idempotency row and final commit. The band's preflight and WorkOrder lock/assignment refresh order are retained. The accessory refusal test now models the real gate flush, transaction rollback, issuance through `issue_accessories_to_production_order` while preserving its BOM requirement, then retries with the same idempotency key.

## Contracts and explicit exclusions

- Added `WorkOrderStatus` for the exact 11 source/database-constraint values. DTO and internal consumers use the enum, while the SQLAlchemy mapping remains `Mapped[str]`. SQL filters crossing to the mapped string bind `.value` strings. This does not type or rewrite `ProductionOrder.status`, `WorkOrder.operation`, Sewing assignment status, or free-form Sewing data.
- The output accounting contract uses an operation-local transition enum for the only target states this command writes (`in_progress`, `completed`). This is not a claim that all `SewingAssignment.status` values are known: the mapped column remains `Mapped[str]`, has no DB constraint, and assignment-wide writer/DTO/job census plus stored-value review remain unresolved gates.
- Existing response, idempotency scope, defect quantity calculation, workflow behavior, Packaging department/plan/notification effects and actor/factory rules remain the compatibility target.
- Corrections/delete, bundle receipts, assignment planning, band receipt/finish, packaging-record creation, packages, finished-goods stock and material consumption remain separate operations. The separate PR305 Sewing detail authorization work stays untouched.
- Language/status stored-value census, any data migration, actual application/PostgreSQL parity, Shavkat's business examples, Mirshoir/Ismail independent review, and visual checks are still required gates. No stored rows were read or modified.

## PostgreSQL test definitions added

`backend/app/tests/test_sewing_output_postgres.py` uses the existing approved `customer_pg_sessions` fixture and audit-chain verifier. It defines factory and band persistence/replay cases, same-key/different-payload refusal with no extra effects, permission/quantity refusals, a real accessory-gate 409 followed by issuance and same-key retry, zero-defect no-waste/sequence behavior, participant failure rollback/retry cases, an explicit outer-commit-call failure label, and independent factory and band WorkOrder-lock waits with backend PIDs, observed blocker witnesses and final audit-chain verification. The factory success case counts SQLAlchemy `after_commit` events for exactly one commit across first submission, replay and refusal, and verifies audit actor/entity/payload.

These are definitions only. No app imports, pytest cases, SQL, PostgreSQL, browser, API process, or external service was run in this worktree under the RAM restriction. Static checks performed: Python AST parsing of all 14 changed Python files, Ruff on those files, and `git diff --check`.

## Candidate files

- API adapters: `backend/app/api/routes/production.py`, `backend/app/api/routes/sewing_bands.py`.
- Typed contract: `backend/app/libs/enums/production.py`, `backend/app/libs/dto/production/production.py`, `backend/app/libs/types/production.py`.
- Business and adjacent existing business-helper owner boundaries: `backend/app/models/production/sewing_service.py`, `backend/app/models/workflow_service.py`, `backend/app/models/sewing_input_service.py`, `backend/app/models/inventory_service.py`, `backend/app/models/bundles_service.py`.
- Persistence and mapping: `backend/app/schemas/production/sewing_output_persistence.py`, `backend/app/schemas/inventory/waste_persistence.py`, `backend/app/schemas/production/production.py`.
- Required-instance PostgreSQL definitions: `backend/app/tests/test_sewing_output_postgres.py`.
- Production ownership guide: `backend/app/models/production/README.md`.

The checkout remains uncommitted for independent review.
