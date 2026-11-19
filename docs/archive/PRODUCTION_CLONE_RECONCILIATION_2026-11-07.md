# Production and clone_main reconciliation — 7 November 2026

## Authorization and scope

The user requested faster deployment guidance, then explicitly requested merging
live production and `clone_main`. In the follow-up they selected **Merge and deploy
after all checks pass**. This authorizes preparing the complete combined candidate
and its necessary schema reconciliation; it supersedes the earlier application-only
release scope, not the requirement for passing gates, a verified backup and compatible
rollback. No production business test rows or business backfills are authorized.

Runtime integration owner/reviewer: Mirshoir/Ismail. Release tooling ownership:
Dilmurod/Mirshoir. Codex root is the single integrator in the isolated worktree;
`reconciliation_review` supplies independent review, `migration_reconciliation`
owns only the new merge revision/rehearsal, and `candidate_qa` owns ignored local
QA artifacts and disposable services. Named human ownership is not evidence of
human acceptance or a message sent to the engineers.

## Frozen inputs and initial production check

- Worktree: `C:/ERP/.codex-work/reconcile-production-clone-20261107`.
- Branch: `codex/reconcile-production-clone-20261107`.
- Shared source: `221deef998b2e0d873786ee1de8dfe3a035a0c4f` on `clone_main`.
- Released application: `a8579e64efbb2f9545d6df1c35d527c1d4ae2f01`.
- Released source and completion record: branch tip `68bc22590`.
- Both application hosts freshly reported release `20261106_061725`, manifest
  `7f52cf7bf61e6fa4159d65e590d9cefaa6a493992e8b80197343490e5ee09fb0`.
- Previous readback: active green, retained compatible read-only rollback blue
  `20261106_054000` / `bf9cb9f0e738e82b9a21909b22e4cdecae7bed37`.
- Production schema is last recorded at `0154_eco_receipt_details`; refresh it
  before any migration. Git baselines were stale: main October 26, clone_main
  November 3. The reviewed live release record supplies the reconciliation base.
- Legacy `C:/ERP` changes remain preserved. No shared branch is force-pushed.

## Merge decisions and verification scope

Preserve both histories and every required CI/frontend contract. Keep shared
Identity access-policy services and typed factory codes alongside released
Cutting rejection locks. Keep authenticated conditional image responses and CAD
attachment responses; independent review caught and corrected a missing local
FileResponse import introduced at that intersection. Keep both Attendance and ECO
administrator permission entries and all open bug/acceptance records.

ECO `0154_eco_receipt_details` and turnstile `0153_gate_revoke_tombstone`
are distinct heads. Join them with one empty `0155_eco_gate_merge` revision;
preserve prior migration bytes, strict startup validation and the single-head gate.
An upgrade from current production applies the existing gate migrations as well
as the empty merge. Rehearse fresh installation and upgrades from both heads on
owned disposable PostgreSQL databases, preserving original table identities,
stored values and balances. A source merge or successful schema rehearsal is not
production migration or deployment evidence.

The current application images cannot be assumed restart-compatible with the
new strict head. Prepare and test compatible recovery before schema execution.
Retain the existing read-only rollback restriction and refresh operational security
counters before any emergency read-only activation; a stale snapshot is unsafe.

Required combined evidence includes full backend regression, real PostgreSQL
operation and concurrency gates, frontend lint/strict types/contracts/build,
legacy JWT/cookie compatibility, ECO/Planning/Cutting/passport/CAD workflows,
connected candidate-browser checks and persisted readback, independent review,
exact immutable artifact provenance, backup, staging performance/result parity,
four health checks and strict two-worker startup/recovery. High-risk observation
is 30 minutes unless the owner grants a new explicit deployment waiver.

## Actual completed deployment - 7 November 2026

The merged application is active, with the owner's two explicit scoped exceptions
recorded below. Public model-picker p95 remains FAILED; timed observation was
WAIVED, never completed. All other required deployment checks passed.

| Role | Active green | Retained blue recovery |
| --- | --- | --- |
| Release | `20261107_043754` | `20261107_043753` |
| Application | `3c6ccc82a8521d74ce274151024ccd5bc1942fde` | `493fd5906809f23bd571949d63b192629e901b84` |
| Manifest | `43b30accbabc4674a395eaa46eecd2c7f554a2513adc33dc859131355526bddd` | `af534829bbad2b581497e5218334292d5cfeabaee748b0b2c8f7a66039067e18` |

Backend activated at 07:04:59.434432 UTC and frontend at 07:05:35.032935 UTC.
Schema is `0155_eco_gate_merge`. Both current symlinks, slot states and immutable
images agree. Recovery493 remains running and strict0155 compatible while
provisioning is disabled and all six gate tables are empty; verify those guards
before incident use. Do not restart old strict0154 images or downgrade/stamp the
database. Older read-only recovery/counter snapshots are historical.

Source integrated by normal nonforce fast-forward to `clone_main` at
`d157b652e7570370131d26e4380559f9518edfe7`. Full backend/frontend trees equal
application 3c and the owner-reviewed7d candidate. This subsequent record-only
publication changes no application/image inputs. Legacy `C:/ERP` work remains
preserved. Worktree/branch remain those recorded in the frozen inputs above.

### Tests, artifacts, backup and schema

- Final [CI42339294521](https://github.com/Shmirzaev/Milana-ERP/actions/runs/42339294521)
  passed:6,578 backend tests, 1,548 expected opt-in/not-applicable skips and 36
  subtests. Required PostgreSQL [42339297228](https://github.com/Shmirzaev/Milana-ERP/actions/runs/42339297228)
  passed 639 + 17 + 84 cases without skips/failures, alongside the other required
  domain gates. Frontend lint, strict types, contracts, build and CI browser passed.
- Recovery CI42339292169 passed 5,245 backend tests / 649 expected skips and required
  PostgreSQL/frontend gates. Integration-only d157 CI42341627527 also passed.
- Final backend digest `fe926ecc25da1b0bea469c7e5d542d0367c48f821619df51c92009b9b4f4d08b`;
  frontend `ad9b505de85e2f18bb57f6cd5f30e81fafb51a0cdbfb1befc750a897597065b8`.
  Recovery backend `bca077e9e3cafd7946320a60d77de4ceab82bcfbad8b0edffbbbf69b20306de6`;
  frontend `1ac79c260b6b73fdd3c8c56917a8eee504642354559ae0551619d0c4a608955f`.
  All use `ghcr.io/shmirzaev/milana-erp-<role>@sha256:<digest>`.
  Exact published OCI/config/layer/source and security provenance passed; images
  were not rebuilt after scanning. Zero policy-blocked findings does not mean
  zero vulnerabilities: final backend retains53 unfixed HIGH / 0 CRITICAL, recovery
  retains54 HIGH and unfixed CRITICAL python-jose3.5.0/CVE-2026-85394. Final frontend
  had 0 HIGH / CRITICAL. Initial9ef fixable security failures remain preserved.
- Exact published default Alembic/uvicorn command, strict schema, two workers,
  worker replacement/restart and shared security counters passed for both images.
  The staging adapter only supplied RELEASE_ID; installed controller, shared
  environment and HAProxy behavior were unchanged. Production seeds stayed off.
- Pre-migration backup:114,047,750 bytes / 1,329 restore objects, SHA256
  `67c5f47e5eca068917bf6a67392cb8833c142c4521464d972abb04bb4f173231`.
  Final pre-stage backup:114,161,920 bytes / 1,395 objects, SHA256
  `0a5e1540e8e97ffd688064434575c2aeb43a1c24e17c771439faef110066d127`.
  Paths/permissions/restore lists remain in the phase journal. Schema-only upgrade
  to0155 preserved prior migration bytes. No business fixtures/backfill or stock,
  shipment, payroll or user creation was performed in production by this task.
- The frontend80% disk guard stopped the first pull. Exact already-cached lower
  layer proof established sufficient headroom with full compressed content and
  reserve still budgeted. No production prune/deletion occurred. Disk maintenance
  remains a follow-up; active/rollback images and backups remain protected.

### Actual functional, browser and performance evidence

The owner passed local application review at 04:35 UTC. Connected Edge/local
synthetic persisted checks covered named ECO/Planning/Cutting/passport/rejection,
CAD, permission, payroll and shipment cases. Local draft saves created two Nastil
rows and a 200 kg planned material/reservation (consumed 0); this was not production
data and did not prove stock consumption. CAD checks prove opaque transport only.
The 20-request/concurrency 2 smoke is not a capacity/fault-abort claim. Extension
hydration warnings, unexercised blank quantity and absent positive production
grouped rows remain explicit limitations; positive grouped cases were local.

Actual final public functional24682 passed 11 signed GETs against original00421,
preserving complete protected/ordered facts. Final signed public Edge verified
inventory 78 types / 81 lines, batch 7826 quantity 548 / reserved 0 / available 548 and distinct
loaded photos for 7586, saved passport 800 two 600-piece rows, and PO0749/0750 dashboards
each 1,200 pieces. No production form was saved; captured warning/error logs were
empty for these final views. This is scoped evidence, not whole-ERP acceptance.

The final staged host-observer interleaving passed 480 GETs across both AB/BA strata
and all five endpoints at original 10% median / 15% p95 / 15% payload budgets; worst ratios
1.07079 / 1.13978 / 1.0. It did not pool away either stratum or compare timings across
different observers. Earlier sequential failures and024549STOP remain retained.
An explicitly reviewed fresh mutable benchmark epoch retained full ordered facts
and per-path hashes (aggregatec14c8f8d), selected50-batch physical/reservation
ledger parity, exact actor14/MIL and unchanged queries/counts/budgets. Original
protected functional baselines stayed fixed. Real ledger activity was observed;
the old field/order difference and historical STOP cause were not proved.

Both public performance comparisons remain **FAILED only model_options:p95**:
157.75 ms baseline to 198.75 ms (+25.99%), then +27.21%. Other four endpoints and all
median/payload/ordered-result checks passed. Failed comparisonscf3f4975/9ea600c5
and rawd5b1d7b7/865dfe6a remain immutable; no outlier removal/budget change or
repeated sampling until success occurred. Historical router response times were
36–43 ms before / 38–44 ms after, without proving historical client identities/cause.
The separate 24-GET diagnostic79acd caught a 194.377 ms sample with 137.636 ms in the
DNS/TCP connection phase, app 36.5 ms and no GC pause. DNS versus TCP and the earlier
failed windows' cause remain unproved; no application latency fix is claimed.

### Explicit owner exceptions and final closing

The owner said **do not monitor it for 30 minutes** (canonical0b0e956d). No timed
observer or start anchor was launched; observation_complete staysfalse. Separately,
the owner answered **Keep merged release; approve this performance exception**
(canonical1a75ef78) to the exact failed public model-picker question. This accepts
only model_options:p95; all other original budgets/gates remain. Performance gate
passed staysfalse, performance exception approvedtrue. Receipt creation time is
not an invented exact user-message timestamp.

Initial final closer206e stopped (receipt0c1e7984). Sanitized locatorf47587f2
placed the HTTPError at the public health loop. Two-GET proof738293c6 showed
public/health200 with correct status/release and public/ready404. Frontend rewrites
support/health only; DEPLOYMENT requires public/health and/login. A separately
reviewed observer-only correction removed only the unsupported public/ready
expectation, preserving internal/ready on both slots/stable backend and all four
supported health checks. No application, proxy or routing configuration changed.

Final actual closing `final-supported-contract-owner-exceptions-closing.json`, SHA256 `0b9b11a9f5da575cbe44c7fe57f2ad5c647195bb9710ed2ae05271223543f663`, passed at
`2026-11-07T07:40:43.360271+00:00`. It freshly rechecked exact sources/full inventories,
published images/default commands, retained recovery, two workers, routers,
all four health endpoints, internal readiness,0155/index integrity, connection
headroom, disabled provisioning and six empty gate tables, disk and owned leases.
Both-host before/after CAS and raw journal stayed unchanged during these reads.
It preserves performance_gate_passed:false and timed_observation_waived:true;
neither a new performance PASS nor a fabricated1800-second observation is recorded.

Owned deployment leases were then released through the frozen phase helper.
Final phase journal SHA256: `e45672f9a53527007e3d1b18f93013293128cc577dd128a04fd0b2c06982d171`. Owned local cleanup receipt
`owned-local-stop-remaining-executed.json`, SHA256 `22e8ae96ee002d01493790e450203ef27edb988ff05aa167ece817f481bb3e2a`, passed: all eight owned process IDs
are absent and two local PostgreSQL containers stopped, with data/images retained.
The initial plan-only failure and later corrected0062 partial execution STOP7bd4
are both preserved: two exact API/frontend processes stopped, with the remaining
four application/launcher PIDs subsequently verified absent. That historical
partial-stop cause remains unproved. The separately reviewed remainder plan
targeted only the two original tunnels and two original containers, with all six
earlier PIDs absent before/end and original ports closed. Exact CIM/native
creation times and allowed conhost descendants stayed guarded; no conhost was
explicitly killed. No broad process kill, data deletion or production retention
cleanup ran.

Durable project/production-base records now match the actual release. This record
does not complete system-wide schema-owned writers, enums or human factory
acceptance, nor claim unrelated historic security/audit risks were resolved.

## Historical preparation snapshots (superseded current-state assertions)

The following preserved preparation statements belong to their original times.
They do not override the actual production checkpoint above.

The initial candidate `43aef8ca7` passed hosted frontend/security validation and
all early migration/ECO/Planning/Cutting PostgreSQL gates. Its separate operation
gate recorded 637 passes and one stale item-deletion race test failure. Production's
Item parent lock intentionally blocks a competing FK insert; the old test waited
for that insert before releasing the deletion transaction. Isolated PG reproduction
observed the lock and proved both commit/refusal and audit-rollback/insert outcomes.
The replacement pins both cases (group minimum 12, overall 639), and a removed-lock
negative control fails both. Existing linked-record and audit rollback controls
remain. The original failed CI evidence is retained, not relabeled as a pass.

Compatible recovery source `9ef1a476202464befe759634c0b33c53ec015aef`
preserves exact current-live application/dependency bytes and adds only four
migration files, refreshed initial baseline metadata and a test-only exact gate
storage contract. Independent PG verified fresh installation and five rejected
storage mutations, including timezone loss. Its local default-command probe
verified strict 0155 startup, two workers, replacement/restart and shared counters;
published-image verification remains required. Recovery artifact workflow:
42337397950, release `20261107_041208`.

The final candidate merges that recovery ancestry, retaining its own complete
gate ORM mappings and original schema-drift test instead of the recovery-only
unmapped-gate allowance. The four added migration files are already identical.
DEPLOYMENT.md records an explicit two-phase compatibility/combined deployment:
initial baseline remains November 6; the phase journal must pin and verify the
intermediate recovery release before final activation. No unexpected drift is
accepted, and neither phase has run in production yet.

The initial recovery source's dependency scan found 41 unaccepted fixable
HIGH/CRITICAL findings in Pillow12.2.0 and Next16.3.8. That source is not eligible
for promotion under the combined candidate's security policy. Prepare a narrow
recovery update to Pillow13.0.0, Next/eslint-config-next16.4.3 and the already
reviewed hardened backend/frontend Dockerfiles. Preserve business/authentication
code and other dependency choices, verify React18 peer compatibility, and require
fresh build, compatibility and exact published-image security evidence. Preserve
the initial failed reports; do not change policy acceptances to turn them green.
A separate npm audit identified development-only Zod4.4.3 HIGH advisory
GHSA-mrhx-c7xc-m3w5, absent from that Trivy snapshot. The recovery lock also moves
that one entry to the final candidate's already reviewed4.6.6; retain its dev-only
classification and all unrelated pins.

Combined candidate7d17ece passed its frontend build/contracts/security scan and
the separate PostgreSQL gate:639 required,17 purchasing/fabric and84 shared
contracts, all without skips or failures. Independent source/persisted review
passed; connected Edge exercised the named synthetic workflows. Draft passport
saves also create two Nastil batches and one newly selected200kg material row and
reservation (consumed 0); physical stock, payroll2500 and shipment8 stayed unchanged.
The 20-request/concurrency 2 read smoke passed with unchanged selected facts; it is
not capacity or fault-abort proof. Full backend CI and recovery hardening remain
pending. Browser extension-injected hydration warnings and the unexercised blank
quantity entry remain explicit limitations. On7November2026 at 04:35 UTC the owner
answered the explicit pre-deployment checklist question with **Review passed — I
completed it**. Record the reviewer as the authenticated user/owner in this chat;
no separate personal name was supplied. This is the human application review,
not a technical/security/backup/observation waiver or earlier acceptance backfill.

Hardened recovery is committed at `493fd5906809f23bd571949d63b192629e901b84`,
planned release `20261107_043753` / workflow42339292169. The final application is
`3c6ccc82a8521d74ce274151024ccd5bc1942fde`, planned release
`20261107_043754` / workflow42339294521 and operation gate42339297228. Its complete
backend and frontend Git trees equal reviewed7d17ece, independently verified.
The later procedure/record commits do not change those application/image inputs.

Installed controller13a9e19d does not inject RELEASE_ID; the newer repository
controller also changes HAProxy routing/error responses. Keep production routing
unchanged through a narrowly reviewed staging adapter: invoke the exact installed
stage operation, match its complete backend Docker argv and add only the explicit
release environment. The named493 recovery predates HTTP release fields, so bind
its legacy health checks to immutable image/container/source/slot/environment and
strict workers. Final3c still requires exact HTTP release identity. The adapter
needs actual installed-version command and negative controls, independent hash
review and a recorded phase plan before any production use.

Integration and validation are in progress. No merge, production migration,
cutover, observation or production acceptance is claimed by this planning record.
Update this section with actual commit/run/evidence identities as gates finish.
