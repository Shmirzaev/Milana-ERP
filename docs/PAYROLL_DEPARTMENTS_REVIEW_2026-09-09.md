# Payroll and department changes — pre-deployment review

Date: 2026-09-09. Worktree: `C:/ERP/.codex-work/payroll-departments-20260909`. Branch: `codex/payroll-departments-20260909`.

All eight requested changes are prepared and locally verified. No production deployment, migration or business-data write occurred. Active production remains green `20260909_053325`; blue `20260909_035800` remains the rollback release. Production database remains at `0117_package_quantity_evidence`.

## Requested changes

- [x] **1. Four-digit order numbers.** New references use forms such as `PO-0001` and `SO-0606`, continuing the historical sequence with concurrency protection and an explicit 9999 limit. Existing visible references are compact, and searches accept them. Stored historical identifiers, QR payloads and editable source values remain unchanged; numbers above 9999 are preserved.
- [x] **2. Department tables.** Incoming, pending, in-progress and completed queues use BSOrder groups, model/variant details, sizes, pictures, quantities, deadlines and preserved actions. White/yellow/green distinguish workflow states. Chrome verified the Milana department fixture; tables retain horizontal scrolling.
- [x] **3. Reusable paid-process catalogue.** Search by name/code, select an existing operation, or add a process with a stable generated code. Chrome created `OP-0004`, searched it and verified deduplication. Identity is scoped by factory and section; prices remain model-specific. Migration `0118_paid_process_catalog` seeds existing names without rewriting model operations or rates.
- [x] **4. Old ERP sections.** Read-only Chrome inspection confirmed all 13: Sewing, Cutting, Packaging, Tikuv, Cleaning, Pressing, Control, Storage, Transfer, Snaps, Buttons, Cord and Sorting. Separate source-stage identities and English/Russian/Uzbek labels are supported.
- [x] **5. Process QR totals.** Operations show the selected total rate per piece and the generated quantity-weighted amount. Browser fixture results were **850 per piece** and **51,000 total**.
- [x] **6. Model-prefix ordering.** Two-letter searches return larger model numbers first. Chrome verified `XJ5999`, then `XJ5614`, then `XJ5415`.
- [x] **7. Control confirmation.** Control scans show related operations and scan states before crediting only the scanned Control operation. Cancelling wrote no payroll record; confirmation created one **29,750** record, and rescanning preserved duplicate protection. Server checks cover numeric/compact/legacy issued labels, factory/employee isolation, stale snapshots, voided records and ordinary single/bulk save bypass attempts. Employee changes invalidate pending reviews and are blocked during confirmation.
- [x] **8. Save missing model sizes.** Manual Process QR uses the same beginning/end size selectors and standard size list as Models. Intermediate sizes appear automatically; 48–58 generates 48, 50, 52, 54, 56, 58. Chrome verified all six persisted sizes and single-size/reversed-range handling; component lint and full/strict TypeScript passed after this follow-up. The API requires payroll/model permission, locks the model, inserts atomically, audits the change and rejects duplicates or an already-configured model. Existing/sibling sizes are preserved.

## Validation

**802 backend tests passed**, with one upstream Starlette/httpx deprecation warning. Frontend lint, strict TypeScript, all frontend contracts and the optimized **85-page production build** passed. Focused tests cover migration seed preservation, normalized catalogue identity/search escaping, factory and permission boundaries, numbering, size persistence, Control replay/return behavior and deferred scanner responses.

Browser checks used synthetic data in an isolated SQLite backend under `outputs/local-qa`; they did not mutate production. The catalogue stores complete normalized names as text and uses a bounded SHA256 identity key for PostgreSQL uniqueness. Unknown explicit factory ownership is not converted to shared ownership.

## Screenshot evidence

Files are in this worktree's `outputs/screenshots/` directory.

| File | Evidence |
|---|---|
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

This is a pre-deployment review, not a production release. Apply migration `0118_paid_process_catalog` to PostgreSQL staging and verify it before deployment. Any subsequently authorized release must follow `DEPLOYMENT.md`, including the reviewed immutable commit/images, backup, inactive-slot validation, health/performance checks and rollback readiness. Broader previously documented security findings are outside this change.
