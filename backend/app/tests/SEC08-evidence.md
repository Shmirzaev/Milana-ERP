SEC08: ported the raw-mutation restrictions from e7782ec and the named
validated/audited department rename service from 297d808.
The df1d08f deactivation donor does not fit: clone_main has no Department.is_active,
and that donor needs a schema migration plus assignment/frontend changes.
No deactivation route or schema change is included.

Kept: true-Super-Admin read-only table/row inspection; named department rename
PATCH /repairs/departments/{id}/rename; legacy department.name-only PATCH routes
through that same named service. Names are trimmed, nonblank, <=128 characters
and unique. Repair and audit commit/rollback together.
Blocked: every generic PATCH to all other tables, all department fields besides
name, mixed/unknown/empty repair payloads, and raw DELETE for every known table.
User privilege/factory changes, role edits, audit edits/deletes, stock, payroll,
finance, work-order state, links/IDs/quantities cannot be changed through the console.
The existing operational business endpoints are unchanged.

Branch codex/sec08 from fresh clone_main (includes Ismail's FN07 purchase bounds).
SQLite fail-first: 6 failed, 1 passed; raw escalation/tampering/deletes succeeded.
Fixed targeted tests including security hardening: 36 passed.
Full SQLite suite (-n 4): 2180 passed, 46 skipped in 191.36s.
Ruff/diff checks passed. External fonts supplied macOS compatibility.
Logs: /private/tmp/sec08-{before,after,suite}.log.
No merge, migration, production data change or deployment.
