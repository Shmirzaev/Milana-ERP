# ECT receiving and same-fabric batch lookup — 7 November 2026

Status: IMPLEMENTED_AUTOMATED_CHECKS_PASSED; actual-browser/persisted UI readback,
PostgreSQL concurrency and independent review remain pending combined verification.

## Direct scope and ownership

User asks (1) accessory receiving as a table, shared supplier and arrival date,
per-row Type/Name/quantity/unit/batch; plus or Enter adds another; equivalent fabric
receiving with commonly used Milana details, and (3) fix same-fabric/different-lot
batch selection failing to find fabric from inventory. User approved verified
origin/clone_main baseline. No production/business-data mutation or deployment.

Engineer: Ismail. Human reviewer: Mirshoir. Business acceptance: Shavkat/operator.
Implementation: Codex /root/ect_receiving in dedicated worktree
C:\ERP\.codex-work\ect-receiving-20261107, branch codex/ect-receiving-20261107,
base b21b51e6c6112a9c181853b8646944de7416ee8b. Root independently reviews/combines;
root owns passport frontend Open-order/filtered-picker URL and shared context.

## Studied operation, callers and tables/types

ECO page -> EcoReceiptForm -> /eco-inventory/receive-bulk -> eco_inventory_service
-> eco_inventory_persistence -> eco_material_batches/eco_material_movements.
One outer transaction and one actor/factory-scoped idempotency receipt cover the
whole table; failure rolls back the supplied Session through request cleanup.
Single-row /receive stays compatible and delegates the same participating writer.
Catalog Item lock and category/activity/unit checks remain authoritative; supplier,
ECO warehouse, ECO order, image URL, QC, roll sum/count and decimal validation
remain checked before commit. No migration, catalog creation or central stock write.
Audit/idempotency retain their existing schema-owned writes and same Session.

Input EcoMaterialReceiveLineIn keeps canonical EcoMaterialKind/EcoReceiptSource/
StockBatchQcStatus; bulk input bounds 1–100 rows. New EcoCatalogCategory is the
four existing catalog values allowed by the ECO picker, returned by item DTO.
Item.category storage and unrelated DTO consumers remain unchanged legacy strings;
unit, batch, colors, names/processes are configurable data, not new enum policy.
Existing eco receipt metadata/JSON and schemas retain their values/types.

Passport split page -> authorized material-batches route -> list_passport_fabrics
-> scoped central list_batches and authoritative transferred ECO source mapping.
Global result had a 500-row cap followed by client compatibility filtering, hiding
older valid lots. Optional positive item_id applies before that cap, including the
transferred receipt query. It never converts ECO row IDs into central batch IDs,
changes consumption, bypasses factory/order permission, or offers linked held/empty
ECO receipts through central fallback. Root appends exact target item_id for split
picker only. General add-material search remains available. Each query stays capped
at 500; a future same-fabric set over 500 uses batch-number search (not unbounded load).

## Read-only production evidence

Production baseline/release verified by coordinator: green 20261107_043754.
Worker GET/SQL-only inspection on active milana-backend-green used SET TRANSACTION
READ ONLY and rollback. No names, credentials or individual business rows copied.
1,550 fabric/semi-finished batches; populated fields: supplier 1,506; rolls/count
1,510; image 1,129; color 824; color code 758; GSM 614; color status 276; old code101;
processes28; length15; width0. Warehouse/date/cost populated in all1,550 (nonnull
zero cost is not evidence of meaningful pricing). Active fabric Items78; largest
active same-item batch group218. Fabric table emphasizes count/color/code/GSM/photo;
width, length, old code, status/processes and cost/QC remain expandable per-row details.
Shared supplier/date/warehouse/document/order/source are entered once.

## Evidence and open gates

- PASS: 39 focused backend cases: new atomic receipt tests7, new picker regression1,
  existing inventory/transfers23, existing transferred-ECO/cutting8.
- RED then GREEN: picker fixture adds501 newer unrelated lots. Before fix, item_id
  query still returns unrelated fabric; after fix older source lots appear with
  only the requested item. Final fixture asserts required lots as a subset because
  pre-existing same-fabric seeded stock also legitimately appears.
- PASS: frontend strict types; scoped ESLint; existing ECO table/retry/locale tests.
- PASS: new UI behavior script renders EN/RU/UZ fabric/accessory tables, fills two
  rows, Enter adds without receipt submission, removes a row, checks one shared
  header and distinct lots/quantities, exact0.1+0.2 roll total and optional lengths.
- PENDING: real PostgreSQL replay/race, bounded100-row receipt, actual connected
  browser desktop/tablet, save/reopen/database effects, target old-lot selection,
  independent review and human checklist. No unrun gate claimed PASS.

Human checklist: receive two accessory lots and two fabric lots with common supplier/
date; check separate balances/history and batch-local details/photos; add with + and
Enter; remove row; verify m/kg and roll totals, failure correction and lost-response
retry; select same-fabric older batch in a passport; incompatible color/unit/dimensions
still refuse; transfer-owned stock remains ECO-backed. No production QA writes.
