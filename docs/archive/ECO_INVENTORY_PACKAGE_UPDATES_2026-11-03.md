# ECO inventory and package visibility: local-review candidate

## Scope and authority

User requests all five changes: complete Cutting Passport Excel export; explicit
legacy package model/variant identity; sewing-factory package filtering and
Warehouse Inventory column; separate ECO fabric/accessory stock; two-sided fabric
dispatch/receipt with an Excel driver document; accessory requirements, approval
after BSO creation and before sewing, allocation and stock-backed issuing.

On 3 November the user explicitly authorized a separate PR into `clone_main`
and local review before any production release. No merge or deployment is authorized.
Base: `77d090f69c293f716adf9e2df6227d9543552442`. Dedicated worktree:
`C:\ERP\.codex-work\eco-inventory-package-updates-20261103`, branch
`codex/eco-inventory-package-updates-20261103`.

Implementation: Codex coordinating agent and isolated package/material workers.
Human domain ownership remains Ismail/Mirshoir for Inventory and
Mirshoir/Ismail for Production, Packaging and Fulfillment; their review has not
been supplied. Independent AI review and Shavkat's local business acceptance are
separate gates. Shared router/navigation/context changes have one writer, the
coordinating agent. No team messages or review approvals are fabricated.

## Baseline and preservation

The legacy checkout has 167 modified tracked paths; preserve them in place.
`origin/main` is stale. `clone_main` records green `20261102_063110`, runtime
`42078704df340558c8a21bf1ef14bf74cc87b222`, schema `0149_besttex_cutting_access`,
with blue `20261031_092951` retained. These are recorded assertions, not fresh
live checks: SSH key authentication was refused. Local-only development was
explicitly authorized following disclosure of this baseline discrepancy.

Existing passport export already has summary and material sheets, filtering and
EN/RU/UZ headers; verify it before making changes. Existing ECO dispatch/return
register is a custody ledger, explicitly without ECO receipts. Preserve it and
introduce the requested inventory transfer separately. Usluga customer-supplied
fabric remains outside factory-owned stock.

## Intended acceptance examples

- Export the authorized filtered passports with all material rows and numeric
  quantities; original output is not multiplied by dashboard-only rules.
- Scan a legacy package: show model and variant numbers using trustworthy
  catalog/import evidence, with unavailable values explicit rather than invented.
- Filter packages by actual sewing evidence; preserve mixed/unknown provenance.
- Dispatch available Milana fabric: remove available source stock, retain an
  in-transit record and Excel document. ECO receives only confirmed quantities;
  repeated requests cannot create duplicate stock. Preserve batch identity,
  units, source/receipt references, actor and history.
- ECO receiving/consumption/history cannot read or mutate Milana balances.
- Requirements attach to an ECO production order/model with an existing BSO.
  Approval allocates stock, issue deducts stock, and unapproved requirements
  cannot pass the applicable sewing handoff. Existing sewn work is not replayed.

## Evidence ledger

Status: LOCAL_REVIEW_CANDIDATE, **not AI_VERIFIED**. PR375 remains a draft. There
is no merge/deployment authorization. Production access, migrations and business
data changes: none. Only disposable local/test fixtures were written.

| Check | Evidence / limit |
| --- | --- |
| Passport Excel | Existing summary/material workbook, filtered export, factory scope and literal formula-safe values covered by regressions; no duplicate button/API was added. |
| Package identity/origin | Literal receipt identities, missing/partial legacy identities, mixed exact-batch sewing evidence and bounded query-count tests pass. Origin filter precedes pagination. |
| ECO transfers/stock | 19 focused regressions pass for dispatch, partial receipt, retries, conservation, reservations/custody/Usluga refusals, factory/permission and bounded stock queries. |
| Accessory requirements/approval/issue | Approval reserves; partial issue deducts stock/reservation atomically. Reapproval keeps issued evidence, foreign/overissue/stale/closed-order requests refuse, unrelated manual blocks remain. Mixed-factory and historical handoffs have explicit regressions. |
| Schema | Single Alembic head `0151_eco_accessory_approval`. Both upgrades run against a disposable SQLite predecessor and match mapped columns; empty downgrade works, evidence-bearing downgrade refuses. No production schema was accessed. |
| Interruption/recovery | Injected failure on the second allocated batch rolls back the first write; same-key recovery plus 50 repeated replays produce exactly two original batch movements. Browser pending keys survive authentication failures and page reload. This is bounded sequential recovery, not PostgreSQL contention proof. |
| Frontend | Optimized build and all inherited build contracts pass; strict TypeScript and full lint pass (12 inherited warnings, no errors). New decimal/retry/translation behavioral checks pass. |
| Broad backend regression | Initial full run: 5,220 passed, 731 skipped, nine failed. Three failures were the fixed-cost factory query budget (now 42 at 1/50/401 bundles); six were ECO sewing fixtures using the former Milana accessory path. The fixtures now receive, approve and issue their actual BOM requirements through ECO APIs. Final affected runs: 114 focused/query-growth tests plus 24 sewing/nastil tests passed; Ruff and diff whitespace checks pass. A second complete local suite has not been claimed. |
| Connected local browser | Actual Chrome: dispatch/in-transit detail; ECO accessory save → submit → approve → issue → reopen; stock 1,000 → 880 after 120 issued; partial delivery 25 sent / 10 received / 15 outstanding → browser confirms remaining 15 → 25 received / 0 outstanding. Console warnings/errors: zero on inspected new screens. Driver Excel downloaded/parsed through the local API. Browser download-event automation timed out, so a browser download completion is not claimed. |
| PostgreSQL | The explicit ECO migration/concurrent-dispatch/concurrent-receipt CI step passed on `bda4998796a2d5b3fb7b2bff35052749f80a6530`, using job-owned PostgreSQL 16 in [run 41618041965](https://github.com/Shmirzaev/Milana-ERP/actions/runs/41618041965). All three cases are selected in that step. Locally they remain skipped because Docker Linux/PostgreSQL is unavailable. This proves the bounded transfer cases; it does not claim all database or full department acceptance gates passed. |
| CI browser limit | The previous candidate's frontend job failed in the unchanged HR employee browser harness: esbuild cannot import `TurnstileAccessPreview.module.css` without an output path. Its script/component have no diff from `clone_main`. The affected package/warehouse/passport browser fixtures passed before this failure; the local optimized build also passes. No all-green CI claim is made. |
| Human / full browser acceptance | Pending. Scoped browser checks above are not complete role/scanner/tablet/translation acceptance. |

Independent review: `/root/review_packages` reviewed package projections and the
accessory operation; `/root/package_identity_factory` independently reviewed the
other worker's inventory/transfers. Corrections cover synthetic legacy numbers,
source paging, N+1 item reads, retry keys after 401/403, ECO block clearing,
factory-specific proofs/block writes, ECO-only historical exemption, and
preservation/release of issued and outstanding allocations. The accessory scope
re-review at `c025cd6b` independently reran five regression cases successfully.
This is AI code review, not named human engineer/operator approval.

New fixed vocabularies must use canonical enums; stock units, names and model
identities remain data. New ORM writes belong in schema persistence operations,
business rules/transaction ownership in services and HTTP binding in routes.

## Table/type and compatibility inventory

- `eco_material_batches.kind`, `eco_material_movements.kind`, transfer status and
  approval status use the feature's canonical enums and typed DTOs; mapped string
  storage remains explicit. Quantities use Decimal / Numeric(14,4), constrained
  positive requests and nonnegative balances/reservations.
- Four stock/transfer tables and three requirement/allocation tables are additive.
  Existing table shapes and historical Milana custody records are unchanged.
- Item/model/BSO/order IDs reference configurable existing records. Units, names,
  colors and notes remain data. Existing manufacturing vocabularies and legacy
  schema-writing debt are intentionally retained outside the narrow new seam.
- ECO stock is not automatically copied from Milana, historical custody, or
  customer-supplied Usluga fabric. Existing cutting stock writers are not silently
  redirected to the ECO ledger. ECO fabric consumption is explicitly recorded
  in its stock screen and may link to an assigned factory production order.
- Accessory approval is required for ECO-routed BSO orders before ECO handoff.
  Existing ECO handoff/output with no new plan retains the previous gate. MIL
  history cannot grant this exemption; non-BSO Usluga retains its existing path.
  Changed pre-ECO-sewing plans require explicit amendment/reapproval; issued
  quantities cannot be reduced or deleted, and only outstanding stock is freed.

## Local review

The local preview is `http://127.0.0.1:13085`. It uses
its own `erp_eco_review` cookie and persistent local SQLite database; no production
credentials or data are needed. Local screenshots/driver workbook, when created,
are under ignored `outputs/eco-review/`.

To start the local workspace, use two terminals in this worktree:

```powershell
# Terminal 1: backend (uses the installed repository test environment)
C:\ERP\.venv\Scripts\python.exe scripts/local_eco_review.py
```

```powershell
# Terminal 2: frontend
cd frontend
$env:API_URL = 'http://127.0.0.1:18085'
npm ci --legacy-peer-deps
npm run dev -- --hostname 127.0.0.1 --port 13085
```

Use the existing disposable demo-admin fixture credentials in
`backend/app/tests/conftest.py`, selecting Milana or Eco Cotton on the login page.
They are test fixtures, not production accounts. Stop an existing preview before
reusing its ports. Entered records now survive restarts in ignored
`outputs/eco-review/local-review.sqlite`. Existing local review records were
copied into that workspace; original temporary files were preserved. The local
runner creates initial fixture data only when no workspace exists. Its bounded
SQLite column initialization is for local review; real installations use Alembic.

1. Milana → Cutting Passports: export the filtered local passport and inspect
   both sheets, dimensions, quantities, model/variant, operator and notes.
2. Packages / Warehouse Stock: choose ECO/Milana/Besttex; inspect the mixed-origin
   sample and unknown origins. Test an actual permitted legacy QR in your own
   isolated data; missing identities must never show a synthetic hidden hash.
3. Milana → Send fabric to ECO COTTON: select `LOCAL-MIL-001`, dispatch a quantity,
   open the driver Excel and check in-transit/outstanding status.
4. Log into ECO → Incoming fabric transfers: receive part, reopen, receive the
   remainder. Check fabric balances/history and the same transfer from Milana.
5. ECO → Accessory approval: select `PO-LOCAL-REVIEW` / `BSO-LOCAL-REVIEW`, add
   `LOCAL-ECO-BUTTON`, save, submit, approve and issue. Inspect allocation before
   issue, stock/history after issue, and persisted approval on reopening.
6. Try a shortage, an unapproved sewing handoff, the wrong factory, a stale plan,
   repeated issue/receipt, and an account lacking approval/issue permission.
   Check the relevant manufacturing handoff using disposable complete workflow
   data; the preview's basic sample alone does not prove every stage interaction.

Grant only the appropriate new permission keys in an isolated review database:
`eco_inventory.read/receive/consume`, `factory_fabric_transfers.read/dispatch/receive`,
and `eco_accessories.read/manage/approve/issue`. Inventory/transfer screens require
their read permission plus the relevant action permission. Materials-only accounts
still cannot access accessories. No existing user's grants were changed.

## Receiving correction after local operator review

The user explicitly requested material-type entry and receiving functionality
like Milana, ready to enter all ECO stock instead of the minimal demo form.
The follow-up integrates `clone_main` at `d6c2edd8` and preserves its customer-pack
and HR work. The old ECO revision IDs remain valid; `0154_eco_receipt_details`
merges `0151_eco_accessory_approval` and `0151_gate_enrollment` and adds receipt
JSON snapshots to batches and transfer lines. No reset/stamp or old stock
conversion is required. Direct field/enum DTOs validate the JSON before writes.

- ECO **Materials and suppliers** uses Milana's existing master-data operation.
  Create/edit fabrics, semi-finished material, accessories or packaging; enter
  SKU (or generate it), name, unit, cost, reorder level and fabric composition.
  Supplier creation/editing remains on its existing tab. These catalog records
  are shared; stock is separate. Existing `storage.items` / `storage.suppliers`
  permissions control these actions; no new grants were assigned.
- **Receive materials** supports Opening stock, Supplier delivery and Other
  receipt; material, batch/color, date/document, supplier, ECO warehouse creation,
  quantity/unit/cost, QC, order link, image upload, notes and fabric measurements,
  color/old codes and process details. Fabric accepts individual weighed rolls,
  total kg or total m. Accessories retain the chosen catalog unit.
- Stock displays quality, valuation/receipt details and per-roll readback.
  Pending/failed/held/rejected stock is unavailable to consumption/allocation;
  quality release is authorized and audited. Allocated stock must be released
  before a hold. Batch unit/category cannot be changed through catalog edits;
  first receipt and catalog mutation serialize on the shared Item lock.
- Materials-only accounts cannot view/select accessory warehouses. Source
  Milana warehouses cannot receive ECO stock. Transfer receipt retains the cost
  and fabric-code snapshot taken at dispatch, including partial receipts.
- Search filters all stock on the server before paging. Shared-item deletion
  includes ECO stock/requirements evidence, preserving linked records.

Bounded independent review identified and corrected accessory deep-link defaults,
unit mismatch, materials-only warehouse scope and a first-receipt/catalog-edit
race. The reviewer confirmed these fixes without a remaining actionable blocker.
Earlier PostgreSQL evidence above belongs to `bda49987`; the new candidate adds
a fourth PostgreSQL race case and must obtain its own CI evidence.

Local Uzbek browser checks created `QA-ECO-RIB-01` with Cotton 100% and cost4.25,
created an ECO warehouse and received12.5kg opening stock, then created
`QA-ECO-ZIP-25` directly under accessories. Database readback confirms categories,
units, receipt reference, cost, warehouse snapshot and quantity. These are local
QA examples, not factory inventory or production data.

Local review additions:

1. From either inventory choose **Materials and suppliers**; create the actual
   material types and suppliers. Use the appropriate category and stock unit.
2. Choose **Receive materials → Opening stock** for each physical batch already
   at ECO, or **Supplier delivery** for a new external receipt. Create/select an
   ECO warehouse and enter the full receipt. Milana dispatches still use incoming
   transfers so stock is not received twice.
3. Reopen receipt details and history; verify individual rolls, costs and totals.
   Place unallocated stock on hold and release it; test refusal to consume on hold.
4. Restart the local API and verify the same entries remain. Local SQLite proves
   persistence and operator flow; complete PostgreSQL/role/handoff acceptance is
   still a separate release gate.

Follow-up automated evidence: 148 focused receipt/approval/sewing/package/query-growth cases pass; Ruff, compileall, normal TypeScript, strict TypeScript and lint pass. Optimized frontend build and inherited build contracts pass on the receiving candidate. The final small UI changes are being rebuilt; no full backend or full final CI pass is asserted.
