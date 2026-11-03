# Pack customer restriction and admin release

Scope approved by Shavkat in this chat: packs for a customer-selected order must
not scan into another customer's shipment; an admin can release selected packs
for any customer. No order-edit freeze, automatic reassignment, deployment or
production business writes are authorized. Release preserves source history and
applies to remaining pieces only. Existing stock reservations and shipment claims
remain protected.

Base: origin/clone_main 77d090f69c293f716adf9e2df6227d9543552442.
Worktree: C:\ERP\.codex-work\pack-customer-release-20261103.
Branch: codex/pack-customer-release-20261103. Implementation: /root; independent
AI review: /root/customer_guard_review; regression tests: /root/customer_guard_tests.
Human domain engineer/reviewer: Mirshoir/Ismail; business acceptance: Shavkat.

Before editing, both VMs' current symlinks and full clean source manifests matched
deploy/production-base.json: green 20261102_063110 / runtime 42078704, manifest
becda671a332afe6fe86857ab948be2d686c984e81d02e6e68053ba83cb7a079.
Both backend/frontend slot states also matched, retaining blue 20261031_092951. These were
read-only inspections. No deployment is part of this task.

## Operation and boundaries

Shipment scan/add/replace/dispatch -> Fulfillment customer compatibility service
-> source ProductionOrder/SalesOrder customer and explicit PackageCustomerRelease.
Admin package release route -> typed release service -> schema-owned release
persistence -> audit/idempotency persistence, one outer transaction. Warehouse
pack selection/detail UI invokes only that action. Package -> stock locks retain
sorted order; release never locks another shipment. Existing claims/reservations
must be removed through their existing workflow first.

New table: package_customer_releases, package primary key, source order identities,
actor/time/reason and released remaining quantity. No existing source relationship
is cleared. A release stops applying if restored quantity exceeds its recorded
scope or source identity changes. No new configurable permission or status is
introduced; existing admin and factory policy apply. Canonical PackageStatus,
ShipmentStatus and FinishedGoodsStatus describe existing action subsets; reference
IDs, reason and source identity arrays are data, not new enum vocabularies.

Affected source studied: shipment create/scan/add/replace/final dispatch, allocation
service, standalone package ship, partial dispatch/reopen, ready-pack and piece
reservation selection, warehouse customer reservations, package detail and warehouse
stock UI, auth/admin/factory policy, schema registration and audit/idempotency.

## Evidence and acceptance state

**AI_VERIFIED_AWAITING_HUMAN for this scoped feature; not merged or deployed.**
Independent source review by `/root/customer_guard_review` found and then verified
fixes for direct-only source attribution after partial dispatch and later-reservation
bypasses. Its independent final API run passed 46 cases. Human technical approval
by Ismail and business/operator acceptance by Shavkat have not been recorded.

- Final focused run: **71 passed, zero skipped**, 22.56 seconds. It includes 46
  feature API cases, 16 existing shipment query/lock-budget cases (1/50/401 packs),
  three new real PostgreSQL release race/rollback cases and six adjacent real
  PostgreSQL allocation/reservation cases. New table creation is exercised through
  actual Alembic upgrades in the identity-pinned PostgreSQL fixture.
- Wider affected run: **263 passed, one failed, zero skipped**, 92.82 seconds.
  The failure is `test_finished_goods_reserve_integrity.py::test_postgres_package_reserve_and_damage_keep_one_valid_state`:
  when damage wins, existing reserve returns 400 while the test expects 409.
  Untouched base `77d090f6` reproduced exactly the same assertion on the same
  disposable PostgreSQL server (one baseline attempt passed; the next failed).
  This wider run remains FAIL; no test assertion or unrelated reserve/damage
  behavior was changed to conceal it. The scoped feature tests are green.
- Deliberate customer-guard and admin-permission faults in disposable source
  copies were detected by the real API regression assertions; candidate restored.
  The original cross-customer scan was reproduced RED before implementation.
  Six later-reservation scan/add/standalone cases also failed before their fixes.
- Bounded integrity: 200 source packs released, ten retries, exactly 200 release
  rows/audits and identical stock/source fingerprints; 201 IDs refused. Concurrent
  release creates one ledger row/audit; precommit failure rolls both back.
- Frontend strict TypeScript, scoped ESLint, localized error-message tests, all
  existing build prerequisites and the optimized 98-route build passed. Ruff,
  Python compilation and whitespace checks cover affected paths. The first build
  correctly refused a missing API_URL; builds then used only the task's loopback API.

Docker Desktop failed during startup. Instead, official EDB PostgreSQL 17.6
[portable binaries](https://get.enterprisedb.com/postgresql/postgresql-17.6-1-windows-x64-binaries.zip)
ran under this worktree's ignored `outputs/qa/pgdata`, bound only to 127.0.0.1:55483.
The runner independently read version/system identifier/data-directory/port and
configured the repository's unchanged approved-instance checks. Owned fixture
databases/schemas were removed after tests. Production PostgreSQL was never used.

Connected Chrome exercised the actual local Next/FastAPI site with disposable
SQLite data: A's pack refused in B's shipment; warehouse grouped selection released
only the checked pack with a reason; sibling stayed restricted; reopened details
showed persisted actor/time/reason; released pack scanned and shipped to B. The
final backend was restarted from the frozen candidate and that refusal -> release
-> successful scan/dispatch sequence was repeated on the second fixture pack.
Database readback conserved both source order/production links and original 16
pieces, recording two explicit releases and 16 sold pieces. No stock was created.
Nonadmin warehouse login showed zero release controls. English, Russian and Uzbek
controls were inspected, including Russian/Uzbek phone-width forms and cancellation.
Browser warning/error logs were empty. Saved readable final preview:
`outputs/qa/admin-release-preview.png`; readback: `outputs/qa/browser-readback.json`.
Intermittent browser screenshot transport timeouts were retried through documented
browser controls; the final preview was successfully captured and inspected.

Local reports: `outputs/qa/customer-pg.xml` (71 passing),
`outputs/qa/affected-with-pg.xml` (263/1 retained failure),
`outputs/qa/baseline-pg.xml` (same base failure), and task-owned fault runner/results.
These are ignored local evidence; the production release and database revision
remain green 20261102_063110 / 0149. Candidate migration head is 0150.

Two old PG fixtures explicitly whitelist tables and now include the release
ledger; two mocked stock rows now include real source fields. Their assertions
are unchanged. Ordinary source-free legacy standalone dispatch semantics remain
as before; the new standalone reservation refusal applies to admin-released packs.
This task does not claim to fix the previously known legacy bypass surface.

## Human acceptance and future release

1. With approved non-production fixtures, select A when creating the source order,
   produce/receive packs and try one in B's shipment: no matched scan or stock move.
2. As warehouse staff, confirm no release control and a direct release API returns
   403. As an admin in the owning factory, open Warehouse Stock -> Actions ->
   Release for any customer, choose exact packs and enter a reason.
3. Reload: actor/time/reason persisted; source order, production identity, QR,
   quantities and unchecked siblings stay intact. Scan released pack for B and
   ship through the normal reviewed workflow. Check partial remainder separately.
4. An active reservation/open shipment must prevent release. A later reservation
   must prevent another order using the released pack. Reopening more pieces than
   the recorded release quantity requires a fresh admin decision.
5. Record human approval of the exact build. Merge/push/deploy require separate
   authorization. Migration 0150 is additive and changes no existing business row;
   deployment still requires backup and DEPLOYMENT.md. Old runtime rollback drops
   enforcement of this new application rule, so it is not a policy-preserving
   rollback even though the additive table is schema-compatible.
