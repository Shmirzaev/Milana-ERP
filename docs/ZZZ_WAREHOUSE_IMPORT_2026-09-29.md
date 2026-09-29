# zzz.zip warehouse import - 2026-09-29

Added all **56 labeled packages / 3,138 pieces / 1,470.98 kg** to Finished Goods. The catalog was skipped at the user’s instruction.

## Additional zzz.zip package import (2026-09-29)

- User requested adding `zzz.zip` and explicitly instructed skipping `Xakim_aka_1_qopdan_Katalog.pdf`. Only the 19 sticker PDFs (27 pages) were imported. The separate two-page, 13-product catalog was excluded; no stock quantity or action was inferred from its contents.
- APPLIED to production Finished Goods warehouse 8: all 56 unique labeled packages, 3,138 pieces, 1,470.98 kg, across 15 existing catalog models. All printed fields were complete, every QR independently decoded, and there were zero duplicate labels, unreadable rows, or pre-existing package collisions. Eight PJ1000 / V-4511 packages resolved to existing catalog model 79 using original identity `PJ1000|4511`; the hidden legacy placeholder was excluded without modification.
- One atomic transaction created 56 immutable receipts, packages, package items, stock rows, QR aliases, and import scans. Complete committed-data readback confirms all 3,138 pieces available with zero reserved/sold quantity. Audit entry 23916, hash `6c0d4f3cee42b026d7a190bf8c175112d5350a32b7376b403cd677069a031d89`. No new model, production order, shipment, permission, schema, or application release was created.
- Manifest SHA-256 `1e6e707cc380dd76c10edc01bf34e889199d52c2d6a269f0b56a805624e01208`; ZIP SHA-256 `dfa1d843102230da50774ef453dd836253f0e5d20862b34959a4cddf8aba0592`. Source file hashes and page/label references remain in each receipt. Task artifacts and operational scripts are preserved under `C:/ERP/.codex-work/sticker-warehouse-20260929/outputs/zzz-20260929/`.
- Fresh backup after the preceding 483-package import and before this batch: `/opt/milana-erp/shared/backups/milana_erp_pre_20260929_110001.dump`, 56,525,878 bytes, mode 0600, 1,203 restore objects; SHA-256 `dca0292b8d8fb78a99aea90255c7117d8065c15485563e2239a655208b9f7c82`; restore-list SHA-256 `30afcefd7577254260deb15dd407e5b2bc2f9e7b39116d2e89bbffbce89a826c`.
- Checks passed: extraction/QR/scope validation, compilation, zero-collision production dry-run, full committed readback, 56 QR/alias checks, 20 internal and five public barcode API samples, and all four health/login checks. Both slot states and manifest guards remain on blue `20260929_034500`, rollback green `20260928_114232`, database `0133_storage_customers`. No deployment, migration, restart, or symlink change occurred.
- Both ZIP imports together added 539 packages / 32,673 pieces / 13,473.07 kg. The prior 37 held packages remain unresolved and untouched. No sticker from `zzz.zip` is held. Work continued in the clean dedicated worktree `C:/ERP/.codex-work/sticker-warehouse-20260929`, branch `codex/sticker-warehouse-20260929`. The production data is committed; documentation is pushed on that branch without merge or deployment.

## Imported packages

| Package QR | Model / variant | Pieces | Weight kg |
|---|---|---:|---:|
| uzerp_ii_21684_1 | PJ1089 / V-6056 | 72 | 30.72 |
| uzerp_ii_21685_1 | TJ2192 / V-4851 | 90 | 31.3 |
| uzerp_ii_21686_1 | TJ2192 / V-4851 | 36 | 12.54 |
| uzerp_ii_21687_1 | PJ1118 / V-3818 | 60 | 28.26 |
| uzerp_ii_21687_2 | PJ1118 / V-3818 | 60 | 28.12 |
| uzerp_ii_21688_1 | KJ13036 / V-6070 | 30 | 23.76 |
| uzerp_ii_21688_2 | KJ13036 / V-6070 | 30 | 23.76 |
| uzerp_ii_21688_3 | KJ13036 / V-6070 | 30 | 23.78 |
| uzerp_ii_21688_4 | KJ13036 / V-6070 | 30 | 23.8 |
| uzerp_ii_21688_5 | KJ13036 / V-6070 | 30 | 23.8 |
| uzerp_ii_21688_6 | KJ13036 / V-6070 | 30 | 23.78 |
| uzerp_ii_21688_7 | KJ13036 / V-6070 | 30 | 23.76 |
| uzerp_ii_21688_8 | KJ13036 / V-6070 | 30 | 23.78 |
| uzerp_ii_21688_9 | KJ13036 / V-6070 | 30 | 23.8 |
| uzerp_ii_21689_1 | PJ1108 / V-5998 | 66 | 27.56 |
| uzerp_ii_21690_1 | XJ3186 / V-6000 | 48 | 15.46 |
| uzerp_ii_21691_1 | XJ3174 / V-5805 | 90 | 34.26 |
| uzerp_ii_21691_2 | XJ3174 / V-5805 | 90 | 34.16 |
| uzerp_ii_21691_3 | XJ3174 / V-5805 | 90 | 34.3 |
| uzerp_ii_21691_4 | XJ3174 / V-5805 | 90 | 34.14 |
| uzerp_ii_21699_1 | PJ1000 / V-4511 | 60 | 27.92 |
| uzerp_ii_21699_2 | PJ1000 / V-4511 | 60 | 27.88 |
| uzerp_ii_21699_3 | PJ1000 / V-4511 | 60 | 27.92 |
| uzerp_ii_21699_4 | PJ1000 / V-4511 | 60 | 27.88 |
| uzerp_ii_21699_5 | PJ1000 / V-4511 | 60 | 27.92 |
| uzerp_ii_21700_1 | PJ1000 / V-4511 | 60 | 27.92 |
| uzerp_ii_21700_2 | PJ1000 / V-4511 | 60 | 27.94 |
| uzerp_ii_21700_3 | PJ1000 / V-4511 | 60 | 27.88 |
| uzerp_ii_21701_1 | BJ5033 / V-6197 | 90 | 22.8 |
| uzerp_ii_21701_2 | BJ5033 / V-6197 | 90 | 22.82 |
| uzerp_ii_21701_3 | BJ5033 / V-6197 | 90 | 22.78 |
| uzerp_ii_21701_4 | BJ5033 / V-6197 | 90 | 22.84 |
| uzerp_ii_21701_5 | BJ5033 / V-6197 | 90 | 22.86 |
| uzerp_ii_21706_1 | KJ13025 / V-5489 | 30 | 27.48 |
| uzerp_ii_21706_2 | KJ13025 / V-5489 | 30 | 27.5 |
| uzerp_ii_21706_3 | KJ13025 / V-5489 | 30 | 27.46 |
| uzerp_ii_21709_1 | PJ1118 / V-3638 | 60 | 27.86 |
| uzerp_ii_21709_2 | PJ1118 / V-3638 | 60 | 27.88 |
| uzerp_ii_21709_3 | PJ1118 / V-3638 | 60 | 27.9 |
| uzerp_ii_21709_4 | PJ1118 / V-3638 | 60 | 27.92 |
| uzerp_ii_21710_1 | KJ13040 / V-6187 | 30 | 23.94 |
| uzerp_ii_21710_2 | KJ13040 / V-6187 | 30 | 23.96 |
| uzerp_ii_21710_3 | KJ13040 / V-6187 | 30 | 23.98 |
| uzerp_ii_21710_4 | KJ13040 / V-6187 | 30 | 24 |
| uzerp_ii_21710_5 | KJ13040 / V-6187 | 30 | 24.02 |
| uzerp_ii_21711_1 | PG10515 / V-5849 | 90 | 24.88 |
| uzerp_ii_21711_2 | PG10515 / V-5849 | 90 | 24.9 |
| uzerp_ii_21711_3 | PG10515 / V-5849 | 90 | 24.92 |
| uzerp_ii_21712_1 | KJ13025 / V-5489 | 30 | 27.46 |
| uzerp_ii_21712_2 | KJ13025 / V-5489 | 30 | 27.48 |
| uzerp_ii_21712_3 | KJ13025 / V-5489 | 30 | 27.52 |
| uzerp_ii_21712_4 | KJ13025 / V-5489 | 30 | 27.5 |
| uzerp_ii_21713_1 | XJ3174 / V-5805 | 90 | 34.14 |
| uzerp_ii_21713_2 | XJ3174 / V-5805 | 90 | 34.16 |
| uzerp_ii_21714_1 | PJ1108 / V-2823 | 42 | 18.34 |
| uzerp_ii_21715_1 | PJ1080 / V-6002 | 54 | 23.58 |
