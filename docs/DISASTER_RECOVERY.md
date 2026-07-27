# Disaster Recovery Plan

This plan must be completed and tested before production launch.

## Recovery Objectives

Set these values before launch:

- RTO: TBD by business owner.
- RPO: TBD by business owner.
- Backup retention: TBD by business owner.
- Restore test frequency: recommended monthly before launch, then quarterly.

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

## Restore Procedure

1. Create a clean recovery database.
2. Restore the latest approved database backup.
3. Restore backend file storage from the matching backup snapshot.
4. Restore the shared backend and frontend environment files from the approved secret backup.
5. Deploy backend and frontend using `DEPLOYMENT.md`.
6. Run the release migration before switching the `current` symlinks.
7. Validate `/health`.
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

- backup timestamp
- restore start time
- restore finish time
- data loss window
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
