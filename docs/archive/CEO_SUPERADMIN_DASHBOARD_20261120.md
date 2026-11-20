# CEO dashboard access and presentation — 20 November 2026

The owner requested superadmin access, then explicitly requested removal of
Waiting for handoff, working day/week/month controls, a clearer Material stock
section, and deployment "directly without any tests". This latest instruction
overrides further tests, browser QA, benchmarks, scans, QA-master review and timed
observation for this release. Skipped gates are not passes or human acceptance.
Immutable builds and operational source/health checks remain necessary.

Worktree `C:\ERP\.codex-work\ceo-superadmin-20261120`, branch
`codex/ceo-superadmin-20261120`, base `a362d5e273eb2c11a82b15bcf54c6673a48808dd`.
Both hosts freshly reconciled to green `20261119_122457_44523647780_1`, source
`65c861c8369d3f966bac69d1b9980aff796744c5`, manifest
`fd7428c089dba546e4b89db784614f9bf8ac44b80bc9a7b1491a7445ce7c8917`.
Schema `0159_ceo_balance_snapshots` is unchanged. This was the verified baseline;
the deployed result is recorded below.

Named shared-auth/frontend owners: Dilmurod engineer / Mirshoir reviewer;
Shavkat business acceptance. Actual implementer root Codex agent; independent
source reviewer `review_ceo_rollout`. No teammate messages sent.

GET `/api/dashboard/ceo` uses a shared persisted-identity dependency and unchanged
dashboard services, DTO and queries. Auth/session `/me` adds server-derived
`can_view_ceo_dashboard: bool`, default false, using exactly the same CEO OR
canonical superadmin predicate. Primary-factory `admin.super` denial wins;
wildcard alone and forged token role cannot grant access. CEO operational-session
restrictions remain CEO-only. No writable user DTO or database field is added.
AuthGate, report entry, Sidebar and CeoShell consume the capability. Superadmins
see the link in MIL/BST/ECO and can return to ERP; CEOs remain report-only.

The report removes handoff summary/waiting presentation, retaining the API and
snapshot data. Buttons replace transparent radio overlays. Week/month expand
narrow one-day presets; custom date ranges retain their boundaries. Materials
use separate unit totals, searchable names/SKUs, a unit filter and 25-row increments;
warehouse detail remains collapsed. EN/RU/UZ supported. Configurable roles/factory
records and canonical report enums remain unchanged; no new fixed vocabulary,
migration or business-data write. Department handoffs and quantities are unchanged.

Before the latest no-tests instruction, access-only changes passed 32 Linux/SQLite
API/report regressions (cookie/bearer factory switch and same-token revocation),
21-context actual-component frontend access checks, existing access/Besttex/customer
checks, strict type checking, lint (8 existing warnings), and focused Ruff.
These do not validate subsequent presentation edits. One initial lifecycle fixture
failed because superadmin revocation also removed ECO scope; the corrected fixture
covers both retained and removed ECO access. No fresh PostgreSQL claim is made.

Local visual setup failed on legacy dependencies; the isolated locked-dependency
preview encountered full local disk and interrupted/corrupted npm installation.
No browser pass is claimed. Automatic approval review rejected removing the owned
`.next` cache as "blocked by policy"; the cache remains. Production was untouched.
Further tests/CI validation, browser QA, scan, performance and observation are
skipped by the owner's latest instruction. Independent review is source-only.

Later human checklist: superadmin menu/report in all factories and Back to ERP;
Week/Month expansion and custom date aggregation; absence of waiting section;
material search/unit/load-more; ordinary-role denial and CEO isolation. This is
retained for later acceptance, not a new permission request.

## Deployed and source-merged

Both hosts serve blue `20261120_040300`, exact runtime commit
`98130821354f487767a9b79f56482f1788ac4c40`, pushed on the task branch and merged
to `clone_main`. Build-only Actions run
[44671704830](https://github.com/Shmirzaev/Milana-ERP/actions/runs/44671704830)
succeeded. Separate helper branch `codex/ceo-owner-publish-20261120`, commit
`9449c0710610d7f1d205be0b2aba1b70dd4c19ee`, is pushed, not source-merged. Its
disposable clean worktree was removed after publication to recover local disk;
the task worktree remains. No further tests/QA/scans/benchmarks/observer ran.
Independent source review's stale unit-selection issue was fixed before commit.

Archive6,822,681bytes SHA256 `9af25b7ce15e38de4bbac155f5a9f3fe7068ece448c03298a5e46b5c6c1df87d`.
Manifest `7e888254a16e7c8ff277d99c4eff29a8a0f40c149aa3229987074232badcabb7`.
Backend `ghcr.io/shmirzaev/milana-erp-backend@sha256:a54facae08c6c3cfe9e4e5d9985e719bfb2bc274a6dbc736bb6619192fd928c3`.
Frontend `ghcr.io/shmirzaev/milana-erp-frontend@sha256:ff49b4c5020b6686be55f98d966c7ca4d5f0da0cf8d6b0c67ec461902444f9cf`.
Backend replaces only four reviewed Python files on the exact live image; running
file hashes match the source archive. Frontend uses locked dependencies and the
real Next production build, bypassing test scripts. Both revision labels/default
commands match; startup seeding and schema bootstrap stay disabled. No production
VM builds/installations or migration. Schema fingerprint `c1830a0f72eddbcf82a76da559bf04da16477ffce29625574a9d28e6e450ca9f`.

Fresh backup `/opt/milana-erp/shared/backups/auto_pre_20261120_040300.dump`,
133,352,664bytes,1,403 restore objects, SHA256
`7307e6ac9c57eba56b6c0adc17d317a7384ff302cc39d8ec0baee147e9a98b34`;
list SHA256 `b4ed789366e20a513d883ecd18f5191b72ae17dcaf9ce88dbb08463807fd50d1`.
Hash/list verification only, not a full restore. No intentional business-data write.

Backend activated04:08:19UTC, frontend04:08:49UTC. Internal backend health,
internal frontend login, public health and public login returned200; health
identifies the new release. Both candidates have zero restart/OOM; source,
actual router, active/rollback and strict schema identities agree. Green
`20261119_122457_44523647780_1` remains running as rollback with its CEO guard.
Protected plan/completed journals are on both hosts under
`/opt/milana-erp/shared/deployment-evidence/20261120_040300/`.

Both owned leases/reservations released. Initial background lock keepers exited
with their helper containers before source/staging mutation; successful V2 keepers
held both real locks through closing. This is coordination evidence, not a test.
The existing owner disk exception is retained; no blanket cleanup. Automatic
deployment remains disabled. Legacy checkout and business data are preserved.

## Follow-up: collapse material detail

The owner identified the expanded search/unit/material-row block and requested it
be collapsible. Reuse the existing native Details component, closed by default,
labelled with the existing EN/RU/UZ material-breakdown text. Unit totals remain
visible; search/filter/load-more and warehouse details retain their behavior.
Two JSX wrapper tags change; no styles, API, permission, database or quantities
change. The same task worktree/owners/source reviewer and prior no-further-tests
deployment instruction apply. Fresh origin/production/baseline reconciliation
agreed at `97259b9de` integration / `981308213` live source, blue040300, before
this edit. Source-only independent review found no blocker; no tests or browser
QA were run for this follow-up, continuing the owner's instruction.

Deployed green `20261120_042800`, source `9f64146d4d5b8e523d71fb6c3483c02118d32acb`,
pushed/merged to clone_main. Build-only run
[44674451985](https://github.com/Shmirzaev/Milana-ERP/actions/runs/44674451985)
passed; helper branch `codex/ceo-collapse-publish-20261120`, commit `051721fcb`,
is pushed and not merged. Backend filesystem is unchanged on the previous live
image; only the source revision label changes. Frontend rebuild uses locked
dependencies and bypasses test scripts. No build/install on production VMs.

Archive6,824,840bytes SHA256 `09f2b25b0d57e44603e44e31ffc9fb7cf68265e4ed4b9a358879b92c6fd4beff`;
manifest `413aa746515609a15a16ee4ce1d94beb3af58768f30fda051fcca565b8438544`.
Backend `ghcr.io/shmirzaev/milana-erp-backend@sha256:712de119f15634879a75b196c379832136c8ac4648f76d6d9b30b30571a76898`;
frontend `ghcr.io/shmirzaev/milana-erp-frontend@sha256:5b3c5d138fdc891300667d9007c10d68e4cdbed8ab9528920011d5851b2d07d3`.

Fresh backup133,536,381bytes/1,403 objects at
`/opt/milana-erp/shared/backups/auto_pre_20261120_042800.dump`, SHA256
`97994bb57bc466c1cfe56c15022bec5bb8559da43f6c970fca9a50988bd75a95`;
list SHA256 `ec2873b42ebfa7618e672e33f7dd7f35307a02c05baba1549cdf0781df95a45b`.
Hash/list verified, not fully restored. No migration or intentional business write;
schema0159/fingerprint unchanged. Backend switched04:31:43UTC, frontend04:32:12UTC.
All four operational health endpoints returned200; actual source/router/container
identities agree, zero restart/OOM. Blue040300 remains running as rollback.
Both leases/reservations released; completed journals/plan are protected on both
hosts under `/opt/milana-erp/shared/deployment-evidence/20261120_042800/`.
Automatic deployment remains disabled; existing disk exception retained.
