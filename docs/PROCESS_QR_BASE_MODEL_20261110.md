# Process QR base-model operations

Owner request: permanently load the model's paid operations instead of the
selected variant's list, then deploy promptly. Owner accepted verified live
20261109_163130 as the source baseline. Catalog owner Ismail/reviewer Mirshoir
remain the human assignments; implementation is by root Codex with independent
Codex review. No human engineering/production acceptance is inferred.

## Scope and contract

Process QR opts in to existing model GET with
`paid_operations_from_model=true` in both standard and Usluga catalogs. The
service projects only paid operations from the exact same catalog/factory
family's base row. Canonical catalog identity and existing latest-base
representative semantics apply. Empty or missing base operations become an
explicit empty list; no-base families and legacy imports retain their own list.
General model GET, model editing, variant identity/pictures/sizes/BOM, operation
rates/order/factory filters, issued QR and payroll snapshots retain their paths.

This read adds no database write, new permission, enum, table, migration or
business row. The query control is boolean; model/factory names remain existing
configurable data and operation JSON retains its established contract. The
indexed PostgreSQL family path avoids approval/write locks. Existing family-save
writes remain unchanged, including their historical catalog-wide family semantics;
this narrow read fix does not claim to resolve broader write-scope risks.

Frontend family cache invalidation covers the opt-in URL. Model/catalog context
guards hide old operations during loading and reject stale/late saves. The loaded
message names the business model; the selected variant remains label/order identity.
CleanUI and Uncodixfy guidance preserve the current layout.

## Verification status before release

Focused backend tests: 18 passed before the final PostgreSQL case was added.
Existing Process QR batch/size/select-all/order/factory/manual/family-save contracts
and strict TypeScript passed. Same-ID catalog-switch and loaded-catalog refusal
cases also passed. Repository Ruff/compilation passed before the final test delta.
Independent runtime review found no blocker. Added mandatory PostgreSQL coverage
proves 25 exact-family reads, constant query count, read-only transaction and full
model-table fingerprint conservation. CI/build/final PG/browser/deployment results
must be recorded separately; this preparation does not claim those have passed.

Both live manifests were freshly verified on 20261109_163130, SHA
535aa197ba218b0d0e867480d6a6570a25273307dfdea2185ce28d383f4e56d7.
Source branch codex/process-qr-base-model-20261110 is isolated in
C:/ERP/.codex-work/process-qr-base-model-20261110. Original BJ5039 configuration
repair is recorded separately; this application change performs no backfill.

Release target reserved: 20261110_064423. Exact reviewed commit, immutable images,
backup, inactive-slot signed QA, full response/performance contracts, health and
rollback checks remain required before cutover. User chose Edge after browser
reconnection. Historical performance exceptions/observation waivers do not apply.
