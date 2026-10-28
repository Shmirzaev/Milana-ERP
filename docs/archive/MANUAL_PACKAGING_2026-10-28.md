# Manual packaging and employee duplicate check — 28 October 2026

## Scope and source

Owner request: add manual pack creation/label printing in Packaging like the
physical warehouse pack form; inspect duplicate Akbarova Dilafruz names; base on
clone_main. Owner correction: keep employee numbers 321 and 503 separate, find
another duplicate; reconcile live production into an isolated candidate; do not
interrupt ongoing refactoring. Deployment was initially unauthorized; the later
explicit blue/green release authorization and outcome are recorded below.

Worktree: `C:/ERP/.codex-work/manual-packaging-20261028`.
Branch: `codex/manual-packaging-20261028`; integration base `c22c88e2`.
Imported release lineage: `fc2664b5`, runtime `ed47ab8d`, live
`20261027_115452`, recorded rollback `20261027_104106`. Both VM source manifests
verified clean and hash `8b8be7776fece64fc01163052efafc76370516faa4b186f5509fbcc1357a8f90`.
Released payroll helpers/DTO/persistence are ported to the current namespaces;
the shared refactor checkout, branch and workers remain untouched.

Engineering owner: Mirshoir; human reviewer: Ismail. Implementation: Codex root.
Independent AI reviewer: Codex subagent `/root/review_manual_packaging`, a separate
agent. Human review is not yet performed. People owner: Dilmurod, reviewer Mirshoir;
master correction was subsequently authorized and is recorded below.

## Operation and acceptance

MANUAL-PACKAGING-20261028: packaging actor selects an approved standard model,
color, weight and 1–200 pack quantities (1–10,000 each), saves immutable manual
source evidence, packed packages/items, stock backed by that packaging evidence,
and one exact print run. No production order/output is invented. Warehouse receipt
remains separate; pending packages must not be reservable or dispatchable. A retry
returns the same run; changed payload, cross-factory access and invalid models
are refused without partial business writes. Label failures must preserve the
saved result/reprint path. Existing physical warehouse receipt is unchanged.

Route -> `models/packaging/manual_packages_service.py` -> typed packaging DTO ->
`schemas/packaging/manual_packages_persistence.py`; audit and idempotency use
their current schema-owned writers and the same Session. Existing label rendering,
print-run resolution and warehouse receiving remain authoritative downstream.
Frontend reuses ManualPackageReceipt in an explicit packaging mode on Packages.

Value ledger: model/color/size/reason are configurable/free text; quantities and
weight are bounded numeric data. Department and package lifecycle use canonical
enums. Manual evidence source is an internal operation discriminator. Unaffected
warehouse/production operations retain their current implementation and gates.
No schema/table migration or full-domain refactor is in scope.

## Employee inspection

Live read-only SQL found only two Akbarova Dilafruz records: MIL employee 321
(row 313) and 503 (row 129). Normalized-name comparison across all factories found
only that pair and the historically distinct Jo'rayeva Zulfiya pair. No other
Akbarova Dilafruz duplicate was found. The later master correction supersedes
the initial read-only scope; no payroll or attendance history moved.

## Authorized master correction applied

Owner subsequently requested switching employee-master assignments from #503 to
#321 while preserving both identities. Exactly two reports were found: employee
rows 1581 and 1587. Reviewed operation commit `fe4bc0f8`, script SHA256
`168997ab25fea23bf0af9fcfb213e0d958837f3ddb5f688e43a9bba8cb26c30b`.
Real isolated PG rehearsal/commit/stale-plan tests and independent review passed.

Initial broad hashing aborted a live rollback rehearsal due to concurrent factory
activity; no apply occurred. Final script uses READ COMMITTED, bounded timeouts,
exact employee/ancestry locks, custom-trigger/rule refusal, locked identity checks
and low-32-bit own-transaction attribution across 95 other business tables. Its
before-commit verifier runs after actual audit finalization; the rollback rehearsal
exercises these same commit hooks before raising a private rollback sentinel.
Final live rehearsal passed. Apply transaction `1870873` changed only the two
manager pointers 129 ->313 plus timestamps and audits 144572/144573. Fresh-session
readback verified both identities, the two links and audit hash links. All four
internal/public health/login checks returned HTTP200. No deployment or migration.

Verified 0600 backup: `/opt/milana-erp/shared/backups/milana_erp_pre_master_reassign_20261028_100334.dump`,
95,513,412 bytes, 1,246 restore objects; SHA256
`f34f872c150a9cd4d518b394a2622b051f518ba845f08dcaeaa54329b3f7e4eb`;
restore-list SHA256 `27353051f9eafa2d00ff9a6cc46a3159cc4234d20505e5063967ecd4a20a77c3`.
Durable correction mirrored to the named Obsidian note. Any undo must narrowly
restore these two links after checking for later edits, never restore the whole DB.

## Packaging checks and remaining gate

Status: IMPLEMENTED, print visual gate BLOCKED; not AI-verified, not human-approved,
initially not pushed/merged/deployed. The later production release below
supersedes publication/deployment status. Independent review found no remaining code blocker.
Earlier recovery, repeat-entry and pending cancellation defects were resolved.
Cancellation is available from persisted list rows after reload, preserves source
evidence, retires every label of that run, and refuses received/used/cross-factory
packs. Reused deletion/retired-number writes now use schema persistence.

- Affected backend suite:146 passed, zero skips, including new create/validation,
  factory/permissions, retry/recovery, second-pack rollback, cancellation/list data,
  existing warehouse/first-grade behavior and imported label/payroll regressions.
- Disposable real PostgreSQL:26 passed, zero skips. Four simultaneous same-key
  calls plus20 replays created2 packs,1 run and1 audit. Six distinct concurrent
  requests conserved12 packs/66 pieces. Includes the master actual commit and23
  imported payroll contention cases; cluster stopped after completion.
- Removing the new factory guard via a private process-only pytest plugin caused
  all3 relevant refusal assertions to fail; restoring it passed all3. Runtime
  source was not mutated by the fault plugin.
- Optimized frontend build and prerequisite contracts passed; normal/strict TS
  passed. Full lint:0 errors,12 existing warnings. Scoped frontend lint, backend
  Ruff and diff whitespace checks passed.
- Connected Chrome exercised actual Next/isolated API:Packaging login ->2 packs
  (8+3) ->success/reprint ->reload ->business WMR/model references ->persistent
  cancellation confirmation (dismissed). Automated tests cover actual deletion.
- Warehouse-role browser scanned one pack and received the exact2-pack run with11
  pieces. Fresh SQLite readback verified2 received packs,2 stock rows/11 pieces,
  1 received run and2 receipt scan logs, with no duplicates. Captured browser
  warning/error log was empty.
- Label endpoint/reprint HTML tests pass; UI opened the generated print preview.
  Browser policy refused inspection of its blob URL. No alternate transport or
  surface was used to evade this refusal. Visual print inspection remains BLOCKED;
  no AI_VERIFIED_AWAITING_HUMAN claim is made.

Local logs/readbacks, form/warehouse screenshots and backup/rehearsal/apply/fault
metadata are in ignored `outputs/manual-packaging/`. No production pack/stock/order
was created. Shared refactor checkout/branch remain untouched.

Human checklist:inspect label preview/physical output; repeat manual creation,
reload, scan/receipt and mistaken-run cancellation on isolated data; record visual
and business acceptance. The owner later explicitly authorized deployment; no shared-branch merge or
human/operator acceptance is claimed.

## Later authorized deployment

Manual Packaging is included in active blue `20261028_123531` (`a0cb9d8b9fdab64dd751e7f3da7a1fa832779780`).
Green `20261027_115452` remains ready for rollback. Full combined validation and
verification limits are in [the release record](MANUAL_PACKAGING_RELEASE_2026-10-28.md).
The shared refactor line was preserved; label physical-output acceptance remains pending.
