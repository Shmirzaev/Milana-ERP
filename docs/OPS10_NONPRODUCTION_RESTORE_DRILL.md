# OPS10 non-production recovery drill record

This is a preparation and evidence template, not proof that a restore has been
performed. Complete it only during an explicitly approved, isolated,
non-production drill. Do not connect the recovery environment to production
services, credentials, traffic, queues, or integrations.

## Decisions required before the drill

The relevant owners must approve and record these values before an observed
drill can establish whether recovery meets business requirements:

| Decision | Owner | Approved value / reference |
| --- | --- | --- |
| Maximum recovery time (RTO) | Business owner | TBD |
| Maximum data loss (RPO) | Business owner | TBD |
| Backup cadence and recovery-point selection | IT / operations | TBD |
| Database and file-backup retention | Business / legal / IT | TBD |
| Off-host copy and restore credentials | IT / security | TBD |
| Drill frequency and scope | Business / IT | TBD |
| Drill approver and observer | Business / IT | TBD |

Do not infer these values from this template or from a single local run.
Retention cleanup must not be introduced until the relevant retention policy
and protected-copy requirements are approved.

## Safety gates

Before starting, the incident/recovery owner and observer confirm:

- The database backup and storage snapshot are approved drill inputs, copied to
  a restricted isolated target. Record their opaque artifact IDs and hashes;
  do not put secrets or customer data in this document.
- The target database, file storage, backend and frontend are separate from
  production. Production DNS, public ingress, scheduled jobs, 1C clients,
  attendance devices, email, object stores and other external integrations are
  unreachable or explicitly disabled.
- Restore credentials are available through the approved secret channel and
  are not copied into the repository, shell history, logs or drill record.
- The paired backup manifest is verified against the exact dump and restored
  storage snapshot with `scripts/storage_recovery_manifest.py verify`, as
  specified in `DEPLOYMENT.md`.
- A clean recovery database is used. Restore and migration commands come from
  the approved recovery procedure and are recorded by the operator; do not
  improvise destructive commands against a non-empty or shared database.
- The observer records UTC timestamps and any pause, retry, manual repair,
  missing artifact or safety stop. A stopped or failed drill is retained as a
  failed result, not silently restarted as a clean pass.

If any isolation or artifact-identity check fails, stop before restore and
record the blocker. Do not switch traffic or write to the source artifacts.

## Drill observations

Record the following for one identified attempt:

| Evidence | Recorded value |
| --- | --- |
| Drill ID / approved change or incident reference | TBD |
| Scope and recovery owner | TBD |
| Observer | TBD |
| Start and end time (UTC) | TBD |
| Source backup timestamp / artifact ID | TBD |
| Paired storage snapshot ID | TBD |
| Manifest verification result and hash | TBD |
| Isolated target identifiers (non-secret) | TBD |
| Database restore start / finish (UTC) | TBD |
| Storage restore start / finish (UTC) | TBD |
| Application startup and migration result | TBD |
| Health/readiness and admin authentication result | TBD |
| Representative business-record checks | TBD |
| File checks for each configured storage class | TBD |
| Failures, retries, manual interventions, safety stops | TBD |
| Latest recovered data timestamp and measured data-loss interval | TBD |
| Total elapsed recovery time | TBD |
| Owner assessment against approved RTO/RPO | TBD |
| Follow-up actions, owner and due date | TBD |
| Business owner approval / date | TBD |

At minimum, validate representative users/roles, recent sales orders,
inventory batches, packages/shipments, audit history, and retrievable files
from barcode, model-file, sales-order-file, and any other configured storage
classes. A successful pairing-manifest check alone is not a successful
database/application recovery.

## Completion criteria

Call the drill witnessed only when an observer saw the isolated restore and
the evidence above is retained. Call it successful only when the recovery
owner and business owner evaluate the observed recovery time and data-loss
interval against the values they approved before the drill, all required
record/file checks pass, and failures/actions are documented. This procedure
does not declare an RTO, RPO, retention schedule, backup durability, or
production readiness.

Keep the approved drill report and exact artifact manifest in the authorized
operations evidence store, not in the source repository. This repository file
is only the reusable checklist.
