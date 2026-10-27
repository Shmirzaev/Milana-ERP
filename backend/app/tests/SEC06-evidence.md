SEC06: ported active-membership NO KEY UPDATE locks from 74a2973 into both
membership PATCH and DELETE. Stable user ID order; populate_existing refreshes
cached membership state before checking the final-admin invariant. NO KEY UPDATE
serializes removals while remaining compatible with actor FK KEY SHARE locks.
Branch codex/sec06 from fresh clone_main.

Real PostgreSQL at localhost:5433/milana_test; isolated schema created/dropped by
fixture; public data unchanged. Environment: STABILIZATION_POSTGRES_URL.
Before: 3 failed, 3 passed in 12.82s. DELETE/DELETE both returned 204; mixed
PATCH/DELETE both removed their admins; old PATCH lock blocked actor KEY SHARE.
After: 6 passed in 9.89s. Concurrent DELETE/DELETE, PATCH/PATCH and PATCH/DELETE
preserve one active wildcard administrator, while actor KEY SHARE stays compatible.
Unset URL: all 6 tests skip cleanly (8.43s).
Full suite on normal SQLite (-n 4): 2173 passed, 52 skipped in 191.03s.
Ruff/diff checks passed. External fonts supplied macOS compatibility.
Logs: /private/tmp/sec06-{before,after,skip,suite}.log.
No merge, migration, production data change or deployment.
