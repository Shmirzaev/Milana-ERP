# Shared-counter latency repair — 19 November 2026

User scope: find the slowdown, fix it and deploy the latest ERP change.
Status: candidate under validation; no new production activation yet.

## Source and ownership

Worktree: `C:\ERP\.codex-work\fix-latency-20261119`.
Branch: `codex/fix-latency-20261119`. Runtime owner: Dilmurod;
repository reviewer: Mirshoir. Codex implements this narrow infrastructure fix;
independent AI review is `/root/review_ceo_rollout`, with no fabricated human QA.

Both live hosts were freshly verified on blue `20261119_030500`, manifest
`b09fc748df6e4da0d00dbabbdd6a38a6b8ce2c38a8c2815cd960eb9e63902fbd`, schema0159.
GitHub clone_main still named the earlier baseline. The clean task worktree began
at verified origin/main, then reconciled the previously reviewed347272878 source
and recovery record b30e5eeb0 without runtime changes. Its only CI conflict retained
the complete, tested clone_main recipe. Compatibility437523dbd is now an ancestor;
its migration files already match the candidate exactly. Added compatibility QA
workflow/script are retained as source history. The dirty legacy checkout remains
untouched. `deploy/production-base.json` records the verified actual recovery.

## Findings and causal limits

Failed epoch traffic:7,684 total requests;4,325 API requests;2,177 model/storage
assets;28 barcode requests. That volume does not support barcode authentication
as the primary cause. Active candidate and idle recovery had different real load;
the previous failed comparison establishes a failed gate, not exclusive source
causation. No batches-specific query change was found. The same backend VM hosts
unrelated analytics/background services; a fresh sample had about45% CPU pressure,
analytics around155% CPU and another service around39% CPU. Those services were
observed only, not changed or stopped. No business payloads or credentials are
included in evidence summaries.

Confirmed defect: SQLite connection context managers do not close connections.
Original source leaked until cyclic GC:300 increments with GC paused increased
Linux descriptors from4 to605; explicit collection returned to4. The limiter runs
before every non-exempt request, including model assets, and serializes local
threads through an RLock. A bounded12-thread/1,200-increment test measured original
p9520.70ms and0.897s total; a diagnostic reused connection measured p951.22ms and
0.477s total. This is an isolated store test, not a full-API improvement claim.

TTL/readiness previously ran DELETE before SELECT, unnecessarily competing for
SQLite's single writer. A held unrelated writer reproduced that contention.
No exclusive cause of the earlier238ms API p95 has yet been established.

## Narrow repair and preserved behavior

Reuse one SQLite connection per worker store under the existing RLock. Configure
WAL once, retain FULL synchronous durability, BEGIN IMMEDIATE, fixed windows,
per-key expiry, namespace separation and the existing fail-open global/fail-closed
credential policy. A file-identity check avoids using a renamed/orphaned database.
Explicit close supports disposable stores. TTL is a pure SELECT with an expiry
predicate; mutating operations still reclaim expired records. There is no enum,
DTO, PostgreSQL-schema, permission, worker-count, DB-pool or business-rule change.

Callers traced: global middleware, authentication lockouts and readiness, all via
get_shared_counter_store. The actual Uvicorn runtime uses spawn and creates its
store within each worker. No connection is shared between processes. Other
backend/feature source remains the previously identified Ismoiljon candidate.

## Evidence and remaining gates

- Ruff on the two changed Python files and diff whitespace check pass.
- Initial shared-store/CEO/security regressions:45 passed.
- Adjacent outage/rate-limit/readiness suite after fixing file replacement:
  73 passed, one explicitly optional case skipped. Initial unconfigured real-PG
  readiness cases correctly refused execution; hosted approved-PG CI is required.
- Separate-process increments, replacement-process persistence, threaded exact
  counts, bounded descriptors with GC paused, WAL read under another writer and
  injected transaction rollback/recovery pass. Exact expiry boundary is included.
- Independent AI review found no correctness blocker for the actual spawn runtime;
  it requested the cross-process, rollback and boundary checks above.
- Full immutable CI/security, owned-PG runtime restart, equal-load application
  comparison, actual browser attempt, both-host source/runtime checks, deployment
  gate, timed observation and closing checks remain required. No pass is inferred.

No production data, accounts, files, schema or routing were changed for this fix.
Production stays on healthy recovery030500 until promotion gates pass. Existing
migration0159 and unassigned CEO role remain as previously recorded.
