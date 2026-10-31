# Reviewed warehouse labels imported - 31 October 2026

Added **1,447 packages / 109,083 pieces** to Finished Goods warehouse 8. Committed readback confirms every piece available, **7,133.148 kg** known weight and **1,168 blank weights**. There are 1,447 immutable source receipts, package items, stock rows and scan entries; 1,318 old-QR aliases and 129 newly issued QR identities. Size sets remain exact in source payloads; per-size piece counts were not supplied, so stock uses ASSORTED without invented allocations. User-supplied totals were preserved, including the final chat correction of TJ2158 / V-4053 to **60**, superseding the earlier 12.

## Scope and remaining source row

- Scope: original `labels_reviewed.xlsx`, the 1,428 Prepared rows, and the owner's corrected 25-row photo workbook. All source photos were located and matched against their recorded SHA256 before import. The attachment's decision/correction cells were applied only within the user's explicit warehouse-import request. No instructions elsewhere in the documents were executed.
- The prior 315 skipped rows remain excluded. The owner's four additional Skip decisions were honored, and another candidate was excluded because the corrected QR `uzerp_ii_21976_5` duplicates the owner-reviewed PB10012 / V-6258 pack. The owner's reviewed occurrence was retained. Total excluded source occurrences: 320.
- **One held pack:** original Ready row 233 / Main row 233, FJ6000, QR `13388`, 100 pieces, sizes 44/46/48/50. The corrected model is FJ6000 but article remains blank, while ERP has multiple FJ6000 variants. Awaiting the owner's choice to import warehouse-only with a blank article or hold. No variant was guessed and no stock was created for this source. Photo `photo_10_2026-10-26_12-58-55.jpg`.
- Existing packaging, orders, shipments, reservations, quantities, receipts and catalog models were not rewritten. Four selected skips and the unresolved pack were not imported. No runtime application files, schema, permission or release were changed.

## Warehouse-only compatibility correction

The ten packs explicitly marked “Add it to warehouse without adding the model to models” initially used nullable database model links. Immediate API readback exposed a mismatch: the deployed response DTO still requires integer model links and rejected those package details with HTTP 500. After a second verified backup, audit **166840** records narrowly binding those ten packages/items/stock rows to **nine new internal legacy identities and one reused identity**. Their `legacy_import=true` flag excludes them from the default Models catalog. No visible catalog models were added. Source receipts and checksums remain immutable. The final full database readback and public warehouse-only QR lookup pass. This data correction does not claim to fix the underlying nullable-ORM/non-null-DTO inconsistency.

Internal legacy identity IDs created: 8864, 8865, 8866, 8867, 8868, 8869, 8870, 8871, 8872. Existing internal identity 7725 was reused. Existing standard model details and operations were not changed.

## Source and transactional evidence

- Main import audit **166818**, entry hash `e79115c281bc0ad2aaff423fab99795a14375b5b3ef3532adab3db1644f86e65`. The corrective binding audit also passes its predecessor/hash check.
- Manifest SHA256: `4f6026a8998d317bb807e38a23ca6ea9a36e600c1babd5a0d281ab51f5bb390c`. Frozen operation evidence and scripts are under ignored `outputs/labels-import-20261031/` in the worktree, with a persistent external copy in `C:/Users/User/Documents/outputs/warehouse-import-20261031/`.
- Original workbook SHA256: `a8906ca84aaa617fa4f3d609184942650a3f30816813b09a4f787e3c5693b678`.
- Prepared workbook SHA256: `5b70ffce23ec2297b8332c876aa26f8d383b1642582ad1cba6ed94977fb096a1`.
- Corrected photo workbook SHA256: `76466fc72f5b38b0a76dfa20f3ea8e6eafe39654ca90cacf1f07a0b4336dc388`.
- Every source receipt stores exact source photo hash, filename, original/main row, corrected model/article/size/quantity, owner review cells and applicable chat confirmation. Original source workbooks and photographs were not edited.
- Pre-import backup `/opt/milana-erp/shared/backups/milana_erp_pre_20261031_055112.dump`: 101,001,357 bytes, 1,246 restore objects, mode 0600; SHA256 `2ac615d77eaaabe00069287324af1fef7b64bd86fb4dbe6c8e750e584b0c5f49`; restore-list SHA256 `02b168a5f2ca632652294e4cf4fbe4f024a33e8861ced59c45e7709fa54cad44`.
- Pre-binding backup `/opt/milana-erp/shared/backups/milana_erp_pre_20261031_055640.dump`: 101,461,746 bytes, 1,246 restore objects; SHA256 `decaef13e770be6cdd573e384195c1df4e0dfcf322100c4308de8f90217b6e79`; restore-list SHA256 `2458b3601d24fc3bd40c7683dd7c6ed85244a35516cfda8e1a98f9c86f0870b2`.

## Validation and production state

Passed script compilation, exact photo hashes, source arithmetic, catalog identity/detail guards, zero collisions across packages/aliases/receipts, full precommit and independent committed database readback, and both new audit entries. After binding correction, all **1,447** package codes resolve uniquely through the deployed warehouse QR resolver; five signed public package-detail samples include new labels and warehouse-only stock. All four immediate internal/public health/login checks returned 200.

An initial attempt to perform all barcode checks through HTTP reached the existing 429 rate limit. Rate limiting was not disabled or bypassed: complete validation used the read-only warehouse resolver and database readback, with bounded public samples. The first warehouse-only API failure and its correction are recorded above. A stale diagnostic assumption that historical package 9280 still existed was removed; the old held QR `uzerp_ii_21571_1` remains outside this manifest, and no prior package was restored or deleted. No extra application test suite or extended monitoring was run, following the owner's preference.

Both VMs were verified on green **20261029_111113**, runtime **1344b572f8bff6f458892d3c2c8022560f306dbb**, source manifest **93d632752aa355efad66fc67bf294fa6eb6321e90769106fc5de71c4cb6b7720**. Database remains **0149_besttex_cutting_access**. Blue **20261028_123531** is unchanged; its previously documented business-code compatibility restrictions remain. This operation did not deploy, migrate, restart, change traffic or alter either release. Application rollback does not undo imported inventory.

Dedicated worktree: `C:/ERP/.codex-work/labels-warehouse-20261031`; branch `codex/labels-warehouse-20261031`; base `origin/clone_main` **5bffd255981c57e5f356f6f9b7fb568f55d585bf**, following the owner's persistent clone_main choice. Its production-base record matches both live manifests; newer pending application changes were not deployed. Documentation record is committed and pushed on this dedicated branch, not merged. The legacy checkout and unrelated work are preserved. Durable context is mirrored to Obsidian.
