# OPS11 credential custody and rotation checklist

This checklist contains no credential values and does not authorize a
rotation. The task that added it did not inspect secret-manager contents,
production environment files, old handover documents, or external callers.
Complete it with the system owner and security owner before marking OPS11
closed.

## Establish custody

- Select the organization-approved vault/secret manager and identify the
  non-secret record ID for each credential. Do not put values, exports, or
  screenshots in this repository, tickets, email, chat, or handover documents.
- Reconcile the inventory against each authorized source of truth without
  exporting values: deployment-provider secrets, the backend host's shared
  environment configuration, CI/environment secret names, database/service
  accounts, and external machine clients (including 1C and attendance devices).
- Assign one accountable primary owner and one backup owner for every
  credential, plus named custodians/groups with least-privilege vault access.
  Avoid shared human accounts. Confirm access/recovery procedures with the
  vault administrator.
- Record the consuming service/client, environment, issuer, vault record ID,
  access group, creation/last-rotation date, expiry/next review date, and
  rotation/revocation behavior. Record identifiers and metadata only, never
  the value or a reversible fingerprint of it.
- Check handover material locations with their owners. Replace embedded values
  with vault references and notify recipients to stop using retained copies.
  Preserve required audit evidence; do not mass-delete documents or backups
  without the records owner and retention policy.

## Plan and perform an owner-approved rotation

1. Inventory every active consumer and confirm the replacement/overlap
   mechanism supported by that service. Set an owner-approved maintenance
   window, validation plan, rollback point, and revocation deadline.
2. Generate the replacement only in the approved secret manager. Transfer it
   directly through that manager to authorized consumers; never use command
   arguments, shell history, source files, or logged deployment output.
3. Update one consumer at a time where supported. Validate the real
   authentication/connection flow and alerting without logging request
   headers, environment values, secret-bearing URLs, or response bodies.
4. For signing/session keys, explicitly account for effects: rotating the JWT
   signing key may invalidate active sessions; rotating file-signing material
   may invalidate existing signed URLs. Keep JWT and file-signing keys
   distinct. Schedule user/client communication where reauthentication is
   expected.
5. For machine integrations, coordinate each named client independently,
   confirm the correct client identity and successful replay-safe test, then
   disable the superseded credential after all consumers acknowledge. Do not
   re-enable a legacy shared token as a fallback without explicit security
   approval.
6. Verify the old credential is rejected, monitor for failed consumers, and
   close the overlap window. Update the vault metadata and access list; record
   only completion time, owners, systems checked, results, and any exception.
7. If exposure is suspected, use the incident process immediately; do not wait
   for the planned maintenance window. Preserve incident/audit evidence while
   removing access to exposed copies under the records policy.

## Value-free evidence record

Keep one record per credential or coordinated client group. Store it in the
approved operations record system, not beside the credentials.

```text
logical credential ID (no value):
service / environment / consumers:
vault record ID:
primary owner / backup owner:
authorized vault group:
issuer / rotation mechanism:
last rotation / next review / expiry:
rotation window / overlap end / revocation time:
consumer validation results / monitoring reference:
handover-copy locations reviewed / records owner:
exception, approver and expiry (if any):
```

## Closure gate

OPS11 remains open until the owner has reconciled all credential consumers and
handover-copy locations, approved vault custody and recovery, assigned owners
and review dates, and completed/verified rotations for credentials whose
handover copies could have escaped. Repository documentation and a pattern
scan cannot prove what values exist in external documents, vaults, host
configuration, backups, or third-party clients.
