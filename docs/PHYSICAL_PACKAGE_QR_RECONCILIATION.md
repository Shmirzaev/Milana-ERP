# Physical package QR identity

Warehouse inventory counts and dispatch identify an individual package. A legacy
sticker such as `uzerp_ii_20818_6` must not resolve to a sibling such as
`uzerp_ii_20818_10`. Receiving print-run grouping remains unchanged. Repeated scans
of the same physical package still count once. Ambiguous shared codes cannot
verify successive shipment packages; the operator must use individual QR labels.

The September 5 reconciliation consolidated legacy sticker packages and retained
their codes as aliases. The September 28 user request authorizes reconciliation
of all those aliases against their immutable receipt evidence.

## Reviewed repair procedure

Run `backend/scripts/reconcile_physical_package_qrs.py` with `PYTHONPATH=backend`.
The default is a dry run that returns operations, exclusions, quantities and a
SHA-256 guard. Review it and take the deployment-procedure PostgreSQL backup
before using `--apply --expected-sha256 <reviewed digest> --actor-id <actor>`.
The application source must be the exact reviewed release commit.

Apply acquires table locks with a ten-second lock timeout, rebuilds the plan and
rejects changed evidence. It commits atomically through the CLI. Existing
packages, stock rows, original receipts, reservations, and shipment history are
not rewritten. Eligible orphaned approved sticker receipts regain their own
package and available stock; misleading aliases to already existing packages are
removed. Parent groups with downstream activity, uncertain receipts, conflicting
identity or inconsistent stock remain excluded for individual review. Excluded
physical codes cannot substitute sibling packages in count/dispatch.

Restoration uses the receipt's quantity, weight and source identity, the verified
parent's catalog/warehouse context, and current consistent stock prices. Original
stickers list sizes without quantities per size, so restored stock uses
`ASSORTED`; no equal size distribution is invented. Historical evidence remains
accessible on each package. Restore does not reuse an assumed storage cell.

For unfinished counts, a scan previously recorded against the wrong package is
moved to the correct identity, preserving its code, timestamp and operator with
an audit entry. Count-start snapshots stay unchanged; restored packages absent
from that snapshot are marked unexpected. Completed reports remain frozen.
Future duplicate count attempts record their exact submitted code in the audit.

## September 28 dry run and rehearsal

- 3,036 consolidated code mappings examined.
- 2,729 eligible packages / 186,147 pieces to restore.
- 187 erroneous aliases point at packages that already exist.
- 120 exclusions: 111 downstream-history conflicts, six missing/ambiguous
  receipts, two receipt-model conflicts and one non-individual sticker code.
- Local production-data rehearsal preserved all 6,238 original package records,
  all 15,904 original stock records, receipt/reservation/shipment fingerprints,
  and produced exactly the reviewed stock increase. A repeat found no further
  applicable operations. All nine photographed labels resolved separately.
- Two current-count scans require identity correction. These are existing scan
  observations; the repair does not create additional physical scan events.

The dry-run plan, exclusion report and rehearsal evidence are retained under the
task worktree's ignored `outputs/reconciliation` directory. Recheck this plan
against production immediately before applying; the counts above are not proof
that a later state is unchanged.

## Production application, September 28

Release `20260928_114232`, commit `d03227f3`, applied the exact reviewed production
plan `c51318ab37016d50529871c799dc7c727bd5497046a5c32259383acbdf2a1e56` after a
verified PostgreSQL backup. Actual results matched the rehearsal: 2,729 packages
and 186,147 pieces restored, 187 obsolete aliases removed, two open scan identities
corrected, and 120 codes excluded for the reasons above. All original protected
business-record fingerprints were unchanged; all nine photographed labels resolve
separately, and a repeated dry run has no applicable operations.

Existing `test1` still has three scans / 174 pieces. Two are now correctly marked
as absent from its original starting stock. Start a new count to include the
restored packages in the expected starting list. No completed count was rewritten.

A separate pre-existing quantity discrepancy was found during final photo review:
`uzerp_ii_20719_1` / `OLD-20719-1` has 78 pieces in its existing package and stock
(six sizes of 13), while its immutable approved receipt and the September 28 photo
both say 60. The identity repair preserved those existing records as planned.
Its quantity needs a separate reviewed stock correction; the other eight
photographed package totals match their labels. The nine identities are distinct,
but their current ERP total is 558 against 540 on the photographed labels.

## Rollback

The data restoration is compatible with the previous application release because
each restored barcode is a normal package with existing receipt evidence. An
application rollback does not reverse the stock restoration. Do not delete
restored packages or restore a database backup after users have reserved or
shipped them. Any data rollback needs a new dependency review and a guarded plan
against the preserved pre-repair backup and reconciliation audit.
