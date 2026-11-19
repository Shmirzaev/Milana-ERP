# ERP latency repair — 19 November 2026

User scope: find the slowdown, fix it and deploy the latest ERP change.
Status at 08:09 UTC: required closing public p95 failed after healthy30minute
observation. Both hosts recovered to030500; corrected e4 candidate is held green.
Further causal diagnosis and successful deployment remain required. Historical
activation/observing checkpoints below are preserved; see final recovery section.

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
untouched. At that initial checkpoint, `deploy/production-base.json` recorded the
verified recovery; the final release section records the current live baseline.

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

## Corrected immutable release: production activation and observation

Status at 07:41 UTC: deployed on both hosts; required 30-minute observation is
in progress, with closing checks pending. Runtime source is e4d9b5a0f57d63c811d93672c4eee3fc5fddf0b9.
Worktree C:\ERP\.codex-work\fix-latency-20261119, branch codex/fix-latency-20261119;
runtime source pushed and fast-forward integrated into origin/clone_main.
The legacy checkout was preserved. Follow-up context/baseline commits are
documentation only and are not the immutable runtime source commit.

Release 20261119_070624_44477044420_1 has manifest SHA256
869a496bae0ee68c72f7915736c5c61764166089b003abb723cd18868d66401e.
Source archive: 6,791,517 bytes, SHA256
0b54bc609860b35e96b93b4f683c6b66ce63f682e335b211165beabe32f92c54.
Backend image ghcr.io/shmirzaev/milana-erp-backend@sha256:35eb250a2cc9aa9676099dc26ee62cba1ad6a1967b240a7690e6c9cd8b6a99cb.
Frontend image ghcr.io/shmirzaev/milana-erp-frontend@sha256:4766e2d970a38d93a78b7af9fd63e625eef2b06a05bdc3a5fd39bd90a9c3cb3e.
Exact source CI44477044420 and integration CI44477906469 passed, including backend,
PostgreSQL, frontend production/contracts, image security and immutable release.
Backend switched 07:35:05.646243 UTC; frontend switched 07:35:36.362998 UTC.
The observer started 07:35:41.161543 UTC; earliest completion 08:05:41.161543 UTC.
No completion is claimed before its actual receipt and separate closing gates.

Rollback remains running blue release 20261119_030500, commit
437523dbd2d558a76f1308d8aa2215aee64b86bb, manifest
b09fc748df6e4da0d00dbabbdd6a38a6b8ce2c38a8c2815cd960eb9e63902fbd.
Backend image sha256:68fd39736f517de5178734c100386b95efb423edf0a1847bdc19395e9bd6ce0e;
frontend image sha256:7fce0d58189fd31e3e2c383c78a9bef8d4c128d544c539ba318009719de1646c.
Schema remains 0159_ceo_balance_snapshots, fingerprint
c1830a0f72eddbcf82a76da559bf04da16477ffce29625574a9d28e6e450ca9f.
No downgrade is part of rollback. CEO assignments and CEO snapshots remain zero.
The old application lacks the CEO authorization guard: keep CEO unassigned; if
CEO accounts are activated later, disable/revoke them before rollback. Foreground
model_options is /api/model-options, distinct from background sewing_options.

Pre-cutover backup:
 /opt/milana-erp/shared/backups/auto_pre_20261119_070624_44477044420_1.dump
132,158,445 bytes; 1,403 restore objects; mode0600; SHA256
2a70b25ebdee988a0c3bee9a4e3ef582c70530e40d62b9a1aa6f347048d6aef8.
Restore-list SHA256380d666b5e0c80928ac8110bdf6ad784c8888acdde32547ea3ddba06fb5819b9.
Pinned PostgreSQL16 client postgres@sha256:e013e867e712fec275706a6c51c966f0bb0c93cfa8f51000f85a15f9865a28cb.
Hash/list were verified; this latest dump was not fully restored. The earlier
025033 dump was fully restored into the owned local RAM PostgreSQL diagnostic clone.

## Final candidate controlled experiments and interpretation

The 201-round old437 versus exact e4 image heavy workload retained exact foreground
payload/row parity. All eight foreground medians improved, but sales wall p95
41.93→55.90 ms and production server p95 48.8→70.2 ms failed; two background sewing
option-label paths also failed strict parity. It remains FAIL, not a passing gate.

One independent-review-approved prospective negative control compared two copies
of the SAME exact e4 image with the same 201-round paired ABBA schedule, resources,
default two-worker command, private environment equivalence and fresh SQLite.
Protocol SHA256f304045ce106d0b3d620dbfaa7de4d7ae615f4830d6346801973dff1e946a6d8.
This A/A also FAILED: sales p95 43.17→112.56, material batches 52.32→193.68,
model options 54.71→78.84, model groups 189.99→235.66 and inventory batches
47.87→87.65 ms; reverse-direction stock 201.44→46.08 and global search
255.93→91.08 ms. Foreground hashes/rows remained exact; the same background labels
failed. No whitelist expansion or retry-until-green occurred. Independent reviewer
/root/review_ceo_rollout verified sample counts, digests and parity, and concluded
this extra diagnostic is inconclusive for source attribution under shared-host
contention/GC. Both FAIL records remain. Fresh prescribed production/public gates,
not a reclassification of failed experiments, governed activation.

Generation-2 GC pauses of 149–168 ms were measured in old and corrected workers,
mostly scanning approximately 670,026 startup-tracked objects with little collection.
A local startup-freeze prototype lacked sufficient matched benefit and lifecycle/
memory proof; it was rejected. No GC freeze/threshold/lifecycle change was committed
or deployed. Unrelated production analytics/background services were not altered.

Actual old437/new e4 HTTP bodies and auth/status were identical for the changed
process and department inbox routes, including paged/legacy/compact variants.
Three target OpenAPI schemas are identical. Full old437/new schema comparison
initially failed because the combined reviewed release adds /api/dashboard/ceo and
/api/packaging/reports/page; a structured comparison found zero changed common
paths or removals. Counter-only ac79 to e4 full OpenAPI is identical (537 paths,
SHA25632de7fb45140e86dee4012b47269fdd65791d960204686f52643aa49fb04239b).
The initial overly broad schema expectation failure remains in the raw evidence.

## Prescribed new production gates

Fresh frozen read-only snapshot matched all ordered facts: sales100, production747,
material batches1615, packages10688, cutting884 (existing scope), work orders3044,
shipments289. The read-only write challenge returned SQLSTATE25006.
101-pair initial wall p95: sales45.3979→42.1655, production50.2925→44.4988,
batches68.5467→69.6493 ms. All median/p95/payload/exact-row budgets passed.
31-pair initial search p95: global120.99→123.63, options50.31→46.53,
groups81.82→79.54, inventory batches60.79→56.57, stock37.82→35.57 ms; all passed.

Public before/after uses the same existing reader, fixed search terms, identity encoding,
three warmups and 21 measured requests per path. Budgets remain +10% median,
+15% p95, +15% payload bytes and exact rows:

| Public query | Before median / p95 ms | Immediate after median / p95 ms |
| --- | ---: | ---: |
| Global search | 233.469 / 729.074 | 230.155 / 236.974 |
| Model options | 160.926 / 206.814 | 158.530 / 169.613 |
| Model groups | 191.954 / 200.409 | 192.830 / 214.836 |
| Inventory batches | 166.418 / 172.310 | 167.068 / 173.086 |
| Stock | 153.460 / 169.040 | 150.196 / 157.566 |

All immediate public gates passed. A separate closing comparison against the same
original before baseline is still required after actual observation completion.
Immediate strict source/current/slot/proxy/image/default-command checks passed;
both workers per backend slot, zero restarts/OOM/counter warnings, separate-process
technical SQLite write persistence 1→2, valid HAProxy config, PostgreSQL37/100
connections, zero invalid indexes, unchanged schema and all four health endpoints.
At 07:37 UTC, new workers each held three SQLite FDs and ~335–340 MB RSS; the old
rollback workers held 20/8 SQLite FDs and ~1.7–1.9 GB RSS. This is an observed
snapshot, not proof of long-term RSS behavior.

Protected evidence on BOTH hosts:
 /opt/milana-erp/shared/deployment-evidence/20261119_070624_44477044420_1/
The before-cutover diagnostics ZIP is 501,197 bytes, SHA256
ae12e4338fa1906e65807ce3e30d468ffe3eab3c6c1e87b6875571a6347e9f66.
Replaced counter-only green logs and earlier failed journals are preserved.
Current root journals:
 /opt/milana-erp/runtime/manual-20261119_070624_44477044420_1.json
Local observer:
 %TEMP%/milana-latency-20261119/20261119_070624_44477044420_1-observation.json

QA used existing read-only production data and technical deployment counter keys.
No business records, users, CEO assignment or balance snapshots were created.
Automatic deployment remains disabled; matching manual reservations stay held
through observation and closing. Existing owner disk override remains recorded.
Owner explicitly authorized deployment after pending QA-master review was raised;
no separate QA-master approval or signed-in visual acceptance is fabricated.
Public login was visibly rendered after cutover; the existing signed-in Chrome
tab remains inaccessible through the adapter. Open risks: common GC/host contention,
ambiguous sewing option labels, unrecorded signed-in/human acceptance and separate
pinned-policy reconciliation before automatic deployment can be re-enabled.

Owned diagnostic clone cleanup: the three label-verified local application/PG
containers and their owned network were removed after exact IDs, states and final
logs were preserved. No production containers, rollback images, unrelated Docker
resources or legacy checkout data were removed.

## Required closing failure and recovery (08:07 UTC)

The 30-minute observer completed 1800.27 seconds / 61 rounds with zero health
failures at 08:05:41.426793 UTC. Observer SHA256
e766a076513fd05cfbf7d0e20aa9a8cf2c46214d4b5a7fb3d753a0de06c88e72.
Health-only observation passed; closing performance failed, so overall rollout
did NOT complete successfully. Do not confuse this with Observation complete.

| Query | Closing median / p95 ms | Outcome |
| --- | ---: | --- |
| Global search | 253.215 / 284.480 | Pass |
| Inventory batches | 167.389 / 170.905 | Pass |
| Stock | 153.680 / 210.544 | FAIL p95, limit194.396 |
| Model groups | 193.040 / 255.732 | FAIL p95, limit230.470 |
| Model options | 157.589 / 165.063 | Pass |

Rows and payload budgets, all medians and other p95 values passed. Failure is
preserved in the root manual journal closing_public receipt and raw
manual-20261119_070624_44477044420_1-closing-public.json. No retry-until-green,
threshold change or reclassification occurred. Backend was restored to blue
030500 at 08:07:29.046301 UTC and strict readback at 08:07:38.404110 UTC;
frontend restored at 08:07:43.688855 UTC with readback08:07:43.980312 UTC.
Both source symlinks, actual routing, slot/image identities and four health
checks pass. Candidate e4 remains held green. No database downgrade or business
data changes occurred. The two confirmed fixes remain source-integrated, but
further causal diagnosis and a successful reviewed deployment remain required.

Independent review recommends a single bounded transport diagnostic on the exact
failed stock/model-group paths plus health, retaining DNS/connect/TLS/first/last
byte, Server-Timing, exact body hashes/bytes and simultaneous internal controls.
This is diagnosis, not a rerun of the failed closing gate. Do not speculate that
GC, unchanged queries or network caused these particular public tail spikes
until the new phase timings distinguish them.

## Further diagnosis and count-window candidate (19 November)

A single 63-round simultaneous transport diagnostic, after recovery, recorded
DNS/TCP/TLS/first-byte/body/Server-Timing and exact hashes on public, LAN frontend,
active backend and held green. All 756 measured calls returned200; nonhealth
payload hashes were stable. Public fresh-connection DNS was a consistent ~97ms
(p95~100ms), a measurement-client/resolver floor, not a proven ERP DNS fault.
The slowest model-group request was287.058ms: DNS99.291ms, TLS complete123.516ms
(cumulative), backend152.3ms, post-ready firstbyte163.266ms. Thus application and
connection setup both matter. The earlier failed closing captured no phase
timings; this later epoch does not establish its exact cause or relabel it.
Protocol SHA256329841388dad9ae0b1451d5ceb857d8cd88c358329f5877f71b8a0f8a036080c;
result SHA2568c87a7d3694d3bcfa8d35011ba3b55c8d06d3819eaf97f13d145eae43bc00f22.

A disposable process in the exact held-e4 image then exercised actual HTTP with
read-only PGOPTIONS plus get_db override, SQLSTATE25006 write refusal, isolated
technical SQLite and no application startup/background tasks or parent patches.
Stock SQL median14.99ms / encoder2.10ms; model groups SQL56.06ms / encoder0.455ms.
Two grouped-key scans cost24.97 and24.60ms: one count, then the page over the same
filtered/grouped set. Endpoint-only hooks failed to attach, so no endpoint-only
wall/CPU claim is made. The first warmup collected generation2 for330.8ms; this
isolated startup observation is not a new steady-state production GC measurement.
Profile SHA25672418c5e62bdcdd68f16c166ef2932f84aca0ccf3b75d64f4c726287265d67d2.

A PostgreSQL translate alternative to the25nested replacements matched all8,356
stored codes,8,356family keys and8,200adversarial Unicode values, but six alternating
EXPLAIN ANALYZE trials found no speed gain (old22–26ms, translate23–26ms). It was
rejected. No normalizer/compiler, index, schema, DNS, GC or stock query was changed.
Experiment SHA2564f36f2512de8849e44a5511423ffed31afb8efbe179b1d543ae7359e51402736.

The narrow candidate instead returns count(*) OVER () alongside already-grouped
page keys when include_total=true. A returned row supplies the exact family total
before pagination; an empty later page retains the old unpaginated count fallback.
Empty first page returns0. No-total queries and SQLite remain unchanged; family
membership, filters, ordering, hydration, permissions and payloads are retained.
This makes page and total use one statement; it does not promise one snapshot for
all subsequent membership/image queries under normal READ COMMITTED transactions.

Prospective frozen read-only HTTP prototype: six alternating old/window epochs,
21measured requests/mode/epoch after3warmups,126samples/mode/path. Group HTTP
median78.063→52.057ms, p9597.367→61.484; SQLmedian55.338→30.494ms. Exactly one grouped
count query disappeared. Stock control median38.216→37.558/p9548.220→44.628ms;
health8.426→8.017/p9510.409→10.194ms. All body hashes were exact;11extended HTTP
cases matched (prefix pages, full/compact, far-empty/first-empty, no-total, V aliases,
code/name/category/status/legacy). These are prototype results, not production
activation or a passing replacement for failed public closing.
SHA2567d088af0be2e7311dca26988303f7bcc73a1fbdf0a35b790cfcdedf27251bb34.
Six balanced EXPLAIN ANALYZE BUFFERS epochs found old count+page versus window
medians: exact47.727→23.786ms, prefix46.180→23.871ms, broad9.410→5.938ms, zero temp
blocks in all plans. Plan evidence SHA256fcdd5d1a01c3221e9286527f7fb8dbea7fdefab6df300616e589cf25a227d8f1.

Fresh fetch found Ismail's merge#561 at d9f905f02bd768507ed6fdf9a240a32fa6960fcb
(parent e4), variant-create persistence extraction23efc6b49. It was fast-forwarded
into this dedicated worktree after verifying both actual production hosts still
030500, production-base437 and schema0159, and reviewing the exact six-file diff.
Independent AI review found no semantic blocker. Its original record's PostgreSQL
HOLD/incomplete acceptance is preserved, not treated as a pass from the merge.
Fresh owned PostgreSQL16 and a source-read-only test container completed86tests,
zero failures/errors/skips,50.44s, including both exact variant PG tests, new group
paging PG cases, catalog/Usluga/image/permission/counter/encoding regressions.
Posttest database census contained only postgres: all owned target databases
were dropped. No uncertain earlier resources were touched.

The source count-window edit, new PostgreSQL tests and scoped CI verification
have independent source review; Ruff, whitespace and CI policy/shard checks pass.
The CI step verifies the job-owned CID and PostgreSQL system_identifier and sets
the approved-instance environment only inside its exact test invocation.
Exact combined-commit CI and a new immutable production attempt are still pending.
Inventory stock does not use this model-group query; no direct fix of its earlier
tail spikes is claimed. Existing health/latency/observation/closing gates remain.
