# BSO, fabric receipts and model operation copying

Requested 9 November 2026:
1. Add the cutting factory name to the BSO page and BSO Excel.
2. Add received amount to fabric inventory.
3. Offer copying all paid operations from one model to another.

Owner correction: "It shouldn’t stay cutting it should say Milana or Eco Cotton fix and deploy fast".
The BSO table and appended Excel factory column now use the existing CUT→Milana,
ECT→Eco Cotton mapping. Department API names, routing and business data remain unchanged;
unknown destinations retain their stored name. This follow-up authorizes deploying
the corrected candidate after technical gates and overrides the separately disclosed
pending human QA-master record. No human QA approval is claimed. The owner's earlier
30-minute monitoring waiver remains in force. Old staged build `20261109_111519`
was not activated; its label-dependent acceptance does not establish this candidate's gates.

The user explicitly approved verified `clone_main` as the worktree base after
the supplied origin/main rule conflicted with the live production baseline.
Base: `14f6670de874f66eba3112281ab5a8dd4f388280`.
Worktree: `C:\ERP\.codex-work\bso-fabric-paid-copy-20261109`.
Branch: `codex/bso-fabric-paid-copy-20261109`.
Implementation: coordinating Codex. Domain owner Ismail, named human reviewer
Mirshoir, operator acceptance Shavkat; no human approval is implied.

Both production manifests verified as release `20261109_035740`, SHA-256
`e5d56b822d8a48d327429a5e6a59cd87111b81bb193a2fd8cf120d007a7fafb1`.
Slot-state access was refused to the SSH actor; no production writes occurred.

## Current release status — 10 November 2026

**Deployed and closing complete.** Both hosts serve green `20261109_163130`, app
`271c5005e12d1efc65d6358756862d8c243685a5`; compatible blue `20261109_035740` is
retained for rollback. PR553 is merged on owner-approved `clone_main`.
Public Edge verified Milana/Eco Cotton in BSO0083 and downloaded Excel, received
576.80 kg separately from remaining196.80 kg, and source-model copying111 draft
operations across three factories. Full reload restored original126; no live Save.

CI passed 6,651 backend tests / 1,568 skips / 36 subtests and all five jobs. Complete
protected workflow, full current A/B ordered facts/receipt and actual signed UI
checks passed. Original failed paired medians and three failed public p95 metrics
remain false, with both exact exceptions explicitly approved by the owner.
A settled public check had zero ERP console errors/warnings and two separately
classified external extension errors retained in raw evidence. Initial failed
console/cancellation evidence remains preserved; global console cleanliness and
human acceptance are not claimed.

Fresh final closing passed all four health checks and source/runtime/database/
rollback guards. No migration or deployment business write occurred. Monitoring
was waived; owned leases, preview processes and tabs are cleaned up. Full identities,
backup, evidence hashes and limitations are in the [release record](archive/BSO_FABRIC_PAID_COPY_RELEASE_2026-11-10.md).
The [9 November candidate record](archive/BSO_FABRIC_PAID_COPY_CANDIDATE_2026-11-09.md)
remains historical evidence of the earlier stopped attempt.

## Operations and acceptance

- BSO read/export: planning routes -> branded_orders_service / existing workbook
  builder -> BrandedPlanningOrder, ProductionOrder, WorkOrder, Department ->
  BrandedOrderHistory. Show every active cutting destination's business name;
  omit cancelled/rejected cutting routes. Preserve existing workbook columns and
  formula-injection protection. Existing permissions remain authoritative.
- Fabric inventory read: inventory batches -> stock_service.list_batches ->
  StockBatch / StockMovement -> inventory desktop and mobile. Received amount is
  implemented as original receipt quantity, distinct from remaining quantity;
  never manufacture a receipt from the current balance. No stock writes or
  schema migration. The release displays received quantity rather than monetary value.
- Paid-operation copy: use the model editor's existing authorized read/save
  operations, retain target details, rates, factories and metadata, and leave the
  source untouched. Copy into a reviewable unsaved draft; saving updates only
  the selected target model through existing scoping/validation. This does not
  use the separate family-wide paid-operation endpoint. Empty/self/failed reads must not clear the
  target draft. Standard and Usluga catalog namespaces remain separate.

## Type and storage ledger

Department names/codes and model IDs are configurable records, not new enums.
Quantities retain existing numeric units. Existing paid-operation factory,
section and selection vocabularies stay canonical; no new state or permission.
Unrelated table/type adoption remains outside this feature.

## Evidence

Historical initial-check status: implementation was technically checked while
visual/console limitations and human acceptance remained open. The current staged
status and owner deployment authorization are recorded above; timing acceptance is pending.

- Backend focused run: 31 passed (receipt projection, BSO cutting progress/export,
  employee exports, automatic printing, paid-operation family and factory scope).
- Wider inventory master-data/groups: 36 passed. The active batch response now
  intentionally includes nullable `received_quantity`; the existing shape check
  was updated explicitly. Archive receipt/return/adjustment semantics are unchanged.
- Real PostgreSQL 17: 4 passed, no skips. New receipt precision/paging test executes
  in a READ ONLY transaction; existing paid-operation concurrent factory saves,
  audit rollback and scope checks pass on the exact mounted candidate sources.
  The dedicated network-isolated Docker instance has no published ports; fixtures
  verify its identity, create their exact owned databases and clean those databases.
  Initial fixture runs failed on guessed Warehouse constructor keywords; corrected
  to the actual `type` field before the final passing run. No application fix was
  hidden in the fixture correction.
- Receipt bounded checks: 12 identical repeat reads and a 24-batch single-aggregate
  query assertion pass; returns/adjustments/usage and incompatible units are tested.
  Missing receipt evidence displays a dash rather than inventing an initial balance.
- Copy frontend harness: 5 passed, including all factories, deselected rows, rates,
  provenance, deep-copy independence, target details, empty/malformed input, self
  refusal, failed reads/retry, duplicate clicks, unmount and catalog namespaces.
  Existing model BOM feedback (4), cutting-factory UI (12) and archive checks pass.
- Full frontend production build and all of its contract prerequisites pass;
  full ESLint has no errors (pre-existing warnings remain); strict TypeScript,
  scoped Ruff, Python compilation and diff whitespace checks pass. The two new
  harness unused-variable warnings were removed. Build/dev-generated AGENTS and
  next-env changes were excluded from the feature patch.
- Independent Codex reviewer `/root/feature_review` reviewed runtime and final
  test deltas, independently ran the five copy tests, and found no new blocker.
  Human reviewer Mirshoir has not approved the feature.

## Actual Edge candidate checks

The user explicitly chose Edge. Loopback frontend `13109` and backend `18109`
serve synthetic fixtures created by `scripts/qa_bso_fabric_copy_20261109.py`.
No production business rows or credentials are used.

- Normal sign-in, expanded BSO factory column and both Cutting/Eco Cotton Cutting
  names passed visual inspection. Edge downloaded `BSO-QA.xlsx`; independent
  openpyxl readback proves column T/header, both destination names, A1:T1 title
  and literal-text formula protection. Browser download-event waiting timed out,
  but the actual downloaded file was found and checked successfully.
- Desktop fabric view visually shows 100.00 kg received / 60.00 kg remaining.
  Phone-sized 390x844 layout shows the same quantities through the actual DOM.
  Mobile screenshot capture timed out: mobile visual screenshot gate is BLOCKED,
  not a screenshot pass. The temporary viewport was reset.
- Source QA9001 -> target QA9002 copied all three factories. Save, full reload and
  reopening Paid Operations retained all three rows/rates. Persisted database
  readback confirms target details retained, source definitions unchanged and
  stock still 60 kg. Self-copy is disabled; copying an empty source displays its
  refusal and retains all three target rows.
- Screenshots inspected/stored in ignored `.qa-bso-fabric-copy/`: BSO factories,
  desktop fabric receipt and saved target operations. Full-page screenshot capture
  also timed out; the normal saved-target screenshot was retained.
- Console is not clean: hydration warnings identify extension-injected
  `bis_skin_checked`, `bis_register` and `__processed_*` attributes, including the
  unchanged root layout. This browser-environment limitation is recorded, not
  suppressed or represented as zero errors. No unrelated runtime fix was made.

Initial production-mode local preview launches were rejected by automatic approval
review with the generic reason `blocked by policy`; the safer loopback development
server launch succeeded. Chrome control failed, and the first in-app browser
session disappeared. Edge was then used as explicitly requested.

At that initial local check, missing mobile screenshot and console gates prevented
a release-ready claim. Those gates later passed on the staged immutable candidate;
its separate performance exceptions were subsequently explicitly approved. See the
current release status above for the completed production cutover.

Human checklist: compare BSO factory names and downloaded Excel; compare fabric
receipt quantity with remaining stock on desktop/mobile; copy a model's complete
paid operations, review, save and reopen, checking target details and source.
