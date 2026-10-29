# Order artwork, Nastil routing and warehouse corrections

29 October 2026. Merged and deployed on green `20261029_083228`; PO-0377's
requested factory correction is applied. Human/operator acceptance remains
separate. Public latency failures were explicitly accepted by the owner, not
relabelled as passing measurements. No 30-minute monitoring was performed.

## Final deployment and correction

- PR344 was fast-forward merged into `clone_main` at exact runtime commit
  `24f4f2310a2194afe9a589796347525e2a7759fa`. This documentation/baseline record
  follows that runtime; it does not change deployed application code.
- Both VMs serve green `20261029_083228`, activated at 09:07 UTC. Source manifest
  `95d3be61132307dc41ec13fff4e51965ad460ab7faa4e5725448db488a13cd59`,
  archive `b7be433f3fa1e07ec36929a4b124bc53673a8dad52f9e28a6153c40c106a40ce`.
  Backend image digest `490a56be19ee998e241023c78b3a4d2764671c4b22ebe1dbea3741d1a9890370`;
  frontend `1cbf8aa2e2fa54bdc2c71515b4557b193eb15f34ffb38529b106f282bec6e57b`.
  Unchanged blue `20261028_123531` retains its exact container IDs, images and start
  times. It was used temporarily to serve traffic while inactive green was replaced.
- Exact immutable CI run 40842869582 passed backend/frontend/release. The backend
  suite passed 4,860 cases with 539 opt-in skips; required PostgreSQL run 40842802962
  independently executed all 165 mandatory cases without skips. Frontend build,
  contracts/browser fixtures, Ruff, strict TypeScript and independent review passed.
- Verified custom-format backup: `milana_erp_pre_20261029_083228.dump`, 96,730,499
  bytes, 1,246 restore objects, SHA256
  `13e14836b0b6eb67f8ca608dc5df3a468d2675e5dcf9e233cc5bb259b721dc6c`.
  Restore-list hash/size and mode 0600 were verified. Schema upgrade was a no-op;
  revision remains `0149_besttex_cutting_access`.
- Actual candidate/public read-only QA passed. Candidate packing-date API values
  matched 47 persisted package rows; connected Chrome displayed original dates.
  Change factory showed Nastil 1 locked and 2/3 selectable. Public post-correction
  Chrome showed six Milana and twelve Besttex bundle rows, with zero console errors.
  Original cutting-print blob-policy refusal remains BLOCKED; no physical-print or
  blanket human acceptance is inferred from these scoped checks.
- The direct paired 120-sample performance gate passed all five endpoints. First
  public closing check failed model-group p95 190.53→232.78 ms (+22.17%). After the
  planned exact temporary-container/proxy cleanup, one independently reviewed
  final-state check failed inventory-stock p95 144.59→185.12 ms (+28.03%); model
  groups then passed. Counts/payloads were identical and medians stayed within
  limits. Host diagnosis did not establish saturation or a root cause. Both false
  gates and raw evidence remain frozen (hashes `154d588203b6c733ce11911c5163296befb03a796105a1307be2ec59658bafbe`
  and `9629c9ee279e0d45ecb827a5b28c2f0d04f71e87cf7120625e94b9887a99f0b4`).
  The human explicitly answered **“Accept latency exception and finish PO-377”**.
  Only this p95 exception was accepted; no further sampling was performed.
- At 09:20 UTC the verified-backup, active actor 14 and pinned production identity
  guarded one correction, audit **151254**. Only batch 255/256's twelve bundles and
  factory/departments changed, with dedicated Sewing/Packaging work orders
  2671/2672 and 2673/2674 (300 pieces each). Shared Milana Sewing remains 600 in,
  600 out; Milana Packaging remains 600 in, 540 out, with plan 600. Storage transfer
  keeps plan 1,200 and output 540. Nastil 1's six bundles/600 pieces stay Milana;
  2/3 each have six bundles/300 pieces at Besttex. No historical Sewing output was
  synthesized. Existing one Sewing record, nine packages, items, stock, order/batch
  quantities and unselected bundles passed protected fingerprints and fresh reads.
  The first quantitative read-only helper used `storage` instead of the actual
  `storage_transfer` operation; that assertion was corrected without reapplying
  the already-committed business change. API scope readback had already passed.
- Immediate closing checks passed after correction and cleanup: both source/slot
  identities, routers, two backend workers, zero restart/OOM/runtime errors,
  database headroom/indexes, revision and all four health endpoints. Temporary QA
  containers/proxy and local isolated QA listeners are stopped. Monitoring was
  explicitly waived and was not performed. The 80% staging gate initially stopped
  image preparation; four exact unused ERP images with verified source archives
  were removed, without touching any containers/volumes or protected blue images.

Evidence is preserved under this worktree's `outputs/deployment/`, including
`evidence.json`, frozen performance files, `po0377-final-readback.json` and
`public-po0377-corrected-context.png`. The data-aware maintenance rollback below
is mandatory after exposure to this release. Production/operator acceptance and
the unresolved latency cause remain open; merge and deployment are complete.

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
  initially active green `20261029_053553`, runtime `186110a5`, manifest
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
handling. These were the pre-release prerequisites; the final guarded application
and readback are recorded above.

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
- Full first backend CI: 4,854 passed, 539 opt-in skips and six query-budget
  failures. The added ownership reads were fixed rather than increasing budgets:
  loss/discriminator reads are combined, exact/generic work-order lookup uses one
  ordered query, and batch presence/ownership are returned together. The unchanged
  1/50/401-size budgets and Nastil/production-flow selection then passed 136 tests.

## Authorized release preparation

The owner explicitly authorized push/merge into clone_main and deployment on top
of current green, preserving blue unchanged, and waived the 30-minute monitoring
window. This overrides only the timed observation requirement. Exact CI, immutable
images, fresh verified backup, no-op schema, candidate/public QA, performance and
immediate runtime/health gates remained required. The pre-deployment live
reconciliation confirmed then-active green 20261029_053553 and blue 20261028_123531
against the recorded manifests; the final green release is recorded above.

Final Besttex handoff prompted a check of the pre-existing raw model-ID fallback
when catalog data is unavailable. The product panel now uses
the authorized work-order model/variant numbers as its fallback, preserving catalog
authorization and preferring catalog information when available. The real component
browser fixture covers both cases. This small display correction required a new
exact-source validation/artifact run, which passed for 24f4f231 as recorded above;
the earlier 63a0e00f artifact was not promoted.

### Data-aware rollback boundary

Blue's old application cannot safely write mixed shared/dedicated Nastil scopes.
The deployment's recovery guard is armed before the new green backend is exposed.
After that boundary, use the reviewed task recovery command
`python outputs/deployment/release.py recover-blue-maintenance` from this preserved
worktree. It retains the original blue images/containers and switches the backend
router into maintenance: only GET/HEAD on health/readiness paths reach blue;
all other application paths/methods receive 503. Frontend returns to original blue.
The explicit command forces maintenance even if an exposure marker is missing.
Health and maintenance refusal are verified before recovery is recorded as passed.
Ordinary ungated blue activation is unsafe after this boundary. Restore normal
business access with compatible reviewed code, or a separately verified inverse
data reconciliation that refuses used/output-bearing scopes. Do not erase or
reassign historical output to make an inverse appear safe.

The guard was tested on an owned ephemeral loopback HAProxy listener with 11
method/path probes; live router/state hashes and original blue identities remained
unchanged. Four local recovery-order/failure tests passed. Initial test failures
(occupied fixed test port, then an incorrect HEAD-readiness expectation) were
diagnosed; no occupied listener was touched and no health behavior was changed.
The recovery guard is now an explicit readiness gate. Timed observation remains
waived; immediate source/health/performance checks remain mandatory.

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
Merge, deployment and the PO correction are complete as recorded above. Human
production/operator acceptance remains separate and pending; release and latency
exception authorization came explicitly from the owner in the deployment chat.
