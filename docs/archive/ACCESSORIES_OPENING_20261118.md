# Milana Accessories opening inventory, 18 November 2026

Status: applied to production; persisted quantities, ledger and audit verified.

The owner requested review of eleven named local workbooks and then instructed
“Do it” for the proposed catalog separation and opening inventory. Confirmed:
use only `КАРТАЛАР 2026` (includes carryover); packed tapes count rolls/bundles,
not metres; ambiguous piece/pair lace stays pending; button sizes 24/44/48/54
are ligne. The separately labelled 11.3 entries retain the source mm convention.
The owner expressly approved using the verified current production baseline
instead of stale `origin/main` for this task. The owner subsequently approved
provisional zero valuation: “Yes proce is not necessary”. Approval is retained
in the private receipt and bound to the reviewed manifest.

Scope: existing Milana `Accessory Storage`, warehouse 2 / department STR only.
Warehouse 12 `Aksesuar` belongs to ECO and is excluded. Preserve all three
existing accessory items; the read-only snapshot found no accessory batches.
No deletion, migration, permission change, application source modification,
application deployment or physical shelf relocation is included.

Production: both hosts verified release `20261116_130518`, manifest
`bc2e0d4bdbb38f6c06b9f3d5c75f3fdaa1fb5087240ca8f7b49d01318908ce40`.
Both full source-manifest checks passed. Database head is
`0157_package_allocation_items`. Worktree base is exact runtime commit
`4d7cf17e55b165b1edc05407065f92597cebdbe5`, dedicated branch
`codex/accessories-opening-20261118`.

Inventory business owner: Ismail; default human reviewer: Mirshoir.
Implementation coordinator: root Codex session. A separate Codex agent reviews
this bounded data operation as required by AGENTS.md; this is not a claim of
human acceptance or a refactoring task.

The deterministic builder reads all cells/formulas using a restricted arithmetic
parser, reconciles cached/net balances, hashes all original files and excludes
template/photo-only rows. It keeps 45 ambiguous source rows pending and excludes
20 older card rows. Reviewed plan: 792 item masters, 759 positive receipt batches,
51 zero-balance source rows producing no receipt. Exact coded thread/tape and
elastic identities can share an item while source rows remain separate batches.
Generic repeated lace/button/zipper/bag descriptions remain pending. Floating or
reused photos are not attached without physical matching.

Product families are searchable name prefixes and SKU namespaces under the
existing `accessory` / `packaging` categories; no new subgroup UI is claimed.
Actual metal buttons use the button family in their visible names. Units retain
kg/metres/pieces/bundles; no unsupported kg-to-piece or roll-to-metre conversion.
Source provenance and provisional valuation appear in batch notes and audit.
Opening receipt timestamps reflect import time; historical dates stay evidence.

Operation path: original files -> `ops/build_accessories_opening_20261118.py` ->
private `outputs/accessories-opening-20261118/manifest.json` -> exact-source SSH
runner -> current input DTO/access guards -> existing schema-owned item/receipt
writers and normal audit hooks, one outer transaction. No runtime files change.

Required gates before apply: source tests; read-only live collision/scope checks;
verified PostgreSQL custom-format backup; isolated restored-copy PostgreSQL
refusals, fault rollback, full rollback, apply, readback and duplicate retry;
independent AI review; committed operation bytes; explicit valuation decision.
Post-apply: persisted exact quantities/movement/audit checks, preservation of old
accessories, real connected-browser inventory readback and four health checks.

Private source manifest, source hashes, pending-row report, backup receipt, QA
receipt and apply/verify receipts stay in ignored outputs. A pending list is
provided to the owner; these rows cannot silently create stock.

## Preparation evidence

- Eight independent source-control tests pass; all four scripts compile.
- Restricted AST parsing rejects executable expressions and unsupported syntax.
- Read-only live inspection passed source, schema, actor, warehouse, duplicate
  SKU/name and existing-stock guards. No existing record is reused or removed.
- Verified PostgreSQL backup:
  `/opt/milana-erp/shared/backups/milana_erp_pre_accessories_opening_20261118_104029.dump`,
  131,247,840 bytes, mode0600, 1,400 restore objects, SHA-256
  `b0f90cc7ec27eccb3ee4937b8ec3fb1402833f149765f4939910ded6d967767d`.
  Restore-list SHA-256 is
  `ffaa3be5afef3fc30f6277bfe73411b7e4b003ec9fe234e12b09e10a3b45210f`.
  Apply requires a matching, reverified backup at most30minutes old.
- Independent agent `/root/accessories_review` verified the frozen source hashes,
  all eight tests, compilation, complete rebuilt-manifest equality and refusal of
  altered manifest data before database access. It found no remaining blocker in
  the bounded files after four corrections: pending uncoded duplicate tape,
  normalized formula syntax errors, exact manifest/source evidence binding and
  backup freshness/binding. This is technical review, not human acceptance.
- Reviewed manifest SHA-256:
  `5d0d727e6b3032c0d24aa7550e5a3778bc1b7a67e8f5809690c387a86189a30d`;
  canonical content SHA-256:
  `8a74887a8c8449adb72528849b0b9c3ce2350439cb7c858fa8afd3ae2bfbf5d6`.
- Frozen builder/importer/runner/test SHA-256 respectively:
  `38f32e637228f5a0077b97c0ef130e25830b453de7a5d8b2ba54c28f8d400c6b`,
  `fed6c4757408cabb339892f2ef202c03c44d7c918c5d06588e81df8023d7a19c`,
  `5993c78c74f6db58ca4329070a4008f9130c74b7134d002d4d7c0295bda40a5a`,
  `2dbae422f968c7b7430f2ff513ddd91d88f3f82d5ca2665f17857098518b7f7d`.

Connected Edge browser visually confirmed the production Accessory Inventory
page and the existing System Admin / Super Admin session before import.
Restored-copy PostgreSQL QA passed: wrong valuation approval, wrong SHA and an
altered quantity were refused; a deliberate fault after three receipts rolled
back all created rows; full rehearsal rolled back all rows; actual private-copy
apply/readback produced792 products,759 batches,759 receipt movements and1552
valid linked audit entries. An identical retry changed nothing; the pre-existing
accessory fingerprint remained identical. The private PostgreSQL container was
removed after the run. This initial rehearsal preceded the production apply below.

Two earlier private QA harness failures are retained in the task history: the
operator could not read the protected production env file, and a restore briefly
hit PostgreSQL's temporary initialization socket. The corrected harness uses
only its private database URLs and waits for final TCP readiness; independent
review covered this final runner delta. No production environment access was
weakened and no production business row was used as a test write.

Independent agent re-read the final private QA receipt (SHA-256
`9681d16adad218bfaf984b8bf83d14cf59f3c6318fce88377818eed9472dffc4`)
and confirmed technical preparation. A final live read-only inspection still
returns ready/no imported namespace and the same pre-existing-accessory
fingerprint. All four internal/public health/login checks returned HTTP200.
These preparation checks preceded the owner's valuation decision and the fresh
backup/QA/apply below; they do not describe the final production state.

## Production apply and closing verification

The approved operation at commit `0683fcf408bf2e11d91e5ee978562603c21faea9`
was applied once through the guarded runner. Its source bytes and reviewed
manifest did not change. A new backup replaced the preparation receipt for
the freshness gate:

- `/opt/milana-erp/shared/backups/milana_erp_pre_accessories_opening_20261118_105126.dump`
- 131,304,828 bytes, mode0600, 1,400 restore objects.
- Dump SHA-256 `933e13458bbbed051966f649e63fcbd7018517889080bb3f4a4f568c002ae612`.
- Restore-list SHA-256 `6c42452aa70152e67977a4c1d7dec303b7a8e6896a6a51ce931b5491b8780607`.

The complete isolated restored-copy refusal/rollback/apply/readback/retry QA
passed again against this backup, and its temporary database container was
removed. Live apply returned `applied:true`, completion audit281388,792 new
products,759 positive opening batches and759 receive movements. Subsequent
read-only verification found exactly1552 linked audit entries and all expected
quantities. The existing accessory fingerprint remained
`bbfe9e388efc46d3d75eb7ffe87140beb35a1556bb16bbc38f0ce0842a4106c7`.
The verify receipt's `already_applied:true` is detection of that completed
operation, not another stock write.

| Family | Unit | Quantity | Batches |
| --- | --- | ---: | ---: |
| Bags | kg | 9,744 | 17 |
| Buttons | pcs | 5,660,900 | 118 |
| Elastic | kg | 2,260 | 7 |
| Lace by metre | m | 357,395.50 | 93 |
| Lace pieces | pcs | 24,250 | 6 |
| Metal accessories | pcs | 416,100 | 24 |
| Cards / tags | pcs | 1,442,200 | 12 |
| Tapes by metre | m | 284,284.84 | 69 |
| Sewing thread | pcs | 22,296 | 187 |
| Packed tapes | bundle | 15,975 | 47 |
| Zippers | pcs | 166,900 | 179 |

The connected Edge browser reopened live Accessory Inventory. Searching elastic
showed all seven positive batches; a focused3cm search showed separate450kg
and258kg batches of the same item, zero cost, Pending QC, warehouse Accessory
Storage and workbook/sheet/row provenance. Screenshot:
`outputs/accessories-opening-20261118/live-inventory.png`. Captured console
warnings/errors were empty. Existing UI limitation: the item-types badge shows
500 because its item list is capped; persisted counts were independently verified.
No UI repair or deployment is included in this data task.

All four internal/public backend health and frontend login checks returned200
after import. Both source releases and manifests remain20261116_130518;
schema0157 is unchanged. The previously recorded rollback release20261116_092917
was untouched. Protected slot-state access was unavailable to this operator;
no fresh privileged slot-state read or traffic switch is claimed.

45 ambiguous rows remain in the private `pending-review.md`;20 historical card
rows were excluded;51 zero-balance rows generated no receipt. Unmatched photos
and physical shelf relocation remain outside this completed import. Receipt
dates reflect18November; source dates remain evidence. QC remains pending and
zero valuation is provisional. No existing stock, BOM links, permissions,
orders, payroll, runtime files or application release were modified.

Independent reviewer `/root/accessories_review` subsequently checked the local
approval, fresh backup, QA, apply and verify receipts against the committed
operation and reviewed manifest, including equal IDs/totals,1552 audits and
unchanged fingerprint. It independently inspected the screenshot and found no
blocker for this bounded operation. Technical state is
AI_VERIFIED_AWAITING_HUMAN; human stock identification/acceptance is not fabricated.
Owner visual checklist: confirm family names/units and source opening quantities,
identify the45 pending rows, match photos physically and assign shelf locations.

Durable context was mirrored to the owner's Obsidian project note. The dedicated
worktree is `C:\ERP\.codex-work\accessories-opening-20261118`, branch
`codex/accessories-opening-20261118`; the operation commit was pushed, not merged.
No application deployment occurred.
