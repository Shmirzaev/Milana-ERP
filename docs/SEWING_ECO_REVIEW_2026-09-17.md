# Sewing, QR Control and Eco fabric transfer review

Prepared for user review on 2026-09-17. **Not merged or deployed.**

## Scope

- Sewing page: saved Input/Sewn/Passed records now have Edit/Delete, confirmation, batch labels and visible protection reasons. Corrections update work-order and sewing-assignment totals, retain an audit snapshot, validate actual upstream output and size limits, and reject stale edits. Used Packaging output and defect/replacement-linked entries remain protected. Daily Sewing Reports are unchanged.
- QR Control: each order starts collapsed and expands independently. White means no active labels scanned, yellow means partly scanned, green means all active labels scanned. Totals use the entire order in the selected factory, regardless of search, status filter or pagination; superseded labels are excluded.
- Fabric to Eco Cotton: a separate Milana-only section with scan queue, Mark sent, scan return, dispatch-date filter, dated item history, counts/weights and outstanding totals. Sending issues exact original roll weights from Milana inventory; return restores the same batch and roll. No Eco inventory or production records are created. Duplicate requests are idempotent, and reservations/stock availability remain enforced.
- Sent rolls are excluded from available inventory counts and printed labels while their original QR identities remain stable. Batch edits/deletion/manual restoration are blocked while any rolls are away.
- Each dispatch automatically downloads one PDF containing sent items and the remaining inventory table, frozen at dispatch time. The PDF remains downloadable from history after returns.
- Migration 0130 creates the custody ledger and grants the existing verified Mubina account inventory.eco_transfers, retaining its other permissions/restrictions. Migration 0131 records sewing assignment contributions and correction versions. UI/API authorization and the targeted migration grant were verified. All new UI/PDF text has EN/RU/UZ translations.

## Review evidence

The screenshot data is disposable local QA data, not production transactions. QR/Eco screenshots use compiled Next pages with intercepted local assets and real isolated API calls. The dynamic Sewing page uses its actual component/providers with only Next navigation/link adapted for the local harness. No frontend listener or external browser request is needed.

Evidence is under `outputs/preview/` in this worktree:

- `sewing-edit.png`, `sewing-saved.png`, `sewing-delete-confirmation.png`
- `qr-control-collapsed.png`, `qr-control-expanded.png`
- `eco-dispatch-draft.png`, `eco-dispatch-sent.png`, `eco-return.png`, `eco-mobile.png`
- `eco-dispatch.pdf`, `eco-dispatch-page-1.png`, `eco-dispatch-ru.pdf`, `eco-dispatch-ru-page-1.png`

The Eco screenshots run as a local Mubina preview account with the material inventory/transfer permissions. Browser checks exercise scan/send/PDF/return, actual sewing edits/deletes, three QR states and mobile overflow. The PDF is rendered and visually inspected in English and Russian; all three languages are generated in backend tests.

Reproducible entry points: `backend/scripts/preview_sewing_eco.py`, `frontend/scripts/prepare-sewing-eco-preview.mjs`, `frontend/scripts/test-sewing-eco.browser.mjs`. The preparation/browser scripts accept ESBUILD_MODULE_PATH, PLAYWRIGHT_MODULE_PATH and PLAYWRIGHT_EXECUTABLE_PATH for local tools. Start a fresh disposable preview backend for every browser run. Build the frontend first.

`backend/scripts/check_eco_sewing_postgres.py` requires an empty loopback PostgreSQL database named erp_qa via ECO_QA_DATABASE_URL. It applies both actual migrations and verifies isolated grants plus simultaneous dispatch, return and stale sewing edit behavior. It refuses other hosts/database names or nonempty databases.

## Validation

- Full backend suite: 980 passed; one existing Starlette test-client deprecation warning.
- Actual PostgreSQL migrations, narrow Mubina grant and concurrent dispatch/return/stale-edit checks passed.
- Frontend lint, strict types, all workflow contracts and optimized 88-page build passed. Build uses an explicit local API_URL.
- Browser checks and EN/RU PDF visual inspection passed; all three PDF languages generated in API tests.
- Ruff and whitespace checks passed. Physical camera/scanner hardware was not exercised.

## Release boundary

Base: origin/main e0516965c497424df3a1c9e91d8766b4976cf844. Production remains blue release 20260917_052400, application commit 42cf6a67cf3cf0e149b60ffc8ca52e943020986c, database revision 0129_user_access_policy, with green 20260916_033607 retained for rollback. Production manifests and deploy/production-base.json agreed before editing. No production business rows or permissions were modified.

Worktree: C:/ERP/.codex-work/sewing-qr-eco-transfers-20260917. Branch: codex/sewing-qr-eco-transfers-20260917. Legacy C:/ERP changes were preserved. Deployment awaits the user's approval after screenshot review and must follow DEPLOYMENT.md, including fresh source reconciliation, backup, exact-commit images, migration, blue/green gates and rollback preservation. Historical audit/security risks remain outside this change.

Custody history must not be dropped on rollback. Migration 0130 refuses downgrade after dispatch history exists. Original per-roll weights are required for previously used batches whose weights cannot be safely reconstructed; the UI explains the required correction instead of guessing.
