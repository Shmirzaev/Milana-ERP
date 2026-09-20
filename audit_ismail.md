# Ismail audit — stabilization fixes

20 September 2026 · `feat/ismoiljon` → `main` · Base `80f4831e`

**46 of 127 findings fixed and regression-tested. No deployment, production access or database redesign.** [Complete backlog](docs/audit_backlog.json) · [QA steps and complexity](docs/stabilization_qa.md). Findings outside this table remain open. Latest `main` has advanced; PR conflicts and final combined-revision testing remain unresolved.

## Fixed and regression-tested

| Bug | Risk | Code / fix |
| --- | --- | --- |
| **AT04 — Removed device profile hides earlier attendance** | Historical hours disappear from reports | [attendance.py:421](backend/app/api/routes/attendance.py#L421): retain profiles with selected-day events; prefer active copies and preserve factory scope. `27e0809`; **16 tests passed**, including overview/export and deduplication. |
| **AT05 — HR uses the wrong day / unsafe scheduled hours** | Wrong attendance totals or 500 errors | [hr_workspace.py:183](backend/app/api/routes/hr_workspace.py#L183): Tashkent day boundaries; validated factory default and safe employee overrides. `76388c2`; **60 related tests passed; 8 independently repeated**. Shift/break/payroll policy unchanged. |
| **PERF34 — Shipment documents repeatedly scan lists** | Quadratic processing and per-package receipt reads | [shipment_review.py:164](backend/app/services/shipment_review.py#L164), [shipment_invoice.py:33](backend/app/services/shipment_invoice.py#L33): index contents, prices and invoice lines; batch receipts. `a14827f`; **46 tests passed; 4 independently repeated**. 1/20 manual packages: **4/4 SELECTs**, unchanged pricing, order and basis hash. |
| **ST10 — Concurrent conversion creates duplicate orders** | Duplicate purchasing commitments | [purchasing.py:187](backend/app/services/purchasing.py#L187): approval/rejection/conversion share a refreshed request lock. `b409897`; **13 tests passed, including 2 real PostgreSQL races**. Rollback and stale-session checks included. |
| **ST07 — Competing reservations overwrite balances** | Overselling or lost reservations | [finished_goods.py:178](backend/app/api/routes/finished_goods.py#L178): lock package then stock; refresh before checking availability. `c8e82dc`; **109 SQLite + 3 real PostgreSQL tests passed**. Damaged-stock eligibility remains ST09. |
| **API04 — Invalid HR inputs and wrong-factory references** | Bad records or server errors | [hr_workspace.py:34](backend/app/api/routes/hr_workspace.py#L34): shared scope, salary/date, reference and required-text checks. `8250e0c`; **33 tests independently passed**. Valid same-factory cross-department links and optional clearing remain supported. |
| **PERF31 — Roster import reads each person separately** | Slow attendance synchronization | [attendance.py:226](backend/app/api/routes/attendance.py#L226): device-scoped lookup in chunks of 400. `a0b9862`; **14 tests passed; 401 people: 403 → 4 SELECTs**. Writes remain O(n). |
| **ST08 — Release recreates consumed stock** | Sold goods become available again | [finished_goods.py:280](backend/app/api/routes/finished_goods.py#L280): lock and refresh package/stock/reservations; reject shipped, invalid or inconsistent balances. `aa71976`; **108 SQLite + 2 real PostgreSQL tests passed**. Shared reserve writers are covered by ST07 above. |
| **PERF11 — Print history queries each run's members** | Slow history as rows increase | [package_workflows.py:115](backend/app/services/package_workflows.py#L115): batch selected runs' members, retain manifest checks and factory filters. `7dacb8d`; **50 runs: 52 → 3 SELECTs**. 7 focused + 18 existing workflow tests passed. |
| **SEC06 — Concurrent deletes remove the last admin** | Administrator lockout | [admin.py:437](backend/app/api/routes/admin.py#L437): serialize membership changes with locks compatible with audit inserts. `74a2973`; **4 PostgreSQL tests passed**. |
| **WF10 — Viewing waste rewrites stored values** | Historical valuations change on GET | [waste.py:41](backend/app/api/routes/waste.py#L41): calculate the response without writing. `7444997`; **3 focused tests independently passed**; related suite **66 passed / 4 PostgreSQL skipped**. Creation-time valuation policy remains open under FN08. |
| **PERF05 — QR issuance repeats reference queries** | Slow bulk label generation | [payroll.py](backend/app/api/routes/payroll.py): batch label/order/reference reads; preserve unique creation counts. `538ff66`; **64 tests passed**. Reference-only 1/10/50 labels: **8/44/204 → 7/7/7 SELECTs**. Writes/output remain O(n). |
| **FN01 — Bad 1C row aborts later imports** | Valid rows lost; batch fails | [finance_1c.py:122](backend/app/services/finance_1c.py#L122): savepoint per row; preserve caller rollback. `ccf409a`; FN01/FN03 **25 tests passed**, including 8 PostgreSQL cases. |
| **FN03 — Reassigned payment leaves old invoice paid** | Wrong receivables | [finance_1c.py:70](backend/app/services/finance_1c.py#L70): ordered locks, refresh both invoices. `163df36`; **21 tests passed**, including 6 PostgreSQL cases. New external-identity races remain separate. |
| **FN05 — One-cent advance fails or disappears** | Missing customer credit | [partners.py](backend/app/api/routes/partners.py): accept cent-sized residuals; reject sub-cent/nonfinite input. `2d23e13`; **23 tests passed**. Existing invoice settlement tolerance is unchanged. |
| **SEC11 — Quality writes ignore factory scope** | Cross-factory quality records | [production.py:5438](backend/app/api/routes/production.py#L5438): guard the work order before writes. `ac45b6b`; **93 scope/workflow tests passed** on this branch. |
| **ST01 — Receipt retry adds stock twice** | Inventory overstated after a lost response | [purchasing.py:170](backend/app/api/routes/purchasing.py#L170): lock order and replay saved result atomically. [Receiving:238](frontend/src/app/(app)/purchasing/receiving/page.tsx#L238): persist request key/payload; recover after reload; coordinate tabs. |
| **ST02 — Movement leaves batch unchanged / accepts another item's batch** | Wrong stock and traceability | [inventory.py:1270](backend/app/api/routes/inventory.py#L1270): validate quantity/item/unit/location; lock and update batch with ledger. |
| **ST03 — W1 movements affect W2 balance** | Wrong warehouse availability | [inventory service:80](backend/app/services/inventory.py#L80): scope incoming/outgoing movements; transfers net to zero globally. |
| **ST11 — Concurrent reservations exceed stock** | Material promised twice | [inventory service:474](backend/app/services/inventory.py#L474): ordered batch/item locks before availability checks. [Cutting:502](backend/app/api/routes/cutting_passports.py#L502): reserve additions together to avoid the discovered lock-order deadlock. |
| **FN02 — Concurrent payments leave stale totals/status** | Wrong receivables or advance allocation | [payments.py:35](backend/app/services/payments.py#L35), [partners.py:242](backend/app/api/routes/partners.py#L242): lock/refresh invoices before calculation. Supported overpayments/advances remain supported. |
| **FN04 — Finance requests create duplicate invoices** | Duplicate billing | [finance.py:68](backend/app/api/routes/finance.py#L68): serialize this endpoint's decision on the order. |
| **SEC04 — Revoked accounts still download model files** | Access survives account revocation | [main.py:338](backend/app/main.py#L338): check current user; release DB connection before file processing. |
| **SEC05 — Old sibling reset links remain usable** | Password changed again using an old link | [auth.py:284](backend/app/api/routes/auth.py#L284): lock user; consume all outstanding links atomically. |
| **SEC07 — Assignment deletion bypasses factory scope** | Changes another factory's work | [production_extra.py:385](backend/app/api/routes/production_extra.py#L385): enforce sewing-flow factory access before deletion. |
| **SEC10 — Lower-privileged admin deletes super admin** | Privileged account removal | [admin.py:593](backend/app/api/routes/admin.py#L593): protect privileged targets on DELETE. |
| **UI01 — Temporary session failure logs users out** | Interrupted work | [auth.ts:20](frontend/src/lib/auth.ts#L20), [AuthGate.tsx:167](frontend/src/components/AuthGate.tsx#L167): distinguish 401/403 from outages; offer bounded retries. |
| **UI02 — Body download escapes request timeout** | Screen can wait indefinitely | [api.ts:23](frontend/src/lib/api.ts#L23): deadline/cancellation covers response body too. |
| **PY01 — Scans credit the wrong employee** | Incorrect payroll | [scan/page.tsx:896](frontend/src/app/(app)/payroll/scan/page.tsx#L896): process badge, work and manual-selection events in order. |
| **PERF01 — Package list repeats DB queries per row** | Slow listings and wasted DB capacity | [packages.py:489](backend/app/api/routes/packages.py#L489): batch context/model reads. **50 packages: 152 → 5 SELECTs.** |
| **AT02 — Partial attendance download advances checkpoint** | Missing clock-in/out events | [connector:403](connectors/hikvision_attendance/read_only_connector.py#L403): require complete pagination before upload/checkpoint. Commit `137637f`. |
| **SEC02 — User deletion rewrites audit actors** | Broken history/hash verification | [admin.py:437](backend/app/api/routes/admin.py#L437): reject deletion with 409; deactivate instead. Concurrent insert rolls cleanup back. Commit `5b157d0`. |
| **API06 — Profile name/email grants pricing access** | Unauthorized price viewing/editing | [price_calculation.py:29](backend/app/services/price_calculation.py#L29), [frontend:60](frontend/src/lib/priceCalculationRequests.ts#L60): require explicit permission. Existing name-authorized staff need a deliberate grant. Commit `d89059e`. |
| **PERF41 — Eco history queries each dispatch's rolls** | Slow history pages | [eco_transfers.py:199](backend/app/api/routes/eco_transfers.py#L199): fetch page rolls together; omit unused snapshot. **50 dispatches: 54 → 5 SELECTs.** Commit `732b65d`. |
| **SEC07 — Utilization exposes another factory's line** | Factory workload disclosure | [production_extra.py:475](backend/app/api/routes/production_extra.py#L475): enforce the selected-factory guard before reading workload. Commit `40c681e`; **46 scope/assignment/workspace tests passed**. No query optimization claimed. |
| **SEC01 — Legacy scoped grants bypass restrictions** | Unauthorized factory/admin access | [admin.py:372](backend/app/api/routes/admin.py#L372): validate changed factory grants and role assignment. Commit `6458d9c`; **50 tests passed**. Existing grants are not automatically revoked. |
| **SEC07 — Linked passport GET ignores factory** | Another factory's cutting data leaks | [cutting_passports.py:449](backend/app/api/routes/cutting_passports.py#L449): check linked order access before serialization. Commit `c855a27`; **35 tests passed**. Unlinked manual records keep their existing policy. |
| **DB04 — Blank installation crashes at migration 0039** | Buyer cannot install | [0001_initial.py:20](backend/alembic/versions/0001_initial.py#L20): frozen historical schema, not current ORM metadata. Commit `1f3e20a`; **13 lightweight + 2 PostgreSQL tests passed**. Fresh upgrade to 0131, safe rerun, existing row preserved. |
| **ST05 — Returns deducted from two issue groups** | Incorrect allowance; valid returns rejected | [inventory service:1245](backend/app/services/inventory.py#L1245): merge linked stock/manual issues before subtracting returns. Commit `b2c126a`; **23 tests passed**. Concurrent returns are covered below. |

| **AT03 — Roster failure blocks attendance events** | Missing clock-in/out records | [connector:711](connectors/hikvision_attendance/read_only_connector.py#L711): isolate stages; retain failure reporting and valid checkpoints. Commit `50f685b`; **43 connector tests passed**. |
| **ST06 — Concurrent returns exceed issued quantity** | Inventory overcredited | [inventory service:1135](backend/app/services/inventory.py#L1135): order-scoped lock before replay/check/write. Commit `712ccf1`; **9 PostgreSQL + 11 SQLite tests passed**. Generic movement writers remain outside this guard. |
| **WF09 — Disposal decisions repeat/reopen stock** | Completed disposal becomes mutable | [waste.py:109](backend/app/api/routes/waste.py#L109): lock parent, enforce transitions, preserve safe rejection. Commit `2ed4150`; **68 tests passed**, including 4 PostgreSQL races. |
| **PERF07 — Payroll labels resolve every order separately** | Small pages slow with history | [payroll.py:2519](backend/app/api/routes/payroll.py#L2519): batch shared reference resolution. Commit `6f5ee2e`; **86 tests passed**. 50 global groups: **156 → 9 SELECTs**. |
| **API01 — Task creator bypasses assignment permissions** | Unauthorized reassignment | [tasks.py:185](backend/app/api/routes/tasks.py#L185): creator edit rights no longer imply manager rights. Commit `a77de07`; **50 tests passed**. |
| **API03 — Settings PATCH resets omitted fields / returns 500** | Settings lost; invalid input crashes | [settings.py:73](backend/app/api/routes/settings.py#L73): merge validated fields under a section lock; malformed input returns 422. Commit `68d9257`; **18 SQLite + 4 PostgreSQL tests passed**, including real logo upload. |

## Evidence

- **Ledger correction:** payroll batching `538ff66` belongs to PERF05, not PY03. Caller-supplied payable authorization remains open; the corrected mapping does not increase the fixed count.
- **CI wiring:** PostgreSQL selection includes administrator membership races. Corrected YAML indentation that would otherwise execute three test-file paths as shell commands. Workflow parsed locally; remote final-revision success is not yet claimed.

- **Latest batch:** SEC06 tested real PostgreSQL concurrent deletes and concurrent audit insertion; disposable clusters stopped. WF10 tests assert no commit/dirty ORM state, unchanged historical totals, authorization and filters. Neither proves every role mutation or accounting report correct.

- **Cycle 3 browser API:** 18 scenarios passed: factory boundaries, unchanged authorized payloads, forbidden grants and allowed scoped grant. [Results](docs/audit-evidence/cycle3-browser-results.json). Frontend launch was policy-blocked; no cycle-3 visual UI proof is claimed.
- **CI (`738daad`): all jobs passed.** Backend **1,314 passed / 24 opt-in PostgreSQL skipped**; PostgreSQL runs separately. The earlier configuration-dependent MCP test failure is corrected. Later commits need their own full rerun.
- **Cycle 2:** attendance connector **30 passed**; audit/admin **54 passed** plus **1 PostgreSQL race passed**; pricing authorization/workflow **40 passed**; Eco suites **15 passed**. Five frontend stabilization scripts, ESLint, strict TypeScript and pinned Ruff passed. These are targeted results, not a new full-suite total.
- **Cycle 2 browser:** same-session rename stayed forbidden; explicit pricing grant worked. Delete showed 409 guidance; deactivation rejected the old session. Eco history rendered 3 dispatches/6 rolls on desktop/mobile. No JavaScript page errors; expected denial responses and restricted-dashboard 403 console messages remain. [Results/screenshots](docs/audit-evidence/cycle2-results.json).
- **CI for first-batch commit `3881177`:** backend, frontend and PostgreSQL jobs passed. Later changes require their own CI run.
- **API coverage:** [510-route ledger](docs/api_test_coverage.json): **388 observed, 377 with success, 222 with rejection, 122 unobserved** in that CI run. Categories overlap. Hits are not correctness or complexity proof; final-revision coverage remains required.
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

### Friend's review — not an identical audit

- **New confirmed source findings:** S22 → SEC11 is fixed/tested above. S14 → UI05 (legacy KPI sums stage outputs) remains open.
- **Partial infrastructure fix:** S17 pool variables are now honored (`cc7ffdf`; 9 construction/validation tests, no live connection). OPS02 stays open: total connection budget across workers/slots still needs verification. Attendance upload memory, file/object scope and additional factory endpoints need targeted checks.
- **Review corrections completed:** payroll duplicate creation/audit counts and residual reference N+1 fixed in `538ff66`; ambiguity, retries and factory-denial regressions passed. This does not prove every payroll endpoint is optimized.
- **API02 partial:** task command validation now rejects bad states, dates, nulls, oversized/blank names and out-of-range integer references (`22593e7`, `c56a7f1`; 56 tests). Unrelated edits to old incomplete references still work. Reference target existence/access is not yet enforced; API02 remains open.
- **WF08 partial:** waste-sale API locks remaining capacity, rejects invalid input and supports user/record-scoped retry keys (`6cb2d3a`; 27 focused + 3 real PostgreSQL tests). Fractional-weight totals preserve PostgreSQL cent rounding. UI still lacks retained keys/remaining-balance handling; unkeyed retries remain ambiguous. Historical sold rows and finance valuation policy are unchanged.
- **ST09 partial:** already-damaged packages cannot be reserved (`9e336ce`; API regression and 3 PostgreSQL reserve races passed). Marking an existing reservation damaged still needs explicit quarantine policy and serialized transitions; not counted as fully fixed.
- **Overlap:** audit-chain races, invoice duplication, raw PATCH fields, image/event-loop work, SQLite rate-store blocking, index candidates and restore gaps already appear here.
- **Stale/qualified:** S32's SQL typo is absent in this checkout. SEC04 revocation and API06 name grants are fixed, not file-object policy in general. Management dashboard labels already distinguish its counters. Unindexed/nullable foreign keys alone do not prove bugs or explain N+1 query counts. The friend's summary has no runtime reproductions or commit hash; its September 12 date references a September 15 schema.

- **Inventory:** batchless reservations are not fully enforced by every batch-specific issue/allocation path. Old stock discrepancies are not repaired. Partial batch transfers reject with 409; splitting batches is a separate workflow.
- **Duplicates:** receipts need the same saved key. Different operators/keys can still represent the same physical delivery. Finance deduplication does not cover every 1C/workflow entry point.
- **Recovery:** receipts require browser storage and Web Locks. Uncertain requests that later lose access/conflict retain evidence and need reconciliation; do not clear storage blindly.
- **Security:** audit-chain concurrency and remaining cross-factory endpoints are not fixed. Account deletion now preserves history; already damaged history is not repaired. Signed sales-file URLs retain their existing expiry-based policy.
- **DB08 — Schema drift:** fresh migrations work, but ORM-only test schemas are not identical. [Reviewed comparison](docs/audit-evidence/fresh-migration-schema-drift.json) keeps **30 unresolved drift entries**, plus intentional/default-representation differences. Align contracts deliberately; do not delete legacy tables automatically.
- **Readiness:** other slow endpoints, full workflow/load tests and backup-restore proof still need work. Other pre-existing lock-order risks remain. **Not a production-readiness sign-off.**

Recorded production application code matches the base; live servers/manifests were intentionally not queried. Revalidate deployment state before any release.
