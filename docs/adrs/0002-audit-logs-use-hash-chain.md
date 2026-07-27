# ADR 0002: Audit Logs Use A Hash Chain

Status: Accepted

Date: 2026-06-18

## Context

Audit logs are central to investigating production, stock, user, and finance changes. Standard database audit rows can be edited or deleted by a sufficiently privileged database actor without obvious evidence unless compared against backups.

## Decision

Each audit row stores:

- `prev_hash`: the previous audit row hash.
- `entry_hash`: SHA-256 over the previous hash and current audit payload.

## Consequences

- Audit history becomes tamper-evident when exported or compared with backups.
- This does not make logs immutable by itself.
- A future verification script should walk the chain and alert on gaps or mismatches.
