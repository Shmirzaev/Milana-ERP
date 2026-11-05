# Production-order cutting factory action, 5 November 2026

## Requested behavior and source

The owner asked where Planning exposes Change cutting factory, then supplied
the Production Order detail screen (PO-0684) and instructed: "add it in this page".
The earlier three-feature release and exact94e visual approval remain valid for
that release; they do not establish human acceptance of this follow-up build.

The follow-up is frozen at `488f3d654b0669a9878b8efd3d34298994e9dc45`, branch
`codex/order-detail-cutting-factory-20261105`, dedicated worktree
`C:\ERP\.codex-work\order-detail-cutting-factory-20261105`. It is pushed and
unmerged. Its four frontend blobs are preserved exactly in source integration
commit `b039fa9918dab71a56f70b7d949a4302641373cc` / draft PR496. The combined
integration migration graph remains separately held; do not deploy that graph.

The detail header reuses the existing action beside Cascade deadlines, binds it
to the displayed order, omits the order picker, and refreshes the page after save.
The Planning dashboard picker remains available. Existing permissions, server
eligibility/refusals and audit operation are reused. No backend, dependency or
migration file changes. The fifth runtime path records the verified production
baseline in `deploy/production-base.json`.

Planning engineer/reviewer ownership remains Ismail/Mirshoir; production ownership
remains Mirshoir with Ismail review. No human signature is inferred from AI work.
The exact UI change creates no new DTO, enum, storage vocabulary or persistence
writer. Existing factory codes and operation services are intentionally retained;
broader schema-writer/type migration remains outside this narrow placement change.

## Exact-source verification

- Complete CI [41983869988](https://github.com/Shmirzaev/Milana-ERP/actions/runs/41983869988)
  passed backend, frontend and immutable release jobs at exact 488f3d654.
  Refactor PostgreSQL CI41983862095 also passed. The duplicate push run was
  canceled, not passed; the full dispatch run retained the required checks.
- Local backend: 5,116 passed, 606 skipped, 14 warnings; Ruff/compile passed.
  Required real PostgreSQL CI gates include Planning19, BST27 and ECO8.
- Frontend: 12 component cases, detail-header target/refresh/permission harness,
  strict types, optimized102-page build and contracts passed. Lint has zero
  errors and12 inherited warnings.
- Actual Edge used a loopback production frontend build, candidate FastAPI and
  isolated PostgreSQL 16 restored from approved synthetic fixtures. Normal login,
  exact-order dialog, save, reload and reopening passed. The actual database
  readback compared106 table counts and all order/item/work-order rows: only the
  selected cutting work order's department/update timestamp and one audit changed.
  Recorded-work and assigned-operator orders refuse with Save disabled. Normal
  synthetic Cutting-role GET and PATCH both return403. Real preview console
  errors were empty. The earlier memory-only fixture is not persistence proof.
- Bounded real HTTP check declared20 capability reads, maximum concurrency2,
  three sequential same-destination PATCH requests,10s request/40s total bounds.
  It passed in2.187s: one transition, one audit,106-table integrity and recovery
  GET passed, zero unexpected HTTP errors. Production was never its target.

Independent reviewer `/root/floor_pictures` inspected the exact source, actual
screenshots/browser receipt and environment scripts, independently recomputed
both raw persisted deltas and their continuity, and recorded
**AI_VERIFIED_AWAITING_HUMAN**. Review receipt SHA-256:
`0d03848008160ca1fe044fe369eef377bb2c90fb8e43ebdd4bd751ffb31c6a3b`.
Scope limits:106-table counts, full rows for orders/items/work orders and prior
factory audits; actual compact906px English preview. No actual phone-viewport
claim; EN/RU/UZ copies passed component tests.

Private evidence lives under the runtime worktree's ignored `outputs/qa-20261105/`
and `outputs/visual/`. Synthetic credentials and raw private evidence are not
published. Independent verification and human acceptance are recorded separately;
the owner subsequently replied **"Visual QA approved"** for exact 488f3d654.
Bound approval receipt SHA-256:
`28a9550b8e2d07ce9578c01660137dcd3aafc89042b145eec03757f87792d838`.

## Final deployment state

**DEPLOYED** on 5 November after the owner's exact 488 visual approval and explicit
"Accept this exception and deploy" reply. Both hosts now serve blue
`20261105_065721` / `488f3d654b0669a9878b8efd3d34298994e9dc45`, manifest
`e6c603d4c1954c64a75962cf189427eb5e316c039ea23de4699b9bd4f3112095`.
Both current links name that release. Working rollback is green
`20261105_043000` / `94e4cfc54c6cc4fd5787bcbc7ba8483f4518a507`, manifest
`dd662d889407378ce78d22ebb40e5ce3f53a3043377027b84315f8733234b257`.
Database remains `0154_eco_receipt_details`; no DDL or BST handoff replay.

Immutable images: backend
`sha256:3318e1f1c32c68a14bee4cf401b32e1271ff00c86b29dd041dde7d1c90e0518f`,
frontend `sha256:cc101bb98011609eef4be640b7d53ff6595b4c5f1648bd81c6d6f3beb8f368b2`.
Backend container 64fc88c6c78f has two workers 3081701/3081702; frontend container
567df3d7e7a8. Closing verified zero restarts/OOM, strict security, seed/schema sync
disabled, two 8+4 pools, unchanged 1200/60s global limit, 35/100 DB connections and
zero invalid indexes. Rollback containers/images remain running.

## Preserved capacity and backup evidence

Initial backend staging failed the unchanged below 80% disk guard:
2,247,874,128 bytes peak versus 1,465,860,095 available headroom. Fresh image
exports/configs, uncompressed layer hashes and committed parent chains were
verified. Exactly two unused recoverable backend images, f4d092e15e269fda... and
b137ad0557e4a839..., were then removed separately with no force/prune. Each had
one alias, zero running/stopped container references, an exact registry copy and
complete checksum/member-verified source archive with raw Git identity. Root
reviewed this necessary recoverable cleanup within the existing deployment
request; an agent's initial approval prerequisite was its delegated read-only
boundary, not a persistent user/repository rule. Independent helper review passed
10 supplied and 20 additional guard cases. Live/rollback/protected releases,
archives, containers, volumes and business data were preserved. Actual subsequent
capacity passed: backend peak 2,247,874,128 < headroom 2,604,281,855 bytes; frontend
peak 678,600,885 < headroom 1,170,451,660. Thresholds/reserves stayed unchanged.

The first 112,340,678-byte backup and its failed-attempt history remain retained.
Before retry2, a fresh full backup passed mode 0600, checksum and 1,329-object
restore-list verification:
`/opt/milana-erp/shared/backups/milana_erp_pre_20261105_065721_20261105_084848.dump`.
Size 112,369,333 bytes; SHA-256
`c59941b96e5eca00804dcf8166a0cdf1d17340daa10c3663edcc0465e1b756df`.
The 512 MiB hard backup limit stayed enforced. Current 0154/zero pending revisions
was re-proven; no migrations, stamps or production manufacturing writes ran.

## Performance exception, retained rollback and successful retry

The initial stale expected admin/model guard produced no valid benchmark. A
read-only diagnosis established actual official selection 14/MIL,
KJ13061-V-6813/kg. The valid paired comparison then **FAILED** Inventory Stock:
median 23.26 to 27.04 ms (+16.25%, limit 10%), p95+21.87% (limit 15%). Other endpoints,
rows and payloads passed. Original failure receipt SHA-256:
`5c59eb549601f89ac9cf2bb98d206136dafafc31b6da46353db68f8baeea375b`.
The owner's explicit exception covers only this paired failure. It remains FAIL;
no pair resampling occurred and final public default limits were not waived.

The first live attempt activated both roles, passed normal read-only public UI
QA, then immediately rolled back backend-first when the public benchmark command
stopped before usable metrics. Both roles/current links returned to 043000.
The failed-window log review found 434 lines, three normal order controls and zero
benchmark-path requests, with no traceback. This supports a premeasurement guard
stop; it does not prove a measured latency failure or its precise cause.

The reviewed f6 ops helper replaced an insufficient transaction-local GUC attempt
with ORDER BY User.id ASC on exactly the untimed native User seed query, preserving
actual ORM rows, active filter, permissions and fail-closed subject/path guards.
All other queries delegate unchanged. This changes executed seed SQL methodology;
no forced user ID, fake role, result fallback or repeated pair was used. The
GUC workaround was removed. Independent review passed 39 offline cases and an
actual isolated PostgreSQL 16 native-query/order/delegation/read-only zero-write
witness. Official benchmark bytes/main/default warmups, samples, timed API
queries and comparator remained unchanged. The official app selector in 488
remains unordered; a durable official-tooling fix is future work.

Retry2 used a fresh active public baseline and final candidate comparison for
actual canonical existing subject 1/MIL, KJ13061-V-6813/kg, separate from paired
subject 14. Default 3 warmups and 3x7 measured samples were retained. Strict public
limits 10% median/15% p95/15% payload passed, with identity/query/row parity:

| Endpoint | Baseline median ms | Live median ms | Median change | p95 change |
| --- | ---: | ---: | ---: | ---: |
| Global search |213.58|213.91|+0.15%|-11.41%|
| Inventory batches |151.73|150.95|-0.51%|-1.03%|
| Inventory stock |140.18|139.03|-0.82%|-2.85%|
| Model groups |189.40|187.38|-1.07%|-4.41%|
| Model options |155.23|153.96|-0.82%|-16.93%|

Payloads were unchanged; every request returned 200. All four health checks,
runtime/source/security/pools/logs and database checks passed. Final closing
receipt at 08:55:52 UTC on 5 November is PASS, SHA-256
`69c3bb16b2300cacb7a4f0d1b41c4b93b0ac750b87d682d3ee834c3bafdd5d34`.
Both exact owned deployment leases were then released. No 30-minute monitor was
created or run, per explicit owner instruction. Normal authentication/session
reads and backups occurred; no production business form was saved and the prior
42/40-worker BST transfer was not replayed.

Normal signed-in staged preview on actual PO-0684 passed with 31 HTTP 200 requests,
unchanged before/after runtime identities and zero application console errors;
its proxy is stopped. Final retry2 public Edge reload showed the header action
and fixed-order dialog on actual PO-0684, without Save and with zero new console
errors. Earlier extension errors/failed attempts remain recorded separately.
The live order is [PO-0684](https://erp.milanapremium.uz/production-orders/726).
The source branch is pushed/unmerged; PR496 remains draft and its combined
migration graph is separately held. Only the exact immutable 488 runtime deployed.

## Recorded human review and handoff

The owner approved exact 488 at the isolated synthetic preview following the supplied checklist for the
header position, fixed PO-0001 dialog, save/reload/reopen and unsafe PO-0002/0003
refusals. Independent AI review preceded this approval. The local QA services are
stopped after completion, with their synthetic PostgreSQL container/volume
preserved. Existing production PO-0684 was not changed as a test. Human production
acceptance remains separate from this recorded local visual approval.
