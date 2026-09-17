# Ismail audit — stabilization fixes

18 September 2026 · `feat/ismoiljon` → `main` · Base `80f4831e`

**14 scoped fixes. No deployment, production access, schema migration or database redesign.** Historical findings outside this table remain open.

## Fixed and regression-tested

| Bug | Risk | Code / fix |
| --- | --- | --- |
| **ST01 — Receipt retry adds stock twice** | Inventory overstated after a lost response | [purchasing.py:170](backend/app/api/routes/purchasing.py#L170): lock order and replay saved result atomically. [Receiving:238](frontend/src/app/(app)/purchasing/receiving/page.tsx#L238): persist request key/payload; recover after reload; coordinate tabs. |
| **ST02 — Movement leaves batch unchanged / accepts another item's batch** | Wrong stock and traceability | [inventory.py:1270](backend/app/api/routes/inventory.py#L1270): validate quantity/item/unit/location; lock and update batch with ledger. |
| **ST03 — W1 movements affect W2 balance** | Wrong warehouse availability | [inventory service:80](backend/app/services/inventory.py#L80): scope incoming/outgoing movements; transfers net to zero globally. |
| **ST11 — Concurrent reservations exceed stock** | Material promised twice | [inventory service:474](backend/app/services/inventory.py#L474): ordered batch/item locks before availability checks. [Cutting:502](backend/app/api/routes/cutting_passports.py#L502): reserve additions together to avoid the discovered lock-order deadlock. |
| **FN02 — Concurrent payments leave stale totals/status** | Wrong receivables or advance allocation | [payments.py:35](backend/app/services/payments.py#L35), [partners.py:242](backend/app/api/routes/partners.py#L242): lock/refresh invoices before calculation. Supported overpayments/advances remain supported. |
| **FN04 — Finance requests create duplicate invoices** | Duplicate billing | [finance.py:68](backend/app/api/routes/finance.py#L68): serialize this endpoint's decision on the order. |
| **SEC04 — Revoked accounts still download model files** | Access survives account revocation | [main.py:338](backend/app/main.py#L338): check current user; release DB connection before file processing. |
| **SEC05 — Old sibling reset links remain usable** | Password changed again using an old link | [auth.py:284](backend/app/api/routes/auth.py#L284): lock user; consume all outstanding links atomically. |
| **SEC07 — Assignment deletion bypasses factory scope** | Changes another factory's work | [production_extra.py:385](backend/app/api/routes/production_extra.py#L385): enforce sewing-flow factory access before deletion. |
| **SEC10 — Lower-privileged admin deletes super admin** | Privileged account removal | [admin.py:572](backend/app/api/routes/admin.py#L572): protect privileged targets on DELETE. |
| **UI01 — Temporary session failure logs users out** | Interrupted work | [auth.ts:20](frontend/src/lib/auth.ts#L20), [AuthGate.tsx:167](frontend/src/components/AuthGate.tsx#L167): distinguish 401/403 from outages; offer bounded retries. |
| **UI02 — Body download escapes request timeout** | Screen can wait indefinitely | [api.ts:23](frontend/src/lib/api.ts#L23): deadline/cancellation covers response body too. |
| **PY01 — Scans credit the wrong employee** | Incorrect payroll | [scan/page.tsx:896](frontend/src/app/(app)/payroll/scan/page.tsx#L896): process badge, work and manual-selection events in order. |
| **PERF01 — Package list repeats DB queries per row** | Slow listings and wasted DB capacity | [packages.py:489](backend/app/api/routes/packages.py#L489): batch context/model reads. **50 packages: 152 → 5 SELECTs.** |

## Evidence

- **PostgreSQL: 21 concurrency checks passed** on disposable local PostgreSQL 17; cluster stopped. Covers receipts, payments, invoice creation, sibling reset links, reservations and Cutting contention.
- **Browser:** real login → temporary 503 → recovery; genuine 401 redirects. Real receipt commit → dropped response → reload/retry leaves quantity **5, not 10**. Rendered payroll UI with controlled API responses preserves badge/work order and manual selections (`[A, A, B]`). No JavaScript page errors in these scenarios.
- Package SELECT counts for **1 / 10 / 50** rows: legacy **5/5/5**, distinct linked models **9/9/9**, order fallback **7/7/7**. Bounded round trips for these pages, **not O(1) total processing** or a load-capacity guarantee.
- **Backend: 1,172 passed / 17 PostgreSQL opt-in cases skipped** in the full sweep; two subsequently added Cutting cases also passed. All 21 final PostgreSQL cases passed separately. Runtime dependency versions match the repository pins.
- **Frontend:** four stabilization scripts, existing build contracts, full/strict TypeScript, ESLint and optimized 88-page build passed. Backend Ruff/compilation passed. Observation-script tests passed on rerun; first run hit a Windows temporary-file rename error (no code change).

Regression sources: [backend tests](backend/app/tests), [reservation concurrency](backend/app/tests/test_material_reservation_concurrency.py), [frontend scripts](frontend/scripts). PostgreSQL checks now run in [CI](.github/workflows/ci.yml). [Browser screenshots](docs/audit-evidence) contain synthetic data only.

Re-run locally (each command starts at the repo root; synthetic data only):

```text
cd backend; python -m pytest -q; cd ..
npm --prefix frontend run test:stabilization
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend run build
python scripts/run_isolated_postgres_tests.py --pg-bin "PATH/TO/POSTGRES/bin" -q -k postgres
```

## Still open / limits

- **Inventory:** batchless reservations are not fully enforced by every batch-specific issue/allocation path. Old stock discrepancies are not repaired. Partial batch transfers reject with 409; splitting batches is a separate workflow.
- **Duplicates:** receipts need the same saved key. Different operators/keys can still represent the same physical delivery. Finance deduplication does not cover every 1C/workflow entry point.
- **Recovery:** receipts require browser storage and Web Locks. Uncertain requests that later lose access/conflict retain evidence and need reconciliation; do not clear storage blindly.
- **Security:** audit-chain concurrency/history deletion and remaining cross-factory endpoints are not fixed. Signed sales-file URLs retain their existing expiry-based policy.
- **Readiness:** other slow endpoints, fresh-database migrations, full workflow/load tests and backup-restore proof still need work. Other pre-existing lock-order risks remain. **Not a production-readiness sign-off.**

Recorded production application code matches the base; live servers/manifests were intentionally not queried. Revalidate deployment state before any release.
