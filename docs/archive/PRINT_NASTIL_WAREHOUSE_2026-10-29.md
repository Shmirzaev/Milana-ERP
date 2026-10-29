# Order artwork, Nastil routing and warehouse corrections

29 October 2026. Implementation candidate; human acceptance, integration and
deployment are pending. No production business rows have been changed.

## Direct scope and baseline

The owner requested: automatic Printing for a variant with attached print artwork;
that artwork in the BSO workbook and cutting sheet; PO-377 Nastils 2/3 at Besttex
and Nastil 1 at Milana, with individual Nastil selection under Change factory;
package packing dates in Receive by order; another shipment of the remaining
pieces using the same package QR; horizontally expanding invoice sizes.
The owner explicitly selected `clone_main` as the base.

- Worktree: `C:\ERP\.codex-work\print-nastil-shipment-20261029`.
- Branch: `codex/print-nastil-shipment-20261029`; base `425ec9fe`.
- Both production source manifests verified against production-base.json:
  active green `20261029_053553`, runtime `186110a5`, manifest
  `b5ca28076acb7b740073c32a40b0b0bf7eb818c83a4d84ba79cf51233d60b570`.
  Both slot states retain blue `20261028_123531` as rollback.
- Production/Packaging/Fulfillment engineering owner: Mirshoir; reviewer: Ismail.
  Catalog/Sales interface owner: Ismail; reviewer: Mirshoir. Business acceptance:
  Shavkat/operators. These are existing ownership assignments, not recorded human
  approval. Implementation: root Codex; independent verifier: separate Codex
  `independent_review` agent. Neither can sign for the human reviewers.

## Behavior and operation ledger

1. Sales client lines and standard production item creation derive Printing from
   the exact variant's print image. Shared work-order creation also covers an
   order with no size items. Existing manual flags/attachments still work.
   The BSO Pechat cell embeds uploaded artwork and reflects the actual Printing
   stage; the cutting sheet fills its existing Pechat box.
2. Selected Nastils receive dedicated Sewing/Packaging work orders. Other Nastils'
   records, packages and quantities stay attached to their original work. Shared
   input, batch choices, completion, loss credit and later Cutting plan propagation
   exclude dedicated Nastils. Selecting an exhausted shared scope cannot fall
   through into legacy unbatched output. Unowned shared stages are completed;
   subsequent new Nastils can reopen their scope through the existing mechanism.
   Chosen Nastils with recorded output, payroll or packaging evidence are refused.
   Unused selected line assignments are released; scans/history are retained.
3. Receive-by-order returns each pending package's original packed_at, number and
   quantity within the existing bounded page. The expandable table formats the
   date in Asia/Tashkent, with a dash for a missing date, in EN/RU/UZ.
4. Partial dispatch already retained item-level remaining quantities and barcode.
   A reproduced defect left the old sales_order_id on the residual stock, so a
   later shipment returned an error despite available quantity. Partial dispatch
   now releases that link after releasing reservations; historical shipment links
   and frozen invoices preserve original attribution. Overdraw and double scans
   retain their existing guards.
5. HTML and Excel grow the size column according to its content; sizes do not wrap
   or shrink. Other column widths remain physically stable. Wide print documents
   use a wider PDF page instead of clipping size text; ordinary widths stay A4.

New persistence mechanics for routing live in schemas/production/factory_routing.py;
the service owns validation and participates in the existing route transaction.
The action's factory DTO uses canonical SewingFactoryCode; selected IDs are strict,
positive, distinct, bounded integers. Existing manufacturing/workflow status
literals and broader legacy writer boundaries remain explicitly retained debt;
this task does not claim system-wide enum/schema-write migration.
No database columns or migrations were added.

## PO-0377 production correction

Read-only live inspection identified order 416, batch indices 1/2/3 as
253/255/256. Nastil 1 has 600 recorded Sewing pieces and nine packages; Nastils 2/3
each have 300 received pieces but no recorded Sewing output or payroll. Additional
planned Nastils 4–6 exist and must remain unchanged.

`backend/scripts/correct_po0377_nastil_factories.py` defaults to a read-only
preview. After the feature is released, apply requires an existing active super
admin actor plus a verified backup reference. It delegates to the same routing
operation, compares protected order/batch/other-bundle/Sewing/package/item/stock
fingerprints, and commits one audited correction. It never invents historical
sewing output. Its preview and committed apply were tested on isolated fixtures.
The script pins order/batch identities 416/253/255/256 and rejects missing or
duplicate Nastil indices before it can write. There is no CLI identity override.
Do not apply it to the old runtime: that runtime lacks exclusive shared-scope
handling. A release and backup remain prerequisites; no live correction occurred.

## Evidence and limitations

- Initial automatic-artwork checks: 7 passed. Expanded main regression selection:
  186 passed; separate final script/Nastil selection: 12 passed.
- Adjacent receipt/later-Nastil/Packaging/shipment suite: 192 passed, six opt-in
  PostgreSQL cases initially skipped. Separate native PostgreSQL execution then
  passed all 13 selected cases, including those six, later-Nastil receipts and the
  new competing-routing commit/retry test. No required PG skip is called a pass.
  The new routing race is included in the mandatory PostgreSQL CI selection.
- Independent verifier executed 65 targeted tests and isolated loss-attribution
  faults, resolving duplicate plan, ownership-bypass, receipt and loss-credit
  findings. Its last bounded application review had no remaining actionable finding.
- Full frontend production build and its inherited contracts passed using pinned
  Next 16.3.8 and all 98 prerendered routes. Strict TypeScript and Ruff passed.
  Full ESLint: zero errors, 12 inherited warnings. diff --check passed.
- Browser used the actual connected Chrome and the compiled frontend against an
  owned loopback native PostgreSQL cluster, isolated files and test accounts.
  Saved/reloaded Nastils 2/3 as Besttex while 1 remained Milana. Inspected the
  original output lock and selectable sibling checkboxes. A 16-request, concurrency
  2, 10-second-timeout retry exercise conserved nine work orders and output counters.
  The six-size invoice had nowrap, equal span top coordinates and matching
  clientWidth/scrollWidth (no clipping). Packing-date rows were visible; the first
  screenshot exposed insufficient cell spacing, which was corrected and rebuilt.
  Browser screenshot capture was intermittently unavailable and those failures
  are not visual passes. Actual scanner UI shipped 30 of a 60-piece fixture pack,
  scanned the same QR into a second shipment showing 30 remaining, and shipped
  those 30. Database readback confirmed two frozen 30-piece invoices and stock
  available/sold 0/60, preserving original physical contents. The BSO export's
  embedded Pechat artwork was extracted and visually inspected. The normal cutting
  print button generated its preview, but browser policy blocked inspection of
  its blob URL; this is a blocked final visual check, not a pass or bypass.
  Complete role/locale/operator replay stays
  a human acceptance requirement; no blanket AI_VERIFIED status is asserted.
- Local logs, JUnit, fixture and screenshots are under ignored outputs/qa/.
  Initial failed attempts remain in this record: shared dependency-junction
  Turbopack build refusal; a stale dependency link accidentally included in TS
  discovery; test PNG byte comparison corrected to compare normalized pixels;
  an overlong test batch number and C-locale Cyrillic search failure corrected
  with bounded fixture IDs and an ICU-backed test database. No application guard
  or expected business result was weakened to obtain a pass.
- Uploaded print images are embedded. External HTTP(S) artwork remains an existing
  report limitation: arbitrary remote fetching was not introduced. Reports retain
  their existing parent-variant identity for unusual mixed-model PO payloads.
  The owner's ordinary single-variant production path is covered.
- New dependency installation reported three inherited audit findings; no package
  versions or lock files were changed by this task.
- First published CI frontend run failed in the pre-existing factory browser
  fixture: it omitted the now-required batch list and searched for the previous
  button text. The fixture now supplies batches, retains whole-order/rejection/
  fully-locked checks and exercises locked Nastil 1 plus selected 2/3 in EN/RU/UZ.
  Its local browser run passed; application code was unchanged by that repair.
- The next CI run passed that factory test, then exposed a second stale fixture:
  later-Nastil Sewing returned an empty owned-progress list while expecting batch
  choices. It now supplies owned IDs 1/2/3, includes foreign batch 4 in the PO and
  asserts that 4 is absent from choices. Existing assignment/save checks remain.
  Its MIL/BST/ECO × EN/RU/UZ browser run passed without an application change.

## Human checklist before integration/release

Use the identified candidate and isolated QA environment first. Create a standard
order for a variant with uploaded artwork and confirm Printing appears. Open its
BSO export and cutting sheet and check the artwork. In Cutting, leave Nastil 1
with saved output at Milana and change only 2/3 to Besttex; reopen both factories
and check Sewing/Packaging handoff, forbidden cross-factory output and retained
quantities. In Receive by order, expand packages and check their original packing
dates. Ship part of a pack, create another shipment and scan its original QR;
verify the remaining per-size pieces, old invoice and final depletion. Print and
export a six-size invoice and verify a single horizontal size line on the selected
paper/PDF width. Check tablet/phone and EN/RU/UZ labels.

Record Mirshoir/Ismail's technical review and the operator's visual acceptance.
Merge, deployment, PO correction and production acceptance are separate pending
states; no release authorization is inferred from this document.
