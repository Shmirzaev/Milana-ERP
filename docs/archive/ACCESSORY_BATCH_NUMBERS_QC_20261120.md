# Accessory batch numbers and QC controls — 20 November 2026

Owner request: replace the imported `MIL-OPEN26-...` batch labels with only
four-digit numbers, and remove the QC status requirement for accessories.
The owner requested Edge for actual browser verification and signed in there.
No application deployment or merge has been authorized in this follow-up.

Scope: 759 opening-import StockBatch identities, original IDs2189–2947 in Milana
Accessory Storage2/STR. The reviewed mapping binds every ID to its old label,
item/SKU and source key, checked against the original import manifest SHA-256
`5d0d727e6b3032c0d24aa7550e5a3778bc1b7a67e8f5809690c387a86189a30d`.
New labels range1000–1818, skipping labels already used anywhere in batch_no or
internal_batch_no, including archived stock. No stock, item or linked business
record is created or deleted. The mapped change is batch_no plus the ORM's normal
updated_at timestamp; quantities, valuation, QC, provenance, warehouse and linked
inventory facts must remain unchanged. Append-only audits retain old/new labels.

Inventory engineering owner: Ismail; default human reviewer: Mirshoir; operator
acceptance: Shavkat. Coordinating implementation/reviewer: root Codex session.
Independent agent accessories_review implemented the two frontend changes and
reviewed the operational correction; root independently reviewed the UI diff.

Initial isolated base65c861c matched release20261119_122457_44523647780_1. Another
engineer's release became live during preparation. The guard refused before plan
construction or business writes. Both fresh source links/manifests then verified
release20261120_040300, source98130821354f487767a9b79f56482f1788ac4c40, manifest
`7e888254a16e7c8ff277d99c4eff29a8a0f40c149aa3229987074232badcabb7`, schema0159.
The owner's prior explicit verified-production-baseline exception applies.
The active container is milana-backend-blue. No traffic switch is part of this task.

## Operation and interfaces

The one-time runner supplies reviewed code in memory to the exact live image;
it installs no runtime files. Business operation -> existing access checks and
schema-owned `set_batch_number` -> StockBatch; normal `log_action` appends audits
in the same outer transaction. Only this supplied Session commits. A table lock
protects label collision checks. Both production host/database and loopback QA
host/database are explicit; fault/rehearsal mode is refused against production.
Full stock/items/movements/reservations/manual-issue fingerprints are compared
around the operation, excluding only authorized label/timestamp columns.
Immediate readback/retry checks that complete snapshot. Legitimate later
inventory activity can make that deliberately strict retry refuse; it cannot
create a second rename operation. Historical audit-chain repair is outside scope.

Accessory UI change: hide QC selectors on receipt, return and edit, omit QC from
their request payloads, and remove QC header/detail text from accessory inventory.
Fabric controls/payloads remain unchanged. Existing backend create DTO defaults
omitted QC to pending; correction exclude_unset preserves a stored status. No
passed inspection is fabricated. Existing pending/passed allocation eligibility
already permits these imported pending batches; held/rejected/failed stock stays
blocked. QC enums, database constraints and history are retained. There is no
new enum, state, permission or migration.

## Gates and current evidence

Frozen mapping and private receipts: outputs/accessories-batch-numbers-20261120.
Actual Edge pre-change readback matches the supplied zipper screenshot, correct
warehouse, provenance and pending QC. Root reviewed both frontend diffs. Focused
behavior checks exercise actual rendered form/JSX and payload functions; source
contracts and targeted ESLint passed under cached tooling.

Exact local dependency installation hit ENOSPC on C:. Automatic approval review
rejected cleanup of this task's partial node_modules with “blocked by policy”.
The owner was asked to free space. Original legacy dependencies/source remain
untouched. Full typecheck initially found only missing cached Daypicker modules;
exact dependency/build and actual candidate-browser gates remain unpassed.

Pre-correction backup:
`/opt/milana-erp/shared/backups/milana_erp_pre_accessory_renumber_20261120_041159.dump`:
133,979,061 bytes, mode0600,1,403 restore objects, SHA-256
`1469b6920e2ddce2a5cae50a0ee353ea230ce537367f687eeca54f95cb7238c7`;
restore-list SHA-256 `e1cc3dd08b530ca8491da9cb25ca1f41de1609031ea39130ed5b5ab19ff56e4e`.
Apply requires a reverified matching backup at most30minutes old, bound QA,
unchanged plan and operation hashes, committed operation source, and live release.

Required data gates: isolated restored-copy valid-hash identity/duplicate/source
refusals, both batch/internal-label collisions, deliberate fault rollback, full
rehearsal rollback, apply/readback,760 linked audits, identical retry, then exact
production readback, actual Edge label verification and four health checks.
No production rename has occurred at this preparation checkpoint.

The isolated restored-copy QA subsequently passed every data gate above,
including rehashed identity/source tampering and collisions in both label fields.
The private PostgreSQL container was removed. Independent source/plan review
found no remaining blocker. The canonical plan hash is
`76c73d79e89076857517afb30cc40679d0c9edd6b196803a081fbcd0bc575cc5`.

Human checklist: verify four-digit labels and readable accessory rows, verify
receipt/return/edit have no accessory QC selection, and confirm fabric QC is
unchanged. Application release/deployment approval remains separate.

Worktree: C:\ERP\.codex-work\accessories-batch-numbers-20261120.
Branch: codex/accessories-batch-numbers-20261120.

## Applied data correction and UI candidate status

The reviewed patch was rebased onto exact live source98130821354f487767a9b79f56482f1788ac4c40
without an inventory source conflict; operation commit
`c5b75a429cabd2877a65c388214750edf0a2d496` is pushed, unmerged. Git converted
new operational files to CRLF, so their raw hash bindings changed. Full isolated
restored-copy QA was repeated against these committed bytes and passed before
production apply. No receipt/hash was edited to reuse earlier evidence.

Live apply succeeded once:759 numbers changed; completion audit292390. Immediate
read-only verification confirmed759 unique targets, no old import labels,760
valid linked audit rows, and the same complete preserved inventory fingerprints
as before. Edge showed zipper labels1522,1544,1649,1493 with original900/600/500/1900
piece balances, zero costs, source keys and warehouse. Screenshot retained at
`outputs/accessories-batch-numbers-20261120/live-four-digit-batches.png`.
Current production still shows QC labels, as the UI candidate is not deployed.
Captured console errors were browser-extension M_ID failures, not ERP scripts.
All four internal/public health/login checks returned HTTP200. Active/rollback
application files and traffic were untouched by this correction.

Hosted CI44673085261 passed exact locked-dependency lint, strict typecheck and
the new accessory test. Its node-only frontend step failed an inherited Lucide
namespace guard: the current baseline includes the CEO test fixture's namespace
import, but the guard only permits the Besttex test fixture. Both involved files
were unchanged by the accessory patch. The narrow follow-up adds that exact
existing fixture to the test-only exception list and normalizes Windows path
separators; application namespace bans and SVG export/render checks remain.
Local verification rendered112 real SVG exports from421 imports successfully.
The original failed CI is retained; this does not establish a full build pass.

The owner's requested QC UI removal remains a source candidate with separate
application deployment/actual candidate-browser gates. Data verification does
not constitute feature deployment or human UI acceptance.

## Disk recovery and current candidate

The owner authorized retrying cleanup and removal of unimportant files. Free
space had recovered to4.7GB. Automatic review again refused deletion of the
task-local partial dependency install. A non-destructive move preserved that
ordinary, non-linked directory under ignored
`outputs/accessories-batch-numbers-20261120/partial-node-modules-preserved`;
no broader cleanup or deletion occurred. Fresh exact `npm ci` installed402
packages successfully. Exact dependency versions include Next16.4.6 and
React/ReactDOM19.2.8. Full typecheck, strict typecheck, lint (existing warnings),
accessory form/payload checks, receiving/supplier/roll-weight contracts and
112 real Lucide SVG exports passed. Independent review repeated those checks.
Full `npm run build -- --webpack`, including its prerequisite contracts, passed.
A second compile changed only the loopback QA API port after Windows refused
the first port; it also passed. No application source was changed for preview.

Another owner task released20261120_042800 / source
`9f64146d4d5b8e523d71fb6c3483c02118d32acb`, manifest
`413aa746515609a15a16ee4ce1d94beb3af58768f30fda051fcca565b8438544`.
Both fresh source manifests verified. It changes no accessory page. The bounded
candidate merged that exact source, resolving only the project-context conflict
by retaining both task records and qualifying the historical040300 deployment.
Candidate `f0790b0565eab371b6212fcfbf681b11011514a5` is pushed, unmerged into
the shared branch. CI44675585763 has failed (details below). The historical applied renumbering
scripts and their040300 guards remain frozen; they must not be rerun.

Visual QA uses the actual optimized Next.js candidate and a loopback-only
synthetic backend, with no production connections, credentials or tokens.
The synthetic identity is clearly named QA Preview. The fixture server started
on127.0.0.1:3260; non-fixture writes are refused. Automatic approval review
rejected starting the Next preview with its required API environment setting,
stating “blocked by policy”. The owner was asked to start this local preview
manually so Edge verification could finish. The owner could not run it and
explicitly instructed the agent to do so. Retrying the required startup command
was again rejected as “blocked by policy”. No alternative wrapper or tool was
used to bypass that rejection. The temporary synthetic backend was stopped;
there is no running candidate preview. Actual candidate-browser verification is
BLOCKED, not passed. No human acceptance, feature completion or application
deployment is claimed.

CI44675585763 passed lint, strict typing, accessory checks, the Lucide guard,
node-only aggregate policy and sales enum contracts. The node-only report retains
128 passes, five quarantined failures, 34 tests requiring an app and one
quarantined pass. The browser step passed load-more, process QR and warehouse
controls, then failed compiling `test-sewing-bands.browser.mjs`: its auth fixture
lacks `canViewCeoDashboard`, now imported by `AuthGate.tsx`. Backend regression
shards4/5 also failed existing auth-me/profile characterization assertions.
Those fixtures, AuthGate and backend characterization tests are byte-identical
to the verified9f64146d production source; the accessory candidate does not edit
them. These failures are recorded rather than treated as passing or expanded
into an unrelated auth repair. Other jobs were still finishing when inspected;
the overall CI cannot pass with these failures. The full optimized build passed
locally, but its later hosted build step was not reached after the browser error.

Remaining gates are actual candidate Edge receipt/return/edit verification,
resolution or explicit disposition of the inherited CI failures, QA-master
review and separate application deployment authorization. The production batch
renumbering is complete independently of these QC UI gates.


## Owner-requested direct deployment

On20 November the owner explicitly instructed “deploy fast without test”.
Further tests/CI, browser QA, scans, performance sampling, QA-master review and
timed observation are skipped for this release, not passed. Earlier failures
and blocked preview evidence remain recorded. Operational source identity,
immutable builds outside production, backup, blue/green and health checks remain.
Fresh production is20261120_044200, source ac83508dbbacc1608e80b6422159b51985d9d35d,
manifest af2c5f2520ecb8be476d2d34e0fa6e13e677921046585b1c2df01ad1842f502f.
The candidate merges current clone_main348948478 to preserve the deployed Cutting
changes; only the project-context document conflicted. Existing owner disk
exception remains; no blanket cleanup is authorized by this deployment.


## Deployed result

PR [574](https://github.com/Shmirzaev/Milana-ERP/pull/574) merged to clone_main
at3a33b7c5ebd4116a2a7565eb6dca93f04a068e7d, with the identical tree as runtime
source78c8aa5b086d056966d21f1d01fa56eb15ab2f65. Build-only Actions
[44677453647](https://github.com/Shmirzaev/Milana-ERP/actions/runs/44677453647)
published release20261120_045400. The queued helper-branch validation was
cancelled by the owner's no-further-tests instruction. The publisher branch
codex/accessories-owner-publish-20261120, commit99560843a, is separate and unmerged;
its sparse worktree is C:\ERP\.codex-work\accessories-owner-publish-20261120.

Archive6,845,496bytes, SHA256
93fa710b32e2e1754f4849bb8319bdd602e785d030f65ebeb3233effcfced585.
Source manifest c7d955135511446f23665748b33b83ffa167e2c8afcae268dce00a507012c692.
Backend ghcr.io/shmirzaev/milana-erp-backend@sha256:133472684c6c5189b330e2055579bcf41ad444cf8f229d5b5ba66428c670451b.
Frontend ghcr.io/shmirzaev/milana-erp-frontend@sha256:27bc52a2adcf1be99fbd3ef334160088709456e795689b0ff9e1743287af4f51.
Backend adds only the reviewed unused schema-owned batch-identity helper over the
exact live backend image; inventory business behavior is otherwise unchanged.
Frontend uses locked dependencies and actual Next production compilation without
test scripts. No production-host build/install, migration or intentional business
write occurred. The historical renumbering operation was not rerun.

Fresh mode0600 backup /opt/milana-erp/shared/backups/auto_pre_20261120_045400.dump,
133,690,585bytes,1,403 restore objects, SHA256
e8ad85c514ac52f63ef9e81e2650ccbf94fb7672b318d66d9519bf977afb7255;
restore-list SHA256 cb3a261500f2fac15a5cc6eaf2af7d8399e17cc3744fb6d1935634354bee8b09.
Hash/list verified, not fully restored. Schema0159 and fingerprint
c1830a0f72eddbcf82a76da559bf04da16477ffce29625574a9d28e6e450ca9f unchanged.

Both roles active green20261120_045400; blue20261120_044200 retained running
for rollback. Backend activated04:58:06UTC and frontend04:58:33UTC. Four required
internal/public health/login endpoints returned200; both health responses report
20261120_045400. Both source manifests and runtime identities agree. Owned real
flock keepers held both deployment locks; reservations/leases were released after
closing identity readback. Protected plan/completed journals are on both hosts
under /opt/milana-erp/shared/deployment-evidence/20261120_045400/.

A first backup call arrived while its own reserve process still held the operation
lock; it refused before backup/write and the subsequent call succeeded after
reservation readback. A closing diagnostic used docker top without a PID column;
Docker rejected that diagnostic. The V2 read-only closing check uses pid,args;
earlier failure evidence is retained, not overwritten. Neither diagnostic
changed routing, application code or business records. No test/browser/benchmark/
scan/timed-observation pass is claimed. Existing owner disk exception retained;
no blanket cleanup. Automatic deployment remains inactive. Later human workflow
acceptance can use the retained receipt/return/edit/fabric checklist.

Closing operational readback confirmed both candidates have zero restarts/OOM and
tracebacks, active routers and valid HAProxy configuration. Backend has exactly two
workers; PostgreSQL has39/100 connections, zero invalid indexes and revision0159.
These are operational checks, not the skipped workflow tests or human acceptance.
