# Access-policy helper split — 3 November 2026

Dilmurod owns this approved RF-009 prerequisite; Ismail (`Ismoiljon1101`) reviews this PR at the user's explicit request. Base: current `origin/clone_main` `58bca5491e7759a18875656500588f37c3a418bd`. The main checkout was fast-forwarded without discarding untracked evidence; implementation uses isolated branch `codex/dilmurod-access-policy-split-20261103`.

`clone_main` advanced during verification to `1f60fe78` (Catalog PR #370). Its changes do not overlap the helper split files; local before/after/full evidence remains pinned to the exact `58bca549` candidate base. Combined merge/CI verification is separate and must be reconciled before landing.

## Scope and preserved contracts

Move `policy_for`, `denied_for`, and `apply_policy` unchanged from `models/user_access_service.py` into `models/identity/access_policy_service.py`. Their source segments, including annotations, expressions, order and wildcard/denial comments, match byte-for-byte. The leaf imports only `core.permission_catalog.PERMISSION_KEYS`. Factory scope imports it directly; user access explicitly re-exports the same three function objects. Existing consumers, contextual `permission_denied`/`access_configured` helpers, selected-factory behavior, grant checks and route signatures remain unchanged.

No permission, role, DTO, enum, schema, persistence, audit, transaction, session or deployment behavior changes. `users.access_policy`, role/extra permissions and factory values keep their existing representations and semantics. This does not extract RF-009 `create_user`, create `identity/access_service.py`, or complete IDN-01. Future shared grant checks remain above the lower context/policy helpers without reverse imports.

## Before/after parity

All existing test source files are unchanged. The merged #345 baseline is identical to its current branch and retains SHA-256 `e053b63125ffd67ad3f61ffedb06f35b7bf1634b19b722f19b771f1059f822c2`; the same 98 cases run on each database.

| Unchanged cases | Before | After |
| --- | --- | --- |
| Access/factory cases, SQLite | 224 passed, 0 failed/errors/skipped | 224 passed, 0 failed/errors/skipped |
| #345 creation baseline, SQLite | 98 passed, 0 failed/errors/skipped | 98 passed, 0 failed/errors/skipped |
| Access/factory cases, PostgreSQL | 224 passed, 0 failed/errors/skipped | 224 passed, 0 failed/errors/skipped |
| #345 creation baseline, PostgreSQL | 98 passed, 0 failed/errors/skipped | 98 passed, 0 failed/errors/skipped |

Each phase executes 420 default cases (#345 already covers both databases) and a separate 224-case PostgreSQL run: 644 distinct executions per phase, 322 per database. These are not additional cases to add to full-suite totals.

The access/factory selection covers `test_user_access_policy`, `test_factory_permission_scope`, `test_factory_scoped_permissions`, `test_scoped_permission_grants`, `test_work_order_factory_scope`, `test_admin_users`, `test_paid_operation_factory_scope`, `test_quality_check_factory_scope`, `test_bundle_receiving_factory_scope`, and `test_privileged_user_delete`.

The local PostgreSQL adapter changes fixture binding only: #322 creates the approved disposable PostgreSQL 17 instance; its identity-checked helper creates/drops one owned target. The existing SQLite-oriented cases run unchanged with PostgreSQL sessions and per-case outer rollback/per-session savepoints; every case checks its configured dialect. No concurrency claim is inferred from that adapter. #345 retains its own explicit independent database fixtures without this adapter. Catalog paths also require generated columns absent from metadata: the adapter applies the existing `0084_model_group_key` migration to its owned target before seeding. The initial incomplete-fixture attempt (220 passed, 4 undefined-column failures) is retained separately; application code and assertions were not changed to repair it.

## Import boundary and regression challenge

Five new checks pass: a cold process importing factory scope does not load user access; each historical helper export is the leaf's identical function object; static traversal includes function-local imports, proves the targeted graph acyclic, and restricts the leaf's application dependency to the permission catalog. The old graph had factory scope → user access → factory scope; the candidate has user access → factory scope → policy leaf → catalog and user access → policy leaf.

In a throwaway minimal source copy, restoring only factory scope's old import makes the cold-import and graph checks fail: 2 expected failures / 3 passes / 0 skips. The candidate is untouched. The copy is discarded after recording output. Independent read-only Codex review by `/root/acceptance_people_recipe` found no source/focused-evidence blockers; final read-only review confirmed the result classification and found no new source/evidence blockers; full-suite results are recorded below. Ten additional bounded fresh-process checks pass across both import orders.

## Full suite and remaining gates

The first unmodified #322 full phase recorded **5,791 passed / 1 failed / 4 setup errors / 0 skipped**, plus 36 passing subtests. Required PostgreSQL groups and the 17-case supplement passed. The four SEC09 gateway setup errors explicitly required the absent HAProxy test binary; the failure was S06 `test_concurrent_stock_adjustments[batch_delta]`, `AttributeError: 'str' object has no attribute 'value'`. All five non-passing outcomes and causes were reproduced on unchanged base `58bca549` in a separate fresh #322 instance.

Only the disposable test environment was then supplied with HAProxy; no tracked dependency, Dockerfile, runner, application or existing test assertion changed. The four unchanged SEC09 cases pass on both base and candidate (4/4 each, zero skips). One temporary base comparison initially omitted `deploy/slotctl.py`; that verification-copy omission was corrected, and the incomplete attempt is retained separately.

The final unmodified #322 `scripts/run_local_postgres_tests.py --inside` phase, with HAProxy present in a fresh runner-owned cluster, recorded **5,795 passed / 1 failed / 0 errors / 0 skipped**, plus 36 passing subtests, in 985.51 seconds. Runner exit1: **overall FAIL**. All 171 required PostgreSQL cases and the 17-case supplement passed; those are subsets of the full total. The sole failure is unchanged S06 `test_concurrent_stock_adjustments[batch_delta]`, whose direct call supplies a string to an enum-typed persistence helper. It reproduces on unchanged `58bca549`; no refactor regression was found and no S06 application/test fix is included.

Final raw JUnit: `.codex-work/postgres-results-a0347b3c/backend.xml`; final full log: `.codex-work/access-policy-evidence/full-suite-with-haproxy.log`. First-run and unchanged-base reports remain retained. Only the runner's own disposable containers/images were removed; existing acceptance/CRM services and volumes were preserved. Runtime and regression-test files are identical to code commit `7c934f10`; the closing evidence commit changes documentation only. PR: [#371](https://github.com/Shmirzaev/Milana-ERP/pull/371), reviewer Ismail requested.

Raw JSON/JUnit/logs, test-source hashes, helper-body parity and challenge reports remain local under `.codex-work/access-policy-evidence/` in the task worktree. No production/shared environment was accessed. Browser/operator acceptance is not recorded for this source-only prerequisite; no AI-verified, accepted, merged or deployed state is claimed. Previously documented active/rollback releases remain unchanged by this PR. Human review and RF-009 remain separate.
