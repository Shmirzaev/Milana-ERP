# Returned split label correction

Owner request: edit returned divided labels, preserve payroll history, test and
deploy without timed 30-minute monitoring. Refactoring remains untouched.
Payroll ownership: Dilmurod (engineer), Mirshoir (reviewer), Shavkat (operator
acceptance). Implementation is Codex; independent AI review is technical evidence,
not human acceptance.

The existing manager-only split-allocation operation gains a returned mode.
Returned available children can change pieces, operation and rate. They remain
unassigned until normal scanning. Scanned siblings are read-only. Every child is
submitted exactly once and the original total is conserved. Historical earnings,
employee snapshots, return history and QR identities remain unchanged, including
history in closed periods. Normal scanning creates the next earning under its
existing period rules. Stale, nested, inconsistent, wrong-factory and unauthorized
requests refuse atomically; retries do not append another audit.

No schema migration or production data repair. A new manager-only GET print
operation renders the same group with current assignments and existing QR tokens.
Final verification and deployment results follow below.

Preparation: 84 focused API/print/scanning cases and 40 real PostgreSQL race cases
pass with zero skips. Independent technical review found and verified fixes for
print fitting CSP and blank/padded read-only historical operation names. A
disposable actual-source fault rewrote historical payroll notes: the history
fingerprint test failed, then passed after restoring the exact helper bytes.
Production build, lint and strict types pass; full backend and exact-commit CI
remain release gates. Local real-page save/reopen proves 53/52 -> 60/45 while all
historical payroll columns and QR/return identities stay unchanged.

## Deployment completed — 20261027_115452

- Both roles are green `20261027_115452`, exact application `ed47ab8d0484878f7b5638825beda2ce62a08f5d`;
  retained blue `20261027_104106` is healthy for rollback. Source manifest
  `8b8be7776fece64fc01163052efafc76370516faa4b186f5509fbcc1357a8f90`; Alembic remains `0149_besttex_cutting_access`.
- Managers can edit returned divided-label pieces, operation and rate. Returned
  labels stay unassigned until normal scanning. Scanned siblings are read-only;
  total pieces, QR/return identities and every historical payroll column persist.
  Closed historical periods stay unchanged. Ordinary recorded corrections remain.
- Exact immutable CI, full backend, 40 real PostgreSQL races, independent review,
  disposable source-fault detection, actual EN/RU/UZ save/reload and phone/tablet
  checks pass. A normal rescan creates only the corrected new earning. Bounded
  20 corrections plus 20 retries preserve active and voided history exactly.
- Fresh verified backup, read-only candidate/public API and actual Next page QA,
  unchanged fixed-origin performance budgets, all four health checks, runtime,
  worker/database/source identities and retained rollback pass. No production
  payroll, manufacturing or permission data was changed by QA or deployment.
  Refactoring was untouched; branch remains unmerged. The owner waived timed
  30-minute monitoring; none was run. Human factory acceptance remains separate.


Immutable CI [40499702500](https://github.com/Shmirzaev/Milana-ERP/actions/runs/40499702500)
passed all jobs on `ed47ab8d0484878f7b5638825beda2ce62a08f5d`: 3,957 backend cases passed / 334 environment skips;
explicit PostgreSQL suites passed 148 and 176 cases with zero skips. Migration,
numbering and frontend browser/build checks also passed. Local backend: 3953 passed, 338 skipped, 11 warnings in 691.46s (0:11:31).
Required payroll PostgreSQL suites: 40 passed, zero skips. Focused returned API:
33 passed, zero skips; affected combined API/print/scanning: 84 passed. Lint,
compileall, strict types and optimized webpack build passed (10 inherited lint
warnings). Exact CI test/PG/build logs remain in local deployment evidence.

Independent AI source and operations reviews pass; named ownership does not claim
human review. The test validity challenge used actual copied source in a disposable
checkout: historical-notes corruption failed the all-column history fingerprint;
restored bytes passed. A missing-lock fault was caught by a real blocking race.

Actual local UI: returned 53/52 -> 60/45, wrong-total Save disabled, save/reload,
unassigned employees, EN/RU/UZ, phone 390x844 and tablet 820x1180, valid authenticated
scan-only role with editor hidden / API 403. Mixed groups leave active siblings
read-only. Long returned sticker text fits inside 60x40mm with fixed-script CSP and
no console error. Recorded control 7/13 -> 8/12 preserved 25 UZS. Normal rescan of
corrected 60 at 2.5 creates only 150 UZS once, with old rows unchanged. No printer job
or production correction was sent. Private raw browser evidence stays local.

Bounded metadata stress: 20 changes + 20 identical retries, zero errors, 105 pieces preserved,
one audit per change, no earning writes, all 4 old payroll rows unchanged, successful recovery
GET. Local latency p95 13.16 ms / p99 21.05 ms
is a disposable test result, not a production capacity claim.

Candidate/public production QA used existing data/accounts and GET/HEAD only.
Target returned label 200125542 loaded both parts as unassigned editable, with all
selected label/history columns unchanged. Package labels retain no Page footer and
cutting sheets retain chosen clients. Actual Next production QR Control exposes the
returned editor. Four health checks, valid HAProxy, 2 workers, 0 restarts/OOM, clean logs,
DB headroom / 0 invalid indexes, exact source/image identities and retained blue readiness
passed. Paired/public performance use the same retained blue client/image, 120 samples
per fixed query, 5 warmups, .025 spacing and unchanged 10% median / 15% p95 / 15% payload budgets.

Backup `/opt/milana-erp/shared/backups/milana_erp_pre_20261027_115452.dump`: 93,257,004 bytes, 1,246 restore objects,
mode 0600; dump SHA-256 `88852fd402c3c51ac9fe845d44e22eb3fb520692e59c1c034e710f4cd9cda31d`;
restore-list SHA-256 `4d0cb9b99809525bb66e29c2a3541d377e85eb1106fb454fe38e72d0f56370b5`. Alembic upgrade/current was no-op;
no schema migration, grant, production payroll edit or data repair occurred.

Images:

- Backend: `ghcr.io/shmirzaev/milana-erp-backend@sha256:a9bd5b3ce0e7512be3104286e549e5ef8519ee4bf58b309bc4817e6abbd0e42f`
- Frontend: `ghcr.io/shmirzaev/milana-erp-frontend@sha256:13fc05908f14a3153ff6f8b49fb22f26c4d8e6a21b2c8794bd0ef6ab9bb6fbe3`

Worktree `C:\ERP\.codex-work\returned-split-edit-20261027`; pushed branch `codex/returned-split-edit-20261027`, unmerged to keep
refactoring uninterrupted. This later metadata commit does not change serving code.
Human operator acceptance remains pending under LABEL-PAYROLL-20261027.

To edit: refresh Payroll -> QR Control, expand the group, click **Edit split
allocation** on a **Returned — ready** row. Change pieces/operation/rate, preserve
the total, enter a reason, save and print updated stickers. Employees are assigned
through normal scanning. The same returned-label pencil is available in Process QR.

Rollback: from this worktree run `outputs/deployment/rollback.py --apply`; it checks
both retained sources/containers, switches backend then frontend to blue `20261027_104106`,
repoints symlinks and runs four health checks. Code rollback does not reverse any
later operator metadata corrections; historical payroll was not rewritten here.
