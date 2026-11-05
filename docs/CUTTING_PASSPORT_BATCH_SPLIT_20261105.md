# Cutting passport: shared inputs, multiple stock batches — 5 November 2026

## Direct scope and source

The user requested one cutting information entry consuming the same-color fabric
from two batches, e.g.100 kg plus200 kg represented by one300 kg entry. The user
first chose a proposed screen, then explicitly said implement after viewing it.
The approved design has one set of cutting inputs and a source-batch split with
live totals, availability checks and a single passport output count.

User instruction remains: use production as base, integrate clone_main later;
no push/merge/deployment or production business-data creation is authorized.
Continue the clean dedicated worktree
C:/ERP/.codex-work/cutting-search-order-fixes-20261105, branch
codex/cutting-search-order-fixes-20261105, parent88f1d06c6. Earlier search/order and
ECO/Qolip fixes remain preserved. Both live hosts were rechecked on065721 at start,
exact base488f3d654. production-base.json still records predecessor043000, the
already disclosed mismatch explicitly overridden by the user's production-base
instruction. Fresh origin/main1a067b01 and clone_mainc5a0d2e4 stay separate.

Production engineering owner Mirshoir, independent human reviewer Ismail;
Inventory owner Ismail; business acceptance Shavkat/operator. Actual Codex root
owns frontend, integration and this packet; cutting_reject_backend owns the
backend operation and scoped tests. Independent Codex review follows source freeze.

## Intended contract and preserved behavior

- Optional batch_allocations on one PassportMaterial stores distinct batch IDs
  and positive quantities alongside one set of shared cutting calculations.
  The existing anchor stock_batch_id remains; ungrouped old passports work.
- Group only the same catalog item/color/unit with compatible known width/GSM.
  Do not average different physical fabric measurements. Preserve independent
  material entries for different fabrics or calculations.
- Total split must equal the authoritative actual usage rounded to0.001. Each
  physical batch remains checked, assigned/reserved, audited and traceable.
  Sources match the order's assigned materials after flattening; no cross-order,
  factory, permission or duplicate-batch bypass. Customer-supplied Usluga stock
  remains on its current path rather than guessed warehouse batches.
- Saving a passport records the split and existing reservations/Nastil output;
  it does not deduct stock. Cutting confirmation owns actual per-batch stock
  movements and the existing shortage/pending-consumption evidence and retries.
  Pieces, rolls and shared calculations must not be multiplied by batch count.
- Existing JSON storage is sufficient; no database migration, new permission,
  business state or stage transition is requested. New logic belongs in a
  Production service. Existing legacy route/service persistence debt is recorded
  explicitly; this feature does not claim full Production layer/type migration.

## Study map and verification plan

Trace cutting_passports routes/create/update/defaults/read/report, PassportMaterial
DTO and existing JSON column, cutting_passport_usage_service, material assignment/
replacement, stock usage/deferred shortage, cutting sheets, reports and Nastil.
Frontend must preserve edit/reopen/new-Nastil, independent added materials,
selected-size calculations, customer-supplied mode and EN/RU/UZ usability.

Required evidence: bug red/green and compatibility tests, meaningful HTTP and real
PostgreSQL save/confirm/refusal/retry/rollback/concurrency checks; actual connected
browser save/reopen100+200 and one600-piece output on disposable data; exact saved
split/stock readback and adjacent independent-material path; desktop/phone visual
inspection; bounded stress; full frontend build/TS and scoped lint; independent
source review. Missing required gates remain BLOCKED, never PASS. Human acceptance
and any future integration/deployment remain separate.

Next step: implement scoped backend contract and frontend shared-form batch split,
freeze runtime files, then verify the exact combined candidate and record results.

## Implemented operation and compatibility

PassportMaterial now has optional batch_allocations of2–1000 distinct physical
source IDs and positive finite quantities to0.001. The legacy anchor ID remains;
the service canonicalizes it first and obtains batch labels from inventory rather
than trusting displayed client text. Full labels stay in nested JSON; the joined
legacy scalar lot label is bounded to the existing64-character database column.
No table/column/migration or permission was added. Input→saved JSON→read contracts
use the same allocation DTO. This adds no fixed business-state vocabulary or enum.
Existing configurable units, factory/material IDs, status literals and legacy
JSON writers remain recorded debt, not completed system-wide typing/refactoring.

The new Production allocation service owns compatibility, exact total, factory and
stock-source rules and read projections. The existing transaction owners still
coordinate passport save, reservations, audit, Nastil and confirmation. A narrow
same-Session schema operation rewrites grouped JSON during pre-use batch replacement;
it never commits. Existing route persistence is retained deliberately, not broadly
extracted. Replacing a grouped source revalidates the complete group; consumed
allocations/calculations remain immutable. Grouped Cutting detail edits send only
notes through the actual UI; material controls are read-only. A linked grouped
Nastil cannot bypass its saved basis through raw amounts, omitted passport IDs,
the client use_passport_materials flag or deferred output.

Each group becomes separate physical CuttingMaterialUsage/stock-movement records.
Additive layer/beika/waste evidence is apportioned with an exact remainder; garment
pieces and rolls remain on the anchor once. Cutting scalar calculation summaries,
cutting sheet and passport reports retain the shared totals and both batch labels.
Legacy independent material entries and customer-supplied Usluga remain compatible.
Recognized cross-factory warehouse sources refuse; inherited assigned STR/NULL/
unmapped warehouse routing remains governed by existing order/work-order access.
This is not a blanket closure of historical factory or authorization audit risks.

Frontend retains independent Add material and adds Add batch to this entry, with
compatible assigned or inventory sources, editable quantities and live validation.
Removing an assigned source restores an independent entry; it never silently
disappears from the order or moves its quantity into another batch. Entire pending
entries remain removable. New-Nastil entry keeps source identities but clears its
quantities. Exact decimal arithmetic matches the ledger's half-even rounding.
Shared input, availability, mismatch and consumed-lock text supports EN/RU/UZ.
Cutting confirmation shows the saved100/200/300 source summary before submission.

## Browser and persisted readback

Actual connected Edge exercised the real Next/FastAPI app with PostgreSQL16 in
the owned loopback-only milana-passport-split-qa-20261105 container (15439), API8009
and frontend3099. QA public data contains dedicated actors, same-item red sources
QA-SPLIT-A/B (150/250kg stock,100/200kg reservations), a blue incompatible source,
one600-piece order and its stages. Generated model columns from existing0084 were
applied only to this disposable schema after create_all; no application migration
or production database changed. New private credentials/env stay outside Git.

PASS: actual UI combined the two assigned source rows, entered one operator,
12rolls,6kg/layer×50layers and600pieces, and saved QA-SPLIT-ONE. Entering90kg in A
showed290-vs300 mismatch and disabled Create;160kg showed its150kg stock limit.
Restoring100/200 enabled save. Reopening preserved one logical material entry and
both quantities. Actual English and Uzbek desktop/390px-phone views were visually
inspected; component/action checks also cover Russian. Retained screenshots are
outputs/qa/passport-batch-split-desktop-en.png, desktop-uz.png, phone-en.png and
phone-uz.png (each filename starts passport-batch-split-).

PASS: after save, API plus direct PostgreSQL readback found stock150/250, zero
Cutting records, one600-piece passport, one300kg material calculation and dashboard
300kg/12rolls/600pieces. After actual UI Cutting confirmation, stock became50/50,
with separate100/200kg consume movements and one600-piece Cutting record/bundle.
Physical usage evidence summed to600pieces and12rolls, not1200/24. Scalar layer
usage remained6kg. Reopened confirmed passport disabled split and shared inputs.
The actual Cutting detail UI saved a note with only notes in the request and kept
stock/calculation evidence unchanged. Non-secret phase readbacks are retained in
outputs/qa/passport-split-saved-readback.json and confirmed-readback.json.

PASS: final npm run build completed all configured regressions and optimized
Next production build. Normal TypeScript and scoped ESLint passed. New actual-page
handler tests cover merging, save payload shape, retained failed-save draft,
separation without source loss, pending singleton removal and notes-only Cutting
patching. Helpers/component tests challenge exact decimal ties, conflicting known
dimensions under an unknown anchor, unit mode, stock, precision, duplicate sources,
consumed controls and EN/RU/UZ rendering. Existing size/stale-response/meter suites
also pass. Build log: outputs/qa/passport-batch-split-final-build.log.

## Review and failures retained

Independent Codex review identified and corrected UI decimal ties, group-wide
measurement consistency, removable pending singletons, mixed consumed-row locks,
unit mismatch, canonical source order, actual notes-edit request shape, forged
saved-source bypass and long scalar labels. The baseline source rejected the new
100+200 shared entry; candidate tests prove the change. Early test fixture failures
included a doubled /api prefix, omitted0084 generated columns, inherited query
budgets needing the new bounded metadata query, and an invalid NULL order ID on a
NOT NULL reservation column. Corrected fixtures preserve those failures as history.

Existing per-source shortage evidence remains traceable if stock changes between
passport save and Cutting; duplicate confirmation still refuses. This feature adds
no new reconciliation UI for that inherited pending-consumption state. It does not
claim an all-source-shortage recovery action. The inherited common.noData i18n
checker failure and extension-injected browser hydration warnings remain as in
the earlier packets; no full i18n or zero-console-error claim is made.

Final backend counts, source fingerprint, closing readback and cleanup state are
recorded below after the frozen combined run. Human acceptance and integration/
deployment remain separate.

## Frozen combined result and closing state

PASS:163 distinct backend cases,4 inherited warnings,36.75seconds, including all
7 real PostgreSQL cases with no required skip. This total includes the63 broader
cases previously run separately; they are not added again. The final command and
module list are retained locally in outputs/qa/passport-batch-split-backend-verification.txt.
The suite covers save/confirm compatibility, exact per-source debit,4 competing
confirmations, row-lock wait/recovery, injected second-source rollback and retry,
shortage evidence, forged raw/deferred/omitted-passport refusals, long labels and
pre-use replacement. A1000-source helper challenge checks linear metadata size,
rounding totals and reversed sheet ordering; it is not a1000-user load claim.
PostgreSQL uses a unique isolated suite schema and distinct case data, not one
schema per case (clarifies the worker evidence wording). Ruff/compileall for all
12 affected Python paths and whitespace checks pass.

PASS: independent Codex source review found no remaining actionable blocker and
independently reran28 HTTP cases plus frontend split/notes/size/stale-response tests.
The14 runtime/configuration path aggregate SHA-256 is
0c980da9bcd9007375ebd886ab6119c7b89c178b8b8607e03d59661232388744,
verified again by the coordinator (sorted relative pathname,NUL,raw bytes,NUL).
The backend9-path aggregate is43a72aea1de47da832e73bfaaec6bc3b644992a2a5bfe00e0d0dac832788e291.
Documentation-only closing changes do not change these runtime fingerprints.

PASS: after final runtime freeze, the API was restarted and the coordinator
rechecked saved group, stock movements, usage/scalar totals and dashboard directly
against PostgreSQL. A notes-only HTTP edit remained200 with stock unchanged, and
the actual production-sheet GET included both canonical source names and100/200kg
amounts. Earlier connected-browser writes and final exact-source PostgreSQL tests
cover creation/confirmation; final readback also verifies the previously written
full-metadata record remains readable after the linear metadata refinement.

Both production hosts were rechecked and remain release20261105_065721 with the
retained043000 rollback. Fresh origin/main1a067b01 and clone_mainc5a0d2e4 do not
replace the user-selected production base. No production business data, schema,
settings, image, service or release changed. No push/merge/deployment occurred.

The owned Next3099 and API8009 processes were stopped. The verified PostgreSQL
container50569b0e/milana-passport-split-qa-20261105 and its anonymous volume were
removed. Automatic approval review rejected deletion of the two private QA JSON
configuration files, stating only blocked by policy; they remain under the named
TEMP folder and no alternate deletion mechanism was used. Its database is gone.
The browser viewport-reset request timed out; restoration was not verified.
Screenshots and non-secret evidence are retained locally under ignored outputs.

Compatibility limit for any future release: the new backend accepts old passports,
but older binaries do not understand grouped source JSON. A rollback or mixed-version
cutover needs explicit grouped-data compatibility review; absence of a migration
does not establish safe downgrade after real grouped records exist. No live group
was created in this task. All historical audit/security risks outside this operation
remain open as recorded in project context.

Status:AI_VERIFIED_AWAITING_HUMAN. Human checklist: group two same-fabric/color
batches, enter100/200, enter the shared cutting details once, save/reopen, verify
one300kg/600piece entry, then check exact source debits and one output after
confirmation. Verify incompatible materials remain separate and inspect the
desktop/phone layout. The final local commit is reported in the chat handoff;
earlier changes remain in parent88f1d06c6. Source integration and deployment still
await separate authorization.
