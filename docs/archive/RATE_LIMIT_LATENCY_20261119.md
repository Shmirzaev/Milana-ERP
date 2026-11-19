# Shared-counter latency repair — 19 November 2026

User scope: find the slowdown, fix it and deploy the latest ERP change.
Status: counter-only candidate was activated and recovered; a second, narrow
response-encoding repair is ready for immutable CI. Production remains030500.

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
- Exact counter-fix CI44471392308 passed all required validation/security/image jobs.
- Exact image default-command owned-PG0159 cold start, two workers, child replacement,
  full restart and counter persistence1/2/3/4 passed; the isolated ledger stayed0.

## Counter candidate activation and recovery

Runtime commitac794fd370eb3e08b92d29c2953d4be9a41e7725 was pushed and integrated
into clone_main. Exact release20261119_062017_44471392308_1, manifest669ea3a71cc677d22367b2b877bd69734b3e8e0cf5aacdb99414b6335f7ed739,
passed frozen seven-workflow facts and initial core/search performance gates.
Backend activated06:40:11UTC and frontend06:40:39UTC. All public before/after
budgets passed; runtime identity, workers, counter writes, DB headroom and four
health endpoints passed. An added internal active-versus-idle postflight comparison
failed stock p9545.28→68.40ms and model-groups84.24→99.38ms. Production recovered
backend06:46:59UTC, then frontend06:47:25UTC. The30-minute observer was interrupted
after about360seconds/13rounds; it did not complete. Both hosts again serve030500.
The failed attempt and measurements remain intact; no retrospective PASS.

Verified backup auto_pre_20261119_062017_44471392308_1.dump:132,128,579bytes,
1,403restore objects, SHA25645e2c71b000304689644239c5e12d733690720c655901baa9023c469a4728e0e,
restore-list SHA2566aa558ad07a49e001d690d9318e189fdbcdb00fcfa2851da5ac75250324ea236,
mode0600 using pinned PostgreSQL16 client. Listing was verified; this latest dump
was not fully restored. The original025033 dump was fully restored into an owned
RAM-backed local PostgreSQL clone; no production business data was written by QA.

## Second causal finding: event-loop response encoding

An exact full-image matched-heavy-load comparison retained101samples per8API
endpoints. Seven endpoints passed, but batches p95 failed57.52→210.72ms wall,
51.1→59.1ms server. All medians improved. This failed experiment is preserved,
not rerun or relabelled. Counter-only module replay under simpler equal API/asset
load had passed, but does not establish full-image heavy-load behavior.

On the restored read-only clone, instrumentation of the actual full requests
measured FastAPI jsonable_encoder for large process/inbox nested responses taking
70.87ms and100.50ms on MainThread. These synchronous, unmodelled route results
were returned to FastAPI for recursive encoding on the ASGI loop, delaying other
requests on that worker. The narrow correction registers three existing sync
reads through the same jsonable_encoder and JSONResponse inside the existing
AnyIO request thread: department-orders inbox, legacy inbox and process tracking.
Original pure callables, signatures, dependencies, query/payload/permission rules
and registration order are retained. There is no model/schema/DTO/business change.
Instrumented new requests moved encoding to AnyIO worker thread (47.29/97.49ms)
and retained exact body hashes on all changed read responses.

Validation:28initial adjacent tests, then131broader cases passed (including5new
serialization cases and8counter cases); Ruff passes. New tests prove exact default
FastAPI bytes/headers for nested datetime/Decimal/enum/None/Unicode, paged and
unpaged payloads, real3route wrappers/signatures, encoder+renderer on the request
thread and /health responsiveness while an encoder is explicitly blocked.
Independent AI source review /root/review_ceo_rollout found no blocker. Exact-image
CI/security, HTTP/OpenAPI/auth, frozen facts, fair heavy load and prescribed
production gates remain required before any new activation.

Heavy background sewing option/report hashes were unstable in both OLD and FIXED
apps. Separate18request checks on the unchanged restored clone produced14different
hashes within each app; structured differences are operation label choices only
(107/109field paths), not evidence of counter-source corruption. No normalization
was applied to erase the failed strict experiment. The unmodified report's
nondeterministic option-label selection remains a documented adjacent risk.

## Prospective deployment protocol clarification

Independent review read DEPLOYMENT.md and confirmed: compare active/candidate
BEFORE activation, then compare PUBLIC before/after and repeat closing checks.
An additional post-cutover internal active-versus-idle ratio is confounded because
only one slot serves live users; it is not an explicitly prescribed extra gate.
The earlier failure and recovery remain recorded. A new attempt must prospectively
pin this interpretation, fresh10%median/15%p95/15%payload gates and exact rows,
frozen seven-workflow facts, full source/runtime identity, explicit SQLite write
proof, four health endpoints and30minute observation. No threshold waiver or
retry-until-green is authorized. The counter-only attempt2 journal was prepared
but never activated; supersede it explicitly when staging the corrected source.

No production schema, account, CEO assignment, snapshot or business record was
created/changed by deployment QA. Schema0159 and CEO unassigned/snapshots0 remain.
Unrelated host services were not changed. Automatic deployment stays disabled.
The dirty legacy checkout remains untouched. Owner's deployment request and prior
Ignore and deploy are recorded; no separate QA-master approval is fabricated.

