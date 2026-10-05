# Ismail bug completion audit

Reviewed on 2026-10-05 and reconciled with `origin/clone_main` at `f61262dd`. All original Ismail implementation tasks have fix evidence, including the ST02 floor extension identified by the full owner audit; the additional QC/archive finding is also implemented. The completion request selects shared reservation capacity and pending/passed QC eligibility. No implementation remains waiting for another go-ahead. Review/merge and production application are recorded separately; this task has not changed production.

The combined changes are prepared in [PR 279](https://github.com/Shmirzaev/Milana-ERP/pull/279). Review means implemented on the proposal branch; Done requires review, merge to `clone_main` and passing regressions. Deployment is recorded separately.

The [full owner and team audit](team-owner-audit-20261005.md) supersedes the earlier all-done interpretation of ST02: item-only claims also need protection from outgoing movements. It records the reproduction, extension and all 37 task rows. Earlier CI counts below predate that extension.

## Implementation results

| Task or finding | Result | Evidence and limits |
| --- | --- | --- |
| DB05 migration preview | Review | Upgrade classification excludes downgrade SQL. Unsupported dynamic SQL, grants, repairs, DDL and unknown helper calls are rejected before database access. The supported 0055 adapter retains predecessor gating and a PostgreSQL READ ONLY transaction. Historical destructive or permission migrations are not rerun. |
| DB06 duplicate catalog objects | Review | Forward revision `0138_ismail_schema_contract` removes two redundant unique indexes and five equivalent FKs only after exact PostgreSQL catalog checks. A differing predicate or FK action causes refusal before any change. Covering constraints remain. Live cleanup still requires D2 approval and a verified backup. |
| DB08 migrated schema contract | Review | ORM fields, defaults, nullability and named constraints now match the shipped contracts; the forward revision creates nine declared HR indexes. Exactly 23 baseline differences were removed and retained verbatim as evidence: 21 DB08 entries and two DB06 unique-constraint entries. The remaining 94 normalized differences are explicit accepted contracts; global ORM parity is not claimed. |
| PERF23 pricing list | Review | Default reads are capped at 50 with a descending ID cursor. All five department pages provide localized Load more and preserve the array response. Previously loaded rows survive a failed page and the same page can be retried. Existing asset preloading and visibility/offline polling remain. |
| PERF35-PURCHASING review finding | Done on clone_main | Independently landed at `e79f0918`; latest code reconciled while preserving the true receivable total. Purchasing regressions passed after integration. |
| Receiving recovery loop | Review | A guarded functional page increment loads the page containing a saved receipt without continuously increasing page count. Original receipt identity and retry behavior remain. |
| RES-PLAN-ARCHIVE D4a | Review | Archived batches are excluded from planning candidates. Existing pinned reservation ledger balances remain visible and are not rewritten. |
| ST11 mixed reservation capacity | Review | Creation now caps reservations by global item capacity, warehouse capacity when scoped, and batch capacity when pinned. Shared batch-before-item locking is retained. This closes both mixed and warehouse-less overbooking without counting claims twice. Tests prove both sequential orders, ordered two-connection races, atomic payload rollback, exact-capacity success, warehouse independence and consumed/released arithmetic. |
| RES-PLAN-ARCHIVE D4b | Review | The candidate query allows pending/passed and excludes failed/rejected/hold. All five QC states are covered for pinned/unpinned requirements, retaining default pending compatibility and existing stock/claim ledgers. |

## Regression evidence

- The affected backend run passed 158 tests covering schema bootstrap, preflight, pricing workflows, package and legacy finished-goods contracts, sewing quantities and catalog behavior. Three additional safety cases were added afterward; the final schema/preflight run passed all 51 tests, including those cases. Runs overlap and must not be added together as a unique-test total.
- Real PostgreSQL 17.11 tests upgraded the entire migration chain, checked the exact drift baseline, preserved synthetic business rows, reran the forward revision, downgraded and upgraded again. A preexisting HR index survives rollback; only indexes owned by the new revision are removed.
- The read-only catalog audit after upgrade reported all nine HR indexes present, seven redundant objects absent and no equivalent duplicate candidates. This describes the disposable QA schema, not production.
- The combined-branch purchasing, planner, stock-concurrency and settings suite passed 56 tests with PostgreSQL enabled.
- All five pricing pages passed browser checks for older rows, failed-page retry without skipping cursors, preserved existing rows, hidden/offline polling pause and online resume. No page errors occurred. Purchasing browser checks also passed: the server total displayed 61, saved page-two receipts loaded, HTTP 500 recovery survived reload, and retries reused the exact receipt key.
- Backend Ruff and whitespace checks passed. The final Next.js production build compiled all 91 routes; workflow contracts, normal and strict TypeScript, and changed-file lint passed. GitHub frontend validation passed with zero errors and five inherited lint warnings.
- First full GitHub backend run: 2,752 passed, 196 skipped and one failed because the shipment test required 0137 to remain the newest migration. The test now checks one head, 0137's real predecessor and its presence in the head's ancestry, allowing valid forward revisions. Both corrected local migration checks passed.
- **Earlier source validation, before the stock changes and latest branch integration, passed on `ee914002fa6ac8886c2154a9ba3f0c10a69eda84`:** [PR validation 37247388527](https://github.com/Shmirzaev/Milana-ERP/actions/runs/37247388527) and [push validation 37247385606](https://github.com/Shmirzaev/Milana-ERP/actions/runs/37247385606) both passed backend and frontend jobs. The full backend suite passed 2,753 tests with 196 optional tests skipped; the dedicated PostgreSQL schema/reservation gate passed 95 tests; deployment observation passed 11 tests. Migration/concurrency/model-numbering gates also passed. These are separate overlapping runs, not a summed unique-test count. Release jobs were skipped; passing validation did not deploy anything. Later stock changes and integration require a new full CI run; the earlier result is historical evidence.

Local browser traffic is mocked and restricted to loopback. This verifies rendering, paging, recovery and polling behavior; it does not establish production latency or live database state. Mandatory PostgreSQL regressions are added to CI so the database-dependent tests cannot silently remain skipped.

## Stock completion evidence

- Before the fix, the new reproduction subset reported five failures and two passing controls on PostgreSQL 17.11. It demonstrated item-first mixed overbooking, warehouse capacity bypass and global warehouse-less claims being ignored by scoped reservations.
- After the fix, all 122 stock/commercial regressions passed with PostgreSQL enabled and no skips. This includes 20 reservation overclaim/locking tests, all five QC states for both pinned and unpinned requirements, planner read-growth/FIFO/coverage invariants, adjacent reservation and stock-movement checks, QC validation and merged purchasing checks.
- Normal/strict frontend TypeScript and purchasing-page lint passed after resolving the concurrent purchasing change. Backend Ruff and whitespace checks passed. The planner still batches stock/claim reads; the QC predicate introduces no per-row query loop.
- D6 shared capacity and D4b pending/passed eligibility are implemented under the owner's instruction to finish. There is no pending stock-policy question. D1 historical profit/currency and D2 production catalog application remain separate follow-ups.
- Full GitHub backend/frontend, PostgreSQL and migration/concurrency checks run on the updated proposal. [PR 279](https://github.com/Shmirzaev/Milana-ERP/pull/279) provides the current head's results. Earlier CI counts above must not be mistaken for the new stock changes' final CI result.

## Production and migration limits

No deployment, live catalog cleanup, destructive migration, permission repair or production business-data write occurred. The deployment SSH key is unavailable in this environment. The latest shared deployment record lists active blue `20261005_070406`, application commit `25a7dd1cff77b4b180181da1db0f8780f1c7675e`, rollback green `20261005_063643` and schema `0137_perf34_shipment_indexes`. These records were read from the shared context and deployment baseline; they were not independently verified live by this task.

Ismail's operations follow-ups OPS02 (live worker/pool connection budget) and OPS03 (shared infrastructure/workload verification) remain unverified because they require production access. FN08's historical profit/currency decision remains with Shavkat under D1; it is outside the 37 implementation rows counted here.

Before applying 0138 in production, follow `DEPLOYMENT.md`: verify the exact active/rollback manifests and slots; inspect the catalog with the read-only audit; record affected objects, sizes, dependencies and lock impact; verify a PostgreSQL backup; obtain D2 approval for the concrete catalog changes; validate the full candidate migration chain and rollback; then stage and gate the inactive slot. This forward revision creates normal indexes, so production lock duration must be assessed using actual table sizes and an appropriate maintenance window.

The downgrade restores the canonical historical redundant definitions and removes only owned HR indexes. It is not a substitute for a database backup and does not recreate arbitrary manual customization. Strict catalog guards refuse mismatches so they can be reviewed separately.

## Review handoff

Worktree: `C:/Users/ismoi/OneDrive/Desktop/remote_work/milana_ERP/.codex-work/ismail-completion`. Local branch: `codex/ismail-completion`; proposal branch: `codex/ismail-review-fixes`; target: `clone_main`. Earlier fixes at `2d3ec8f9` are included in the combined history. The shared clone, other engineers' branches and preserved server PDF are untouched.

The task tracker remains authoritative. Of Ismail's original 37 implementation rows, 31 remain Done on clone_main and six are Review after ST02 was reopened and fixed in the proposal; the additional RES-PLAN-ARCHIVE finding is also Review. No Ismail implementation row remains Open, Partial or Blocked. Review does not claim a merge or deployment. This audit covers Ismail's scope and does not claim that the other engineers' open tasks or earlier global security risks are resolved.
