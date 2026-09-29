# Resolved warehouse packages - 2026-09-29

## Held sticker packages resolved (2026-09-29)

- User requested importing the missing variants from the open old ERP and leaving four unknown/conflicting package weights blank. The user explicitly chose to HOLD the reused QR package `uzerp_ii_21571_1` (XJ3182 / V-5950, 60 pieces, 21.72 kg). Its existing package 9280 / PG10521 V-6105 / 60 pieces / 15.1 kg and immutable receipt were verified unchanged.
- APPLIED atomically to Finished Goods warehouse 8: six source-backed approved catalog variants and 36 packages / 1,873 pieces / 823.18 kg of known weight; four weights are NULL. All 1,873 pieces are available. Each package has one immutable source receipt, item, stock row, QR alias, and import scan. No production order, shipment, schema, permission, or release change occurred.
- Created catalog variants: KJ13038 V-6154, V-6152, V-6204; PJ1242 V-6217; BJ5008 V-6191; PM7015 V-6219 (new model IDs 8163-8168). Identity, color, sizes, and operations were read from authenticated old-ERP forms and master records. Five exact variant photos were imported; BJ5008 V-6191 had no variant picture, so its source master picture was used with explicit provenance. Raw evidence and hashes are preserved. Operations were imported only onto the six new rows, using established Milana/Besttex/Eco Cotton scopes; existing family operations/general/status were verified unchanged. No BOM or recipe was inferred.
- Corrected the 15 KJ13038 label size tokenizations to the source-confirmed single `FREE SIZE`; original extracted tokens remain in receipt provenance. Package size quantities remain ASSORTED because labels give total pieces without size allocations. Source-verified sizes for the other three new families are preserved.
- Blank weights: `uzerp_ii_21609_2` (source blank) and `uzerp_ii_21656_1`, `_2`, `_3` (duplicate source labels disagree). No conflicting weight was selected. Original extraction and the user's blank-weight resolution are recorded.
- Final totals for `sticker (2).zip`: 519 imported packages / 31,408 pieces / 12,825.27 kg known weight, four blank weights, one package / 60 pieces on hold. Including the separate `zzz.zip` batch: 575 packages / 34,546 pieces / 14,296.25 kg known weight. The Xakim catalog remains excluded by user instruction.
- Fresh pre-mutation backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260929_110002.dump`, 56,552,157 bytes, 1,203 restore objects, mode 0600; SHA-256 `18a3398a837973cd514d5df88383144ef6b987a7e019c86e5f4e7ea3f61e910a`, restore-list SHA-256 `f7c94e5e0c6c9dfa0d4a996bb38283f116671f8a03e2f01d591038a6aaf5718f`.
- Frozen package manifest SHA-256 `240cc6952552b6b6e20a25e40a89813b3e19ed17c4227e464dc0d42b4cfe39ca`; catalog SHA-256 `d336fe18014f1063f990f51fc16f9b7c1504e0bbc624b4e1aed0480aeae16005`. Catalog audit 23994 hash `f5c3bb4695cc65563fa85b0a9d1bab942d22c96133f40cf3daa7f930764dff51`; package audit 23999 hash `e44baa5bbd9ae5bc3e68d36720821d5244cc6783ca0014f5e946a026d7a7be82`.
- Checks passed: compilation, source identity/size/operation/image/hash validation, zero-collision production dry-run, atomic precommit and separate committed readback, independent verify mode, all 36 internal QR HTTP lookups, six public QR lookups including all blank weights, six public catalog details and exact image-content hashes, unchanged existing family/held-package checks, and all four health/login probes (HTTP 200).
- Active blue remains `20260929_034500`, rollback green `20260928_114232`, database head `0133_storage_customers`. Both release baselines were verified; no deployment, migration, restart, or symlink change occurred. Dedicated worktree `C:/ERP/.codex-work/sticker-warehouse-20260929`, branch `codex/sticker-warehouse-20260929`; docs-only record is pushed, not merged. Evidence and task-only scripts: `outputs/held-20260929/`. Legacy checkout preserved; durable context mirrored to Obsidian.


## Imported packages

| QR | Model / variant | Pieces | Weight kg |
|---|---|---:|---:|
| uzerp_ii_21551_1 | KJ13038 / V-6154 | 30 | 25.5 |
| uzerp_ii_21551_2 | KJ13038 / V-6154 | 30 | 25.5 |
| uzerp_ii_21551_3 | KJ13038 / V-6154 | 30 | 25.5 |
| uzerp_ii_21551_4 | KJ13038 / V-6154 | 30 | 25.6 |
| uzerp_ii_21551_5 | KJ13038 / V-6154 | 30 | 25.5 |
| uzerp_ii_21552_1 | KJ13038 / V-6152 | 30 | 25.48 |
| uzerp_ii_21552_2 | KJ13038 / V-6152 | 30 | 25.42 |
| uzerp_ii_21552_3 | KJ13038 / V-6152 | 30 | 25.42 |
| uzerp_ii_21552_4 | KJ13038 / V-6152 | 30 | 25.54 |
| uzerp_ii_21552_5 | KJ13038 / V-6152 | 30 | 25.54 |
| uzerp_ii_21561_1 | KJ13038 / V-6204 | 30 | 24.36 |
| uzerp_ii_21561_2 | KJ13038 / V-6204 | 30 | 24.06 |
| uzerp_ii_21561_3 | KJ13038 / V-6204 | 30 | 24.24 |
| uzerp_ii_21561_4 | KJ13038 / V-6204 | 30 | 23.76 |
| uzerp_ii_21561_5 | KJ13038 / V-6204 | 30 | 23.76 |
| uzerp_ii_21589_1 | PJ1242 / V-6217 | 60 | 24.7 |
| uzerp_ii_21589_2 | PJ1242 / V-6217 | 60 | 24.7 |
| uzerp_ii_21589_3 | PJ1242 / V-6217 | 60 | 24.7 |
| uzerp_ii_21589_4 | PJ1242 / V-6217 | 60 | 24.7 |
| uzerp_ii_21603_1 | PJ1242 / V-6217 | 66 | 27.1 |
| uzerp_ii_21609_2 | XJ3106 / V-3814 | 72 | blank |
| uzerp_ii_21636_1 | BJ5008 / V-6191 | 90 | 25.9 |
| uzerp_ii_21636_2 | BJ5008 / V-6191 | 90 | 26.4 |
| uzerp_ii_21637_1 | BJ5008 / V-6191 | 55 | 16 |
| uzerp_ii_21656_1 | BJ5033 / V-6198 | 90 | blank |
| uzerp_ii_21656_2 | BJ5033 / V-6198 | 90 | blank |
| uzerp_ii_21656_3 | BJ5033 / V-6198 | 90 | blank |
| uzerp_ii_21698_1 | PM7015 / V-6219 | 60 | 28.2 |
| uzerp_ii_21698_2 | PM7015 / V-6219 | 60 | 28.2 |
| uzerp_ii_21698_3 | PM7015 / V-6219 | 60 | 28.2 |
| uzerp_ii_21698_4 | PM7015 / V-6219 | 60 | 28.2 |
| uzerp_ii_21698_5 | PM7015 / V-6219 | 60 | 28.2 |
| uzerp_ii_21698_6 | PM7015 / V-6219 | 60 | 28.2 |
| uzerp_ii_21698_7 | PM7015 / V-6219 | 60 | 28.2 |
| uzerp_ii_21698_8 | PM7015 / V-6219 | 60 | 28.2 |
| uzerp_ii_21698_9 | PM7015 / V-6219 | 60 | 28.2 |
