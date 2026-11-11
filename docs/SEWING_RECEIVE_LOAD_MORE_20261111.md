# Sewing receiving: Load more

Scope: owner asked where the other USL-0026 nastils were, then requested a
Load more button and explicitly selected `clone_main` as the source branch.
Base: `3053788f2e17bd5585bccf8cd4547a62cc297516`. Both production hosts were
verified at `20261111_052632`, manifest
`55d0edc9b7893df95987102cc6d9ccbe5b59a89f3c369eb5ea1f46a9868d4520`,
matching `origin/clone_main:deploy/production-base.json`. Rollback remains
`20261110_135430`. No merge or deployment is requested.

Accountable production engineer: Mirshoir; human reviewer: Ismail.
Implementation: root Codex agent; independent AI review recorded below.
Neither named human's acceptance is implied.

Operation: list sewing-ready batches. Existing route
`GET /api/bundles/sewing-receive-options` reads Bundle, ProductionOrder,
SalesOrder, Model, ProductionBatch and model images. Existing factory scope,
sewing permission, search aliases, readiness predicate, grouping and array
response are retained. Pagination adds a nonnegative offset and deterministic
newest-first ordering; each request remains bounded to at most 100 groups.
The existing route query is retained migration debt; no new persistence path,
business vocabulary, DTO fields, permission, state transition or table is added.
All existing enum/type candidates and unrelated operations are retained out of
scope with their existing domain owners in TEAM_OWNERSHIP.md.

Caller: BundleScanPanel, ordinary Sewing manual receipt. Initially show 20
groups, append 20 per click, stop after the final page, reset on submitted
search/factory change, retain visible rows on errors and allow Retry. Refresh
and successful manual/QR receipt revalidate all loaded pages. Band-scoped
receiving retains its separate existing endpoint and behavior. Receipt POSTs,
line selections, QR scanning, quantities and downstream handoffs are unchanged.
No listing request writes business data.

Acceptance: 49 waiting batches are reachable as 20, 40, 49; more than 100
batches remain reachable; equal creation timestamps cannot duplicate/omit groups;
received/foreign-factory batches remain excluded. Loading/error/empty states,
search reset, scope reset, refresh after receipt and all three existing
translations must work. Run focused backend pagination and receipt/factory
regressions, actual React/SWR browser interaction, lint and strict TypeScript.
Use only disposable fixtures. No production business writes or deployment.

## Verification evidence

- Baseline reproduction failed the 123-batch regression because every offset
  returned the same 20 rows. The fixed test covers all three factories, equal
  timestamps, the 100-row cap, negative offsets, received/foreign scope and
  read-only bundle/scan-log state.
- Final backend command (PYTHONPATH=backend): `python -m pytest
  backend/app/tests/test_sewing_receive_pagination.py
  backend/app/tests/test_manual_sewing_batch_receipt.py
  backend/app/tests/test_bundle_receiving_factory_scope.py
  backend/app/tests/test_sewing_manual_line_receive.py
  backend/app/tests/test_bundle_reference_aliases.py
  backend/app/tests/test_sewing_band_access.py -q --tb=short`:
  **89 passed**, zero skips/failures, 58.93 seconds. Ruff passed for changed
  Python paths. Existing test-only dependency/weak-secret warnings remain.
- Strict frontend TypeScript and scoped ESLint passed, as did the existing
  `test-bundle-scan-conflicts.mjs` regression. Existing `common.loadMore`,
  `common.loading` and `common.retry` translations are reused in EN/RU/UZ.
- `node scripts/test-sewing-receive-load-more.browser.mjs` passed against the
  actual candidate Next/FastAPI app and disposable SQLite fixtures: 20/40/49,
  all 123 distinct batches, selected line preservation, return to a cached
  search, temporary 503/Retry, real receipt POST followed by 48-row persisted
  GET readback, Refresh, all three factories and the 390-pixel phone viewport.
  There were zero page errors. The actual receipt affected only one disposable
  fixture batch; production data was never written. Full desktop and phone
  screenshots and the 62-request result are in ignored `outputs/load-more/`;
  both layouts were inspected with vision. The phone keeps the existing
  horizontally scrolling table and shows the button beneath it.
- Connected Edge on loopback port 18823 was signed into the disposable app.
  The agent inspected its screenshot and clicked the actual Load more button:
  20 -> 40 -> 48 rows, with the button absent at the end (the fixture receipt
  above had already removed one of the original 49). No production action ran.
  Chrome's connector failed before navigation; Edge completed the visual check.
- Bounded local stress: 21 list GETs, 4 maximum concurrent requests, 123 groups,
  2,000 ms per-request limit; p95 36.74 ms, maximum 36.77 ms, zero errors and
  identical complete rows before/after. No production performance claim.
  Error recovery was exercised separately by the browser's temporary 503.
- Independent reviewer `/root/review_sewing_load_more` identified and then
  verified fixes for the plain-Python band caller's default offset and SWR's
  cached-query size restoration. Final re-review found no actionable issues;
  its separate real React/SWR/Chrome reproduction confirmed the reset settles
  at 20 rows without a render loop. Human review remains separate.
- No schema/locking/constraint behavior changed; PostgreSQL-specific migration
  and concurrency gates are not applicable to this read-only pagination patch.
  A full production build, CI and release QA have not run; this is local evidence,
  not deployment readiness. Next-generated incidental files were restored.

Status: **AI_VERIFIED_AWAITING_HUMAN** for this bounded local operation.
Code and verification remain on the dedicated task branch; no push, shared-branch
merge or deployment was performed. `clone_main` was re-fetched and remained at
the verified base. Next step: human/source integration review and release checks
when requested. The active production and rollback releases remain unchanged.

Human checklist: open Sewing receiving, search USL-0026, click Load more until
the last pending nastil is shown; confirm search resets, a chosen line remains
selected while appending, and Refresh updates the full loaded list.
