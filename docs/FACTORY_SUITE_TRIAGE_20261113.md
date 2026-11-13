# Factory full-suite triage — 13 November 2026

Worker /root/packaging. Base6570901bc8628074e985aed38d5bd148c8c223e0.
Isolated worktree C:/ERP/.codex-work/factory-suite-triage-20261113,
branch codex/factory-suite-triage-20261113. Root checkout and production untouched.

The full-suite root backend-final.log markers were mapped against the exact
8,362 collected test nodes, then representative failures reproduced in the
owned derivative milana-factory-qa:20261113 with the approved Packaging PG env.
Evidence logs are ignored outputs/factory-triage/ in this worktree.

## Packaging query budget: intentional behavior change, corrected assertion

All three test_packaging_record_complete_bom_query_growth cases (BOM1/50/401)
failed only27-versus26 SELECTs; the real API save returned201 and the later
assertions still verify one PackagingRecord and exact BOM/stock usage.

Old packaging budgets made3 aggregate reads (Sewing, manual receipts, input) plus
one receipt-existence read. Automatic Sewing availability removes the receipt
aggregate; the existence read is retained for legacy input-counter compatibility.
The complete write now costs one fewer SELECT independently of BOM length.
Only the fixed-count assertion is changed27->26 with this rationale. BOM and
stock read assertions and all quantity/write conservation assertions remain.

Red: all3 parameter cases failed with26!=27 on exactbase6570901bc.
Green: full test_cutting_packaging_write_query_growth.py passed15 tests in the
owned derivative image. No application source changes were needed.

## Other failures: separated owners/environment evidence

- Passport list models/sales chunk-budget test is8/8/13 reads vs prior7/7/12,
  consistent with the one new batched Cutting navigation lookup. Assigned to
  /root/cutting_reports; this worker makes no edit to that test/helper.
-13 ECO migration/concurrency errors are the test fixture's explicit disposable
  database-name guard: original approved root/Packaging env names lack_ci/_qa.
  Root provisioned the owned empty milana_factory_packaging_qa DB. Rerun of
  test_eco_inventory_postgres.py and test_eco_receiving_table_postgres.py using
  the explicit loopback55439 URL passed13 tests. No product or fixture edit.
- JWT resolved-runtime contract fails because the reusable QA derivative inherits
  python-jose3.5.0 and ecdsa0.19.2 alongside the correctPyJWT2.15.0. Current and
  exactba2ac53b source requirements declare onlyPyJWT2.15.0. Root owns derivative
  image cleanup and its rerun; no Dockerfile/image change by this worker.
- Optional-operator PostgreSQL fixture uses customDepartment.code=CUT-<uuid>;
  new unconditional CuttingDepartmentCode cast raisesValueError before saving.
  /root/eco_fabric owns a compatibility adapter for legacy central-only custom
  departments while explicit ECO sources still requirecanonicalECT. No overlap
  edit by this worker; both exact failing nodes were forwarded to that owner.

No full-suite pass is claimed while the root run remains incomplete. Independent
review of this assertion change, final combined reruns, browser readback, human
acceptance and deployment approval remain coordinator-owned gates.

## Legacy flow assertion reconciled with automatic availability

The original root full run's67% failure was
`test_production_flow.py::test_packaging_receives_sewing_work_by_scan_and_manual_entry`.
It deliberately expected18 input to be refused after17 legacy receipts despite20
actual passed Sewing pieces. This conflicts with the owner's requested automatic
availability; the real API correctly returns201 on the candidate. Standalone red
reproduction confirms201-versus-old400.

The renamed compatibility test retains all manual/scan receipt history, duplicate
scan and over-receiving checks. It now refuses21>20 actual output, checks queue20,
saves18 despite17 historical receipts, and verifies queue2, actual input18, exactly2
unchanged historical receipts and zero automatic packages. No application change.
Full test_production_flow.py passes81 tests in the owned derivative image.
