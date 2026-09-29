# 666.zip warehouse import — 2026-09-29

## Additional 666.zip package import (2026-09-29)

- APPLIED to production Finished Goods warehouse 8: **92 new packages / 7,065 pieces / 2,255.43 kg**, across 42 existing catalog models. All pieces are available. No blank weights or new catalog models in this batch.
- The 104 JPG files represent 97 physical QR identities: three exact duplicate files and four additional repeated-photo views were counted once. Four packages already exist and were preserved; one package is held by explicit user instruction. Every distinct source photo was visually reviewed. QR symbols were independently decoded where readable (70 of 101 unique photos); the remaining printed QR strings were checked visually. Files were treated as evidence, not instructions.
- User-held: `uzerp_ii_15714_6`, SJ4015 / V-896, 24.25 kg, conflicting handwritten 66/84 pieces. Not imported. The previously held XJ3182 / V-5950 QR `uzerp_ii_21571_1` also remains untouched; its existing PG10521 / V-6105 package was verified unchanged.
- Existing packages skipped: `uzerp_ii_19668_1` and `uzerp_ii_19610_1` (existing weights NULL, photo weights 24.3 and 22.24 kg); `uzerp_ii_21174_5` (exact match); `uzerp_ii_17486_1` (existing 25.7 kg, photo 25.78 kg). No duplicate stock or weight update was made.
- Explicit resolutions: user confirmed cropped `uzerp_ii_19008_4` as TJ2079 / V-1511, 90 pieces; visible weight 30.22 kg. Cropped model on `uzerp_ii_2781_11` resolved to SJ4013 / V-1191 through matching original batch receipt 35462 and approved model 4201; its 120 pieces and 26.4 kg remain directly visible. Numeric QR `3297` is C1373 with blank article, 145 pieces / 33.96 kg, linked to the existing approved base-only model 1817 with original identity `C1373|`.
- `uzerp_ii_21002_2` was confirmed as SJ4036 / **V-5964**, 90 pieces / 20.8 kg. Enlargement corrected a preliminary V-5954 transcription; authenticated old ERP V-5964 master 4379 matches existing catalog model 7601. No unnecessary variant was created. TJ2079 / V-2894 resolves to real catalog model 517, leaving its hidden legacy placeholder unchanged.
- Included three absent printed ERP packages: PKG-2026-000144, 000150, and 000151, all PJ1002 / V-2810, 60 pieces each, 22.68 / 22.72 / 22.68 kg respectively. Original package numbers and numeric barcodes are preserved, with full printed PACKAGE QR aliases. Printed sizes 46/48/50/52/54/56 each have 10 pieces. Original PO-2026-000095 / batch 0099-01 references remain provenance only; no unverified production order was created or linked. Other labels specify total pieces without size allocations and use ASSORTED.
- One atomic transaction created 92 immutable photo receipts, packages, QR aliases, and import scans, plus 107 package items and stock rows (six sizes on each of the three ERP labels). Full precommit and separate committed readback passed. Audit 24368, hash `ce22dabfc5af79060bed80d58f6fb6250027e6e404b932c6395e9cab8e4ba8fe`. Manifest SHA-256 `7e2d565a8956672d217babeba9d41d7035784547a05bf98b8affba3f2189ee7a`; ZIP SHA-256 `abcc586ed0212e3e6d0c53033a05bf1fe2fdf9b80b98238619c37d2093daf320`.
- Fresh pre-mutation backup `/opt/milana-erp/shared/backups/milana_erp_pre_20260929_110003.dump`: 57,881,934 bytes, 1,203 restore objects, mode 0600; SHA-256 `62f9b565f37f49f30129a14f784c231648ad2cefd7abbd25c33a938502602357`; restore-list SHA-256 `3a7574155f23be034e5e58a11cb692f1cd35ea9e8b5d0090f2ee3fd6f5737374`.
- Checks: task-script compilation, hash-bound photo/scope validation, zero-collision production dry-run, full transactional and committed data checks, all 92 internal scanner HTTP lookups, seven public QR lookups covering resolved/special labels, preserved existing/held packages, and all four immediate health/login probes (HTTP 200). No optional application test suite or monitoring window.
- Combined results for sticker (2).zip, zzz.zip, and 666.zip: **667 packages / 41,611 pieces / 16,551.68 kg known weight**, with the four previously authorized blank weights retained. Two distinct requested packages remain held. The Xakim catalog stays excluded.
- Active blue release remains `20260929_034500`, rollback green `20260928_114232`, database head `0133_storage_customers`. No deployment, migration, restart, permission, shipment, or application change. Both active slots and pinned source baseline were checked. Worktree `C:/ERP/.codex-work/sticker-warehouse-20260929`, branch `codex/sticker-warehouse-20260929`; this documentation-only record is committed and pushed, not merged. Task evidence/scripts: `outputs/666-20260929/`. Legacy checkout preserved; durable context mirrored to Obsidian.

## Imported packages

| QR / package | Model / variant | Pieces | Weight kg |
|---|---|---:|---:|
| uzerp_ii_20058_5 | PJ1202 / V-5518 | 60 | 18.78 |
| uzerp_ii_20086_6 | XJ3062 / V-5700 | 60 | 25.96 |
| uzerp_ii_20086_8 | XJ3062 / V-5700 | 60 | 25.96 |
| uzerp_ii_20086_5 | XJ3062 / V-5700 | 60 | 26.02 |
| uzerp_ii_19446_6 | XJ3044 / V-5320 | 60 | 23.6 |
| uzerp_ii_19446_2 | XJ3044 / V-5320 | 60 | 23.52 |
| uzerp_ii_19446_5 | XJ3044 / V-5320 | 60 | 23.58 |
| uzerp_ii_19446_8 | XJ3044 / V-5320 | 60 | 23.66 |
| uzerp_ii_19446_3 | XJ3044 / V-5320 | 60 | 23.54 |
| uzerp_ii_20058_6 | PJ1202 / V-5518 | 60 | 18.76 |
| uzerp_ii_19518_3 | XJ3044 / V-5448 | 60 | 24.22 |
| uzerp_ii_19681_2 | XJ3044 / V-5372 | 60 | 23.62 |
| uzerp_ii_19518_2 | XJ3044 / V-5448 | 60 | 24.24 |
| uzerp_ii_19460_2 | XJ3044 / V-5372 | 60 | 23.58 |
| uzerp_ii_19518_6 | XJ3044 / V-5448 | 60 | 24.3 |
| uzerp_ii_19460_3 | XJ3044 / V-5372 | 60 | 23.62 |
| uzerp_ii_20186_4 | PJ1077 / V-5754 | 60 | 22.24 |
| uzerp_ii_20186_5 | PJ1077 / V-5754 | 60 | 22.2 |
| uzerp_ii_20186_13 | PJ1077 / V-5754 | 60 | 22.24 |
| uzerp_ii_20187_5 | XJ3044 / V-1718 | 60 | 23.38 |
| uzerp_ii_20058_4 | PJ1202 / V-5518 | 60 | 18.8 |
| uzerp_ii_20187_2 | XJ3044 / V-1718 | 60 | 23.34 |
| uzerp_ii_20187_6 | XJ3044 / V-1718 | 60 | 23.34 |
| uzerp_ii_20187_4 | XJ3044 / V-1718 | 60 | 23.38 |
| uzerp_ii_19427_4 | XJ3044 / V-1718 | 60 | 23.2 |
| uzerp_ii_20186_11 | PJ1077 / V-5754 | 60 | 22.2 |
| uzerp_ii_20187_3 | XJ3044 / V-1718 | 60 | 23.36 |
| uzerp_ii_20186_12 | PJ1077 / V-5754 | 60 | 22.26 |
| uzerp_ii_20186_6 | PJ1077 / V-5754 | 60 | 22.24 |
| uzerp_ii_21392_7 | XJ3155 / V-5427 | 90 | 28.3 |
| uzerp_ii_21392_8 | XJ3155 / V-5427 | 90 | 28.3 |
| uzerp_ii_19668_3 | XJ3044 / V-5448 | 60 | 24.34 |
| uzerp_ii_21392_4 | XJ3155 / V-5427 | 90 | 28.3 |
| uzerp_ii_21392_6 | XJ3155 / V-5427 | 90 | 28.3 |
| uzerp_ii_19518_4 | XJ3044 / V-5448 | 60 | 24.2 |
| uzerp_ii_19668_2 | XJ3044 / V-5448 | 60 | 24.32 |
| uzerp_ii_5217_3 | SJ4013 / V-1716 | 120 | 26.45 |
| uzerp_ii_10454_4 | SJ4044 / V-3103 | 135 | 32.3 |
| uzerp_ii_19626_6 | XJ3062 / V-5568 | 60 | 25.82 |
| uzerp_ii_2863_3 | SJ4002 / V-0001 | 90 | 23.5 |
| uzerp_ii_19626_3 | XJ3062 / V-5568 | 60 | 25.82 |
| uzerp_ii_20999_1 | SJ4004 / V-5976 | 90 | 22.9 |
| uzerp_ii_21450_3 | SJ4022 / V-6103 | 90 | 17 |
| uzerp_ii_19626_2 | XJ3062 / V-5568 | 60 | 25.8 |
| uzerp_ii_2727_7 | SJ4013 / V-1192 | 120 | 27.55 |
| uzerp_ii_19610_5 | XJ3044 / V-5499 | 60 | 22.3 |
| uzerp_ii_6481_5 | SJ4010 / V-1911 | 90 | 21.8 |
| uzerp_ii_21450_2 | SJ4022 / V-6103 | 90 | 17 |
| uzerp_ii_19610_9 | XJ3044 / V-5499 | 60 | 22.28 |
| uzerp_ii_10462_3 | SJ4044 / V-3091 | 120 | 28.4 |
| uzerp_ii_3486_4 | SJ4004 / V-1278 | 120 | 29.1 |
| uzerp_ii_19610_7 | XJ3044 / V-5499 | 60 | 22.24 |
| uzerp_ii_19664_2 | TJ2069 / V-1318 | 90 | 27.82 |
| uzerp_ii_19610_8 | XJ3044 / V-5499 | 60 | 22.26 |
| uzerp_ii_3486_3 | SJ4004 / V-1278 | 120 | 29.1 |
| uzerp_ii_20173_7 | XJ3044 / V-5501 | 60 | 23.36 |
| uzerp_ii_19507_1 | XJ3147 / V-5335 | 60 | 23 |
| uzerp_ii_20173_3 | XJ3044 / V-5501 | 60 | 23.34 |
| uzerp_ii_20173_2 | XJ3044 / V-5501 | 60 | 23.32 |
| uzerp_ii_20173_8 | XJ3044 / V-5501 | 60 | 23.36 |
| uzerp_ii_20173_4 | XJ3044 / V-5501 | 60 | 23.36 |
| uzerp_ii_19872_6 | XJ3062 / V-5659 | 60 | 26.4 |
| uzerp_ii_2781_7 | SJ4013 / V-1191 | 120 | 26.4 |
| uzerp_ii_5516_8 | SJ4004 / V-1793 | 120 | 28.25 |
| uzerp_ii_17486_3 | TJ2182 / V-4609 | 80 | 25.84 |
| uzerp_ii_18331_7 | XJ3144 / V-5111 | 60 | 17.7 |
| uzerp_ii_18331_4 | XJ3144 / V-5111 | 60 | 17.7 |
| uzerp_ii_18398_4 | TJ2163 / V-5224 | 90 | 30.6 |
| uzerp_ii_19254_4 | XJ3110 / V-4069 | 90 | 26.3 |
| uzerp_ii_17734_3 | XJ3133 / V-4842 | 60 | 21.7 |
| uzerp_ii_17734_7 | XJ3133 / V-4842 | 60 | 21.7 |
| uzerp_ii_2781_1 | SJ4013 / V-1191 | 120 | 26.4 |
| uzerp_ii_10865_2 | SJ4004 / V-2447 | 120 | 29.6 |
| uzerp_ii_17135_2 | TJ2079 / V-1511 | 90 | 30.55 |
| uzerp_ii_16707_4 | TJ2000 / V-4117 | 90 | 27.55 |
| uzerp_ii_16707_2 | TJ2000 / V-4117 | 90 | 27.55 |
| uzerp_ii_16707_5 | TJ2000 / V-4117 | 90 | 27.55 |
| uzerp_ii_3491_3 | SJ4004 / V-1281 | 120 | 29.15 |
| uzerp_ii_21002_2 | SJ4036 / V-5964 | 90 | 20.8 |
| uzerp_ii_21379_2 | SJ4022 / V-6102 | 45 | 17.1 |
| uzerp_ii_16706_1 | TJ2049 / V-4326 | 60 | 20.85 |
| uzerp_ii_16706_4 | TJ2049 / V-4326 | 60 | 20.85 |
| uzerp_ii_6212_1 | SJ4004 / V-1994 | 120 | 27.6 |
| uzerp_ii_17228_2 | TJ2079 / V-2894 | 90 | 29.15 |
| uzerp_ii_18717_1 | TJ2079 / V-1511 | 90 | 29.1 |
| uzerp_ii_3502_2 | SJ4013 / V-1363 | 120 | 26 |
| PKG-2026-000151 | PJ1002 / V-2810 | 60 | 22.68 |
| PKG-2026-000144 | PJ1002 / V-2810 | 60 | 22.68 |
| PKG-2026-000150 | PJ1002 / V-2810 | 60 | 22.72 |
| 3297 | C1373 / (base model) | 145 | 33.96 |
| uzerp_ii_2781_11 | SJ4013 / V-1191 | 120 | 26.4 |
| uzerp_ii_19008_4 | TJ2079 / V-1511 | 90 | 30.22 |
