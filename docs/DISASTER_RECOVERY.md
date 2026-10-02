# Disaster Recovery Plan

This plan records production recovery requirements and must be implemented and tested against them.

## Recovery Objectives

Approved by the business owner on 2026-10-02:

- RTO: at most 24 hours from outage to restored usable service.
- RPO: zero loss of acknowledged business transactions and their required files.
- Backup retention: seven days of recoverable database and file history.
- Continue using the company's existing server for now. This does not establish independent failover or waive the recovery targets.
- Restore test frequency and incident/vault ownership remain to be assigned.

These are required targets, not measured current capabilities. No backup schedule, replication, retention cleanup or production configuration is activated by recording them here.

## Systems In Scope

- PostgreSQL database.
- Backend file storage:
  - `BARCODE_STORAGE_DIR`
  - `MODEL_FILES_DIR`
  - `SALES_ORDER_FILES_DIR`
- Frontend VM release and shared environment configuration.
- Backend VM release, image tag, and shared environment configuration.

## Backup Requirements

1. Database backups must be automated.
2. Backups must be encrypted at rest.
3. Backups must be stored outside the primary runtime.
4. Restore credentials must not be stored only inside the production system.
5. At least one restore test must be completed before production data is entered.

### Zero-data-loss acceptance

Periodic dumps or VM snapshots alone cannot prove the approved zero RPO. Recovery must retain every acknowledged write even if the primary host and its local storage are lost. Choose and verify synchronous durable database protection in an independent failure domain, together with durable protection for uploaded business files. PostgreSQL WAL archiving and matching file snapshots support recovery history; asynchronous copying alone leaves a possible loss window.

Retain the complete restore chain for every point within seven days: a usable base backup, its required WAL, matching files and protected configuration. Verify that retention cannot remove a prerequisite backup or any active/rollback release protected by `DEPLOYMENT.md`. Approve capacity, backup encryption, storage ownership and the failure model before configuring or deleting anything.

Demonstrate the target in an isolated failure/restore drill with a recorded final acknowledged transaction and file. Show that both survive primary-host loss, the recovered application is usable within 24 hours, and the oldest required recovery point is available. Record failures and measured gaps; do not report zero data loss from a dump listing or a successful health check.

## Restore Procedure

1. Create a clean recovery database.
2. Restore the latest approved database backup.
3. Restore backend file storage from the matching backup snapshot.
4. Restore the shared backend and frontend environment files from the approved secret backup.
5. Deploy backend and frontend using `DEPLOYMENT.md`.
6. Run the release migration before switching the `current` symlinks.
7. Validate `/ready` and `/health` against the recovered dependencies.
8. Log in as an admin.
9. Verify representative records:
   - users and roles
   - latest sales orders
   - inventory batches
   - packages and shipments
   - audit logs
   - uploaded files

## Minimum Restore Test

Before launch, perform a restore into a non-production environment and record:

- backup timestamp and database/WAL/file snapshot identities
- restore start time
- restore finish time
- last acknowledged and last recovered transaction/file, with the measured data loss window
- failed steps
- owner approval

## Incident Roles

Fill this in before launch:

- Incident commander: TBD
- Technical restore owner: TBD
- Business approval owner: TBD
- User communication owner: TBD

## Launch Gate

Do not treat the system as production ready until a restore test has passed and the measured restore time is acceptable for the chosen RTO.
