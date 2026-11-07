# Independent review: root Warehouse and Passport changes, 7 November 2026

Reviewer: Codex worker `/root/pack_two_nastils`. Implementer: root Codex agent.
Human domain owner: Mirshoir; human reviewer: Ismail; operator acceptance: Shavkat.
This independently reviews user items 2/7/8 only. The worker's Packaging code is
excluded from this review and is not approved by its author.

Reviewed source: root's uncommitted candidate in
`C:/ERP/.codex-work/ect-warehouse-workflows-20261107`, based on
`b21b51e6c6112a9c181853b8646944de7416ee8b`. File hashes below identify the actual
reviewed content; this is not an approval of later changes or an unidentified
combined revision. Root files were read only; reviewer changed only this note in
the reviewer's separate worktree.

## Verdict

**No remaining source blockers in the reviewed item 2/7/8 candidate.** Initial
findings were reported, accepted and fixed by root, then independently checked.
This is a scoped independent source/test review, not human acceptance, a merge
authorization, deployment authorization, or a claim that every combined browser
gate has been completed. Root owns final combined checks and browser evidence.

## Findings and re-review

| Finding | Original evidence | Fixed behavior and result |
| --- | --- | --- |
| P1: historical dispatch silently omitted | No frozen document; ShipmentPackage20, original PackageItem20, fully consumed dispatched counters20 produced zero report rows. Reproduced in disposable SQLite. | `_historical_documents` bulk-reads authoritative ShipmentPackage quantities, customer/order/model metadata. It does not use current remaining quantities; unknown historical sizes remain explicitly unknown. Reproduced20 is retained, labeled historical, with `sizes={"—":20}`. PostgreSQL recheck PASS. |
| P2: displayed variant search failed | Raw3372 returned a row while displayed V-3372 returned none. | V-3372, SJ4044-V-3372 and SJ4044/V-3372 normalize to the existing model/variant search representation. Regression and independent PostgreSQL checks PASS. |
| P2: map handoff selected unrelated source | URL exact model changed only match decoration; full-cell candidates auto-selected another variant. | Source candidates now intersect exact model and applicable query; unrelated source cannot be auto-selected. Full placements remain available for target occupancy/mixed-model refusal. Source review PASS. |
| P3: date upper overflow | Valid date_to9999-12-31 raised OverflowError. | date.max treated as unbounded upper bound. Lower date.min underflow was separately reported and corrected similarly. Both extremes independently checked on PostgreSQL, PASS. |

Authorization review found no new permission bypass: report JSON/Excel both use
existing storage.packages/storage.shipment permission checks; the scope follows
the existing global warehouse inventory/report behavior. No financial fields or
business writes are exposed. Existing frozen dispatch lines, including partial
pack quantities, remain authoritative. Excel user text is forced to literal
string cells; no spreadsheet formula injection was observed.

The primary stock workspace structurally matches the user reference: shared
search/factory/date filters, map on the left, stock on the right, exact variant
selection restricts list/map counts, and location actions remain reachable. The
Passport Open action targets its existing linked production order. This source
review does not replace inspection of actual browser screenshots.

## Independent checks actually executed

1. Root feature tests:
   `C:/ERP/.venv/Scripts/python.exe -m pytest -q app/tests/test_warehouse_shipment_report.py`
   from root/backend: **5 passed**. Targeted Ruff on report route/DTO/service/tests:
   **PASS**. Ordinary existing test deprecation/fixture-secret warnings remained.
2. `node scripts/test-warehouse-workspace.mjs` from root/frontend: **PASS**.
   Exact variant/query/location intersection, sibling/prefix controls and access
   to the last option of a2,500-row synthetic collection are covered. This is a
   pure helper test, not a DOM/browser lifecycle check.
3. Independent PostgreSQL check against the worker-owned disposable PostgreSQL16
   container `milana-multi-nastil-pg-20261107`, loopback15567, database postgres.
   A random review-only schema was created, populated, tested and dropped.
   No production host, production database or existing local business rows were
   queried or mutated. No credentials were needed; this server uses local test
   trust authentication.
4. At500 frozen shipments on the Tashkent midnight boundary: **500 rows,
   5,000 pieces,500 package dispatches,500 shipments,50 rows in the first page**.
   Exactly **one SELECT** for this frozen-only read. Original review sample was
   **22.77ms**; final fixed-source sample was **12.66ms**. These local samples are
   bounded engineering evidence, not production performance-budget acceptance.
5. PostgreSQL independently verified displayed-variant query forms, both maximum
   date boundaries,501-row Excel including its header, and a literal
   `=Review client` string with cell type `s`.
6. PostgreSQL fully consumed legacy package20 without a frozen document remains
   in the report with link quantity20, one package, one shipment, historical flag
   and unknown size. All report sessions remained clean (`new`, `dirty`,
   `deleted` empty). Owned schemas were dropped in `finally`.

Reproducible local script (ignored test artifact, not deployable source):
`C:/ERP/.codex-work/pack-two-nastils-20261107/.codex-work/review-root-warehouse.py`.
Its exact result/hashes:
`C:/ERP/.codex-work/pack-two-nastils-20261107/.codex-work/review-root-warehouse.json`.
Run from the reviewer's worktree with
`C:/ERP/.venv/Scripts/python.exe .codex-work/review-root-warehouse.py`.
The script hardcodes only the disposable loopback15567 server, forces application
DATABASE_URL to in-memory SQLite before imports, and drops only its own UUID
PostgreSQL schema. This note is the only review artifact committed for porting.

The parent reports actual connected-browser checks for stock exact-variant115
pieces -> selected-cell60 pieces and report V-3372 ->20 with downloaded XLSX.
Those are **parent-owned evidence**, not independently witnessed by this worker.
Root still owns final screenshot inspection, integrated persisted readback and
all remaining combined gates. Human acceptance remains pending.

## Reviewed SHA-256 identities

| Root-relative file | SHA-256 |
| --- | --- |
| backend/app/models/fulfillment/shipment_report_service.py | a4e56a34aaa755039da66a5491cdf77bf3172278e2aa4decfba89e8318e3b0f2 |
| backend/app/libs/dto/fulfillment/shipment_report.py | 689a0bf5d9bd2396090765301ae7833a65e823c86b887b774acd6813520c822a |
| backend/app/api/routes/warehouse_reports.py | 8d5f0c381bb9e954758fb79e58b472d0815192df0f1d360377dc790ecf3fa666 |
| backend/app/tests/test_warehouse_shipment_report.py | 656071981078e8716ff704c7dda00b052e5a6117791875154d6297a12ea6a7bd |
| frontend/src/app/(app)/warehouse-map/page.tsx | 4eb1600157cb0dec3d7da34a11143b45aa31a177fc9cab539c9dbc32099261a2 |
| frontend/src/app/(app)/warehouse-stock/page.tsx | 077c3df10ad58e9dcfacbd942ffaf1161514964e6ef05cdaef9a80c36f4d9a1c |
| frontend/src/components/WarehouseStockMap.tsx | 273be61e00c53417274bfefd1f8ba33d7854142d23f414b4046968d0a0d6e50c |
| frontend/src/lib/warehouseWorkspace.ts | ae74166031e18f20f209f862e31d75397b62c1f1db6c5207d4af593d17bf03cb |
| frontend/src/app/(app)/warehouse-stock/shipments/page.tsx | 8e2b6e176afc66df4359fcf264dfcb1b658537f7ed37920421f601e4a169d533 |
| frontend/src/app/(app)/cutting-passports/page.tsx | 449fbaf1b490db3b19df076b3773d2486436de27b952f3a4a2a617d39ea96979 |
| frontend/src/components/Sidebar.tsx | 2e7024f921efcdec30387b97fa47a453ce1fc1d2ee6c6d1bc14ad0773b6c0c57 |
