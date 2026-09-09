# Payroll and department changes — pre-deployment review

Date: 2026-09-09. Worktree: `C:/ERP/.codex-work/payroll-departments-20260909`. Branch: `codex/payroll-departments-20260909`.

All eight requested changes are prepared, including automatic size ranges and the clarification that existing order numbers and QR/printed references must become canonical. Local aggregate QA is complete. No production deployment, migration or business-data write occurred. Active production remains green `20260909_053325`; blue `20260909_035800` remains the rollback release. Production database remains at `0117_package_quantity_evidence`. Read-only production checks found zero orphaned references and valid BSOrder links.

## Requested changes

- [x] **1. Actual four-digit order numbers.** Migration `0119_canonical_order_references` assigns canonical `SO`/`PO`/`USL`/`PR`/`PUR` values to existing primary and denormalized order fields, including issued MW2/JSON reference fields; new orders use the same format. Durable historical aliases preserve old printed-label lookup. Valid numbers and unique usable suffixes are retained where possible; collisions/out-of-range values receive available numbers. Allocation is serialized and blocks at 9999 instead of wrapping. Standalone production uses its actual `PO`/`USL` number rather than generating a synthetic `SO`; sales-linked production uses its real Sales Order number. Database IDs, scan UIDs, rates, quantities, raw audits and idempotency fingerprints remain intact. This supersedes the earlier display-only implementation.
- [x] **2. Department tables.** Incoming, pending, in-progress and completed queues use BSOrder groups, model/variant details, sizes, pictures, quantities, deadlines and preserved actions. White/yellow/green distinguish workflow states. Chrome verified the Milana department fixture; tables retain horizontal scrolling.
- [x] **3. Reusable paid-process catalogue.** Search by name/code, select an existing operation, or add a process with a stable generated code. Chrome created `OP-0004`, searched it and verified deduplication. Identity is scoped by factory and section; prices remain model-specific. Migration `0118_paid_process_catalog` seeds existing names without rewriting model operations or rates.
- [x] **4. Old ERP sections.** Read-only Chrome inspection confirmed all 13: Sewing, Cutting, Packaging, Tikuv, Cleaning, Pressing, Control, Storage, Transfer, Snaps, Buttons, Cord and Sorting. Separate source-stage identities and English/Russian/Uzbek labels are supported.
- [x] **5. Process QR totals.** Operations show the selected total rate per piece and the generated quantity-weighted amount. Browser fixture results were **850 per piece** and **51,000 total**.
- [x] **6. Model-prefix ordering.** Two-letter searches return larger model numbers first. Chrome verified `XJ5999`, then `XJ5614`, then `XJ5415`.
- [x] **7. Control confirmation.** Control scans show related operations and scan states before crediting only the scanned Control operation. Cancelling wrote no payroll record; confirmation created one **29,750** record, and rescanning preserved duplicate protection. Server checks cover numeric/compact/legacy issued labels, factory/employee isolation, stale snapshots, voided records and ordinary single/bulk save bypass attempts. Employee changes invalidate pending reviews and are blocked during confirmation.
- [x] **8. Save missing model sizes.** Manual Process QR uses the same beginning/end size selectors and standard size list as Models. Intermediate sizes appear automatically; 48–58 generates 48, 50, 52, 54, 56, 58. Chrome verified all six persisted sizes and single-size/reversed-range handling; component lint and full/strict TypeScript passed after this follow-up. The API requires payroll/model permission, locks the model, inserts atomically, audits the change and rejects duplicates or an already-configured model. Existing/sibling sizes are preserved.

## Validation

The canonical-number follow-up passed **821 backend tests**, frontend lint, strict TypeScript, all frontend contracts and the optimized **85-page production build**, with one upstream Starlette/httpx deprecation warning. After the final BSOrder capacity guard and expanded migration assertions, **18 focused migration/numbering tests passed**. BSOrder remains numeric four digits and rejects exhaustion rather than generating 10000. Focused tests cover migration seed preservation, normalized catalogue identity/search escaping, factory and permission boundaries, numbering, size persistence, Control replay/return behavior and deferred scanner responses.

Canonical-reference regressions verify fresh bundle PNG/inline print QR content, legacy bundle-label resolution, authenticated browser image access, canonical cutting-sheet output, stale passport/stock/purchasing writes, preservation of manual references, and inventory replay after alias migration without duplicate stock or snapshot/hash changes. Bundle image URLs now generate QR content from live order data with `private, no-store`; Process QR prints the canonical order line. Existing package, bundle, employee and model identifiers retain their own namespaces.

Browser checks used synthetic data in an isolated SQLite backend under `outputs/local-qa`; they did not mutate production. The catalogue stores complete normalized names as text and uses a bounded SHA256 identity key for PostgreSQL uniqueness. Unknown explicit factory ownership is not converted to shared ownership.

## Screenshot evidence

Files are in this worktree's `outputs/screenshots/` directory.

| File | Evidence |
|---|---|
| `canonical-process-qr.png` | Migrated issued labels show stored PO-0608 while preserving their numeric scan identities |
| `canonical-bundle-print.png` | Bundle print document and freshly generated QR use migrated PO-0202 |
| `department-order-tables.png` | BSOrder grouping, compact numbers and department status rows |
| `paid-process-search.png` | Searchable reusable paid processes |
| `paid-operations-totals.png` | Process QR operation totals |
| `models-prefix-order.png` | Descending model-prefix results |
| `manual-model-sizes.png` | Inline missing-size entry |
| `automatic-size-range.png` | Updated beginning/end selectors and automatic intermediate sizes |
| `manual-model-sizes-saved.png` | Sizes saved to the selected model |
| `control-confirmation.png` | Related operations and pre-credit confirmation |
| `control-confirmed.png` | Confirmed Control payroll result |
| `control-uzbek.png` | Uzbek Control review |

## Remaining release gate

This is a pre-deployment review, not a production release. Run the complete `0117 -> 0118_paid_process_catalog -> 0119_canonical_order_references` migration sequence on an isolated PostgreSQL staging copy before deployment. Verify catalogue seeding, canonical uniqueness and capacity, durable aliases, denormalized/issued-payload rewrites, old/new scanner compatibility, and unchanged IDs, scan UIDs, rates, quantities, raw audit records and idempotency fingerprints. SQLite fixtures do not substitute for this PostgreSQL gate.

Any subsequently authorized release must follow `DEPLOYMENT.md`, including a verified production PostgreSQL backup before migration/material changes, the exact reviewed immutable commit/images, inactive-slot validation, all four health checks, performance checks and rollback readiness. Neither migration has run on production. Broader previously documented security findings are outside this change.
