# Milana ERP Project Context

Last updated: 2026-07-27

This is the repository copy of the durable context for future Milana ERP work.
It was consolidated from 181 ERP-associated Codex sessions dated 2026-05-12
through 2026-07-23: 127 user-facing chats, 42 internal review sessions, and 12
daily monitoring runs. Passwords, tokens, and other secrets are intentionally
excluded.

## What This Project Is

Milana ERP is the real production system for a garment/textile factory, not a
demo. It covers:

`Sales Order -> Planning -> Cutting -> Bundle QR/barcode -> optional Printing
-> Sewing -> Packaging -> Package QR/barcode -> Finished Goods -> Shipment`

It also includes branded-stock production, Besttex and Eco Cotton flows,
material and accessory inventory, purchasing, reservations, waste, payroll,
finance/1C integration, customers, audit history, forecasting, traceability,
tasks, notifications, user/role management, daily sewing reports, and an
AI/MCP assistant.

The repository is `C:\ERP`.

## Technical Shape

- Backend: FastAPI, SQLAlchemy 2, Alembic, PostgreSQL, Pydantic, JWT/cookie
  authentication.
- Frontend: Next.js App Router, React, TypeScript, TailwindCSS.
- Local development: Docker Compose, frontend on port 3000 and backend on port
  8000.
- Production domain: `https://erp.milanapremium.uz`.
- Production topology:
  - PostgreSQL VM: `172.16.10.3`
  - FastAPI backend VM: `172.16.10.4`
  - Next.js frontend VM: `172.16.10.5`
  - Nginx Proxy Manager routes the public domain and forwards `/api`,
    `/storage`, and `/health` to the backend.
- Production releases live under `/opt/milana-erp/releases/<release_id>`.
- `/opt/milana-erp/current` points to the active release on both application
  VMs.
- Backend uses release-tagged Docker images and publishes container port
  `10000` as VM port `8000`.
- Production data and uploaded files must stay outside release folders.
- `DEPLOYMENT.md` is the only authoritative deployment procedure. Old Vercel,
  Render, and Hugging Face deployment notes are historical.

## Current-State Warning

On 2026-07-23, a deployment was explicitly rolled back to release
`20260723_065753`. The abandoned release `20260723_132410`, its backend image,
staging archive, and test stock data were removed. Public health checks passed
after rollback.

As of 2026-07-27, both application VMs point to active release
`20260727_102911`, and the backend runs image
`milana-backend:20260727_102911`. This release retains the reviewed old-ERP
model migration and complete-detail display from `20260727_075027`, the
complete-catalog Models/PLM search from `20260727_092334`, supplier-scoped
Material Inventory viewing and reporting from `20260727_101728`, and adds
chosen-date Excel/PDF exports to the Daily Sewing Report. Alembic remains at
`0071_model_less_legacy_sales`. Release/image `20260727_101728` is the
immediate application rollback; `20260727_092334` remains as an older rollback
release.
The ASTATKA ready-stock import remains removed; model-less legacy sales
support is still present in the active code and migrations but has no imported
ASTATKA stock to act on.

The active backend and frontend release source was verified read-only on both
application VMs before the 2026-07-27 GitHub reconciliation. Its deterministic
source manifest covers 385 files and 5,258,504 bytes, with SHA-256
`f78fb17dcc95002b860fe40ef84eef3c9f936531f1756c8729b6f93809e118aa`.
Candidate branch `codex/sync-latest-erp-20260727` reconciles that exact source
with current `origin/main` in an isolated worktree. The original local working
tree and its uncommitted files remain untouched; backups, generated output,
screenshots, bundles, and other non-source artifacts are excluded. This source
control reconciliation did not deploy code or change production data.

Draft PR `#1` contains a later, source-only security follow-up that upgrades
the candidate to Pillow `12.3.0`, Next.js `16.2.12`, PostCSS `8.5.18`, and
sharp `0.35.0`. The only remaining audit exception is
`PYSEC-2026-1325`: python-jose installs ecdsa transitively, no fixed ecdsa
release exists, and production/public startup now rejects JWT algorithms other
than HS256 so the vulnerable elliptic-curve path is unreachable. The README
was also rewritten to describe the current production ERP and supported
developer workflow. These PR changes have not been deployed; production
remains on release/image `20260727_102911`.

The reviewed old-ERP catalog is now live in production: 6,404 source identities
were verified exactly once, with 5,637 new models and 767 existing models
enriched without changing any of the 881 pre-existing names, codes, or image
rows. Production now contains 6,518 models, 11,884 model-image rows, 24,535
model-size rows, 5,065 model-color rows, and the unchanged 42 BOM rows.
All 6,518 production model/variant rows are approved as of the later
2026-07-27 catalog-wide approval described below.
All 69 protected operational table snapshots were unchanged. Fourteen
unresolved identities covering 23 old records remain quarantined and must not
be guessed.

The verified pre-code custom PostgreSQL backup is
`/var/backups/milana-erp/pre_old_erp_models_code_20260727_075027.dump`
(873 restore-list entries; SHA-256
`9006c0efef0cedc015f8b0fcd7171c41e15b0f69553b11ea394b2269babf2d05`).
The final pre-data plain backup is
`/var/backups/milana-erp/pre_old_erp_models_20260727_075027.sql`
(SHA-256
`8b8ff1f8fcf6dced6a5a40524bede6d9bd4a5196a80718af763404f76a3a1c21`),
and the rollback-complete media backup is
`/opt/milana-erp/shared/backups/pre_old_erp_model_media_20260727_075027_regular.tar`
(SHA-256
`40e42ea4756aad624a65e52920ad2724b3abc681fed25563aa7785f336850063`).
Older verified PostgreSQL backups remain stored as
`pre_inventory_reports_20260724_040430.dump`,
`pre_variant_image_fix_20260724_062842.dump`, and
`/var/backups/milana-erp/pre_models_performance_20260727_062443.dump`
(858 restore-list entries; SHA-256
`ceb127b3ebb7c9747229c431f4034b4626dd78b26974a086370fc3bedfc15c4d`).
The pre-import backup remains
`pre_astatka_ready_stock_20260725_045504.dump` with SHA-256
`33f105a084d5cd14114a43951444e0369c427ccbf254fc91272c24eceb316e5e`.
The verified backup immediately before removing the ASTATKA import is
`/var/backups/milana-erp/pre_astatka_ready_stock_purge_20260725_091323.dump`.
Its restore list contains 873 entries and its SHA-256 is
`94a341eef416792d37b501637fcaecb00f7dbefa51b125173a2ae4b446de107a`;
a matching local copy is retained under
`.codex-work/astatka-ready-stock-purge-20260725/backups/`.
The verified backup immediately before the supplier-scoped Material Inventory
release is
`/var/backups/milana-erp/pre_supplier_inventory_filter_20260727_101728.dump`.
Its restore list contains 873 entries, it is 25,156,362 bytes, and its SHA-256
is `8fbdd7399f35e1af77b784b7d77a709f2ca1173befce581f09822ab87a8efb98`.
The verified backup immediately before the Daily Sewing Report export release
is
`/opt/milana-erp/shared/backups/pre_daily_sewing_exports_20260727_102911.dump`.
Its restore list contains 873 entries, it is 25,160,670 bytes, and its SHA-256
is `2f508d3b7b8322530936f1bad9ca46b7f59564a2c9d0865a95ac20568771d02a`.
The verified backup immediately before deleting mistaken branded-stock
production order `PO-2026-000037` is
`/var/backups/milana-erp/pre_po37_full_delete_20260725_175650.dump`. Its restore
list contains 873 entries, its SHA-256 is
`2dd08def4e911775fb9dcb601233b319e4a0de79d313554a388de04805c304dc`,
and a matching local copy is retained under
`.codex-work/po37-delete-20260725/backups/`.

Do not assume that same-day changes deployed after `20260723_065753` are still
active in production. Reverify before relying on:

- Per-batch material picture isolation.
- Restored Cutting access to Sewing Flows, Daily Sewing Report, and Sewing
  Floor.
- Daily Sewing Report Kroy number and two-part top/bottom quantity changes.
- Any other release created after `20260723_065753`.

The sales-to-warehouse shipping improvement was implemented and tested in the
local workspace, but the production deployment containing it was rolled back.
The desired behavior remains:

- Warehouse notification names each model/variant, color, size, quantity,
  customer, and destination.
- Notification opens the exact order in the shipping queue.
- Warehouse queue shows item-level details, not only address and total
  quantity.

At the time this context was written, the local Git working tree was very dirty,
contained extensive uncommitted work, and was 11 commits behind `origin/main`.
Always run fresh Git checks. Do not deploy by blindly taking only local HEAD or
only GitHub. First reconcile the production release, GitHub, and current local
changes in a clean staging checkout/worktree without altering the user's
working tree.

## Local Old-ERP Model Migration

On 2026-07-25, the old ERP model catalog was migrated to localhost only for
review. The migration did not target, change, or deploy production. The frozen
source contained 3,065 model rows and 5,153 variant rows. Reconciliation
created 4,408 variants and 1,218 standalone models, bringing the local catalog
to 6,505 models, 11,856 image rows, 24,355 size rows, and 5,046 color rows.
Model BOM and all operational order, stock, package, shipment, user, and
finance data remained unchanged.

Duplicate reconciliation treats the current ERP as authoritative: existing
model names, codes, and pictures are immutable, and only missing metadata or
variants may be added. Twenty-nine ambiguous or conflicting source identities
were quarantined instead of guessed. A deterministic metadata correction
filled missing fields on 291 records created by the import; it did not target
pre-migration models or create additional catalog rows or files.
The final fixed-planner dry run was fully idempotent with zero catalog,
metadata, provenance, or media actions. An independent post-correction audit
passed 27/27 checks across all 71 database tables, 63 operational aggregates,
all 29 quarantines, and the complete 8,163-file media inventory.

The auditable source, plans, reports, quarantine list, and integrity inventories
are under
`.codex-work/old-erp-model-migration-local/2026-07-25T09-18-06-117Z/`.
Verified pre-import and pre-correction database/media backups are retained
under `local-backups/`. At migration handoff on 2026-07-25, the local database
remained at Alembic revision `0064_remove_fabric_pictures` and the backend was
deliberately not restarted.
For review, an isolated temporary frontend is bound to loopback at
`http://localhost:3001/models` because the pre-existing port-3000 frontend
proxy was returning errors. The catalog and representative `PJ-1106` master
and variant pictures were verified in that preview. The production release
remains `20260725_062442`.

On 2026-07-27, the stalled local Docker Desktop engine was recovered so the
localhost administrator credential could be rotated at the user's request.
Restarting the existing ERP containers advanced the local database to Alembic
revision `0069_legacy_finished_goods`. The local backend image was rebuilt to
install the already-declared `openpyxl` dependency, after which health and an
authenticated Super Admin login both returned HTTP 200. Previous sessions
were revoked and the reset was audit-recorded. No credential value is stored
in this context, and production was not changed or deployed.

Later on 2026-07-27, the localhost-only model migration was corrected from a
complete, hash-pinned extraction of the old ERP. The current old source has
3,072 model rows and 5,163 variant rows; its complete-detail evidence contains
28,272 operation rows and 1,929 recipe rows. For the original 3,065-model
receipt scope, 6,394 imported model records received missing legacy details
and 4,629 safe display names were changed to the exact old `Product` value.
Existing duplicates remained authoritative: their names and picture rows were
not changed, including eight source conflicts that were deliberately
preserved.

The reviewed append-only delta created ten variant model rows and enriched one
exact duplicate without changing that duplicate's name or pictures. It added
20 image rows, 29 size rows, and 10 color rows. The final local catalog has
6,515 models, 11,876 image rows, 24,384 size rows, and 5,056 color rows.
Model BOM and every checked order, stock, package, shipment, item, and finance
count remained unchanged. Seven new models whose authenticated source
operation list was empty were explicitly stored with zero paid operations;
the final repeat dry run had zero remaining creates, updates, renames, media,
size, or color actions.

The port-3000 localhost frontend now shows Product-based names, complete old
ERP provenance, recipes, and the expanded paid-operation fields. Browser QA
verified model `6113` (`TJ-2053`, 30 operations), model `7943`
(`PJ-1203-5581`, one recipe and zero source operations), model `7948`
(`XJ-3062-5583`, 45 operations), and protected duplicate model `6658`.
Fourteen unresolved identities covering 23 old model records remain held for
an explicit conflict policy; 22 have incompatible pictures and/or colors and
record `1683` has no usable identity. They must not be merged or split by
guessing.

The complete-correction artifacts are under
`.codex-work/old-erp-model-complete-correction-local/2026-07-27T03-41-35-375Z/`.
The latest pre-apply plain PostgreSQL backup is
`local-backups/pre_local_explicit_empty_paid_ops_20260727_104145.sql`
(SHA-256
`6e28a4024e704375193e1b6891cee272dd3dd411e9d78c67d49ccca8144b4e92`);
the verified current media snapshot is backed by
`local-backups/pre_local_delta_product_name_media_20260727_102802.tar`
(SHA-256
`f0ad89223f87bf6ec55a476e9163cac8d8a99b143f43ec5fe8511bd4cc291e31`).
This work touched localhost only; production was not changed or deployed.

Also on 2026-07-27, the localhost Models/PLM list was optimized after the
completed migration made its original all-record grouping query too slow.
Variant-group pagination now uses a lightweight identity pass, selects whole
groups, and hydrates only the requested page. Model-image binary data is not
loaded for list requests, and the frontend opts into a compact response that
keeps the names, model/variant identity, translations, composition, pictures,
and fabric information used by the list while omitting large migration-detail
sections that are only needed on model detail pages. The default API response
remains compatible.

The list now keeps existing rows during refresh, shows an accessible loading
indicator on first load and pagination, distinguishes errors from a successful
empty result, avoids off-screen card layout work, and disables repeated model
card prefetches. Signed-in localhost browser timings improved from about 3.30
to 1.81 seconds for 100 groups, from 4.35 to 2.55 seconds when selecting 500
groups, and from 4.79 to 2.85 seconds for page two at 500 groups. The page-one
backend path fell from 29 SQL statements and about 3.51 seconds to 4 statements
and about 1.66 seconds with the compact response; its decoded response shrank
from 531 KB to 127 KB. Catalog tests, Ruff, strict TypeScript, targeted ESLint,
translation parity, the production frontend build, health checks, and browser
loading-state checks passed. No database rows were changed. This optimization
was first reviewed on localhost. A production-adapted, five-file version was
subsequently deployed as release `20260727_062443` without importing any
localhost model or media data.

### Production Old-ERP Model Migration

On 2026-07-27, the reviewed model package was deployed to production through
release `20260727_075027`. The frozen package SHA-256 is
`941457e0299c8876b1cf5fe164c4238ef6d4085543a631c6706e67162eba2e85`.
The deterministic production plan SHA-256 is
`ca95920695d930d81d0026a5d48acc30cd1fe6378e239cc06f3d81ff67854483`;
the applied report file SHA-256 is
`d30cf15e2edba42e82d98f815af1d9e3932a18e998d4de94976d30676396318e`.

The migration processed all 6,404 reviewed identities: 5,637 were created and
767 exact duplicates were enriched. It added 9,580 image rows, 23,534 size
rows, 5,056 color rows, and 22,867 paid-operation entries. New model display
names use the old ERP `Product` field. Existing duplicate names, codes, and
pictures remained authoritative and were not changed. Recipes and complete
old-ERP provenance are shown on model detail pages. Seven authenticated
source records with empty operation lists remain explicitly represented with
zero paid operations.

The independent verifier passed with all 6,404 migration receipts present
exactly once, zero duplicate canonical identities, all 881 pre-existing model
name/code/image snapshots unchanged, and all 69 operational table hashes
unchanged. The final media inventory contains 8,584 files totaling
3,138,157,547 bytes; 4,966 files were newly created, while ten planned targets
already existed with identical content. The verifier file SHA-256 is
`afc2376ab15262afa54d121908f6d2b2b47e1b5780860bfe5e99b860a99b9432`.

Signed-in production browser QA checked model `5227` (`TJ-2053-879`, Product
name and 30 paid operations), model `3993` (`PJ-1203-5581`, one recipe and
zero source operations), model `6492` (`XJ-3062-5583`, 45 paid operations),
and protected existing model `3` (`TJ2026-V-4248`). Model `3` kept its exact
original name and primary picture while receiving missing old-ERP details.
The production catalog displayed its loading indicator and rendered 100 of
2,021 variant groups in about 2.1 seconds. Backend/internal, frontend/internal,
public health, and public login checks all returned HTTP 200; service logs
showed no deployment errors, and the signed-in browser console was empty.

Later on 2026-07-27, the user authorized approving the complete production
model catalog. One approval was made from the visible Models button and the
remaining 5,637 draft model/variant rows were approved sequentially through
the exact same canonical approval action. The final status is 6,518 approved
and zero draft models. Every approval records the System Admin approver,
timestamp, and audit entry. The verified pre-approval custom PostgreSQL backup
is
`/var/backups/milana-erp/pre_approve_all_models_20260727_085500.dump`
(873 restore-list entries; 24,405,205 bytes; SHA-256
`47ca688bb7a01afddf5576e9a12abd1d373bcce28afaf7f492b356caf4365309`).
Independent post-apply checks confirmed the model identity hash and all model
image, size, color, and BOM snapshots were unchanged; only approval metadata
and the expected 5,638 approval audit records changed. The post-verification
dry run found 6,518 approved models and zero remaining approval targets. All
four production health checks returned HTTP 200, service logs were clean, and
the Models UI showed no remaining Approve actions. The complete approval
evidence is under
`.codex-work/old-erp-model-production-migration-20260727/production-evidence/approval/`.

Also on 2026-07-27, release `20260727_092334` corrected the three Models/PLM
filter fields so they search the full server-side catalog before pagination
instead of filtering only the rows loaded on the current page. The frontend
debounces requests by 250 ms and keeps the existing loading indicator. The
release candidate was built from the exact active `20260727_075027` release
and changed only the catalog route, its regression tests, and the Models page.
The 15 catalog tests, Ruff, strict TypeScript, targeted ESLint, and the
production Next.js build passed. Signed-in production browser QA found
off-page records by model/variant number, name, and category, each with the
correct single result and no console errors. Both internal services and both
public endpoints returned HTTP 200, and the backend and frontend logs showed
no deployment errors. No database rows or schema were changed.

The verified pre-deployment custom PostgreSQL backup is
`/opt/milana-erp/shared/backups/pre_model_search_20260727_092334.dump`
(873 restore-list entries; 25,160,197 bytes; SHA-256
`25d928761b6ed86a2028d1e2066e301e21a0e036737e31738041675639a7cab7`).
Deployment evidence is under
`.codex-work/model-search-full-catalog-20260727/20260727_092334/`.

Fourteen unresolved identities covering 23 old model records remain
quarantined. The complete production package, backups, reports, verifier, and
run evidence are under
`.codex-work/old-erp-model-production-migration-20260727/` locally and
`/opt/milana-erp/shared/migrations/old-erp-models-20260727_075027/` on the
backend VM. The migration's original application rollback is release/image
`20260727_062443`; complete data rollback uses the verified pre-data database
and regular-file media backups listed in Current-State Warning. For the later
search-only release, the immediate application rollback is `20260727_075027`.

## Stable Business Rules

- The ERP must reflect real factory handoffs; do not add disconnected demo
  screens.
- Creating a Production Order starts Cutting automatically.
- Optional stages such as Printing must be skipped automatically when not
  required.
- Cutting overproduction becomes the real downstream planned quantity for
  Sewing, Packaging, and Storage.
- Cutting shortfall may close Cutting while remaining replacement work is
  tracked separately.
- Work must remain traceable by sales order, production order, work order,
  batch, bundle, package, model, variant, size, and responsible department.
- User-facing screens should show real names/numbers, not raw database IDs.
- Sales prices are net; tax calculation was removed.
- A branded-stock pack is commonly treated as 60 pieces where that flow
  applies.
- Package creation must respect the selected batch's packed quantity, including
  partial packages.
- Finished-goods stock must come from validated packaging/receipt evidence;
  never create stock casually for testing.
- Old ready-product balances may remain model-less when no exact current model
  exists, but must retain immutable source receipt evidence and their original
  source model code/name for search, stock display, labels, and shipment work.
- Material and accessory quantities use kilograms where applicable.
- Material pictures may belong to the model/BOM, shared material item, or exact
  stock batch. Batch-row uploads must affect only that batch. An assigned batch
  picture is operational material evidence and must not replace a model or
  variant identity picture.
- Model variants are primarily differentiated by variant number,
  fabric/color/pattern, and picture while remaining selectable for new orders.
  Process Tracking and Production Order identity surfaces must use the same
  canonical variant picture shown in Models.
- Employees may edit after deadlines; the post-deadline admin restriction was
  removed.
- Deletions must be narrowly scoped and blocked when records are already
  reserved, linked, or used.

## Departments and Special Production Flows

- Standard flow: Cutting -> optional Printing -> Sewing -> Packaging ->
  Finished Goods.
- Besttex has its own textile flow and packaging path.
- Eco Cotton has dedicated Cutting and Sewing departments/inboxes; Planning can
  route work to Main Cutting or Eco Cotton Cutting.
- Replacement work from Sewing defects goes back to Cutting, keeps the
  originating sewing line, and remains visible to Packaging as outstanding
  replacement quantity.
- Cutting Inventory holds created bundles until Sewing or Printing scans and
  receives them.
- Sewing lines were consolidated/renamed in earlier work. Read current live
  names and mappings from production before another migration.
- Sewing-role navigation is intended to show only Sewing Flows, Daily Sewing
  Report, and Sewing Floor, plus the internal work-order sewing action needed
  to record finished work.
- Cutting users were intentionally given access to the three Sewing workspace
  pages as an exception.
- On 2026-07-24, a user-approved duplicate-production cleanup retained the
  older `PO-2026-000038` and deleted the unused newer `PO-2026-000039`.
  The two orders had identical planning group, model, fabric, six size lines,
  600-piece quantity, deadline, and untouched waiting work orders. The deleted
  order had no batches, cutting records, bundles, reservations, or downstream
  links. Its six item rows and four work orders were removed atomically, and
  audit record `#3564` preserves the deletion evidence.

## Daily Sewing Report

This is a reporting ledger and is not supposed to mutate the main production
workflow automatically.

Important intended behavior:

- User chooses a sewing line and may select the active work from Sewing Floor.
- Order, model, variant, and Kroy number are detected where available.
- Model/variant and Kroy number can be entered manually when no
  order/model/passport is attached.
- Kroy number should come from the latest Cutting Passport when available.
- Reports record sewn quantity, defects, defect reason, and work date.
- Users can add more sections/work rows.
- Each section has a "2-part garment" checkbox:
  - Off: one sewn quantity.
  - On: separate Top quantity and Bottom quantity.
- Saved reports and summaries retain the manual identity and section
  quantities.

Because of the 2026-07-23 rollback, verify which of these fields are currently
live before making follow-up changes.

## Inventory, Models, and QR

- Material Inventory and Accessory Inventory are separate views.
- On 2026-07-25, the user-approved `astatka.xlsx` ready-product balance was
  imported into production: 1,232 positive source rows and 437,636 pieces.
  Exact matches linked 305 rows (109,826 pieces) to existing models; 927 rows
  (327,810 pieces) were stored model-less with their original source identity.
  No models, model sizes, model colors, brands, or aliases were created. Five
  negative source rows were excluded (`PJ-1016-v1163` -6,
  `SJ-4044-v3372` -210, `xj-3062-v3903` -60, `tj-2170-v4478` -45, and
  `pj-1169-v4872` -60); the last row's separate +60 entry was also excluded
  because the pair nets to zero. The import created one immutable receipt,
  package, package item, finished-goods row, and storage scan per accepted
  source row. Post-import production totals were 1,255 packages, 1,370
  finished-goods rows, 438,976 pieces, and 438,376 available pieces; the model
  count remained 881. Database reconciliation, signed-in warehouse search for
  model-less item `F-2544`, migration `0070_model_less_legacy_stock`, focused
  regressions, frontend build/type checks, and all four production health
  checks passed. Audit record `#3632` records the import.
- Release `20260725_054453` added direct sales support for those old balances.
  A sales line can reference the exact finished-goods row and snapshot its
  original source model code/name while leaving `model_id` null. The sales form
  searches current and old ready stock together, reserves only the selected
  stock row, and shipment consumption supports partial sales from an aggregate
  legacy package without incorrectly selling the remainder. Migration
  `0071_model_less_legacy_sales` is active. A signed-in production check found
  1,140 sellable product/variant choices and successfully searched and selected
  `F-2544` as a 60-piece full pack without creating a test order. Production
  reconciliation still showed 881 models, 1,232 legacy receipts/packages,
  437,636 imported pieces, and zero imported reservations/sales immediately
  after deployment.
- Release `20260725_062442` removed the generic Incoming, Pending, In Progress,
  and Done Today columns from `/departments/FGS` only. The Finished Goods page
  now opens directly to Pending Package Intake and Ready to Ship. A signed-in
  production check confirmed both operational tables remained visible, the
  four workflow columns were absent, all four health checks passed, and no
  business data changed.
- Later on 2026-07-25, the user reversed the ASTATKA ready-stock decision and
  approved complete removal. A guarded transaction deleted exactly 1,232
  `ASTATKA_XLSX` receipts, packages, package items, finished-goods rows, and
  import scan logs totaling 437,636 pieces. The import had created zero catalog
  models; all 881 real models, including the 305 that had only been referenced
  by imported stock, were preserved.
- The only downstream use was a 120-piece reservation and package link for
  `SO-2026-000002` and `SH-2026-000002`. Both records were retained for audit
  and changed to `cancelled`; the reservation and shipment-package link were
  removed before the imported stock was deleted. Audit records `#3648` through
  `#3650` record the two cancellations and purge.
- Post-purge reconciliation shows zero legacy receipts, 23 packages, 1,340
  finished-goods pieces, 740 available pieces, 600 reserved pieces, zero sold
  pieces, and 881 models. All four health checks returned HTTP 200. No code
  release was deployed; active release remains `20260725_062442`.
- Inventory has searchable material/accessory groups and master-data management
  for materials, accessories, and suppliers.
- Mubina has narrowly scoped access to delete unused duplicate stock-batch
  rows; used/reserved rows must remain protected.
- On 2026-07-24, Fabric Storage stock-batch deletion was fixed for PostgreSQL.
  The delete query now locks only the `stock_batches` row instead of also
  locking the nullable eagerly joined material row, which previously caused a
  500 before safety checks ran. Receipt movements are also explicitly flushed
  before their parent batch is deleted, avoiding a PostgreSQL FK-ordering
  failure. Release `20260724_120725` passed all 23 inventory regression tests
  and all four required health checks.
- On 2026-07-24, a user-approved production-data correction changed
  `SO-2026-000033` from the wrong `4958 / Rotation` fabric row to the existing
  `4958 / SEKER SAKAR` row (559.6 kg). The now-unlinked wrong `Rotation` row
  containing 300 kg and its lone receipt movement were deleted atomically.
  Audit records `#3562` and `#3563` record the relink and deletion. No other
  inventory or production-order rows were changed.
- On 2026-07-25, the user confirmed that public order
  `SO-2026-000037`—the UI alias for standalone branded-stock
  `PO-2026-000037`—was entirely mistaken. A guarded, rollback-rehearsed
  transaction deleted exactly 1 production order, 6 production items, 4 work
  orders, 1 production batch, 1 cutting record, 6 untouched bundles, 6
  creation-only bundle scan logs, 1 recorded waste row, and 4 stale sewing
  notifications. There were no sales-order, package, shipment,
  finished-goods, reservation, payroll, invoice, or payment links.
- The mistaken cutting entry had consumed 256 kg from Fabric Storage batch
  `4958`. The cleanup restored that batch from 303.6 kg to 559.6 kg and
  retained original consume movement `#497` with compensating return movement
  `#499`. Shared planning order `0029`, sibling `PO-2026-000038`, model
  `Х-3044 / V-5567`, and all catalog/material records were preserved.
  Deletion audits are `#3657` and `#3658`; their new hash-chain segment passed.
- The six generated bundle QR files and six barcode files were archived and
  removed from live storage. Signed-in Cutting, Milana Sewing, and Production
  Orders pages contain no `SO-2026-000037`, `V-5567`, or links to work orders
  `152`/`153` or production order `37`; sibling `SO-2026-000038` remains
  visible. All four required health endpoints returned HTTP 200. No code
  release was deployed; active release remains `20260725_062442`.
- Reservations connect planned production to stock, and cutting consumption
  should not drift from reservations.
- Models and materials can have pictures; list pages use thumbnails for
  performance.
- On 2026-07-24, branded-stock Planning was fixed so a model without fabric
  BOM rows no longer hides Material Inventory batches or blocks order
  creation. The picker lists all positive, QC-accepted material batches,
  prioritizes exact BOM-item matches when present, and preserves a valid
  manually selected non-BOM batch. Production release `20260724_094140` was
  verified in the signed-in UI with model `ТJ-2107-3553` and batch `4957`
  (`Suprem`, 548.8 kg available), by frontend type/i18n/build checks, and by
  all four required health checks. No production order or stock movement was
  created during verification. Empty verification planning group `0032` was
  cancelled with zero productions and an audit record; the user's pre-existing
  open planning group `0031` was left unchanged.
- On 2026-07-23, the DINAR 2025 material workbook was imported into production:
  255 source rows, 66,653.51 kg, and 2,693 pieces/rolls were reconciled exactly.
  The import created 23 material masters and 254 stock batches; the previously
  tested batch 7758 was retained as the one exact existing row. Pictures were
  attached to all 198 rows that had embedded workbook images; 57 source rows
  had no embedded image. Because the ERP requires a batch number, the three
  blank source batches use traceable IDs `DINAR-XLSX-R6`, `DINAR-XLSX-R69`, and
  `DINAR-XLSX-R110`. No deployment or code release was performed for this
  operational data import.
- On 2026-07-23, the current positive balances from the SAFF workbook
  `Cафф.xlsx` were reconciled into production: 26 rows, 17,245.55 kg, and 475
  rolls. Four equivalent batches (`7450`, `7451`, `7678`, and `7679`) already
  existed and were retained; the source's stray leading backtick on `7679` was
  treated as the same batch. The import created 11 material masters and 22
  stock batches totaling 14,883.12 kg and 354 rolls, increasing the batch
  ledger from 377 to 399 rows. All 23 source rows with embedded pictures have
  batch pictures in the ERP; three source rows had no picture. New rows use
  supplier Saff, Fabric Storage, and QC status Qabul. No deployment or code
  release was performed.
- On 2026-07-24, the Samo positive-balance workbook was imported into
  production: 11 stock rows, 6,297.08 kg, and 285 rolls. Because the workbook
  contains no fabric names and the ERP requires every batch to have a material,
  the import created 11 independently renameable temporary masters named
  `Material pending - Samo - <batch>`; repeated batch numbers also include the
  Excel row suffix (`R2`, `R3`, etc.). All 11 workbook pictures are attached to
  their exact batch rows. New rows use color code `C0001`, supplier Samo,
  Fabric Storage, and QC status Qabul. The batch ledger increased from 399 to
  410 rows. These 11 temporary material names remain operational follow-up
  work; no deployment or code release was performed.
- On 2026-07-24, the inventory batch editor was deployed so Material Name
  selects an existing same-group, same-unit material instead of renaming the
  shared material master. Reassignment is limited to unused, unreserved
  batches, and the original receipt movements follow the reassigned batch.
  The live modal was checked without saving any inventory change.
- On 2026-07-24, Material Inventory reporting gained deployed Excel and PDF
  exports. Both reports include every material with positive on-hand stock,
  grouped material/SKU totals for batch rows, recorded rolls/pieces, and
  kilograms, plus a grand total. The PDF supports English, Russian, and Uzbek
  text, and the Excel grand totals use formulas. Production verification
  downloaded both files and reconciled 57 materials, 407 positive batch rows,
  6,182 recorded rolls/pieces, and 135,190.58 kg. The deployment passed the
  21-test inventory suite, frontend type/i18n/build checks, report-generation
  smoke tests, all four required health checks, and live browser verification.
- On 2026-07-27, release `20260727_101728` added a material-only Supplier
  filter to Material Inventory. Users can choose a named supplier or
  `No supplier`; the scope is preserved in the URL and applies consistently
  before pagination to item counts, positive stock, batch lines, search/date
  filtering, and both Excel and PDF exports. Filtered reports identify the
  selected supplier and are returned with `Cache-Control: no-store`. A narrow
  inventory supplier-options endpoint exposes only supplier IDs/names and
  whether unassigned positive stock exists. Production API results reconciled
  exactly to independent database totals: all suppliers 57 material types,
  428 positive batch lines, 144,789.76 kg, and 6,614 pieces; Dinar 29 types,
  341 lines, 100,234.44 kg, and 4,356 pieces; unassigned 5 types, 24 lines,
  9,977.77 kg, and 1,024 pieces. Existing referenced suppliers `masis` and
  `MASIS` remain separate records and were not merged. No material, supplier,
  stock, movement, or schema rows were changed. The focused 49-test backend
  suite, Ruff, compile checks, i18n parity, strict TypeScript, targeted ESLint,
  local signed-in UI QA, production frontend/backend builds, filtered
  Excel/PDF validation, Alembic head, service logs, and all four required
  health checks passed. The immediate rollback is release/image
  `20260727_092334`.
- On 2026-07-27, release `20260727_102911` added chosen-date and date-range
  Excel/PDF exports to the Daily Sewing Report. Both formats include a
  line-level summary and the saved report rows with report/saved times, line,
  section, order, model, variant, Kroy number, sewn and defective quantities,
  reason, and notes. The Excel workbook contains `Summary` and `Entries`
  sheets with filters, frozen headers, typed dates, and summary formulas; the
  landscape PDF supports Unicode and page numbering. Access follows the
  existing Daily Sewing Report read permission. Existing report saves already
  persist in PostgreSQL table `sewing_daily_reports`; this release did not
  create or modify business rows and did not change the schema. The clean
  seven-file release passed six focused backend tests, Ruff, strict TypeScript,
  targeted ESLint, production frontend/backend builds, Alembic head, signed-in
  production UI and real Excel/PDF download validation, clean browser/service
  logs, and all four required health checks. The immediate rollback is
  release/image `20260727_101728`.
- On 2026-07-27, release `20260727_062443` optimized the production Models/PLM
  list from the exact active `20260727_060803` source. Variant-group requests
  now paginate complete groups before hydrating their members, omit binary
  image data from list hydration, and offer an opt-in compact response that
  retains every field used by the catalog. The frontend uses that compact
  response, preserves existing rows during refresh, shows accessible initial
  and refresh loading states, separates retryable errors from a true empty
  result, skips off-screen card layout, and disables numeric model-detail card
  prefetches. Signed-in production QA loaded 100 of 189 groups in 483 ms and
  all 189 groups through the 500-size option in 447 ms, with the spinner
  observed and no false empty/error state or console errors. The canonical
  five-file diff passed 14 catalog tests, Ruff, strict TypeScript, targeted
  ESLint, EN/RU/UZ parity, production builds, Alembic head
  `0071_model_less_legacy_sales`, exact deployed-source hashing, clean service
  logs, and all four required health checks. Production still has 881 model
  rows and 2,304 model-image rows; no business rows, media, packages, or
  migration revision changed. The verified pre-deploy backup is
  `/var/backups/milana-erp/pre_models_performance_20260727_062443.dump`
  (858 restore-list entries; SHA-256
  `ceb127b3ebb7c9747229c431f4034b4626dd78b26974a086370fc3bedfc15c4d`).
  Release `20260727_060803` and its backend image remain available for
  rollback. The unchanged frontend dependency tree still reports six
  high-severity npm audit findings.
- On 2026-07-27, release `20260727_060803` added targeted SWR background
  refresh to live operational data without globally polling all 207 data
  hooks. Process Tracking and department boards refresh every 10 seconds;
  operational queues, order/stock lists, maps, package detail, and Sewing Flow
  work lists refresh every 15 seconds; aggregate dashboards refresh every 30
  seconds. These bounded hooks also refresh in hidden tabs, on focus, and after
  reconnect, pause while offline, deduplicate same-key requests, and send GETs
  with `cache: no-store`. Large reference lists, editor/form hydration, and
  imperative scanner lookups remain excluded so typed quantities, filters,
  selections, and scan inputs are not reset. Cached Process Tracking and
  dashboard content stays rendered during background validation and transient
  errors; the Process Tracking Refresh button shows loading only for a manual
  click. Signed-in production verification observed three successful
  Process Tracking requests during a 23-second hidden-tab window and a
  Warehouse Stock request on its 15-second cadence with stable rendered rows.
  The exact 24-file frontend-only diff passed independent safety review,
  targeted ESLint, TypeScript, i18n, production builds, fixed-interval and
  no-store behavior checks, Alembic head `0071_model_less_legacy_sales`, and
  all four required production health checks. No business data or migration
  changed. The verified pre-deploy backup is
  `pre_background_refresh_20260727_060803.dump`.
- On 2026-07-27, release `20260727_051430` separated model/variant identity
  pictures from operational fabric-batch pictures. The Models catalog,
  Process Tracking list, Production Order list/detail, and Work Order API now
  resolve the same exact `variant_picture_url`; `material_image_url` remains
  batch-first for cutting, scanning, and other floor work. A database-level
  read-only production audit covered all 29 retained production orders and
  found 29/29 catalog matches in both list and detail, zero list/detail
  disagreements, and zero variant pictures replaced by batch images. Six
  orders had assigned batch pictures; all six retained those pictures
  separately as operational material evidence. Signed-in browser checks
  compared all six previously mismatched Process Tracking rows and confirmed
  `PO-2026-000034 / V-3637` matched the Models Variants tab and order Summary.
  No business rows, uploaded media, or migration revision changed. Focused
  backend image regressions, 79 broader backend tests aside from one unrelated
  order-dependent shared-session test that passes alone, Ruff, Python
  compilation, frontend i18n/type/build checks, Alembic head
  `0071_model_less_legacy_sales`, and all four required production health
  checks passed. The verified pre-deploy backup is
  `pre_variant_picture_consistency_20260727_051430.dump`.
- On 2026-07-24, exact model-variant material pictures were made authoritative
  over shared BOM/item fallback pictures in production tracking, production
  details, department inboxes, model previews, and labels. Creating or editing
  a variant now synchronizes its explicit material picture, preventing a shared
  BOM fabric photo from making unrelated variants look identical. An explicitly
  assigned stock-batch picture still takes precedence because it represents the
  actual fabric issued to that production order. The incorrect primary garment
  photo for `XJ3128-V-4683` was replaced from a verified source; the previous
  image record was retained for recovery. Release `20260724_063531` was verified
  against production orders `PO-2026-000024`, `000025`, `000027`, and `000028`,
  all four required health endpoints, Alembic head, automated tests, and the
  signed-in Process Tracking UI.
- On 2026-07-24, Process Tracking was corrected to use the production order's
  explicitly assigned stock-batch picture before the model-variant material
  fallback. This resolved the disagreement where `PO-2026-000033` showed the
  orange `XJ3044-V-5492` variant swatch in Process Tracking while Production
  Order Detail correctly showed the dark floral picture for assigned batch
  `4958 / SEKER SAKAR`. Release `20260724_124802` was staged from the prior
  active release with only the Process Tracking backend file changed. The
  focused batch-picture precedence and fallback tests passed, both application
  VMs and the backend image were verified on the new release, all four required
  health endpoints returned HTTP 200, and the live Process Tracking and
  Production Order APIs now return the same batch image URL.
- On 2026-07-24, four legacy variant material-image records were reconciled to
  their distinct, audit-confirmed original attachments: `ХJ-3030-V-5107`,
  `ХJ-3030-V-3637`, `Х-3044-V-5568`, and `Х-3044-V-5567`. Production orders
  `000034`, `000035`, `000037`, `000038`, and `000039` were verified through
  both the live API and signed-in Process Tracking UI. At that point, seven
  shown legacy variants had no separately attached original material picture
  in the new ERP audit history: `XJ3152-V-5411`, `PJ1173-V-5472`, `PJ1173-V-5473`,
  `PJ1173-V-4684`, `PJ1142-V-3506`, `XJ3044-V-5370`, and
  `XJ3044-V-5373`. The validated pre-repair backup is
  `pre_restore_variant_pictures_20260724_065150.dump`. This was a data repair;
  no new code release was required.
- Later on 2026-07-24, those seven missing material pictures were recovered
  from their exact variant records in the signed-in legacy ERP and imported
  into production. The extracted originals were visually checked and the
  uploaded copies matched them byte-for-byte. Production orders `000019`,
  `000020`, `000023`, `000025`, `000030`, `000031`, and `000032` were verified
  through the live API and signed-in Process Tracking DOM. The validated
  pre-import backup is `pre_old_erp_variant_import_20260724_070427.dump`.
  This was an audited data/file repair on active release `20260724_063531`; no
  code deployment was needed.
- Four of those legacy JPEGs (`XJ3152-V-5411`, `PJ1142-V-3506`,
  `XJ3044-V-5370`, and `XJ3044-V-5373`) were subsequently found to be missing
  only their final JPEG end marker. Browsers could decode the source files, but
  the thumbnail service correctly returned HTTP 415. The exact source files
  were preserved, the missing end marker was appended without recompression,
  and fresh audited picture URLs were assigned to avoid browser negative-cache
  entries. All seven recovered pictures then returned valid 160px WebP
  thumbnails and loaded with non-zero dimensions in the signed-in Process
  Tracking UI. The validated database backup is
  `/opt/milana-erp/shared/backups/pre_legacy_thumbnail_repair_20260724_071052.dump`;
  the four pre-repair source files are preserved under
  `/opt/milana-erp/shared/backups/legacy_thumbnail_sources_20260724_071052/`.
  Active release remained `20260724_063531`; no code deployment was needed.
- On 2026-07-24, 32,361 UZERP ready-product rows, 429,687 available pieces,
  158,079 package barcode aliases, and migration-only model placeholders were
  imported. Subsequent model linking did not meet the user's requirements.
  Treat the import and all reconciliation evidence as rejected historical work,
  not current production inventory.
- On 2026-07-25, the user explicitly requested complete removal of that import.
  A guarded purge matched and deleted exactly 32,361 legacy receipts, 32,361
  packages, 32,361 package items, 32,361 finished-goods rows, 32,361 import
  scan logs, 158,079 barcode aliases, 511 migration-only models, and the
  import-only `Legacy Stock` brand. It also removed the migration-only model
  children: 1 image, 2,000 sizes, 1,294 colors, and 2 BOM rows.
- The purge aborted on any reservation, shipment, sale, order link, batch
  allocation, or non-import scan. Production preflight found zero blockers.
  A transactionally equivalent dry-run produced the expected retained state
  before the apply was allowed to commit.
- Current production contains zero UZERP warehouse-18 receipts, zero
  `legacy_stock` packages from that import, zero related finished-goods rows,
  zero related barcode aliases, zero migration-only models, and no
  import-created `Legacy Stock` brand. The original ERP state remains: 23
  ready-product packages, 1,340 pieces, and 881 real model records.
- Signed-in production verification shows `Paket qabulini kutmoqda (23)` with
  quantity `1340`, Models/PLM has 189 real groups, and filtering model number
  by `LEGACY-` returns no results.
- Keep the old ERP frozen and retain it as a read-only audit source. Do not
  delete or unfreeze it; no old-ERP ready-product data is currently imported
  into the new ERP.
- New compact process QR formats were introduced for easier scanning while
  retaining compatibility with old JSON QR labels.
- Payroll labels are separate from operational bundle/package labels.
- Package and bundle labels can show material/model pictures, traceability, and
  package weight.

## Access, Security, and Audit

Implemented security foundations include HttpOnly browser sessions, bearer
tokens for machine clients, role-based permissions, CSRF origin checks,
security headers, login/password-reset rate limits, global API rate limiting,
signed attachment URLs, authenticated model files, and hash-chained audit
records.

However, the latest deep audit on 2026-07-11 found 14 confirmed/reportable
issues: 8 High, 4 Medium, and 2 Low. Treat the system as high risk until these
are explicitly fixed and retested:

1. A single production-stage permission could complete or overwrite other-stage
   work orders.
2. Packages could mint finished-goods stock without packaging evidence.
3. `mark-shipped` could bypass mandatory package-scan verification.
4. Shipments could be marked delivered before shipping, including empty
   shipments.
5. Payroll scan trusted client-supplied quantity, rate, and scan identity.
6. Finance invoice creation accepted draft orders and arbitrary amounts.
7. Sales-order invoice generation allowed broad pre-delivery statuses.
8. Sewing bundle receiving did not enforce the current user's sewing-factory
   scope.
9. A real `.env` contained secret-like production configuration; active status
   was not verified.
10. Proxy-based rate limiting trusted forwarded client IPs without a configured
    proxy allowlist.
11. Mobile dependencies had moderate advisories.
12. Backend dependency audit flagged the `python-ecdsa` timing advisory.
13. Frontend lint had an impure `Date.now()` render path.
14. Backend Ruff checks found unresolved catalog type names.

The audit-history chain has repeatedly failed at record `#744` in daily
monitoring. Investigate this before treating audit history as tamper-evident.

Passwords and infrastructure credentials appeared in earlier chats. They are
not copied here. Rotate credentials pasted into chat and keep them only in
approved secret/environment locations.

The production Linux deployment credential needed for VM administration is
stored outside the repository under the current Windows account in Windows
Credential Manager, target `MilanaERP/production-linux-sudo`. Only this
non-secret target reference may be documented or used by deployment tooling;
the credential value must never be written to source code, Git, notes, logs,
or command output. Other credentials from the supplied infrastructure document
were intentionally not copied into the project.

## Monitoring and Management Reporting

An active daily automation runs at 17:00 Asia/Tashkent:

- Generates a 24-hour ERP activity report.
- Converts it into a non-technical Uzbek manager summary.
- Emails it to the authenticated Gmail account.
- Reports active work orders, finished goods, late orders, defects, waste,
  department output, stock receipts, user activity, and audit-history
  consistency.

Recurring concerns are the audit-chain inconsistency at record `#744`, active
work orders without downstream entries, bulk edits/approvals that inflate audit
counts, waste, shortfalls, and replacement work.

## AI and Integrations

- 1C finance sync uses the existing backend API with a shared integration token
  and stable external IDs.
- A Python Milana ERP MCP server exists for an AI GM assistant.
- MCP reads must go through existing FastAPI APIs and ERP permissions, never
  directly to the database.
- GM access is broad read-only; writes are limited to confirmed notifications
  and optional task creation.
- Every MCP action should be audited, secrets must never be returned, and bulk
  actions need guardrails.
- The MCP integration previously failed because an ERP bearer token expired;
  token refresh restored `erp_me`.
- AI planning/optimization ideas should begin in shadow mode: calculate
  recommendations without changing live production until explicitly approved.

## UX and Language Preferences

- Important UI text supports English, Russian, and Uzbek.
- Fix Cyrillic/Latin inconsistencies and mojibake instead of adding duplicate
  translations.
- Tablet and phone layouts matter because operators use smaller screens.
- Operational screens should be compact, aligned, and easy to scan.
- Use dropdowns/search pickers instead of raw IDs.
- Scanner pages need large inputs, clear states, Enter-key support, and a
  visible next action.
- Printing layouts must match the real paper/label size and avoid unnecessary
  branding.

## How Future Work Should Proceed

1. Inspect the current production release, database migration head, local
   working tree, and GitHub state before changing or deploying anything.
2. Preserve unrelated local changes.
3. Make the smallest exact change requested.
4. Do not create business data unless explicitly requested.
5. Do not deploy unless requested or clearly included in the task.
6. Use `DEPLOYMENT.md`, take a verified database backup, build both sides before
   cutover, keep rollback releases, and run all four health checks.
7. Never overwrite `/opt/milana-erp/current` before successful builds and
   migrations.
8. Verify permissions at both frontend and backend levels.
9. Test the affected end-to-end factory handoff.
10. Report what changed, what data was touched, active release, checks run, and
    unresolved work.
11. Never echo secrets into chat or documentation.

## Open or Unfinished Work

- Deploy or reimplement the sales-to-warehouse item-detail notification safely
  after reconciling the rollback.
- Verify which post-`20260723_065753` features are absent from production and
  restore only the intended ones.
- Import the user's Excel model catalog by grouping duplicate model names into
  variants; discussion occurred, but the workbook import is incomplete.
- Investigate audit-history chain failure at record `#744`.
- Fix and regression-test the high-risk findings from the 2026-07-11 audit.
- Confirm exact live sewing-line consolidation names before further changes.
- Validate old ERP QR-to-record mapping, then plan bulk import.
- Review and merge the production-source reconciliation PR, then separately
  classify the preserved local-only and non-production work before adding any
  of it to GitHub.
- After review, deploy the dependency-security update only through
  `DEPLOYMENT.md`; it is not part of the currently active production release.
- Establish tested database backup/restore, RTO/RPO, monitoring alerts, and
  retention policies.
- Add end-to-end browser tests for login, RBAC, sales order creation, scanning,
  shipment, and logout.

## Useful References

- `DEPLOYMENT.md` - only production deployment procedure.
- `README.md` - project overview and local setup.
- `docs/ARCHITECTURE.md` - architecture and trust boundaries.
- `docs/PRODUCTION_READINESS.md` - readiness checklist.
- `docs/SECURITY_RUNBOOK.md` - security operations.
- `docs/DISASTER_RECOVERY.md` - backup and recovery planning.
- `docs/DEVELOPER_GUIDE.md` - codebase walkthrough.
- `docs/training/` and `output/pdf/training/` - department training material.
- `.codex-work/deep-security-quality-audit/final/` - latest deep audit evidence.
- `scripts/erp_daily_monitor.py` - daily management report source.

## Update Rule

After a significant ERP task, update only the affected sections and refresh the
date. Record the active production release and any rollback. Keep this as a
concise source of truth, not a transcript.
