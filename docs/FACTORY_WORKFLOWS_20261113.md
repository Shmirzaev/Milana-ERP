# Factory workflow corrections — 13 November 2026

## Authorization and reconciled source

The owner requested: (1) matching public Order No/new batch numbering; (2)
automatic Sewing-to-Packaging availability, selectable batch and pack-label count;
(3) passport Open to Cutting; (4) correct Cutting dashboard calculations; (5)
uniform invoice package-row heights and 10 pt font; (6) Milana Planning using Eco
Cotton fabric for Eco Cutting; (7) repair Eco passport fabric lookup/consumption.
Plan then implement; wait for separate deployment approval. The owner subsequently
authorized reconciling the baseline with the verified live release.

Fetched clone_main: 3053788f2e17bd5585bccf8cd4547a62cc297516. Both hosts serve
20261111_115200, manifest db9df64cbcf57e4ab93ac83ef677d7d394b07652a1a4cf3fe1815abc92adac28;
both complete live manifest checks passed. All 2,495 manifest files match Git
46ddd5c7864f0a68bd9a3c884d835a2a5dbf9bfb byte-for-byte (LF Git archive).
The already-deployed source and later release metadata on fa9177846 were merged
into this isolated task branch as 479c5bf6. No production mutation occurred.
Recorded rollback remains 20261111_052632 and schema 0156_variant_price_workflow;
protected slot-state access requires sudo and has not been reverified in this task.

## Implementation plan and operation ledger

Lead engineering domain: Production/Packaging (Mirshoir; default reviewer Ismail).
Planning/Inventory/Finance ownership remains Ismail, reviewer Mirshoir. These are
repository ownership assignments, not claims of human participation or approval.
Codex implements isolated disjoint slices and a different agent reviews each
integrated change under AGENTS.md. Human/operator acceptance remains pending.

| Operation | Intended change and acceptance | Source seams | State |
| --- | --- | --- | --- |
| WF01 numbering | New Nastil serial uses public order number, retains unique batch suffix; historical identities/QR remain stable; retry does not duplicate. | production_service, passport_nastil_service, extra-batch route, production/batch_number_service | Implemented; automated PASS, visual/review pending |
| WF02 packaging | Proven Sewing output immediately appears in Packaging without a manual acceptance action. Operator chooses source batch(es) and a bounded number of packs to label; unselected balances stay available. Preserve physical Packaging/warehouse evidence, factory scope, partial packs, retry/concurrency protection. | workflow/batch progress, packaging receipt/source services and Packaging UI | Study |
| WF03 passport navigation | Open resolves the actual authorized Cutting work order rather than whole-order detail, including ECT. | passport output/UI and Cutting route | Study |
| WF04 Cutting dashboard | Trace the main Cutting and passport dashboard calculations, dates/factory/status filters, multi-material/Nastil grain, units and partial output; fix evidenced defects and reconcile independently computed totals. | dashboards and cutting_passport_reports | Study |
| WF05 invoice Excel | Package table font is 10 pt; all package rows share a common height sufficient for the longest wrapped row. Preserve counts, money, sorting, images and existing print settings. | shipment_invoice_excel_service and export tests | Study |
| WF06 Planning ECO | Milana Planning can select valid Eco stock and create an order routed to ECT, without an account/factory bypass. Reject unauthorized/unavailable sources. | production_planning, material selection and Planning UI | Study |
| WF07 ECO fabric | Trace direct and transferred receipts through selection, reservation, passport confirmation and exact physical ledger debit/reversal. Support real eligible ECO fabric; never debit MIL a second time, fabricate stock, or bypass QC/reservations. | ect_passport_fabric and eco inventory/planning services | Study |

New/changed fixed vocabulary must reuse canonical enums; configurable fabric,
factory and order identities remain data. No broad refactor or historical data
repair is authorized. No production business rows may be created for testing.

## Verification and delivery

Each worker records callers, affected fields/DTOs, exact changed paths and tests.
Run defect reproductions and focused backend/frontend regressions first; then
affected full handoffs, real isolated PostgreSQL integrity/concurrency checks,
lint, strict TypeScript, build and applicable required gates. Prepare isolated
fixtures for actual connected-browser visual checks, reopen/readback and bounded
load/retry challenges. Missing required checks remain BLOCKED, never PASS.
Review exact integrated source independently. Record all results here before
handoff. Commit/push only intended task paths after proportional tests; do not
merge clone_main or deploy without the owner's separate authority.

Implementation worktree: C:/ERP/.codex-work/factory-workflows-20261113.
Branch: codex/factory-workflows-20261113. Preserve C:/ERP unchanged.

## WF01 technical evidence

Six defect regressions failed on reconciled source: initial PO/SO/USL/five-digit
numbers, manual extra batch, and later passport Nastil all used the PK rather
than the public reference. The fix uses one pure shared formatter for those three
writers. It reads ProductionOrder.order_no (SalesOrder first when linked), keeps
the familiar numeric suffix plus two-digit Nastil suffix, and never rewrites
existing rows. Nonstandard historical references retain their old creation fallback.
No API/DTO/storage type, permission, QR payload or sequence stream was changed.
The schema-hotfix historical repair and frontend missing-serial fallback remain
unchanged; neither creates new regular orders or overwrites a stored serial.

Windows focused suite: 38 passed. Same focused tests plus the existing PostgreSQL
numbering concurrency check on Linux: 39 passed. Three additional real PostgreSQL
PO/SO/USL commit/reopen/retry cases passed. Reports: outputs/factory-qa/numbering.xml
and numbering-pg.xml. Scoped Ruff and git diff --check passed. Existing test-only
deprecation/short synthetic JWT warnings remain. Browser/independent review pending.

Independent WF01 reviewer /root/packaging reproduced a downstream ambiguity:
separate POs sharing one Sales Order, or PO/USL numeric streams, can now share the
same order-local Nastil serial. The old unscoped traceability lookup selected the
newest matching row silently. Two added plain/BATCH reference regressions failed
with a wrong-order HTTP 200 before the correction; lookup now refuses ambiguous
serials with HTTP 409. Exact BATCH_ID printed QR resolution is preserved. The
numbering/traceability/query-growth suite then passed 32 tests; scoped Ruff passed.
No other active batch creator was missed in the independent source search.
