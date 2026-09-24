# OPS03 shared infrastructure, limits, and schedule review

This is a read-only evidence procedure for an authorized infrastructure owner.
It does not assert that Milana ERP shares a host with another workload, that a
backup job is configured, or that contention has occurred. No host, database,
backup, or scheduler was inspected while preparing this document.

## Evidence currently in the repository

- `deploy/slotctl.py` declares two blue/green backend slots, two workers per
  slot, SQLAlchemy pool size 8 and overflow 4. Its calculated peak across both
  slots is `2 × 2 × (8 + 4) = 48` connections; the declared PostgreSQL ceiling
  is 100. This is an application configuration budget only. Other clients,
  admin sessions, backup/monitoring processes, actual effective settings, and
  non-application resource limits are not included or verified here.
- `DEPLOYMENT.md` requires a PostgreSQL dump paired with a storage snapshot and
  an exclusive-create SHA-256 manifest. The manifest proves artifact identity
  at verification time; it does not prove that backups run on a schedule,
  reside off-host, are retained, or avoid production load.
- `docs/OPS10_NONPRODUCTION_RESTORE_DRILL.md` records a separate isolated
  restore drill. Artifact verification and local tests are not a restore or a
  resource-contention measurement.

## Approval and ownership

Before collecting host evidence, identify the exact authorized environment,
review window, change/incident reference, and read-only access scope. Record
owners and supporting systems without secrets:

| System / workload | Host or service boundary | Accountable owner | Resource limits / isolation | Evidence source and date |
| --- | --- | --- | --- | --- |
| ERP PostgreSQL | TBD | TBD | TBD | TBD |
| ERP backend slots / proxy | TBD | TBD | TBD | TBD |
| ERP frontend slots / proxy | TBD | TBD | TBD | TBD |
| Database backup and WAL/archive process | TBD | TBD | TBD | TBD |
| Storage snapshot / replication process | TBD | TBD | TBD | TBD |
| Other workloads on shared hosts/storage/network | TBD | TBD | TBD | TBD |
| Monitoring, security scan, maintenance jobs | TBD | TBD | TBD | TBD |

An unknown owner, host boundary, schedule, limit, or evidence source stays
`unknown`; do not infer it from a repository setting or a host name.

## Read-only verification sequence

Run only from an approved administrative session. Capture UTC time, source,
scope, and tool/version with each observation. Redact credentials, customer
data, full command environments, and unrelated tenant details.

1. **Resolve topology and ownership.** Ask infrastructure/DB/backup owners for
   the authoritative inventory of hosts, VMs/containers, shared disks, network
   links, backup targets, backup operators, alert owners, and maintenance
   windows. Compare this inventory with approved infrastructure-as-code and
   service-manager configuration. Record disagreements rather than choosing
   one source silently.
2. **Verify configured limits without changing them.** Read the effective
   backend worker count, per-worker DB pool and overflow, slot overlap,
   PostgreSQL `max_connections`, current connection use/roles, container or
   cgroup CPU/memory quotas, disk capacity/inodes, storage I/O limits, and
   network shaping/quotas. Record configured values separately from observed
   values. For PostgreSQL, include non-ERP clients and reserved/admin
   connection capacity; do not treat `100 - 48` as spare capacity.
3. **Inventory schedules.** With the backup owner, inspect the scheduler
   definitions and recent successful/failed runs for database full/incremental
   or WAL archives, storage snapshots/replicas, off-host copies, verification,
   pruning, monitoring and maintenance. Record timezone, cadence, duration,
   overlap windows, destination, retention owner/policy reference, last
   success, last failure, and alert destination. A configured timer without
   run evidence is not coverage evidence.
4. **Observe a normal baseline.** At an owner-approved representative period,
   record PostgreSQL connections/maximum and wait events, backend worker and
   slot/container CPU/memory/restarts, host CPU/memory pressure, disk free
   space/inodes and I/O latency/queue, storage throughput/latency, and network
   utilization/errors. Use the approved monitoring source; do not install
   agents or enable new logging as part of this read-only review.
5. **Observe the actual backup window.** Capture the same metrics before,
   during, and after the scheduled database and storage backup, using the
   scheduler's run IDs/timestamps to correlate them. Record backup bytes,
   duration, exit/verification status, snapshot/dump pair ID, and concurrent
   maintenance/other-workload activity. Compare against the owner-approved
   service limits/objectives; this document defines no thresholds.
6. **Report coverage and gaps.** For each database and storage recovery
   artifact, state source, destination boundary, encryption evidence,
   integrity-check result, restore-drill reference, retention policy owner,
   and whether deletion/pruning is governed. Report missing evidence as
   unknown/not verified. Do not run a backup, restore, failover, cleanup,
   scheduler, or load test during this read-only verification.

## Review record

| Field | Value |
| --- | --- |
| Review ID / authorization reference | TBD |
| Environment and scope | TBD |
| Observer / technical owner | TBD |
| Review start/end (UTC) | TBD |
| Normal-window evidence references | TBD |
| Backup-window evidence references | TBD |
| Effective limit/config snapshots | TBD |
| ERP and non-ERP connection/resource maxima | TBD |
| Database backup schedule / last verified success | TBD |
| Storage snapshot/copy schedule / last verified success | TBD |
| Retention and off-host policy references / owners | TBD |
| Contention or coverage observed | TBD / not observed / unable to determine |
| Deviations, unknowns, action owner and due date | TBD |
| Infrastructure/DB/backup owner review | TBD |

A successful static configuration check or quiet sample does not prove that
capacity is adequate under peak load. A backup-window sample without a
representative run does not establish backup impact. Keep source evidence in
the authorized operations evidence store; this repository contains only the
reusable checklist.
