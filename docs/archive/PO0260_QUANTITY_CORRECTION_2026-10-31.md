# PO-0260 quantity correction — 31 October 2026

Owner request: "make all 250 500 is wrong". Scope is the erroneous actual/output
and derived downstream quantities for PO-0260, not the original 300-piece order
plan or new business records. Owner explicitly approved the matching clone_main
baseline after origin/main's stale production metadata was reported.

Source worktree: `C:/ERP/.codex-work/correct-po0260-20261031`, branch
`codex/correct-po0260-20261031`, starting at `5bffd255981c57e5f356f6f9b7fb568f55d585bf`.
Both application VMs independently resolved active `20261029_111113`, manifest
`93d632752aa355efad66fc67bf294fa6eb6321e90769106fc5de71c4cb6b7720`, matching
clone_main's production-base metadata. The runtime source was not edited or deployed.

## Evidence and exact changes

Order 285 / PO-0260 had five received 50-piece bundles, total 250. Cutting record
299 had five bundles / 250 bundled pieces but stale 500 cut / passed pieces. Its
creation audit recorded ten bundles. No Sewing output, daily report, Printing
output, Packaging receipt/output, package, finished stock or replacement existed.

The guarded operation locked the order, work orders, Cutting record, assignments
and bundles, checked an exact before-state fingerprint and changed seven rows:

| Record | Corrected fields | Before → after |
| --- | --- | --- |
| Cutting record 299 | cut_pieces, passed_pieces | 500 → 250 |
| Cutting work order 1116 | actual_input_qty, actual_output_qty, passed_qty | 500 → 250 |
| Sewing work order 1117 | planned_input_qty, planned_output_qty | 500 → 250 |
| Packaging work order 1118 | planned_input_qty, planned_output_qty | 500 → 250 |
| Storage work order 1119 | planned_input_qty, planned_output_qty | 500 → 250 |
| Cancelled assignment 161 | quantity | 500 → 250 |
| Planned assignment 163 | quantity | 500 → 250 |

Updated timestamps changed on these seven rows. All statuses, original plan 300,
five order breakdown rows, passport, material plan, five bundles and ten scans were
preserved. Protected linked evidence hash before/after:
`7ece91b186d6d7e98023925e81c243086d0bcc68d9faa975589df87b5f0f723a`.

## Backup and verification

Validated PostgreSQL backup:
`/opt/milana-erp/shared/backups/milana_erp_pre_po0260_quantity_20261031_094218.dump`.
103,887,746 bytes, mode 0600, 1,246 restore objects, SHA-256
`17b58e3ab57dea4cfd6986b30aede5a8d1c0538819026c85471506412747ab83`;
restore-list SHA-256 `2fd3b16290301af4ee51fe7fd6005626070562eaf5afc7c4ceab31d7c4d45529`.

The rollback rehearsal returned Actual/Cut/Bundle quantity 250 and restored the
exact before fingerprint. The first apply attempt also rolled back because its
pre-commit audit lookup preceded the live audit service's commit-time insertion.
The runner was corrected to use the returned audit object after the normal outer
commit; rehearsal was repeated successfully before the successful application.
No quantities persisted from the failed attempt.

Successful application audit: 173981, `correct_po0260_quantity`. Independent
read-only persisted resolver checks returned Actual/Cut/Bundle 250, five bundles;
hash-chain verification for that appended audit passed. Signed-in Chrome page
`/work-orders/1117/sewing` was refreshed and visually showed Actual 250, Received
5 bundles / 250, and selected line 250/250. No Sewing record was submitted during
verification. All four internal/public backend-health/frontend-login checks were 200.

Operational scripts are `ops/correct_po0260_quantity.py` and
`ops/backup_po0260_quantity.py`. Ignored evidence is in `outputs/po0260/`.
This was a single-order data correction, not a general application fix for stale
Cutting totals following bundle changes. Existing broader risks remain open.
