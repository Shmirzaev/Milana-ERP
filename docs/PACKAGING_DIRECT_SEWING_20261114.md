# Direct Sewing to Packaging — 14 November 2026

## Scope and baseline

Owner request: "Remove save packaging record part as well so anything out from
sewing will be ready for packaging, and check fully packaging workflow after that
and tell me how it is working and what is not making sense". This applies globally,
not only to the example work order. The earlier seven-fix deployment was withdrawn;
this request authorizes implementation and review, not deployment.

Engineering owner: Mirshoir. Named human reviewer: Ismail. Business acceptance:
Shavkat/operators. Codex coordinates implementation; separate Codex agents provide
backend implementation and independent review. No human participation is presumed.

Dedicated worktree: `C:/ERP/.codex-work/factory-workflows-20261113`, branch
`codex/factory-workflows-20261113`, clean starting HEAD
`1f2329ab3e75f49bb1bed612855efe09ff596cbc`. This continues the investigation branch,
which contains withdrawn code; it is not the active production source.
Fresh fetch: `origin/clone_main` is `3053788f2e17bd5585bccf8cd4547a62cc297516`.
The retained live source adds the three documented November 11 commits to that
integration line. `deploy/production-base.json` records release `20261111_115200`,
source `46ddd5c7864f0a68bd9a3c884d835a2a5dbf9bfb`, schema
`0156_variant_price_workflow`; public `/health` agrees with that release on
14 November. The last full two-host verification is the recorded November 13
rollback. Fresh host verification is unavailable because the local credential
source is absent; no deployment is attempted or claimed.

## Operation and acceptance criteria

1. Passed Sewing output appears automatically in the correct factory Packaging
   queue and can be selected as a source, without acceptance or a separate saved
   Packaging record. Failed Sewing pieces do not increase availability.
2. Select an exact Nastil, or explicitly selected same-department Nastils, and a
   number of packs. Create only those packages/labels; leave the remainder.
3. The existing package creation transaction records only any newly needed
   Packaging evidence and the requested packages/allocations/print run together.
   Existing saved unlabelled output is used first. GET requests never create stock
   or physical evidence. A rejected action, race or retry cannot duplicate output.
4. Labels retain the existing provisional finished-goods rows. Warehouse receipt
   validates package/label evidence and enables warehouse use; provisional rows
   alone do not establish warehouse receipt. Reprinting creates no extra packages.
5. Trace partial packs, batch ownership, corrections, returns, first/second grade,
   Usluga, payroll and completion; preserve supported behavior or record exact
   unresolved limitations. Do not silently invent policy for ambiguous grading,
   damage, color or size evidence.

No migrations, backfills or production business-data writes are planned. Existing
record API/history is retained for compatibility, correction and audit; its form
is removed from the normal Packaging page. Package creation uses the existing
permission and idempotency operation, with explicit direct workflow context.
Damage may be recorded with single-source labels or through a narrow idempotent
damage-only action; a wholly damaged batch never requires a fabricated package.

## Implemented operation and caller coverage

The normal order page no longer has the Save Packaging Record form or its POST.
Passed Sewing pieces appear automatically as ready, excluding Sewing damage and
all historically consumed Packaging input. Select a Nastil, capacity, actual size
contents, weight and pack count (1–200). The preview shows exactly what will be
created. Allow a partial pack controls the final requested pack; all other pieces
remain available. Explicitly selecting at least two same-department Nastils allows
mixed packages, with each source quantity retained in allocation history.

Pack and create labels uses one keyed transaction: reuse saved unlabelled output,
record only newly needed good/damaged pieces, consume packaging BOM, record waste,
update counters/status, create packages/allocations and create one print run. A
partial direct action starts the work order automatically; final output completes
it. Record damage only creates evidence and waste without a package, print run or
finished-goods row. Lost responses are reconciled; cross-action pending requests
are mutually exclusive, so a damage retry cannot repeat through the other action.

First/second grade on this order page passes the same direct context and retains
strict actual-size and stock-grade guards. Where old Sewing data lacks sizes,
grade entry still requires the existing size confirmation; that is not Packaging
acceptance or a saved Packaging record. Ordinary packing permits the operator's
configured recipe when actual size evidence is incomplete and explicitly asks
them to check contents. Known actual size totals are enforced when complete.

The queue keeps old saved-but-unlabelled goods visible. Its Packed column counts
physical output, while Ready to pack also includes unlabelled saved output;
therefore old records can show 240 sewn / 75 packed / 240 ready before any labels.
This is reuse, not another 75 pieces. A future wording improvement could distinguish
ready to label from unprocessed Sewing output. Usluga retains its own confirmation
and customer-owned-goods flow, without warehouse print runs.

Warehouse receiving remains separate. Actual scanning of the test print run
received only that run's 60-piece package; the next 35-piece package stayed packed.
The received package was placed in A01/S1 and reopened with its QR and history.
Creating labels retains provisional finished-goods accounting rows; receipt and
eligibility gates determine warehouse use. Reprinting does not create packages.

Legacy saved-record APIs/history remain for compatibility and corrections. Shared
output recording is now service-owned with schema-owned insert/counter/start
writes. Existing BOM, waste, audit, notification, workflow, package and idempotency
writers remain explicit extraction debt, sharing the outer Session/transaction.
Canonical PackagingDepartment and WorkOrderStatus are retained. Existing stock-kind
Literal, free-form package type, wrapper operation strings and the damage result's
safe four-field raw projection remain typed-contract debt. No whole-domain enum,
persistence or payroll-completion claim is made. No schema/storage change.

## Exact-source evidence

Runtime frozen patch is relative to `1f2329ab3`, not production. Backend: 21 paths,
manifest SHA256 `e84dcefd706f37d25f078a08c647ec9e170bd81b98fc5d2e244b3bf82e6e3ef5`.
Frontend: 546 source files, manifest SHA256
`37a1c5985586a990c3674d74d661094629872702af9724ffb2c25027d8211ef5`.
Independent reviewer `/root/eco_fabric` verified every hash with zero drift and
found no remaining introduced runtime issue. Implementer `/root/packaging` owned
backend changes; `/root` owned frontend, connected-browser checks and documentation.
These are separate Codex sessions, not named human approvals.

Evidence is retained locally under ignored
`outputs/direct-packaging-qa-20261114/`; logs and fixtures are not published.
No credentials or business records are included in this packet.

| Gate | Actual result and evidence |
| --- | --- |
| Focused backend | PASS: 137 tests, 49.44s, `backend-focused-final.log`; direct action, grade, automatic queue, Sewing quantities, print runs, multi-Nastil and query-growth regressions. |
| Adjacent backend | Initial 215 pass / 2 fail / 5 optional PG skips, `adjacent-backend-initial.log`. The two old queue expectations were narrowly updated for the approved saved-plus-new balance; those two pass in `adjacent-queue-corrected.log`. The five skipped cases were subsequently run on real PG below. No full-suite claim. |
| Mandatory real PostgreSQL | PASS: 4 tests, 7.11s, `direct-pg-start-final.log`: eight distinct-key requests conserve availability, eight same-key retries create one result, atomic failure/recovery, concurrent Sewing-defect and Packaging handoff, partial start and failed-action status rollback. |
| Reserve PostgreSQL | PASS: all five initially skipped competing-reserve/release/dispatch/damage cases, 6.32s, `adjacent-reserve-pg-final.log`; owned UUID schemas only. No relevant PG skip remains in this bounded selection. |
| Test validity | Pre-change page fails the removed-form assertion in `frontend-before-regression.log`. Direct partial status old body: four failures / one legacy control pass in `direct-start-red.log`. Exact old Sewing callable deterministically raises PostgreSQL DeadlockDetected in `sewing-lock-red.log`; current PO-first ordering passes. |
| Frontend checks | PASS: actual page-render/submit tests, 2,500 mixed-quantity scenarios, 1,000 grade-weight cases plus eight faults, idempotency/recovery including simultaneous cross-action attempts; changed-path ESLint and TypeScript without incremental cache. |
| Frontend production compilation | PASS: exact-byte fresh source build, default Next/Turbopack, two workers, exit0, `frontend-hermetic-build.log`. Manifest rechecked with zero drift after build. Earlier default-cache builds failed after the disk incident; those failures are retained, not reported as passes. The build's preceding script chain had passed separately. |
| Backend static/integrity | PASS: Ruff backend/app without cache, changed-Python AST/nonzero checks, source manifest and diff whitespace checks. |
| Connected Edge browser | PASS on isolated localhost UI/API/PG: admin and Packaging-only navigation; automatic ready output; exact requested count; full/partial toggle; selected mixed allocation; all-damaged batch; first grade; grade cache refresh after ordinary packing; warehouse scan/placement; reopen persisted status. Viewed screenshots are listed below. |
| Database readback | PASS: read-only SQL over the owned fixture database. Final ordinary/grade case: sewn95, packed71, remaining24, three packages1+60+10, status in_progress. Full/partial case:60+35 packages, only60 received. Mixed case: one60 package allocated35+25,15 left. Damage-only case: input95/damage95 with zero packages or stock. `browser-readback-final.json`. |
| Printed label popup | BLOCKED: the browser control layer rejects blob URLs. No alternate surface or policy workaround was attempted. Normal HTTP package detail and saved QR images were viewed; actual popup layout and physical print/scan hardware are not verified. |
| Human / merge / deployment | NOT PERFORMED. Overall completion/release gate remains BLOCKED by printed-label visual verification; do not label the whole task AI_VERIFIED_AWAITING_HUMAN or release-ready. |

The feature skill requires: "Missing browser access or a required test environment
is BLOCKED, never PASS" ([exact instruction](../.agents/skills/milana-feature/SKILL.md)).
This is the reason for preserving the narrow outstanding visual gate; it does not
require another deployment permission question or block recording reviewed source.

## Connected-browser records and human checklist

Local UI `http://127.0.0.1:18943`, API18942, PostgreSQL55441, database
`milana_direct_packaging_qa`. Container/host guards are in the ignored fixture
helpers; no production connection or business-data creation occurred. QA records
are disposable, were not reseeded during verification and remain for review.

Viewed and saved: `direct-ready-95.png`, `mixed-created-60-left-15.png`,
`warehouse-received-60.png`, `damage-only-95-no-labels.png`,
`direct-packaging-status-final.png`, `direct-packaging-form-final.png` and
`packaging-only-queue.png`. Final status was reopened after a new10-piece action
to prove the status correction, not merely inferred from tests. Packaging-only
queue shows remaining24/15 and the two untouched saved-output cases at240 each.

Ismail/QA master and operators should repeat on the identified candidate:

1. Start with new passed Sewing output and no Packaging record. Confirm automatic
   queue entry and no acceptance/Save Packaging Record step, using the actual role
   in each factory. Confirm another factory's sources cannot be used.
2. Select a Nastil, create only one requested full pack, reopen it and confirm the
   source remainder and in-progress status. Repeat with partial disabled/enabled,
   selected mixed sources, actual sizes, grade entry and all-damaged output.
3. Open the actual generated label popup, inspect QR/barcode, batch/quantity,
   grade/weight and print on the production label stock. Scan using factory
   hardware; reprint and confirm no new package/stock. Tablet/phone usability and
   all EN/RU/UZ interactions still need operator visual coverage.
4. Receive only the selected print run, place it and confirm other runs stay packed.
   Repeat return/correction, Usluga and material-shortage cases with agreed policy;
   their backend regressions ran, but those full UI paths were not repeated here.
5. Record candidate, role, expected versus saved results and approval/rejection.
   No silence, prior deployment approval or historical e538 test grants acceptance.

## Existing behavior that does not yet make sense

1. Packaging BOM consumption allows insufficient inventory (`require_available=False`).
   It may consume only available stock or produce an unbatched movement. Atomicity
   is preserved, but a material shortage does not block packing. Strict shortage
   policy needs an explicit stock/operations decision and a separate correction.
2. Old records can have input greater than packed plus damaged (for example,
   input318 / packed240 leaves78 unclassified). That input is already consumed;
   treating78 as fresh Sewing would double-use it. No operator finalization path
   was found. New actions avoid creating such WIP; old rows need reconciliation.
3. Mixed-source allocations store piece quantities by batch and package contents
   by size, without an exact size-by-batch matrix. Exact per-batch size provenance
   cannot be proven from this storage; it is not silently inferred from the plan.
4. Cancelling/deleting a material-linked package is blocked until BOM usage is
   corrected, but no complete operator reversal path was found. Keep the guard;
   implement a traceable material reversal instead of bypassing it.
5. The shared product header still says Received / bundles although direct
   Packaging no longer has an acceptance gate; the queue's Packed versus Ready
   wording can also confuse old saved output with labelled stock. These are
   presentation debts, not evidence that acceptance remains mandatory.

## Handoff and production safety

Active production remains release115200/source46ddd; withdrawn094409/e538 remains
off traffic. No deployment, migration, backfill, production fixture, deletion,
backup restoration, payroll payment or production stock mutation occurred.
Do not deploy this investigation branch as a packaging-only release: it contains
the six other withdrawn feature changes in its ancestry. Before a future release,
reconcile active production, clone_main and the reviewed patch in a clean staging
checkout, complete the remaining gates, and obtain fresh owner deployment approval.

A disk-full build incident temporarily truncated one root-owned frontend helper.
It was restored atomically from the baseline plus reviewed edits, then checked by
regressions, exact-source manifests, independent review and the fresh successful
production compilation. Docker Desktop was restarted to recover owned local QA;
no production service was restarted. Avoid deleting unrelated work/build data.

Source commit/publication status is recorded at handoff. No merge or production
retirement of the legacy API is authorized or claimed by this packet.
