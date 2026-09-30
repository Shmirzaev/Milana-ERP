# zxz.zip warehouse import - 2026-09-30

## zxz.zip warehouse packages imported (2026-09-30)

- APPLIED to production Finished Goods warehouse 8: **all 67 packages / 4,521 pieces / 1,523.40 kg**, across 15 approved catalog variants. All pieces available; no blank weights, duplicated packages, skipped labels, or holds from this ZIP. The 17 supplied PDFs contain 29 pages. All pages were visually reviewed, all 67 QR symbols independently decoded and matched printed identifiers, and there were no conflicting labels. Document contents were used as evidence, not instructions.
- Created only the missing approved catalog variant `PB10012-6256`, model ID 8171, for five packages / 300 pieces / 95 kg. Authenticated old ERP variant 6256 confirms master PB10012 (3265), color Rotatsion Baski, six sizes 122/128/134/140/146/152, and the exact variant fabric picture. Stored the picture as `material`, not a finished-garment image. Source master has 58 operations totaling 10,220 UZS per factory; established Milana/Besttex/Eco Cotton scopes are preserved on this new variant only (174 entries). Existing PB10012 family rows and their operation lists remained unchanged. No BOM or recipe was inferred.
- One atomic transaction created the one catalog variant and 67 immutable source receipts, packages, ASSORTED items, stock rows, QR aliases, and import scans. Source labels provide total pieces and size sets, without per-size quantities. Catalog audit 24783; package audit 24784. No production order, shipment, customer, permission, schema, or application-release change.
- Package manifest SHA-256 `03f3f3ad4ebefde2b950381b9246be9b85b87b90672083800f5655f8ba0ca0c6`; catalog manifest SHA-256 `5379c1782057bee3f2802773c19cb96588b1e67fb79ff7dc3ccedb6a515084b6`; ZIP SHA-256 `a3315194a6b694d3c48aaca006e4f8a628868661300c0a12e16bae539969b011`. Each receipt retains the source PDF hash, page and label number. Frozen evidence and task scripts: `outputs/zxz-20260930/` in the worktree below.
- Fresh pre-mutation PostgreSQL backup `/opt/milana-erp/shared/backups/milana_erp_pre_20260930_100001.dump`: 58,918,576 bytes, mode 0600, 1,203 restore objects; SHA-256 `abb15fe1cc83beb6d18cf1bbbb375ea90420ec04be77572c97e8b4b44a16d65d`; restore-list SHA-256 `3771fff4ede8b6b8d7b8b86472a26d1f66bd7cfcc1335c128c429e23647be57e`.
- Required checks passed: script compilation, source identity/sizes/operation/image/hash validation, zero-collision production dry-run, complete atomic precommit and separate committed readback, all 67 internal barcode HTTP lookups, three public QR lookups, public catalog and exact material-image hash, preservation of existing PB10012 family and previously held QR, and all four immediate health/login probes (HTTP 200). No extra application test suite or monitoring window.
- Production was reconciled before edits: both VM slots, current symlinks and source manifests agree with current `origin/main` production baseline. Active blue remains `20260929_120503`, rollback green `20260929_110044`, database `0133_storage_customers`, source manifest `ffe4692e89549631a894eaca7f893a6ce95e333fd581a3c010478c5dd3b364f7`, application commit `380069a6e77472f0921e4b620d44c88778f30533`. No deployment, migration, restart, or symlink change was needed for this live data import.
- Prior task records report 668 packages / 41,677 pieces / 16,575.93 kg known weight imported from sticker (2).zip, zzz.zip and 666.zip. Including this batch, cumulative imports are **735 packages / 46,198 pieces / 18,099.33 kg known weight**; the prior four NULL weights remain unchanged. The previous XJ3182 / V-5950 label reusing `uzerp_ii_21571_1` remains held; existing PG10521 / V-6105 package 9280 was verified unchanged. The separately excluded Xakim catalog remains excluded.
- Dedicated clean worktree `C:/ERP/.codex-work/zxz-warehouse-20260930`, branch `codex/zxz-warehouse-20260930`, created from verified `origin/main` `0a2f98f27bb4f1f33c22380e7629703d4f0f7e62`. Documentation record committed and pushed, not merged. Legacy checkout and prior import worktree preserved. Durable context mirrored to Obsidian.

## Imported packages

| QR | Model / variant | Pieces | Weight kg |
|---|---|---:|---:|
| uzerp_ii_21720_1 | PB10012 / V-6256 | 60 | 19 |
| uzerp_ii_21720_2 | PB10012 / V-6256 | 60 | 19 |
| uzerp_ii_21720_3 | PB10012 / V-6256 | 60 | 19 |
| uzerp_ii_21720_4 | PB10012 / V-6256 | 60 | 19 |
| uzerp_ii_21720_5 | PB10012 / V-6256 | 60 | 19 |
| uzerp_ii_21726_1 | PM7013 / V-6196 | 60 | 30.1 |
| uzerp_ii_21727_1 | PM7013 / V-6196 | 90 | 45.2 |
| uzerp_ii_21734_1 | SJ4071 / V-6143 | 90 | 25.3 |
| uzerp_ii_21734_2 | SJ4071 / V-6143 | 90 | 25.3 |
| uzerp_ii_21734_3 | SJ4071 / V-6143 | 90 | 25.3 |
| uzerp_ii_21734_4 | SJ4071 / V-6143 | 90 | 25.3 |
| uzerp_ii_21734_5 | SJ4071 / V-6143 | 90 | 25.3 |
| uzerp_ii_21735_10 | PJ1228 / V-6037 | 60 | 24 |
| uzerp_ii_21735_1 | PJ1228 / V-6037 | 60 | 24 |
| uzerp_ii_21735_2 | PJ1228 / V-6037 | 60 | 24 |
| uzerp_ii_21735_3 | PJ1228 / V-6037 | 60 | 24 |
| uzerp_ii_21735_4 | PJ1228 / V-6037 | 60 | 24 |
| uzerp_ii_21735_5 | PJ1228 / V-6037 | 60 | 24 |
| uzerp_ii_21735_6 | PJ1228 / V-6037 | 60 | 24 |
| uzerp_ii_21735_7 | PJ1228 / V-6037 | 60 | 24 |
| uzerp_ii_21735_8 | PJ1228 / V-6037 | 60 | 24 |
| uzerp_ii_21735_9 | PJ1228 / V-6037 | 60 | 24 |
| uzerp_ii_21736_1 | PG10518 / V-6038 | 60 | 16.9 |
| uzerp_ii_21736_2 | PG10518 / V-6038 | 60 | 16.9 |
| uzerp_ii_21736_3 | PG10518 / V-6038 | 60 | 16.9 |
| uzerp_ii_21736_4 | PG10518 / V-6038 | 60 | 16.9 |
| uzerp_ii_21736_5 | PG10518 / V-6038 | 60 | 16.9 |
| uzerp_ii_21736_6 | PG10518 / V-6038 | 60 | 16.9 |
| uzerp_ii_21736_7 | PG10518 / V-6038 | 60 | 16.9 |
| uzerp_ii_21736_8 | PG10518 / V-6038 | 60 | 16.9 |
| uzerp_ii_21736_9 | PG10518 / V-6038 | 60 | 16.9 |
| uzerp_ii_21737_1 | PB10011 / V-6040 | 60 | 16.9 |
| uzerp_ii_21737_2 | PB10011 / V-6040 | 60 | 16.9 |
| uzerp_ii_21737_3 | PB10011 / V-6040 | 60 | 16.9 |
| uzerp_ii_21737_4 | PB10011 / V-6040 | 60 | 16.9 |
| uzerp_ii_21737_5 | PB10011 / V-6040 | 60 | 16.9 |
| uzerp_ii_21737_6 | PB10011 / V-6040 | 60 | 16.9 |
| uzerp_ii_21737_7 | PB10011 / V-6040 | 60 | 16.9 |
| uzerp_ii_21737_8 | PB10011 / V-6040 | 60 | 16.9 |
| uzerp_ii_21737_9 | PB10011 / V-6040 | 60 | 16.9 |
| uzerp_ii_21741_1 | PM7016 / V-6208 | 60 | 27.8 |
| uzerp_ii_21741_2 | PM7016 / V-6208 | 60 | 27.8 |
| uzerp_ii_21741_3 | PM7016 / V-6208 | 60 | 27.8 |
| uzerp_ii_21741_4 | PM7016 / V-6208 | 60 | 27.8 |
| uzerp_ii_21741_5 | PM7016 / V-6208 | 60 | 27.8 |
| uzerp_ii_21741_6 | PM7016 / V-6208 | 60 | 27.8 |
| uzerp_ii_21741_7 | PM7016 / V-6208 | 60 | 27.8 |
| uzerp_ii_21741_8 | PM7016 / V-6208 | 60 | 27.8 |
| uzerp_ii_21741_9 | PM7016 / V-6208 | 60 | 27.8 |
| uzerp_ii_21743_1 | PG10518 / V-6038 | 42 | 11.7 |
| uzerp_ii_21744_1 | SJ4004 / V-6216 | 162 | 37.8 |
| uzerp_ii_21753_1 | PJ1058 / V-6126 | 60 | 24.8 |
| uzerp_ii_21753_2 | PJ1058 / V-6126 | 60 | 24.8 |
| uzerp_ii_21753_3 | PJ1058 / V-6126 | 60 | 24.8 |
| uzerp_ii_21753_4 | PJ1058 / V-6126 | 60 | 24.8 |
| uzerp_ii_21753_5 | PJ1058 / V-6126 | 60 | 24.8 |
| uzerp_ii_21753_6 | PJ1058 / V-6126 | 60 | 24.8 |
| uzerp_ii_21753_7 | PJ1058 / V-6126 | 60 | 24.8 |
| uzerp_ii_21753_8 | PJ1058 / V-6126 | 60 | 24.8 |
| uzerp_ii_21754_1 | PM7015 / V-6219 | 42 | 19.7 |
| uzerp_ii_21755_1 | PM7011 / V-4891 | 30 | 10.7 |
| uzerp_ii_21756_1 | PJ1232 / V-6095 | 72 | 31.9 |
| uzerp_ii_21757_1 | PJ1183 / V-5055 | 168 | 35 |
| uzerp_ii_21758_1 | SJ4013 / V-6242 | 90 | 20.4 |
| uzerp_ii_21758_2 | SJ4013 / V-6242 | 90 | 20.4 |
| uzerp_ii_21758_3 | SJ4013 / V-6242 | 90 | 20.4 |
| uzerp_ii_21760_1 | SJ4022 / V-6172 | 135 | 25.8 |
