# Search, Cutting and order fixes — 5 November 2026

## Authorized scope and source

The user requested: fix search icons overlapping text; add Cutting order rejection
with a reason; remove the default 600 pieces when creating an order; show model
and variant numbers beside the package rows in shipment quantity review.
The user then explicitly directed development from production and deferred merging
with clone_main. No merge or deployment is authorized by this task.

Worktree: `C:/ERP/.codex-work/cutting-search-order-fixes-20261105`.
Branch: `codex/cutting-search-order-fixes-20261105`.
Base: production `488f3d654b0669a9878b8efd3d34298994e9dc45`, release
`20261105_065721`, verified on both hosts; manifest
`e6c603d4c1954c64a75962cf189427eb5e316c039ea23de4699b9bd4f3112095`.
All 1,905 manifest files match this checkout (allowing Windows CRLF conversion).
Rollback: `20261105_043000`. No production business data is changed.

## Ownership and operation map

Codex coordinates UI, integration and verification. A separate Codex agent owns
backend rejection implementation; a different agent must review the final diff.
Human domain ownership remains Production/Fulfillment Mirshoir, reviewer Ismail;
Planning Ismail, reviewer Mirshoir. This record does not assert human acceptance.

1. Shared `.input` CSS overrides Tailwind icon padding; preserve the existing
   layout and explicitly honor `pl-8`/`pl-9` for decorated inputs.
2. Cutting rejection: route -> dedicated production business service -> same-Session
   schema writes, existing WorkOrder rejected status/is_blocked/block_reason.
   Require permission, factory scope and nonblank reason; refuse produced or handed
   off work, preserve PO and downstream plans, notify Planning and audit. Reject
   retries must not duplicate evidence; no new vocabulary or migration.
3. Planning new/reset/model-size quantity defaults must remain blank until entered.
   Preserve entered totals and batching limits; do not change stored orders.
4. ShipmentReviewPanel reads existing preparation package model_no/model_code and
   variant_no. Display those identities with existing localized labels and variant
   formatter, including narrow screens. Quantity review writes remain unchanged.

## Verification and handoff

Record actual automated, isolated database, connected browser, bounded integrity
and independent review results here before handoff. Missing checks are BLOCKED,
never PASS. No production mutation, push, merge or deployment is authorized.

Human checklist: search text clears the icon; a fresh Planning order and selected
model have blank quantities; Cutting rejection requires a reason and remains
rejected after refresh; package quantity rows identify model and V-number in EN/RU/UZ.

## Backend Cutting rejection evidence

Actual implementer: Codex worker `cutting_reject_backend`; separate Codex reviewer
`independent_review`. Human Production owner remains Mirshoir, reviewer Ismail;
operator acceptance remains pending. Base is the production revision above. The
11 changed/new runtime and test Python files have aggregate SHA-256
`ddfd5371380fb679f52f232df3dcc58346630ee4775de58889a64d770bd78105`
(sorted repository-relative path, NUL, raw file bytes, NUL for each file).
The coordinator records the final combined commit after its own checks.

Contract: `POST /api/work-orders/{wid}/reject-cutting`, JSON `{"reason":"..."}`,
returns existing `WorkOrderOut`. Reason trims whitespace and requires 1–2000
characters; extra fields refuse. Any `cutting.records`, `planning.production` or
wildcard permission is necessary, plus selected source factory; Usluga requires
ECO. Closed jobs and any recorded production/passport/consumed material/downstream
evidence refuse with 409. Lock order is ProductionOrder, then all WorkOrders in ID
order, using NOWAIT; contention returns 409 and rolls back. Only the selected Cutting
WO becomes rejected/blocked with reason and end time. PO status, quantities, plans,
Nastils, reservations and downstream rows stay preserved. Same-reason retries are
idempotent; another reason refuses. Audit and the creator's Planning notification
commit together. There is no reopen action, schema migration, stock mutation or
reservation release in this feature.

Operation/type ledger: the reason is free text. New `production.WorkOrderStatus`
contains exactly the current WorkOrder CHECK vocabulary and is used by the new
operation/terminal guards. Existing mapped string storage, CHECK/defaults,
WorkOrderOut/Update DTO fields and other-stage consumers remain intentionally
unchanged; full WorkOrder enum/type adoption remains pending. The Production guide
and shared enum ledger explicitly record that boundary. Persistence for the new
rejection lives in `schemas/production/work_order_rejection.py`; existing audit
and notification services already use schema-owned writes in the supplied Session.

Final automated checks on the candidate:

- PASS: Ruff over all 11 affected Python paths and Python `compileall`.
- PASS: 157 cases across `test_cutting_order_rejection.py` (38), its PostgreSQL
  companion (11), existing work-order command/status tests and both Planning
  cutting-factory suites (108). Final repeat: 157 passed, four inherited warnings,
  18.09 seconds; no required PostgreSQL case skipped.
- PASS: HTTP reason/extra-field validation, anonymous/missing/stage/permission/
  factory/Usluga denials, execution-history refusals, same/different-reason retries,
  saved reason/audit/notification readback, full preserved downstream plan snapshots
  and audit-fault rollback. Existing mutations refuse rejected work, including
  start/complete/unblock/update, extra/split/update Nastils, Cutting output,
  passports, bundles, Quality and block reason overwrite.
- PASS: real PostgreSQL lock refusal at order/Cutting/Sewing rows, each below two
  seconds; ten simultaneous retry attempts with one audit/notification; cached
  start/update/Cutting/block/unblock/Quality requests refuse after rejection;
  notification-fault rollback after a real flush leaves all snapshots/evidence
  unchanged. Recovery retry then works.

Failures preserved: the first ten-worker test deadlocked its own barrier by checking
out all five pool connections before ten workers reached the barrier. Moving the
barrier before checkout corrected the test harness; the repeated real test passed.
Independent review found stale block/unblock requests could overwrite rejection
reason and Quality could still insert history. Added regressions demonstrated four
failures before fixes (HTTP Quality 201 plus cached PostgreSQL block, unblock and
Quality), then passed after the lock refresh and terminal guard changes. This is
red/green evidence, not a claim the initial implementation passed.

Isolation/recovery: an owned disposable PostgreSQL16 container
`milana-cutting-reject-qa-20261105` binds only `127.0.0.1:15438`. Test modules create
and drop unique synthetic schemas; real ERP databases were never used. Its public
schema contains separate synthetic browser fixtures: minimal configuration,
private QA users, one approved model, untouched CUT/ECT orders and a produced CUT
refusal order. An initial browser-fixture setup failed on omitted required
ProductionOrderItem.model_id and rolled back that fixture transaction; correcting
the fixture produced the saved public-schema cases. Browser credentials and API
environment are private temporary files outside Git. Keep the owned container
alive for the coordinator's real UI/readback checks; stop/remove it and its private
temporary artifacts only after that work ends. No production cleanup is required.
The coordinator records actual connected-browser/EN-RU-UZ acceptance separately.

## Integrated frontend and actual browser verification

Coordinator `/root` implements the UI; `/root/independent_review` is the independent
Codex reviewer. Its final review found no remaining blocker after the two backend
fixes and the final UI followups. This records AI evidence, not human acceptance.

- PASS: `npm run test:order-floor-fixes` executes actual Planning size redistribution,
  blank create/reset defaults, exact retained small totals, package model/variant
  React rendering and rejection controller refusal/retry/refresh-failure behavior
  in EN/RU/UZ. The check is now part of `npm run build`.
- PASS: strict TypeScript, scoped ESLint (zero errors; five inherited warnings),
  Planning cutting-factory12 cases, shipment preparation and the complete frontend
  build-contract chain. Optimized Next16.3.8 build produced102 routes. The final
  integrated build also passed after the last UI edits (exit0).
- PASS: actual connected Edge at `http://127.0.0.1:3098`, actual FastAPI8008 and
  owned PostgreSQL15438. The browser submitted a reason on a produced CUT order;
  the409 refusal preserved its entered text and persisted state. An untouched CUT
  order was rejected, reopened with its saved reason and hidden execution form.
  SQL readback confirms exactly one rejection audit, preserved PO/stage plans,
  unchanged produced control and unchanged shipment/package/stock reservations.
- PASS: actual Planning group creation in the disposable database, then model and
  variant selection and editable M/S size rows, all quantities blank with total0.
  The production form was never submitted. Existing history input measured36px
  left padding versus an icon ending28px after the input's left edge.
- PASS: actual scanned package review shows model `QA123` and `V-03` beside
  `PKG-REVIEW`; EN/RU/UZ text and390x844 phone labels were visually inspected.
  EN refusal and RU/UZ phone rejection dialogs were visually inspected. A first
  screenshot found table-inherited nowrap clipping; the local wrapper now resets
  whitespace and the textarea is a block. Repeated screenshots confirmed the fix.
  The temporary viewport override was reset.

Evidence is in ignored `outputs/qa/`: `persisted-readback.json`,
`cutting-refusal.png`, `cutting-rejected-saved.png`, `planning-blank-quantities.png`,
`shipment-model-variant.png`, RU/UZ phone package screenshots and RU/UZ phone
rejection screenshots. Screenshots show synthetic fixtures, never production data.

Limitations/failures are retained: ORM create_all omitted migration0084's generated
model columns, causing initial inbox500s. Only the owned QA schema received the
existing0084 expressions; no application/schema migration was added. QA addresses
using the reserved `.invalid` domain failed actual EmailStr login422; only synthetic
login addresses were corrected. Browser console reports extension-injected
`bis_skin_checked`/`bis_register` hydration differences; no zero-console-error claim
is made. Existing shipment tables remain horizontally scrollable on phones.
The repository i18n checker fails on inherited `common.noData` in unchanged
PlanningCuttingFactoryAction (confirmed in base488); it is not a regression here.
Initial build attempts refused absent/HTTP-public API configuration, and a renamed
legacy dependency junction accidentally entered TypeScript's scan. An exact
lockfile dependency install and moving that link outside frontend resolved local
setup; the actual optimized build then passed. Automatic command review refused
local production-mode start commands; the safe loopback dev server supplied actual
browser QA. No production runtime or security setting was modified.

Status: scoped AI_VERIFIED_AWAITING_HUMAN after final integrated checks. Human
checklist remains above. No push, merge, deployment or production business write.

## Closing state

Final integrated optimized build, strict TypeScript, scoped ESLint and whitespace
checks passed. Both production hosts were rechecked and remain on065721 with the
same manifest; no production changes occurred. The loopback QA frontend/API were
stopped, the exact owned PostgreSQL container and its anonymous volume were removed,
and temporary credential JSON files were deleted. Screenshots and non-secret
readback/build evidence are retained locally. The temporary legacy dependency link
is outside frontend under ignored QA outputs; the candidate uses its own lockfile
installation. No push, source integration or deployment occurred.
