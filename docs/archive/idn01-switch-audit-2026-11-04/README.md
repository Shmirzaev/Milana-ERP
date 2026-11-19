# Factory-switch audit evidence — 4 November 2026

Candidate: #387, runtime commit `d19e6c91`, stacked on #386 `da9cdf79`. Dilmurod implemented the decided audit change; Ismail is requested to review it. No production or shared environment was used.

## Automated checks

- Fail-first on the unchanged #386 service: **0 passed, 4 failed, 0 errors, 0 skipped**. Both route aliases on both databases failed only because the expected audit row was absent.
- After implementation: **36 passed, 0 failed, 0 errors, 0 skipped** for the updated #382 switch suite on SQLite and disposable PostgreSQL. This checks actor, MIL/ECO before and after, `created_at`, hash, a single audit INSERT, refusal, same-factory selection, cookie/bearer behavior and the prior old-token rule.
- Adjacent auth, policy, credential cutoff, reset and audit-chain tests: **85 passed, 0 failed, 0 errors, 0 skipped**. Ruff on changed Python files, compilation and `git diff --check` passed.
- Full #322 run: **6,046 passed, 2 failed, 0 skipped**; required and supplemental PostgreSQL gates passed. The failed Sales/PERF26 package-row assertion (27 vs 18) and Inventory/S06 string-versus-enum test are the same two failures recorded on the #386 base. The run used a Git-ignored, passive PERF06 worker-drain adapter: two pending AnyIO workers exited before the original fixture guard. No test assertion or required gate was disabled.

## Isolated persisted readback

The [prewritten stress plan](stress-plan.md) and [password-free raw readback](readback-stress.json) cover a fresh localhost PostgreSQL copy of the candidate. The selected factory came from `/api/auth/me`; `users.factory_code` remained the primary assignment, MIL.

| Request | New switch-audit rows | Stored result |
| --- | --- | --- |
| MIL → ECO | 1 | Actor, MIL, ECO, timestamp and hash present |
| ECO → MIL | 1 | Second row links to the first hash |
| MIL → MIL | 0 | Audit count unchanged |
| MIL-only account → ECO | 0, HTTP 403 | Selected factory and stored grants unchanged |

The bounded two-request burst took **0.033 s**; both responses were 200 in **0.019 s** and **0.015 s**, below the prewritten 5 s per-request and 10 s stop limits. It added exactly two complete MIL→ECO rows, with no changed user assignment or grants. The existing hash-chain verifier reported **4 rows checked, OK**. An authorized test admin also read all four rows through `GET /api/audit-logs?action=switch_factory`; each included actor, old/new factory, timestamp and hash. The denied request ran before the burst rather than after it as listed in the plan; volume and limits were unchanged.

The Admin Audit Logs page was **not visually inspected**, and no human or independent AI approval is claimed. Already-written audit rows remain if this code is rolled back. The two unrelated full-suite failures remain blockers to a green combined gate.
