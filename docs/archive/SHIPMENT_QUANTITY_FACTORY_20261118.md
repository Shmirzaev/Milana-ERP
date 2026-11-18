# Shipment quantity selection across factories

18 November 2026. User requested diagnosis, then a fix for quantity-save 403 on
SH-2026-000337 / PKG-2026-003047. Explicitly approved verified `origin/clone_main`
instead of stale `origin/main` as the implementation base. No merge/deployment
authorization is inferred. Engineer owner: Mirshoir; human reviewer: Ismail;
business acceptance: Shavkat/operators. Human acceptance remains pending.

## Source and operation

- Worktree: `C:/ERP/.codex-work/shipment-quantity-factory-20261118`;
  branch: `codex/shipment-quantity-factory-20261118`;
  source base: `b0a5473b2` on `origin/clone_main`.
- Both production symlinks name `20261116_130518`; both manifest-file digests
  match `bc2e0d4bdbb38f6c06b9f3d5c75f3fdaa1fb5087240ca8f7b49d01318908ce40`,
  matching this branch's production-base record. Source baseline is `4d7cf17e`;
  retained rollback is recorded as `20261116_092917`. No production writes.
- Operation: `POST /api/shipments/{sid}/packages/{pid}/quantity`,
  `ShipmentQuantityReview.keep_remainder=true` ->
  `package_dispatch_service.select_dispatch_quantity` ->
  `shipment_allocation_service.validate_claim` -> schema-owned `save_package_claim`.
  Sole alternate caller is the isolated PostgreSQL race test.
- Frontend caller: `ShipmentReviewPanel.save`, through the existing shipment
  preparation workspace. Editor checks `storage.shipment`; backend route checks
  the same effective selected-factory permission and requires a matched scan.
- Selection writes only `Shipment.dispatch_snapshot.package_quantities`,
  `ShipmentPackage.quantity` and the existing audited selection event. Package
  contents, print/receipt evidence, stock, reservations and manufacturing owner
  stay unchanged. The route owns commit; lock order and schema writer are unchanged.
- Existing created/draft state subset, integer quantity DTOs and strict booleans
  are retained. No vocabulary, enum, API contract, table or migration is added.
  Physical receipt correction (`keep_remainder=false`) and all manufacturing
  package-access checks remain outside this change.

## Defect and intended behavior

The warehouse is shared, but selection called the manufacturing-only
`require_package_access` guard. A Besttex pack therefore scanned successfully but
its Milana selection failed, including for Super Admin. Remove that call only
from dispatch selection. Keep route permission, matched scan, package/link
readiness, current quantity, per-size availability and competing-claim guards.
Packaging creation/edit/print operations retain their existing factory guards.

## Verification record

- Baseline: the new real-route regression passed same-factory selection, then
  failed a cross-factory selection with 403 and the specific matching-factory
  error (1 failed, 1 passed). This reproduces the defect before the fix.
- Candidate checks: 61 passed across `test_shipment_quantity_factory_scope.py`
  (23 new cases), `test_shipment_review.py` and `test_open_shipment_allocations.py`;
  18 passed across `test_factory_permission_scope.py`,
  `test_factory_scoped_permissions.py` and `test_shipment_duplicate_scan.py`.
  Ruff for changed Python and `git diff --check` pass. No frontend source changes.
- Real PostgreSQL: all five `test_open_shipment_allocations_postgres.py` cases
  passed with zero skips on a disposable PostgreSQL 16 container bound only to
  loopback port 15424. Two-worker attach/edit/dispatch races retain per-size stock
  conservation and stale-readiness checks. Production was never a test target.
- Actual connected Edge, local candidate frontend on 13124 and candidate backend
  on 18124: logged into Milana as seeded Super Admin, scanned a Besttex-owned
  60-piece package, saved one piece in each of two sizes, then fully reloaded.
  The real page retained quantity 2 and displayed each size as 1. The screenshot
  was visually inspected. Independent read-only SQL confirmed BPK ownership,
  physical quantity 60, selected quantity 2, stock totals quantity/available/
  reserved/sold = 60/60/0/0 and the matching audited reason.
- Bounded separate disposable test fixture: 25 changing partial saves, one
  refused over-allocation without an audit/claim change, then one successful
  recovery save. All 26 saves passed in 1.033 seconds; physical/available stock
  stayed 60 and final selected quantity was 2. This is a bounded local check,
  not a production performance or load claim.
- Independent agent reviewed the unchanged runtime diff and tests with no
  blocking finding, and independently reran all 23 new tests with zero skips.
  It also inspected the screenshot and SQL/stress evidence. Reviewed Git blob
  hashes: service `0feefb044adcc2c5f8dafc0a56facea06ece0152`,
  tests `7a962746ade7ca5ad0b0b8c9a2920545767fb14f`.
- Local ignored evidence: `outputs/shipment-quantity/qa_server.py`,
  `saved-after-reload.png`, `browser-readback.json`, `readback.py`, `stress.py`,
  `stress-result.json`. The server uses test-only temporary SQLite and synthetic
  fixtures; it does not load production data or credentials.
- Browser limitations: extension-injected `bis_skin_checked` attributes produce
  hydration warnings. A supplementary cross-factory manufacturing-detail visit
  remained on its existing Loading screen, so that visual negative check is not
  counted as passed. The unchanged manufacturing guard's 403 is independently
  verified by the regression test. Denied-role and downstream browser checks are
  not established; API tests verify both. Full visual verification is BLOCKED;
  do not mark `AI_VERIFIED_AWAITING_HUMAN` or authorize release from this evidence.
  No clean-console or whole-packaging-UI claim is made.
- An initial supplementary pytest command named nonexistent
  `test_factory_scopes.py`; collection ran no tests. The corrected explicit
  three-file command produced the 18 passes above. No test was weakened.
- No production data, role, permission assignment, schema, release, image or
  traffic route changed. No merge/deployment authorization is inferred.
- Acceptance matrix: each MIL/BST/ECO login versus each PKG/BPK/ECP owner for
  a shipment-only actor and Super Admin; selected totals persist without changing
  physical stock; actors without shipment permission receive 403 with no writes;
  unscanned packages remain blocked. Split dispatch must consume 2 then 58 of
  60 pieces while manufacturing access remains factory restricted.
- Human checklist: in an isolated candidate, log into Milana, scan a Besttex
  package, select a partial quantity, Save, reopen and verify the saved total and
  remaining stock. Repeat with a shipment-only actor; verify a packaging edit
  is still denied across factories. Do not save test quantities in production.
