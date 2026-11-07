# Separate migration approval: ECO and turnstile history

Status: PROPOSED, NOT APPROVED. No migration file or production schema was
changed by the application reconciliation. Owner explicitly reserved migration
changes and execution for separate approval.

This future full-branch package is not required for the requested narrow feature
runtime. That candidate starts from exact deployed ECO984 and retains0154 with
zero migration-file changes. Undeployed turnstile work is preserved in the source
integration candidate and excluded from that narrow runtime.

## Existing histories to preserve

Verified deployed source 984aeffb has this history:

    0149_besttex_cutting_access
      -> 0150_eco_inventory_transfers -> 0151_eco_accessory_approval --+
      -> 0150_package_customer_release -----------------------------+
         -> 0154_eco_receipt_details (production's recorded head)

clone_main 61cd16bd9 separately contains:

    0149_besttex_cutting_access -> 0150_package_customer_release
      -> 0151_gate_enrollment -> 0152_gate_edit_baseline
      -> 0153_gate_revoke_tombstone

Numeric prefixes repeat but full revision identities differ; do not rename them.
The deployed ECO 0154 merge covers the package and ECO accessory branches, not
the turnstile branch. Combining the existing six files without a new merge leaves
two heads. The production startup verifier requires the exact source head(s),
and CI requires a single head. Do not weaken either check or stamp the database.

## Recommended separately reviewable package

1. Copy the three released ECO migration files byte-for-byte from 984aeffb into
   a separate migration commit/PR: 0150_eco_inventory_transfers.py,
   0151_eco_accessory_approval.py and 0154_eco_receipt_details.py.
2. Retain all existing turnstile migrations unchanged. Add one empty merge
   revision (proposed name 0155_eco_gate_merge, subject to a fresh collision check)
   whose down_revision is (0154_eco_receipt_details,
   0153_gate_revoke_tombstone). No data-copy or data-correction statements.

   Proposed new file body (not installed or executed):

   ```python
   """Join deployed ECO and preserved turnstile migration histories."""
   revision = "0155_eco_gate_merge"
   down_revision = ("0154_eco_receipt_details", "0153_gate_revoke_tombstone")
   branch_labels = None
   depends_on = None

   def upgrade():
       pass

   def downgrade():
       pass
   ```

3. Add graph and PostgreSQL upgrade/rollback-compatibility tests in that package.
   Recheck fresh install and upgrades from the exact deployed ECO head and the
   existing turnstile head; preserve business-table identities and balances.
4. Only after separate owner approval and successful isolated checks, build the
   exact combined immutable candidate and a compatible previous-application
   rollback. Verify actual default-command cold start, two workers, worker
   replacement/restart, strict security/head and disabled startup seeding.
5. Back up production before a separately authorized migration/cutover. Keep
   current traffic on the existing release until all candidate gates pass.

## What upgrading current production would actually do

The ECO history is already recorded at 0154: Alembic should not replay its seven
ledger/approval tables or the receipt-details columns. Upgrade to the proposed
merge must instead apply the not-yet-deployed turnstile 0151/0152/0153 branch:

- Create gate_photo_assets, gate_employee_devices, gate_operations, gate_targets,
  gate_simulator_devices and gate_simulator_people.
- Add the employee and attendance-device (id, factory_code) unique constraints.
- Permit nullable operation photos for edit/revoke, add seven edit-baseline
  fields and their consistency constraint to gate_targets, and add the simulator
  person's present/tombstone field.
- Advance migration bookkeeping to the new merge head. No real hardware command,
  enrollment, employee creation, payroll update or stock change is intended.

These are real database changes despite the new merge revision itself being
empty. They are not authorized by the application-only approval. Existing strict
0154 images cannot be assumed restart-compatible with a new head; metadata-only
compatibility images must be independently verified before promotion. Retain
backups and all new evidence; rollback never downgrades, stamps or drops data.

## Alternative if turnstile schema is deferred

Keep the combined source candidate undeployed. Prepare a separate narrow runtime
candidate from the exact verified deployed ECO source with only the requested
Planning/picture fixes; it would retain the original 0154 migration tree and avoid
turnstile schema changes. This does not deploy all clone_main application work.
It requires an explicitly agreed release scope and exact-source validation.

## Independent approval checkpoints

- Approval A: create/test the separate migration package (no production changes).
- Approval B: apply that verified package to production and deploy the exact
  combined application with the verified compatible rollback.
- The timed 30-minute observation remains waived. Required backups, immediate
  health, candidate/readback and performance gates remain in force.

Independent read-only review by Codex /root/floor_pictures confirmed the source
graph, schema effects, startup verifier and rollback caveat. A separate AST-only
analysis found152 unique revisions in the union and exactly two existing heads,
0153_gate_revoke_tombstone and0154_eco_receipt_details. No imports, DDL or migration
execution were used for that analysis. This is proposal verification, not an
approved/tested migration package or production migration acceptance.
