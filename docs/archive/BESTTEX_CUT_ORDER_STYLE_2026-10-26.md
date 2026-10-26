# Besttex Cut orders: grouped factory-table style

26 October 2026. Implemented in `C:/ERP/.codex-work/besttex-cut-orders-style-20261026`, branch `codex/besttex-cut-orders-style-20261026`. Base `0b820c5f` records live application `d187959565821cadde420809a602426caee9ac42`. Both live roles, immutable images and retained blue rollback were reverified before editing. Production remains green `20261026_045639`; blue `20261024_093619` remains rollback. This follow-up is not deployed or merged.

Business group: Production, with catalog photo presentation. Team ownership remains Mirshoir / reviewer Ismail for Production and Ismail / reviewer Mirshoir for Catalog. Codex implemented the owner-requested follow-up; an independent AI reviewer completed two scoped reviews with no actionable findings. This is technical evidence, not claimed human engineering review or operator acceptance.

## Change

Cut orders now follows the existing factory table: compact yellow rows, planning-order group headers, model and variant thumbnail columns, separate business numbers, sizes, material, cut/passed counts, date, deadline and the existing print action. Page-local group summaries state their scope explicitly. Search includes the displayed planning-order reference and name. Existing paging remains bounded.

The list DTO gains additive presentation fields. Page models/photos are fetched in batches using existing family garment and exact-variant selectors. Image binary data is deferred with raiseload; absent or mismatched variant pictures stay empty. Existing thumbnail/preview links are reused. Only GET list and print operations remain available; factory/record/batch authorization is unchanged. No schema, permission, stock or manufacturing-data migration is introduced. No refactoring files or dirty legacy-checkout changes are included.

## Verification

- PASS: 19 Besttex API cases, including family/exact-variant images, missing/mismatched variant, group-reference search, letter/numeric sizes, no image binary reads, existing access denials and read-only print behavior.
- PASS: 18 existing model-photo/projection/query-growth cases.
- PASS: scoped Ruff and ESLint, TypeScript, all 3,427 EN/RU/UZ translation keys, full frontend contract/build chain and optimized webpack build. Turbopack local preview rejected the external dependency junction; webpack was used successfully. No dependency or product configuration was changed for that local tooling constraint.
- PASS: actual candidate UI against isolated local SQLite and files, signed in as a permission-only Besttex reader. Inspected desktop and phone screenshots; verified both thumbnails loaded, grouping, BSO search, empty results, EN/RU/UZ, horizontal table scrolling without widening the page, and the print button opening the expected sheet popup. Zero page console errors. Blob popup visual inspection remains unavailable under browser policy; no workaround was attempted.
- PASS: bounded read challenge after visual QA: 80 GET requests, maximum concurrency 4, timeout 5 seconds, predeclared p95 bound 1,000 ms and zero expected errors/writes. Actual median 43.91 ms, p95 69.75 ms, recovery 12.05 ms, zero errors and all 96 business-table fingerprints unchanged. Disposable local fixtures only; no production load or factory transactions.
- NOT APPLICABLE: new locking/constraint migration checks; this change adds read projections only. No new PostgreSQL migration exists.

Evidence and screenshots remain in ignored `outputs/style-preview/`, including the build log, read-load plan/result and `cut-orders-desktop.png`, `cut-orders-phone-uz.png`. Local QA processes are stopped at handoff. No files, releases, backups or business data were deleted for this follow-up.

Human/operator acceptance and production deployment remain pending. Existing production baseline and blue rollback have not been changed.
