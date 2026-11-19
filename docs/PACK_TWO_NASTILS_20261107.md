# Selected Nastils: Packaging operation, 7 November 2026

## Direct scope and source

User item 6: “Add an option to pack 2 nastils in once when both out from sewing”.
Coordinator accepted two-or-more explicit Nastil selection using existing saved
Packaging evidence; include normal Eco Cotton production, retain separate Usluga
and grade safety rules. No production data writes or deployment are authorized.

- Engineer/domain owner: Mirshoir. Human reviewer: Ismail. Business acceptance:
  Shavkat/operators. Implementer: Codex subagent `/root/pack_two_nastils`.
- Worktree: `C:\ERP\.codex-work\pack-two-nastils-20261107`.
- Branch: `codex/pack-two-nastils-20261107`.
- Base: `b21b51e6c6112a9c181853b8646944de7416ee8b`, verified
  `origin/clone_main`, explicitly accepted by user after the origin/main mismatch.
- Coordinator verified active release `20261107_043754`, application `3c6ccc82`,
  manifest `43b30accbabc4674a395eaa46eecd2c7f554a2513adc33dc859131355526bddd`.
  This operation does not change active/recovery slots or schema `0155_eco_gate_merge`.
- Skill: repository `.agents/skills/milana-feature/SKILL.md`; existing frontend
  design rules from cleanui and uncodixfy. No shared i18n file writes.

## Old behavior and intended change

The standard Packaging page already had a merge-all-batches checkbox. Its
planner consumed every available Nastil without explicit selection, so staff
could not combine two while leaving a third untouched. It also retained a
legacy fallback to `packed_qty` when `available_to_package` was missing.

The new option shows exact source Nastils and their `available_to_package`
balances. Staff select at least two; empty/unavailable sources are disabled.
Only selected saved output enters full/partial package plans. Copies is disabled
in this mode because it packages all selected available output, preserving the
existing merge behavior. Hold-partial mode retains its existing remainder policy.
Single-Nastil creation remains on its existing path. New copy supports English,
Russian and Uzbek in `frontend/src/lib/multiNastilPackaging.ts`.

Study also found a relevant authorization defect: mixed packages have null
`production_batch_id`, while the three creation APIs authorized only that parent
field and could miss allocation-source factories. The new business service
resolves/authorizes every allocation source before creation. A package can have
only one receiving department. Exact membership/quantity validation stays in
package creation. The browser correction below adds one read-only endpoint;
no new permission, table, migration or state is added.

Packaging output must first be saved per Nastil after Sewing. This UI does not
create output/receipt facts automatically or combine department handoff ledgers.
Usluga keeps its separate customer-owned confirmation path. First/second grade
still reject ambiguous mixed-batch size evidence; no grade bypass is introduced.

## Operation/caller and persistence trace

| Caller/operation | Contract/service | Existing persistence/effect |
| --- | --- | --- |
| `/work-orders/[id]/packaging`, selected sources | `planSelectedNastils`; `PackageIn.batch_allocations` | Pure plan; no writes |
| GET `/packages/sources/{work_order_id}` | `PackageSourcesOut`; `package_sources_service.package_sources`; public `packaged_quantity_balances_by_batch` | Authorize anchor WO, project same-department sibling Nastils from existing saved-output and consumed-allocation ledgers; read only |
| POST `/packages/print-runs/create-packages` | `PrintRunCreatePackagesIn`; `require_package_source_access`; `create_package` with one `PackageWriteContext` | One order lock, per-source remaining budgets, package/item/allocation rows, scan/audit/notification, source stock, print-run/member receipt and request idempotency |
| POST `/packages` and `/packages/bulk` alternate callers | `PackageIn`/`PackageBulkIn`; same source authorization helper; existing creation services | Existing transaction/identity/image/notification/stock behavior retained |
| GET work-order Packaging progress | existing production/workflow service, unchanged | Read Sewing release, Packaging receipts/output, package allocations |
| Label/print-run Warehouse receipt | existing package/print-run services, unchanged | Source quantities printed; exact run receives only its packages |

The new helper is read-only business authorization. Existing creation routes and
root services still contain legacy transaction orchestration/direct ORM writers;
this feature does **not** claim their full schema-owned-write migration. No new
write implementation was introduced, and lock/commit order was not moved.

## Table/field and vocabulary ledger

| Table/fields | Classification and disposition |
| --- | --- |
| `production_batches.id`, `batch_no`, `name`, order link | Configurable identity/business labels, retained. Explicit selected IDs are references, never an enum. Membership remains validated by creation. |
| `work_orders.production_batch_id`, department link, operation | Exact/fallback source routing retained. New helper consumes existing routing; generic operation typing is outside this slice (production owner). |
| `departments.code` for PKG/BPK/ECP | Fixed packaging vocabulary: new helper returns canonical `PackagingDepartment` members; `.value` adapts existing string boundary. No stored vocabulary change. Existing generic normalization helpers remain unchanged debt. |
| `sewing_records.passed_qty`, batch link; `packaging_receipts.quantity` | Existing release evidence, unchanged; no plan-based fallback introduced. Sewing release limits covered by adjacent tests. |
| `packaging_records.packed_qty`, batch/work-order links | Existing saved output budget per source, unchanged. No writes from this new selector. |
| `packages.production_batch_id`, total/capacity/shortfall/status/stock kind | Existing parent projection and package lifecycle retained. Mixed parent null preserves allocation authority; existing PackageStatus/PackageStockKind adoption beyond the new helper remains packaging-owner debt. |
| `package_batch_allocations.package_id`, batch link, quantity | Authoritative per-source consumption, retained without schema changes. Full and partial packs consume only their recorded sources. |
| `package_items` model/color/size/quantity | Existing content contract retained; mixed grades remain blocked where per-size source evidence is absent. |
| `finished_goods_stock`, scans/audit/notifications | Existing downstream writes and ledger behavior retained/tested. No new status/action vocabulary. |
| print runs/members/idempotency | Existing atomic request and immutable membership/evidence retained; no new discriminator. |
| Other production/inventory/fulfillment tables | Outside this operation, pending their named domain owners; no full-domain/type-completion claim. |

## Acceptance and evidence

Primary example in each factory MIL/BST/ECO: source A=35, B=40, unselected C=90,
recipe capacity60. Expected first pack A35+B25; partial pack B15. A total35,
B total40, C consumed0; saved stock total75. Same request key returns the same
run. Further B1 is rejected even while C90 remains. Warehouse receipt retains
the exact two packages and their source allocation quantities.

Refusals cover hidden cross-factory allocations in all three creation APIs,
less than two available selected sources, later-package source overrun with full
transaction rollback, and corrections/retries after rejection. Existing grade
and customer-owned restrictions remain mandatory.

Executed checks (Python `C:/ERP/.venv/Scripts/python.exe`, not the outdated
`backend/.venv`; frontend node_modules is a read-only dependency junction):

- PASS: focused backend feature/Sewing release/evidence/write-context suite,
  **29 tests** after the dedicated-WO browser correction below.
- PASS: existing print-run workflow/first-grade/write-query/allocation-query
  suite, **63 tests**.
- PASS: real loopback PostgreSQL feature race/recovery plus existing package
  write/concurrency suite, **10 tests**, zero skips. Disposable owned container
  `milana-multi-nastil-pg-20261107`, loopback15567, random auto-dropped schemas.
  Two simultaneous attempts for A35+B25 produce one commit and one refusal;
  B15 remains packable; rollback restores both source budgets.
  The source read includes a 200-Nastil bounded projection with eight SELECTs,
  preserving both allocation rows and legacy fallback/shortfall consumption.
- PASS: strict frontend TypeScript and targeted ESLint.
- PASS: actual page-render/submit-closure regression proves selected allocations
  reach the atomic API as60+15; zero/one-source selection sends no request.
- PASS: pure planner integrity across **2,500** varied source-balance scenarios;
  no selected-source overspend or unselected-source borrowing.
- PASS: existing Nastil navigation and package request identity/recovery checks.
- PASS: exact baseline `b21b51e6c` backend source reproduced **three expected
  failures** in the per-source factory-denial regression (each creation API
  incorrectly returned201). Candidate source was restored in `finally`; its
  focused seven-case feature suite passed. Local red evidence is under
  `.codex-work/pack-two-nastils-evidence/baseline-scope-red.txt`.

Early verification setup errors were corrected: old backend venv lacked PyJWT;
one guessed nonexistent Usluga test filename prevented that invocation's
collection; first PG fixture run had a non-unique synthetic department name.
Those attempts are not passes. The final focused commands above ran successfully.
No production business data or credentials were used. Ordinary existing test
deprecation/fixture-secret warnings remain; they do not change test results.

## Browser-discovered dedicated-WO correction

The parent's actual combined browser run found the first candidate unusable for
the supplied dedicated-WO fixture: the unbatched record-entry WO correctly
excluded its sibling Nastils from `/packaging-batch-progress`. The first selector
incorrectly reused that scoped progress read, showing zero sources even though
the atomic creation API accepted both saved outputs. Earlier worker tests did not
prove this actual UI case; the browser result is a real failed gate, not a pass.

The narrow correction adds GET `/packages/sources/{work_order_id}` through a new
Packaging service and typed read DTO. It authorizes the anchor Packaging WO,
resolves exact/fallback packaging ownership, and returns only sibling Nastils in
that receiving department. Balances reuse the same saved Packaging output minus
existing allocation/fallback/shortfall ledgers as package creation. The selector
uses this read, while normal record-entry input/progress retains its original WO
scope. Package/QR/grade mutations refresh both reads. Source errors/loading are
visible; there is no fallback to missing or unrelated progress balances.

Updated API regressions prove normal progress.items remains empty for this
dedicated-WO fixture while source quantities are35/40/90, then0/0/90 after the
same60+15 atomic action and identical-key replay. Other-factory siblings are
filtered; wrong anchor factory and missing package permission are refused.
Existing labels still include both Nastil names. The page submit-closure test
explicitly uses empty scoped progress plus separate source rows, detecting the
original UI dependency mistake. Running that regression against the old page at
979660563 fails as expected; restored new page passes. Local red evidence is
`.codex-work/pack-two-nastils-evidence/dedicated-wo-page-red.txt`.
Final strict types, ESLint and planner checks
pass. Parent owns independent review and repeat actual browser/readback for this
corrected candidate; no worker completion/production acceptance is inferred.

## Remaining gates and handoff

Status: **CODE_TESTED; browser/independent-review gates pending**. Do not mark
AI_VERIFIED_AWAITING_HUMAN from worker tests alone. The coordinator owns combined
source checks, connected-browser visual screenshots, persisted reopen/readback,
independent AI review and completion-email delivery. No push, merge or deployment
occurred in this worker.

Reusable isolated browser fixture:
`app.tests.test_multi_nastil_packaging.seed_nastils(factory="ECO", sessions=qa_sessionmaker)`
returns `(order_id, model_id, [A,B,C])`. Import only after setting the disposable
QA database environment; explicitly supply its Session factory. It assumes the
existing seeded T-SHIRT-001 model and factory departments. Open the unbatched
Packaging WO for this order at `/work-orders/<id>/packaging`; choose A/B, inspect
60+15 output, create, reopen packages/labels and verify A35/B40/C0 in the local DB.

Human checklist: ECT operator can find both Nastils after Sewing and saved
Packaging output; choose exactly two among three; test hold/create remainder,
translations/tablet layout and weights; receive correct run; inspect labels and
reopened source history. Wrong factory and exhausted source must refuse cleanly.

Rollback: source rollback removes the selector/authorization improvement; it does
not reverse packages already created. Their existing allocation/receipt evidence
remains valid. No schema/data rollback or old-path retirement is proposed.
