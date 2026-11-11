# Besttex manual order 8823-01 payroll correction

Performed 11 November 2026, 15:02:36 Asia/Tashkent (10:02:36 UTC).

## Owner scope and source

The owner asked to delete every payroll label for the pictured order, including
the amount calculated for employees, so staff can print again. The later explicit
correction was: "do not restore just delete the labels from order". No label from
the preceding investigation was restored.

The picture's QR `200203248` identified Besttex manual order
`MAN-8823-01-94WJ3U`, batch 01, model BJ5033, variant V-6741, sewing line Minura
Toshboyeva. This is distinct from previously investigated order 8824-01 / V-6742.
Both serving hosts matched release `20261111_052632` and source manifest
`55d0edc9b7893df95987102cc6d9ccbe5b59a89f3c369eb5ea1f46a9868d4520`.
The owner approved using verified `origin/clone_main` after the stale
`origin/main` production-base mismatch was reported. Worktree:
`C:\ERP\.codex-work\delete-bst-8823-labels-20261111`, branch
`codex/delete-bst-8823-labels-20261111`, base `3053788f2e17bd5585bccf8cd4547a62cc297516`.
This is an explicitly authorized data correction, not an application release or
refactoring acceptance. Domain engineering/review owners remain Dilmurod/Mirshoir;
no human engineering acceptance by them is claimed.

## Exact data effects

- Deleted 138 QR labels for only factory BST and the exact manual order/model.
- Changed 66 active, periodless `recorded` payroll entries to `voided`, removing
  780,960 UZS of active earnings across nine employees. No paid/approved/locked
  period or linked adjustment was involved.
- Preserved all 93 payroll history rows, including 27 already voided entries,
  with employee/work/quantity/rate/amount evidence unchanged. Cleared live
  `scan_uid`, retained `original_scan_uid` and archived dedupe keys for all 93,
  so fresh deterministic label issuance and same-date scanning can work without
  inheriting cancelled scan identities. Previous keys are in the correction audit.
- Added one atomic, owner-authorized audit entry `242175` with no impersonated
  staff actor. Full original target evidence is preserved in the backup/private
  inspection; the audit records label IDs, payroll identities and amounts.
- Restored zero labels. No changes to order 8824-01, catalog configuration,
  employees, periods, adjustments, manufacturing, inventory or shipments.

## Backup and execution evidence

Full PostgreSQL backup, completed and validated before application:

- Path: `/opt/milana-erp/shared/backups/milana_erp_pre_bst_8823_delete_20261111_100002.dump`.
- Size: 121,632,220 bytes; permissions `0600`; 1,400 restore objects.
- Dump SHA-256: `cc10d4ac70473c68ae9511b56be9c8f1de77370cfb208584e940bb45321010cd`.
- Restore-list SHA-256: `7c2daf97ba2dae89c3f95293ef68448370d1b7a757006223c4c95270e1b23704`.

Reviewed operation committed before execution as `c6a52dc16`:
`ops/delete_bst_8823_labels_20261111.py`, source SHA-256
`54bf4da0c979674ff9a3070146407ede10232811950a704c8964c8e0aeb1c64f`.
Independent Codex reviewer `/root/review_payroll_cancellation` confirmed no remaining
actionable finding on those exact bytes. No runtime file, image or container was
edited. The program ran through stdin using existing production schema-owned
persistence and audit helpers with one outer transaction.

The initial full-JSON conservation rehearsal passed but held payroll writer locks
too long (roughly 45 seconds). The final version uses per-row scalar fingerprints
covering pay/scope/identity fields, while still comparing every target evidence
field. Its complete SSH/startup/rehearsal/readback took 6.58 seconds. The final
rehearsal rolled back all changes and reproduced the exact original target hash:
`fd04378c00a4e6f3bec883c62c116cfc53cc068ea9356adbf0343646b5a6b6ff`.
No rehearsal audit or business insert was committed.

## Verification and handoff

- Python compilation and Git whitespace check passed.
- Final rehearsal and committed operation both passed bounded lock/statement
  timeouts, exact snapshot/count/amount guards, target relationship checks, full
  retained-target-field comparison and unrelated payroll scalar conservation.
- Persisted readback: zero order labels, zero active payroll rows/earnings,
  93 retained voided history rows; all live scan identities released.
- Actual serving `list_qr_labels` business service returned total/available/
  scanned/closed counts of zero; `resolve_qr_token` rejected `200203248` with 404.
- Correction audit hash and its predecessor link both verified. This verifies
  the new entry, not a claim about the entire historical audit chain.
- Internal backend health, internal frontend login, public health and public
  login each returned HTTP 200.
- No browser visual check or broad application suite was run for this data-only
  operation; application runtime source was unchanged. Staff reprint/acceptance
  remains their next action. Refresh Process QR before issuing the new labels.

Active green release remains `20261111_052632`; retained blue rollback is
`20261110_135430`; schema remains `0156_variant_price_workflow`. No merge,
deployment, migration, restart or traffic switch occurred. Private inspection,
backup, rehearsal, application and closing evidence is under ignored
`outputs/bst-8823-cancellation/` in the task worktree; payroll snapshots are not
committed to source control.
