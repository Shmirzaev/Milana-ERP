# Shared infrastructure capacity and operating ownership

Operating owner: **Ismail**, assigned by the user's OPS02/OPS03 completion
instruction. [Owner scope](../deploy/operations-owners.json) covers infrastructure
inventory, admission budgets, contention and backup-job failure follow-up.
Application feature ownership and the separate recovery/security assignments
remain recorded in `bugs.md`.

## PostgreSQL allocation

The [reviewed policy](../deploy/connection-budget.json) retains two ERP slots,
two workers per slot, pool eight and overflow four: **48 ERP connections**.
Shared role ceilings total **39**. The resulting 87 application connections
leave **10 ordinary maintenance slots plus three reserved superuser slots**
inside PostgreSQL's existing maximum of 100. No worker, server maximum,
password, permission or business record change is required.

| Role | Ceiling |
| --- | ---: |
| erp | 48 |
| authenticator | 10 |
| catalog_user | 6 |
| catalog2_user | 6 |
| leadlens | 6 |
| milanaweb | 6 |
| kotiba | 3 |
| milanaweb_user | 2 |

Role ceilings limit new ordinary connections; existing sessions are retained.
Superusers bypass role ceilings. PostgreSQL documents approximate role-limit
checks during simultaneous connection attempts. Keep administrative activity
inside the maintenance allocation; new login roles, additional workers or
privilege changes require a revised allocation before service activation.
These bounds protect global capacity; a service at its ceiling can reject new
connections. Check failed admission and pool timeout counts, and align its
client pool with its allocation before increasing demand or changing ceilings.
[PostgreSQL role-limit documentation](https://www.postgresql.org/docs/16/sql-createrole.html).

## Applying or restoring the allocation

Use `scripts/connection_budget.py` from an exact reviewed Git commit on the
database VM with peer authentication as postgres. Run its default read-only
plan first. It refuses server-setting drift, unidentified login roles,
unexpected superuser privileges and limits below current usage.

Apply requires the exact plan SHA-256 and a new rollback-record path. The
record is written exclusively with mode 0600 before a single guarded
transaction changes all eight role limits. If any identity, limit or active
client check fails, none of the role changes commits. Restore using
`--rollback <record>` and the same policy. Preserve the record on the database
VM and inspect the post-change roles. Never terminate sessions to fit a budget.

Check both ERP slots, public ERP and shared-service responses before and after
the change. Restore the previous limits if availability regresses. This
operation changes role metadata only and does not deploy an application or
migrate its schema.

## Repeatable capacity and contention evidence

`scripts/ops_pool_probe.py`, passed through stdin to the existing ERP backend
image, issues only read-only catalog queries and short `pg_sleep` calls. It
uses the actual 8+4 worker allocation, queues 24 requests across eight rounds,
records checkout waits and refuses to run without four connections of spare
ERP headroom after its maximum of 12 additional clients. Its engine is disposed
on exit. This is a **controlled pool peak**, not an observed factory incident
or a representative factory workload/latency benchmark.

The isolated PostgreSQL test exercises every role at its ceiling, global
saturation, excess-admission rejection, atomic drift refusal and rollback while
an existing session survives. `scripts/ops_capacity_capture.py` records guest
resource limits and database client/wait states without business-row reads.
Retain timestamps and distinguish controlled load from observed traffic.
Correlated actual factory incidents and network-path diagnosis remain OPS01/07.

## Shared resources and backups

Ismail maintains the shared workload inventory and effective VM/container/
systemd limits, checks CPU/run queue, available memory, swap and disk pressure,
and coordinates changes to shared budgets. An unlimited individual container
limit must remain visible; the current VM limits are not per-service isolation.

Ismail checks the enabled daily Proxmox snapshot job `backup-b44c5fd8-0b64`,
VMs 100–104, PBS `backup-17tb`, every included data disk and the successful
completion record. Schedule: 00:00 Asia/Tashkent (19:00 UTC the previous day).
PBS prune retains seven daily snapshots. Escalate failed/missing backups and
capacity shortages to the recovery owner, **Dilmurod (OPS04/OPS10)**. Snapshot
presence does not prove zero RPO, independent failure domains or a witnessed
application restore. Credential/vault rotation remains Dilmurod's OPS11.
