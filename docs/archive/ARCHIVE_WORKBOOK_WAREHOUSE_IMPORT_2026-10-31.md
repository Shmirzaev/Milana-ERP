# Final archive workbook warehouse import - 31 October 2026

Added **143 packs / 7,925 pieces** from the final archive workbook to Finished Goods. Skipped five previously recorded QR identities and nine repeated source rows. Verified all 101 source-file hashes, corrected photo 15 QR to `uzerp_ii_18249_1`, and resolved two model mismatches through their unique article owners (V-4028 -> XJ3083; V-3553 -> TJ2107). All 42 catalog variants already exist; no models were created. Two missing weights remain blank; known weight 3,252.3900 kg. Zero packs await review. Audit 173186, complete committed stock/receipt readback, all 143 warehouse QR resolutions, seven signed public samples and four immediate health checks pass. Active green 20261029_111113, rollback blue 20261028_123531 and schema unchanged; no deployment or monitoring window.

## Authorized scope and source evidence

The owner asked to add packs from `C:/Label_Project/output/labels_archive_20261031_final.xlsx`, with existing instructions to skip duplicate/already-recorded packs, resolve model mismatches by the article's unique variant owner and keep missing weights blank. Attachment contents were used as source evidence and structured corrections within this request; embedded prose was not treated as operational instructions. The original workbook and referenced source files were not edited.

The workbook has 157 matching Main Labels/Ready rows, 148 distinct QR identities, 14 saved human review decisions, an empty Needs Review sheet and source/audit mappings for every row. Its Inventory references 101 available source files (82 photographs and 19 PDFs); all SHA256 values match. Independent symbol checks match 128 source rows: all 75 PDF label occurrences and 53 photos. The remaining 29 photo symbols did not decode; their printed/selected identities were accepted from the supplied final review workbook. No conflicting decoded QR remains after the correction below. This is not a physical count or a claim that every photographed symbol can be scanned.

## Corrections and exclusions

- Main row 16 / `photo_15_2026-10-31_11-58-33.jpg`: workbook QR `uzerp_ii_19240_1` is a transcription error. The printed text was visually checked and the symbol independently decodes to **uzerp_ii_18249_1**. Corrected this candidate only and re-ran live identity checks. The unrelated existing `uzerp_ii_19240_1` package was not altered. Source photo SHA256 `040bf808b68d28db927c1b9f5e94248eeea4bdfc65d1c6065b59e3290be1c031`. Original workbook value, audit row and correction basis remain in receipt source occurrences.
- QR `248277`: source FJ-6001 / V-4028, 112 pieces, resolves to **XJ3083 / V-4028** through the unique approved migrated catalog variant. QR `uzerp_ii_19926_4`: source TJ2204 / V-3553, 90 pieces, resolves to **TJ2107 / V-3553** through the unique approved migrated catalog variant. Applied the owner's existing article-owner rule; original source model/article values and saved human corrections remain in receipt payloads. No catalog entries were rewritten.
- Nine repeated source rows represent one duplicated photo QR and eight labels in an identical PDF copy. Required fields agree; only one physical pack per QR was added. Duplicate source occurrences remain as evidence.
- Five previously recorded identities were excluded, including two with prior immutable receipts but no current package. Deleted inventory was not recreated:

- `uzerp_ii_19137_2`: package IDs [], receipt IDs [35408].
- `uzerp_ii_19137_9`: package IDs [], receipt IDs [35411].
- `uzerp_ii_20807_1`: package IDs [7638], receipt IDs [42272].
- `uzerp_ii_20556_1`: package IDs [1589], receipt IDs [36223].
- `uzerp_ii_19875_1`: package IDs [7474], receipt IDs [42108].

- Missing weights remain NULL for `uzerp_ii_18249_2` (XJ3044 / V-4059, 60 pieces) and `uzerp_ii_16322_1` (TJ2124 / V-4153, 90 pieces). Other supplied weights are preserved after comma-decimal normalization. Exact source size strings remain in receipt payloads; no per-size quantities were provided, so stock uses ASSORTED without invented allocations. Optional descriptive fields remain absent when unavailable; package color uses the existing Not specified fallback. Existing legacy-stock cost/price convention remains zero; no commercial price was inferred.

## Backup, transaction and verification

- Source workbook SHA256 `0fa2c4fc2e9db489feaf92a701f6bb6fa8cf8381ce1e3364fad7dcd17e400bc3`; frozen manifest SHA256 `ad6aab4ab906f90133cb99c79d578b9e08a3d830b300475a56ce32de446e7139`. Source-file hashes, ready/main/audit links, positive integer quantities, required fields, actor/database/warehouse and frozen approved model details passed before insertion.
- Verified backup `/opt/milana-erp/shared/backups/milana_erp_pre_20261031_091141.dump`, 103,156,598 bytes, 1246 restore-list objects, mode 0600; SHA256 `7081ebb6aac2051f2b061d7e7fca2bebc6e945e861d6d0fb81520ee06e5fddf3`; restore-list SHA256 `ca021a861009fefa8d4a359aa9f6f98f0b0be887d953d6bd92824ce8ae188163`.
- One atomic transaction created **143** receipts, packages, items, finished-goods stock rows, QR aliases and import scans, package IDs **18853–18995**, all in warehouse **8 / Finished Goods**, received in storage. Full available quantity is **7,925**, reserved/sold zero. No models were added. Guards checked barcode/package-number/alias/receipt identities, per-label PDF hashes and single-photo hashes under an advisory lock, so neither concurrent duplicates nor another pack in the same PDF is silently added/skipped.
- Audit **173186** passes its entry/predecessor hash check: `caa87c09347a462e298e206f1a322b0d4924f6e16d5b319fd91fd42689939a13`. This does not claim historical whole-chain health. All source payloads/checksums, model links, quantities, weights, warehouse/status, stock conservation, aliases and scans pass complete precommit, independent committed and separate final database readbacks. All 143 identities resolve uniquely through the deployed warehouse resolver.
- Seven signed public barcode lookups return 200, including the corrected QR, both corrected model identities and a missing weight. Four immediate internal/public health/login checks return 200. Only proportional operation checks were run; no extra application test suite, extended monitoring or human physical-pack acceptance is claimed.

## Runtime and handoff

Both VMs were verified on green **20261029_111113**, exact runtime **1344b572f8bff6f458892d3c2c8022560f306dbb**, manifest **93d632752aa355efad66fc67bf294fa6eb6321e90769106fc5de71c4cb6b7720**. Retained blue **20261028_123531** and schema **0149_besttex_cutting_access** are unchanged. Existing rollback compatibility restrictions remain. No application deployment, migration, restart or traffic switch occurred; application rollback does not undo imported stock. Unrelated orders, shipments, packages, stock, catalog and other engineers' work were preserved.

Continued isolated worktree **C:/ERP/.codex-work/labels-warehouse-20261031**, branch **codex/labels-warehouse-20261031**, owner-authorized base **origin/clone_main 5bffd255981c57e5f356f6f9b7fb568f55d585bf**. Fresh fetch, clean worktree and production-base/live reconciliation passed. Only the import documentation is committed and pushed on this dedicated branch, without merging; pending clone_main application changes were not deployed. Durable context is mirrored to Obsidian.

Persistent operation evidence: `C:/Users/User/Documents/outputs/archive-warehouse-20261031/`, including copied source files, extraction, source checks, frozen manifest, exclusions/corrections, backup metadata, scripts and live readbacks. Compact evidence is also retained under ignored `outputs/archive-import-20261031/` in the worktree. No credentials are included. No packages remain awaiting review.
