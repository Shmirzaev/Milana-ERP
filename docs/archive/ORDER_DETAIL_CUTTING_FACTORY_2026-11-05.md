# Production-order cutting factory action, 5 November 2026

## Requested behavior and source

The owner asked where Planning exposes Change cutting factory, then supplied
the Production Order detail screen (PO-0684) and instructed: "add it in this page".
The earlier three-feature release and exact94e visual approval remain valid for
that release; they do not establish human acceptance of this follow-up build.

The follow-up is frozen at `488f3d654b0669a9878b8efd3d34298994e9dc45`, branch
`codex/order-detail-cutting-factory-20261105`, dedicated worktree
`C:\ERP\.codex-work\order-detail-cutting-factory-20261105`. It is pushed and
unmerged. Its four frontend blobs are preserved exactly in source integration
commit `b039fa9918dab71a56f70b7d949a4302641373cc` / draft PR496. The combined
integration migration graph remains separately held; do not deploy that graph.

The detail header reuses the existing action beside Cascade deadlines, binds it
to the displayed order, omits the order picker, and refreshes the page after save.
The Planning dashboard picker remains available. Existing permissions, server
eligibility/refusals and audit operation are reused. No backend, dependency or
migration file changes. The fifth runtime path records the verified production
baseline in `deploy/production-base.json`.

Planning engineer/reviewer ownership remains Ismail/Mirshoir; production ownership
remains Mirshoir with Ismail review. No human signature is inferred from AI work.
The exact UI change creates no new DTO, enum, storage vocabulary or persistence
writer. Existing factory codes and operation services are intentionally retained;
broader schema-writer/type migration remains outside this narrow placement change.

## Exact-source verification

- Complete CI [41983869988](https://github.com/Shmirzaev/Milana-ERP/actions/runs/41983869988)
  passed backend, frontend and immutable release jobs at exact488f3d654.
  Refactor PostgreSQL CI41983862095 also passed. The duplicate push run was
  canceled, not passed; the full dispatch run retained the required checks.
- Local backend: 5,116 passed, 606 skipped, 14 warnings; Ruff/compile passed.
  Required real PostgreSQL CI gates include Planning19, BST27 and ECO8.
- Frontend: 12 component cases, detail-header target/refresh/permission harness,
  strict types, optimized102-page build and contracts passed. Lint has zero
  errors and12 inherited warnings.
- Actual Edge used a loopback production frontend build, candidate FastAPI and
  isolated PostgreSQL16 restored from approved synthetic fixtures. Normal login,
  exact-order dialog, save, reload and reopening passed. The actual database
  readback compared106 table counts and all order/item/work-order rows: only the
  selected cutting work order's department/update timestamp and one audit changed.
  Recorded-work and assigned-operator orders refuse with Save disabled. Normal
  synthetic Cutting-role GET and PATCH both return403. Real preview console
  errors were empty. The earlier memory-only fixture is not persistence proof.
- Bounded real HTTP check declared20 capability reads, maximum concurrency2,
  three sequential same-destination PATCH requests,10s request/40s total bounds.
  It passed in2.187s: one transition, one audit,106-table integrity and recovery
  GET passed, zero unexpected HTTP errors. Production was never its target.

Independent reviewer `/root/floor_pictures` inspected the exact source, actual
screenshots/browser receipt and environment scripts, independently recomputed
both raw persisted deltas and their continuity, and recorded
**AI_VERIFIED_AWAITING_HUMAN**. Review receipt SHA-256:
`0d03848008160ca1fe044fe369eef377bb2c90fb8e43ebdd4bd751ffb31c6a3b`.
Scope limits:106-table counts, full rows for orders/items/work orders and prior
factory audits; actual compact906px English preview. No actual phone-viewport
claim; EN/RU/UZ copies passed component tests.

Private evidence lives under the runtime worktree's ignored `outputs/qa-20261105/`
and `outputs/visual/`. Synthetic credentials and raw private evidence are not
published. Independent verification and human acceptance are recorded separately;
human acceptance of this new build is pending.

## Deployment state and capacity hold

This follow-up is **NOT DEPLOYED**. Verified active production remains green
`20261105_043000` / `94e4cfc54c6cc4fd5787bcbc7ba8483f4518a507`, manifest
`dd662d889407378ce78d22ebb40e5ce3f53a3043377027b84315f8733234b257`.
Working rollback remains blue `20261104_080711` / `984aeffb22aedd3262d7cd61e2d88a905b589e8d`.
Database remains `0154_eco_receipt_details`; no DDL or BST handoff replay.

Candidate CI release `20261105_065721` has manifest
`e6c603d4c1954c64a75962cf189427eb5e316c039ea23de4699b9bd4f3112095`.
Its immutable images are backend
`sha256:3318e1f1c32c68a14bee4cf401b32e1271ff00c86b29dd041dde7d1c90e0518f`
and frontend `sha256:cc101bb98011609eef4be640b7d53ff6595b4c5f1648bd81c6d6f3beb8f368b2`.
Local image exports were checked against platform configs, uncompressed layer
hashes and committed parent chains. No candidate image has been pulled on production.

The backend staging capacity projection fails the unchanged below80% disk guard:
2,247,874,128 bytes peak allocation versus1,465,860,095 bytes available headroom.
The frontend projection passes. Backup allowance has an actual512MiB hard file
limit; existing RAM/disk reserves and thresholds remain enforced. No lease,
cleanup, backup, staging or cutover has run. A read-only investigation is preparing
a concrete archived-unused ERP image cleanup proposal; it is not approval to
remove images or unrelated data.

Before cutover: complete independent evidence review and new exact-build human
visual acceptance; resolve capacity through a reviewed explicit scope, measure
actual reclaimed space and rerun capacity; then follow DEPLOYMENT.md for owned
leases, full backup/restore-list proof, zero pending migrations, inactive-slot
staging, normal signed-in read-only candidate QA, default paired performance,
backend-first activation, public QA and all four health/closing checks. Existing
deployment authorization and waiver of30-minute monitoring persist. No timed
monitor has been created or run for this follow-up.

## Human local checklist

Use the isolated preview at `http://127.0.0.1:3097/production-orders/1` in Edge.
The records are synthetic. Check the header button beside Cascade deadlines,
open it, confirm PO-0001 is fixed, change factory, save and reopen after reload.
Check `/production-orders/2` and `/production-orders/3` refuse unsafe changes.
Record approval/rejection of exact488f3d654. Existing production PO-0684 has not
been changed as a test. Human production acceptance remains separate.
