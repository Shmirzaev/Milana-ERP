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

## State

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
reservation (consumed0); physical stock, payroll2500 and shipment8 stayed unchanged.
The20-request/concurrency2 read smoke passed with unchanged selected facts; it is
not capacity or fault-abort proof. Full backend CI and recovery hardening remain
pending. Browser extension-injected hydration warnings and the unexercised blank
quantity entry remain explicit limitations. On7November2026 at04:35UTC the owner
answered the explicit pre-deployment checklist question with **Review passed — I
completed it**. Record the reviewer as the authenticated user/owner in this chat;
no separate personal name was supplied. This is the human application review,
not a technical/security/backup/observation waiver or earlier acceptance backfill.

Integration and validation are in progress. No merge, production migration,
cutover, observation or human acceptance is claimed by this planning record.
Update this section with actual commit/run/evidence identities as gates finish.
