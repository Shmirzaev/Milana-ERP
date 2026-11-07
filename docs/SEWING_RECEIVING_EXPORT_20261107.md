# Daily sewing Excel and manual line receipt — 7 November 2026

Status: AUTOMATED_CANDIDATE; actual connected-browser verification and independent
AI review are pending the parent integrator. This is not human acceptance.

## Direct scope and baseline

The owner requested (4) that the selected Top/Bottom garment part appear in the
daily sewing Excel, and (5) a sewing line choice during manual bundle receipt.
The owner clarified: **Allow both: choose a line or leave unassigned.**
No source merge, push, deployment or production business mutation is authorized
by this packet. The parent owns the combined UI screenshots and completion email.

Parent verified both live hosts on release `20261107_043754`; user approved verified
`origin/clone_main` despite stale `origin/main`. Worker base is `b21b51e6c`, worktree
`C:\ERP\.codex-work\sewing-receiving-export-20261107`, branch
`codex/sewing-receiving-export-20261107`. Writer: Codex subagent
`/root/sewing_receiving_export`; independent AI reviewer: parent integrator.
Production engineer: Mirshoir; human reviewer: Ismail. Reporting/payroll owner
Dilmurod and reviewer Mirshoir remain relevant for report interpretation.
Shavkat/operators retain business acceptance; none is claimed here.

## Changed behavior

The workbook retains the original five columns in order, then adds localized
Garment part, Top qty and Bottom qty. Top-only and Bottom-only saved splits display
that exact part. Both positive quantities display both parts. Absent legacy splits
remain blank quantity cells with '-' part instead of guessing from the model.
Each saved entry remains one row; the existing Sewn qty column is unchanged and
continues to hold top+bottom when the existing two-part model uses piece totals.
No save, stock, Sewing output, payroll or PDF calculation changes.

The manual receipt table adds an optional line selector per Nastil. Its default
keeps the current assignment, or receives unassigned if none exists. Choosing an
active line atomically uses the same acceptance operation as the batch QR. The
complete locked Nastil must be ready; line/factory access, accessories, existing
line conflicts and assignment quantity rules remain enforced. Replays create no
duplicate receipt/assignment. They retain the existing acceptance audit behavior
(one accepted-action entry per request, including zero-receipt replays).
Manual selected-line receipts retain per-bundle manual audit entries and record
`accept_sewing_batch_manual`; QR keeps its existing action/note.

Legacy bundles whose explicit `production_batch_id` is null remain receipt-only;
the selector explains this limitation in EN/RU/UZ. Assigning such historical
order-wide bundles would require choosing a different assignment scope, outside
this batch-acceptance reuse. An explicit API line with null batch fails before any
write. A model-filtered manual request cannot widen to another historical model.
Existing split/multiple-line work cannot be reassigned implicitly by this action.

## Operation/caller and persistence map

| Entry/caller | Service/contract | Reads and writes |
| --- | --- | --- |
| `BundleScanPanel.manualReceive` -> POST `/bundles/manual-receive-sewing` | `SewingManualReceiveIn`; `receive_manual_sewing` | Existing selected batch/model/factory scope; optional positive configurable line ID |
| Existing batch QR -> POST `/bundles/sewing-batches/{id}/accept` | `accept_sewing_batch` -> `SewingBatchAcceptance` | Same batch -> bundle -> assignment lock order and original validation sequence |
| Either line acceptance | schema `create_receipt_assignment`, `resize_receipt_assignment`, `start_receipt_assignment` | `sewing_assignments` insert/quantity/status/start; `work_orders.sewing_flow_id` only if empty |
| Shared receipt helpers | `receive_many_at_sewing` / `receive_at_sewing` | Bundle status/departments, BundleScanLog, WorkOrder actual input/progress, ProductionOrder status; original audit/progress transaction retained |
| Shared progress/audit | existing public `reconcile_sewing_order`, `log_action` | Same supplied Session; outer receipt service commits once |
| GET daily report export | `build_sewing_daily_report_xlsx` | Reads saved `top_qty`/`bottom_qty`; workbook bytes only |

No new table/column/index/migration or business permission. HTTP binding and
permission dependency remain in routes. The legacy batch-output projection remains
in `bundles.py`; this feature does not extract unrelated label/list logic. Shared
receipt/progress/audit mapped writers are retained migration debt, not claimed
schema-boundary completion. New assignment writes are schema-owned.

## Field/type ledger

| Table/contract field | Classification and disposition |
| --- | --- |
| `sewing_daily_reports.top_qty`, `bottom_qty`, `sewn_qty` | Existing optional/nonnegative integer saved quantities; unchanged. Report derives a localized display label without persisting a new discriminator. |
| `SewingManualReceiveIn.production_batch_id` | Configurable FK; required, explicit-null historical meaning retained. |
| `SewingManualReceiveIn.sewing_flow_id` | New optional positive configurable FK; not an enum or permission. |
| `SewingManualReceiveIn.factory_code` | Canonical `SewingFactoryCode` enum with prior trim/uppercase/empty-to-default normalization. Invalid vocabulary now fails DTO validation with 422 rather than legacy service 400; legal serialized values unchanged. |
| `SewingAssignment.status`, WorkOrder/Bundle states and operation, department codes | Existing fixed vocabulary and action subsets retained verbatim during bounded operation extraction. No canonical assignment enum exists at this base; broader table-by-table production adoption and actual stored-value census remain unresolved, not claimed complete. |
| Assignment note and audit action | Source note identifies manual/QR; audit action is the existing open action namespace with one new manual-batch action. No user-controlled status/action. |
| Line/model/order names and IDs | Configurable references/text; no enum conversion. |
| `SewingBatchAcceptance` / `SewingManualReceiveResult` | Used dataclass and precise TypedDict beside their single production feature; route maps/returns their fields to existing public response without a parallel DTO hierarchy. |

## Automated evidence and validity

- Original b21 route fails selected-line regression: receipt succeeded without a
  `sewing_assignment_id` or assignment. Candidate proves persisted assignment and
  retry/readback. Original five-column Excel fails all four Top/Bottom/both/legacy
  regression shapes; fixed candidate reads saved fields, preserving totals.
- Focused suites include daily reports, later Nastil MIL/BST/ECO handoff, band
  authorization, sewing workspace permissions and Production flow. Exact final
  counts are recorded in the worker handoff after the last run.
- Isolated PostgreSQL uses owned container `milana-sewing-receipt-pg-20261107`,
  loopback port 15568 and randomly isolated fixture schemas. The owned container was
  stopped after the passing PostgreSQL run; no other local service was touched. It covers no-line
  receipt plus printing loss, selected-line receipt for all three factories,
  work-order lock refusal/recovery, sibling evidence, Sewing -> Packaging,
  two concurrent selected receipts, and 12 replay requests per selected case.
- Frontend strict TypeScript, scoped ESLint, actual scanner-handler execution,
  factory access (54 cases) and factory daily report contracts are required.
  Handler regression checks selected batch IDs `[89,95,null]` and line values
  `[7,null,null]`, exercising the actual source function.
- Existing test-only short JWT and deprecated TestClient/Pydantic namespace warnings
  remain inherited; no real credentials are used.

## Browser and human checklist

Parent owns the actual connected-browser gate on the combined candidate. Use
`backend/app/tests/sewing_receipt_browser_fixture.py` via `runpy.run_path` and an
authenticated loopback httpx client; do not import pytest conftest into a QA server.
It seeds one waiting 128-piece Nastil/four bundles, two lines and saved Top24/Bottom16
reports and returns IDs/routes/expectations. Call again for an unassigned-receipt
example. All synthetic writes are isolated local fixtures; no production QA rows.

1. In `/bundles/scan/sewing?factory=MIL`, search returned order, choose a line,
   receive; reopen line context and confirm one 128-piece assignment and four
   receipt logs. Test second record with default unassigned and with planned line.
2. Verify inaccessible/inactive/other-factory line, conflicting existing line and
   missing accessories cannot partially receive or assign.
3. Export chosen daily date: Top24 and Bottom16 each appear once with exact part,
   numeric split and unchanged Sewn qty; inspect EN/RU/UZ, narrow viewport and no-batch
   explanation. Existing report editing/PDF remain operational.
4. QA master and named human owners record acceptance before any separately
   authorized deployment. Until parent visual/independent gates pass, do not mark
   AI_VERIFIED_AWAITING_HUMAN. No deployment happened in this worker.
