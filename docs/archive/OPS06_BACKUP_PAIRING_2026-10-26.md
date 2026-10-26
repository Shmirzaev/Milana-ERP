# OPS06 backup pairing candidate — 26 October 2026

Owner Dilmurod; reviewer Mirshoir. Candidate from `origin/clone_main` `b92ee8ff`.
This is not a production backup, restore or deployment.

## Existing state

`DEPLOYMENT.md` requires a unique custom-format PostgreSQL dump, mode 0600,
`pg_restore --list`, object count, sizes and SHA-256. Prior deployment records
name dumps under `/opt/milana-erp/shared/backups/`. The backend container mounts
host `/app/storage` at the same path; configuration uses `barcodes`,
`model_files`, `sales_order_files`, `attendance_photos` and `hr_documents` below
that root. `docs/DISASTER_RECOVERY.md` calls for matching database/file recovery
but says scheduling, replication and retention are not activated by the plan.
No paired upload artifact or shared pair ID is documented in this checkout, and
no backup cron/timer configuration was found here. Live host schedules and actual
backup inventory were not inspected.

## Verification contract

The donor `13f5994` fits the current `scripts/` and deployment layout for
hashing, but did not inspect file references inside its dump. The candidate
uses a new manifest to bind the dump's SHA-256 and size to every regular file
under the supplied storage snapshot. It compares names, sizes and hashes and
reports missing, extra and changed files. It reads known upload-bearing columns
from the supplied custom-format dump through local `pg_restore`, including
model/stock images, printing attachments, QR images, system logo, cutting
passport image, HR document `stored_name` and attendance `photo_file_name`.
External URLs are excluded. A manifest cannot be created if a database
reference is absent from its storage snapshot. Verification rechecks references
and reports `missing_referenced_files` separately.

The script connects to no server and does not alter the dump or storage tree.
`create` writes one new mode-0600 manifest outside both artifacts; `verify`
writes nothing. It fails closed if an expected table/column is absent from the
dump or `pg_restore` cannot read it. Operators must quiesce writes and record the
capture interval; hashes alone cannot prove simultaneous snapshots, backup
authenticity, off-host durability, or zero RPO. An isolated restore drill remains
required. Inventory extras mean files added relative to the saved manifest;
unreferenced files already present when paired are retained because some files
are generated caches or historical retained uploads.

## Evidence

- Fixture tests: clean pair, missing/extra/changed files, mismatched dump and
  storage identities, DB-referenced file absent at creation/verification,
  internal HR/attendance/JSON paths, symlink refusal and path traversal refusal.
- A disposable local PostgreSQL 18.4 custom-format dump with all mapped tables
  and four file references passed `create` and `verify` against a four-file
  storage snapshot. No production database or backup was accessed.
- Fixture tests: 18 passed. Full backend suite: 3,864 passed, 312 skipped,
  13 warnings (exit 0). Ruff on `backend/app` and both changed scripts passed.
  An optional whole-`scripts/` Ruff sweep failed on three untouched unused
  imports in training generators; those files are outside OPS06.

Gate 3 actual visual recovery workflow and Gate 4 bounded restored-service
stress/persisted readback are BLOCKED without an approved isolated restore
environment. No production data, release, slot or rollback state was changed.
