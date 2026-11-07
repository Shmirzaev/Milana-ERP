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

Integration and validation are in progress. No merge, production migration,
cutover, observation or human acceptance is claimed by this planning record.
Update this section with actual commit/run/evidence identities as gates finish.
