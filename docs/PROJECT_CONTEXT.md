# Milana ERP: current working context

## Guidance publication and runtime scope

The 26 October guidance publication on `clone_main` at `b92ee8f` was
documentation-only; it did not integrate the runtime candidate in
[draft PR #308](https://github.com/Shmirzaev/Milana-ERP/pull/308). Later integration
candidates contain application changes that require their own exact-source evidence.
Historical results below belong to their named snapshots, not automatically to
this checkout, a new combined candidate or deployed production. Inspect current
code and the operation ledger before advancing a gate. Schema-owned writers,
system-wide enum/type adoption and human acceptance remain incomplete.

Updated 2026-10-28. Keep this file short: current decisions, release pointers and
unresolved risks. Detailed history belongs in [the archive](archive/README.md),
not appended here. This summary does not replace live release verification.

The earlier QA artifact omitted Next runtime inputs and returned 404 on `/login` and
`/`. A repaired genuine f27 artifact subsequently passed local login and scoped
visual/readback checks for PRs 335–337. This does not establish production status
or human production acceptance. See the [dated integration evidence](archive/VERIFIED_INTEGRATION_2026-10-28.md)
for exact source identities, observations and limitations; the earlier failures and
candidate history remain recorded there.

The current integration checkpoint includes CI tooling PR338 at
`e6f597891489e38207e01b6bfcca3d8df1b7adea` and Customer UPDATE PR339 at
`61b1a7020c5e1465aa076acc238d94ea1ad7dd03`. Its scoped Customer evidence and
V23 resource failure are recorded in the [dated integration evidence](archive/VERIFIED_INTEGRATION_2026-10-28.md).
Supplier UPDATE is a later source candidate with its own verification gates; it is
not included in that dated checkpoint. Dependency PR331 has separate environment
and runtime gates. No deployment or human production acceptance is implied.

## Source and production

- Shared integration/production branch: clone_main. origin/main is stale for this work.
- Continue a suitable isolated worktree; preserve the legacy C:\ERP checkout.
  Use separate engineer work directories and one landing queue coordinated by Mirshoir.
- [DEPLOYMENT.md](../DEPLOYMENT.md) is the only supported release procedure.
  Before release reconcile Git, production-base.json, both manifests and runtime slots.
- The imported [26 October invoice release record](archive/INVOICE_READABILITY_2026-10-26.md)
  reports green `20261026_085306`, retained blue rollback `20261026_055538`,
  application `439555a77ef583b1b212398e16ecd52ced786e45`, manifest
  `9511b57bf62fd3142c865f3bb07aaf3e2f1053629f90c8521a652cd6da9139e2`
  and database `0149_besttex_cutting_access`. Its invoice-only release uses 11 pt
  customer/transport text, 9 pt product text, separated SVG branding and matching
  Excel. The record reports exact CI/four health checks and a corrected fixed-origin
  performance comparison passing after an initial failed gate and rollback;
  public-path tail variation remains unresolved. No 30-minute observation or
  refactoring job was added. These are attributed upstream observations, not new
  production checks by this integration review; operator acceptance stays separate.
- [PR #310](https://github.com/Shmirzaev/Milana-ERP/pull/310) merged as
  `cdcbdfe5e7cfeb08a65e6a86da27fc7b6175733d`, tree
  `aabd33becc5662469eb2ba408f832fb0059f1229`. Its six-file invoice port is being
  reconciled with frozen refactor candidate `d0920f6367b702f63c88d5940cf1b44155b34aec`.
  This successor candidate is **not deployed, not AI-verified and not human-approved**.
  The prior invoice-only production release does not accept or deploy the refactor.
- `deploy/production-base.json` carries the imported release assertion above.
  Local successor merge `02c25ecf2c8acad55418d86cf5b067fc89307162` has actual
  parents `034cb788` and recorded production `439555`; all 36 released paths were
  reconciled, retaining reviewed namespace ports and both historical release records.
  It includes released QR pictures, Besttex views, grade weights and the exact
  migration `0149_besttex_cutting_access`. The migration has not been applied to QA
  or production by this review. Customer permissions, Finance payment forms and
  truthful Sales list totals have independent technical reviews; combined checks
  and actual successor browser replay remain required. Live manifests, slots and
  database revision have not been reverified. See the
  [integration addendum](archive/INVOICE_READABILITY_2026-10-26.md#source-reconciliation--27-october-2026).
- The earlier `20261024_032622` deployment recorded an initial performance failure and rollback, followed
  by reactivation of the same images; public-path tail variation remains unresolved.
  The owner waived the timed observation period. The archive preserves all attempts.

## Later-Nastil Sewing fix deployed

- Permanent later-Nastil receipt/completion and assignment fix is implemented and tested for MIL/BST/ECO. Runtime candidate `1fce86b5`; immutable CI `40082616718` passed.
- Ismail merged PR #304 as `ec02b5f`; the owner explicitly accepted his merge as approval and authorized deployment without the 30-minute monitoring window. The tested immutable runtime has identical application/frontend/migration/CI files to that merged fix. Later service relocation `1dfd1c5d` remains outside this release; repository architecture below describes that newer branch state.
- Activated at 16:13 Tashkent. Fresh backup, no-op schema verification, renewed 18-check factory QA, real live browser checks, all four health checks, runtime/log/database/source/rollback checks and fixed-query paired/public performance budgets passed. No business records/history were repaired or replayed; all eight PO-0307 table fingerprints match across cutover. Timed monitoring was explicitly waived, not reported as performed. Operator business acceptance remains pending.
- [Detailed verification and release record](archive/SEWING_LATER_NASTIL_2026-10-24.md) preserves root cause, tests and deployment preparation.
- Owner-authorized historical reconciliation at 16:29 Tashkent: reviewed 44 pending
  Nastils and reopened 38 incorrectly completed Sewing work orders (MIL 33, BST 4,
  ECO 1) through the deployed service. All 38 now appear in their factory's active
  Sewing floor, restoring 19 missing Milana orders. Only status/end_time/update
  timestamps changed; 38 append-only audits record the prior completion times.
  Fresh backup, 41-table conservation/persisted checks, all 131,366 backup audit
  rows, factory API/browser checks and four health endpoints passed. Pending cuts
  and receipts were not approved or fabricated; ECO USL-0008 still has 335 pieces
  awaiting Cutting approval. PO-0307 remains correctly completed at 256 pieces.
  Runtime/rollback/schema are unchanged; see the archive's historical reconciliation.

## Architecture and migration state

- Execution update, 26 October: Ismail explicitly requested "do the rest iwth codex
  subagents !" Codex subagents now implement the remaining system-wide refactor in
  isolated owned checkouts; one integrator and a separate independent reviewer
  retain the operation gates. This supersedes MiniMax-only execution for this task,
  not human domain ownership, acceptance or release/spending authority. Preserve
  prior worker source/evidence. See [execution rules](../AGENTS.md#implementation-execution)
  and the [remaining-domain ledger](REFACTOR_COVERAGE.md#remaining-work-by-domain).
  This is an execution change, not a new verification or completion claim.

- Historical scope correction, 26 October: the earlier six-area extraction
  checkpoint covered service/DTO placement and only the initial InvoiceStatus
  centralization. It did not complete Ismail's assignment. Subsequent enum and
  writer candidates must be assessed from their own operation records in the
  [coverage ledger](REFACTOR_COVERAGE.md); the old completion claim was too broad.
  Production/business acceptance remains separate.
- The owner's required unit is one business operation: study old behavior and
  callers, classify all relevant table/field/type candidates, implement, then
  automated checks -> actual visual E2E -> persisted readback/bounded stress ->
  independent AI review -> `AI_VERIFIED_AWAITING_HUMAN`. Follow the
  [task packet and operation ledger](VERIFICATION.md#0-study-the-old-behavior-and-give-the-agent-a-verifiable-task)
  and [table audit](../backend/app/libs/enums/README.md#table-by-table-audit).
  Human visual/technical approval, merge and production acceptance are separate.
  Synthetic QA values do not establish the complete production vocabulary.
- The owner's system-wide mentor-discipline goal requires actual enum-typed
  DTOs/internal contracts and consistent schema/service consumers. Default-only
  string fields do not satisfy it. Intentional OpenAPI/validation changes needed
  for enum typing must be explicit and tested; keep business rules and operation
  subsets. The six Ismail pilots are incremental work, not whole-ERP completion;
  Identity/People/Production/Packaging/Fulfillment/platform coverage remains owned
  and pending in the system-wide ledger.
- Keep the FastAPI/SQLAlchemy/PostgreSQL monolith. Router -> feature service ->
  schema-owned persistence operations + supplied Session -> database. Services
  retain business rules, permissions and one outer transaction. Ismail explicitly
  requires writes/updates behind schema models; this boundary remains unfinished
  despite the completed namespace move. Include audit/notification/idempotency and
  mapped mutations, preserve locks/hooks, and verify one complete operation first.
  No microservice/ORM replacement.
- Target: api/routes/ for HTTP, models/ for business services, schemas/ for
  database schema models, libs/dto/<feature>/ for input/update/output contracts,
  libs/enums/ for fixed vocabulary, libs/types/ for distinct internal contracts.
- Business services live in `backend/app/models/<group>/*_service.py`;
  existing shared helpers remain in `backend/app/models/*_service.py`.
  The old `backend/app/services/` directory was removed. Archived plans and
  commit-specific bug evidence may still name it; those paths describe history,
  not where an agent should create or move current code. Follow
  [the service guide](../backend/app/models/README.md) and
  [the current source map](REFACTOR_MAP.md).
  The owner then authorized completing namespace separation urgently: the 22 DTO
  files are now in libs/dto/ and 26 SQLAlchemy definition files in schemas/, with
  all callers and ORM registration updated. Table definitions and business rules
  are unchanged. See the plan's verification record for actual checks/limitations.
- The owner authorized all six Ismail areas (catalog, purchasing, sales, inventory,
  planning, finance) as parallel candidate work. The historical `3cdd6808` checkpoint
  for draft PR #308 combined their grouped services and entity-named DTOs. Its modules
  are listed in [the source map](https://github.com/Shmirzaev/Milana-ERP/blob/3cdd6808ff7ced0717f337d17d4e530719d4a86f/docs/REFACTOR_MAP.md#service-destinations). Existing
  shared helpers remain at models/ root. Finance/Purchasing/Sales passed 397
  tests with zero skips; Planning/Finance paging passed 206, including real PG.
  Final affected coverage passed 694 cases plus 18 recovered from Windows temp
  permission setup errors, with zero skips, and two separate PG stock races passed.
  Actual six-area UI flows, persisted readback and bounded stress passed; see
  [the candidate record and human checklist](https://github.com/Shmirzaev/Milana-ERP/blob/3cdd6808ff7ced0717f337d17d4e530719d4a86f/docs/archive/ISMAIL_SIX_AREA_REFACTOR_2026-10-25.md).
  At that checkpoint, API/table DDL parity covered 577 routes, 475 paths and 97 tables.
  These historical checks do not verify later enum/OpenAPI or schema-writer changes.
  Mirshoir's review and Shavkat's business acceptance remain separately recorded gates;
  no current candidate visual pass or production deployment is claimed here.
- Humans decide business policy, interfaces and cutover; AI implements approved
  scope. Multitenancy is deferred. No deletion quota or table-per-service requirement.

## Work and ownership

- [Refactor plan](REFACTOR_PLAN.md): tasks/dependencies; [source map](REFACTOR_MAP.md):
  current files and proposed homes; [team ownership](TEAM_OWNERSHIP.md): exact assignments.
- Mirshoir: architecture, database integrity, production, packaging, fulfillment,
  release approval. Ismail reviews Mirshoir's changes.
- Ismail: catalog, purchasing, sales, inventory, planning, finance; DTO/enum/type
  conventions. Dilmurod: identity, people/payroll, tasks, shared platform and CI.
- Shavkat: business clarification, priorities and operator acceptance, not technical
  review or migrations. Each code change has an engineer and a separate reviewer.
- Use [active bugs](../bugs/bugs.md) for defects and [finished bugs](../bugs/finished_bugs.md)
  only after named human production verification. Refactoring tasks stay in the plan.
- Shared [skills](AGENT_SKILLS.md): milana-refactor for extraction, milana-feature
  for new behavior; both Codex and Claude use repository-controlled instructions.

## Required checks and open risks

- Follow [verification gates](VERIFICATION.md) after each runtime migration/fix/feature:
  test validity, relevant automated tests, actual visual E2E with screenshot inspection,
  bounded isolated stress, persisted integrity/recovery, then human acceptance.
  Required missing/skipped checks are BLOCKED, not PASS. No production stress/data fabrication.
- Default backend pytest fixtures use SQLite. Real PostgreSQL checks need their
  documented setup/collection; do not infer locking correctness from SQLite success.
- One write path per request and one outer transaction owner. Preserve locks, audit,
  idempotency and side-effect timing. [Retry identity rules](idempotency.md) are active.
- Preserve stable business rules in [AGENTS.md](../AGENTS.md). Particular regression
  cases include sewing 600 received -> 495 then 105, independent Nastils, optional
  stages, and validated packaging receipts before finished-goods stock.
- Historical authorization/audit-chain findings are not declared resolved here;
  consult AGENTS.md and the relevant bug/evidence. OPS01/OPS07 still require the
  correlated factory-path evidence described in [performance evidence](performance-evidence.txt).
- CI branch triggering and automatic recovery improvements in the plan remain
  implementation tasks; skills/docs do not install enforcement or rollback.
- RF-013's [disposable single-host rollback rehearsal](archive/RF013_SINGLE_HOST_REHEARSAL_2026-10-27.md)
  switched both roles through real HAProxy, proved a candidate settings write remains
  readable/writable by the old backend, and recovered from a partial activation.
  The failed frontend remained routed for 41.41 seconds from injected stop to old
  service; `slotctl.activate()` does not compensate. This is local evidence only:
  Mirshoir review, visual acceptance, future RF-005 data compatibility, and an
  accountable production rollback operator remain pending. No production state changed.
- Recovery targets in [DISASTER_RECOVERY.md](DISASTER_RECOVERY.md) remain requirements,
  not proof of measured capacity. Preserve backups, active/rollback releases and evidence.

## Latest documentation work

- Shared skill/ownership baseline: f8719d19; verification gates: c1277680.
- Removed superseded developer/review instructions, consolidated backend/docs into
  docs/, archived dated reports and the full old context, and relocated training
  generation tools under scripts/training/. Runtime code, data, tests, deployment
  settings and test-consumed audit baselines remain unchanged.
- Documentation cleanup is not a deployment. See the final task handoff for its
  publication commit; do not infer current production from a documentation commit.
- Obsidian mirror location from AGENTS.md was unavailable during prior planning;
  no mirror synchronization is claimed. Search archived evidence only as needed.
