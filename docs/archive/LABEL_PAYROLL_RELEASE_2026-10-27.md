# Package, cutting and payroll-label corrections

The owner requested removal of the package-label Page footer, the selected client
on cutting sheets, and correction of both employee/piece allocations and operation
names/rates after payroll-label division. Codex implementation was explicitly
authorized. The subsequent instruction authorizes deployment and waives the
30-minute observation only. Immediate release gates and rollback remain required.

This isolated production patch starts at exact live application
`439555a77ef583b1b212398e16ecd52ced786e45`, release `20261026_085306`, green on
both roles. Its verified manifest is
`9511b57bf62fd3142c865f3bb07aaf3e2f1053629f90c8521a652cd6da9139e2`.
Blue `20261026_055538` is the initial rollback. Alembic is
`0149_besttex_cutting_access`; this change adds no migration or business-data repair.
Only the reviewed feature delta from clone_main candidate `5bccc542` and the real
PostgreSQL tests from `18b343b7` were ported to the deployed namespace layout.
Existing Process QR model pictures remain intact. No integration/refactoring
branch was merged or other engineer's working directory changed.

Worktree: `C:/ERP/.codex-work/label-payroll-release-20261027`.
Branch: `codex/label-payroll-release-20261027`. Group ownership follows
TEAM_OWNERSHIP: packaging/cutting Mirshoir with Ismail reviewing; payroll Dilmurod
with Mirshoir reviewing. These names describe responsibility, not human approval.
Implementation/testing was Codex under the owner's exception. Independent AI
source review of both layouts found no remaining actionable issue.

## Behavior and safeguards

- Package labels retain four cards per A4 page, ordinals and QR contents, without
  the application-generated Page footer.
- Cutting sheets display the escaped sales/planning customer or service customer
  when present; no empty client field is introduced.
- Payroll managers can use **Edit split allocation** in Payroll QR Control or the
  divided-label pencil in Process QR. Change employees, redistribute the same
  total pieces, edit names/rates, supply a reason, save and print updated stickers.
  Scan-only users cannot correct allocations.
- The correction uses one transaction, factory authorization, schedule/period,
  label and record locking, a stale revision guard, Decimal money and transactional
  audit. Original voided earnings, QR identities and work dates remain unchanged.
  Paid/closed, returned, nested, incomplete, Control-reclassified and wrong-total
  allocations refuse atomically. An exact retry creates no extra audit entry.
- The correction DTO and persistence helper use the current production layout.
  This is no permission, schema, enum or namespace migration. The separately
  prepared integration patch uses clone_main's current grouped layout.

## Recorded preparation checks

- Exact production-port affected backend suite: **208 passed, zero skipped**,
  including 13 new PostgreSQL correction races and existing return/period races.
  Tests use isolated loopback PostgreSQL 16.15 and independent schemas.
- Old-source issue/scan/split reproduced the missing correction endpoint; print
  regressions failed before the fix. Removing the Control guard broke four refusal
  cases. Removing the schedule advisory lock broke the real PostgreSQL blocking
  challenge. Restored guards pass.
- Bounded isolated stress: 20 corrections plus 20 retries conserve pieces, money,
  QR/record counts and exactly one audit per changed request; injected mid-write
  failure rolls back completely.
- Frontend lint, strict types, optimized production build/contracts, backend Ruff,
  compile and whitespace checks pass. Full backend and exact immutable CI are
  recorded separately before promotion.
- Connected-browser testing of the actual production-port QR Control React page,
  real providers/auth/API and disposable DB confirms employee selection, all-field
  save, refreshed rows, reload/reopen persistence and invalid-total Save refusal.
  EN/RU/UZ views and scan-only action hiding pass; the inspected console is clean.
  The static QA bundle is served only by the explicit loopback test helper. It
  does not replace the full Next production build. Earlier automatic approval
  review blocked Next server startup; no equivalent startup bypass was used.
- API-generated package/client print artifacts were visually inspected in the
  connected browser. Synthetic fixtures never connect to production.

The production deployment result, immutable identity, backup and immediate
postflight will be appended after successful promotion. Human factory acceptance
remains outstanding; the active bug is not marked finished by AI verification.

## Deployment completed — 20261027_104106

- Both production roles are blue `20261027_104106`; exact reviewed application
  `1d2bfe3d5a5035d925720017766432693177d30f`. Retained green `20261026_085306` is healthy and ready for rollback.
  Both current symlinks, slot states, source manifests and image identities agree.
  Source manifest: `1d5642ed285ae7fcb4c5b3dd69e3b8222b8a720f92ea44a20d95e9e8b8d5cbec`.
- Immutable CI [40490386264](https://github.com/Shmirzaev/Milana-ERP/actions/runs/40490386264)
  passed all jobs: full backend **3,924 passed / 324 skipped**, then explicit
  PostgreSQL suites **138 passed** and **176 passed**, migration/numbering scripts,
  frontend lint/types/real-page browser regressions/build and image publication.
  The local affected suite passed 208 without skips, including 13 new PostgreSQL
  races. The initial local full run's obsolete footer assertion was corrected and
  its seven print cases passed; exact final CI is green. Independent source and
  deployment-operations reviews found no remaining blocker.
- Actual isolated UI save, employee selection, all requested fields, persisted
  reload/reopen, wrong-total refusal, stale conflict/reload, EN/RU/UZ and valid
  authenticated scan-only restrictions pass. The original scan-only fixture's
  reserved email failed existing profile validation; that evidence was superseded
  by a repeat with a valid example.com fixture against unchanged runtime sources.
  The reproducible integration QA helper includes this test-only correction.
- Signed candidate and public Next production pages show the actual saved-split
  editor and existing values with zero console errors. Production QA used GET/HEAD
  only, existing accounts/records, and preserved the selected group's fingerprint.
  Package HTML has no Page footer and cutting HTML contains the selected client.
  Styled print artifacts and corrected synthetic payroll stickers were visually
  inspected locally. Browser popup inspection remains limited by the browser's
  existing popup policy; no real printer job or production correction was sent.
- All four immediate health checks, valid HAProxy, two backend workers, zero
  restarts/OOM, clean runtime logs, database connection headroom and zero invalid
  indexes pass. Paired candidate and closing public performance pass with the same
  retained-green client/image, 120 measured samples per fixed query, five warmups,
  identical row counts and unchanged 10% median / 15% p95 / 15% payload budgets.
- Fresh mode-0600 backup `/opt/milana-erp/shared/backups/milana_erp_pre_20261027_104106.dump`: 93,141,121 bytes,
  1246 restore objects; dump SHA-256 `751a9b6a3136b067ebb7f9b98618379f00f33ed0bf6903cf51b7dc57fa4aa82c`;
  restore-list SHA-256 `25c685b9c1bf5b661cabc3a1d9c151a362c59588af0ba5aeba04f417c991b1e8`. Candidate Alembic upgrade/current
  was a no-op at `0149_besttex_cutting_access`; no grants, manufacturing-data repair,
  payroll edits or fabricated production records were performed.
- The owner explicitly waived the high-risk 30-minute observation. No timed
  observer was started or represented as passed. Green remains live for rollback.
  Refactoring worktrees and the dirty legacy checkout were untouched. No integration
  or refactoring merge was performed. Human operator acceptance remains outstanding;
  `LABEL-PAYROLL-20261027` stays in the active bug tracker.
- Application branch `codex/label-payroll-release-20261027` is pushed. Deployment metadata
  is a later Git record and does not alter the immutable serving commit above.
  Private raw QA evidence and production screenshots remain in ignored
  `outputs/deployment`; production payroll details were not copied into Git.

Images:

- Backend: `ghcr.io/shmirzaev/milana-erp-backend@sha256:66033f169f123c1686079d3681b62e48c2f14851dcd79159c912f8fc96a8ada3`
- Frontend: `ghcr.io/shmirzaev/milana-erp-frontend@sha256:a5cda222e95c382857acfb3b6c0954feeb9fe5293282d750f1939cf6c6a2bb06`

To edit: **Payroll → QR Control → Edit split allocation**, or the divided-label
pencil in Process QR. Supply a reason, preserve total pieces, save, then print
updated stickers. Closed/paid payroll remains locked.

Rollback uses `outputs/deployment/rollback.py --apply` from this worktree: verify
both retained sources/containers, switch backend then frontend to green
`20261026_085306`, repoint both symlinks and rerun all four health checks. It does not
downgrade the database or reverse any later operator payroll correction.
