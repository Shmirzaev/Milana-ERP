# Besttex Cut orders: grouped factory-table style

26 October 2026. Implemented in `C:/ERP/.codex-work/besttex-cut-orders-style-20261026`, branch `codex/besttex-cut-orders-style-20261026`. Base `0b820c5f` records live application `d187959565821cadde420809a602426caee9ac42`. Both live roles, immutable images and retained blue rollback were reverified before editing. Production is now blue `20261026_055538`; green `20261026_045639` is the running rollback. This follow-up is deployed without an integration merge.

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

Evidence and screenshots remain in ignored `outputs/style-preview/`, including the build log, read-load plan/result and `cut-orders-desktop.png`, `cut-orders-phone-uz.png`. Local QA processes are stopped at handoff. No retained release files, backups or business data were deleted. Approved deployment-only replacements are recorded below.

Human/operator acceptance remains separate. Deployment completion is recorded below.


## Deployment completion (2026-10-26)

- Both roles are blue `20261026_055538`, activated at 06:38 UTC, exact application `dc8d1aea60ace79ff15dfb1900a1b96b2e5108f6`. Previous green `20261026_045639` / `d187959565821cadde420809a602426caee9ac42` remains running and verified for rollback. Current symlinks, runtime slots, source hashes and immutable image IDs agree. Source manifest: `a9354a9f08cfc1f9e72c4362796330509f57adbe3368b46aa1806a0c95305a12`. No refactoring or dirty legacy-checkout changes were included.
- Cut orders now uses grouped factory-table headers, compact rows, separate clickable model/variant thumbnails and business numbers, sizes/material/deadline, cut/passed quantities and the existing print action. Named Besttex access remains read-only and factory/record/batch scoped. No permission, schema or business-data change; Alembic stays `0149_besttex_cutting_access`.
- Exact immutable CI [40276930267](https://github.com/Shmirzaev/Milana-ERP/actions/runs/40276930267) passed all jobs, including full backend, explicit PostgreSQL suites, frontend lint/types/browser/contracts/build. Local full backend, 37 focused/photo cases, lint/types/i18n/build, independent source/ops reviews and local EN/RU/UZ desktop/phone QA passed. Bounded local challenge (80 GET requests, maximum concurrency 4) had zero errors and 96 unchanged business-table fingerprints.
- Signed candidate/public read-only QA verified actual grouped records, model/variant thumbnails, search, print action and zero console errors. All four health checks, valid HAProxy, two workers, zero restarts/OOM, clean logs, PostgreSQL headroom and zero invalid indexes passed. Paired and public closing performance used 120 samples per fixed query, identical result counts and unchanged latency/payload budgets. No timed monitoring was run, as explicitly waived by the owner.
- Fresh mode-0600 backup `/opt/milana-erp/shared/backups/milana_erp_pre_20261026_055538.dump`: 91,777,938 bytes, 1246 restore objects, SHA-256 `1502ed12a5dc4ffde70b4b5cb6ddf6e2bffca8404b781f8cf9ca77435a2524d3`. Restore-list SHA-256 `23a430d4cce34d9d562061f747343b4e01e402d2be72a4877430b9844c2620b1`. Active/rollback sources/images, older releases, uploads, volumes, backups and manufacturing data remain retained. Only the owner's explicitly approved inactive-container and deployment scratch replacement/cleanup was allowed; no disk cleanup was performed for this follow-up.
- Technical details, immutable digests and rollback commands are in this deployment record. Application/record branches are pushed, with no integration/refactoring merge. Temporary read-only QA gateways were stopped; human factory acceptance remains separate.


- Backend image: `ghcr.io/shmirzaev/milana-erp-backend@sha256:446627531235002362dedf08d33e3dc6de49150a05de42881d183d1ac8927c5a`
- Frontend image: `ghcr.io/shmirzaev/milana-erp-frontend@sha256:7c749b03f624422142b0b68eebfa39c4b702f77aadaac85bf983045908937cd9`
- Source archive: `be1a1a9eda8271f6dd5dd9b01458000d6a8ba1e40b1ff663df90d26239426fef`; 1436 exact Git files verified on both VMs.
- Application commit: `dc8d1aea60ace79ff15dfb1900a1b96b2e5108f6`; CI run `40276930267`.
- The Cut orders projection intentionally adds requested display metadata: 30 rows now use 20,574 bytes (previously 8,077); photo binaries are fetched separately. The five existing search/inventory benchmark payloads are unchanged.
- Closing disk usage: backend 75.65%, frontend 72.75%; no disk cleanup was needed.
- Local full backend result: `3883 passed, 313 skipped, 12 warnings in 609.81 seconds`. PostgreSQL CI evidence is recorded separately; required skips were not treated as passes.
- Exact deletion authorization: Replace only inactive milana-backend-blue and milana-frontend-blue containers from 20261024_093619; automatically remove this deployment temporary migration container and HAProxy validation files; normal routing/current-symlink updates. Keep current green 20261026_045639 running for rollback and retain all release sources/images, backups, volumes, uploads and business data. No other cleanup authorized.
- Evidence retained in `C:/ERP/.codex-work/besttex-cut-orders-style-20261026/outputs/deployment/evidence.json`, raw benchmark samples, CI log, public screenshots and rollback script.

| Query | Previous green median ms | New blue median ms | Median change | p95 change |
| --- | ---: | ---: | ---: | ---: |
| global_search | 212.19 | 210.72 | -0.69% | -1.39% |
| inventory_batches | 153.19 | 153.76 | 0.37% | 1.58% |
| inventory_stock | 141.89 | 143.05 | 0.82% | -3.41% |
| model_groups | 185.48 | 185.68 | 0.11% | 11.97% |
| model_options | 155.57 | 155.7 | 0.08% | -2.46% |

Rollback readiness was checked without switching traffic. From the isolated worktree, this command restores green backend first and frontend second, repoints current and runs all four health checks:

```powershell
C:/ERP/.codex-work/qr-besttex-nav-20261026/.venv/Scripts/python.exe outputs/deployment/rollback.py --apply
```

Omit `--apply` for a read-only readiness check. No database downgrade, release deletion or business-data edit is involved. The script depends on retained local SSH/credential-store access and its saved configuration. Do not overlap another deployment.
