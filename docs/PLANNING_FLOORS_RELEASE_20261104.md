# Narrow Planning, floor pictures and BST candidate

Status: IN PROGRESS, NOT DEPLOYED. Owner's original request, approved scope and
migration separation are preserved in the source integration packet. Integration
worktree: C:\ERP\.codex-work\planning-floors-bst-20261104, branch
codex/planning-floors-bst-20261104, based on clone_main61cd16bd9. Released ECO
application changes were reconciled there without overwriting other clone work.

This separate immutable-runtime preparation uses
C:\ERP\.codex-work\planning-floors-release-20261104, branch
codex/planning-floors-release-20261104, based on freshly verified production
984aeffb22aedd3262d7cd61e2d88a905b589e8d. Only approved small feature commits are
ported. Existing ECO functionality, customer-package safeguards, FG numbering,
schema0154 and locked dependencies are retained. Migration files, package-lock
and dependency versions have zero diff from984. No undeployed turnstile/refactor
work is included by accident. Source integration and release scopes differ openly.

## Scope and authority

1. Planning: change eligible order Cutting routing CUT/ECT, scoped source and
   destination permissions, recorded-evidence guards, concurrency locks and audit.
2. Department floors: available order artwork or exact-model valid print image,
   keeping model/material pictures and existing department/Band access.
3. BST: prepare guarded current-worker/flow handoff, preserving identities and
   history. Production execution is held for the owner's required620 identity
   confirmation and completed verification/backup. See BST_MASTER_HANDOFF_20261104.md.

The user authorized deployment without30-minute observation, then required
application reconciliation approval before edits and separate approval of database
migrations. Application scope was approved. This narrow release requires no new
database migration. That does not waive actual browser QA, source review, CI,
backup, performance, rollback and immediate/final health requirements.

## Evidence checkpoints

- Independent source review found no integration loss in the ECO source port:
  65 paths match exact released blobs, five match the clean three-way result,
  and the only manual permission conflict retains both turnstile and ECO entries.
- Floor review found a model-fallback PDF-selection defect. It was reproduced,
  fixed narrowly and independently closed;6 new cases protect it. No shared model
  helper or existing model/material image behavior was broadly rewritten.
- Root narrow145-case focused suite passed, including new routing40 HTTP/SQLite
  and9 real PostgreSQL cases plus artwork, inbox and existing ECO sewing gates.
  Later routing review findings require a final follow-up run after correction.
- Root narrowBST PostgreSQL27 passed in19.65s, zero skips, on owned disposable
  loopback25465 database; no Alembic run. Individual real payroll totals were
  removed from the source packet and replaced by arbitrary synthetic fixture pay.
- All frontend build-contract commands passed, including9 Planning component
  controller/SSR cases. Initial Next compile failed because Turbopack rejects
  dependency junctions outside its root. Removed only the verified task-owned
  junction and installed the exact locked dependencies locally for another build.
- Actual connected-browser verification is BLOCKED. Extension tab access twice
  failed; documented Windows fallback stopped because the current browser URL
  could not be established confidently. No further UI input or bypass followed.
  SSR/component tests are not represented as actual visual acceptance.

Production remains on20261104_080711; no business row, schema, role, account,
release, container, symlink or proxy changed. Worker transfer and deployment are
held, not completed. Before promotion, refresh all production/source state and
verify every required gate on the exact candidate; prior release-specific p95
exceptions do not apply. A code rollback cannot reverse a committed future roster
handoff; its reviewed audit/CAS before-state is the recovery reference.

## Final correction and validation checkpoint

Sparse recorded history is refused through work-order, batch, sewing-assignment
and package-allocation links even when direct production_order_id is null. Final
source review includes the legitimate52 HTTP/SQLite and19 real PostgreSQL Planning
cases, including a public-created CUT->ECT vs bornECT positive ECT cutting/bundle
to MIL Sewing receipt handoff. Earlier stale-scope and evidence omissions remain
documented in the worker packet, not relabeled as original passes.

A full Windows backend run at13e48e767 was interrupted at29% after six clustered
new query-budget failures. The exact targeted reproduction returned43vs42 SELECTs
for Cutting bundles (and31vs30 for materials) caused by unconditional refreshed
authorization. The final fix retains the initial successfully authorized department
identity and reauthorizes after locked refresh only if that identity changed.
It does not remove any security guard or alter an old performance assertion.
Independent reviewer reran the six old caps and actual PostgreSQL stale-source
race:7 passed. Root final run:109 passed, zero skips (71 Planning including19PG,
15 existing query-growth cases and23 floor artwork cases). There is no completed
full local backend report; do not claim the full suite passed.

Build prerequisites, optimized102-page Next16.3.8 build, strict TypeScript, Ruff,
compileall and diff checks passed. Frontend lint:0 errors/12 existing warnings.
Both actual component/controller suites passed (9 Planning,14 artwork). Added both
as build prerequisites and explicit Planning/BST PostgreSQL CI gates. Complete
exact-revision CI/publication remains pending at this checkpoint. Prior metadata/
documentation corrections change no runtime schema. No migration file, lockfile
or dependency version differs from deployed984.

Independent source reviews found no remaining bounded feature issue. Actual
connected-browser checks remain BLOCKED; SSR is not visual acceptance. New BST
identity620 remains unconfirmed, so no executable production plan has been captured
or applied. Current payroll amounts/history remain unchanged; existing reports
would regroup historical views under current managers after a future handoff.
No push to clone_main, production cutover or timed monitoring has occurred.
