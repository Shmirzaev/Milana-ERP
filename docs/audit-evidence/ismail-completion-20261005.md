# Ismail bug completion audit

Reviewed on 2026-10-05 against `origin/clone_main` at `42284682`. This report covers Ismail's remaining implementation tasks and the three defects found during his earlier review. Four partial tasks now have implementations and local regression evidence. Two stock-policy decisions remain unanswered, so the overall work is not yet complete. Production has not been changed.

The combined changes are prepared in [draft PR 279](https://github.com/Shmirzaev/Milana-ERP/pull/279). Review means implemented on the proposal branch; Done requires review, merge to `clone_main` and passing regressions. Deployment is recorded separately.

## Implementation results

| Task or finding | Result | Evidence and limits |
| --- | --- | --- |
| DB05 migration preview | Review | Upgrade classification excludes downgrade SQL. Unsupported dynamic SQL, grants, repairs, DDL and unknown helper calls are rejected before database access. The supported 0055 adapter retains predecessor gating and a PostgreSQL READ ONLY transaction. Historical destructive or permission migrations are not rerun. |
| DB06 duplicate catalog objects | Review | Forward revision `0138_ismail_schema_contract` removes two redundant unique indexes and five equivalent FKs only after exact PostgreSQL catalog checks. A differing predicate or FK action causes refusal before any change. Covering constraints remain. Live cleanup still requires D2 approval and a verified backup. |
| DB08 migrated schema contract | Review | ORM fields, defaults, nullability and named constraints now match the shipped contracts; the forward revision creates nine declared HR indexes. Exactly 23 baseline differences were removed and retained verbatim as evidence: 21 DB08 entries and two DB06 unique-constraint entries. The remaining 94 normalized differences are explicit accepted contracts; global ORM parity is not claimed. |
| PERF23 pricing list | Review | Default reads are capped at 50 with a descending ID cursor. All five department pages provide localized Load more and preserve the array response. Previously loaded rows survive a failed page and the same page can be retried. Existing asset preloading and visibility/offline polling remain. |
| PERF35-PURCHASING review finding | Review | Purchasing reads the paginated response correctly and uses a server-filtered receivable total, counting each order once even with several outstanding lines. |
| Receiving recovery loop | Review | A guarded functional page increment loads the page containing a saved receipt without continuously increasing page count. Original receipt identity and retry behavior remain. |
| RES-PLAN-ARCHIVE D4a | Review | Archived batches are excluded from planning candidates. Existing pinned reservation ledger balances remain visible and are not rewritten. |
| ST11 mixed reservation capacity | Partial | Common batch-before-item locks already exist. An item-only claim and a batch claim can still overcommit the same stock because batch availability does not subtract item-only claims. D6 must select the capacity rule before that formula changes. |
| RES-PLAN-ARCHIVE D4b | Blocked | QC eligibility still retains its existing rule. The owner must decide whether pending stock remains eligible or only passed stock can be offered. |

## Regression evidence

- The affected backend run passed 158 tests covering schema bootstrap, preflight, pricing workflows, package and legacy finished-goods contracts, sewing quantities and catalog behavior. Three additional safety cases were added afterward; the final schema/preflight run passed all 51 tests, including those cases. Runs overlap and must not be added together as a unique-test total.
- Real PostgreSQL 17.11 tests upgraded the entire migration chain, checked the exact drift baseline, preserved synthetic business rows, reran the forward revision, downgraded and upgraded again. A preexisting HR index survives rollback; only indexes owned by the new revision are removed.
- The read-only catalog audit after upgrade reported all nine HR indexes present, seven redundant objects absent and no equivalent duplicate candidates. This describes the disposable QA schema, not production.
- The combined-branch purchasing, planner, stock-concurrency and settings suite passed 56 tests with PostgreSQL enabled.
- All five pricing pages passed browser checks for older rows, failed-page retry without skipping cursors, preserved existing rows, hidden/offline polling pause and online resume. No page errors occurred. Purchasing browser checks also passed: the server total displayed 61, saved page-two receipts loaded, HTTP 500 recovery survived reload, and retries reused the exact receipt key.
- Backend Ruff and whitespace checks passed. The final Next.js production build compiled all 91 routes; workflow contracts, normal and strict TypeScript, and changed-file lint passed. Full ESLint previously reported zero errors and five inherited warnings. GitHub checks remain pending until publication.

Local browser traffic is mocked and restricted to loopback. This verifies rendering, paging, recovery and polling behavior; it does not establish production latency or live database state. Mandatory PostgreSQL regressions are added to CI so the database-dependent tests cannot silently remain skipped.

## Decisions still required

1. **D6 and ST11:** Recommended: item-only and batch reservations share capacity and reject overbooking. The alternatives are deliberately independent pools or rejection of overlapping scopes. The chosen rule needs sequential, same-request and two-connection PostgreSQL regressions, while retaining batch-before-item lock order and consumed/released claim semantics.
2. **D4b and QC:** Recommended: allow `pending` and `passed`, exclude `failed`, `rejected` and `hold`. Requiring only `passed` would make default newly received stock ineligible until QC approval. Archived exclusion remains independent of this decision. Historical reservation balances must remain visible without creating new eligible candidates.

These are the two pending questions presented to Ismail. Recommendations are not recorded as approved decisions.

## Production and migration limits

No deployment, live catalog cleanup, destructive migration, permission repair or production business-data write occurred. The deployment SSH key is unavailable in this environment. The last recorded active release is blue `20261003_071825`, application commit `d7d083def8bd190eff92b46562319e2735ce10cc`, with rollback green `20261003_065351` and schema `0135_usluga_paid_processes`. These are historical records, not a fresh production check.

Before applying 0138 in production, follow `DEPLOYMENT.md`: verify the exact active/rollback manifests and slots; inspect the catalog with the read-only audit; record affected objects, sizes, dependencies and lock impact; verify a PostgreSQL backup; obtain D2 approval for the concrete catalog changes; validate the full candidate migration chain and rollback; then stage and gate the inactive slot. This forward revision creates normal indexes, so production lock duration must be assessed using actual table sizes and an appropriate maintenance window.

The downgrade restores the canonical historical redundant definitions and removes only owned HR indexes. It is not a substitute for a database backup and does not recreate arbitrary manual customization. Strict catalog guards refuse mismatches so they can be reviewed separately.

## Review handoff

Worktree: `C:/Users/ismoi/OneDrive/Desktop/remote_work/milana_ERP/.codex-work/ismail-completion`. Local branch: `codex/ismail-completion`; proposal branch: `codex/ismail-review-fixes`; target: `clone_main`. Earlier fixes at `2d3ec8f9` are included in the combined history. The shared clone, other engineers' branches and preserved server PDF are untouched.

The task tracker remains authoritative. Four rows move from Partial to Review, not Done. Of Ismail's original 37 implementation rows, 31 are previously Done, five are Review and one is Partial. The additional RES-PLAN-ARCHIVE finding is Blocked only on D4b, with its archive half in review. ST11 and QC policy remain explicit pending work. This audit covers Ismail's scope and does not claim that the other engineers' open tasks or earlier global security risks are resolved.
