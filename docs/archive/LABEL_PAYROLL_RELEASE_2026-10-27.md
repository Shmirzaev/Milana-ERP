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
