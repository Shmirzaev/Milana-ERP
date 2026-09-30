# Old ERP catalog reconciliation — 30 September 2026

The production catalog was updated additively from a fresh authenticated old-ERP capture. This is not a claim that every historical source inconsistency has been resolved: configured processes, existing identities and production links remain authoritative, and ambiguous source links are preserved for review.

| Result | Count |
|---|---:|
| Source model masters reviewed in list | 3,289 |
| Source variants reviewed in list | 5,964 |
| Relevant masters with full detail capture | 323 |
| Missing variants created | 220 |
| Standalone model created (PB10014) | 1 |
| Existing records enriched | 1,654 |
| Existing empty paid-process lists restored | 432 |
| Paid processes added to those existing records | 17,744 |
| Paid processes on new records | 5,330 |
| Size rows added | 2,656 |
| Color rows added | 306 |
| Image links added | 443 |
| Original image files verified | 247 |

New records are drafts. Of the 221 new records, 105 also have no operations in the source; no rates were invented. Source operation order, names, rates, currency, duration, stage, control direction and final-operation flags were retained. Recipes remain source documentation rather than invented inventory/BOM links. Existing populated operation lists, model names/codes, images and production links were preserved. All eight records belonging to TJ2189/V-4776, PJ1013/V-3846, PJ1118/V-2922 and BJ5007/V-2235 remain separate and unchanged.

## Numbering

The live variant counter is 6427 and the live next-number preview is **V-6428**. Model-prefix counters were calibrated from the newest old-ERP master in each prefix. The reviewed application change adds server-reserved model numbers per prefix and checks occupied legacy codes and identity metadata. It ignores historical outliers such as variant 43891 and model XJ7641. Preview reads do not consume a number; creation reserves it transactionally. The application change is deployed in release `20260930_141107` from commit `b4277bbe55f10e2db45f46425c973d8d8a5220ee`. Verified previews are XJ3201, PJ1253, KJ13051 and V-6428.

## Source exceptions

XJ3184/V-5968 and V-5969 have two source masters with the same mold 4667 but different products (buttoned versus zippered robe); they remain unchanged pending a source choice. Other unresolved links below already have catalog identities and remain unchanged. Source V-5889 has the invalid all-zero model number and was not created. Historical master labels that conflict with the actual variant catalog, or describe noncanonical slash/clone identities, were held rather than introducing ambiguous records.

| Source identity | Reason held |
|---|---|
| XJ3184/5969 | source master unresolved |
| XJ3184/5968 | source master unresolved |
| 00000000/5889 | invalid source identity |
| TJ2194/4916 | source master unresolved |
| TJ2194/4915 | source master unresolved |
| TJ2194/4840 | source master unresolved |
| TJ2194/4839 | source master unresolved |
| TJ2010/4778 | source master unresolved |
| TJ2010/4336 | source master unresolved |
| TJ2010/3764 | source master unresolved |
| TJ2010/3721 | source master unresolved |
| TJ2010/2864 | source master unresolved |
| TJ2010/2863 | source master unresolved |
| TJ2010/2862 | source master unresolved |
| TJ2010/2861 | source master unresolved |
| TJ2010/2860 | source master unresolved |
| TJ2010/2859 | source master unresolved |
| TJ2010/2858 | source master unresolved |
| TJ2010/2830 | source master unresolved |
| TJ2010/1588 | source master unresolved |
| TJ2010/1 | source master unresolved |
| TJ2010/2 | source master unresolved |
| TJ2010/149 | source master unresolved |
| TJ-2026/2 | noncanonical historical master label |
| TJ-2017/1 | noncanonical historical master label |
| TJ-2016/1 | noncanonical historical master label |
| TJ2146 - clone | noncanonical historical master label |
| PJ3044/1599 | master label conflicts with variant catalog |
| XJ3062/5890 | master label conflicts with variant catalog |

## Verification and handoff

- Exact readback passed for all 1,875 plan targets, every appended size/color/image, and every image file hash. All 7,433 original names/codes and all eight duplicate-record detail hashes were preserved. Final counts: 7,654 models, 31,418 sizes, 5,885 colors and 19,240 image links. BOM remains 442 rows.
- Authenticated production UI showed imported PM7015/V-6424, its six sizes, image, source general details and paid-process rates. No orders, stock, packages, shipments, payroll records, users or permissions were created or modified by this import.
- All four internal/public health/login checks returned 200. At import verification, active green was `20260930_053552`; no application deployment or schema migration occurred during the import. Subsequently deployed blue `20260930_141107`, with green `20260930_053552` retained for rollback; database revision remains `0133_storage_customers`.
- Full backend regression suite: 1,087 passed. After final importer refinements, all nine numbering/import regression tests passed. Scoped Ruff, strict TypeScript, frontend contract checks and production build passed. Frontend lint has four pre-existing unused-symbol warnings in the department page.
- Worktree: `C:/ERP/.codex-work/catalog-parity-20260930`. Branch: `codex/catalog-parity-20260930`. Implementation commit: `2a609e93e57d8f57418ebb1acf8ce4af4e3cfc1f`. Pushed and merged through PR #242; deployed from merge commit `b4277bbe55f10e2db45f46425c973d8d8a5220ee`. Release CI passed 1,088 backend tests, frontend checks/build and database/observer regressions. Signed read-only browser QA, performance gates, all four health checks and the full 30-minute observation plus closing checks passed. Deployment did not repeat the import.
- Plan SHA-256: `1da7926f469cfc8f6d6f766b782ebf72b0c01aa5cc95b363ab6cb180309f0a60`. Bundle SHA-256: `59079f4ca0c295f366120efa6495780930bb0409fae4f16bc76bb0f4697d5ba0`. Production evidence directory: `/opt/milana-erp/shared/catalog-parity-20260930-v2`; local evidence under `outputs/reconciliation/`.
- Verified backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260930_130105.dump` (59,523,374 bytes, 1203 restore objects), SHA-256 `185eac054bd612097165d00110ef51f9a76b5827da7cf706da72c836c32805fe`.
- A dry run detected UTF-8 corruption in the initial large textual snapshot transfer. Nothing was applied from that plan. The snapshot was re-transferred as compressed bytes; the rebuilt plan passed dry run and exact post-import hash verification.
