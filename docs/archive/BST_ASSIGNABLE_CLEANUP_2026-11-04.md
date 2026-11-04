# BST historical assignable-work cleanup — 4 November 2026

## Owner scope and authoritative baseline

The owner requested removal of all assignable BST sewing works because they had
left the factory. When asked specifically about PO-0377 Nastil 3 (0416-03),
300 received pieces with zero stored Sewing output, the owner answered
**"Sewn and handed over"**. No output count or receipt was fabricated from this
attestation. The owner corrected the branch source to `clone_main` after the
initial stale `origin/main` baseline check. Legacy `C:/ERP` was preserved.

The dedicated worktree is `C:/ERP/.codex-work/bst-assignable-cleanup-20261104`,
branch `codex/bst-assignable-cleanup-20261104`, from `origin/clone_main`
`febe73c69434032737bcca1f5f305aa7702e3ba8`.
The exact applied operational scripts are committed as
`3e5c6868651ed48b8745ec89812a26a74aa1ee68`. This is an operational data correction,
not an application deployment or a production/refactor acceptance claim.

Both live source trees and `clone_main`'s `deploy/production-base.json` matched
release `20261103_094602`, manifest
`ee765f999e782193878390897873c7b5865749460d4d776cf321fcd28490f8a9`,
runtime `11f80a2995daeeb90b5c01318aec9e9c6a40f1c9`, schema
`0150_package_customer_release`. Both complete source manifests verified.
Active blue and compatible green rollback `20261103_112256` remain unchanged;
no deployment, migration, restart, image, configuration or permission change occurred.

## Saved correction

Exactly **14 BST Sewing work orders**, representing **21 genuine BST assignable
batch rows / 8,277 received pieces**, were administratively closed. Only
`status` (`in_progress` to `completed`), `end_time` and `updated_at` changed.
The end time is the correction time, not an invented historical handover time.
No business row was deleted and no SewingRecord or receipt was created.

Affected work-order IDs:
`1069,1499,1507,1527,1579,1603,1607,1611,1615,1715,1839,1843,1847,2673`.
Business order numbers: PO-0248, PO-0345, PO-0347, PO-0352, PO-0365,
PO-0371, PO-0372, PO-0373, PO-0374, PO-0377 (only BST Nastil 3), PO-0399,
PO-0430, PO-0431 and PO-0432.

The initial 22-row / 8,877-piece query result included one foreign-factory row:
Milana work order `1627`, PO-0377 Nastil 1 (`0416-01`), 600 pieces.
It was excluded and its complete row and history remained unchanged.
The deployed BST query still displays that one Milana row because its factory
filter selects production-order IDs before expanding their work orders/batches.
This is tracked as `SEW-BST-ASSIGNABLE-FACTORY-20261104`; clearing it needs a
separate runtime fix and deployment authorization, not a Milana data change.

All existing quantity counters, plans, future Nastils, stock, reservations,
bundles/scans, Sewing records, packages, shipments, payroll and audit history were
preserved. Fourteen standard same-transaction append-only audits
`205870`–`205883` carry the complete affected work-order before/after images,
owner attestation and backup reference. The automation actor is null; no signed-in
operator identity was falsely attributed. The new 14-entry hash segment, including
its predecessor link and recomputed entry hashes, passed verification. Historical
full-chain findings were not retested or declared fixed.

## Backup, execution and verification

- Fresh full custom-format PostgreSQL backup:
  `/opt/milana-erp/shared/backups/milana_erp_pre_bst_assignable_20261104_063301.dump`.
  Size 111,682,320 bytes, mode 0600, 1,251 restore-list objects.
  Dump SHA-256 `245525159e41e76e0a06a3e5308ac9c79bb8cdc8060bf73bece4e405471484b8`;
  restore-list SHA-256 `5390467a4dabec88533f9119c10d3144b43c6da02191a25a6b61a73ed99ab9c9`.
  Backup contents/hash/catalog were revalidated before rehearsal and apply.
- Python compilation passed for both operational scripts. Actual PostgreSQL
  rehearsal changed exactly the allowed fields, then rolled back to the exact
  original fingerprint. A deliberately stale fingerprint was refused before
  writes; independent readback again matched the original state.
- A short NOWAIT table write gate and ordered work-order locks protected the
  exact snapshot/CAS and history checks. Rehearsal held the gate 4.139 seconds;
  committed correction held it 4.386 seconds. Rehearsal consumed 14 audit sequence
  values which rolled back; those harmless gaps are not missing audit records.
- Thirty-five related table snapshots were conserved, including all 60 order
  work orders, 41 planned batches, 132 bundles, 28 Sewing records, 179 packages,
  1,030 finished-goods rows, 51 Packaging records and linked shipment evidence.
  No active line assignment existed for any target.
- Every factory's deployed queue projection after the correction equaled its
  prior projection with only the exact target BST work orders removed. Foreign
  work, including Milana `1627`, was unchanged. A fresh read-only Session verified
  committed statuses, audits and the remaining queue after apply.
- All four internal/public backend health and frontend login checks returned 200.
  Both source/release checks remained unchanged after the correction.
- Independent AI reviewer `/root/review_bst_cleanup` reviewed the exact script,
  source hash, snapshot, backup and rehearsal; no blocker remained. Human domain
  ownership stays Production Mirshoir / reviewer Ismail, business acceptance
  Shavkat/operators; no teammate was impersonated or contacted.
- Connected-browser visual verification was **BLOCKED** by the browser adapter
  failing to bind/claim the existing ERP tab. Do not label this as a visual pass
  or `AI_VERIFIED_AWAITING_HUMAN` runtime feature verification. Queue evidence came
  from the deployed queue helper and PostgreSQL; no signed-in browser/API readback
  is claimed.

The before fingerprint is
`e6d28db5ff8ce514a997100d983b513a4f564795f0d1584364b61db03905a209`;
committed after fingerprint is
`645720008264bf202ba0b9b34b6f3b38944942f56145a756449ef27f226fcc1c`.
Applied correction source SHA-256 is
`84185d3ae81fb407fd26e76666589b4cfb39545fed1a109bcd04ba4d44163d27`.
Private snapshots and machine-readable evidence remain in ignored
`outputs/bst-assignable-20261104/` in the dedicated worktree.

## Preserved limitations and operator readback

The normal complete action refuses unfinished ledger quantities/planned Nastils.
This expressly owner-confirmed historical status correction does not rewrite that
guard or conceal the discrepancies in stored counts. PO-0377 Nastil 3 still has
zero recorded output; no new Packaging allowance or Finished Goods was minted.
Later genuine receipt/evidence actions can legitimately reopen a work order
through the existing reconciliation service.

Extra positive-plan Nastils under a closed shared work order may become visible
in the Process QR selector with zero sewn output. The normal UI allocates zero
labels for them. The pre-existing privileged issue endpoint's missing sewn-budget
guard is an inherited risk, not fixed or introduced by this correction.

Operator check: refresh Besttex Sewing Flows and expand a line. The 21 genuine
BST rows should be absent; the only remaining wrongly included row is Milana
PO-0377 Nastil 1. Reopen BST PO-0377 Nastil 3 and verify its existing counts remain
zero and history remains accessible. Do not record another 300 pieces merely to
match the owner's historical attestation.
