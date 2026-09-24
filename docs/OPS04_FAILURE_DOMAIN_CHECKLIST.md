# OPS04 failure-domain and failover evidence checklist

This is a local planning checklist only. It does not verify live hypervisor or
physical-host placement, establish high availability, or authorize an
infrastructure change. The audit finding reports that ERP VMs share a physical
host; this task did not contact production or verify that claim.

## Map the current failure domains

Have the infrastructure owner export a read-only, timestamped inventory from
the virtualization/cloud control plane for the PostgreSQL, backend and
frontend VMs. Record non-secret asset IDs and map each dependency to its actual
failure domains:

- physical server / hypervisor / cluster and anti-affinity placement;
- site, room, rack, power feed/UPS and cooling;
- network switch, uplink, firewall, VPN, DNS and internet circuit;
- storage device, datastore, mount/replica and backup target;
- public proxy/load balancer and its control plane;
- identity, secret manager, monitoring and alerting dependencies.

Use the authorized source of truth (provider/hypervisor inventory), not IP
addresses, VM names, blue/green slots, or separate application processes as
proof of independent failure domains. Include the evidence timestamp and owner
review. Redact unrelated host inventory and credentials.

## Distinguish release rollback from disaster recovery

The two backend/frontend slots and retained releases support application
staging and rollback on the documented VMs. They do not, by themselves,
survive loss of a VM, physical host, shared datastore, power, site, public
proxy, or network path. Database recovery and `/app/storage` recovery require
their own coordinated, tested procedure; see the
[deployment backup/recovery procedure](../DEPLOYMENT.md#stage-source-backup-and-migration)
and [the disaster recovery plan](DISASTER_RECOVERY.md).

For each single failure in scope, record expected impact and approved recovery:

| Failure domain | Affected services/data | Detection | Recovery/failover mechanism | Owner-approved RTO/RPO | Last test/evidence |
| --- | --- | --- | --- | --- | --- |
| Physical host / hypervisor | | | | | |
| Database VM / storage | | | | | |
| Backend VM / upload storage | | | | | |
| Frontend VM / public proxy | | | | | |
| Site power / network / ISP | | | | | |

## Evidence and closure gate

1. Record owner-approved RTO/RPO and data-loss policy for each critical
   service. Define who may declare an incident and authorize failover.
2. Document how database, uploaded files, runtime configuration/secrets,
   DNS/proxy and immutable application artifacts are recovered together. Keep
   credentials out of this checklist.
3. Exercise the runbook in an isolated/non-production environment first.
   Preserve the exact fault injected, start/end times, detected symptoms,
   manual steps, data-integrity checks, measured recovery/data-loss times,
   failed steps, and owner sign-off. A tabletop is useful but is not a
   successful technical failover test.
4. Repeat only with explicit infrastructure authorization before any
   production fault-injection. Do not stop a VM, block a route, edit DNS, or
   change storage/replication settings as part of documentation work.

OPS04 remains open until actual placements and shared failure domains are
verified, the owner-approved architecture addresses them, and recovery or
independent failover is demonstrated against the selected RTO/RPO.
