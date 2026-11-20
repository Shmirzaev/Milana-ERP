# Accessory batch numbers and QC controls — 20 November 2026

Owner request: replace the imported `MIL-OPEN26-...` batch labels with only
four-digit numbers, and remove the QC status requirement for accessories.
The owner requested Edge for actual browser verification and signed in there.
No application deployment or merge has been authorized in this follow-up.

Scope: 759 opening-import StockBatch identities, original IDs2189–2947 in Milana
Accessory Storage2/STR. The reviewed mapping binds every ID to its old label,
item/SKU and source key, checked against the original import manifest SHA-256
`5d0d727e6b3032c0d24aa7550e5a3778bc1b7a67e8f5809690c387a86189a30d`.
New labels range1000–1818, skipping labels already used anywhere in batch_no or
internal_batch_no, including archived stock. No stock, item or linked business
record is created or deleted. The mapped change is batch_no plus the ORM's normal
updated_at timestamp; quantities, valuation, QC, provenance, warehouse and linked
inventory facts must remain unchanged. Append-only audits retain old/new labels.

Inventory engineering owner: Ismail; default human reviewer: Mirshoir; operator
acceptance: Shavkat. Coordinating implementation/reviewer: root Codex session.
Independent agent accessories_review implemented the two frontend changes and
reviewed the operational correction; root independently reviewed the UI diff.

Initial isolated base65c861c matched release20261119_122457_44523647780_1. Another
engineer's release became live during preparation. The guard refused before plan
construction or business writes. Both fresh source links/manifests then verified
release20261120_040300, source98130821354f487767a9b79f56482f1788ac4c40, manifest
`7e888254a16e7c8ff277d99c4eff29a8a0f40c149aa3229987074232badcabb7`, schema0159.
The owner's prior explicit verified-production-baseline exception applies.
The active container is milana-backend-blue. No traffic switch is part of this task.

## Operation and interfaces

The one-time runner supplies reviewed code in memory to the exact live image;
it installs no runtime files. Business operation -> existing access checks and
schema-owned `set_batch_number` -> StockBatch; normal `log_action` appends audits
in the same outer transaction. Only this supplied Session commits. A table lock
protects label collision checks. Both production host/database and loopback QA
host/database are explicit; fault/rehearsal mode is refused against production.
Full stock/items/movements/reservations/manual-issue fingerprints are compared
around the operation, excluding only authorized label/timestamp columns.
Immediate readback/retry checks that complete snapshot. Legitimate later
inventory activity can make that deliberately strict retry refuse; it cannot
create a second rename operation. Historical audit-chain repair is outside scope.

Accessory UI change: hide QC selectors on receipt, return and edit, omit QC from
their request payloads, and remove QC header/detail text from accessory inventory.
Fabric controls/payloads remain unchanged. Existing backend create DTO defaults
omitted QC to pending; correction exclude_unset preserves a stored status. No
passed inspection is fabricated. Existing pending/passed allocation eligibility
already permits these imported pending batches; held/rejected/failed stock stays
blocked. QC enums, database constraints and history are retained. There is no
new enum, state, permission or migration.

## Gates and current evidence

Frozen mapping and private receipts: outputs/accessories-batch-numbers-20261120.
Actual Edge pre-change readback matches the supplied zipper screenshot, correct
warehouse, provenance and pending QC. Root reviewed both frontend diffs. Focused
behavior checks exercise actual rendered form/JSX and payload functions; source
contracts and targeted ESLint passed under cached tooling.

Exact local dependency installation hit ENOSPC on C:. Automatic approval review
rejected cleanup of this task's partial node_modules with “blocked by policy”.
The owner was asked to free space. Original legacy dependencies/source remain
untouched. Full typecheck initially found only missing cached Daypicker modules;
exact dependency/build and actual candidate-browser gates remain unpassed.

Pre-correction backup:
`/opt/milana-erp/shared/backups/milana_erp_pre_accessory_renumber_20261120_041159.dump`:
133,979,061 bytes, mode0600,1,403 restore objects, SHA-256
`1469b6920e2ddce2a5cae50a0ee353ea230ce537367f687eeca54f95cb7238c7`;
restore-list SHA-256 `e1cc3dd08b530ca8491da9cb25ca1f41de1609031ea39130ed5b5ab19ff56e4e`.
Apply requires a reverified matching backup at most30minutes old, bound QA,
unchanged plan and operation hashes, committed operation source, and live release.

Required data gates: isolated restored-copy valid-hash identity/duplicate/source
refusals, both batch/internal-label collisions, deliberate fault rollback, full
rehearsal rollback, apply/readback,760 linked audits, identical retry, then exact
production readback, actual Edge label verification and four health checks.
No production rename has occurred at this preparation checkpoint.

The isolated restored-copy QA subsequently passed every data gate above,
including rehashed identity/source tampering and collisions in both label fields.
The private PostgreSQL container was removed. Independent source/plan review
found no remaining blocker. The canonical plan hash is
`76c73d79e89076857517afb30cc40679d0c9edd6b196803a081fbcd0bc575cc5`.

Human checklist: verify four-digit labels and readable accessory rows, verify
receipt/return/edit have no accessory QC selection, and confirm fabric QC is
unchanged. Application release/deployment approval remains separate.

Worktree: C:\ERP\.codex-work\accessories-batch-numbers-20261120.
Branch: codex/accessories-batch-numbers-20261120.
