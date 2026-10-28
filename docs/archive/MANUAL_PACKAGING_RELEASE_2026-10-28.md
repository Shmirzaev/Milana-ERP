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

Release status: PREPARING. No candidate build, deployment or verification success
is asserted by this planning record. Detailed exact-source CI/artifact/backup/
slot/rollback/performance/browser evidence will be recorded after each gate.
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
