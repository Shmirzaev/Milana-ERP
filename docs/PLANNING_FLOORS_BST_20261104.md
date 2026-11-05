# Planning, floor pictures and BST master reconciliation

Status: IN PROGRESS. User approved the reconciliation scope on 4 November 2026.

## Authority and boundaries

Original request: add a change-cutting-factory action in Planning; show available
printing pictures on department floors; replace BST current masters Oydinoy
Mamadaliyeva with Yoldashova Dilfuza and Shaxnoza Maxsimova with Axunova Xayotxon,
transfer connected workers and update flow names; deploy without timed 30-minute
monitoring. Later instruction: reconcile small features and deployed ECO features,
preserve clone_main work, keep database migration changes/execution separate and
obtain approval of scope first. The user approved the detailed scope in chat.

Source: clone_main 61cd16bd9591901e31f91682e26bc65a7cbe5c04. Dedicated worktree:
C:\ERP\.codex-work\planning-floors-bst-20261104, branch
codex/planning-floors-bst-20261104. Deployed ECO application source:
984aeffb22aedd3262d7cd61e2d88a905b589e8d; handoff d080957e8d596e64ce4a333f709a647546921e52.
Verified current production release 20261104_080711, manifest
0221829adfc216391679b744ae512b6c4d96913bb0316c31dfe12fb9a1641be7.
Recorded schema 0154_eco_receipt_details; compatible rollback 20261104_093330.

No new migration files, production migration execution or database stamping/downgrade
is authorized by this approval. Prepare a separate graph-resolution
proposal. Current migration graph is intentionally not deployment-ready.
Existing production business data, original employee identities, historical
production/payroll and unrelated clone_main work must remain intact.

## Ownership and operation ledger

Human ownership remains TEAM_OWNERSHIP.md: Planning Ismail/Mirshoir; Production
Mirshoir/Ismail; People Dilmurod/Mirshoir; integration/release Dilmurod/Mirshoir.
Codex root coordinates implementation and integration; independent agents review.
This does not claim any named human has performed acceptance.

| Operation | Implementation scope | Required evidence | State |
| --- | --- | --- | --- |
| ECO application reconciliation | Exact released feature diff, excluding migrations; manual integration of shared paths | Focused ECO/package/permissions tests, frontend checks, preserved-source review | Studying |
| Planning cutting-factory reassignment | Planning UI, typed action DTO/service/schema writes, scoped route and tests; no schema migration | Allowed/denied roles, destination access, evidence guard, no-op/retry, history preservation, actual UI/readback | Studying |
| Floor printing pictures | Department inbox projections/DTOs and floor UI, image-only attachments, existing access | With/without pictures and non-image attachments, department isolation, actual rendered UI | Studying |
| BST master handoff | Read-only discovery, exact reviewed before/after plan, guarded same-transaction update and tests | Current worker counts/flow mapping, old identities/history preserved, backup, CAS/locks, readback | Studying |
| Migration graph | Existing ECO and turnstile identities preserved; separate proposal only | Isolated graph/compatibility analysis; separate owner approval before changes/apply | Awaiting separate approval |

No operation is verified merely by source integration. Record actual commands,
PASS/FAIL/BLOCKED and evidence after implementation. All final combined changes
require independent review and appropriate automated, visual, persisted-data and
bounded integrity checks. Missing checks remain blocked. No production test data.

## ECO application integration checkpoint

Ported the exact 11f80a29 -> 984aeffb application/test delta, excluding all
backend/alembic paths. Shared files were three-way integrated, not replaced.
The sole text conflict was permission_catalog.py: retained attendance.provision
and added all ten ECO permission entries. All other clone_main paths remain.
Updated the stale production metadata to the verified active release; this is
documentation of the running state, not migration execution or a new deployment.

Checks on the ECO combined application checkpoint:

- PASS: 177 focused ECO receiving, approval, transfer, sewing assignment/handoff,
  package identity/origin and bounded query-growth cases.
- PASS: 63 factory permission, scoped grants, identity import-boundary,
  inventory schema-owned item creation and catalog collection-update cases.
- PASS: repository backend Ruff and compileall, frontend strict TypeScript;
  frontend lint has zero errors and 12 warnings.
- PASS: frontend ECO decimals/retry/locales, real user-access/Besttex/Sewing and
  hidden package-change-request contracts; Sales canonical-enum/mutation checks.
- FAIL (unchanged source): test:invoice-status-parity still expects a legacy
  string-literal PaymentStatus declaration, while clone_main uses the canonical
  type. Relevant script and customer page are unchanged by this reconciliation.
- An initial user-access script invocation from repository root failed because
  its imported Besttex check resolves src relative to cwd; rerunning from the
  required frontend directory passed. This was not an application failure.
- BLOCKED: actual connected-browser visual checks. Browser extension tab access
  twice failed with a timeoutMs property error. Documented Windows Computer Use
  fallback stopped because it could not establish the current URL confidently.
  No further UI input or workaround was attempted; no visual PASS is claimed.
- DEFERRED: ECO migration-source tests and full migrated PostgreSQL CI await the
  separately approved migration package. See
  MIGRATION_RECONCILIATION_PROPOSAL_20261104.md. No migration files were changed.

BST read-only discovery established a private before-state for the requested
master handoff. Exact production identifiers, roster membership and manager
relationships remain in ignored reviewed artifacts. The owner subsequently
confirmed Yo'ldasheva Dilfuzaxon and Axunova Xayotxon as the replacements; the
approved aggregate transfer is42/40 workers. Preserving payroll
rows does not freeze historical report grouping: existing payroll reports group
by current Employee.manager_employee_id. A current-roster transfer therefore
regroups past-period report views while retaining original payroll records and
amounts. No historical attribution/storage change is included silently.

## Narrow runtime candidate and integration refresh

The requested small features need no new schema. Separate runtime worktree
C:\ERP\.codex-work\planning-floors-release-20261104, branch
codex/planning-floors-release-20261104, starts from verified deployed984 and ports
only Planning, floor pictures and the guarded BST maintenance source. It retains
the exact0154 migration tree and dependency versions. User-authorized deployment
can continue only after required verification and the unresolved BST identity;
no second deployment authorization is invented. A future full-branch migration
merge remains separately held. Source preservation is not automatic deployment.

Origin clone_main advanced to4e17b4aa5 (PR398 catalog family approval). Merged that
five-path delta into this isolated source candidate without conflicts; three new
catalog operation tests passed. It stays excluded from the narrow runtime.
No shared integration branch was modified remotely.

Independent review of ECO application source b7b3707a1 found no source loss:
65 paths exactly match984 blobs, five equal the automatic three-way results and
the one permission conflict is the released catalog plus attendance.provision.
Independent floor review found and closed a model-fallback PDF selection defect
with six regression cases and a red/green witness. Planning review found stale
factory authorization in material/passport/command writes; refreshed PO->WO
interlocks and actual PostgreSQL race witnesses cover the corrections. Missing
work-order/batch-only history links are receiving final guard regressions.

The narrow candidate's build prerequisites and optimized102-page Next build
passed with exact locked16.3.8 dependencies. The first compile rejected an external
dependency junction; replacing only that verified task link with npm ci resolved
it without source/config/version changes. Root narrowed focused152 backend cases
passed, including41 HTTP and15 PostgreSQL Planning cases, plus27 BST PostgreSQL
cases (a fixture-only pay redaction then passed its targeted preservation case),
eight unchanged ECO PostgreSQL gates and49 floor/band/dashboard/schema cases.
These checkpoint counts belong to their named scopes; the full backend run and
the final optional-link guard follow-up are not yet represented as passing.

Browser verification remains BLOCKED. No worker transfer, live schema change,
source publication/remote merge or deployment has occurred. All four current
internal/public health checks returned200; source/manifest on both production
hosts remained20261104_080711. Neither timed monitoring nor a production business
form was run. Record final revision/results and remaining gates before handoff.

## Final source checkpoint before CI publication

The final optional-link guard covers WO-only waste/payroll/labels/reports,
batch-only package/allocation/payroll/report, assignment-only daily reports and
batch passport_actual_quantity. Independent final source review found no remaining
bounded-scope issue. Original recorded-evidence failures remain in the worker packet.

The broad narrow-runtime Windows run was interrupted at29% to investigate six
new constant-query assertion failures (Cutting bundles43vs42 and materials31vs30,
at1/50/401 rows). This was a real regression from an unconditional authorization
lookup, not an inherited baseline failure. It is fixed without relaxing any
assertion: retain the initially authorized department identity, refresh under the
PO->WO locks, and repeat authorization only when department identity changed.
The stale CUT->ECT request still refuses403. Independent reviewer reran all six
old query budgets and that PostgreSQL race successfully. Root final narrow run
passed109 cases (71 Planning including19PG,15 query-growth,23 artwork), zero skips.
The interrupted full run has no complete JUnit and is not called a full pass.

The CI candidate adds dedicated Planning19PG and BST27PG gates on job-owned
loopback PostgreSQL; BST creates its uniquely named empty test database and drops
it through EXIT cleanup only after successful creation. Frontend build now runs
both new component suites (9 Planning and14 artwork). No production DB is used.

The combined source branch retains every origin clone_main4e17b4aa5 change and
the deployed ECO application; it intentionally awaits separately approved migration
graph work and must not be merged/deployed as-is. Only the separate narrow984
runtime branch is prepared for publication/complete CI. At this source checkpoint
publication/CI results are pending; report actual remote state separately.

No production worker transfer or deployment occurred at this 4 November checkpoint.
The later [5 November checkpoint](PLANNING_FLOORS_CHECKPOINT_20261105.md) records
the owner's identity confirmation, actual connected Edge verification and explicit
visual acceptance. Backup, inactive-slot checks and cutover remain pending.
