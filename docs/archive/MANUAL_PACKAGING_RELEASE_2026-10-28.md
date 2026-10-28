# Combined clone_main and manual Packaging release — 28 October 2026

The owner explicitly authorized deployment of manual pack creation/label printing
and the large current clone_main change, merged with the current live release.
Use blue/green, preserve the current version for rollback, and do not interrupt
the ongoing refactoring checkout/workers. The owner waived the timed 30-minute
observation only. Tests, backup, migration compatibility, candidate/production QA,
performance budgets and immediate postflight remain required.

Release worktree: `C:/ERP/.codex-work/manual-packaging-release-20261028`.
Branch: `codex/manual-packaging-release-20261028`; manual feature `e19e414f`;
frozen clone_main input `e6f597891489e38207e01b6bfcca3d8df1b7adea`.
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
