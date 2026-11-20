# Cutting remaining balance — 20 November 2026

User scope: check and remove already sewn/packed unaccepted bundles from Cutting
balances, including partial batches. User chose: "Show remaining pieces; mark
uncertain bundle counts 'Needs count'". No fabricated acceptances or manufacturing
data corrections are authorized or needed. Production owner: Mirshoir; technical
reviewer: Ismail; operator acceptance: Shavkat. Codex implements this read projection;
the independent AI reviewer is `/root/balance_review`, not either human reviewer.

Dedicated worktree: `C:\ERP\.codex-work\cutting-exact-balance-20261120`, branch
`codex/cutting-balance-runtime-20261120`. Created from `origin/main`, reconciled
with `clone_main`, initially based on production-record commit `a362d5e27`.
While disk cleanup was pending, the owner independently released the CEO candidate.
Both hosts were reverified at `20261120_040300`, runtime `981308213`, manifest
`7e888254a16e7c8ff277d99c4eff29a8a0f40c149aa3229987074232badcabb7`.
This task first fast-forwarded to matching production-record commit `97259b9de`.
At final publication, a fresh fetch found the owner's material-collapse release:
both hosts now name `20261120_042800`, manifest
`413aa746515609a15a16ee4ce1d94beb3af58768f30fda051fcca565b8438544`.
`deploy/production-base.json` agrees with runtime source `9f64146d4`.
The task fast-forwarded again to production-record commit `bfb25ae8c`, preserving
the scoped Cutting patch. The only intervening UI code is the unrelated CEO
material-detail collapse; combined frontend build is repeated below. Runtime
slots.json is not readable by this SSH account; the release record reports green
active and blue `20261120_040300` rollback, and both containers were observed.
The earlier apparent mismatch came from stale `origin/main`.

Operation map: dashboard/cutting and bundles/cutting-inventory -> existing board
and new production Cutting balance read service -> immutable Bundle/scan,
PrintingRecord, SewingRecord, PackagingRecord and PackageBatchAllocation evidence
-> department dashboard and Cutting inventory. Permissions/factory authorization,
all write commands, printing labels and stored quantities remain authoritative.

Vocabulary ledger: reuse WorkOrderStatus.CANCELLED, SewingFactoryCode and
CuttingDepartmentCode. The read-only UNASSIGNED sentinel is an explicit Literal,
not an unrestricted string. Source event strings remain private SQL adapters;
no new persisted states. Arbitrary size names remain data.
No schema migration, new permission, business write or wider enum refactor.

Rules: one snapshot for balance evidence; exact PO/effective batch; NULL stays separate. Aggregate each
stage before taking overlapping evidence maxima. Explicit receipts and unlinked
outputs are a union with bounds, not blindly additive or assumed identical.
Known complete size evidence narrows that union. Multiple source/factory partitions
remain unresolved if consumption cannot be attributed. Exact zero disappears;
partial pieces stay visible. Physical label counts remain unknown when quantities
do not establish a unique count. Search and pagination do not recompute consumption.
Original label counts must not be represented as remaining stock or reprinted as
if their physical contents were known.

Evidence and status: DEPLOYED by explicit owner instruction; verification incomplete.
The following pre-deployment evidence retains its original scope. Read-only production snapshot confirms screenshot
MIL 516/35,878 and BST 1,395/97,304; 1,911 pending labels, no mixed accepted/pending
source batches, no mixed-factory source batches in this snapshot. 204/207 Sewing
records lack size breakdowns, so partial label identities cannot be established.
Private source snapshot is under ignored `outputs/cutting-balance/`.

Required checks: old-source failing quantity regression, focused dashboard/inventory,
receipt/output/correction/packaging regressions; PostgreSQL projection and query
budget/read-only evidence; actual connected-browser candidate screenshot and
refresh/drilldown; independent AI diff review; bounded projection load. Missing
checks are BLOCKED. User acceptance/merge/deployment are distinct from AI verification.

Independent AI review challenged 27,171 cases in memory: 2,871 exact single-factory
receipt/output cases, 20,736 factory subsets and 3,564 complete-size/overproduction
cases. No unsound bounds remained after correcting known-size overflow and
preserving whole-batch constraints across factories. Inventory freezes projected
label IDs; ancillary label metadata is read afterwards, not claimed to share the
balance snapshot. Final focused suite: 30 passed. Affected Cutting -> Sewing ->
Packaging handoff suite: 129 passed (224 existing warnings). Ruff, strict TypeScript,
the frontend contract tests and formatter tests passed. Full frontend lint had
zero errors and 14 existing warnings. Production Next.js build compiled 104 routes
with API_URL pointing only to the disposable local test backend.

The independent frozen-ledger oracle and read-only PostgreSQL projection agree:
MIL 22,908 pieces / 47 orders; BST 46,655 pieces / 112 orders. Physical bundle
identities remain uncertain in 1 MIL and 21 BST batches; no unresolved piece
balances in that snapshot. The optimized projection measured 244–371 ms after an
initial correlated-scan version took about 2.2 seconds. No business data changed.

Final read-only probe on the new live green backend reconfirmed those exact totals;
six projection runs measured 234–352 ms. Candidate code executed only in the
standalone probe process; serving application files and records were untouched.

Local validation was blocked by a full C: drive. The owner authorized removal of
unnecessary files. Official npm/uv/pip cache cleanup and Playwright's uninstall
command removed regenerable downloads, preserving source, worktrees, production
backups, Chrome and Edge. Manual Remove-Item cleanup was rejected by automatic
approval review; no equivalent ad-hoc deletion was performed.

The supported full-backend runner stops during collection in unchanged
`test_create_user_extraction_gaps.py`: "In
test_postgres_concurrent_unique_creations_keep_audit_chain: function uses no
fixture 'creation_database'". This is recorded as BLOCKED, not a suite pass;
the unrelated identity test was not changed as part of the Cutting fix.

Actual browser inspection is SKIPPED by the owner's explicit response on
20 November: "i'm having errors do it or just skip". Automatic approval review
had rejected both local Next.js preview startup attempts as "blocked by policy";
the owner was unable to start it manually. No rendered candidate screenshot or
visual/persisted-UI acceptance is claimed. The independent calculation/diff review
passed, but the candidate is not AI_VERIFIED_AWAITING_HUMAN because required
verification is incomplete. No source merge, deployment, migration or production
business write occurred.

Remaining operator/QA checklist: open the candidate Cutting dashboard; confirm
the same remaining pieces in the destination row and inventory drilldown; check
a partially processed batch shows Needs count and its original label quantities;
confirm fully processed work disappears; search/page/refresh; repeat in EN/RU/UZ.
QA master must record the pre-deployment decision against the exact build.

Final combined candidate based on `bfb25ae8c`: the 129-test handoff suite passed
again in 54.36 seconds; the complete `npm run build` (including formatter and
existing contract checks) passed and generated 104 routes. Ruff and diff whitespace
checks passed. Independent reviewer reconfirmed no new findings on this baseline.
Visual inspection remains owner-skipped and full-suite collection remains blocked.

## Owner-requested direct deployment

On 20 November the owner explicitly instructed "deploy deirectly without test".
This overrides the remaining repository/skill verification gates for this release;
it does not turn skipped gates into passes or constitute recorded QA-master testing.
Further tests/CI, browser QA, security scans, performance sampling and timed
observation were skipped. Previously queued validation jobs were cancelled.

PR [#573](https://github.com/Shmirzaev/Milana-ERP/pull/573) merged to clone_main at
`03e14d02e24baa21cada828a6e740027bef7e3b4`, whose tree exactly matches runtime source
`ac83508dbbacc1608e80b6422159b51985d9d35d`. Build-only Actions run
[44676083062](https://github.com/Shmirzaev/Milana-ERP/actions/runs/44676083062)
published release `20261120_044200`. Helper branch
`codex/cutting-owner-publish-20261120`, commit `cabb5fef8`, remains separate and is
not merged. Its isolated worktree is `C:\ERP\.codex-work\cutting-owner-publish-20261120`.

Archive6,835,987bytes, SHA256
`a5b9c7e313cb0dd23815269d52679a50f163122c4221cdb2497a31794c7e2b15`.
Manifest `af2c5f2520ecb8be476d2d34e0fa6e13e677921046585b1c2df01ad1842f502f`.
Backend `ghcr.io/shmirzaev/milana-erp-backend@sha256:c1fd9e68a76bb03d1bcce4941b4fd4930dc40291b238d37bd344cf12c392d0d9`.
Frontend `ghcr.io/shmirzaev/milana-erp-frontend@sha256:e7ec0c15cda1d6be248e054e91a4521a8e9e737762bcd3f1e890f333750ed4df`.
Backend changes only the four reviewed Python application files over exact live
image `712de119...`; staged hashes match the source archive. Frontend uses locked
dependencies and the actual Next production build, bypassing test scripts.
No build or dependency installation on serving VMs; default image commands and
strict production/startup-write settings preserved. No migration. Schema0159 and
fingerprint `c1830a0f72eddbcf82a76da559bf04da16477ffce29625574a9d28e6e450ca9f` unchanged.

Fresh mode0600 backup `/opt/milana-erp/shared/backups/auto_pre_20261120_044200.dump`,
133,632,935bytes,1,403 restore objects, SHA256
`3b5bd95030a5357b14126912f2e8648cbc0ac532d95765f546fa74dc1ea6fbf3`;
restore-list SHA256 `16a58a05ba2b472a20d85f185dbc14cbe2f79c5b954b0a1f4105b0b6c8af5e91`.
Hash/list verified, not fully restored. No intentional production business writes.

Both hosts active blue `20261120_044200`, green `20261120_042800` running rollback.
Backend router switched04:46:24UTC and frontend04:46:41UTC. Internal backend health,
internal frontend login, public health and public login returned200; both health
responses identify the release. Actual router/source/container identities agree;
two backend workers started without tracebacks; both candidates have zero restarts/OOM.
Owned keepers held the real deployment flocks; both reservations and leases released.
Protected plan/completed journals are under
`/opt/milana-erp/shared/deployment-evidence/20261120_044200/` on both hosts.
The existing owner disk exception remains: backend95%, frontend81% at preflight,
with11GB/15GB available. Protected retention dry-run only; no release/image blanket
cleanup. Automatic deployment remains inactive. The legacy checkout is preserved.
