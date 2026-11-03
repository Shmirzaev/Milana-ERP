# Combined clone_main and manual Packaging release — 28 October 2026

The owner explicitly authorized deployment of manual pack creation/label printing
and the large current clone_main change, merged with the current live release.
Use blue/green, preserve the current version for rollback, and do not interrupt
the ongoing refactoring checkout/workers. The owner waived the timed 30-minute
observation only. Tests, backup, migration compatibility, candidate/production QA,
performance budgets and immediate postflight remain required.

Release worktree: `C:/ERP/.codex-work/manual-packaging-release-20261028`.
Branch: `codex/manual-packaging-release-20261028`; manual feature `e19e414f`;
initial clone_main input `e6f597891489e38207e01b6bfcca3d8df1b7adea`.
Both live manifests verified clean: green `20261027_115452`, application
`ed47ab8d0484878f7b5638825beda2ce62a08f5d`, manifest
`8b8be7776fece64fc01163052efafc76370516faa4b186f5509fbcc1357a8f90`.
Existing blue rollback is `20261027_104106`. Candidate will use inactive blue,
retaining current green source/images/container for immediate rollback.

This worktree contains the live namespace reconciliation `55450eea`, guarded
employee master script `fe4bc0f8`, manual packs, and the latest clone_main merge.
The production master reassignment was already applied and must not be replayed.
No new migration revision is present relative to live; verify actual ORM/table
compatibility and Alembic head before any candidate startup or cutover.

Mirshoir is the engineering/release owner; Ismail is the human reviewer.
Codex root integrates; independent Codex `/root/release_review` reviews the exact
combined source/operations. Named ownership is not a claim of human acceptance.
Do not push to or overwrite the shared clone_main working checkout; publish only
the dedicated candidate branch. Reconcile any subsequent shared-line/production
advance before activation.

Initial planning status was PREPARING. The dated promotion record below
supersedes that status and records the actual release evidence.
Earlier feature evidence is in [the manual-pack task](MANUAL_PACKAGING_2026-10-28.md).

## Refreeze after concurrent landing

Before schema or slot staging, the mandatory fetch stopped candidate `630aef34`
because PR #339 advanced clone_main to `61b1a7020c5e1465aa076acc238d94ea1ad7dd03`.
That first candidate passed full CI and produced immutable release
`20261028_111041`; its source/images were prepared but never staged or activated.
Green production remained untouched. Its evidence is retained separately.

The isolated release now includes PR #339's eight-path customer-update persistence
extraction, typed command and five required PostgreSQL cases. Independent review
found preserved required-name, optional omission/null/empty, permissions, audit
and transaction semantics, with no Packaging overlap or migration. Refreeze the
new exact combined commit, rerun affected and full CI/PostgreSQL gates and build
new immutable artifacts. This snapshot includes clone_main through `61b1a702`;
subsequent ongoing refactor operations remain outside the frozen release until
reviewed. Do not interrupt or overwrite the shared refactor line.

## Corrected candidate after staged Finance checks

Candidate `f38f11a5`, immutable release `20261028_113704`, passed full CI
(4,820 default cases plus separately required PostgreSQL suites) and was staged
on inactive blue. Green `20261027_115452` still serves traffic; no activation
occurred. Signed GET checks covered 21 workflow projections, actual browser
checks opened the manual pack form without saving, and paired performance passed.
The final runtime-log gate correctly failed on Finance cost breakdown: a nullable
descriptive BOM item was passed to `int()`. AST comparison confirmed the same
function in the old live release. No production BOM or inventory was repaired.

The corrected candidate skips only BOM rows without an inventory item when
calculating inventory costs. Existing linked-item prices, waste, packaging and
labor calculations remain unchanged. The regression first produced two failures
and one linked-only passing control; after the fix all three cases and the
32-case relevant Finance suite passed. Independent review separately passed all
three new cases. Build new immutable images from the corrected exact commit,
renew the backup and candidate/runtime/performance checks, and verify Finance
before switching traffic. Preserve both earlier unactivated attempts as evidence.
The frozen clone_main input remains `61b1a702`; refactoring continues separately.

Physical print/label preview visual acceptance remains BLOCKED by the earlier
browser blob-preview refusal; automated label HTML/reprint checks and the prior
isolated Packaging-to-warehouse browser handoff are attributed to their exact
source. Do not claim human acceptance or a completed full-system refactor.

## Production promotion verified

Blue `20261028_123531` is active on both application VMs, runtime commit
`a0cb9d8b9fdab64dd751e7f3da7a1fa832779780`; source manifest `3b2fb1c4e67f5c08a127d56d9490ee64c10997eb576ee0aeb9613caee246aaed`.
The frozen input is clone_main `61b1a702`, reconciled with live `ed47ab8d`,
manual Packaging `e19e414f`, and the reviewed Finance correction. The shared
refactor checkout/branch/workers were not changed or interrupted. Only the
dedicated release branch was pushed; no main/clone_main landing is claimed.

Green `20261027_115452` remains running with its original source/images for immediate
rollback. Backend switched before frontend after all candidate gates passed.
Database remains `0149_besttex_cutting_access`; schema verification was a no-op.
Owner waived timed 30-minute monitoring; immediate postflight was completed.
No scheduled monitor was created and no timed observation is claimed.

The first corrected promotion at 13:08 UTC automatically restored green at
13:09 UTC after the public QA harness incorrectly required root
`/openapi.json` to return200. Existing Next/public routing returns404, also
confirmed on restored green. All25 business projections had passed before
that assertion. Independent review approved checking the schema on the exact
backend slot while requiring public404 parity. The failed attempt, successful
rollback, original evidence/log hashes and unchanged successful performance
samples are retained under `promotion_attempts` and `promotion-attempt-1/`.
No application/image change or public performance resampling was made for this
harness correction. Final promotion renewed all activation guards and passed
the corrected complete public checks.

Exact immutable [release CI](https://github.com/Shmirzaev/Milana-ERP/actions/runs/40688824325) and
[refactor PostgreSQL CI](https://github.com/Shmirzaev/Milana-ERP/actions/runs/40688809921) passed.
Local full backend: 4823 passed,
518 opt-in skips; required PostgreSQL gates were
separately enforced without skips. Local manual PostgreSQL:3 passed. Frontend
optimized build/strict types/lint:0 errors,12 existing warnings, byte-identical
frontend attribution plus renewed exact-source CI. Independent source and
deployment-helper review found no remaining code blocker.

Signed GET QA checked the existing workflow projections and corrected Finance
cost components, authorization refusals, unchanged selected package/payroll
history, and existing label HTML. Actual connected Chrome verified the staged
manual form and Finance values; public UI and all four internal/public
health/login checks passed. Candidate paired and closing public performance
met the fixed-origin budgets; raw 120-sample results are retained. Final source,
image, router, two-worker, restart/OOM, disk, database headroom/index and runtime
log checks passed. Normal browser authentication touched only actor last_seen_at
and updated_at metadata. No production packs, stock, orders or invoices were
created by QA. Earlier owner-authorized two-employee master reassignment remains
as recorded in the feature task; both Dilafruz people stay separate.

Fresh 0600 pre-release backup:`/opt/milana-erp/shared/backups/milana_erp_pre_20261028_123531.dump`;
95,461,940 bytes,1246 restore objects;
SHA256`bda7581bd1ce8f7e96a72c05ee67674f1e95b28f225a49004f8ec910eb322e77`;
restore-list SHA256`9d357bdec1fee50a7b880c331412c64c84a0637144c6a352e374fae23600a6f9`.
Backend image:`ghcr.io/shmirzaev/milana-erp-backend@sha256:e358ad0fb7cf07f9753d3834c5145999d1c25fdd3371bc314d86a0ce4990acef`.
Frontend image:`ghcr.io/shmirzaev/milana-erp-frontend@sha256:bb2ebdf0915dab4b6040b17b9c561954f05403afa6cccc897c560afb8ebd6593`.

Evidence is retained under this worktree's ignored `outputs/deployment/`:
config/evidence JSON, exact CI/JUnit reports, archive metadata, checks, screenshots,
backup verification and raw performance. Previous unactivated attempts are
`outputs/deployment-attempt-630aef34/` and `outputs/deployment-attempt-f38f11a5/`;
the latter's correctly failed runtime gate exposed the Finance bug. Their results
are historical and were not relabeled as the corrected candidate's checks.

Human/operator acceptance remains pending. The earlier blob-label inspection was
refused by browser policy and remains BLOCKED; no alternate surface was used to
evade it. Automated label/reprint checks and the prior isolated creation-to-receipt
handoff remain attributed to their exact unchanged source. The optional extra
local UI restart was also rejected by automatic approval review as blocked by
policy; it was not retried. This deployment has the owner's explicit authorization.
No AI_VERIFIED_AWAITING_HUMAN, physical printer or whole-refactor
completion claim is made. Operator checklist: inspect label preview/physical
output, repeat manual creation/reload/warehouse receipt/cancellation on isolated
data, and record acceptance.
