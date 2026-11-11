# HR deployment preparation — 11 November 2026

Owner request: prepare the reviewed HR/Hikvision work for deployment; keep the
previous ERP connected and defer the owner's real-person pilot. This request
does not activate production, a LAN writer or an access-rights handover.

People engineering owner: Dilmurod. Technical reviewer: Mirshoir. Business/QA
acceptance: Shavkat/operator and QA master. Independent AI integration review is
recorded separately from those human approvals.

## Reconciled source and storage

The fresh worktree is `C:/ERP/.codex-work/hr-deployment-ready-20261111`, branch
`codex/hr-deployment-ready-20261111`, starting at `origin/clone_main` `c02f83ac0`.
It ports only the seven HR commits through `5bf47f388` from the earlier isolated
candidate. The old worktrees and legacy checkout remain preserved.

Both hosts' active source manifests were verified on 11 November: blue release
`20261110_135430`, application `cfe03885e03e4310e9b7c86ec9649ff350565d65`, manifest
`1abc90b9e4b87f3e16ef0e255fe1829d15e9b510d6f61f1b2c030baf33fa89a3`.
Both slot records agree; recorded recovery is green `20261110_135420`. Public
health agrees. `deploy/production-base.json` is preserved unchanged. Disk was
77% backend / 78% frontend, above the 70% alert; recheck and resolve through
protected retention before any production staging. No pruning is authorized here.

The deployed pricing migration and frozen HR migration both descend from
`0155_eco_gate_merge`. New metadata-only merge `0157_pricing_gate_live_merge`
preserves both `0156_variant_price_workflow` and `0156_gate_live_integration`.
Neither released/frozen migration was rewritten. From deployed pricing, upgrade
applies only the additive HR migration and merge. Saved pricing requests,
approvals and staff data are not rewritten by the HR upgrade.

The disposable roundtrip deliberately unmerges first, asserts both parent heads,
then targets `0156_gate_live_integration@-1`, asserts pricing alone, and upgrades
again. This is local verification, **not a production rollback procedure**.
It retains synthetic approved pricing rows and the same users/models/employees
and pricing table OIDs throughout. Pricing's forward-only downgrade is never
invoked. HR downgrade refuses retained configuration/profile/job evidence.

## Recovery artifact

The existing deployed/recovery backend images expect pricing head 0156 and are
not restart-safe rollback images after the 0157 migration. Do not label them
compatible merely because the new DDL is additive.

Separate worktree `C:/ERP/.codex-work/hr-schema-recovery-20261111`, branch
`codex/hr-schema-recovery-20261111`, preserves the deployed application behavior
and adds the exact same frozen HR migration plus merge metadata. Its test-only
storage contract must preserve the shared migration-drift baseline. Build this
as a separately reviewed immutable recovery artifact; do not graft files into a
serving image or relax strict startup checks.

`scripts/test_rollback_image_schema_0157.py` exercises each exact published backend
digest using its actual default CMD, isolated PostgreSQL, two strict workers,
child replacement and full restart. It checks health/readiness, production shared
counters and full ordered row fingerprints including a saved pricing approval,
an employee and retained disabled HR configuration/queued observation. Ordinary
Sales/Models/Pricing GETs must still work. The HR image must report management
disabled; recovery must have no live-management route. No factory address, host
port or source mount is used. The immutable release workflow runs this check
after backend publication and before reporting both artifacts ready.

## Repeatable checks and evidence

The combined local scoped suite passed 765 cases, including the eight real
PostgreSQL turnstile cases and pricing/startup regressions, with zero failures
or skips. The earlier first integration run's 764 passes/one Alembic-plan failure
is retained as failed evidence; the corrected eight-case rehearsal and final
765-case run supersede it. The full ERP CI gate remains required for the final
commit; the old 609-case/Edge evidence does not certify this new combined source.

Windows connector checks passed all 224 cases including actual current-user
DPAPI. The new Windows CI job pins its test dependencies, rejects missing/skipped
cases and blocks artifact publication. Backend test TLS support now has an
explicit development dependency rather than an accidental local installation.

All eight PostgreSQL identities are now included in the mandatory no-skip
refactor gate (653 required cases total); evidence-policy tests challenge missing,
replacement, duplicate, skipped, failed and errored HR cases. Frontend lint and
strict typing passed (14 inherited lint warnings); the live-UI production build
passed. Both compile-flag variants and exact-source CI/security/image checks must
be recorded before promotion.

Current-session raw logs, reports, source/image identities, final Edge captures,
persisted readback and cleanup evidence belong in ignored
`outputs/hr-deployment/`. The final handoff receipt there records exact commits
and workflow URLs/results. Do not infer a pass from an existing filename or a
parent commit. Earlier firmware evidence remains in
[the compatibility packet](TURNSTILE_FIRMWARE_COMPATIBILITY_20261110.md).

## Promotion checklist for the deployment owner

1. Re-fetch the landing queue. Reconcile any later `clone_main` or production
   changes; preserve unrelated pricing work. Require green full validation,
   mandatory PostgreSQL, Windows connector and security scans on the exact
   reviewed feature/recovery commits. Retest changes that invalidate evidence.
2. Obtain QA-master build approval and deployment authorization. Prepare both
   immutable archives and scanned/published image digests through `DEPLOYMENT.md`,
   with a unique release identity for each. A published artifact is not live.
3. Verify the recorded base/manifest/actual routing on both hosts again. Hold
   deployment leases; check disk/registry/headroom/retention and preserve active,
   rollback and at least three additional releases. Validate a fresh PostgreSQL
   backup before migration. Keep uploaded files and private settings unchanged.
4. Prove the reviewed recovery digest on target 0157 before migrating production.
   Keep startup seeding/schema bootstrap false, strict verification enabled and
   the actual image CMD unchanged. Do not downgrade/stamp shared production to
   make old images boot. Stage, warm and compare protected read/performance
   contracts, inspect rendered affected pages and run all four supported health
   checks before traffic cutover. Preserve observation and threshold failures;
   historical performance waivers do not apply to this release.
5. Compile the HR frontend with manual input `turnstile_live_ui=true` when visible
   controls are wanted. Initial backend mode stays `disabled`; per-device write
   approvals remain false and no LAN writer is activated. UI visibility grants
   no physical write authority. Register the tested compatible recovery through
   the supported rollback-field compare-and-set procedure and verify actual
   restart/worker/health state before closing the release.
6. Keep the installed attendance reader, task, config, pins, cursors and previous
   ERP connections unchanged. An independently approved read-only observation
   pilot may later enable Hikvision mode with per-device writes false and a
   separate read-only LAN worker for an exact allowlisted identity. Do not modify
   device subscriptions/network settings or switch off the previous ERP.

## Owner's later physical pilot

The owner will supply his exact employee number, selected lane and approved
access plan/validity schedule. Establish an explicit pilot identity boundary
with the previous ERP before any Milana write, and agree the sole-writer handover
before general activation. Two unrestricted writers are not supported.

With the owner present, check real recognition/passage, enrollment, name/photo,
separate revoke/restore/delete, uncertain/offline recovery, unrelated profiles
and fresh scans in both ERPs. Deleting a device profile retains HR/payroll/audit
history. `turnstile-31` deletion remains refused on its native `deviceError`; do
not reboot or alter its settings to bypass that refusal. The read-only six-lane
checks and synthetic test success are not physical acceptance.

Source integration, immutable publication, production activation and real-device
handover have separate recorded states. Human approval and physical acceptance
remain pending until explicitly performed and recorded.
