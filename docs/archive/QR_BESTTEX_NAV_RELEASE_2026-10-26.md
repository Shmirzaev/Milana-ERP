# Completed QR, Besttex and grade packaging deployment

26 October 2026. Green `20261026_045639` / `d187959565821cadde420809a602426caee9ac42` is live on backend and frontend. Blue `20261024_093619` / `1fce86b5b9156fac050ca5c98433198323b20929` remains running for rollback. No ongoing refactoring was included. The dedicated application branch `codex/qr-besttex-nav-release-20261026` is pushed; this documentation record is a separate branch, with no integration merge.

## QR pictures, Besttex cut orders and compact grade totals deployed (2026-10-26)

- Both production roles are green `20261026_045639`, application `d187959565821cadde420809a602426caee9ac42`, activated at 05:34 UTC. Blue `20261024_093619` / `1fce86b5b9156fac050ca5c98433198323b20929` remains running and verified for rollback. Both current symlinks, slot states, immutable image IDs and source manifests agree. Source manifest: `6aa95086ca942de2503487d8506b485920cef914a02727e9497c448b07585959`.
- All three requested changes are live: Process QR model/variant thumbnails; factory-scoped read-only Besttex cut-order search and cutting-sheet printing for besttex@milanapremium.uz and admin; compact 1-nav/2-nav entry with separate total kg and exact 0.0001-kg allocation. Only the feature patch was ported onto exact active application 1fce86b5 in the deployed namespace layout. No ongoing clone_main refactoring or dirty legacy-checkout changes were deployed.
- Data-only migration `0149_besttex_cutting_access` grants the named account the narrow permission, preserving its role, factory and other rights. No schema shape, manufacturing records, stock, packages or orders were altered by deployment QA. A fresh 91,679,382-byte verified PostgreSQL backup with 1,246 restore objects remains on the backend VM.
- Exact-commit immutable CI [40271633438](https://github.com/Shmirzaev/Milana-ERP/actions/runs/40271633438) passed backend, frontend and release jobs: full backend 3,884 passed / 311 skipped plus explicit PostgreSQL suites, lint/types/contracts/build and focused access/migration tests. Independent source/operations review passed. Local EN/RU/UZ browser tests verified persisted grade weights and exact conservation; bounded 80-request stress preserved all 96 business-table fingerprints.
- Candidate/public signed read-only QA verified both thumbnails, the compact fields, Besttex's 140 eligible records, GET sheets, denied anonymous/invalid access and zero console errors. The actual Chrome print button opened the cutting-sheet popup. Automated visual inspection of its blob URL was blocked by browser policy; no workaround was attempted. The existing renderer, opener CSP and print path were reviewed. Direct API navigation has the existing restrictive backend CSP and is not the UI print flow.
- All four internal/public health checks, two workers, zero restarts/OOM, clean logs, valid HAProxy, PostgreSQL headroom and zero invalid indexes passed. Both paired candidate and public closing fixed-query performance gates passed (120 samples per query; identical result counts and payload sizes). Backend disk 75.33%, frontend 72.61%. The owner explicitly waived 30-minute monitoring; immediate and closing checks were completed, with no timed observer represented as passed.
- Only explicitly approved cleanup was executed: npm download cache, old unused untagged backend build images and 154 historical server backup copies after complete local hash/restore-list verification. Archives remain at `C:/Users/User/Documents/Milana ERP Archives/20261026-capacity`. Active/rollback releases, all container-referenced/tagged images, volumes, uploads, newer backups and business data remain. The two stopped-container frontend image candidates and the locally blocked .next removal were preserved.
- Full artifact hashes, backup details, performance evidence and the rollback command are recorded below. Temporary read-only QA gateways were stopped. Application branch is pushed; no integration merge or unrelated refactoring landing was performed. Deployment evidence is retained in `C:/ERP/.codex-work/qr-besttex-nav-deploy-20261026/outputs/deployment`.


## Immutable artifacts and database

- Backend: `ghcr.io/shmirzaev/milana-erp-backend@sha256:b137ad0557e4a839decb63709601a033b27f32173b44d12c84c0f37a60ef472b`
- Frontend: `ghcr.io/shmirzaev/milana-erp-frontend@sha256:4730b2635f6fd2eb1e013be2c41c0774ed1c684304c1ed223d99489ddf06c926`
- Source archive SHA-256: `26d09bf94a6b0a2126e39855e70b7d1e9be0bd48be9e17fe493bc85c0603c90b`; 1,434 files byte-verified against the exact Git commit on both VMs.
- Backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20261026_045639.dump`; SHA-256 `de7992338c761ad342b4c50fd535ac43299441c24093ba5513b7b7e77acd1881`.
- Restore-list SHA-256: `78c2967eea7a7bf790ac8839f89f2839e9b2921c53426e5b0e8970cabd52093b`. Mode 0600, full custom archive listing verified before migration/cutover.
- Database revision: `0149_besttex_cutting_access`; rollback-compatible named-account permission grant only. Do not downgrade the database for application rollback.

## Public closing performance

120 measured requests per fixed query after five warmups; unchanged median 10%, p95 15% and payload 15% budgets. All result counts and payload sizes matched. Paired blue/green medians were also 0.34–0.77% faster on green.

| Query | Blue median ms | Green median ms | Median change | p95 change |
| --- | ---: | ---: | ---: | ---: |
| global_search | 213.46 | 210.4 | -1.43% | -15.92% |
| inventory_batches | 153.39 | 150.59 | -1.83% | -3.11% |
| inventory_stock | 141.85 | 140.86 | -0.7% | -1.48% |
| model_groups | 186.34 | 183.32 | -1.62% | -1.92% |
| model_options | 155.65 | 154.38 | -0.82% | -1.68% |

## Ready rollback

From `C:/ERP/.codex-work/qr-besttex-nav-deploy-20261026`, readiness only:

```powershell
C:/ERP/.codex-work/qr-besttex-nav-20261026/.venv/Scripts/python.exe outputs/deployment/rollback.py
```

To restore blue backend first, frontend second, both symlinks and all four health checks:

```powershell
C:/ERP/.codex-work/qr-besttex-nav-20261026/.venv/Scripts/python.exe outputs/deployment/rollback.py --apply
```

The script uses existing private credential-store/SSH access without printing secrets. It verifies the retained blue source manifests, release labels and running containers. No deletion, database downgrade or business-data edit is involved. Previous green 20261024_032622 source/images also remain retained. Do not overlap deployments.

Full local evidence: `outputs/deployment/evidence.json`, raw performance samples, approved cleanup/offload records and public screenshots. Temporary QA gateways have been stopped. No 30-minute observation was run, as explicitly requested by the owner. Human factory acceptance remains outstanding; no bug tracker item was retired.
