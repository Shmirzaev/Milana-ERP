# Milana ERP Project Context

Last updated: 2026-09-05

## Live old-ERP finished-goods reconciliation imported (2026-09-05)

- The authenticated old-ERP `TAYYOR MAHSULOT OMBORI` item-barcode report was audited across all 81 pages (40,228 report rows) against the 823 old-only candidate QR groups. Exactly 805 QRs had positive live stock and were imported; 18 QRs were absent/zero and remain held. The immutable manifest contains 805 packages / 60,513 pieces, 4,500 model/variant/size rows, four live-query quantity corrections, two mixed-model packages, and intentionally blank weights. Manifest SHA-256 is `8acf974442a9eda8866244e81846d2b0b1d60a3c94e2a957b9e8e721251f4f72`; the 133,962-byte guarded dry-run/import bundle SHA-256 is `a55863330db61b76db6bf059043a82235e290df39ca15d79f14205fe4c55376d`.
- PR `#50` merged the deterministic manifest builder and guarded importer as merge commit `56bd47a462f104025e0f27bad34f6ac4b393d0f5` (implementation commit `6b6bfc2155626bd7f33d879b3dffdfb7ababf637`). Local focused tests passed `19/19`, Ruff, Python compilation, and diff checks passed, and GitHub Actions run `33885620305` passed the full backend/frontend suites and immutable candidate publication. Candidate backend image `20260904_144555` has digest `sha256:f2f894e7fb9bb6b7263ef3d20470deffc9ee2661549839e5e18c627c3818e851`; it was used only as a one-shot importer and was not activated for application traffic.
- The user approved a finished-goods freeze before the write. Repeated production dry-run found zero receipt, package-number, package-barcode, or alias collisions and one required deterministic warehouse-only legacy model. Immediate pre-import backup `/opt/milana-erp/shared/backups/milana_erp_pre_old_erp_live_stock_20260905_083238.dump` is mode `0600`, 49,591,629 bytes, and has a 76,226-byte restore list with 1,069 objects. Dump SHA-256 is `020487feb691fc285ef60b4908eb3a971447dc9f99e70ee8aaa01780ee7d9402`; restore-list SHA-256 is `cd91cc54c807836d6d29fe7c3d8fdb31c52ec51e8c314d16f4cce7b4555de669`.
- One atomic transaction created exactly 805 receipts, 805 packages, 4,500 package items, 4,500 finished-goods stock rows, 805 numeric old-ERP QR aliases, 805 import scan rows, one hidden legacy model, and 937 model-size rows. Committed readback verified all 805 package graphs, 60,513 total/available pieces, 556 distinct linked models, and the immutable source payloads. Audit row `16559` records the import with entry hash `c6a014b17ef3d91051fdfb2c115720f8901bd9525f6f0d14fa393edc6a036748`.
- Finished Goods changed exactly from 6,676 packages / 484,083 pieces to 7,481 packages / 544,596 pieces. Available quantity is 544,338, reserved quantity remains 258, and there are zero stock-balance failures. Seven representative corrected, normal, and mixed-model packages resolved identically from both their numeric old-ERP QR and canonical `uzerp_ii_<number>_1` barcode. Internal/public backend health and frontend login returned HTTP 200; active containers remain running with zero restarts/OOM and no matched recent backend traceback/exception/critical/HTTP-5xx or frontend error markers.
- This was a data-only production operation. Active backend/frontend release `20260904_113556` remains unchanged in green, release `20260903_042100` remains running in blue as rollback, both source manifests remain valid, and PostgreSQL remains at `0113_variant_selling_price`.
- Security follow-up: one failed dry-run shell invocation printed the production backend environment into the private Codex task log before exiting; it did not change the database and the values were not committed or uploaded to GitHub. Treat the affected credentials as exposed and rotate them through a separately approved, coordinated credential-change window.

## Process QR size-major bulk printing deployed (2026-09-04)

- Process QR bulk printing now uses one canonical order everywhere: configured garment size first (with the natural size comparator as fallback), then model operation number, copy index, and stable label ID. The final print boundary re-sorts every requested row before QR preparation, so all labels for one size are printed before the next size even when issued-label API rows arrive interleaved. PR `#48` merged the change as commit `32bd0283619f9fa4e17defaffbc488b84edf6d07` (implementation commit `e6ccecfbee7c2262822762717f158f9a610db80b`).
- Local validation passed frontend lint, strict TypeScript, the Process QR ordering regression, and the optimized 83-route production build. A clean pinned backend environment passed Ruff, Python compilation, and all 511 backend tests. GitHub Actions run `33868720224` passed backend, frontend, and immutable release publication jobs.
- Active backend/frontend release is `20260904_113556` in the green slot. Its 2,026,759-byte deterministic archive SHA-256 is `313cb62c39bed2c0962652815712dbf99da08909fb8400ee61c4dfc02d4fa434`; the matching 674-file source-manifest SHA-256 is `8ffb4aeff68756a68956b3b76157d06e7e5be7e2961b662b8a3cb6f767922cca`. Backend image digest is `sha256:dbd2192a3cbb0b05c7392c1ca6c224a09f355c8c3aaab58ac60a9d590df42318`; frontend image digest is `sha256:e24b879601f6361830f6ff749cfcf3dda6ece48d1687fd7dad8ed82826762064`. Release `20260903_042100` remains running in the blue rollback slot.
- Verified pre-deployment backup `/opt/milana-erp/shared/backups/milana_erp_pre_20260904_113556_retry2.dump` is mode `0600`, 49,475,759 bytes, and has a 76,226-byte restore list with 1,069 objects. Dump SHA-256 is `b8292803a6879cb07bbd419f4e85bd3284a2a51059cde439a5ad1659da6d2d37`; restore-list SHA-256 is `4fade9fe92131aa0ab09bb66972bc5aa30615ba682c0a2bed25a128aea7d8946`. Migration validation was a no-op and PostgreSQL remains at `0113_variant_selling_price`.
- The warmed active-versus-candidate performance gate and public post-cutover comparison both passed with identical payload sizes and no threshold failures. Signed-in Chrome QA loaded the deployed Process QR page without browser warnings/errors. Existing manual Kroy `8812` displayed 282 issued labels as six contiguous groups in configured order (`M-46`, `L-48`, `XL-50`, `2XL-52`, `3XL-54`, `4XL-56`), with exactly 47 operations numbered sequentially from 1 through 47 inside every size. The Process QR print-all control was enabled but no physical print job was sent; the focused regression tests the mixed-size print-boundary sequence directly.
- Cutover activated backend first and frontend second. Both current symlinks and green slot states name the new release; all four internal/public health and login checks returned HTTP 200, HAProxy and both routers validated, the active backend had exactly two workers, active and rollback containers were running with zero restarts/OOM events and no matched recent error/HTTP-5xx markers, and PostgreSQL used 26 of 100 connections with zero invalid indexes.
- The completed 30-minute observation returned 60/60 public health and 60/60 public login probes at HTTP 200. Closing inspection again verified the new green release and blue rollback containers all running with zero restarts/OOM events, zero matched recent error/HTTP-5xx markers, valid manifests, routers, and HAProxy configuration, exactly two backend workers, 30 of 100 PostgreSQL connections, zero invalid indexes, and 62%/55% backend/frontend disk use. One closing `global_search` p95 sample was transiently 16.5% above the pre-cutover baseline while its median remained within budget; the immediate repeat passed every gate with `global_search` median/p95 changes of `-6.58%`/`-4.84%`, identical payloads, and improvements on all other measured routes.
- Deployment added no migration and created, edited, deleted, issued, or printed no production order, work order, Process QR label, bundle, package, inventory, shipment, user, role, permission, audit, or other business row. The only data operation was the validated pre-deployment database backup.

## New old-ERP PDF sticker batch imported (2026-09-04)

- The user supplied `newwww.zip` with 203 old-ERP PDF exports. The archive SHA-256 is `9abe3708860abdde3838fc1219d0debcb2d163e9d38ac16e0870c803f099624e`. Text extraction found 647 sticker records; one exceptional PDF page was visually verified as two additional labels with numeric QR values `1496135` and `1496136`. Seventeen trailing pages were genuinely blank. One exact repeated QR (`uzerp_ii_20972_1`) had the same model, variant, quantity, weight, and sizes in both source PDFs, so only one copy was retained. The resulting source set has 648 unique packs / 42,287 pieces and one weight intentionally blank because it is absent from the sticker.
- Production preflight found 155 QR values already present. Every existing package matched the incoming model/variant and quantity, so all 155 were skipped without changing or duplicating them. The remaining 493 packs / 32,250 pieces resolve to exactly one approved catalog model/variant across 105 identities. No unresolved, conflicting, or hidden fallback models were required.
- The immutable manifest SHA-256 is `65936ef1041008d2d80d7bdc64641a07bfee6446d7602f951eeff3e4bbbbe7c2`; the 22,802,304-byte guarded evidence/import bundle SHA-256 is `056742fcc18574856f6f665ec85550a2bb8890c621b4a32e5a6eae776ad4e895`. Production-clone dry-run, atomic apply, and committed verify all passed with 493 receipts, packages, package items, stock rows, scan rows, and QR aliases; known package weight totals 12,495.60 kg. No application code, schema, or catalog model rows changed.
- Immediate pre-import backup `/opt/milana-erp/shared/backups/milana_erp_pre_20260904_092145.dump` is 49,367,081 bytes with 1,069 restore objects and SHA-256 `1125536cbc0570d594128bac22f8cad932a1783bb8f2e9bc23ef6c543af2ade3`; its restore-list SHA-256 is `8409f89c7c15a1ddf10e1115279fd303b3046538f2cbe1692e6ec1224e8e156f`. Production dry-run reported zero collisions, and audit row `16497` records the committed import with entry hash `8e4eb6f15cbab07d821977e969bdcb90222d061939b9f89931c0be6b974aef2c`.
- Committed readback verified the full 493-package graph and 493 distinct QR aliases. Thirteen distributed public QR samples returned HTTP 200 with the correct package quantities. Finished Goods now contains 6,676 package/stock rows, 484,083 total pieces, and 483,825 available pieces, with zero stock-balance failures.
- This was a guarded data-only production import. Active backend/frontend release `20260903_042100` remains unchanged in blue, green release `20260902_134732` remains the application rollback, and PostgreSQL remains at `0113_variant_selling_price`. The active backend is running with zero restarts/OOM, and internal and public health checks returned OK.

## User-corrected QR conflict workbook imported (2026-09-04)

- The user edited the prior nine-group QR-conflict workbook in place, retaining eight incoming sticker rows, correcting four misread QR values (`uzerp_ii_18287_1`, `uzerp_ii_18882_3`, `uzerp_ii_18919_1`, and `uzerp_ii_17965_1`), and deleting five unreadable or duplicate incoming rows. The five remaining `Existing production` rows were treated as reference evidence only and were not imported or altered. The revised 1,018,073-byte workbook SHA-256 is `d8c8ebfe720f502f46a14695cc0709fb7699ad1e4d4f36c77ff83f145494448d`; workbook inspection found 13 retained data rows, 18 embedded original images, and no formula errors.
- Production comparison found all eight retained QR values unused. Six rows resolved to exactly one approved catalog model/variant. The BM-1877 / V-5209 and XJ3067 / V-5578 rows had no authoritative catalog match, so their packs use two deterministic `legacy_import` warehouse-only models that catalog endpoints exclude; postflight found zero hidden rows exposed in Models/Variants.
- The immutable manifest contains eight packs / 558 pieces across eight identities and 194.23 kg, with all eight original photos hash-verified. Manifest SHA-256 is `1338cc2ba11a31aec188b1bc6600ef37a637b2b4eb32d54ce4513a728324c2c7`; the 200,274-byte guarded import bundle SHA-256 is `cd3f07948bcfc848f7062075c35d09f526b07d404738153c7f13398a481d673d`. Production-clone dry-run, atomic apply, and committed verify all passed before the live write.
- Immediate pre-import backup `/opt/milana-erp/shared/backups/milana_erp_pre_20260904_084618.dump` is 49,362,297 bytes with 1,069 restore objects and SHA-256 `443fc2198314b0f3005010031eb48d9d283fa62f20fe737c3455bcba8f987198`; its restore-list SHA-256 is `1a72a178b2288f55debf618b7eb3b7870f3d4dc7531742200e2d1186da4284ea`. Production dry-run reported zero collisions, then one transaction created exactly eight receipts, packages, package items, stock rows, scan rows, and QR aliases plus two hidden model rows. Audit row `16489` records the import with entry hash `fdfcbf1252c50256f256ba1094b39a81bbfb377814f33303886fde68fd7f0171`.
- Committed production readback verified all eight package graphs and all eight public QR lookups at HTTP 200 with the correct quantities. Finished Goods now contains 6,183 package/stock rows, 451,833 total pieces, and 451,575 available pieces, with zero stock-balance failures.
- This was a guarded data-only deployment. Active backend/frontend release `20260903_042100` remains unchanged in blue, green release `20260902_134732` remains the application rollback, and PostgreSQL remains at `0113_variant_selling_price`. The active backend remains running with zero restarts/OOM, and internal and public health checks returned OK.

## Remaining user-completed sticker packs imported under approved fallback rules (2026-09-03)

- The remaining review set from `organized-packs-all-missing-one-sheet-with-pictures-completed.xlsx` was processed under the user's explicit fallback rules: a missing quantity becomes 60 pieces, a missing source QR is accepted without a QR alias, and duplicate QR photos are collapsed only when their model number and quantity agree. The final production manifest contains 543 new packs / 54,943 pieces across 302 model identities; 32 quantities were defaulted to 60, 307 packs have no source QR, 236 retain a real QR alias, 69 weights remain intentionally blank, and 18 size fields remain blank with the package item represented as `ASSORTED`.
- Exactly 84 packs link to approved catalog models. The other 459 packs are attached to 249 deterministic `legacy_import` warehouse-only models, which are excluded from Models/Variants catalog endpoints; committed verification found zero such models exposed in the catalog. These packs remain represented in Finished Goods stock without inventing catalog variants.
- Six workbook duplicate groups had matching model number and quantity, so one representative pack was imported and six redundant photos were dropped. One production QR collision was an exact model/quantity match and was skipped because that pack already existed. Four workbook duplicate groups and five production QR collisions disagreed on model and/or quantity; all nine groups were withheld. The review workbook contains both sides of every conflict as 18 unique rows with 18 embedded original pictures.
- Immutable manifest SHA-256 is `fb1989d07147f02e8c950069526ac473f508adf4191ef3646badadbf5f88395b`; the guarded 543-photo production bundle SHA-256 is `83c65229acf5d59114daf4b564de2bac5337588d5499093fe1d72bf636d4a187`. PR `#44` merged the importer v3, rule-based manifest/classification tooling, backward-compatible tests, and hidden-model support as merge commit `cc32cc2b68dbaaacc23d5179940040f45d830217` (implementation commit `ebfc12a3`). Focused importer tests passed `4/4`; Ruff, Python compilation, formatting, Node syntax checks, production-clone dry-run/apply/verify, and workbook re-import validation all passed.
- Immediate pre-import backup `/opt/milana-erp/shared/backups/milana_erp_pre_20260903_174938.dump` is 49,099,820 bytes with 1,069 restore objects and SHA-256 `0d0a701c8a0eae1ad2e069be12ad20f45a4a2b3eb2282869858e60bd292f096c`; its restore-list SHA-256 is `412f31736d16fcad235be49d78cb1eff503b4f264ce57c3a4670e6744e6a8b3f`. Production dry-run found zero collisions, then one transaction created exactly 543 receipts, packages, items, stock rows, and scan rows plus 236 QR aliases and 249 hidden model rows. Audit row `16486` records the import with entry hash `78355e783fe2818b279d51893a70ed40fcf0e0cb5c9f26aaa4dc9f258f70c8a0`.
- Production postflight verified all 543 packages, 236 aliases, 249 hidden models, 459 hidden-model packages, and zero hidden catalog rows. Five sampled real QR aliases returned HTTP 200 with the correct package/quantity, while two sampled no-QR internal identifiers correctly returned HTTP 404 because no QR alias was created. Finished Goods now contains exactly 6,175 package/stock rows, 451,275 total pieces, and 451,017 available pieces, with zero stock-balance failures.
- This was a guarded data-only deployment. Active backend/frontend release `20260903_042100` remains unchanged in blue, green release `20260902_134732` remains the application rollback, and PostgreSQL remains at `0113_variant_selling_price`. The active backend remains running with zero restarts/OOM, and internal and public health checks returned OK.

## Previously withheld old-ERP sticker packs resolved and imported (2026-09-03)

- The 173 packs withheld from the user-completed workbook for missing catalog identity were reviewed against the authenticated old ERP, the old-ERP 5,613-variant snapshot, current production catalog data, and their original sticker photos. Exactly 167 packs now link to authoritative existing catalog model/variant identities. Six genuinely ambiguous labels (`uzerp_ii_19809_1`, `uzerp_ii_19988_7`, `uzerp_ii_43702_1`, `uzerp_ii_79900_5`, `uzerp_ii_8832_8`, and `uzerp_ii_9569_8`) were imported under deterministic `legacy_import` warehouse-only models; catalog endpoints explicitly exclude those internal models, so they do not appear in Models/Variants.
- The immutable manifest contains 173 packs / 12,703 pieces across 133 target identities, with 4,047.09 kg of known weight and one intentionally blank weight. Manifest SHA-256 is `d39fad2944bda3dc6d067584473384521b786494b0d1f2ee5a77a4024435c87f`; the 4,494,008-byte photo/import archive SHA-256 is `eca50451a2e7a6e80e4d29b861fce2af7f8543c4e0ffa2e00ddbf10d1529a5a7`.
- A production-clone rehearsal passed dry-run, atomic apply, committed readback, repeat verification, QR/alias checks, and hidden-catalog filtering. Focused importer tests passed `3/3`; Python compilation passed. PR `#42` merged the guarded manifest builder/importer and catalog filtering as merge commit `ea6308ca94dc863c89f490f13e77c315e54eff36` (implementation commit `2c5f739e`).
- Immediate pre-import backup `/opt/milana-erp/shared/backups/milana_erp_pre_20260903_171027.dump` is 49,050,006 bytes with 1,069 restore objects and SHA-256 `e4bcc7630c62a1227ffca8dbb67716c49df5494a55b11ef9612da73b96b9edbb`; its restore-list SHA-256 is `8cdafd70dcfad29d1d4f3158ad39544d411daf1072cb3a8d61efe15e52a2d4a7`. Production dry-run found zero identifier/QR collisions, and the apply transaction created exactly 173 receipts, packages, items, stock rows, scan rows, and aliases. Audit row `16476` records the import with entry hash `0a5769269c501f7be2920e45096e1ff119bf727df24d1910cec284e54c20dfde`.
- Committed production verification found all 173 distinct packages and aliases, all six hidden models linked to exactly six packages, and zero hidden rows exposed by catalog filtering. Six public QR samples returned HTTP 200 with the correct package and quantity. Finished Goods now contains 5,632 package/stock rows and 396,332 total pieces; 396,074 pieces are available, and every stock balance is valid.
- The 14,611,179-byte consolidated remaining-review workbook (SHA-256 `0a1860ee1e3875317ab2cf9a5b125e6d7d5913ad809379e3a07f5e3e60564b88`) contains one sheet with 563 unique unresolved/conflicting photos and 563 embedded original pictures, with no duplicate row when one photo is missing multiple fields. It combines 484 incomplete rows, 53 malformed-QR groups, 10 duplicate-QR groups, and six production identifier collisions for user review; blank weight alone is not treated as an issue.
- This was a guarded data-only deployment. Active backend/frontend release `20260903_042100` remains unchanged in blue, green release `20260902_134732` remains the application rollback, and PostgreSQL remains at `0113_variant_selling_price`. The active backend stayed running with zero restarts/OOM, and internal and public health checks returned OK.

## User-completed old-ERP pack workbook imported (2026-09-03)

- The user-completed workbook `organized-packs-all-missing-one-sheet-with-pictures-completed.xlsx` (SHA-256 `42d76811d50e0a4839ba1adf520863d6514d332500d5519f625a88850f89bbe6`) contained 2,691 data rows and exactly 2,691 embedded sticker photos. The import required QR, model, variant, sizes, and quantity; weight was allowed to remain blank only where the sticker had no printed weight. No workbook text was treated as an instruction.
- Workbook preflight withheld 484 rows missing at least one required field, 53 malformed QR groups, and 10 conflicting duplicate-QR groups. Production comparison then excluded 10 packs already present exactly, 173 packs without an exact approved catalog model/variant, and 6 identifier collisions whose stored package data did not match the workbook. None of those rows was guessed, overwritten, or duplicated.
- The immutable production manifest contains 1,942 new packs / 147,815 pieces across 572 approved catalog variants, with 44,969.20 kg of known weight and 13 intentionally blank weights. Manifest SHA-256 is `eff5a8897d46b5e11ac1d55c586eca39e01dbaa8403afd9efac3cb78c7ae797e`; its 1,942 original embedded photos were hash-checked individually. The staged 51,369,580-byte evidence archive SHA-256 is `523405dac8d3cb585e28a0a28651d4f20f8f047fa946ffeef5f1942008646154`.
- A verified production snapshot was restored into isolated local database `erp_completed_packs_20260903_162751_v2`. Local dry-run, atomic apply, committed readback, and verify each resolved exactly 1,942 packs / 147,815 pieces, 1,942 receipts, package items, stock rows, scans, and QR aliases; the second dry-run failed closed on identifier collisions as intended. Ruff and Python compilation passed for the guarded import and verification tooling.
- Immediate production backup `/opt/milana-erp/shared/backups/milana_erp_pre_20260903_163616.dump` is 48,666,005 bytes with 1,069 restore objects and SHA-256 `968d1feb6f80d2dc3c43adcd417691a5872e0cc545afaec5d81ea6e33ea5c35e`. The production dry run again found zero collisions in the final manifest, after which one transaction created all 1,942 receipts, packages, package items, stock rows, scan logs, and QR aliases. Audit row `16469` records the import with entry hash `f3fb7f539b704cb5f851e7efaf5854231e1e03a00adf47321ff970c7bc54b4f7`.
- Finished Goods totals changed exactly from 3,517 to 5,459 packages and from 235,814 to 383,629 package/available pieces, with zero stock-balance failures. All 1,942 package barcodes and aliases were checked in PostgreSQL as distinct packages; 21 internal and 6 public QR API samples returned the correct package, including a seven-digit legacy code and a blank-weight pack. An initial all-HTTP sweep hit the configured global rate limit at HTTP 429; the corrected verifier checks the complete set in PostgreSQL and samples HTTP below that limit.
- This was a data-only deployment: active backend/frontend release `20260903_042100` remains unchanged in blue, release `20260902_134732` remains running in green as application rollback, and PostgreSQL remains at `0113_variant_selling_price`. Active container restart/OOM counts remain `0`/`false`, backend and frontend internal checks and both public endpoints returned HTTP 200, PostgreSQL had 33 connections and zero invalid indexes. Guarded import tooling was merged through PR `#39`; rate-safe verification was merged through PR `#40`.

## Whole-package reservation and packed-stock receipt deployed (2026-09-03)

- Branded-stock Sales orders now reserve factory-produced physical packages as indivisible bags. An exact single-package quantity is preferred; otherwise allocation chooses the greatest whole-package total that does not exceed the requested quantity. A package is either fully reserved or left fully available, so a 78-piece request uses the 78-piece bag first and the next 78-piece request can use one 60-piece bag and visibly remain `60 / 78`. Legacy aggregate/package-less stock keeps its existing piece-level behavior.
- Physical packages are eligible only when complete and backed by balanced package-item and finished-goods rows, all stock rows are available, the package has no prior reservation or sale, and its status is `received_in_storage` or `reserved`. Partial fulfillment leaves the Sales order in `reserved` status, records the shortage in its notes, and notifies Finished Goods with the prepared/required quantity; complete fulfillment remains `ready`.
- Active backend/frontend release is `20260903_042100` in the blue slot, built from merge commit `d3986992919a41dd10795dcdb02b57ba99b90463` (PR `#37`). Its deterministic 2,019,659-byte archive SHA-256 is `e37ca9a1a7f8478ba1063daa969f0b8445b4fac171501b981e585f55bb886e39`; the matching 673-file source-manifest SHA-256 is `4f613ad793b6b2c077e2799999b20df14f9e65e5d0949c52e9a945c87d2e4a95`. Backend image digest is `sha256:c808af952c17da49159295407bd17fd5c44e01512d8e26cd22a6a8971166a860`; frontend image digest is `sha256:4bfc059e47937e885b9bd5da6a35d91ea5e4c86182bab7552b73aeb3070681f0`. Release `20260902_134732` remains running in the green rollback slot.
- Local validation passed Ruff, Python compilation, all 13 branded-stock Sales tests, and all 507 backend tests. Immutable workflow `33714650826` passed backend, frontend, and release-image publication jobs. Production migration validation was a no-op and PostgreSQL remains at `0113_variant_selling_price`.
- Verified pre-change backup `/opt/milana-erp/shared/backups/erp_pre_whole_package_receipt_20260903_041000.dump` is mode `0600`, 49,074,220 bytes, and has a 1,084-line / 76,225-byte restore list. Dump SHA-256 is `a00e820e52822fd530db5b8ba57f9cf3484dca3362a0c62d41cf3005487c860e`; restore-list SHA-256 is `5e16c0642a5d731bb745f67fb5730eca32294dcfb2b1e29fb8ff34d0af94aac9`.
- The guarded dry run and apply both resolved the same scope. All 156 previously `packed` packages, totaling 10,226 pieces, were received into Finished Goods Storage through the ordinary receipt service with 156 `received_storage` scan rows. The one pre-existing partial reservation on package `105` was released (18 pieces). Full 60-piece packages `106` and `107` were preserved and attached to `SH-2026-000001`, while exact 78-piece package `1834` remains fully reserved and attached to `SH-2026-000002`. Audit rows `16265`-`16420` record the package receipts, `16421` records reservation reconciliation, and `16422` records shipment attachment.
- Production verification found zero `packed` packages, 3,707 received packages / 248,069 pieces, zero partially reserved physical packages, and zero finished-goods stock-balance failures. `SO-2026-000001` is correctly partial at 120 pieces in two complete bags: V-5646 is `60 / 60` and variant 3472 is `60 / 78`; `SH-2026-000001` shows the same two bags and 120 pieces. `SO-2026-000002` remains `ready` with four complete bags / 258 pieces, including its exact 78-piece variant-3472 bag, and `SH-2026-000002` is unchanged at four bags / 258 pieces.
- The active-versus-candidate performance gate passed with identical rows and payload bytes on all five endpoints. Median changes ranged from `-5.09%` to `+2.67%`; p95 changes ranged from `-11.55%` to `+3.72%`. The public post-cutover comparison also passed with zero payload changes; every measured median and p95 improved, with medians from `-7.54%` to `-0.83%` and p95 from `-8.96%` to `-5.23%`.
- Signed-in production Chrome QA showed `SO-2026-000001 / Zafar Aksu` directly on the all-orders Shipment floor with two attached packages / 120 pieces. Variant 3472 visibly shows `60 / 78`, one package, and `Partially prepared`; package `PKG-2026-000105` visibly contains six sizes of 10 pieces each and has total quantity 60. The V-5646 line shows `60 / 60`, and both packages remain plain `Not scanned`. Browser warnings/errors were zero and no scan, ship, deliver, or other UI mutation was submitted.
- Initial postflight found all four internal/public health and login checks at HTTP 200, both blue slots and current symlinks on `20260903_042100`, both HAProxy routers active and valid, the backend running exactly two workers, zero active-container restarts/OOM, and clean application logs. The rollback-protected observation completed 61 consecutive 30-second rounds over 1,815 seconds; every internal/public health and login probe returned HTTP 200 and both symlinks remained unchanged. Closing checks again confirmed both blue slots active, green `20260902_134732` running as rollback, zero restart/OOM events on all four containers, two backend workers, no matched backend/frontend error, traceback, critical, or HTTP-5xx log markers, active and valid routers, 34 of 100 PostgreSQL connections in use with one active connection, zero invalid indexes, zero partially reserved physical packages, and zero finished-goods stock-balance failures.

## All-orders shipment floor and variant pricing deployed (2026-09-02)

- The Shipments page now presents every open/eligible Sales order as its own full preparation workspace on one page, matching the Cutting Floor operating pattern. There is no Sales-order dropdown or second selection step. Each order shows its Sales-order number, customer, model and variant pictures, ordered and prepared quantities, attached packages, package checklist, scan control, and shipment actions. A single non-mutating search narrows the visible order workspaces; Shipment history remains read-only below them and no longer has a `Select` action.
- Order and model rows remain plain with **Not scanned** until every attached package is verified; fully scanned work turns green. The user-facing workspace no longer emits **Awaiting packages**, including lines that do not yet have a package. English, Russian, and Uzbek runtime text and a source contract cover the all-orders layout and status rule.
- Active backend/frontend release is `20260902_134732` in the green slot, built from commit `14e3aa225636bc9b238f3009032c00cc3b878367`. Its deterministic 2,015,421-byte archive SHA-256 is `d076d72e37efb4e8892b389f0f5a3e1a88283eb78e97f1ccb51916dcd944e7bb`; the matching 672-file source-manifest SHA-256 is `7d27f20e5bad70a68e3725dc951a86945a76f465d153c48f3e54deca70a449f8`. Backend image digest is `sha256:9181375f76a21522457b0d5fcf74951b26fede42b2819598e021922f2752209d`; frontend image digest is `sha256:984ed9cfeba8b85a23c84e3f61241a0fc8092f5564fed809a23b657dc6dbc7ca`. Combined release `20260902_132646` remains running in the blue rollback slot.
- This release also contains the corrected variant-selling-price implementation. Production PostgreSQL is at `0113_variant_selling_price` with exactly 1,597 model rows holding imported prices; 65 unresolved variants remain blank. The expensive bulk selling-price fields were removed from `/api/models/model-options`; Sales Order creation fetches the selected variant's price separately. No price import was rerun during the shipment deployment.
- Local validation passed the shipment contract, frontend lint, strict TypeScript, every inherited build contract, and the optimized 83-route Next.js build. Immutable workflow `33637910075` passed Ruff, Python compilation, all 506 backend tests, the full frontend job, and exact archive/image publication. The repository-wide i18n checker still reports only the same 12 unrelated pre-existing Inventory keys.
- Verified pre-cutover backup `/opt/milana-erp/shared/backups/milana_erp_pre_20260902_134732.dump` is mode `0600`, 48,575,420 bytes and has a 1,084-line / 76,225-byte restore list. Dump SHA-256 is `f281af29363a94654191e04b35e5f33547facd337d36bf8fa41bd64865c4a052`; restore-list SHA-256 is `f12f9aceeab0d524b5cbb7e3dff2024df623a64676bdb96435d5a82ee459b441`. Candidate migration validation was a no-op at Alembic head `0113_variant_selling_price`.
- The active-versus-candidate performance gate passed with identical rows and payload bytes on all five endpoints. Median changes ranged from `-6.41%` to `+2.41%`; p95 changes ranged from `-5.21%` to `+3.92%`. The public post-cutover comparison also passed with zero payload changes; medians ranged from `-2.47%` to `+2.31%` and p95 from `-5.86%` to `+4.55%`.
- Signed-in production Chrome QA showed both current Sales orders simultaneously (`SO-2026-000002 / Nigina Buxoro` and `SO-2026-000001 / Zafar Aksu`), all expected model/variant pictures, one history-status combobox only, zero **Awaiting packages** labels, and the expected plain **Not scanned** state. Search filtering was read-only and the full order list restored; browser warnings/errors were zero. No create, add-package, scan, ship, deliver, or other business action was submitted.
- The intermediate combined release `20260902_132646` first completed a rollback-protected observation with 50 consecutive 30-second sample rounds and all four internal/public health/login checks at HTTP 200. Final release `20260902_134732` then completed 60 consecutive 30-second rounds with the same four checks at HTTP 200 and zero failures. Closing checks confirmed both green slots active, blue `20260902_132646` running as rollback, matching current symlinks, active/valid HAProxy routers, zero active or rollback container restarts/OOM, exactly two backend workers, zero matched recent backend/frontend error or HTTP-5xx log markers, 25 of 100 PostgreSQL connections in use, zero invalid indexes, Alembic `0113`, 1,597 priced model rows, and the same signed-in shipment UI state with an empty browser console.
- The shipment deployment itself created, edited, or deleted no Sales order, shipment, package, stock, reservation, scan, user, role, permission, or audit row. The only shipment-task database write was the verified backup. The pricing migration/import was completed separately before this combined application release and is recorded above.

## Previous shipment selector release (superseded, 2026-09-02)

- The Shipments page now has one searchable Sales-order selector that combines eligible orders with orders that already have shipments. Every choice shows the Sales-order number and customer; fully scanned orders are green, while incomplete and not-yet-created orders remain plain. Selecting an existing shipment opens it directly, and selecting an order without a shipment immediately previews its model/variant pictures, requested quantities, ready packages, storage locations, and scan state on the same page.
- Preparation rows and package rows are green only after every attached package for that row is actually scanned. A package that is prepared but not scanned is now labelled **Not scanned** and remains plain; **Awaiting packages** is reserved for an order line with no prepared package quantity.
- New read-only `GET /api/shipments/sales-order/{sales_order_id}/preparation` provides the pre-creation view. Shipment list responses now include required, scanned, and remaining package counts plus a completion flag using only matched scans for packages actually attached to that shipment.
- Root-cause diagnosis for the reported `SO-2026-000002` mismatch found that branded-order reservation could choose finished-goods rows whose packages were still only `packed`. Future allocation now accepts package-backed stock only when its package is `received_in_storage` or `reserved`, while retaining compatibility with legacy package-less stock rows. Regression coverage proves a lower-ID packed package is skipped in favor of a received package.
- Sales-order creation no longer performs a warehouse-wide legacy metadata repair. Repair is limited to requested branded models, locked stock candidates are reused for validation/allocation, and regression coverage keeps the create path within 30 SELECTs even with 250 unrelated legacy stock rows. The local measured request completed in 0.04 seconds instead of the observed production requests of 8.1-8.7 seconds; reservation, shortage, notification, audit, and transaction rules remain unchanged.
- Active backend/frontend release is `20260902_113706` in the green slot, built from merge commit `e6a51d1f32eaee5bcefbf725aeb64ca3b0edb6f8` (PR `#30`). Its deterministic 1,986,718-byte archive SHA-256 is `b14f2e2db077cb86b3a31c0e9622b3647efab186d8bb88634684211b0432040c`; the matching 667-file source-manifest SHA-256 is `addbbe75e43152a6a26d158bf8adb703c5d83faf7122bbef77c6873bf69f3d64`. Backend image digest is `sha256:dda4bd7144c554e563cb3911381fab50168ff0197ffaf365946c72be6748f29c`; frontend image digest is `sha256:3c40b5b53a5e00e82b0978c8457f1e2bc3b66dcdd99cdbad55837838aaee7cb8`. Release `20260902_084754` remains running in the blue rollback slot.
- Local and GitHub validation passed Ruff, Python compilation, all 504 backend tests, frontend lint, strict TypeScript, the shipment contract, every inherited production build contract, the optimized 83-route Next.js build, and immutable release workflow `33625539719`. The repository-wide i18n checker still reports only the same 12 unrelated pre-existing Inventory roll/label keys.
- Verified pre-deployment backup `/opt/milana-erp/shared/backups/milana_erp_pre_20260902_113706.dump` is mode `0600`, 48,893,636 bytes and 1,067 restore objects; dump SHA-256 is `f51da9022a82a7ede911afbb41e46bef9ca20618f44499485cbca135786b3e8b`, and the 76,070-byte restore-list SHA-256 is `3ac00ff963d76419d1c416f36f16893e7fb0aaa1d4463843344858f7ec31fe1e`. The migration was a no-op and PostgreSQL remains at `0112_price_calc_requests`.
- The candidate performance gate passed with identical rows and payload bytes. The public post-cutover comparison also passed: global search `+5.40%` median / `+8.36%` p95, inventory batches `+1.28%` / `+6.02%`, inventory stock `+0.20%` / `-8.15%`, model groups `-2.59%` / `+0.57%`, and model options `+2.10%` / `+4.13%`.
- Signed-in production Chrome QA verified the single searchable order dropdown, Sales-order number plus client labels, plain **Not scanned** state, model and variant pictures, existing-shipment selection, and the one-page preparation/checklist/history layout with zero browser warnings or errors. No shipment action or scan was submitted during QA.
- A guarded post-deployment correction repaired the pre-existing `SO-2026-000002` mismatch. It released only reservation rows `59`-`67` (78 pieces) from packed packages `104`/`105`, preserved the other Sales order's 8-piece reservation, reserved received warehouse package `OLD-20648-1` (`package_id=1834`, `stock_id=2821`) for the same order, and attached it to `SH-2026-000002`. The shipment now shows all four variants prepared, 4 packages / 258 pieces, and 0/4 **Not scanned**. Stock invariants balance on every touched row; audit `16235` records the correction.
- Both current symlinks and green slot states name the release; both HAProxy routers validate, both active and rollback containers remain running with zero restarts/OOM, the active backend has exactly two workers, and all internal/public health and login checks return HTTP 200. PostgreSQL had 69 connections of headroom and zero invalid indexes. One unrelated pre-existing forecasting-dashboard request returned HTTP 500 because a BOM row has a null `item_id`; shipment workflow requests and subsequent logs were clean.
- The completed observation ran 60 consecutive 30-second rounds of public health and login probes over 1,776 seconds with zero failures; combined with the pre-monitor cutover checks, the release remained continuously healthy for more than 35 minutes. Closing checks again found both green slots active, both blue rollback containers running, zero restarts/OOM, zero matched backend/frontend error or HTTP-5xx markers since shipment QA began, 33 of 100 PostgreSQL connections in use, zero invalid indexes, all four internal/public checks at HTTP 200, and the same signed-in shipment UI state with an empty browser console.

## Variant selling prices pre-deployment implementation history (superseded, 2026-09-02)

- A clean local branch adds a nullable USD selling price to each exact `Model` variant, including source, update timestamp, and completed price-request traceability. No price is copied when a new variant is created.
- Selecting a variant on a new Sales Order fills that variant's current selling price while keeping the field editable. The backend independently applies the variant price when a client omits `unit_price`; an explicit zero or another entered price remains an intentional override.
- When all price-calculation departments are complete and Finance enters a positive selling price, that request now updates the exact linked variant and records the request as its source. Incomplete or cleared requests do not erase a previously approved variant price.
- The authenticated catalog review contained 1,749 cards. The reviewed import manifest contains 1,660 unique readable USD prices; 1,595 identities match the latest production catalog snapshot after exact matching plus 22 globally unique variant-number corrections. Two already-duplicated ERP identities receive the same price on both existing rows; the importer never creates a model or variant. Sixty-five readable prices remain withheld because no exact or globally unique ERP variant match exists, and 61 source cards were excluded because 36 had no positive price and 25 had no variant number.
- Local migration, guarded import, idempotency check, API/workflow tests, strict TypeScript, lint, source contracts, and signed-in browser QA passed. This pre-deployment state was superseded by the production rollout recorded at the top of this file.

## Shipment preparation workspace deployed (2026-09-02)

- The Shipments page is now one continuous preparation workspace: create/select a shipment, scan packages, review every model/variant and ordered color/size quantity, inspect the package checklist and storage locations, complete shipment actions, and search shipment history without leaving the page. Desktop uses dense tables; phone/scanner widths use readable cards.
- Preparation rows are visible from the Sales order before any package exists. Each row shows the model-catalog picture, variant/material picture, business model and variant numbers, requested color/size breakdown, prepared versus required quantity, package verification count, and readiness state. Physical package rows show their contents, storage location, quantity, and scanned state.
- New read-only `GET /api/shipments/{shipment_id}/preparation` composes expected Sales-order lines with package-backed quantities and scan state. Existing package eligibility, stock, shipping, and delivery mutation rules remain authoritative and unchanged. English, Russian, and Uzbek runtime labels are included.
- Active backend/frontend release is `20260902_084754` in the blue slot, built from merge commit `b817ffdd31d2f7b3cfef9c4e998e2eac3806f568` (implementation PR `#27`, release-build correction PR `#28`). Its deterministic archive is 1,980,857 bytes with SHA-256 `7e96cddabc974cde9f2f83271eb83edd4b28559ee3454cb0d882dda587e8afa2`; the matching 667-file source-manifest SHA-256 is `2a5844f513283c8cb3f4128865159d8a0f47a81f95acf979bc6e9353967fb0ac`. Backend image digest is `sha256:e0c73f429f3cd8ddd9f77b70c87fee32450f7288482959e4fa69841c72e024ca`; frontend image digest is `sha256:6d6b778633ec7262190b0c7e57a0adf7c6910fd69957757791c1237d5107494c`. Release `20260902_065540` remains running in the green rollback slot.
- Local and GitHub validation passed all 502 backend tests, full frontend lint, strict TypeScript, shipment-preparation and inherited production build contracts, and the optimized 83-route Next.js build. Immutable release workflow `33610640097` built and published the exact archive and both images. The repository-wide i18n checker retains only 12 unrelated pre-existing Inventory roll/label keys.
- Preliminary release `20260902_083544` stopped inside the immutable workflow before staging because a frontend-only image build could not read the backend source for the new cross-stack contract. PR `#28` made the backend portion conditional only when that source tree is absent; an exact local frontend image build and the complete replacement workflow passed. The preliminary release never reached either production slot.
- Verified pre-deployment backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260902_084754.dump`, mode `0600`, 48,418,191 bytes and 1,082 restore-list lines; dump SHA-256 `cb1a58b0acf0b6849f36a37bbf794b7258415f7af269987547195c7365e4c79e`, restore-list size 76,071 bytes, and restore-list SHA-256 `4345b9663afcd9f47a756350fdbc69d35b8e55f86bb78762d5ee3e9dd2db8732`. Alembic was a no-op and remains at `0112_price_calc_requests`.
- The initial candidate gate passed. The first post-cutover comparison then reported a transient `model_groups` p95 spike of `+47.57%` while result rows and payload bytes matched, so both roles were immediately rolled back. Two consecutive settled inactive-slot comparisons passed; the guarded cutover was retried once. Final post-cutover changes were: global search `-5.34%` median / `-8.57%` p95, inventory batches `-2.81%` / `-2.66%`, inventory stock `-0.85%` / `-8.13%`, model groups `+0.41%` / `+3.10%`, and model options `-6.59%` / `-7.45%`, with identical result rows and payload bytes.
- Signed-in production Chrome QA displayed the selected shipment's Sales-order preparation lines with both model and variant pictures, ordered color/size quantities, prepared state, package verification state, the empty-package guidance, action controls, and searchable history on one page. Desktop and phone-width checks reported zero browser warnings or errors; no action button or mutating form was submitted.
- Both current symlinks and blue slot states name the new release; all four internal/public health and login checks pass, both HAProxy routers validate, the active backend has exactly two workers, and active plus rollback containers are running with zero restarts/OOM events and no matched traceback, exception, critical, or HTTP-5xx log markers. PostgreSQL used 27 of 100 connections with zero invalid indexes; backend/frontend disk use was 59%/54%.
- The final activation remained live for more than 36 minutes before closing checks. Forty consecutive automated 30-second sample rounds of each internal backend, internal frontend, public health, and public login endpoint passed, followed by four successful closing checks. Closing inspection again found both blue slots active, both green rollback containers running, zero restarts/OOM and matched error markers, 32 of 100 PostgreSQL connections, and zero invalid indexes.
- After rollout, the user explicitly requested deletion of empty shipment `SH-2026-000001` so Sales Order `SO-2026-000001` could receive a replacement. A locked transaction reverified shipment ID `3` was `created`, never shipped/delivered, and had zero package links and zero scan logs; it deleted only that shipment and wrote audit row `16207`. No packs existed for the Sales order, so no package, finished-goods stock, reservation, or warehouse movement was required. Post-checks found zero matching shipment rows, zero package/scan links, and zero open shipments for the Sales order.
- The deletion has its own verified pre-change backup: `/opt/milana-erp/shared/backups/milana_erp_pre_delete_shipment_3_20260902_095300.dump`, mode `0600`, 48,418,176 bytes and 1,082 restore-list lines; dump SHA-256 `8158c28d13727c63f581398b50433521caae1e6443ef0d7835fd8fa03b52a76d`, restore-list size 76,071 bytes, and restore-list SHA-256 `fbd3aff88ea3473c36bc79e5f7f522e157da18f875313f03f722292d62e8cdd5`.
- Security follow-up: the user-supplied SSH password was placed in chat and a failed backup wrapper rendered the database connection credential in terminal output. Treat both credentials as compromised and rotate them; rotation was not performed in this task because it would affect access and running services.
- Deployment added no migration and changed no production business row. The only later business mutation was the separately authorized deletion of that one empty shipment plus its audit row; no package, scan, Sales order, stock, reservation, user, role, permission, or other row changed.

## Searchable sales-order models and inline customer creation deployed (2026-09-02)

- The Create sales order page now uses the existing searchable selector for branded-stock models. Search matches model labels plus their model-group identity, preserves full/not-full pack counts, and keeps the selected stock option and availability details visible. The old long native option-group menu is gone.
- Users who have `sales.customers` permission now see an **Add customer** action beside Customer. Its in-place modal creates a customer with the existing API, refreshes and selects the new customer, and preserves the unsaved order draft. Users without that permission do not see the action. English, Russian, and Uzbek runtime locale bundles contain the new copy.
- Active backend/frontend release is `20260902_065540` in the green slot, built from merge commit `4da7cbfe579f8f8c94acb985e54ca8e8b6278ef7` (implementation PR `#24`, locale correction PR `#25`). Its deterministic archive is 1,968,864 bytes with SHA-256 `657d9687bc99a35899f4d864f7926653215e283330d7f868778b6c2ca07bd8ed`; the matching 665-file source-manifest SHA-256 is `904806190fcfdb7f64a7b4063362ada8ab8795382164ef2054dd8d9ca3be29bc`. Backend image digest is `sha256:0c046950e5082b7e27cf553f7a8a6fd4a2de0b7d2df9cdd5937cc8e390320b41`; frontend image digest is `sha256:b286611643e8eddf2b96f2f44f0ed07643243c95d17fee9783edfa7075e09fda`. Release `20260831_130708` remains running in the blue rollback slot.
- Local validation passed Ruff, Python compilation, all 501 backend tests, full frontend lint, strict TypeScript, the focused sales-order selection/model-option/physical-pack contracts, all 19 production build contracts, and the optimized 83-route Next.js build. GitHub Actions and immutable-image workflow `33601085970` passed. The standalone i18n checker continues to report only 12 unrelated pre-existing Inventory roll/label keys.
- Signed-in production browser QA verified the localized Add customer button, name/phone/email/address modal and cancellation without submission; it switched to Branded stock sale, typed `5646`, found and selected `5646 - 33 packs`, displayed `33 packs available (1,980 pcs)`, confirmed the native option groups are absent, and found no browser console errors. It restored the form to Client order and created no customer or order.
- The first built candidate, `20260902_062807`, reached traffic briefly, where signed-in QA caught a raw translation key because the initial copy had been added to an obsolete dictionary rather than the runtime locale bundles. Both roles were immediately rolled back, the locale bundles and build contract were corrected, and only the corrected immutable release was redeployed.
- Verified pre-deployment backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260902_065540.dump`, 48,417,583 bytes and 1,067 restore objects; dump SHA-256 `7195dd234fc1ba2ec670bb751513e79c973623a3e59b0ef8e684037590d5f3ed`, restore-list size 76,071 bytes, and restore-list SHA-256 `60c155784ccce99963ade8f63659fda4410ca2a0779db61ceedcdc5c768b68ec`. The migration was a no-op and PostgreSQL remains at `0112_price_calc_requests`.
- The single first corrected post-cutover benchmark showed a cross-endpoint timing spike and triggered the required automatic rollback. Host and result-shape checks found no application fault. Three alternating isolated blue/green comparisons then passed in aggregate, so the guarded cutover was retried. Final post-cutover median-of-three changes were: global search `+1.51%` median / `+2.54%` p95, inventory batches `+0.07%` / `+0.59%`, inventory stock `+2.15%` / `+5.22%`, model groups `+0.63%` / `+2.53%`, and model options `+0.29%` / `-2.97%`; every result count and payload size matched.
- Cutover activated backend first and frontend second. Both current symlinks and green slot states name the corrected release; all four internal/public health and login checks returned HTTP 200, HAProxy/router validation passed on both VMs, the active backend has exactly two workers, and active plus rollback containers are running with zero restarts/OOM events and no matched traceback, exception, critical, or HTTP-5xx log markers. PostgreSQL used 28 of 100 connections with zero invalid indexes.
- The completed observation kept the release live for more than 31 minutes from frontend cutover. After the immediate postflight, 54 consecutive automated samples of each internal backend, internal frontend, public health, and public login endpoint all returned HTTP 200 over 1,605 seconds. Closing checks again verified both green slots active, both blue rollback containers running, zero restarts/OOM and matched error markers, valid source manifests and routers, 29 of 100 PostgreSQL connections, zero invalid indexes, and the same successful signed-in UI behavior.
- Deployment added no migration and created, edited, or deleted no customer, sales order, stock, reservation, package, shipment, user, role, permission, audit, or other business row. Only the validated database backup, release/slot metadata, current symlinks, and read-only verification queries were performed.

## Fabric inventory archive deployed (2026-08-31)

- Fabric and semi-finished stock-batch deletion is now an archive operation. The batch row, receipt/usage movements, linked planning/cutting history, and released reservation history remain intact; any remaining quantity is removed through the existing audited `StockBatchDelete` issue movement. Unused fabric receipts are no longer physically deleted. Accessory deletion behavior is unchanged.
- A fabric batch is automatically archived when consumption or a stock adjustment reduces it to zero. The normal active Inventory and Planning selectors continue to exclude archived/empty stock. The archive query also includes legacy zero-balance material batches that predate `archived_at`, deriving their archive date and used quantity from their movement history without a production data rewrite.
- Fabric Storage now links to a read-only EN/RU/UZ archive page with server-side search, received-date and supplier filters, pagination, pictures, received/used quantities, warehouse/supplier details, archive time, and a truthful Deleted or Used up reason. There is no restore action, so viewing history cannot mint stock.
- Active backend/frontend release is `20260831_130708` in the blue slot, built from merge commit `cfb0907693a9fd62a740085c253f6fb2a21b79db` (implementation PR `#21`, corrective PR `#22`). Its deterministic archive SHA-256 is `2ac3e42e1ddbcfce4b9d40e98db6636fcd49736aa6840b1b26cd083e268d7816`; the matching 664-file source-manifest SHA-256 is `77b0b6ade002cffc1a55820c29ffb6df8bb2cd778c16ee1ef59e34b21b308c89`. Backend image digest is `sha256:570c48db94ca81420c0e3b455dcd7f4bfb7c794cea88835d3bb55b2418f9b2c1`; frontend image digest is `sha256:2c99d5298ae5f32408649f1e800b3a4b0ae91f34edfd88481fe9912e6e115939`. Release `20260831_111523` remains running in the green rollback slot.
- Local and GitHub validation passed Ruff, Python compilation, all 501 backend tests, full frontend lint, strict TypeScript, the archive contract, every inherited production build contract, and the optimized 83-route Next.js build. The i18n checker reports only the same 12 unrelated pre-existing Inventory roll/label keys.
- Initial candidate release `20260831_124910` was stopped before traffic cutover by the mandatory performance gate: normal `/api/inventory/batches` payload bytes were `16.76%` above baseline because archive-only response fields were serialized for active rows. The correction keeps those six archive fields exclusive to `archived=true` requests and adds an active-response regression assertion. No traffic reached that rejected candidate.
- Verified pre-deployment backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260831_130708.dump`, 48,338,550 bytes and 1,067 restore objects; dump SHA-256 `b789c7fb0d8c512aee629fb83afe427753bb1b5c0290428356e2caf21554143b`, restore-list SHA-256 `d2ee3e325b749bcdaea8cec7af74ca0bf7e43922b67a40a557d96a541ed880fc`. Alembic was a no-op and remains at `0112_price_calc_requests`.
- The first corrected candidate process set showed inconsistent timing regressions across unrelated endpoints while row counts and payload bytes matched; host load, CPU, database, HTTP, container limits, and reversed-order/fresh-baseline diagnostics found no infrastructure or result-shape fault. Traffic remained on green. Restaging only the inactive candidate produced a clean mandatory gate: identical rows and payload bytes, median changes from `-10.17%` to `-1.96%`, and p95 changes from `-10.66%` to `+12.83%`, all within budget. The post-cutover benchmark also completed successfully.
- Candidate read-only API QA returned 475 archived material batches, sampled 50 archive and 50 active rows, found both deleted and used reasons, confirmed no active/archive overlap, and matched the same database snapshot before and after: 866 batches, 29 explicitly archived material batches, 475 zero-balance material batches, 1,589 movements, and 15,918 audit rows. Signed-in Chrome QA showed the EN archive table with 50 of 475 results, pictures, supplier/warehouse details, received/used quantities, Deleted and Used up reasons, pagination/filter controls, and zero browser warnings/errors.
- Cutover activated backend first and frontend second. Both current symlinks and blue slot states name the new release; all four internal/public health and login checks passed, manifests and HAProxy/router validation passed, the active backend has exactly two workers, and active plus rollback containers are running with zero restarts/OOM events and no matched error/HTTP-5xx log markers. Closing PostgreSQL usage was 24 of 100 connections with zero invalid indexes; backend/frontend disk use was 58%/53%.
- The completed 30-minute observation returned 60/60 public health and 60/60 public login probes at HTTP 200 over 1,807.2 seconds. Closing checks again verified blue active, green rollback, exact image labels/digests, current manifests, router configuration, public endpoints, and the post-cutover benchmark.
- Deployment created no migration and created, edited, or deleted no production inventory quantity, reservation, stock movement, order, user, role, permission, audit, or other business row. Only the validated database backup and read-only verification queries were performed.

## Eco Cotton process tracking includes Usluga (2026-08-31)

- Active backend/frontend release is `20260831_111523` in the green slot, built from merge commit `a93c576a6a1d07801a5c7364534300baa2b31849` (implementation PR `#19`). Its 662-file source-manifest SHA-256 is `d3a0047ad4aedfa65bbbb487f957562ba500371ac02fb4a45ace60268a914531`; deterministic archive SHA-256 is `69b4a1b9ca52215749527ef7653bd0704d78267208c2f55c30c5089fc338cf01`. Backend image digest is `sha256:b08dc06847de5fea74b9e9211e137934d45266e705524054f347283cf17d2e48`; frontend image digest is `sha256:45a5c9e49029fd5e1232c7df6914cb8af5534a8128138fc7c0cb185743d9b948`. Release `20260831_100414` remains running in the blue rollback slot.
- `/processes?factory=ECO` now shows active standard and Usluga orders together under the authoritative Eco sewing-factory route. Unscoped process-tracking consumers remain standard-only, other factories cannot leak into the Eco view, and an Eco session requesting Milana is rejected. Usluga outside-company names/references participate in search and the outside-company name is displayed as Customer; the printable export follows the same factory/source scope. The existing table, filters, sorting, pagination, stage detail, audit, and print layout remain unchanged, with truthful EN/RU/UZ subtitle copy.
- GitHub Actions run `33386120056` passed Ruff, Python compilation, all 500 backend tests, frontend lint, strict TypeScript, every production build contract, and the optimized 82-route Next.js build. The immutable release archive and both GHCR images were built once from the merged commit. Local validation also passed the focused 3-test tracking suite, an 18-test wider Usluga/process/security selection, Ruff, compilation, the Eco contract, lint, strict TypeScript, all production contracts, and the optimized build; the i18n checker retained only the same 12 unrelated Inventory keys.
- Verified pre-deployment backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260831_111523.dump`, 48,252,340 bytes and 1,067 restore objects; dump SHA-256 `75010ca011f89a2d53a7cdd2d3848ec13ecf1310991c01eacba20fd956d5ad00`; restore-list SHA-256 `dd71944035927299306d721a4af6478e0fd99c350361162dba1f127a33108406`. The migration was a no-op and PostgreSQL remains at `0112_price_calc_requests`.
- The pre-cutover performance gate passed with identical rows and payload bytes across all five searches. Candidate median changes ranged from `-0.22%` to `+8.08%` and p95 changes from `-17.13%` to `+13.40%`, all within the release budgets; post-cutover and closing benchmarks also passed.
- Candidate read-only QA matched the API exactly to the authoritative production scope: 7 active Eco orders, comprising 1 standard and 6 Usluga. It verified all 6 Usluga customer displays and printable rows, customer/reference search, zero Usluga rows in the unscoped consumer, and HTTP 403 for a Milana query under the Eco token. Signed-in Chrome QA independently displayed the same 7 rows and 6 `USL-*` numbers with real customer names, the Usluga-aware subtitle, and zero browser warnings/errors, then restored the session to Milana.
- Cutover activated backend first and frontend second. Both current symlinks and green slot states name the new release; public and internal health/login returned HTTP 200, HAProxy and both routers validated, the active backend had exactly two workers, active containers had zero restarts/OOM events and no matched recent error/HTTP-5xx markers, PostgreSQL used 22 of 100 connections with zero invalid indexes, and backend/frontend disk use was 57%/53%.
- The completed 30-minute observation returned 61/61 public health and 61/61 public login probes at HTTP 200 over 1,817.1 seconds. Closing inspection again verified active green and rollback blue containers all running with zero restarts/OOM events and zero matched error markers, valid manifests and HAProxy configuration, 24 of 100 PostgreSQL connections, zero invalid indexes, unchanged 57%/53% disk use, and successful closing benchmark/public checks.
- Deployment added no migration and created, edited, or deleted no production order, work order, Usluga order, bundle, package, inventory, user, role, permission, audit, or other business row. The only data operation was the validated pre-deployment database backup.

## Sewing assignment moves and reduced Daily Sewing Excel deployed (2026-08-29)

- Active backend/frontend release is `20260829_112849` in the green slot, built from merge commit `aa6ddc99b4a2f2840406ee4e5000c9b15a62552d`. Its 661-file source-manifest SHA-256 is `9b0eee10f6ef3e2ed172f81934e182fd67e0d9dd462a764baeadde867e27380e`; the deterministic archive SHA-256 is `3b70b11b544455c0eb92ceee167c08a9165b16fd82c36bb93baf5bc7255b0050`. Backend image digest is `sha256:9819c56be536d6708ce53c1359859a5830f9537a5ba167c99a61f9e41bafb447`; frontend image digest is `sha256:5f10a06d5668e4fc420f60e59f71ebfbde84f5e4bdcf4b82f9152fa33b66f900`. Release `20260829_081957` remains running in the blue rollback slot.
- Every expanded Sewing Flows line now shows a compact Move action for each active assigned work row. Supervisors select another active line in the same factory; the assignment, its completed quantity, status, batch scope, and deadline remain intact, while both line views and workload summaries refresh immediately. The API verifies access to both lines, blocks cross-factory/inactive/finished moves, revalidates the factory route, updates the convenience primary line when appropriate, and records the transfer audit event.
- Daily Sewing Report Excel exports contain one `Entries` worksheet with only number, sewing line, model number, Kroy number, and sewn quantity. The report period and generated timestamp remain above the table; the PDF export is unchanged.
- Validation passed Ruff, Python compilation, all 499 backend tests, full frontend lint, strict TypeScript, every build contract, and the optimized 82-route Next.js build locally and in GitHub Actions. The repository-wide i18n checker still reports 12 unrelated pre-existing Inventory roll/label keys; the new Move key is present in English, Russian, and Uzbek.
- Verified pre-deployment backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260829_112849.dump`, mode `0600`, 47,780,173 bytes and 1,078 restore objects; dump SHA-256 `4421f4c3b35f19d4770fbf2a3cf3837a083e458df36162d0b61d5cc302acc4f4`, restore-list size 76,071 bytes, and restore-list SHA-256 `808910351ffdd3009adb314c3bd8189569d774e1e77d6a3bdb78dc6eabe767e8`. `alembic upgrade head` completed and the database remains at `0112_price_calc_requests`.
- The first warmed candidate comparison had one transient `model_groups` p95 outlier while its median improved; traffic stayed on blue. The repeat gate passed with identical payload bytes and changes within budget across all five searches: medians ranged from `-7.87%` to `+3.06%`, and p95 from `-8.32%` to `+7.05%`. A repeated public-route benchmark also passed with identical payload bytes and no regression failures.
- Signed-in, read-only Chrome QA confirmed Move on every active row of an expanded line, opened a destination dialog listing only the other active Milana lines, and closed it without submitting. The production Excel download was inspected directly: one `Entries` worksheet, exactly the five requested columns, and no extra report-data columns. Browser console errors were zero.
- Cutover switched backend first and frontend second. Both current symlinks and green slot states name the new release; all four internal/public health and login checks returned HTTP 200, HAProxy validation and both routers passed, both containers had zero restarts/OOM and zero critical-log matches, the backend had exactly two workers, PostgreSQL used 27 of 100 connections, and invalid indexes were zero.
- The completed observation returned 52/52 public health and 52/52 public login probes at HTTP 200 over 1,811 seconds. Closing inspection again found zero active/rollback container restarts or OOM events, zero recent critical/error/HTTP-5xx log matches, 32 of 100 PostgreSQL connections in use, zero invalid indexes, 58%/53% backend/frontend disk use, valid release manifests and HAProxy configuration, and both blue rollback containers still running.
- Deployment created no assignment move, sewing report, inventory quantity, order, bundle, package, shipment, user, role, permission, or other business row. No schema migration was added; the only data operation was the validated pre-deployment database backup.

## Payroll Scan latency fix deployed (2026-08-29)

- Active backend/frontend release is `20260829_081957` in the blue slot, built from Git commit `2ac412103901c1c70db326194f92ecce7784b4de`. Its 660-file source-manifest SHA-256 is `8f3e00f7cb41e08d6ad11aa54a44c0980bb79eb46d1a58c5564596bca9e2cfe8`. Release `20260829_065045` remains running in the green rollback slot. Database head remains `0112_price_calc_requests`.
- Exact 9-digit numeric work scans no longer wait for the legacy 140 ms input-settling timer. When an employee is already selected, one factory-scoped `POST /api/payroll/scan/numeric-work` now resolves the authoritative issued label and persists through the existing payroll ledger/idempotency logic in one round trip. Compact and legacy QR formats keep their previous parsing and timing behavior.
- Single-row fallback saves now use the existing single-record endpoint; the bulk endpoint remains reserved for restored multi-row recovery. Scanner-history serialization is deferred to browser idle time with a synchronous unload flush, removing whole-history JSON work from the scan interaction. Existing duplicate, return, retry, permission, factory, and automatic-save behavior remains intact.
- Validation passed 498 backend tests, Ruff, Python compilation, full frontend lint, strict TypeScript, every build contract, and the optimized 82-route Next.js build locally and in GitHub Actions. Candidate production parity checks returned identical result counts and payload bytes with no regression failures.
- The isolated production candidate replayed an already-recorded label 15 times through the new endpoint: median `17.31 ms`, p95 `37.85 ms`, every response returned the same existing record, and pre/post label, record, table-count, and audit-count fingerprints were identical. The gate created or changed no payroll or other business row.
- Verified pre-deployment backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260829_081957.dump`, 47,772,826 bytes and 1,067 restore objects; dump SHA-256 `dcb61743ede11f3031c45b4888482e4641fdd40c146512e90f467466d5698ca4`, restore-list SHA-256 `dbeb69c6d8238eb83778d4695e1b6cc7c159108550d0f59ac2cbb4814f2c8b27`.
- Cutover switched backend first and frontend second. Internal and public health/login checks returned HTTP 200, both blue containers had zero restarts and zero OOM events, PostgreSQL used 26 of 100 connections with zero invalid indexes, and immediate post-cutover logs had no matched traceback, exception, critical, or HTTP 5xx markers.
- The completed 30-minute observation returned 57/57 public health and 57/57 public login probes at HTTP 200. Closing inspection again found zero restarts, zero OOM events, no matched recent error/5xx markers, 29 of 100 PostgreSQL connections in use, zero invalid indexes, 57%/53% backend/frontend disk use, valid release manifests and HAProxy configuration, and a successful post-cutover benchmark. The Windows browser helper stopped before navigation because it could not establish the existing Chrome URL confidently; no browser input was sent. Authenticated candidate API QA and public route/authorization checks passed, but a signed-in visual browser-console check remains the only uncompleted QA item.

## Guarded performance and zero-downtime production release (2026-08-29)

- Active backend/frontend release is `20260829_065045` in the green slot, built from Git commit `6748e54e7334715cbf4c653d4749a608e66c19c6`. Its 660-file source-manifest SHA-256 is `e6bf06953240e994afe72e0d2f55d55bd689d98b2e4a70711065e3da617a5b8a`. Release `20260829_060947` remains live in the blue rollback slot. Both public health and login returned HTTP 200 after cutover; database head remains `0112_price_calc_requests`.
- The final production observation completed 60/60 health probes and 60/60 login probes at HTTP 200 over 30 minutes. Closing postflight found zero container restarts, OOM events, recent error markers, or invalid indexes; PostgreSQL used 32 of 100 connections while both slots remained live, and backend/frontend disk use was 57%/53%.
- Production now uses prebuilt immutable GHCR images, loopback-only blue/green application slots, and a stable HAProxy `milana-router` on each application VM. Production VMs no longer install application dependencies or compile backend/frontend releases during a normal deployment.
- The release preserves application behavior while adding a deterministic source/base drift gate, complete backend/frontend CI, validated PostgreSQL backup, inactive-slot warm-up, production-data result/payload parity checks, and median/p95 regression budgets before graceful traffic activation. The complete backend suite passed 497 tests; frontend lint, strict TypeScript, production contracts, and optimized build passed in CI.
- Pre-cutover production-data benchmarks returned identical row counts and payload bytes. For the final green release, candidate medians improved by 9.61% for global search, 5.16% for inventory batches, 12.13% for inventory stock, 9.61% for model groups, and 8.77% for model options; corresponding p95 changes were -13.09%, -5.36%, -2.80%, -9.34%, and -10.11%.
- Signed-in production QA exposed and fixed a duplicate Inventory navigation race between its 200 ms type-to-search timer and the explicit Search button. Both behaviors remain: typing still searches automatically, while button/Enter cancels the pending timer and applies immediately. Batch `16936`/`16937` read-only results were correct, measured type-to-visible response was 393 ms, and browser console checks found zero warnings/errors.
- Verified final pre-deployment backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260829_065045.dump`, 47,770,451 bytes, 1,067 restore objects, dump SHA-256 `cad9fd60415151a9316ba2ec40838d52bcebd608bd560a467b78d647ad614a31`, restore-list SHA-256 `59807f8ac505b01cf513f754caff40b47aba5c4756ed23ae05a420c11d84d1c0`.
- Deployment created no business rows and changed no business data. Manifest-verified retention archived and removed 199 old generated release trees on the backend and 196 on the frontend while protecting the active and newest five releases; archived source remains under `/opt/milana-erp/shared/release-archives`. Frontend disk use fell from 83% to 52%, removing the main repeated-deploy degradation/failure pressure.
- `DEPLOYMENT.md` is the required future workflow: start from the recorded clean production baseline, push a reviewed commit, let GitHub Actions build once, stage the inactive slot, back up/migrate, run parity/performance and signed-in read-only QA gates, activate backend then frontend, observe, and retain rollback capacity. Never deploy from the historically dirty `C:\ERP` checkout.
- Repository `AGENTS.md` now requires every file-changing Codex task to create or use a clean dedicated worktree from verified `origin/main` before its first edit, stage only named paths, and report its worktree/branch/commit/test/deployment state. Direct deployable edits and releases from the legacy `C:\ERP` checkout are prohibited.

## Bounded inventory-search rendering follow-up (2026-08-29)

- Follow-up release `20260829_100455` is based on exact active release `20260829_100015` and keeps that release/image as immediate rollback. Signed-in browser QA proved a broad inventory unit search completed its server request quickly but mounted 418 detailed batch rows in both responsive rendering paths, causing unnecessary client work.
- Material and accessory Inventory now initially render 80 fetched batch rows and expose the existing localized Load more control until all fetched rows are visible. Server search, pagination, item/batch totals, row ordering, pictures, quantities, reservations, edit/delete/QR actions, and access to every result are unchanged.
- The build contract enforces the shared 80-row desktop/mobile window and incremental access to the full fetched result. No backend, database, migration, business data, permission, or stock mutation is included.

## Bounded global-search rendering follow-up (2026-08-29)

- Follow-up release `20260829_100015` is based on exact active release `20260829_095434` and keeps that release/image as its immediate rollback. Signed-in browser QA of a broad query proved the API was fast but the page mounted 100 Bundle plus 100 Model links at once, making the end-to-end interaction visibly slow.
- The Search page now initially mounts 30 results per entity family and exposes the existing localized Load more control until every fetched result is visible. API results, totals, ordering, links, permissions, keyboard/form behavior, and access to all 100-per-family matches are unchanged.
- A source contract enforces the 30-row window, incremental access to every fetched result, and localized control. No backend, database, migration, business data, or authorization change is included.

## Production search-latency optimization release (2026-08-29)

- Release `20260829_095434` is reconstructed from the exact active backend/frontend source release `20260829_035323` (651-file source-manifest SHA-256 `9575d4984bb0d3524ad55e5376ff7d2be200bf861aae09dba10b6deab3271bf6`). The two production source archives were preserved separately and were byte-identical. Release `20260829_035323` remains the immediate application rollback.
- Search behavior, permissions, result fields, routes, business rules, Usluga catalog isolation, and access to every selector option remain unchanged. Shared local selectors cache normalized text and initially mount 80 rows with the existing incremental control; model selectors memoize option mapping/lookups, abort superseded requests, reset stale pages, and debounce at 180 ms. Inventory and Models input delays fall from 350/250 ms to 200/180 ms.
- Inventory stock and batch pages use windowed totals instead of an extra filtered count scan. Batch reservation/availability values are derived from the already-bulk-loaded active reservation rows instead of two queries per batch. Global search selects only the scalar fields required for labels while retaining the standard-catalog filter.
- No Alembic migration or PostgreSQL index is added. The database remains at `0112_price_calc_requests`; the indexed PostgreSQL family-key optimization and authoritative server inventory filtering already present in production are intentionally preserved rather than reimplemented.
- Local validation passed scoped frontend ESLint, ordinary and strict TypeScript, the bounded selector contract, every production build contract, and an optimized 82-route Next.js build. Backend validation passed Ruff for the changed paths, Python compilation, the new 24-row constant-query inventory regression, and 86 wider catalog/inventory/reservation/Usluga tests. The two wider failures reproduce unchanged on the untouched active source: model-number hyphen normalization and supplier-deletion semantics. The active release's two unrelated HR render-purity ESLint findings also remain unchanged and outside this release.
- The release does not create, edit, or delete any business row. Production rollout follows `DEPLOYMENT.md`: drift gates, immutable candidate builds on both VMs, a validated fresh PostgreSQL backup, migration-head verification, backend-then-frontend cutover, all four health checks, runtime inspection, and signed-in read-only search QA. No data mutation is required.

## Sales-first collaborative price calculation ready locally (2026-08-27)

- This candidate is reconstructed from exact active production release `20260827_101946` (source-manifest SHA-256 `f7f1acda541cb6d3ec4c4f9a5b7d95fbdffd3612ef153922e81f251bfb5d7cd7`) and preserves its recruitment profile work and database head `0111_recruitment_profile`.
- Sales creates each persisted request by selecting a searchable model variant. The same request appears immediately in Finance, Abbosbek's Purchasing queue, and the accessory Inventory queue; Finance cannot create requests and edits only its pricing fields.
- Abbosbek enters Kroy number, fabric price, and sewing cost; Kroy information is resolved against Cutting Passports. The accessory team enters up to four accessory names and prices. Cost price remains hidden until both operational stages are complete and includes fixed packaging cost `0.1`.
- The forward-only migration is `0112_price_calc_requests`, directly based on the active `0111_recruitment_profile`. No production request or other business row was created during local validation.

## Fabric deletion and batch-number search correction ready locally (2026-08-27)

- Corrective candidate `20260827_063824` is reconstructed from and based on the exact active backend/frontend release `20260827_060926` (source-manifest SHA-256 `0c82405ac360292d76675d13ff218d3b6ddfd339da99156ae2774944999a5028`), preserving its HR workspace and database revision `0110_hr_workspace`.
- Production deletion attempts for fabric batch ID `1238` failed and rolled back because PostgreSQL rejects a broad `FOR UPDATE` applied to the nullable side of SQLAlchemy's eager outer joins. The correction suppresses relationship joins and locks only matching `material_reservations` rows with `FOR UPDATE OF material_reservations` before releasing them.
- Inventory search already submits typed text automatically after 350 ms and the backend correctly returns batch `16937`. The page no longer applies its incomplete item-name/SKU/unit-only filter while that server search is pending, so valid batch-number searches do not incorrectly flash an empty table.
- No production fabric, reservation, movement, or other business row changed during diagnosis or local QA. Batch `16937` remains active and searchable; failed delete requests for batch ID `1238` were transactionally rolled back.
- Validation passed all four focused stock-batch deletion tests, PostgreSQL SQL-compilation regression coverage, Ruff, Python compilation, strict TypeScript, targeted ESLint, all frontend build contracts, and a 77-route optimized production build. The wider inventory selection passed 34 of 35 tests; its sole failure is the inherited supplier-deletion expectation mismatch already documented below.

## Reserved and used fabric-batch deletion ready locally (2026-08-27)

- Candidate release `20260827_052114` is based on exact active production release `20260826_103803`; it is staged locally and is not yet deployed.
- Fabric Storage deletion now keeps the existing physical delete for unused receipt-only batches. A reserved, planned, adjusted, consumed, or otherwise used batch instead has every still-open reservation amount released, its remaining batch quantity removed through one inventory issue movement, its QC state placed on hold, and its row archived out of active batch lists. Historical reservations, production plans, Cutting usage, BOM, waste, and movement evidence remain linked for traceability.
- This intentionally supersedes the former stable rule that blocked deletion of reserved/linked/used fabric batches. The user explicitly requested that delete-authorized Storage staff be able to remove those rows from active inventory without the HTTP 409 error.
- Production batch number `16936` was inspected read-only: batch `1238` has `600 kg`, one legacy production-order link and four multi-material planning links; batch `1256` has `720.35 kg` and no downstream links. Neither row was changed or deleted during development or QA.
- Focused validation passed all five batch-delete tests, and the complete inventory/reservation selection passed `40` tests. The one excluded broader failure is the inherited supplier-deletion expectation mismatch already documented in project context. Ruff passed for the changed files with the active release's five pre-existing `F401` findings ignored, and Python compilation passed.

## Besttex dynamic daily sewing report sections ready locally (2026-08-26)

- This clean candidate is based on exact active release `20260826_043516` and is staged at `.work-active-20260826_043516-besttex-daily-sections`; it is not deployed.
- Every Besttex sewing band now follows the same dynamic Daily Sewing Report entry workflow as Eco Cotton: three initial section rows, Add section up to 20 rows, per-section order/manual-model and kroy selection, defects, and optional upper/lower cloth quantities whose sum becomes the sewn quantity.
- Backend create/update handling now preserves section, upper, and lower quantity fields for factory `BST`. Eco Cotton behavior, Milana's existing section-enabled lines, ordinary Milana single-entry lines, stored reports, totals, exports, workflow counters, and factory authorization remain unchanged.
- Validation passed Ruff, all 9 Daily Sewing Report backend tests (including parameterized Besttex/Eco persistence), TypeScript, the factory-section UI contract, every frontend build contract, and an optimized 68-route production build. No production source, schema, report, work order, assignment, payroll, inventory, or other business row changed.

## Besttex sewing bands added (2026-08-26)

- Production has exactly 16 active Besttex sewing lines named `1-Band` through `16-Band`, with codes `BST-BAND-01` through `BST-BAND-16` and row IDs `96` through `111`.
- The rows are scoped to factory `BST`, have no supervisors, and retain `capacity_per_day = 0`. Audit row `15202` records the atomic 16-row creation. No Milana or Eco Cotton sewing-flow row changed.
- Validated pre-change backup: `/opt/milana-erp/shared/backups/pre_besttex_sewing_bands_20260826_101056.dump`, 47,251,288 bytes, 988 restore objects, dump SHA-256 `0d3552e115aaf91e68da994f0d1a9730d15a02a2485d29543a819e223e3c56a3`; restore-list SHA-256 `a848a70faf4e71f445ad6e54ba99ba2a5bb5876dd89d0f1ca116e0f7acc0cf30`.

## Multi-material Planning and Cutting restoration release (2026-08-26)

- Release candidate `20260826_043516` is reconciled from exact active release `20260826_043324`, including its Cutting department reassignment migration and model/BOM picture precedence. It restores the previously deployed multi-material Planning and Cutting workflow that disappeared from later source while its `0075_multi_fabric_cutting` schema remained in production.
- Standard and branded-stock Planning can add two or more distinct fabric batches, each with its own positive estimated quantity and unit. Duplicate batches and incomplete rows are blocked; the first material remains mirrored in the legacy scalar fields for backward compatibility. Usluga remains manual and inventory-free.
- Reservations follow every explicitly planned fabric. Cutting requires an actual quantity for every planned fabric in one atomic submission, blocks missing or unexpected batches, consumes each reservation or stock batch exactly once, records per-material usage, and leaves no partial movement when validation fails.
- Local validation passed the 15-test material-reservation suite, all 14 Usluga regressions, seven focused production-flow tests, Python compilation, the multi-material and legacy branded-fabric frontend contracts, TypeScript, and the optimized 68-route production frontend build. One inherited factory-inbox test still expects an admin token to bypass the current Besttex login boundary and fails unchanged after the Cutting transaction succeeds.
- This restoration adds no migration or business data of its own. Until cutover verification completes, production remains on release `20260826_043324` at database head `0109_reassign_121_122_to_ect`.

## Usluga manual fabrics and approved Cutting batches release candidate (2026-08-20)

- Release candidate `20260820_072419` is reconciled from exact active release `20260820_053224`. Usluga model fabrics are free text with exactly one main fabric and any number of secondary fabrics. They never carry an inventory item or stock-batch link; standard Milana/Besttex BOM behavior and Usluga accessories remain inventory-backed and unchanged.
- ECT Cutting selects the model fabric for each saved material batch. Main-fabric batches record kilograms and cutting evidence, create ordinary product bundles/passports, and move to ECO Sewing only after an authorized Usluga planner approves the batch. Secondary-fabric batches record kilograms, rolls, waste, beika/layer quantities, operator, and notes for reports only; they create no product pieces or bundles.
- Saving or printing a passport never approves or closes Cutting. The batch history remains on the work order, supports repeated batches, independent passport printing, approval, and reasoned rejection. Pending batches keep Cutting open; all model fabrics and every planned production batch require approved evidence before completion. Bundle movement is blocked while its source batch is pending or rejected.
- Model fabric name/role and deletion are locked after Cutting has used that row. Approved main and secondary kilograms update the Usluga order's reported material total without any stock movement, reservation, receipt, or inventory consumption. Usluga Planning's existing `usluga.manage` permission can approve; migration `0107` also adds the narrower `usluga.cutting.approve` permission to the Usluga role.
- Migrations `0106_usluga_manual_fabric` and `0107_usluga_cutting_approval` were validated from the exact active-release PostgreSQL schema. A legacy Usluga fabric was converted to a manual main fabric with both inventory links cleared, the role permission was added once, and verification found zero invalid Usluga fabric rows.
- Local validation passed seven focused Usluga API tests plus the isolated standard replacement workflow, Ruff, Python compilation, a single Alembic head, the production-realistic PostgreSQL migration/backfill check, the Usluga UI contract, TypeScript, ESLint, and the optimized 68-route frontend build. The inherited i18n checker retains the same 12 unrelated inventory-label errors. The broader active-source suite passed 94 tests and retained nine unrelated baseline/stateful failures in factory-scope, label-image, model-number normalization, and shared test data.
- This section describes the immutable deployment candidate. Until cutover verification completes, production remains on release `20260820_053224` at database revision `0105_eco_usluga_attendance`.

## Usluga model and planning parity release (2026-08-19)

- Release `20260819_125649` packages the approved Usluga model/planning parity revision from exact active release `20260819_115056`. It adds no Alembic revision and keeps database head `0105_eco_usluga_attendance`.
- The Usluga catalog now uses the same full technical model workspace as Milana: search/filter/pagination, model cards, create/edit/view/clone/delete/approve, general details, composition, technical BOM/specification, pictures, variants, pattern, other documents, mini post, size chart, sewing guide, ECO-only paid operations, translations, costing, and SAM. Usluga models remain in the isolated `usluga` catalog scope and are invisible to standard models, Sales, and ordinary Production Orders.
- Usluga planning is now a full planning workspace with an approved-model selector, model preview/link, outside-company and reference fields, deadline, manual kilograms/material evidence, editable multi-color and multi-size lines, size-range distribution, a live plan summary, searchable/status-filtered history, and linked ECT Cutting -> ECO Sewing -> ECP Packaging progress. A separate order-detail page shows every planned color/size line, material evidence, packages, stage links, and final handover.
- The no-inventory rule is unchanged and regression-tested: Usluga order creation and Cutting cannot select, reserve, consume, receive, transfer, or create stock; model BOM entries are technical specifications only and do not cause stock movements. The route still ends in direct customer handover without finished-goods storage.
- Local validation passed 26 focused Usluga/model/catalog tests with one unrelated baseline test deselected, Ruff, Python compilation, TypeScript, targeted ESLint, the optimized 68-route frontend build, and signed-in browser QA of planning, the model catalog/editor, paid operations, and order detail with no console warnings/errors. The inherited i18n checker still reports the same 12 unrelated inventory-label keys. The deselected catalog assertion also fails unchanged in the active source because model-number normalization removes a hyphen before a leading digit.


## Eco Cotton Usluga workflow and attendance device enrollment deployed (2026-08-19)

- Active backend and frontend release: `20260819_115056`; production database head: `0105_eco_usluga_attendance`. Immediate application rollback is backend image/release `20260819_093340-compat-0105` with frontend release `20260819_093340`; the compatibility image is the exact prior application plus only the new migration marker so it can start safely against revision `0105`.
- Eco Cotton now has an isolated Usluga model/order workspace. Usluga models have an ECO-only catalog scope and are excluded from the normal PLM catalog, global search, Sales, standard Production Orders, and Process Tracking. Orders receive `USL-YYYY-NNNNNN` numbers and record the outside company, customer reference, size/color quantities, deadline, material description, kilograms used, notes, package quantities, and final recipient.
- Creating an Usluga order starts exactly ECT Cutting, ECO Sewing, and ECP Packaging. Printing and finished-goods storage are omitted. Cutting forces every bundle to ECO Sewing and rolls recorded input kilograms into the service-material total. Usluga cannot select, reserve, or consume inventory; create storage-transfer work; mint finished-goods stock; or enter warehouse receipt/location/reservation/shipment. Packed packages are handed directly to the outside-company recipient with an audited `handed_over` status.
- Eco Cotton navigation is separated into Cutting, Sewing, Packaging, Usluga, and Attendance. Factory and department authorization hides Usluga from Milana and Besttex. Migration `0105` created the unassigned `Eco Cotton Usluga` role; permissions can be granted through User Administration.
- Attendance remains separate from ERP employees/payroll and is factory-scoped. The UI can enroll Dahua or Hikvision devices with HTTPS and certificate pinning, issue a one-time connector token, download LAN connector configuration, rotate the token, and disable/enable synchronization. Device usernames/passwords are used only in the local download and are never sent to or stored by ERP.
- The existing LAN polling connector remains Hikvision-specific. Live Dahua profile/event/photo polling still requires the exact ECT Dahua model/firmware and validation of its read-only endpoints on the factory LAN. ERP enrollment, token-authenticated ingestion, factory scoping, daily attendance, and reporting are deployed and ready for that adapter.
- The immutable release was reconciled from exact active release `20260819_093340`, not the dirty/behind checkout. Release archive SHA-256: `d4acf712eea44c94becfe6e1be497c863244570d8b2b488edbbff7a61e7b147a`; 596-file manifest SHA-256: `de6d853d22d050585276f2eeff673db7a076097bd1d9142649ba9631d745c3c8`; backend image ID: `sha256:7b4d9b45bb4db6c1116e525efed56123d85587d1c8af52c8ac091e297cb8b1e5`; frontend build ID: `GNH4Vvks6MbYDKCamgq6t`.
- Verified pre-migration backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260819_115056.dump`, 46,147,074 bytes, mode `0600`, 974 restore objects, dump SHA-256 `39fc10a431315e3b3429e818af4bba9f9abb4f0b7737e2ccadf6b8d138042960`; restore-list SHA-256 `66977eb25aa605aa2991313d750802dede0bf81c4d9caa799c49e2c2f109a638`.
- Migration verification found zero Usluga models/orders, all six existing attendance-device rows preserved, zero managed-device tokens, one unassigned Usluga role, and the direct-handover constraint. No user, device enrollment, model, order, package, inventory, production, shipment, or other business record was created. The only data mutation was the additive schema migration and unassigned role.
- Validation passed 24 focused Usluga, attendance, idempotency, and Sales isolation tests; Ruff; Python compilation; a single Alembic head; strict TypeScript; targeted ESLint; and local/remote 67-route production builds. A broader run passed 61 tests and retained five failures reproduced unchanged against the untouched active-source candidate; the inherited i18n baseline retains 12 unrelated inventory-label keys and npm audit retains seven findings (one moderate, six high).
- All four internal/public backend-health and frontend-login checks returned HTTP `200`; public `/usluga` and `/attendance` also returned `200`. Postflight found one Uvicorn parent with two workers, zero restarts/OOMs, no new traceback/5xx errors, zero invalid PostgreSQL indexes, and 22 of 100 database connections. Signed-in read-only QA confirmed the five separate Eco Cotton navigation groups, an empty Usluga workspace with the no-inventory notice, the Dahua-first device enrollment form, and zero browser warnings/errors. No form was submitted or downloaded during QA.

## Short purchase-order closure and requested purchasing data correction (2026-08-19)

- Release `20260819_072932` adds an explicit close decision when an Active Purchase Orders receipt leaves any ordered quantity outstanding. Choosing Close order records the actual received quantity, marks the purchase order received/closed, records the canceled remainder in the audit log, and removes it from Active Purchase Orders. Choosing Keep open preserves the existing partially-received behavior.
- Material pictures in Active Purchase Orders are now keyboard-accessible links that open the original stored picture in a separate browser window/tab. The existing table layout, picture size, supplier grouping, receiving fields, and EN/RU/UZ coverage are preserved.
- The requested production correction is intentionally separate from the general workflow: `PUR-2026-000022` is returned from partially received to sent/not received by removing its isolated receipt batch and two receipt/zeroing movements and resetting its single line from 529.20 kg received to zero. The pictured unrelated fabric batch `6183` / `30/1P_CMP SUPREM` / 429.40 kg / 19 rolls is fully deleted with its sole original receipt movement after guarded verification proves it has no reservation, production, BOM, Cutting, waste, or other use. Historical audit rows and shared picture files remain preserved, and new audit rows record both corrections.
- The candidate is based on exact active release `20260819_043507`; no Alembic schema migration is required and the database remains at `0104_purchase_batch_images`.

## Historical purchase receipt pictures repaired (2026-08-19)

- Release `20260819_043507` follows the purchase receipt picture/manual-batch release with a constrained data backfill. Production inspection proved that every one of the 21 active purchase-order lines has a required picture identical to its approved purchase-request line, and all 21 files render successfully.
- Two batches received before release `20260819_041831` had no `stock_batches.image_url` even though their proven linked purchase-order lines retained valid pictures: internal batches `PUR-2026-000014` and `PUR-2026-000001`. Migration `0104_purchase_batch_images` copies those authoritative line pictures only through `receive` movements whose reference type is `PurchaseOrderLine`, only when the batch picture is empty, and never overwrites an existing batch picture.
- Future purchase receipts remain covered by the application change in `20260819_041831`, which assigns the purchase-line picture while creating the stock batch. Supplier-entered batch numbers, internal PO numbers, quantities, movements, and all unrelated inventory rows are unchanged.
- Immediate application rollback release/image: `20260819_041831`. The data-only migration is intentionally non-destructive on downgrade because removing an authoritative batch picture after it may be in use would be unsafe.

## Purchase receipt photos and separate batch identities (2026-08-19)

- Release `20260819_041831` fixes Active Purchase Orders receiving so the operator enters the supplier/manufacturer batch number manually instead of receiving a prefilled `PUR-...-<line>` value. The purchase number is stored separately in the new system-controlled `stock_batches.internal_batch_no` field and displayed beside the external batch number in Material Inventory on desktop and mobile.
- The exact purchase-line picture is copied to the newly received stock batch. Material Inventory therefore renders that receipt-specific picture immediately without changing the global material-master picture or any unrelated batch picture.
- Migration `0103_purchase_internal_batch` adds the nullable indexed internal-batch column and backfills existing batches only when a `receive` stock movement proves a link through `PurchaseOrderLine` to a real purchase order. Existing external batch numbers and order references are preserved.
- The change was reconciled from exact active release `20260819_035431`; that release/image remains the immediate rollback application. Because the new column is nullable and additive, the rollback application remains schema-compatible, although it will not display or populate the new field.

## Purchase-order overage receiving (2026-08-19)

- Purchase-order receiving now accepts a positive delivered quantity even when it exceeds the ordered or remaining amount. The full actual quantity is added to the inventory batch, stock movement, purchase-order line total, and audit record; the line's displayed remaining quantity stays clamped at zero and the existing received-status calculation continues to close fully received lines.
- The receiving form no longer emits an HTML maximum tied to the remaining order quantity. Positive-quantity validation, roll count/weight handling, warehouse and supplier validation, batch creation, permissions, and draft-order rejection remain unchanged.
- Regression coverage proves an overage receipt succeeds and increases material stock by the complete received quantity. The focused purchasing suite, Ruff, Python compilation, frontend contract, targeted ESLint, TypeScript, and the local 66-route production build pass.
- Active backend and frontend release: `20260819_035431`; immediate rollback release/image: `20260818_120233`; the database remains at Alembic `0102_attendance_mirror` with no schema change. Backend image ID: `sha256:e4d0cffe657c85f8e2b71c7c039b173b59a020e4f21ed7cbe4d476aa16920739`; frontend build ID: `K4Ue_8zXZ0058d_TdQMC`.
- Verified pre-cutover backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260819_035431.dump`, 46,124,871 bytes, mode `0600`, 973 restore objects, dump SHA-256 `c1cd588f24674e9d16b15201dfc727a74633f22850396da79bf5c9129b26ba29`; restore-list SHA-256 `e97fe47a061840b79d1f1e70adad35d25d85964a6156bc86b4f8d3c79de3a093`.
- Remote builds and the no-op migration check passed before cutover. All internal/public backend health and frontend login checks returned HTTP 200. Postflight found one Uvicorn parent with two workers, zero restarts, no OOM, no new backend/frontend errors, zero invalid PostgreSQL indexes, and 21 of 100 database connections. The inherited npm audit remains seven findings (one moderate and six high).
- Signed-in production QA opened the purchase-order receipt form and confirmed the quantity input has no maximum while retaining its minimum and unit-specific step. The page reported zero browser console errors. No receipt was submitted and no inventory, batch, stock movement, purchase-order, audit, or other business data was changed during QA.

## Forecasting data-source repair implemented locally (2026-08-18)

- The reported all-zero Forecasting page was diagnosed read-only in production. The page and API loaded without browser errors, but production had zero Sales orders/items and zero saved forecast recommendations while it had 26 branded planning orders, 46 branded production orders, 66 inventory items, 211 model BOM rows, and 1,117 finished-goods rows. Every inventory item had a zero reorder level.
- The local forecasting engine now keeps branded Sales orders as the authoritative demand signal per model/brand/collection/color/size variant, but falls back to completed finished-storage branded production history for variants that have never been recorded through Sales. Draft/cancelled sales and unfinished/cancelled production are excluded from history. The eight-week demand trend uses the same per-variant source rule.
- Production suggestions now subtract both matched finished-goods availability and quantities already in active production, preventing duplicate production advice. Finished-goods rows with missing brand/collection inherit those identities from their linked production order for forecast matching.
- Material reorder analysis now evaluates all active items. A positive configured reorder level is no longer required when active BOM demand or the latest 90-day usage rate exceeds available stock. `storage_transfer` production remains included in active pipeline and BOM demand until receipt is complete.
- The low-finished-stock card now counts demand variants whose on-hand stock is below one average week of observed demand instead of counting individual depleted package rows.
- Regression coverage was added for production-history fallback, demand-trend fallback, active-pipeline subtraction, legacy stock identity matching, and zero-reorder-level BOM shortages. All 17 forecasting/traceability tests, Ruff, Python compilation, and whitespace validation pass.
- This repair is local only. No deployment, migration, production data mutation, recommendation creation, or inventory threshold change was performed. Production remains on release `20260818_100747` with database revision `0102_attendance_mirror`; deployment and signed-in acceptance testing remain outstanding.

## Payroll paid-operation model save access deployed (2026-08-18)

- Active backend and frontend release: `20260818_100747`; immediate rollback release/image: `20260818_122518`; production database remains at Alembic `0102_attendance_mirror` with no schema change.
- Process QR now saves model paid operations through a dedicated `PATCH /api/models/{model_id}/paid-operations` endpoint. The standard Payroll role can use it through its existing `payroll.manage` permission; payroll users still receive `403` from the general model-edit endpoint and do not gain `modeling.models` or access to model identity, BOM, images, variants, approval, or other model fields.
- The endpoint accepts only the paid-operation list, scopes payroll reads and writes to the factory embedded in the login session, preserves every hidden factory's operations and every non-payroll model field, rejects rows assigned to another factory, and writes an `update_paid_operations` audit event. Process QR uses the narrow endpoint without a visual/layout change.
- The immutable candidate was reconciled onto the exact active `20260818_122518` source, preserving the six-turnstile attendance release and its 66 frontend routes. Exactly four existing source/test files changed; the generated TypeScript build-info file was excluded from the new source archive.
- Release archive SHA-256: `9ecf84beb2ebd2857d085a94cd9aeb271d51e6d8fb1bf1633c5436585bfc6735`; 582-file source-manifest SHA-256: `822aeb250e7e1e9d8b1fadfb1923e66a6533f8190b787221cc0915ee3e8b0c55`; backend image ID: `sha256:4b7b1f7a4eee9f1535978556fd81e136194c54823cd177031a2fc27250037e32`; frontend build ID: `Hrw5ZbZigvQvdpS8ZuNUr`.
- Verified pre-cutover backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260818_100747.dump`, 45,989,146 bytes, 973 restore objects, dump SHA-256 `fdf90ac72b387d1eb99452e574fdca184bfe50dc3ad87eb1499095cbd08cf9ed`; restore-list SHA-256 `7d5c94113c7355d31b8ef76a03dc09dc8201dc4369ce7fa09b4fb9c27c4d43e0`.
- Validation passed all 34 focused payroll and paid-operation factory tests, Ruff, Python compilation, strict TypeScript, targeted ESLint, Process QR ordering/manual-order contracts, local and remote 66-route production builds, deterministic archive/manifest verification, the no-op migration check at `0102`, and all four private/public health/login checks. Postflight found one registered `PATCH` route, one Uvicorn parent with two workers, zero container restarts, zero invalid PostgreSQL indexes, and 14 of 100 database connections. The inherited npm audit remains at seven findings (one moderate and six high). A separate broader local catalog/payroll run exposed one unrelated existing model-number normalization failure where a generated `FAMILY-…` code loses its hyphen; that path was not changed here.
- Signed-in, read-only production QA loaded Process QR, confirmed the enabled `Modelga saqlash` action, and found zero browser console errors. The production Payroll role retained `payroll.manage`, `payroll.scan`, and `payroll.view` without `modeling.models`. No save action was used and no model, paid operation, payroll row, permission, role, factory scope, or other business data was changed.


## Six-turnstile attendance aggregation and daily Excel report deployed (2026-08-18)

- Active backend and frontend release: `20260818_122518`; immediate rollback release: `20260818_122125`; production database remains at Alembic `0102_attendance_mirror` with no schema change.
- The isolated `/attendance` workspace now combines read-only data from all six Hikvision turnstiles: `10.100.50.73`, `10.100.50.31`, `10.100.50.91`, `10.100.50.41`, `10.100.50.115`, and `10.100.50.104`. Profiles and raw events remain device-specific for traceability, while the daily view deduplicates them by Hikvision employee ID so the same employee appears only once across lanes.
- Each employee/day shows the first scan as arrival and the last scan as departure. A departure is shown only when it is at least one minute after arrival, preventing near-simultaneous scans at adjacent lanes from becoming a false zero-minute workday. The raw scan history is preserved unchanged. The page shows complete, one-scan, and absent states plus elapsed time.
- A permission-protected Excel report is available from Attendance and follows the selected date, search text, usage filter, and EN/RU/UZ language. Signed-in production QA verified the combined six-turnstile page, used-person filter, arrival/departure calculation, one-scan suppression, and a successful report response.
- The connector is strictly read-only toward every device: GET requests and only the Hikvision profile, face, and access-event search POST endpoints are allowed. It supports per-device certificate pins, XML and JSON firmware responses, legacy TLS where required, digest fallback, retries, resumable one-day event windows, and independent per-lane progress. Existing HTTP Listening, ISUP, Hik-Connect, SDK Server, network, door-control, and old-ERP configuration were not changed; the old ERP remains the writer and continues operating in parallel.
- All six profile passes completed with 1,500 profiles reported per device. The combined union contains 1,507 unique Hikvision employee IDs because seven IDs are present on only some lanes. The designated photo source has 1,183 usable mirrored face pictures; 215 remaining advertised picture URLs are stale or missing on the device and cannot currently be imported. An interrupted initial `.73` photo pass created 400 device-specific duplicate mirror copies before `.41` was designated as the canonical photo source; no deletion or cleanup was performed, and UI aggregation still uses one representative profile per employee ID.
- The Windows scheduled task `Milana Hikvision Attendance (Read Only)` was re-enabled and verified with result `0`; all six event cursors reached the current period. At production QA the page showed 392 unique employees using a turnstile that day, 1,115 not used, 1,249 raw scans, and a current multi-device sync time.
- The only business data touched is the isolated attendance mirror: device-specific profiles, raw access events, and face-picture copies. No HR employee, payroll, ERP user, card, face credential, production, stock, or other business record was created, linked, or modified.
- Verified pre-cutover backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260818_122518.dump`, 45,975,753 bytes, 973 restore objects, dump SHA-256 `ba4070ef1b50125c129cba1e4369367564405256295109eaf25fd954c7dda9a0`; restore-list SHA-256 `7b8f20dd04b07ac7ad964ad4aa5134c35f9a9c74b460fe894c9bbfbb88b2592d`.
- Release archive SHA-256: `2dda7d3ece68da528dde709fe68d7ffdd8fe25de3c7f16f5c115ef308d9254bb`; 583-file source-manifest SHA-256: `7dccd8013443d63a4edb31bae541e8d146e238065789260d170d97342bbba8f6`; backend image ID: `sha256:0f83559041cfb72627b41dbefbee48ca7984a322afd23b6a46078e8a3e489754`; frontend build ID: `WwxKKF6nSjx-jCLr3FW7w`.
- Validation passed eight attendance backend tests, five connector tests, Ruff, strict TypeScript, targeted ESLint, 2,695-key EN/RU/UZ parity, the attendance report contract, local and remote 66-route production builds, deterministic archive verification, and all four private/public backend/frontend health and login checks. The inherited npm audit remains at seven findings (one moderate and six high) and was not introduced by this change.

## PO-2026-000108 incorrect cutting submissions rolled back (2026-08-18)

- Production application release remained `20260817_130345` and database head remained `0102_attendance_mirror`; this was a narrowly scoped, audited data correction with no code deployment or schema change.
- Fresh production inspection identified branded production order `PO-2026-000108` / ID `122`, planned for 600 pieces. Cutting had two incorrect 600-piece submissions, records `52` and `53`, which inflated cutting actual/pass quantities and the downstream plan to 1,200. Six remaining bundles, IDs `1503`-`1508` / numbers `BND-2026-001440`-`BND-2026-001445`, contained 100 pieces each for sizes 44, 46, 48, 50, 52, and 54.
- Preflight proved all six bundles were still `created` with only six creation scans and zero printing, sewing, packaging, package-receipt, package, finished-goods, reservation, accessory-issue, sewing-assignment, sewing-report, or replacement-request records. Both cutting submissions recorded zero fabric input, so no production stock movement existed. A July stock movement that coincidentally carries reference ID `52` was identified as unrelated and preserved.
- After a serializable precondition recheck, the correction deleted the six bundles and scans, cutting records `52` and `53`, unused waste records `41` and `42`, and unread notifications `1017`-`1024`; reset cutting work order `474` to `in_progress` with zero actual/pass/fail quantities; reset sewing work order `475` to `waiting`; restored sewing, packaging, and storage plans from 1,200 to 600; and returned the production order status to `cutting`. The planning cutting passport and all unrelated stock/data were preserved. Audit log `13626` records the correction, and bundle numbering was not rewound.
- Verified pre-correction backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260818_043439.dump`, 43,632,407 bytes, 973 restore objects, dump SHA-256 `15f6bafec6c27bba6884e48ac639e1a7f5459d4d9c40cff0ec4eb19aafb79a7c`, restore-list SHA-256 `cdeb0af929d5285f7177138e9a3601ceb1468eac969cab1cc04f5809a2578966`.
- Post-correction verification found zero cutting records, bundles, stale notifications, and waste records; Cutting `in_progress`; Sewing `waiting`; downstream plan 600; and zero actual downstream output. Internal and public backend health and login checks returned HTTP 200.

## PO-2026-000109 incorrect cutting submission rolled back (2026-08-18)

- Production application release remained `20260817_130345` and database head remained `0102_attendance_mirror`; this was a narrowly scoped, audited data correction with no code deployment or schema change.
- The screenshot contained `PO-2026-000109` and `PO-2026-000110`. Fresh production inspection showed that `PO-2026-000109` / ID `123` had advanced incorrectly from Cutting to Sewing after a one-piece cutting submission, while `PO-2026-000110` / ID `124` was already in Planning with zero Cutting activity and therefore required no mutation.
- Preflight proved `PO-2026-000109` had zero bundles, scans, printing records, sewing records, packaging records, packaging receipts, packages, finished-goods stock, material reservations, manual accessory issues, sewing assignments, sewing reports, or replacement requests. Its only mistaken production result was cutting record `54` with one cut/passed piece, unused 11 kg waste record `43`, and four unread incoming-cutting notifications. No fabric batch or input quantity was recorded, so the correction required no stock change; an older July stock movement that coincidentally carries reference ID `54` was explicitly identified as unrelated and preserved.
- After a serializable precondition recheck, the correction deleted cutting record `54`, unused waste record `43`, and notifications `1025`-`1028`; reset cutting work order `478` to `in_progress` with zero actual/pass/fail quantities; reset sewing work order `479` to `waiting`; kept packaging and storage waiting; and returned the production order status to `cutting`. The existing planning cutting passport and all unrelated data were preserved. Audit log `13621` records the correction.
- Verified pre-correction backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260818_042750.dump`, 43,631,779 bytes, 973 restore objects, dump SHA-256 `5ed243a92f6f9bcb339a7f4c8e4b894eb94cace896784b9356804f5c4c5bf423`, restore-list SHA-256 `81fb1867d83cf1c8ef223d110c1376e54e2d23bbb0580065fa3c8ca5c1a690ab`.
- Post-correction verification found zero cutting records, zero bundles, zero stale notifications, zero waste records, Cutting `in_progress`, Sewing `waiting`, and zero actual downstream output. Internal and public backend health and login checks returned HTTP 200.

## SO-2026-000107 incorrect cutting bundles rolled back (2026-08-18)

- Production application release remained `20260817_130345` and database head remained `0102_attendance_mirror`; this was a narrowly scoped, audited data correction with no code deployment or schema change.
- The exact target was branded production order `PO-2026-000107`, displayed as `SO-2026-000107`, production order ID `121`, batch `0121-01` / ID `42`. Cutting had mistakenly created 612 one-piece bundles: IDs `891`-`1502`, numbers `BND-2026-000828`-`BND-2026-001439`, with 102 bundles each for sizes 44, 46, 48, 50, 52, and 54.
- Preflight proved all 612 bundles were still `created`, had only their 612 creation scan logs, and had zero printing, sewing, packaging, package-receipt, or other downstream records. The associated cutting submission was record `51`; no material reservation existed, and its fabric movement, waste, and notifications were isolated and unused.
- After a serializable precondition recheck, the correction deleted the 612 bundles, 612 creation scan logs, cutting record `51`, unused 34.1 kg waste record `40`, and four stale unread sewing notifications. It reset cutting work order `470` to `in_progress` with zero actual/pass/fail quantities, reset sewing work order `471` to `waiting`, restored downstream plans to the original 600-piece plan, and returned the production order status to `cutting`.
- Fabric batch `5503` / ID `941` was restored from 226.4 kg to 536.4 kg through audited 310 kg return movement `1544`; the original consumption movement remains preserved for traceability. Audit log `13602` records the complete rollback. Bundle numbering was not rewound, so newly corrected labels will continue after the deleted range and cannot collide with old printed labels.
- Verified pre-correction backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260818_035351.dump`, 43,643,289 bytes, 973 restore objects, dump SHA-256 `ac1324ae7243930c82662bfea4c6e58e1e87c587f44750b6ac1a709ebf89f2a8`, restore-list SHA-256 `74e8119333c08e59dfb1514e1b35415f177c498873854e99481b704e91fb69c6`.
- Post-correction verification found zero bundles, zero cutting records, zero stale notifications, zero waste record, one compensating fabric return, Cutting `in_progress`, Sewing `waiting`, and zero actual downstream output. Public `/health` and `/login` checks returned HTTP 200.

## Automatic roll-weight division for new fabric receiving deployed (2026-08-17)

- Active backend and frontend release: `20260817_130345`; immediate application rollback release/image: `20260817_124406`; database head remains `0102_attendance_mirror`.
- Direct Fabric Receiving and Active Purchase Orders no longer ask operators to enter kilograms for each roll. Operators enter only the total received kg and the total roll count. The frontend automatically allocates the total across that many rolls in hundredths of a kilogram, distributing any one-cent remainder so the generated weights add back to the exact entered total, then submits those generated per-roll weights for unique roll QR records/labels.
- Existing Material Inventory printing continues to use the same automatic allocation from the batch total and stored roll count. Sticker size/content and the 24-label print-page fix are unchanged.
- The candidate was rebuilt from the exact immutable active `20260817_124406` archive. The scope is frontend-only: the two receiving pages now use a shared allocation helper also used by the sticker preview, related EN/RU/UZ validation text was updated, and a production-build regression contract was added. Backend code, schema, migrations, and business data are unchanged.
- Release archive SHA-256: `e202baa9604e0576862d405f4cd46a77686a03ac4f335370b2c1bfc6d844012d`; 581-file source-manifest SHA-256: `1fb515bdf76f7885e2b96429b2ed2a9b141c3419a7c4c13a3d8c732d2952c5e5`; backend image ID remains `sha256:5bd931939c92ee06b8bcd3d9b4dbbea3e49cec8e6cd5de6b0e222fb3abb6c4ad`; frontend build ID: `lkf8xeBsS8BL5Q-wD77UZ`.
- Verified pre-cutover backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260817_130345.dump`, 43,609,771 bytes, 973 restore objects, dump SHA-256 `4cc7bca2a6d6660a1012302afc2a9b842e99b143271ac89078f37fcab56f9572`, restore-list SHA-256 `0a18fffbcaab857feeb923f1a99778bbce26b65fa43671d530e5c97955df1e35`.
- Validation passed the new receiving and existing legacy-roll contracts, arithmetic samples including uneven division, 2,686-key EN/RU/UZ parity, TypeScript, targeted ESLint, local and remote 66-route production builds, deterministic archive/manifest verification, the no-op migration check at `0102`, and all four internal/public health/login checks. Runtime has one Uvicorn parent and two workers, no new backend/frontend error markers, and 17 of 100 PostgreSQL connections at cutover.
- Signed-in read-only production QA confirmed editable Netto plus Soni on `/inventory/receive?group=materials`, and editable Miqdor plus Soni in an existing kg purchase-order receive dialog. Neither workflow displayed per-roll kilogram inputs. The dialog was closed without submission; no receive, stock, batch, purchase order, QR, attendance, payroll, or other business-data mutation was performed.


## Material sticker print-page inflation fixed (2026-08-17)

- Active backend and frontend release: `20260817_124406`; immediate application rollback release/image: `20260817_123334`; database head remains `0102_attendance_mirror`.
- Root cause of the reported `973 sheets of paper`: the material-sticker print CSS used `visibility: hidden` for the ERP application. Invisible inventory/layout elements retained their dimensions, so Chrome paginated the entire ERP page in addition to the roll stickers.
- The printable sticker sheet is now rendered as a direct `document.body` portal. During material-sticker printing, all other direct body children use `display: none`, removing the ERP layout from print pagination. Only the 60 x 40 mm labels remain, with one forced page per roll; a 24-roll batch therefore produces 24 label pages.
- The candidate was rebuilt from the exact immutable active `20260817_123334` archive. Exactly one production component and its existing regression script changed; backend code, schema, migrations, sticker content, automatic roll-weight division, new-fabric receiving, and business data are unchanged. Archive SHA-256: `087dd043252620f7957ebff3083cfc90fc22546f21f54d7ead440ea0e0524ce0`; 579-file source-manifest SHA-256: `c8323f0f7fa94e79b5f02480c26850e808266e92930e531d3bff867cbaa722d2`; backend image ID remains `sha256:5bd931939c92ee06b8bcd3d9b4dbbea3e49cec8e6cd5de6b0e222fb3abb6c4ad`; frontend build ID: `kO-Ou-o4a_opNVqM_ErZ_`.
- Verified pre-cutover backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260817_124406.dump`, 43,584,914 bytes, 973 restore objects, dump SHA-256 `54226e537ede058af3e40006390694224fff7f6040fc8a9cc1f75642b0d97d69`, restore-list SHA-256 `3c9e9fdf4add028aba3228ad1f203b61e8ae1d27c44d163c193cb9c6e69c3e3c`.
- Validation passed the extended print-isolation regression, 2,686-key EN/RU/UZ parity, strict TypeScript, targeted ESLint, local and remote 66-route builds, deterministic archive/manifest verification, the no-op migration check at `0102`, and all four internal/public health/login checks. Runtime has one Uvicorn parent and two workers, no new backend/frontend error markers, and 20 of 100 PostgreSQL connections at cutover.
- Signed-in production QA opened material batch `5263`, confirmed a 560.40 kg total, exactly 24 roll stickers, and a 24-roll preview. No Print job, Receive, save, stock, batch, order, attendance, payroll, or other business-data mutation was performed. Native Windows print-preview automation stopped because it could not verify Chrome's current URL with enough confidence, so the OS preview counter was not programmatically read after deployment.

## Automatic equal roll weights for existing fabrics deployed (2026-08-17)

- Active backend and frontend release: `20260817_123334`; immediate application rollback release/image: `20260817_114722`; database head remains `0102_attendance_mirror`.
- Existing Material Inventory batches no longer ask operators to enter roll kilograms. Opening the QR action divides the batch's total quantity across its stored roll count automatically, preserving the exact two-decimal batch total by distributing any one-cent rounding remainder, and presents the existing unique 60 x 40 mm stickers with a direct Print button. It does not save derived weights to the batch.
- New fabrics remain unchanged: direct Fabric Receiving and Active Purchase Orders still require the exact kilogram weight of every physical roll and derive net quantity and roll count from those entries.
- The candidate was rebuilt from the exact immutable active `20260817_114722` archive, preserving payroll factory isolation and the attendance mirror. Exactly three existing frontend files changed and one regression script was added; backend code, schema, migrations, and business data are unchanged. Archive SHA-256: `9c997a4e7433e307e989161c707dd0fdb65cd5c6bfde8682733c99b7de7d9268`; 579-file source-manifest SHA-256: `b69b1e741e2ee18f08250a343d658e57dc0f82e11b7df57d2d389e1f77149d06`; backend image ID remains `sha256:5bd931939c92ee06b8bcd3d9b4dbbea3e49cec8e6cd5de6b0e222fb3abb6c4ad`; frontend build ID: `usz2IVtGDtHLAtz59vbpj`.
- Verified pre-cutover backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260817_123334.dump`, 42,717,158 bytes, 973 restore objects, dump SHA-256 `95fe5f25b927624a7ca8af0a771c21a62dd65180f58fb44c6bb4db2f1118573a`, restore-list SHA-256 `122aebfa10541b07bcdf89b936d2813a0754ad7cf0f63e894113999f64cfe7b0`.
- Validation passed the legacy-roll regression contract, 2,686-key EN/RU/UZ parity, strict TypeScript, targeted ESLint, local and remote 66-route builds, deterministic archive/manifest verification, the no-op migration check at `0102`, and all four internal/public health/login checks. Runtime has one Uvicorn parent and two workers, no new backend/frontend error markers, and 14 of 100 PostgreSQL connections at cutover.
- Signed-in read-only production QA opened batch `5501`: ERP showed 14 stickers derived from 307.30 kg, displayed 21.95 kg on roll 1, exposed no roll-weight input or save action, and kept exact per-roll entry on Fabric Receiving. Browser errors were zero. No Print, Receive, save, stock, batch, order, attendance, payroll, or other business-data mutation was performed during verification.

## Read-only Hikvision turnstile attendance mirror deployed (2026-08-17)

- Active backend and frontend release: `20260817_114722`; immediate application rollback release/image: `20260817_113949`. Production is at Alembic `0102_attendance_mirror`. Release `20260817_090521` cannot start against the `0102` version marker and must not be used without a planned database/application rollback.
- `/attendance` is a new isolated, permission-protected read-only workspace. It stores Hikvision device metadata, mirrored people, access events, and protected face pictures in dedicated attendance storage. It does not create, update, link, or overwrite HR employees, payroll, ERP users, cards, faces, or production records.
- The LAN connector is installed in the current Windows user's local application-data folder because backend VM `172.16.10.4` cannot route to turnstile `10.100.50.41`. The device transport permits GET plus only the documented `UserInfo/Search`, `FDSearch`, and `AcsEvent` search POST endpoints; it contains no device-write or door-control operation. Device TLS is certificate-pinned, credentials use Windows DPAPI, and ERP ingestion uses a separate high-entropy token.
- The device UI reported exactly 1,500 profiles. Existing HTTP Listening, ISUP, Hik-Connect, SDK Server, network, and old-ERP settings were not changed. The old ERP remains the only writer and can continue operating in parallel.
- Local setup completed after securely confirming the pinned TLS certificate and storing the Hikvision credentials with Windows DPAPI. The initial read-only mirror imported all 1,500 device profiles, 1,183 retrievable face pictures, and the device's 15,858-event 30-day history. The other 317 profiles have no retrievable picture: 102 expose no face URL and 215 return missing/broken image responses from the device, consistent with its own broken thumbnails.
- This firmware returns XML for some endpoints despite advertising `application/json`; the local connector now safely accepts JSON or Hikvision XML. It permits the device's same-origin `/LOCALS/pic/enrlFace/` GET path for enrolled images, throttles image reads to avoid saturating the terminal, uses 100-record search pages, and includes Windows timezone data. The scheduled read-only job runs every five minutes; a post-import scheduled test completed with Windows result code `0`. Existing HTTP Listening, ISUP, Hik-Connect, SDK Server, old-ERP integration, door control, cards, and face records were not changed.
- The first cutover exposed a two-worker race while adding an optional Attendance seed role. Automated rollback then could not start the older image against the new Alembic marker, so service was immediately restored with the compatible candidate. Corrective release `20260817_114722` removes that seed mutation; admins retain wildcard access and can grant `attendance.view` as an extra permission. The harmless role row created by the first worker remains; no business record changed.
- Latest verified backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260817_114722.dump`, 42,643,293 bytes, 973 restore objects, SHA-256 `88baca4b9c5108e672fe0a0315ec2149b4119a4d2f4a2dde6cb594b7e6e11107`; restore-list SHA-256 `ed67919684f1edbfb4e3cf766f7ca5f11da454b4a3ddac50228a00a90d073edb`. The original migration backup `milana_erp_pre_20260817_113949.dump` is also retained (42,627,456 bytes, 935 objects, SHA-256 `cfb071750e1c030bfeb6002eb2bddda540aad71547e292135253e4530345edac`; list SHA-256 `1fb73108dc27fe83ac1b561d791f4d61757ecf536daff645d6e00991345dad2f`).
- Release archive SHA-256: `3e588a880ebc2509024452d9a0233131754b277bb9d2165ee447eb971d3da4b5`; 578-file manifest SHA-256: `3d51a8b1add110630510241e0e75e59f013f263c34bf6b3e15bfc63283a5668a`; backend image ID: `sha256:5bd931939c92ee06b8bcd3d9b4dbbea3e49cec8e6cd5de6b0e222fb3abb6c4ad`; frontend build ID: `4VnamYdnnWN5mHMKWeSLt`.
- Validation passed five focused backend tests, two connector tests, Python compilation, 2,686-key EN/RU/UZ parity, TypeScript, local and remote 66-route builds, migration and manifest verification, all four health checks, two Uvicorn workers, and database headroom (15/100). The inherited full backend suite produced 425 passes and 12 unrelated existing failures outside attendance.

## Payroll QR factory isolation deployed (2026-08-17)

- Payroll QR now behaves as three independent factory workspaces for `MIL`, `BST`, and `ECO`. The implementation uses hard factory tenancy inside the existing PostgreSQL database rather than three physical database servers, preserving shared Sales -> Cutting references while preventing cross-factory payroll reads and writes.
- Migration `0101_payroll_factory_scope` adds a required factory key to employees, payroll periods, payroll records, payroll QR labels, and payroll adjustments. Employee numbers, period numbers, label identities, scan identities, and deduplication identities are unique per factory, so the same business number can exist independently in each workspace.
- Employee CRUD and badge resolution; period lifecycle; QR issue, resolve, list, edit, split, delete, return, and scan; payroll records, adjustments, summaries, order QR status, sewing reports, and Excel export are all scoped server-side to the factory embedded in the login session. Process QR only lists sewing-completed orders routed to that factory and locks the paid-operation factory selector to it.
- Active backend and frontend release: `20260817_090521`; immediate application rollback release/image: `20260817_071031`; database head: `0101_payroll_factory_scope`. The archive SHA-256 is `d235ac17c0127611442d06fa0477c191b6420ddf86b41304ab4647f951c25a3c`; the 563-file source-manifest SHA-256 is `65183af233abdfdc0e5e50a3795f7328fbde206101cd2a98151597033f644652`. Backend image ID is `sha256:4d6a0f2a8eaae1fd6735d82863946ad095e8b78ed8c0b85ccc296300fa729968`; frontend build ID is `LldUIJxQlDHm9wfuU6hrK`.
- Verified pre-migration backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260817_090521.dump`, 42,621,306 bytes, 928 restore objects, mode `0600`, dump SHA-256 `748b891f6f2b2a344b6d57864f3784c7524a38e0fc2214cf3a6d2b2765159fc5`; restore-list SHA-256 `44f755d3acad2056368688182bb0122ada61369daa5fba0cc8e569d162e38202`.
- Preflight and post-migration audits matched exactly: 306 employees, one period, 11 payroll records, 977 labels, and zero adjustments. Every existing row resolved to and was tagged `MIL`; there were zero mixed-factory periods, ambiguous unscanned labels, employee user/department conflicts, or label flow/routing conflicts. No payroll, QR, employee, period, order, stock, or other business row was created or deleted; the migration only added/backfilled factory ownership and replaced global identity constraints with per-factory constraints.
- Validation passed: 31 payroll tests, five adjacent process/factory/permission tests, Ruff, Python compilation, a single Alembic head, strict TypeScript, targeted ESLint, Process QR ordering/manual-order and sewing-report print contracts, local and remote 65-route builds, candidate read-only production queries, both manifests, all four internal/public health/login checks, two Uvicorn workers, zero restarts, 16 PostgreSQL connections at initial postflight and 24 after signed-in QA, zero invalid indexes, unchanged shared model storage, and no recent backend/frontend error markers.
- Signed-in read-only production QA showed Milana with 306 employee badges and its completed orders, while an authorized switch to Eco showed zero employee badges, zero completed orders, and Eco-only sewing lines. The paid-operation factory selector was disabled in both workspaces, Daily Sewing Report followed the selected login factory, and the browser console had zero errors. The admin session and original Inventory tab were restored to Milana; no print, save, issue, scan, edit, or delete action was used.
- Rollback warning: the database remains forward-compatible with the previous application immediately after deployment, but once non-Milana data or duplicate per-factory identities are created, release `20260817_071031` is not a safe operational rollback because it assumes globally unique payroll identities. Roll forward with an application image that understands `0101`, or perform a specifically planned database/application restore from the verified backup.

## Exact per-roll material weights and simplified QR stickers deployed (2026-08-17)

- Active backend and frontend release: `20260817_071031`; immediate application rollback release/image: `20260817_062546`; database head: `0100_material_roll_weights`.
- Material Inventory now asks for the exact kilogram weight of every physical roll before printing an existing batch. The entered weights must be positive, the roll count must match, and their sum must equal the batch quantity within 0.01 kg. Saving persists the weights on that exact stock batch and prints one distinct QR sticker per roll.
- New fabric receipts in both direct Fabric Receiving and Active Purchase Orders collect exact per-roll kilograms. Net quantity and roll count are derived from those entries. Existing API clients may still omit roll weights, so the schema change is backward compatible.
- The 60 x 40 mm sticker was simplified to material, supplier, batch number, color, that roll's exact kg, a unique QR, and a compact `B<batch>-R<roll>` code. Label text is bold, the print page is fixed at 60 x 40 mm, and the QR payload identifies the exact batch and roll rather than representing the whole batch.
- The immutable candidate was prepared from the exact previously active `20260817_062546` source. Archive SHA-256: `e5fc37a50565e7c211ebb3f69fd624e519b302a46f17f92316ff48c6e16e21f5`; 562-file source-manifest SHA-256: `98f9d3b36d18de0f3d4367b474f58e31ab614503a38467ebe588994231ca9cff`.
- Verified pre-migration backup: `/opt/milana-erp/shared/backups/pre_material_roll_weights_20260817_071031.dump`, 42,620,566 bytes, 928 restore objects, dump SHA-256 `1a29a79ccbab18056fddd48cfbbdcd7eb160dedf5225f70d11404c9df3879c60`, restore-list SHA-256 `baf17cf3ce07661b46537bcdfeec3752dcb88679c41a2064a627f408a26ce0ff`.
- Validation passed: 15 focused backend tests, single Alembic head, 2,659-key English/Russian/Uzbek parity, strict TypeScript, local and remote 65-route production builds, deterministic archive/manifest verification, migration to `0100`, and all four internal/public health/login checks. Runtime has one Uvicorn parent and two workers, zero recent backend/frontend error markers, zero frontend restarts, and 25 of 100 PostgreSQL connections.
- Signed-in read-only production QA confirmed the QR action on every material batch, a 14-roll modal for batch `5501` with 14 independent kg fields and a distinct `B985-R1` preview, and per-roll entry on Fabric Receiving. No weights were entered or saved and no stock, receipt, batch, order, or other business record was created or changed during verification. Migration `0100` only added the `roll_weights_kg` JSON column with an empty-list default.
- The Xprinter XP-365B vendor preferences show the 60.0 x 40.0 mm form selected; ERP also enforces that size through print CSS. Windows' generic PrintTicket view still reports its legacy `USER` dimensions, so the vendor dialog and a physical test print remain the authoritative media/calibration checks. The inherited frontend audit remains seven findings (one moderate, six high).

## Per-roll material QR stickers deployed (2026-08-17)

- Active backend and frontend release: `20260817_062546`; immediate rollback release/image: `20260817_045238`; database head remains `0099_payroll_qr_edit_split`.
- Material Inventory now exposes a QR action on every material batch. The 60 × 40 mm label prints one unique QR sticker per physical roll, includes the material name/SKU, batch, color, batch quantity, roll position, gramaj, supplier, and warehouse, and opens the exact batch and roll context when scanned. Print CSS uses a 60 mm × 40 mm page, bold label text, a 21 mm QR, and safe printer margins.
- The immutable candidate was rebuilt from the exact active `20260817_045238` source. Six frontend source files differ: the inventory page, the new sticker modal, the legacy dictionary, and the three active split locale files. Backend code, schema, and business data are unchanged.
- Immutable archive SHA-256: `d086289fade1878f47a41887a4bc89c48924bfb384b07913682b424d15ef62b0`; 557-file source-manifest SHA-256: `0e7d69b7becf8879ffa66bbabd01a395361b66c0becd955019e3cfb9078793ec`; backend image ID: `sha256:10a4019ce004fc9673b5adf81891ffc2229a519685f6b8977faab64045c3772b`; frontend build ID: `ESySQcI7QynatdBty7IZI`.
- Verified final pre-deployment backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260817_062546.dump`, 42,620,167 bytes, 928 restore objects, mode `0600`, dump SHA-256 `83020a4b6f4af1549aff38a7f198107d99de4d5bb05c22b24a40a3ff257e7fd7`, restore-list SHA-256 `091d63781a7562059241d40bf22ffd4c5e316d3d4b3391b07f8d15cbddd3beed`.
- Locale parity passed with 2,645 keys in English, Russian, and Uzbek. Inventory build contracts, strict TypeScript, local and remote 65-route builds, deterministic archive/manifest checks, migration verification, and all four internal/public health/login checks passed. Runtime verification found one Uvicorn parent and two workers, zero restarts/OOM/error markers, an active frontend service with zero error markers, and 16 of 100 PostgreSQL connections.
- Signed-in read-only production QA opened batch `5924`: ERP displayed 10 roll stickers and generated 10 non-empty, distinct QR payloads, while showing the translated Uzbek title, batch, and `226.90 kg` quantity. No stock, roll, batch, order, or other business record was created or changed.
- Preliminary release `20260817_060908` passed builds and health checks but failed the signed-in locale acceptance check because the new labels were missing from the active split locale files. It was immediately rolled back to `20260817_045238` before the corrected immutable release was prepared. Its validated backup remains at `/opt/milana-erp/shared/backups/milana_erp_pre_20260817_060908.dump`; no schema or business-data mutation occurred.

## Package label size-only deployment (2026-08-17)

- Active backend and frontend release: `20260817_045238`; immediate rollback release/image: `20260817_042112`; database head remains `0099_payroll_qr_edit_split`.
- Printed package QR labels now show garment sizes without per-size piece counts. Batch allocation quantities and the separate total Quantity row were also removed from the printed label. Package quantities remain stored and enforced everywhere else in ERP.
- The candidate was rebuilt from the exact active `20260817_042112` source. Exactly one backend source file changed and one focused regression test was added; there was no schema migration or business-data mutation.
- Immutable archive SHA-256: `402d21642cf10bbfc20ad713378953e0ba22e1ee2c656a2c96e949ffdcba5057`; 556-file source-manifest SHA-256: `84162a9dd77b5e4f136f794dbe6fd32b07fcaa9582502fada6b5df1c2e8eec2c`; backend image ID: `sha256:70ae2f4652c880cd6f604490713c053a55f6a1e919cce02130343a1e910d2169`; frontend build ID: `n5MOIrfLhG2DqWn1LIVq7`.
- Verified pre-deployment backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260817_045238.dump`, 42,615,656 bytes, 928 restore objects, dump SHA-256 `c32e5961004ce99939f88a6ad7e2db7dfb3058bb6014efebfe78f94b6536d8f3`, restore-list SHA-256 `48c9d36d62c4501fea5b2ee13304367e204049abe3521e0583cb6f635befbd60`.
- Focused package-label and escaping tests, Ruff, Python compilation, all existing frontend build contracts, the 65-route production build, candidate read-only queries, deterministic archive/manifest checks, migration verification, and all four internal/public health checks passed. Two Uvicorn workers run with zero restarts; PostgreSQL reported 18 connections and zero invalid indexes at the final check. Shared model storage remained unchanged at 23,377 files / 3,457,854,251 bytes / digest `04ef579ce46f822a5a6999c0490c8d0769ee6b72778d252ef5582403e3b59e8c`.
- Signed-in read-only production QA expanded an existing package group and generated a `Package Label Sheet` without browser warnings or errors. No package, quantity, stock, order, or other business record was created or changed.

## Collapsible supplier folders deployed (2026-08-17)

- Active backend and frontend release: `20260817_042112`; immediate rollback release/image: `20260817_040859`; database head: `0099_payroll_qr_edit_split`.
- Supplier sections on Active Purchase Orders now start expanded and can be collapsed or reopened from the full-width supplier header. The compact Lucide chevron control works by mouse, touch, and keyboard, exposes `aria-expanded` and `aria-controls`, and uses translated English, Russian, and Uzbek action labels. Collapsing a supplier hides that supplier's order rows and subtotal while leaving other suppliers visible.
- The candidate was rebuilt from the exact active `20260817_040859` source. Exactly six existing frontend files changed; backend code, database schema, purchase-order grouping, and kg calculations are unchanged.
- Immutable archive SHA-256: `47eda00e9fcca32b13da8185cfac91ca5e1547732f5b14ec90a91efe748b235d`; 555-file source-manifest SHA-256: `4ed2c2bde82aa054038d17395997f442c9ca5a296d0fcec0645f7f718f3b99de`; backend image ID: `sha256:8d983bd18542cacfa789f025844716989b278eab451934151f85a7fab9de16e2`; frontend build ID: `fJ2wJXNmPkRQiiHp3RtEf`.
- Verified pre-deployment backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260817_042112.dump`, 42,614,653 bytes, 928 restore objects, dump SHA-256 `31ceacf08fd66f744978230acd1cccc54172156f69f557f0a9f41c7105646761`, restore-list SHA-256 `a667aedf162ba1c72acaa28950ecf5e40ce01ea8bdba40e7eec3f9b4c37d7b54`.
- Locale parity (2,631 keys), supplier grouping/collapse contract, inventory separation, branded-fabric, Process QR, strict TypeScript, targeted ESLint, local and remote 65-route builds, candidate read-only checks, deterministic archive/manifest, migration, and all four internal/public health checks passed. Two Uvicorn workers run with zero restarts; PostgreSQL reported 16 connections and zero invalid indexes at the initial final check; shared model storage remained unchanged at 23,368 files / 3,457,241,715 bytes / digest `3f3a87714bf4805d9ff402291f7dfc8f3d155ea35d6ae60519cafac26661b700`.
- Signed-in read-only production QA collapsed Dinar from the 23-order expanded view, leaving the two Samo orders and Samo's 1,400.00 kg subtotal visible, then reopened Dinar and restored all 23 orders. Expanded state changed `true -> false -> true`, and the browser reported no warnings or errors. No Receive action was used and no purchase order, receipt, stock, or other business data changed. The inherited frontend audit remains seven findings (one moderate, six high).

## Active purchase orders grouped by supplier deployed (2026-08-17)

- Active backend and frontend release: `20260817_040859`; immediate rollback release/image: `20260815_123528`; database head: `0099_payroll_qr_edit_split`.
- The Active Purchase Orders receiving table now separates visible receivable lines by line-level supplier, falling back to the purchase-order supplier when needed. Each supplier section ends with the total original ordered quantity in kilograms. Non-kilogram accessory units are excluded rather than mixed into the kg total.
- The candidate was reconciled over the exact active `20260815_123528` source and preserved its Process QR runtime-locale correction. Exactly six existing source files changed and one regression script was added. The production build now runs the supplier-grouping contract automatically.
- Immutable archive SHA-256: `2a53c6a57bbfc82170c0f5c2d4d6029d7d4012921e47f3d91d020577f650a8bb`; 555-file source-manifest SHA-256: `ec7d00f7169cefe904aa44b1419e277bf675587ef5c0c4ccb34cb60ff0f7141d`; backend image ID: `sha256:8d983bd18542cacfa789f025844716989b278eab451934151f85a7fab9de16e2`; frontend build ID: `zeaKyxTncwBHAJ8no306E`.
- Verified pre-deployment backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260817_040859.dump`, 42,614,657 bytes, 928 restore objects, dump SHA-256 `03812713dcd3f96ebc6c44bc038f565c031d9ec72a0cff47b653033188616363`, restore-list SHA-256 `ec5e856a1a81d6dd1d58afd97c9075b9fd5280c7421aff69dd7f945fa901e42b`.
- Local and remote supplier-grouping, inventory-separation, branded-fabric, Process QR, locale parity (2,629 keys), strict TypeScript, targeted ESLint, candidate read-only queries, deterministic archive/manifest, migration, and 65-route builds passed. All four internal/public checks returned HTTP 200; two Uvicorn workers run with zero restarts, PostgreSQL reported 23 connections and zero invalid indexes at the final stability check, and shared model storage remained unchanged at 23,368 files / 3,457,241,715 bytes / digest `3f3a87714bf4805d9ff402291f7dfc8f3d155ea35d6ae60519cafac26661b700`.
- Signed-in read-only production QA showed 23 active purchase-order rows grouped under `Dinar` and `Samo`, with totals of 14,400.00 kg and 1,400.00 kg respectively, and no browser warnings or errors. No receive action was used and no purchase order, receipt, stock, or other business data changed. The inherited frontend audit remains seven findings (one moderate, six high).


## Process QR runtime-locale corrective deployment (2026-08-15)

- Active backend and frontend release: `20260815_123528`; rollback release: `20260815_123009`; database head: `0099_payroll_qr_edit_split`.
- The release preserves the active fabric/accessory receiving separation and its runtime translations, while adding the four Process QR sewing-closure/actual-output keys to the split EN/RU/UZ runtime locale bundles. The Process QR build contract now fails if those runtime keys are missing.
- Signed-in read-only verification showed six eligible sewing-closed orders, no raw `page.processQr.*` keys, a read-only 600-piece actual sewing quantity for `SO-2026-000095`, and the matching 600-piece batch/size quantity. No QR, payroll, order, stock, employee, or other business row was created or changed.
- Immutable archive SHA-256: `de9bdda5e69ce1a74e6d788c8d58835fa01fa83030baf6405fd74db6e2e2605d`; 554-file source-manifest SHA-256: `ef258413dc8aca0a456a8f74f57dd186ae3d9e7dc2a740db0963d269ecb098c3`; backend image ID: `sha256:8d983bd18542cacfa789f025844716989b278eab451934151f85a7fab9de16e2`; frontend build ID: `ZMFsgDE_d7uBuwc4Ly9Lo`.
- Verified pre-deployment backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260815_123528.dump`, 42,611,762 bytes, 928 restore objects, dump SHA-256 `6644a26ae05de60e47d710cacbdfea6f293f1af8ab3c8c177f222242539230af`, restore-list SHA-256 `8620fcd537863f75ac8dc2bd756dc814be656c90415675b3d84db3b340dcf118`.
- Locale parity (2,627 keys), Process QR contracts, strict TypeScript, targeted lint, local/remote 65-route builds, candidate read-only queries, both source manifests, all four internal/public health checks, two Uvicorn workers, zero restarts, zero invalid indexes, clean logs, and unchanged shared-storage fingerprints all passed. The inherited frontend audit remains seven findings (one moderate, six high).

## Fabric and accessory receiving/storage separation deployed (2026-08-15)

- Active backend and frontend release: `20260815_123009`; database head: `0099_payroll_qr_edit_split`. The candidate was reconciled over concurrent Process QR release `20260815_121308`, preserving all six of that release's changed files byte-for-byte.
- Inventory navigation now has dedicated Fabric Receiving and Accessory Receiving entries. Each receiving page loads only its own item group, warehouse type, and recent batches. Fabric-only color, image, and gramaj fields stay on Fabric Receiving; accessory returns and production-order issues stay on Accessory Receiving.
- Material and accessory storage pages remain separate and no longer expose an in-page group switch. The receive API also rejects fabric/semi-finished items sent to Accessory Storage and accessory/packaging items sent to Fabric Storage, including accessory returns.
- The first functional release `20260815_122459` was superseded after signed-in QA found raw labels from missing split runtime locale keys. Corrective release `20260815_123009` adds EN/RU/UZ runtime locale ownership and extends the build contract to require those keys.
- Release archive SHA-256: `09a1c5fa2afd6d9a35fe87137ca81b5306ef9f3c5f4211f8976da909468bdf60`; 554-file manifest SHA-256: `10ed03a6500eb4713e0932a032185e07e6f6d22b0705a8a05b51b25f6234f1f8`; backend image ID: `sha256:8d983bd18542cacfa789f025844716989b278eab451934151f85a7fab9de16e2`; frontend build ID: `JTFVJm7coz_oOK_rqhin_`.
- Verified final pre-cutover backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260815_123009.dump`, 42,611,612 bytes, 928 restore objects, SHA-256 `2fc03ca859191b4c159116ce3c8ccf07cd2f519e6b2f1a2a9ab6d50d7fd397d5`; restore-list SHA-256 `8c216790502bb1b2ce3d67795dbca563a12fb15588fe05309e0faf112e5750bd`.
- Validation passed: 32 relevant backend tests, receiving/storage and Planning fabric build contracts, runtime-locale contract, EN/RU/UZ parity, strict TypeScript, targeted ESLint, local and remote 65-route production builds, candidate migration, identical manifests, all four internal/public health checks, zero invalid indexes, zero backend restarts, and no new runtime error markers. Signed-in read-only Chrome QA confirmed correct Russian labels, Fabric Storage only on the fabric page, Accessory Storage only on the accessory page, accessory return/issue isolation, separate storage pages, and no console warnings/errors. No stock, receipt, return, issue, order, or other business row was created or changed.
- Persistent model-file storage remained unchanged at 23,356 files, 3,456,760,461 bytes, digest `f58bbda1796f0a3dfd53364e1242eba1ca42be53e9389bc6f611877b9a48b7c8`. The inherited frontend audit remains seven findings (one moderate, six high). Known-good application rollback release `20260815_121308` remains available and is schema-compatible with `0099`.


## Process QR sewing-closure and actual-output deployment (2026-08-15)

- The ERP-order source on Process QR now requests only production orders whose sewing work orders all have the explicit `completed` status; it does not infer sewing closure from plan, cutting, downstream progress, or rolled-up stage percentages.
- Process QR quantities now come from `SewingRecord.passed_qty` and `SewingRecord.size_quantities`, aggregated by production order, production batch, and garment size. ERP quantities are read-only, and multi-batch labels use the exact sewing-entered quantity for each batch/size instead of distributing the plan or cutting output.
- Manual Process QR mode remains editable for early-stage work that is not represented by an ERP production order.
- This change was deployed first in release `20260815_121308` and is preserved in active release `20260815_123528`.

## Audited Process QR edit and split workflow deployed (2026-08-15)

- Active backend and frontend release: `20260815_113703`; database head: `0099_payroll_qr_edit_split`. The release was reconciled over concurrent release `20260815_113056`, retaining the Planning fabric fix and the live Uzbek Qator corrections.
- Every issued Process QR card now has an edit action. Only never-scanned, never-returned, payroll-unlinked labels are editable. A normal correction changes the operation name and piece rate while preserving the label ID, QR token, printed QR number, quantity, and other work identity. Every correction is written to the audit log.
- An editable label can be split into 2–50 positive whole-number quantities whose sum must exactly equal the original quantity. The original row becomes a permanent `superseded` tombstone, its QR is rejected by both resolve and payroll-record creation, and each replacement receives a new QR identity. Superseded rows remain hidden from operational/report totals but are fetched internally by Process QR to prevent accidental deterministic reissue.
- Payroll record creation now treats issued labels as the server-side authority for operation identity, quantity, rate, currency, line, batch, size, and copy data. Cached or modified client payloads cannot override the issued wage calculation.
- The page tracks corrected/replacement label IDs for the current browser session and exposes **Print edited** so operators can reprint only changed labels. Scanned/unsafe labels show the edit control disabled. The existing card layout was retained, with a standard modal and compact Lucide edit action following CleanUI/Uncodixfy guidance.
- No payroll, QR, order, stock, employee, or other business row was created or modified during deployment or signed-in verification. Migration `0099` only added split-lineage/supersession schema fields and the expanded status constraint.
- Release archive SHA-256: `e1eef876af0704c8775f13bff108326e9bba41ccdebec57b25b5696f71ddec31`; 553-file manifest SHA-256: `083beeae7cd9a63c4e49ea1872e6bade1e10d42cceeaae159dddf078397ad805`; backend image ID: `sha256:ca537685ffc57512ca1f4cc865f63f8717f3b170cc6a400f2e3a306621f7b11b`; frontend build ID: `JwW7K2FAIkFxRod6oB52D`.
- Verified backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260815_113703.dump`, 42,601,272 bytes, 925 restore objects, SHA-256 `65a71dc493554831fbae6c9dc339a9222edcf22e0623efb795242648e3f86096`; restore-list SHA-256 `528f2d059be87535536e029c8372f4bc093d482042aad8b0b470f2bc86f64e4b`.
- Validation passed: 30 focused payroll tests, Python compilation/Ruff, single Alembic head, 2,615-key EN/RU/UZ parity, Process QR ordering/edit/split contracts, targeted ESLint, strict TypeScript, local and remote 65-route builds, both source manifests, all four internal/public health checks, two Uvicorn workers, zero restarts, zero invalid indexes, and no new error markers. Signed-in read-only Chrome QA confirmed enabled and disabled edit states, disabled `Print edited (0)`, the edit/split modal, two default split parts, and the permanent-old-QR warning; the modal was closed without saving.
- Rollback warning: after any label has been split, release `20260815_113056` is not a safe application rollback because it does not understand `superseded` labels. Roll forward with an application image containing migration `0099`, or perform a specifically planned database/application rollback from the validated backup.

## Any available Planning fabric restored and build-protected (2026-08-15)

- Active production release `20260815_113703` on backend and frontend includes this fix together with the concurrent audited Payroll QR edit/split work and the preserved runtime Uzbek Qator correction. Production is at Alembic `0099_payroll_qr_edit_split (head)`. The fabric change added no schema migration and created or changed no production order, stock, reservation, or other business record.
- Root cause: a later release accidentally restored both halves of an obsolete model-BOM compatibility rule that had already been removed on 2026-08-06. Planning displayed `Select an available fabric batch that matches this model's fabric type.`, and the backend independently rejected the same valid outside-BOM selection.
- Planning may again choose any available fabric or semi-finished batch for branded production. Matching model fabric remains sorted first as a convenience, and the first available batch is now the fallback when there is no match. The backend accepts the operator-selected batch and records its real batch ID, material SKU, and unit. Missing batches, non-fabric inventory, zero available stock, and failed/rejected QC batches remain blocked.
- Recurrence protection is now part of the normal frontend production build: `npm run build` first runs `check-branded-fabric-type-override.mjs`, which fails if the obsolete message/check returns or the all-batches fallback, stock filter, or QC filter disappears. The backend regression creates a positive-stock fabric batch outside model `#1`'s BOM and proves branded production accepts and records it.
- Release `20260815_113703` has a 553-file source manifest SHA-256 of `083beeae7cd9a63c4e49ea1872e6bade1e10d42cceeaae159dddf078397ad805`; release archive SHA-256 is `e1eef876af0704c8775f13bff108326e9bba41ccdebec57b25b5696f71ddec31`. Backend image ID is `sha256:ca537685ffc57512ca1f4cc865f63f8717f3b170cc6a400f2e3a306621f7b11b`; frontend build ID is `JwW7K2FAIkFxRod6oB52D`.
- Verified pre-cutover PostgreSQL backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260815_113703.dump`, 42,601,272 bytes, 925 restore objects, SHA-256 `65a71dc493554831fbae6c9dc339a9222edcf22e0623efb795242648e3f86096`; restore-list SHA-256 `528f2d059be87535536e029c8372f4bc093d482042aad8b0b470f2bc86f64e4b`.
- Validation passed: two focused backend tests, Python compilation, Ruff, the frontend regression contract, strict TypeScript, targeted ESLint, local and remote 65-route production builds, active source/compiled-artifact checks, both manifests, all four internal/public health checks, two Uvicorn workers, zero restarts, 17 PostgreSQL connections, zero invalid indexes, and no recent error markers. Signed-in read-only Chrome QA loaded the branded Planning page as Super Admin with no console warnings/errors; because there were no branded-order groups, no test order was created.
- The first fabric-only release `20260815_113056` was briefly active. Post-deploy reconciliation found that the prior `111745` manifest was stale and had omitted its two newer Qator locale files. Before a redundant corrective cutover, concurrent release `113703` incorporated those actual Qator files, this complete fabric fix, and migration `0099`; it superseded `113056`. Any rollback must use an application image containing migration `0099`, because the database is now at that revision.


## Runtime Uzbek Qator terminology correction deployed (2026-08-15)

- Active production release: `20260815_111745` on backend and frontend. Immediate rollback release/image: `20260815_105049`. Production remains at Alembic `0098_performance_indexes (head)`; no schema or business-data mutation occurred.
- Root cause: the earlier Qator change updated the legacy combined `dict.ts` and `supplemental.ts`, but the Next.js runtime loads split locale bundles. The active split files still had `field.section = "Seksiya"` and the old add/remove wording, so the live page correctly reflected those stale owning values.
- The actual runtime owners now use `Qator`, `Qator qo‘shish`, and `Qatorni olib tashlash` in `frontend/src/lib/i18n/locales/uz-base.ts` and `frontend/src/lib/i18n/locales/uz-supplemental.ts`. English and Russian remain unchanged; Daily Sewing Report behavior and layout are unchanged.
- The immutable candidate was rebuilt from the exact newer active 552-file release `20260815_105049` and changed only those two split Uzbek locale files. Release archive SHA-256: `b98d8a4c548506dd7ac0b5d86db8803f23cbb78f1ffe321afd4f7581b8ca9f5d`; identical source-manifest SHA-256 on both VMs: `f556b8b8de9014522d36cbc542b4c7d8beac22a3d8ceb45cd5cd6a01fc3a25e48`. Backend image ID: `sha256:6dd032422b93a67cc7068fda9716566a04d4d999b9f878178c6a2fb8a195d3f2`; frontend build ID: `PbxDqMDbrONhZukzXaZ8e`.
- Verified pre-cutover PostgreSQL backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260815_111745.dump`, 42,601,280 bytes, 925 restore objects, SHA-256 `5ccec793ffd88629bb17f6c624672cfcc4d7e485facbcb8ffe8776d6da2b1b396`; restore-list SHA-256 `fe716955fe520021a81a046e11133bc48458cd45e31d189eb2e3e22288adbdb4c`.
- Validation passed: 2,595-key EN/RU/UZ parity, strict TypeScript, zero-warning targeted ESLint, local and remote 65-route builds, candidate migration, identical manifests, and all four internal/public health checks. The active compiled bundle contains `field.section: "Qator"` and no `field.section: "Seksiya"`. Signed-in Chrome verification found one visible `Qator 1`, zero `Seksiya 1`, the `Qator qo‘shish` action, and no console errors. Runtime checks found two Uvicorn workers, zero restarts, OOM false, 5 of 100 PostgreSQL connections, zero invalid indexes, and no new backend/frontend error markers.

## Payroll operation ordering, void filtering, and safe QR size deletion deployed (2026-08-15)

- Active production release: `20260815_105049` on backend and frontend. Immediate rollback release/image: `20260815_103957`. Production remains at Alembic `0098_performance_indexes (head)`; this release added no migration and changed no business data during deployment.
- Paid operations on Process QR now have compact up/down arrow controls. Reordering marks the model operations dirty and the existing **Save to model** action persists the new sequence; labels continue to use that saved operation order. CleanUI and Uncodixfy guidance kept the existing table layout and introduced only standard Lucide icon controls.
- Payroll Summary now requests active records explicitly, and the backend defines `status=active` as every record except `voided`. Explicit `status=voided` remains available for audit/history views, while summary totals already excluded voided records.
- Issued Process QR labels now expose a **Delete size** action for each size group. Deletion is all-or-nothing, row-locked, permission-protected, and audited. It is rejected if any selected label was scanned, returned, linked to a payroll record, referenced by payroll history, from another size, or from another order. Only a complete never-scanned size group can be removed.
- The candidate was rebuilt from the exact active `20260815_103957` production source after a preflight caught the earlier release switch. Exactly ten source files changed. Release archive SHA-256: `50b1d7f6efa3e69cf9a9e9aab9dd94f37dec99beafdbe1363dd9c810d9d4acc3`; 551-file source-manifest SHA-256: `06f62ef1a46285b82bd7a58cf7de05a459a6ac97b085bedcc2349a4e09540ee0`. Backend image ID: `sha256:6dd032422b93a67cc7068fda9716566a04d4d999b9f878178c6a2fb8a195d3f2`; frontend build ID: `1QZPSBTHq2uRbwSifFvSX`.
- Verified pre-cutover PostgreSQL backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260815_105049.dump`, 42,601,258 bytes, 925 restore objects, SHA-256 `264349a6c9ce67d06bbf1dc8d7da7d63dfca76a23d0fbd13f8f59c2078a7d7ff`; restore-list SHA-256 `9ca05b08430b298f109ba8e41c9955ef2fb53d29446ba1ddfaa60cd6846d0a9d`.
- Validation passed: all 29 payroll backend tests, Python compilation and Ruff, 2,595-key EN/RU/UZ parity, Process QR ordering/manual-order and Payroll Scan autosave contracts, strict TypeScript, targeted ESLint, local and remote 65-route production builds, backend image build, candidate migration check, both manifests, and all four internal/public health checks. Signed-in read-only production QA found 42 up and 42 down controls, six size-delete buttons, no raw payroll status translation keys, and the Payroll Summary page loaded successfully. No button that changes production data was clicked.
- Runtime postflight found two Uvicorn workers, zero backend restarts, OOM false, ten PostgreSQL connections, zero invalid indexes, and zero recent backend/frontend error markers. The inherited frontend audit remains seven findings (one moderate, six high).

## Fabric receipt color persistence deployed (2026-08-15)

- Active production release: `20260815_103957` on backend and frontend. Immediate rollback release/image: `20260815_150511`. Production remains at Alembic `0098_performance_indexes (head)`; no schema or business-data mutation occurred during deployment.
- Root cause: receiving already persisted the entered color on `StockBatch.color`, but the Receive Fabric page kept newly entered colors only in transient React state and initialized that state empty after every reload. The color therefore disappeared from the selector even though the receipt retained it.
- Added protected read-only `GET /api/inventory/colors`, which returns distinct nonempty received batch colors with case-insensitive de-duplication and sorting. The Receive Fabric page now merges those persisted values with unsaved in-session entries and refreshes the list after a successful receipt. A color becomes reusable only after the receipt succeeds, so cancelled or failed receipts do not create false color master data.
- The candidate was rebuilt from the exact active 552-file production source and changed only `backend/app/api/routes/inventory.py`, `backend/app/tests/test_inventory_master_data.py`, and `frontend/src/app/(app)/inventory/receive/page.tsx`. Release archive SHA-256: `7924415d31b34c853a3e57d52bd7ddfc6624330de6b03eea400a9758dd1c8d6e`; identical source-manifest SHA-256 on both VMs: `9717fc9ee6d2719e0400b1a1ea366ac76907ee1fe78d8075b138addfd0f1ef6b5`. Backend image ID: `sha256:1de359fae96d1e453b8ca88fc2caafc12722392262d7861ecef4e9e3382cfc6e0`; frontend build ID: `s2XmpmK6erE5UO9ytbjao`.
- Verified pre-cutover PostgreSQL backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260815_103957.dump`, 42,600,890 bytes, 925 restore objects, SHA-256 `0601b7e166d88d95809fbdd0ef09a0310b395a4b93ca1b862e480a074d067c30`; restore-list SHA-256 `1bb428ff8fc8ab427a1ca6be819665d9ea8f821baee6e4f2cdcca79200389648`.
- Validation passed: the new receipt/color regression, strict TypeScript, zero-warning targeted ESLint, local and remote 65-route production builds, backend image build, candidate migration, identical manifests, and all four internal/public health checks. The broader inventory selection produced 31 passes and one inherited unrelated supplier-deletion expectation failure. Runtime verification found the new route registered, 59 distinct persisted colors, zero invalid indexes, two Uvicorn workers, zero container restarts, OOM false, and no new backend/frontend error markers. The unauthenticated endpoint correctly returned HTTP 401. No signed-in browser session was available for a final visual selector check.

## Daily Sewing Report “Qator” terminology deployed (2026-08-15)

- Active production release: `20260815_150511` on backend and frontend. Immediate rollback release/image: `20260815_093340`. Production remains at Alembic `0098_performance_indexes (head)`; no schema or business-data mutation occurred.
- In the Uzbek Daily Sewing Report, numbered entries now display as `Qator 1`, `Qator 2`, and so on instead of `Seksiya`. The matching controls now read `Qator qo‘shish` and `Qatorni olib tashlash`, and the Uzbek Excel/PDF export column header is also `Qator`. English and Russian wording and all report behavior are unchanged.
- The candidate was rebuilt from the exact active 552-file production source and changed only `frontend/src/lib/i18n/dict.ts`, `frontend/src/lib/i18n/supplemental.ts`, and `backend/app/services/sewing_daily_report_exports.py`. Release archive SHA-256: `a13b95d961b24ec6a731d0269f31703483ddca0982da90502b2dccd34e8b1b09`; identical source-manifest SHA-256 on both VMs: `5573ec363380f5985213f493c515d2444426320ef55e43a05b2467e757709a55`. Backend image ID: `sha256:98d7ef56ac8d24c6327b320fed53f40dcd5aa0528d874d5c02315a8b4c403a91`; frontend build ID: `pHBZM8RKwidkrCDEvTQvo`.
- Verified pre-cutover PostgreSQL backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260815_150511.dump`, 42,595,097 bytes, 925 restore objects, SHA-256 `1da43c487d8af26206566a8d362bd110ba67e5355026d9a423abc9953e84f68d`; restore-list SHA-256 `0a82e5890f4552ccfc1623f5dc297fc4c5be6409e5c1cb346c4f1d498038c484`.
- Validation passed: 2,586-key EN/RU/UZ parity, strict TypeScript, all seven Daily Sewing Report backend tests, both remote builds, candidate migration, source manifests, and all four direct/public health checks. Postflight confirmed the active frontend source and compiled chunks contain the new `Qator` strings, and the running backend image contains the `Qator` export header.
- The available Chrome session returned `Kirish taqiqlangan` for the protected Daily Sewing Report and the alternate browser was signed out, so the final visual signed-in page check could not be completed. Neither browser console reported warnings or errors. Runtime checks found two Uvicorn workers, zero backend restarts, OOM false, 464.2 MiB backend memory, 22 of 100 PostgreSQL connections, zero invalid indexes, and no new backend/frontend error markers. The inherited frontend audit remains seven findings (one moderate, six high).

## Employee-badge typography enlargement deployed (2026-08-15)

- Active production release: `20260815_093340` on backend and frontend. Immediate rollback release/image: `20260815_092238`. Production remains at Alembic `0098_performance_indexes (head)`; no schema or business-data mutation occurred.
- Employee badge print typography on the existing 60 mm x 40 mm layout is now larger and explicitly bold at weight 700: employee name `9.5pt`, ID/department/role details `8pt`, and employee-number footer `8.5pt`. The 21 mm QR size, three-line department allowance, badge dimensions, employee-number payload, and legacy badge compatibility are unchanged.
- The candidate was rebuilt from the exact active 551-file source and changed only the Process QR label CSS plus its focused source contract. Release archive SHA-256: `a27f2129ed38c93c7ddf88314ec8b2cd3fc64a2b515e0c731c4d81d7072143f1`; identical source-manifest SHA-256 on both VMs: `4d5efebc1bb94f77dc63139e9187652dfd211d8363603e6f4e753e493abe937f`. Backend image ID remains `sha256:2778eb46f3965ff8b4369fb89f1f72197767bb5a669139109fe4eb563dc785c4`; frontend build ID: `UCMHjHBWWv6m68ajQYB5a`.
- Verified pre-cutover PostgreSQL backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260815_093340.dump`, 42,594,823 bytes, 925 restore objects, SHA-256 `e8bf90c1fb7bdbffc0261c452a43917d2cd36563fa6ce585d73bfb7ff5459256`; restore-list SHA-256 `1adb7ef75f4357025b0f7b0c03eac15cea5dd12302c04bb0f58bb057ee2e8c34`.
- Validation passed: 2,586-key EN/RU/UZ parity, Process QR print contract, strict TypeScript, targeted ESLint, local and remote 65-route production builds, backend image build, migration check, and all four direct/public health checks. Signed-in read-only production verification confirmed the page loads without console errors and the deployed stylesheet contains the exact `9.5pt`, `8pt`, and `8.5pt` weight-700 rules. No print action was triggered.
- Final runtime audit found two Uvicorn workers, zero backend restarts, OOM false, zero recent backend/frontend error markers, 21 PostgreSQL connections, and zero invalid indexes. The inherited frontend audit remains seven findings (one moderate, six high).

## Employee-number payroll badges and manual scan deployed (2026-08-15)

- Active production release: `20260815_092238` on backend and frontend. Immediate rollback release/image: `20260815_090752`; the pre-change stable release `20260815_081545` is also retained. Production remains at Alembic `0098_performance_indexes (head)`; no schema or business-data mutation occurred.
- Employee badges now show and encode the real `Employee.employee_no` instead of the internal database row ID. Employees without a configured number retain the explicit `EMP-####` compatibility fallback, and previously printed legacy 9-digit employee tokens continue to resolve.
- Payroll Scan now accepts a typed employee number, resolves it case-insensitively to the internal employee ID, and displays the real employee number. Employee labels use larger `7.2pt` bold detail text on the 60 mm x 40 mm print layout, with up to three department lines so the department and role remain visible. English, Russian, and Uzbek scanner/help text was updated in the split production locale bundles.
- The first candidate `20260815_090752` passed functional verification but its new placeholder exposed a raw translation key because production loads split locale bundles. The signed-in UI gate caught this before completion; corrective release `20260815_092238` added the same translations to the actual split bundles and passed the repeated build and verification process.
- Final release archive SHA-256: `a696cdbcfd682ff77cf0353aa241ae61db31b15c5d21d8fdd53d8d08296a2ffb`; identical 551-file source-manifest SHA-256 on both VMs: `4692e0e8de9553f648aa9118894d3521ec36835a869e6a553c66827473587822`. Backend image ID: `sha256:2778eb46f3965ff8b4369fb89f1f72197767bb5a669139109fe4eb563dc785c4`; frontend build ID: `iDsGthIdCfvtNpOwlNjqq`.
- Verified pre-cutover PostgreSQL backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260815_092238.dump`, 42,594,830 bytes, 925 restore objects, SHA-256 `f3cfaa77cda41dd19c9fb3a062b103883cccdcee0e767a8f975d9cc27a726716`; restore-list SHA-256 `c67d4d80fa5074ee39335f5a98823604f04b17dae3a8fe642192f111b0c1733d`.
- Validation passed: 28 payroll tests, 2,586-key EN/RU/UZ parity, Process QR and Payroll Scan source contracts, strict TypeScript, local and remote 65-route production builds, backend image builds, migration checks, and all four direct/public health checks. Signed-in read-only verification confirmed A'zamova Durdona appears as employee `2193` in Process QR and its badge preview, and typing `2193` in Payroll Scan selects the same employee with no raw key. No label was printed and no payroll or other business record was created or changed.
- Final runtime audit found two Uvicorn workers, zero backend restarts, OOM false, zero recent backend/frontend error markers, 20 of 100 PostgreSQL connections, and zero invalid indexes.

## Production test shipment cleanup (2026-08-15)

- At the user's request, empty test warehouse-exit shipment `SH-2026-000001` (database ID `2`, reference `Shavkat aka Ukraina`) was deleted from production.
- Pre-delete validation confirmed status `created`, null Sales order/customer, zero package links, zero scan logs, and no shipped or delivered timestamp. The transaction rechecked and locked the row before deleting exactly one `shipments` row. No package, scan, stock, reservation, or other business row was deleted or changed.
- The two existing shipment audit records were preserved, and one `delete_test_shipment` audit entry was appended with the old shipment values and user-confirmed cleanup reason. The normal shipment-number generator will reuse `SH-2026-000001` for the first real shipment because no shipment rows remain.
- Verified pre-delete PostgreSQL backup: `/opt/milana-erp/shared/backups/milana_erp_pre_delete_test_shipment_20260815_090637.dump`, 42,594,719 bytes, 925 restore objects, SHA-256 `047a19b67f321123668d0bf926784d4e3cde5f90e30639c5d2dfba8928c501b7`; restore-list SHA-256 `57e6cb40b04a52cf64ca7c756d8c3c307f1830c8697a5f1f30d0e707a0d7ac92`.
- Post-delete verification found zero shipments, zero shipment-package links, and zero shipment scan logs. Packages remained `178`; finished-goods rows remained `1,051`, with quantity/available `11,355`, reserved `0`, and sold `0`. Direct and public backend health remained OK. Active application release stayed `20260815_081545`; Alembic stayed at `0098_performance_indexes`.

## Process-label single-name-word split deployed (2026-08-15)

- Active production release: `20260815_081545` on backend and frontend. Immediate rollback release/image: `20260815_071952`. Production remains at Alembic `0098_performance_indexes (head)`; no schema or business-data mutation occurred.
- The sewing-line identity now uses both available print lines efficiently: the line code and surname remain together on the first line, while only the final personal-name word and any suffix move to the second line. For example, `SEW-13 Maxmudova` prints above `Nargiza - 2`. Model and sewing-line type remains `6pt` bold; every other 60 mm x 40 mm label field is unchanged.
- The immutable candidate was rebuilt from the exact active 551-file source and changed only `frontend/src/app/(app)/process-qr/page.tsx` plus its focused ordering/source contract. Release archive SHA-256: `73c5d50e7f38af15dfd54a46bbfc6b439515453e9a17d143309449c35f80be4b`; identical source-manifest SHA-256 on both VMs: `383d73df9bfe2c592668d3a44c22ae2b297d5c9be0a0b91d5497f7a15c8d7291`.
- Frontend build ID: `4DeWbhKcFdEz0TYNkm8Uy`; unchanged backend image ID: `sha256:113aed32d20b9f6c53fc3f644ac6a94a6b0cbc8bd2c45caee9fefe1490abd758`. The exact split regression, focused source contract, strict TypeScript, zero-warning targeted ESLint, remote 65-route frontend build, backend build, backup validation, and migration check passed. The inherited frontend audit remains seven findings (one moderate, six high).
- Verified pre-cutover PostgreSQL backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260815_081545.dump`, 42,594,426 bytes, 925 restore objects, SHA-256 `73d238a29c68c90cf61dd8d786890de41f176fa654dbc69d6ba3419e197db6e0`; restore-list SHA-256 `5a92c6c2f0c656a59f80ac1407ee8ca5fa4855c3bb7702bd0cecedd217b54d92`.
- Signed-in, read-only production verification found 282 work labels and confirmed the live first sewing-line value is exactly `SEW-13 Maxmudova\nNargiza - 2`; the controlled `pre-line` rule is loaded and the browser reported no warnings or errors. No print or data-changing action was performed.
- Final verification found two Uvicorn workers, zero container restarts, 20 of 100 PostgreSQL connections, and zero invalid indexes. Direct backend health, direct frontend login, public health, and public login returned HTTP 200.

## Process-label sewing-line wrap deployed (2026-08-15)

- Active production release: `20260815_071952` on backend and frontend. Immediate rollback release/image: `20260815_071534`. Production remains at Alembic `0098_performance_indexes (head)`; no schema or business-data mutation occurred.
- On every 60 mm x 40 mm process label, the sewing-line code now prints on the first line and the complete sewing-line/person name prints on the second line. Both the model and sewing-line identity values use `6pt` bold type; all other label text, QR placement, numbering, and Kroy footer remain unchanged.
- Two newer releases became active during guarded preflight. Both attempts stopped before upload or symlink changes, and the final candidate was rebuilt from the exact 551-file source of release `20260815_071534`. This preserved its newer Finished Goods and Shipments work and overlaid only the Process QR label page plus its focused source contract.
- Release archive SHA-256: `a9d24db294f56096c3d1c39a1c48ca08063c998fde21d754b09eefbe1b288310`; identical source-manifest SHA-256 on both VMs: `b5f08263a456aae1dadaf7c05f4ddf3577fd9a0488f587146b2afcd7bf0c5152`. Frontend build ID: `-Ane99j0EERO-wcJF3GX9`; backend image ID: `sha256:113aed32d20b9f6c53fc3f644ac6a94a6b0cbc8bd2c45caee9fefe1490abd758`.
- Verified pre-cutover PostgreSQL backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260815_071952.dump`, 42,594,422 bytes, 925 restore objects, SHA-256 `10e501eb8d91aeffdd5b220a974fcbaa727a25c2626e2efc6d38e9486260e14d`; restore-list SHA-256 `e4e1fb96573362204a837cc1cf003e8767163a3815ed8bbb3d6ee0196105d8a3`.
- The focused ordering contract, strict TypeScript, zero-warning targeted ESLint, local checks, remote 65-route frontend build, backend build, backup validation, and migration check passed. The inherited frontend audit remains seven findings (one moderate, six high).
- Signed-in, read-only production verification found 282 work labels, each with one model identity and one sewing-line identity. The live value rendered as `SEW-13`, a controlled newline, then `Maxmudova Nargiza - 2`; the deployed stylesheet contained the `6pt` and `white-space: pre-line` print rules, and the browser reported no warnings or errors. No print or data-changing action was performed.
- Final verification found two Uvicorn workers, zero container restarts, 17 of 100 PostgreSQL connections, and zero invalid indexes. Direct backend health, direct frontend login, public health, and public login returned HTTP 200.

## Ready-product warehouse exit without Sales order deployed (2026-08-15)

- Active production release: `20260815_071534` on backend and frontend. Immediate rollback release/image: `20260815_070630`. Backend image ID: `sha256:b5d14c5d5be2ec66b3acc29cb175aab7091c73049f2ecf366282efc3d07f0808`; frontend build ID: `TtOJOaoTsicNASDO7BQ9E`. Production remains at Alembic `0098_performance_indexes (head)`; no migration or business-data mutation occurred.
- Finished Goods now exposes an EN/RU/UZ `Create warehouse exit` action that opens Shipments in a dedicated `Without sales order` mode. Warehouse staff must enter a recipient, destination, or approved reason, then scan each package label before confirming the exit.
- The orderless path consumes only existing package-backed finished-goods stock. It rejects packages tied to a Sales order, reserved stock, packages already attached to another open shipment, packages not received into storage, and packages whose full quantity is not available in finished-goods stock. Orderless records remain audited shipments with null `sales_order_id`, API type `warehouse_exit`, and the reference retained in shipment notes.
- Both `/ship` and the legacy `/mark-shipped` alias now require all attached packages to be scanned and ready. Delivery is blocked until the shipment is shipped, closing the documented shipment-scan and premature-delivery bypasses for these endpoints.
- A concurrent Process QR label release `20260815_065927` appeared during staging. The warehouse candidate was rebuilt from that exact active 551-file source so the Process QR work was preserved. Signed-in verification then caught an untranslated Uzbek CTA caused by a stale supplemental-key bundle; the final immutable hotfix moved the warehouse-exit copy into the two owning page bundles. Final release archive SHA-256: `244ecb261133c2dc3bc48f128137922a0ad7f13aa0ce340360aac92be3f70b62`; identical 551-file source-manifest SHA-256 on both VMs: `93f677e82266aff4dee0cdce9180cd86e881a0f1712f52531f04c58132e14602`.
- Backend regression coverage passed 16 unique tests: the full 13-test traceability/forecasting module plus Sales-order reservation shipping, same-model substitution, and scan idempotency. The complete create/add/scan/ship/deliver orderless flow, duplicate-open-shipment protection, stock consumption, Ruff, Python compilation, strict TypeScript, targeted ESLint, EN/RU/UZ parity, three remote backend builds, and three 65-route production frontend builds passed. The inherited npm audit remains seven findings (one moderate, six high).
- Verified final pre-cutover PostgreSQL backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260815_071534.dump`, 42,594,436 bytes, 925 restore objects, SHA-256 `33401c306073cb22b4044648132530e65a1f14460b08dfa02b930111cb85adee`; restore-list SHA-256 `2924d9635c493e0584bf6e6dc8b123f3e5e4318c413a2c9189d8c1fc71de48fa`.
- Signed-in, read-only production verification showed the Uzbek `Ombor chiqimini yaratish` action on Finished Goods, visible and linked to `/shipments?mode=warehouse_exit`; no shipment or stock action was submitted. Before and after deployment, shipments, shipment packages, and shipment scans remained `0`; packages remained `178`; finished-goods rows remained `1,051`, with quantity/available `11,355`, reserved `0`, and sold `0`.
- Final verification found one Uvicorn parent with two workers, 437.3 MiB backend memory, 84 PostgreSQL connection slots of headroom, and no new traceback, exception, 5xx, or frontend service error. Direct backend health, direct frontend login, public health, and public login all returned HTTP 200.

## Process-label model and sewing-line text sizing deployed (2026-08-15)

- Active production release: `20260815_065927` on backend and frontend. Immediate rollback release/image: `20260815_094716`. Production remains at Alembic `0098_performance_indexes (head)`; no schema or business-data mutation occurred.
- On 60 mm x 40 mm process labels, only the model value and sewing-line name now use the smaller `6.5pt` bold type with `1.05` line height. This applies consistently to every process label, prevents long model and line names such as Bozorova Nargiza from being clipped, and leaves all other label text, QR placement, numbering, and Kroy footer unchanged.
- The immutable deployment candidate was rebuilt from the exact active 551-file production source and overlaid only the process-label page and its ordering/source contract. The separate local ready-product warehouse-exit work was not included. Release archive SHA-256: `fadf45e22fd2eef5b1afbcf7849ef8874e89ce1750f1d2f3af91f61edd5717b2`; identical source-manifest SHA-256: `33818b6e8ab543756c0c6cde13003d6e2e0d7c007ffc32a8f968a9998df14019`.
- The process-label ordering contract, strict TypeScript, targeted ESLint, local production checks, remote 65-route frontend build, unchanged backend image build, and migration check passed. Frontend build ID: `dBIWRDUaAtZzce8HoyvxJ`; backend image ID: `sha256:288c2180be29e67d0517a4ca391b8d4491d856328c5e7ccecb2385efa5a00728`.
- Signed-in, read-only production verification reloaded the live Process QR page and found 282 existing work labels with exactly 564 identity-value bindings: one model and one sewing-line value per label. The deployed print stylesheet contained the scoped `6.5pt` rule, including the full live line value `SEW-13 - Maxmudova Nargiza - 2`, and the browser reported no warnings or errors. No print or data-changing action was performed.
- Verified pre-cutover PostgreSQL backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260815_065927.dump`, 42,594,427 bytes, 925 restore objects, SHA-256 `2c92bd2c842f0177088ccd0653f0ac54b8aada9a10b05dacdb8f59aa6bff0b27`; restore-list SHA-256 `ce8f17b7d5360688174391473764ce89f8f2d305ae482bababde3d1614d8691f`.
- Final verification found two Uvicorn workers, zero container restarts, 21 of 100 PostgreSQL connections, and zero invalid indexes. Direct backend health, direct frontend login, public health, and public login returned HTTP 200. The inherited frontend audit remains seven findings (one moderate, six high).

## Performance remediation and production re-audit deployed (2026-08-15)

- Active production release: `20260815_094716` on backend and frontend. Backend image: `milana-backend:20260815_094716` (image ID `sha256:288c2180be29e67d0517a4ca391b8d4491d856328c5e7ccecb2385efa5a00728`); frontend build ID: `52B_JDLWbJCHlSSr36YCh`. Production is at Alembic `0098_performance_indexes (head)`.
- Immediate application rollback is release/image `20260815_040053`. Its source does not contain revision 0098, so before starting that older image use the 0098 image to stamp the version marker back to `0097_model_lookup_indexes`; the additive indexes can remain and are backward-compatible. A normal 0098 downgrade instead removes the indexes.
- The remediation added response gzip and Server-Timing/slow-request instrumentation; replaced finished-goods and branded-stock N+1/repair-on-GET behavior with joined read-only queries; bulked process-tracking, packaging-inbox, and active-production lookups; paged variant-family identities before hydration; added notification/task summary endpoints; added 12 concurrent relationship/workflow indexes; and reduced client polling, process-QR fetch size, clock updates, hidden WebGL animation, global font loading, and initial locale payloads.
- Measured production medians improved from 1,528.68 ms to 44.53 ms for finished goods (-97.1%), 3,963.97 ms to 155.58 ms for branded stock (-96.1%), 288.16 ms to 113.53 ms for 50-row process tracking (-60.6%), 235.53 ms to 112.20 ms for work orders (-52.4%), and 106.35 ms to 23.56 ms for the 100-row model list (-77.8%). Finished-goods SQL statements fell from about 1,052 to one; 25-row process tracking fell from 117 to 21.
- API gzip reduced the 425,862-byte finished-goods body to 9,452 wire bytes. Public login asset transfer fell from 336,769 to 257,776 bytes (-23.5%), while representative initial route-JS gzip fell 42-54%. Repeated Lighthouse mobile runs remained 99/100 with CLS 0; transfer weight fell from 430,375 to 352,126 bytes. The evidence-backed re-audit score is 90/100 overall, not a claimed perfect score.
- Image quality and quantity were preserved: no source image was re-encoded or removed. At cutover `/app/storage/model_files` was identical before and after: 23,147 files, 3,447,967,215 bytes, aggregate SHA-256 `12f49a1df9dc0f24ddd97c66a4a7703862e521fe58e1942e315d588927fe3e50`.
- Verified pre-cutover PostgreSQL backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260815_094716.dump`, 42,580,173 bytes, 925 restore objects, SHA-256 `c8b50ff925a375e9d0d5414cf08030e10c5c2c20ad9b069d60f180ccfb9bf4bb`; restore-list SHA-256 `4dd38b881e1c9de764aa9445231cd0c2d30e39c09d3ea959d1b3e1ba06b2ee6c`. An earlier verified backup for candidate 094435 also exists. Its first migration attempt created the concurrent indexes but stopped before updating Alembic because the initial revision identifier exceeded the 32-character version column; the active release stayed unchanged, the identifier was shortened, all indexes were confirmed valid/ready, and the idempotent corrected migration completed.
- Release archive SHA-256: `b6932e13b49385728cd8f8acf8406aeca4b16fd316f1249a37592abfb9a7f9dd`; identical 551-file source-manifest SHA-256 on both VMs: `961549db0a7355a1910e7c96212130f534884df491acc428ca07bc79dfb084c0`.
- Exact baseline regression was 406 passed / 12 failed; the optimized candidate was 410 passed / the identical 12 inherited failures, including four new performance contracts. Frontend typecheck, zero-warning lint, 2,572-key locale parity, targeted UI contracts, local/remote backend builds, and both 65-route frontend builds passed. The inherited inventory supplier-edit source-contract check and seven npm advisories (one moderate, six high) remain.
- Both Uvicorn workers run with zero restarts; PostgreSQL reported 22 of 100 connections and zero invalid indexes during final verification. Recent backend/frontend logs contained no new error markers. Direct backend health, direct frontend login, public health, and public login all returned HTTP 200.
- Remaining performance work: variant-group serialization is still about one second and returns 296 KB decoded; several legacy collection APIs remain large/unbounded; `pg_stat_statements` is not enabled; authenticated RUM/p95/p99 monitoring and tested container resource limits are still absent. The 151 foreign keys without a leading index must be ranked from workload evidence rather than indexed blindly.


## Searchable Payroll Summary employee filter deployed (2026-08-15)

- Active production release: `20260815_040053` on backend and frontend. Immediate rollback release/image: `20260815_034106`. Alembic remains `0097_model_lookup_indexes (head)`; no schema or business-data mutation occurred.
- The Payroll Summary employee filter is now an accessible type-ahead selector instead of a long native dropdown. It searches employee name, employee number, position, department code, and department name, while preserving the `All employees` default and existing payroll filtering behavior. English, Russian, and Uzbek search/no-result text was added.
- The immutable candidate was rebuilt from exact active release `20260815_034106` and overlaid only `frontend/src/app/(app)/payroll/page.tsx` and `frontend/src/lib/i18n/supplemental.ts`. Release archive SHA-256: `15c4f92e68312125e3944d3dfa162c638dea29d69ecf6905168a2775de60a791`; identical 544-file source-manifest SHA-256 on both VMs: `0dc15f1afe9dbca91368bf30386fbe0a6b0406ff2dda8b7c63b36ea1f90cb8ce`. Backend image ID: `sha256:d786c9e72726be7cf819a32517c5545193cf3e509c84b34d65a1d790a5253078`; frontend build ID: `H8Bc54t4ehMZDlOpI5OoS`.
- Verified pre-cutover PostgreSQL backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260815_040053.dump`, 42,569,168 bytes, 913 restore objects, SHA-256 `40b2ae9ce48cb9fa1e5ba3c9fb77a91513be90846170daa8d30bb65c41b7a961`; restore-list SHA-256 `0dcd83ef78e171746e6f123c7f6bc00b4b378f63a72c428300d09d5ed1792c0a`.
- The focused employee-search contract, translation parity (2,572 keys per locale), strict TypeScript, local and remote 65-route production frontend builds, unchanged backend image build, migration check, and source-manifest checks passed. Signed-in read-only production verification typed `Durdona` and correctly narrowed the selector to `A'zamova Durdona` and `Salomova Durdonaxon`; no employee was selected and no data was changed. The browser reported no warnings or errors.
- Direct backend health, direct frontend login, public health, and public login returned HTTP 200. The backend runs two Uvicorn workers with zero restarts and used 435.8 MiB; PostgreSQL used 14 of 100 connections. Recent backend and frontend startup logs contained no new errors or tracebacks. The inherited frontend audit remains seven findings (one moderate, six high).

## Sewing production Excel export deployed (2026-08-15)

- Active production release: `20260815_034106` on backend and frontend. Immediate application rollback release/image: `20260815_030847`. Alembic remains `0097_model_lookup_indexes (head)`; no schema or business-data mutation occurred.
- The Sewing Production Report toolbar now downloads a true `.xlsx` workbook instead of CSV. The workbook uses the active report filters and language, retains QR/employee/line/cutting/model/product/operation/size details, stores quantity/rate/amount as numeric cells, includes totals, freezes the header, and neutralizes formula-like user text.
- The immutable candidate was rebuilt from exact active release `20260815_030847` and changed three existing source files plus one new backend export service. Release archive SHA-256: `4484349ebd90f35d0f318d097c73e444ec7a7d1379f36367a66904b28aeee1c2`; identical 544-file source-manifest SHA-256 on both VMs: `5b055d2295b1771dff355268d68e825d78ed4ef3cc5987212e553eb455ff8e12`. Backend image ID: `sha256:d786c9e72726be7cf819a32517c5545193cf3e509c84b34d65a1d790a5253078`; frontend build ID: `vg4vT6y12KBeJwc4_-Ttractive`.
- Verified pre-cutover PostgreSQL backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260815_034106.dump`, 42,569,166 bytes, 913 restore objects, SHA-256 `d0ce8a5eda4ac7b7fe896509812320660f39492b1e320d97a941cbe674c4ab0b`; restore-list SHA-256 `d69380049f42243715617b33a7ebe1fe30c28d2a588afb276b42d9accab7c1cf`.
- Local validation passed all 27 payroll tests, the sewing-report export/print contract, TypeScript, Python compilation, and the 65-route production frontend build. Both remote builds and the candidate migration check passed.
- Signed-in, read-only production verification showed the Excel action with five filtered rows and confirmed `GET /api/payroll/reports/sewing-production.xlsx` returned HTTP 200. Both Uvicorn workers are running with zero container restarts; the backend used 480.3 MiB and PostgreSQL used 22 of 100 connections. Direct backend health, direct frontend login, public health, and public login all returned HTTP 200; recent backend/frontend logs contained no new startup errors or tracebacks.

## Bounded model API incident fix deployed (2026-08-15)

- Active production release: `20260815_030847` on backend and frontend. Immediate application rollback: `20260814_113548`. Production is at Alembic `0097_model_lookup_indexes`; the additive index is forward-compatible with the rollback application, so an immediate application rollback does not require a database downgrade.
- Root cause confirmed in `catalog.py`: `GET /api/models` applied `LIMIT/OFFSET` only when `include_total=true`, then serialized ORM models after eager-loading every image and BOM relationship. `GET /api/models/{id}/variants` loaded every model and filtered the family in Python.
- The deployed API always validates and applies model-list pagination (default 50, maximum 100), projects compact columns with one correlated thumbnail, keeps COUNT optional, adds compact `GET /api/model-options` (default 30, maximum 50), and performs bounded variant-family SQL using the generated `model_group_key` from migration `0084`.
- Migration `0097_model_lookup_indexes` created `ix_models_legacy_status_created_id` concurrently for status-filtered selector/list order. Existing `ix_models_model_group_key_id` remains the variant lookup index; signed production verification confirmed both indexes are ready and valid.
- All frontend collection-style `/api/models` calls were removed. Planning uses a shared 300 ms debounced, cancellable, incrementally paged selector; Cutting Passports fetches only the chosen production order's model detail; model variants explicitly request 50-row pages.
- A 6,606-row local regression benchmark returned 100 rows in a 22,301-byte payload, averaged 37.1 ms/request across ten requests during the final full suite, and recorded 0.93 MiB peak traced allocation. The focused endpoint suite, frontend contract checks, i18n, lint (zero errors), strict TypeScript, and the 65-route production build passed.
- The final full backend run completed with `405 passed, 13 failed`; all six bounded-model endpoint regressions passed. The remaining failures are the inherited catalog separator, supplier deletion, legacy finished-goods, package/material-label, sewing model-number/factory-routing/rework/inbox, and legacy purge expectations; none exercises the new bounded model endpoints.
- The immutable candidate was rebuilt from exact active release `20260814_113548` and changed 20 existing files plus six new files, with no removals. Release archive SHA-256: `ecdf952e200d20dc9200e0f443084d22df4eeb20ce9746bd15ee80f0ee1c2375`; 542-file source-manifest SHA-256: `235a7ec082d5b3b1a049ea149c915dde3ae6da9ba698188dac3542ae68d851ba`. Backend image ID: `sha256:87460c424592fd6441a63f47159ad7ad54056386a3aa7692a6c6638d604a8b90`; frontend build ID: `VPMIeVGb7f_rYDio6mKvt`.
- Verified pre-cutover PostgreSQL backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260815_030847.dump`, 42,565,560 bytes, 912 restore objects, SHA-256 `4d93b51eed5a56a877d7545ebda8532cb7229015c6c368e89fcef3f763da4db0`; restore-list SHA-256 `bf42899c1766a6399d4659e16bfc8e99c44255623504643b1cc2d1f93abd788b`.
- Signed read-only production verification returned the default 50-row model page in 15,194 bytes and 66.6 ms, a seven-row counted page over 6,606 total models in 22.6 ms, seven model options in 20.5 ms, an exact-ID lookup in 11.9 ms, and three bounded variants in 38.3 ms. A `page_size=101` request returned HTTP 422. Model and audit row counts were unchanged.
- Both remote builds, source-manifest checks, migration/index validity, two-worker runtime and zero-restart checks, recent backend/frontend error scans, and all four internal/public health/login checks passed. The backend used 476.4 MiB at the final stability snapshot and PostgreSQL used 15 of 100 connections after cutover. The inherited frontend audit remains seven findings (one moderate, six high).

## Packaging stickers without Sewing total deployment (2026-08-14)
## Packaging stickers without Sewing total deployment (2026-08-14)

- Active production release: `20260814_113548` on backend and frontend. Immediate rollback release/image: `20260814_110200`. Alembic remains `0096_batch_item_consistency`; no schema or business-data mutation occurred.
- Packaging can now save its production record and create package stickers without waiting for Sewing to enter `passed_qty`. When the formal Sewing-to-Packaging receipt workflow is not in use, cumulative Packaging input is limited by the selected production batch plan, or by the Packaging work-order plan for an unbatched order. Orders that do use Packaging receipts remain strictly capped by the quantity actually received from Sewing.
- The reported production target was verified read-only before and after deployment: Packaging work order `#288` belongs to `PO-2026-000071`, batch `0075-01 / #29` is planned for 462 pieces, the Packaging work-order plan is 600, and Packaging still has zero records, zero passed/input quantity, and zero receipts. The order has nine Sewing records whose combined passed quantity is zero. Deployment did not create a package, sticker, or production record.
- The new end-to-end regression saved 420 packed pieces against a 462-piece batch while Sewing remained at zero, created a 60-piece package, rendered its printable label, and rejected a cumulative 463-piece Packaging entry against the 462-piece batch plan. Receipt-limit and internal-batch regressions also passed. The broader Packaging selection produced 19 passes and three inherited failures; the complete stateful production-flow module produced 68 passes and seven known unrelated label-image, factory-scope, and test-state failures. Python compilation, Ruff, and the 65-route frontend production build passed.
- Backend image: `milana-backend:20260814_113548` (image ID `sha256:cd9488bcf83004409632c649573cf2b45e3c318245489d31bbd5f09996620a92`); frontend build ID: `b543GFEp2YmcM4K52seLl`. Release archive SHA-256: `451b41f201a8b97a1f26d4699bd827441521b54d2cb0f8118622bc4905edfffd`; 536-file source-manifest SHA-256: `e56764e8e339c1a64dc541aba7f0e52955d56f7aa26746bcecaf1b36bf9ba4ca`.
- Verified pre-cutover PostgreSQL backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260814_113548.dump`, 42,532,764 bytes, 912 restore objects, SHA-256 `4f2c16279be1f0563b8ad14aa18c2f2a25f5e18dd92cb87bed6ba7f23a415bbf`; restore-list SHA-256 `8e69750850efdff800b0572867f7199e5448ea4e22d8953e0f9d6ba902329922`.
- Signed-in read-only production checks confirmed the loaded plan-based handler and unchanged work-order evidence. Direct backend health, direct frontend login, public health, and public login returned HTTP 200. The backend runs two workers, used 13 of 100 PostgreSQL connections after cutover, and had no new 5xx/traceback markers. The inherited frontend audit remains seven findings (one moderate, six high).

## Cutting inbox downstream-work filter deployment (2026-08-14)

- Active production release: `20260814_110200` on backend and frontend. Immediate rollback release/image: `20260814_044538`. Alembic remains `0096_batch_item_consistency`; no schema or business-data mutation occurred.
- The normal Cutting queues now exclude production orders that have verifiably progressed beyond Cutting: a downstream production status, started/counted downstream work, bundles transferred to Printing/Sewing, packages, or finished-goods rows. Untouched Cutting work remains visible, and replacement-cutting work continues in its dedicated section. The Done Today history is unchanged.
- Signed-in production verification reduced the normal Cutting queue from nine unique orders to one. `SO-2026-000001`, `SO-2026-000034`, `SO-2026-000048`, `SO-2026-000049`, `SO-2026-000055`, `SO-2026-000056`, `SO-2026-000081`, and `SO-2026-000083` are absent because of downstream/package/finished-goods evidence. `SO-2026-000106` correctly remains the sole pending Cutting item because it has no active downstream department; its five payroll records are voided.
- The guarded production check reconfirmed all nine production orders and their evidence unchanged: 60 packages totaling 4,320 pieces, 352 finished-goods rows totaling 4,320 pieces, and `SO-2026-000106`'s 270 payroll labels plus five payroll records.
- Python compilation, Ruff, and three focused inbox regression tests passed. The complete stateful production-flow module produced 66 passes and eight existing order-dependent failures when run monolithically; the changed inbox tests pass independently. Both builds passed, including the unchanged 65-route frontend build. The inherited frontend audit remains seven findings (one moderate, six high).
- Backend image: `milana-backend:20260814_110200` (image ID `sha256:b91798771762c9fab6285745814ee26c3617410605a09d5e9a84dfcbcbe0c580`); frontend build ID: `5lPeMsi3atc7PPrW3dX-g`. Release archive SHA-256: `cc208f7c9945e8896a9f22cc7e1a17c2833c202ef8bdb9345326f6fce082aaf1`; 536-file source-manifest SHA-256: `77a807c37c3ac756d78afddb8890523b0e3feef90c0c2433dc1da854f00b9b50`.
- Verified pre-cutover PostgreSQL backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260814_110200.dump`, 42,531,020 bytes, 912 restore objects, SHA-256 `e991ee901740933025bb0ef4ca9f78b30cf656818407dd809134de05aba07cc3`; restore-list SHA-256 `93918100a77fe8081f6a0933f82a73b2d309a2670b82694bdf87d5af98cc9753`.
- Direct backend health, direct frontend login, public health, and public login returned HTTP 200. The backend runs two workers, used 13 of 100 PostgreSQL connections after cutover, and had no new 5xx/traceback markers.

## Purchase request returned to pending approval (2026-08-14)

- At the operator's explicit request, production Purchase Request `PR-2026-000032` (row `#32`) was returned from `approved` to `pending_approval`. Its `approved_by` and `approved_at` fields were cleared.
- Preflight confirmed that no purchase order, purchase-order line, receipt, or stock movement existed for the request. Its sole line was preserved unchanged: item `#82 / 30/1 COMPACT SUPREM`, supplier `Dinar`, material name, photo, quantities, and unit all remain intact.
- The three unread automatic notifications claiming that this request was approved (`#669`-`#671`) were removed so users are not directed to convert a request that is pending approval. The original pending-approval notifications remain.
- Audit `#13072` records the reversal and validates in the recent audit-chain segment. The full historical chain still has the known pre-existing `prev_hash` mismatch at audit `#744`.
- Verified pre-change PostgreSQL backup: `/opt/milana-erp/shared/backups/pre_pr32_return_pending_20260814_154000.dump`, 42,530,124 bytes, 912 restore objects, SHA-256 `60a89b02b7a27a302cef2ec56279ba518c18c3fe8d51f9197bd9f75618f80bb6`; restore-list SHA-256 `4acee2ab3b155c19270c109f40b11e71d934962809a62d86cd7735bd5533fef6`.
- No deployment or schema change occurred. Production remains on release/image `20260814_044538` with Alembic `0096_batch_item_consistency`. Direct backend health, direct frontend login, public health, and public login returned HTTP 200; the backend had two workers, zero restarts, no OOM or recent error markers, and PostgreSQL used 21 of 100 connections.

## Production data purge: 39 workflows not handed to Sewing (2026-08-14)

- At the operator's explicit request, production workflows created before 2026-08-14 Tashkent time that still had no Cutting-to-Sewing handoff or production evidence were removed. The deleted public/UI numbers were `SO-2026-000015`, `SO-2026-000016`, `SO-2026-000022`, `SO-2026-000023`, `SO-2026-000031`, `SO-2026-000032`, `SO-2026-000045` through `SO-2026-000047`, `SO-2026-000050` through `SO-2026-000054`, `SO-2026-000064` through `SO-2026-000069`, `SO-2026-000075` through `SO-2026-000080`, `SO-2026-000085`, `SO-2026-000087` through `SO-2026-000089`, `SO-2026-000091`, `SO-2026-000093`, `SO-2026-000094`, `SO-2026-000096` through `SO-2026-000099`, `SO-2026-000104`, and `SO-2026-000105`. These were 39 standalone branded-stock `production_orders`, not customer `sales_orders`, totaling 24,600 planned pieces.
- A guarded, rollback-rehearsed serializable transaction deleted exactly 39 production orders, 157 zero-activity work orders, 231 untouched size rows, 33 production-material planning rows, and one material reservation. Thirty-seven Cutting work orders were waiting; two were marked in progress but still had zero counters and no Cutting record. There were no production batches, Cutting/Printing/Sewing records, bundles or scans, sewing assignments/reports/replacements, packages, payroll evidence, tasks, notifications, stock movements, idempotency responses, or denormalized order-number references for the deleted set.
- The deleted reservation was `MR-2026-000001` on `PO-2026-000031`: 229.99 kg reserved, 0 consumed, and 0 released. Its item `#81` and stock batch `#424` were preserved. All 39 models, 12 branded-planning parents, and 33 referenced fabric batches matched their complete pre-delete fingerprints after the transaction; no stock-batch quantity or inventory ledger row changed.
- `SO-2026-000106` was initially eligible but was automatically excluded when concurrent production activity appeared during preflight: it had 270 process QR labels and five payroll records representing 500 scanned pieces. Its production order, five work orders, payroll evidence, and printing attachment were locked, compared, and preserved. The post-purge eligibility query returned zero remaining untouched workflows.
- The one target-only printing image for `SO-2026-000105` was archived before deletion and removed from active storage after database reconciliation. Recovery archive: `/opt/milana-erp/shared/backups/unmoved_cutting_workflow_purge_20260814_150500/printing_attachment.tar.gz` (2,843 bytes; SHA-256 `aa6d3eac0847caa268f183c7fe778c82c038babeeddd85c047b6cced79468a16`). The protected `SO-2026-000106` image remains active.
- Audit records `#13023` through `#13061` record the 39 deletions and their hash-chain segment validates successfully. The full historical audit chain retains its existing `prev_hash` mismatch at record `#744`.
- Verified pre-change PostgreSQL backup: `/opt/milana-erp/shared/backups/pre_unmoved_cutting_workflow_purge_20260814_150500.dump`, 42,532,918 bytes, 912 restore objects, SHA-256 `59401f2716a33a1854232b1a4882abb5dc01e7e2fcc83fdcefa9c017e2dbcebd`; restore-list SHA-256 `3b5efa26ed6d0d773856cbb05810b335ebf963db93d06f34685d3ed078efa8cf`.
- No application deployment or schema change was performed. Backend and frontend remain on release/image `20260814_044538` with Alembic `0096_batch_item_consistency`. The backend has two workers, zero restarts, no OOM or recent error markers, PostgreSQL used 20 of 100 connections, and all four internal/public health and login checks returned HTTP 200.

## Fabric Storage delete and reservation consistency deployment (2026-08-14)

- Active production release: `20260814_044538` on backend and frontend. Immediate application rollback: `20260814_043852`; both are compatible with Alembic `0096_batch_item_consistency`.
- Root cause: the Fabric Storage delete button always appended `force=true`. The backend interpreted a forced delete of a linked/used batch as “set quantity to zero and hold” rather than a real delete. Separately, the authorized batch-material reassignment path moved stock movements but did not move batch-linked reservation/BOM/waste item references. Production reservation `MR-2026-000001` therefore remained on archived item `#48 / OCHIRV0R` after its batch `#424` moved to active item `#81 / 30/1 COMPACT PENYE SUPREM`, producing 0 − 229.99 kg available.
- Delete semantics are now strict: unused receipt-only batches are physically deleted with their receipt movements; any reserved, linked, adjusted, consumed, or otherwise used batch is rejected with HTTP 409 even if a caller supplies `force=true`. The frontend no longer sends forced deletes. Quantity-edit and authorized material-reassignment workflows remain available.
- Batch material reassignment now atomically relinks all batch-owned item references in stock movements, material reservations, model BOM rows, and waste rows, and records the relink counts in the existing StockBatch update audit.
- Migration `0096_batch_item_consistency` repaired exactly one proven mismatch: reservation `#1 / MR-2026-000001` changed only its `item_id` from archived item `#48` to the current item of batch `#424`, item `#81`. Its production order `PO-2026-000031`, status `reserved`, batch, quantity 229.99 kg, consumed/released amounts, and all stock quantities were preserved. Audit `#12932` records one corrected material-reservation row and zero BOM, movement, or waste corrections.
- Empty inactive materials are excluded from Fabric Storage rows and totals, while inactive materials that still have positive batch stock, active reservations, or batchless stock history remain visible. Signed-in production QA of `/inventory?group=materials&q=15319` now shows exactly one row and a total of one: 2,181.70 kg total, 229.99 kg reserved, 1,951.71 kg available. The archived OCHIRV0R row and negative availability are absent.
- Validation passed: 17 reservation/delete regression tests before the first deployment, four focused count/filter tests for the final release, Ruff on all changed backend files (ignoring only the active release's pre-existing F401 baseline), Alembic single-head and compile checks, frontend TypeScript/ESLint, two clean 65-route production builds, backend image builds, source-manifest checks, post-migration mismatch reconciliation, signed-in UI QA, runtime/log checks, and all four internal/public health/login checks. PostgreSQL used 18 of 100 connections after final cutover.
- Final backend image: `milana-backend:20260814_044538` (image ID `sha256:12122e86bb1142e473048309222fdd4f4342a991589175820a26b79929cce4ea`); frontend build ID: `TZVWZI-qjrwlXRkHFDoUD`. Release archive SHA-256: `cfb3ec9671940a320d82e5437c291503b5f7ef0e421d252b26650d71dfc0d8ef`; 536-file source-manifest SHA-256: `aed07df2dd3b7eb59281dbc5064ee0477c9479238c3a085ca4d3e3439a13fd6c`.
- Verified pre-migration backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260814_043852.dump`, 42,500,977 bytes, 912 restore objects, SHA-256 `14f8a6daffb2d1c2ee71870631444012d632a40e3db7ea26c105ee8b4b7aaaa0`; restore-list SHA-256 `7cd5220c9d67d742e98467f83e3a96974fe705419a0222c88791dea93e496f95`. Final pre-cutover backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260814_044538.dump`, 42,501,144 bytes, SHA-256 `8cff3fbb6b5610835b84c5f0fc166bca6c8c92117a0e840b6a72d92785ebe3f5`; restore-list SHA-256 `8c6696a105e4d167a328e2833bc8025cce50b3e6625412f860d23c7a8480c787`.
- Existing frontend dependency advisories remain at one moderate and six high; no dependency versions were changed in this scoped fix.


## Branded-order model metadata and picture deployment (2026-08-14)

- Active production release: `20260814_031756` on backend and frontend. Immediate rollback release: `20260813_131328`. Both use Alembic `0095_fix_bozorova_qr_payload`, so application rollback requires no database downgrade.
- Branded-stock order history no longer depends on the separate full approved-model catalog to display linked production models. Production currently has 6,597 approved models; when that large secondary request was unavailable or incomplete, history rows lost valid metadata and fell back to raw database IDs such as `#7146`, with empty model and fabric pictures.
- `/api/planning/branded-orders` now loads only the models referenced by the returned production groups and embeds each model's business code, name, model-picture URL, fabric label, and fabric-picture URL. The frontend prefers this self-contained history payload, keeps the model catalog only as a compatibility fallback, and never exposes a raw model ID when metadata is unavailable. Model selection and creation behavior are unchanged.
- Production data inspection confirmed the seven affected models still existed, were approved, and had 14 physical image files in shared storage. No data recovery or data correction was required. Signed-in read-only QA opened existing group `0023`: `PJ1032V-V-5755` and `PJ1032V-V-5756` displayed with their full names, both model thumbnails and both Brown/Black fabric thumbnails loaded successfully, no `#7146/#7147` fallback was visible, and the browser console had no errors.
- Regression tests covering a linked model excluded from the picker passed, along with the complete customer/payment-history module, targeted production/model-image tests, frontend lint, TypeScript, the production Next.js build, backend image build, source-manifest checks, Alembic head check, both runtime checks, all four internal/public health and login checks, and a signed authenticated API response check. PostgreSQL used 15 of 100 connections after cutover.
- Backend image: `milana-backend:20260814_031756` (image ID `sha256:3f567d4e947e528624be6640f49ed8b318b629cbfabd5d139d1f6788f3d0a319`); frontend build ID: `M1GIeKh5y2WrQwypqWRtT`. Release archive SHA-256: `b0e935c4c7b14eabc4e0c130b7e3692bbb69f08810ffe0a4e1de919ce1af1da6`; 535-file source-manifest SHA-256: `f09fc9501647b2eb94b47dd40612077befa5f7be5cadb781c5405eb75d153b47`.
- Fresh validated backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260814_031756.dump`, 42,497,255 bytes, 912 restore objects. Dump SHA-256 `269e4f03207eb5c4a2050dba4ffc9d8a4b221a74007b63c78d27660de69c3f98`; restore-list SHA-256 `d9288226ac3a13bebbe0194f5a724f034b58ab7602b5a8749991aa458a91325f`.
- No schema or business data changed. Postflight reconfirmed zero payroll labels and zero payroll records. The existing seven frontend dependency advisories (one moderate, six high) remain outside this scoped fix.

## Payroll-account test data cleanup (2026-08-13)

- At the user's explicit request, production data created by the dedicated active `Payroll` user/role during testing was isolated by actor columns and audit history, dependency-checked, backed up, and removed. Active application release remained `20260813_131328` on both VMs and Alembic remained `0095_fix_bozorova_qr_payload`; no code, migrations, configuration, or symlinks changed.
- The guarded transaction removed exactly 468 `payroll_qr_labels` issued by the Payroll account and 11 `payroll_records` scanned by it (record IDs 4-14: 10 recorded and one previously voided), representing 1,100 test pieces and 228,000 UZS across existing production orders `PO-2026-000003` and `PO-2026-000082`. Labels were deleted before records because 10 labels referenced those records. No payroll periods or adjustments existed, and the foreign-key/actor scan found no downstream or non-payroll data owned by the Payroll account.
- Existing production orders, employees, models, sewing/cutting/inventory data, the Bozorova name correction, QR payload correction, label layout/font changes, all other users' data, and immutable historical audit rows were preserved. One new system audit entry (`remove_test_data`, audit ID 12908) records the exact deleted fingerprint and validated backup; its entry hash verifies successfully.
- Post-cleanup state is 0 payroll labels, 0 payroll records, 0 payroll periods, and 0 payroll adjustments. Both application VMs still resolve `current` to release `20260813_131328`, and the four internal/public backend-health and frontend-login checks returned HTTP 200.
- Fresh validated pre-cleanup backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260813_132300.dump`, 42,511,799 bytes, 912 restore objects. Dump SHA-256 `7e262d86e7c5785794ce96f3b4748d7a0a979a15eb5dad62d691d2652de0b82a`; restore-list SHA-256 `abcef170e1963c412e7ecc39bce9b38f2231553d75d8729c82f5db652367c1d5`.

## Process-label sewing-line font deployment (2026-08-13)

- Active production release: `20260813_131328` on backend and frontend. Immediate rollback release: `20260813_130356`. Both use Alembic `0095_fix_bozorova_qr_payload`, so application rollback requires no database downgrade.
- Only the sewing-line value on issued 60 mm x 40 mm process labels now prints at 7 pt bold with 1.05 line height. This allows `SEW-01 - Bozorova Nargiza` to fit inside its existing two-line area. Every other label detail remains 8.4 pt bold; operation title/number, QR, Kroy footer, ordering, numbering, and QR data are unchanged. Clean UI and Uncodixfy constraints kept the change print-only and limited to that one value.
- Process QR ordering contract, strict TypeScript, targeted page lint, production Next.js build, backend image build, both VM release-manifest checks, Alembic head check, all four internal/public health and login checks, two-worker/runtime/log checks, deployed-source CSS check, and PostgreSQL headroom check passed. PostgreSQL used 15 of 100 connections after cutover. No business data changed.
- Backend image: `milana-backend:20260813_131328` (content-equivalent image ID `sha256:a81b008dafd587ba34161073315d0696e5fe1ffa0ab8c1f0ad6935e163948f15`); frontend build ID: `Wptom4bIenILNGs-DGwyc`. Release archive SHA-256: `0c2ce7d9ddebf9977065b946192ca0587e7b00837e7da217f9082fc3446bd38e`; 535-file source-manifest SHA-256: `c9f25f80bad1d1f4875dba5b83542e6175420ce50ec9e8948e89e28f55d789f8`.
- Fresh validated backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260813_131328.dump`, 42,511,799 bytes, 912 restore objects. Dump SHA-256 `22eddc7b8d67da857ca74cbb6a17b7b9a1bc573cd1f89e54b0cb6c00107a1d70`; restore-list SHA-256 `9429864b3d2fc77e3f6af647b732ed80d05896998100e1bc57274eefd0f3eb2a`.

## Bozorova Nargiza name and process-label print deployment (2026-08-13)

- Active production release: `20260813_130356` on backend and frontend. Immediate application rollback release: `20260813_125431`. Production is at Alembic `0095_fix_bozorova_qr_payload`; before starting the older backend image, use the new image to downgrade the version marker to `0094_fix_bozorova_name` (the `0095` downgrade intentionally preserves the corrected QR payload data).
- Corrected the canonical Milana sewing line `MIL / SEW-01` from `Bozorva Nargiza` to `Bozorova Nargiza` in seeds, maintenance scripts, migration compatibility data, tests, and production operational data. Historical audit records were not rewritten.
- Audited transactional migrations corrected 1 `sewing_flows` master row, 17 `sewing_daily_reports.line_name` snapshots, 468 `payroll_qr_labels.sewing_line_name` values, 468 uppercase names embedded in the same issued QR payloads, 11 `payroll_records.raw_work_json` snapshots, and 4 `idempotency_records.response_json` values. Post-deployment inspection found zero old-spelling occurrences in non-audit operational text/JSON fields; all 468 `SEW-01` QR-label line fields and payloads contain the corrected spelling. Audit actions `correct_name` and `correct_qr_payload_name` were appended.
- The 60 mm x 40 mm process-label layout keeps 8.4 pt bold details and now allocates 2.25x row height plus 6.6 mm of wrap space to the sewing-line value, allowing `SEW-01 - Bozorova Nargiza` to print fully on two lines. Existing QR size/inset, operation number, Kroy footer, label order, and operation numbering are unchanged. The Clean UI and Uncodixfy constraints kept this as a print-only spacing correction without adding UI chrome.
- Process QR ordering, numbering, TypeScript, lint (zero errors; three unrelated existing hook warnings), Python compilation, sewing-line regression tests, local and production frontend builds, backend image builds, both VM manifest checks, Alembic head checks, all four internal/public health and login checks, two-worker runtime checks, log checks, and PostgreSQL headroom checks passed. PostgreSQL used 13 of 100 connections after final cutover.
- Active backend image: `milana-backend:20260813_130356` (image ID `sha256:a81b008dafd587ba34161073315d0696e5fe1ffa0ab8c1f0ad6935e163948f15`); frontend build ID: `5MSA3aH9BVC3Y1qbZMGwi`. Final archive SHA-256: `a23329a4f9cb40b7fc179266b1b287e69df1b683c85e58a4a2163960c599cdc3`; 535-file source-manifest SHA-256: `43484b2970d10b2bd205f889cee1b9819165f218a3dbde303f3732b87cfef40c`.
- Final fresh validated backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260813_130356.dump`, 42,511,761 bytes, 912 restore objects. Dump SHA-256 `a991055f1b5e6dd91d7dd1da899fbc092bbec210ddeaba182dfb221b71f8fd28`; restore-list SHA-256 `3d0dd2d0b624769b8e32160a69db936f290b670800825494a8240be165f9016a`.
- The first build attempt stopped before migration/cutover because the frontend VM had no free disk space. Only reproducible `frontend/node_modules` and `frontend/.next` directories from inactive releases were removed (164 directories); the active release, immediate rollback release, candidate source, shared configuration, storage, and business data were protected. Free space increased to 47 GB. The remaining seven known npm advisories (one moderate, six high) were not changed in this scoped release.

## Process QR full-height label text deployment (2026-08-13)

- Active production release: `20260813_124322` on backend and frontend. Immediate rollback release: `20260813_123906`; both use Alembic `0093_payroll_reversal`, so rollback requires no database downgrade.
- The unused vertical gap under process-label details is removed. The six detail rows now form a full-height CSS grid across the entire available body beside the 21 mm QR, with the sewing-line row receiving 1.7x height for two-line names and the other five rows sharing the remaining height.
- Main detail text increased from 7.2 pt to 8.4 pt bold. The previous fixed 2.8 mm row height was removed. The existing 60x40 mm page, top-right operation number, top-aligned QR, bottom-left Kroy number, bottom-right QR token, print-safe inset, QR size, label ordering, and model operation numbering remain unchanged.
- The Process QR ordering and manual-order contracts, strict TypeScript, targeted lint with zero warnings/errors, local and two production Next.js builds, VM release-manifest checks, migration-head checks, and all four internal/public health and login checks passed.
- Signed-in read-only production QA selected existing order `SO-2026-000003`. The first label retained `Chontak overlo`, `№ 1`, six detail rows, `Kroy no -`, and `QR 200000241`; deployed CSS confirms 100% detail height, 8.4 pt text, the `1fr 1fr 1.7fr 1fr 1fr 1fr` row grid, and removal of the old fixed row height. No labels or business data were created or changed.
- Backend image: `milana-backend:20260813_124322` (content SHA `28d133acf3c2c00ebcb222b0cda460fb4599fc6a2b71c132305b6e4ac82c298a`); frontend build ID: `WBSm050urfNieUYxkulH6`. Release archive SHA-256: `d7a289fe5e65d66270a5bc20c6ce39a570b1dd39fd2191a45a4f953adff6fc09`; 533-file source-manifest SHA-256: `77fae21e2088d053be30087b1b68205ef19ee2f0608c507de8ec8a0b667283f2`.
- Fresh validated backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260813_124322.dump`, 42,511,031 bytes, 912 restore objects. Dump SHA-256 `7aae48c6e6bbf5e8247869b07042cb2db60d422bdf5a05a4739524077e291601`; restore-list SHA-256 `c59daad8519c637b9423039ccfae573cc810319eeb553644a3769242acfd1726`.
- No schema or business data changed during deployment or QA. The backend runs two Uvicorn workers, PostgreSQL used 15 of 100 connections during postflight, and the frontend dependency install continues to report seven known npm advisories (one moderate, six high); no unreviewed dependency upgrade was included.

## Process QR label layout deployment (2026-08-13)

- Active production release: `20260813_123145` on backend and frontend. Immediate rollback release: `20260813_122510`; both use Alembic `0093_payroll_reversal`, so rollback requires no database downgrade.
- Issued 60 mm x 40 mm process labels now place the model-operation number in the top-right header. The QR is top-aligned on the right, and the six main detail rows (model, batch, sewing line, size, quantity, and rate) use larger 7.2 pt bold print text with 2.8 mm row height.
- `Kroy no` was removed from the detail list and moved to the bottom-left footer; the exact QR number remains at the bottom-right. The operation title stays at the top-left and the label page size, QR size, print-safe inset, model operation numbering, garment-size order, and operation order are unchanged.
- The Process QR ordering and manual-order contracts, i18n validation (2,569 keys per language), strict TypeScript, targeted lint with zero warnings/errors, local and production Next.js builds, both VM release-manifest checks, migration-head check, and all four internal/public health and login checks passed.
- Signed-in read-only production QA selected existing order `SO-2026-000003` and inspected its 234 existing labels. The first label showed `Chontak overlo` with `№ 1` in the header, six detail labels without Kroy, and footer `Kroy no -` plus `QR 200000241`. Deployed print CSS retained 60x40 mm, 7.2 pt detail text, 8 pt operation number, and top-aligned QR. QA did not issue, print, edit, or delete labels or other business data.
- Backend image: `milana-backend:20260813_123145` (content SHA `28d133acf3c2c00ebcb222b0cda460fb4599fc6a2b71c132305b6e4ac82c298a`); frontend build ID: `-xySautEbDxYXv-owUBfq`. Release archive SHA-256: `39e7a19f87ad99d9c42c2cd6c264ca1c75a4ffbf5771149e69bed24b8b5dd722`; 533-file source-manifest SHA-256: `86625eeaae8f0ccab0bb982662e5d84941506359cb125b895fe07cbddf7c18ac`.
- Fresh validated backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260813_123145.dump`, 42,510,560 bytes, 912 restore objects. Dump SHA-256 `16c46b231603c5ba6307c8756b44c1ffe8ffeb2446155e6917757d7d4be228a3`; restore-list SHA-256 `7c2d10bca0b6f22972cb2e175152e314ae40492c29e0594ea8d40577bc08bfb2`.
- No schema or business data changed during deployment or QA. The backend runs two Uvicorn workers, PostgreSQL used 13 of 100 connections during postflight, and the frontend dependency install continues to report seven known npm advisories (one moderate, six high); no unreviewed dependency upgrade was included.

## Sewing report rate-total deployment (2026-08-13)

- Active production release: `20260813_122510` on backend and frontend. Immediate rollback release: `20260813_121704`; both use Alembic `0093_payroll_reversal`, so rollback requires no database downgrade.
- The printed sewing production report's final totals block now also shows the sum of every `Average rate / O‘rtacha narx` row across the complete filtered report. It appears as the fourth compact total alongside scanned QR count, completed pieces, and total payroll amount, with English, Russian, and Uzbek labels.
- The rate-total contract, i18n validation (2,569 keys per language), strict TypeScript, targeted lint with zero warnings/errors, local and production Next.js builds, both VM release-manifest checks, migration-head check, and all four internal/public health and login checks passed.
- Signed-in read-only production QA confirmed 10 displayed rate values (`250`, `250`, `70`, `260`, `120`, `150`, `260`, `260`, `210`, and `200` UZS) produce the displayed `O‘rtacha narxlar jami` of `2,030 UZS`. The remaining totals stayed 10 QR codes, 1,000 completed pieces, and 203,000 UZS. QA did not invoke printing or change business data.
- Backend image: `milana-backend:20260813_122510` (content SHA `28d133acf3c2c00ebcb222b0cda460fb4599fc6a2b71c132305b6e4ac82c298a`); frontend build ID: `vPrbwuBw2ix22MkMQ365H`. Release archive SHA-256: `6c59aa538f958f5807cae8fc8ad34095860843e1845d492e6969cf94cee2d260`; 533-file source-manifest SHA-256: `6eaf7eeb6e5e713ceb6e5bdc0264d6dedef5a47bb3029b9eef3dde71a029e042`.
- Fresh validated backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260813_122510.dump`, 42,510,558 bytes, 912 restore objects. Dump SHA-256 `323ac8f6553a3c1a9691bc786d4841dfdc1a1d94c2ef16724e307b5313b86887`; restore-list SHA-256 `7f76650acb7b108aae61d241063abfe1e504aef9b1f03ad5f9ac4fecb29f8d4d`.
- No schema or business data changed during deployment or QA. The backend runs two Uvicorn workers, PostgreSQL used 14 of 100 connections during postflight, and the frontend dependency install continues to report seven known npm advisories (one moderate, six high); no unreviewed dependency upgrade was included.

## Sewing production report print deployment (2026-08-13)

- Active production release: `20260813_121704` on backend and frontend. Immediate rollback release: `20260813_114054`; both use Alembic `0093_payroll_reversal`, so rollback requires no database downgrade.
- The on-screen sewing production report keeps its full 12-column operational detail. Printing now uses a dedicated compact 9-column table containing row number, date, employee, QR/barcode, model and size, operation, completed quantity, rate, and amount. Repeated sewing-line, cutting/order, product, employee-number, and internal operation-code details are omitted from print only.
- Printed report text is 9.5 px, bold, black, and uses darker cell borders. A final non-breaking totals block reports the number of scanned QR records, total completed pieces, and total payroll amount. All new labels are translated in English, Russian, and Uzbek.
- The print contract, i18n validation (2,568 keys per language), strict TypeScript, targeted lint with zero warnings/errors, local and production Next.js builds, both VM release-manifest checks, migration-head check, and all four internal/public health and login checks passed.
- Signed-in read-only production QA confirmed the compact print table has exactly nine columns and, for the current active filters, 10 rows with the first row combining model `ХJ3062-5593` and size `S-44`. The final totals show 10 scanned QR codes, 1,000 completed pieces, and 203,000 UZS. QA did not invoke the print dialog or create, edit, or delete business data.
- Backend image: `milana-backend:20260813_121704` (content SHA `28d133acf3c2c00ebcb222b0cda460fb4599fc6a2b71c132305b6e4ac82c298a`); frontend build ID: `jaZhxnXyl3sjjrXd7dzbT`. Release archive SHA-256: `500e5682bf627b22a8ab480b541f3bfc1f2e01cd9651b25f6367180bd486e58c`; 533-file source-manifest SHA-256: `db63386052a88f079db662bfbffbb35ce3131903107b13437ffb925540850145`.
- Fresh validated backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260813_121704.dump`, 42,508,720 bytes, 912 restore objects. Dump SHA-256 `950f989cda899b2306817ffa0d63135fcb8c17d4215a99abd917eda1ffed401b`; restore-list SHA-256 `f12fb6ee838edfc92edf96f94314d2649b2d8ffe3284f18886c8f06eae94924b`.
- No schema or business data changed during deployment or QA. The backend runs two Uvicorn workers, PostgreSQL used 14 of 100 connections during postflight, and the frontend dependency install continues to report seven known npm advisories (one moderate, six high); no unreviewed dependency upgrade was included.

## Process QR manual-order deployment (2026-08-13)

- Active production release: `20260813_114054` on backend and frontend. Immediate rollback release: `20260813_111340`; both use Alembic `0093_payroll_reversal`, so rollback requires no database downgrade.
- Process QR now has separate `ERP order` and `Manual order` source modes. Manual mode searches model variants through the paginated model API, uses the selected variant's configured sizes, and automatically loads its saved paid operations and rates.
- The operator enters the Kroy number and then uses the existing sewing-line, factory, per-size quantity, operation selection, label issuance, size grouping, printing, Payroll Scan, QR Control, return, and reporting flows. When the selected model's paid operations belong to exactly one factory, that factory is selected automatically.
- Manual QR labels do not invent production-order, sales-order, work-order, or production-batch foreign keys. Their stable `MAN-<model id>-<Kroy token>` reference and deterministic label UIDs allow the same model/Kroy job to reload existing labels and preserve idempotent issuance. A model without configured sizes is blocked from label issuance.
- The manual-order contract, existing Process QR ordering contract, strict TypeScript, i18n validation (2,565 keys per language), lint (zero errors and three unrelated existing hook warnings), local and production Next.js builds, 27 payroll backend tests, both VM builds, migration check, and all four internal/public health and login checks passed.
- Signed-in read-only production QA searched for existing variant `V-5756`, selected `PJ1032V-V-5756`, and confirmed six configured sizes (`50` through `60`) plus its saved paid operations loaded. The Kroy field remained empty, label issuance stayed disabled, and QA created, edited, or deleted no QR, payroll, model, or other business data.
- Backend image: `milana-backend:20260813_114054` (content SHA `28d133acf3c2c00ebcb222b0cda460fb4599fc6a2b71c132305b6e4ac82c298a`); frontend build ID: `FVvVIHHqh9r9Qymmrwakx`. Release archive SHA-256: `aac054aeeb4b4af72b9d60a98f6bf64f62272a814e93ef30d5fe1eebe5ad1e4c`; 532-file source-manifest SHA-256: `534f6bb19736f326ca9b1af00e60900d1b3bf702ac94366a45d00c94eb589930`.
- Fresh validated backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260813_114054.dump`, 42,507,959 bytes, 912 restore objects. Dump SHA-256 `8957c023148e52678e63ef92d125306cdb0a954d1cacdec38c2620b49f26c126`; restore-list SHA-256 `303a9cd89cab38f57ba232e6bb98cb914f15d5493f63f53f5edb00c11adef384`.
- No schema or business data changed during deployment or QA. The backend runs two Uvicorn workers, PostgreSQL used 14 of 100 connections during postflight, and the frontend dependency install continues to report seven known npm advisories (one moderate, six high); no unreviewed dependency upgrade was included.

## Payroll Scan automatic-save deployment (2026-08-13)

- Active production release: `20260813_111340` on backend and frontend. Immediate rollback release: `20260813_110036`; both use Alembic `0093_payroll_reversal`, so rollback requires no database downgrade.
- After a valid employee and work QR pair is scanned, Payroll Scan now posts the new payroll row to the server immediately. The manual `Save to Payroll` and `Save All` controls were removed; a row-level Retry action appears only when automatic persistence fails.
- Saved or currently-saving rows are locked against local quantity/rate editing and per-row local undo/removal. Restored browser-session rows that were still pending are submitted automatically after permissions and session state load. Existing backend duplicate protection remains authoritative.
- The automatic-save contract, strict TypeScript, i18n validation (2,552 keys per language), lint (zero errors and three unrelated existing hook warnings), local and production Next.js builds, 27 payroll backend tests, both VM builds, migration check, and all four internal/public health and login checks passed.
- Signed-in read-only production QA confirmed that Payroll Scan loaded without console errors, the manual save controls were absent, 10 existing session records remained saved, and no Retry action was shown because no save had failed. QA did not scan a QR or create, edit, or delete payroll or other business data.
- Backend image: `milana-backend:20260813_111340` (content SHA `28d133acf3c2c00ebcb222b0cda460fb4599fc6a2b71c132305b6e4ac82c298a`); frontend build ID: `2UqW7GSXfIfp0LshKePmc`. Release archive SHA-256: `5e752a25e0f6faef2655cb128d69dcfda0ad73472e2d2f8cf31b7690d9062525`; 531-file source-manifest SHA-256: `2421d3c07f5d6779658dc5ebc465b714f614892bd572052a892e082826a54477`.
- Fresh validated backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260813_111340.dump`, 42,504,755 bytes, 912 restore objects. Dump SHA-256 `fa881d7f0ed31f37a4a8b8668c07868c7a3c2aa48d8ff8ca71e83e859243bcb6`; restore-list SHA-256 `9e03f637241d3aab24a6879a34abad563ba4fbcd33fc63d6b2fa71bf8aed5782`.
- No schema or business data changed during deployment or QA. The backend runs two Uvicorn workers, PostgreSQL used 14 of 100 connections during postflight, and the frontend dependency install continues to report seven known npm advisories (one moderate, six high); no unreviewed dependency upgrade was included.

## Process QR shared operation-number deployment (2026-08-13)

- Active production release: `20260813_110036` on backend and frontend. Immediate rollback release: `20260813_104920`; both use Alembic `0093_payroll_reversal`, so rollback requires no database downgrade.
- The printed `№` is now the one-based paid-operation sequence saved on the selected model instead of the global `payroll_qr_labels.id`. The first model operation prints `№ 1`, and that same operation keeps `№ 1` for every garment size. The unique nine-digit QR token remains unchanged and visible for scanning.
- Signed-in read-only production QA used existing order `#86`: `Chontak overlo` showed `№ 1` on `S-44`, `M-46`, and `L-48`, while the distinct QR tokens remained `200000007`, `200000006`, and `200000005`. No print dialog was opened and no QR, payroll, model, or other business data changed.
- The ordering/numbering regression contract, strict TypeScript, lint (zero errors and three unrelated existing hook warnings), local Next.js production build, both VM builds, migration check, and all four internal/public health and login checks passed.
- Backend image: `milana-backend:20260813_110036` (content SHA `28d133acf3c2c00ebcb222b0cda460fb4599fc6a2b71c132305b6e4ac82c298a`); frontend build ID: `I7nAFD3J5cuL1i0w_U8tW`. Release archive SHA-256: `f13fa7828047cf9c8c94bba133775dcebd78d3398b85bee7c5a3846da2543486`; 530-file source-manifest SHA-256: `2c646f2cd488c822deb60a3474edf43db862dc2caf971f320dc5b7c4fbadb05d`.
- Fresh validated backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260813_110036.dump`, 42,504,753 bytes, 912 restore objects. Dump SHA-256 `8ca14849cb3c535330af05ae77580971963991bbd11df824eff9b4a9816d92b6`; restore-list SHA-256 `9b185b54b7a36707986b047be70ad10c7bce1dffec93aba025971e96f9645495`.
- No schema or business data changed. The backend runs two Uvicorn workers, and PostgreSQL used 14 of 100 connections during postflight.

## Process QR size and model-operation ordering deployment (2026-08-13)

- Active production release: `20260813_104920` on backend and frontend. Immediate rollback release: `20260813_103619`; both use Alembic `0093_payroll_reversal`, so rollback requires no database downgrade.
- Process QR preview, issued-label groups, per-size printing, and print-all now use explicit smallest-to-largest garment-size order. Labels inside every size follow the paid-operation array order saved on the selected model, then copy number and stable label ID; API newest-first order no longer reverses or mixes printed operations.
- Signed-in read-only production QA used existing order `#86`. The six groups rendered exactly `S-44`, `M-46`, `L-48`, `XL-50`, `2XL-52`, `3XL-54`; the first 12 S-44 operations exactly matched the first 12 operations displayed from the model. No print dialog was opened and no QR, payroll, model, or other business data changed.
- The ordering regression contract, i18n validation (2,550 keys per language), strict TypeScript, lint (zero errors and three unrelated existing hook warnings), local Next.js production build, both VM builds, and all four internal/public health and login checks passed.
- Backend image: `milana-backend:20260813_104920` (content SHA `28d133acf3c2c00ebcb222b0cda460fb4599fc6a2b71c132305b6e4ac82c298a`); frontend build ID: `laktsqlIBl9KOE6HXiXEU`. Release archive SHA-256: `def571f8eefd0fb229e07f1beac78152e75295b58c67870ef63b87ea78d90942`; 530-file source-manifest SHA-256: `f08bc1d1488ef3f798570b45bef6f9db0cd82daf2364044059d1f05de30d8dc7`.
- Fresh validated backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260813_104920.dump`, 42,504,760 bytes, 912 restore objects. Dump SHA-256 `a9615de293f53482f7b8be8696f461b1064cf5d51d2fa8a94cbbc37a867b913c`; restore-list SHA-256 `17bcf6853e6baaee3b632d5c3345d097191a8a9d12918c6359ea24bdf69042fe`.
- No schema or business data changed. The backend runs two Uvicorn workers, and PostgreSQL used 14 of 100 connections during postflight.

## Process QR print separator and QR inset deployment (2026-08-13)

- Active production release: `20260813_103619` on backend and frontend. Immediate rollback release: `20260813_101254`; both use Alembic `0093_payroll_reversal`, so rollback requires no database downgrade.
- The uneven line visible across the thermal label was the print footer's top border. That separator is now disabled in print CSS. The label remains exactly 60 mm x 40 mm.
- The work-label QR was reduced from 22 mm to 21 mm and the right print-safe padding increased from 1.5 mm to 3 mm, moving the QR away from the cut edge while retaining scan size. Stable label number and exact QR number remain printed below it.
- Frontend strict TypeScript, the print-layout contract, local Next.js production build, both VM builds, and all four internal/public health and login checks passed. Signed-in read-only production QA used existing order `#86`, confirmed size-grouped issued labels and visible label/QR numbers, and verified the deployed print rules without opening the print dialog or changing data.
- Backend image: `milana-backend:20260813_103619` (content SHA `28d133acf3c2c00ebcb222b0cda460fb4599fc6a2b71c132305b6e4ac82c298a`); frontend build ID: `73Fi2xTd8OVYCV5-20nc8`. Release archive SHA-256: `d7ccb5fb10078fd1035facf9e595474bc59d37edc8d71ddf0ddc0418146d9881`; 529-file source-manifest SHA-256: `eaca1d623f151555abeb8328e51fc499241f77c303c228f075dc344c399bdbbc`.
- Fresh validated backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260813_103619.dump`, 42,504,758 bytes, 912 restore objects. Dump SHA-256 `b58595de2130a2077dfc852d311fa949592f0aa99b11cdff8dacf29ecbae8154`; restore-list SHA-256 `4ba4858f7a4b4922be4349a2d1c826993326cff2a45959cacb57402787314bd6`.
- No schema or business data changed. The backend runs two Uvicorn workers, and PostgreSQL used 18 of 100 connections during postflight.

## Process QR 60x40 label readability deployment (2026-08-13)

- Active production release: `20260813_101254` on backend and frontend. Immediate rollback release: `20260813_095401`; both use Alembic `0093_payroll_reversal`, so the immediate application rollback requires no database downgrade.
- Process payroll labels remain fixed at exactly 60 mm x 40 mm with zero page margin. Printed work-label titles use 8.2 pt bold text, details use 6.4 pt bold text, long operation titles may occupy two lines, and long sewing-line values may occupy two lines without leaving the label boundary.
- The factory row was removed from work-label preview/print content. Every issued label now prints its stable database label number (`№ <id>`) and the exact nine-digit QR token (`QR <token>`) in a bold footer.
- Signed-in production QA used existing production order `#86` without mutations. A rendered label showed seven intended detail rows, no factory row, stable label `№ 231`, QR token `200000231`, the 60x40 page declaration, the fixed 60x40 label box, and zero browser-console errors. All 234 existing labels remained unchanged and distinct.
- Frontend lint passed with zero errors and three unrelated existing hook warnings; i18n validation passed for 2,550 keys per language; normal/strict TypeScript, the print contract, local and production Next.js builds, both VM builds, and all four health/login checks passed.
- Backend image: `milana-backend:20260813_101254` (content SHA `28d133acf3c2c00ebcb222b0cda460fb4599fc6a2b71c132305b6e4ac82c298a`); frontend build ID: `N54QOvyHfYr9ityJLJgMI`. Release archive SHA-256: `689d8762573c0fcd32246c9c01b6d92bba22ca1da7b8638719fb57d08a1cfe0a`; 529-file source-manifest SHA-256: `b5f231008e2fb8d7e244399d99ac79a1270b25f4dc14ccddfa4d5575cdff3de6`.
- Fresh validated backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260813_101254.dump`, 42,503,464 bytes, 912 restore objects. Dump SHA-256 `9c56c4d3fa312d7fc8ad9ee01f45da6e57db31e105929f91b9a9c34b694d9938`; restore-list SHA-256 `a1ab08e15cdc5dc4b947d1f0f575d6159f45395c058d962e5fc46e5e60217385`.
- No schema or business data changed. PostgreSQL used 15 of 100 connections, two Uvicorn workers were active, and recent backend/frontend logs contained no new application error.

## Process QR idempotent issuance and size printing deployment (2026-08-13)

- Active production release: `20260813_095401` on backend and frontend. Immediate rollback release: `20260813_075850`; both use Alembic `0093_payroll_reversal`, so this immediate application rollback does not require a database downgrade.
- Backend image: `milana-backend:20260813_095401`, image SHA `28d133acf3c2c00ebcb222b0cda460fb4599fc6a2b71c132305b6e4ac82c298a`, published as `8000:10000`. Frontend build ID: `Llscrpt0CaTBZ24JyF8tg`.
- Process QR issuance is now idempotent in the UI and API. The frontend submits only not-yet-issued deterministic label IDs; the backend returns existing labels without changing their original payload, operation, quantity, rate, issuance timestamp, or audit history. Repeated issue requests report created/existing counts and create no duplicate issue audit when nothing changed.
- Once labels are issued, they leave the ready-to-issue preview and appear in a persistent Issued labels section grouped by size. Users can print all issued labels or one exact size. QR images are fully generated before the browser print dialog opens, and the print-only DOM contains only the selected issued rows.
- Production inspection before and after cutover found 234 payroll QR labels for production order `#86`, all with distinct label UIDs and zero duplicate semantic groups. Signed-in QA showed six size groups (`S-44`, `M-46`, `L-48`, `XL-50`, `2XL-52`, `3XL-54`) with exactly 39 labels and an enabled per-size print button in each group; both issue buttons were disabled because all configured labels were already issued. No business data was created, deleted, or changed by deployment/QA.
- Validation: 27 payroll backend tests passed including double-issue immutability; frontend lint had zero errors and only three unrelated existing hook warnings; 2,550 i18n keys per language, normal and strict TypeScript, local Next.js production build, both VM builds, and signed-in production UI QA passed. The browser console had zero errors.
- Release archive SHA-256: `389e7ca258cd59fef06a7da2f4d62df64824f1d87b0eb2f4b6d00afdde611027`; 529-file source-manifest SHA-256: `941fc2ddc9902c05b5299aff1930a88f1d48409cf6bceeb6e49aaa91fcc4e224`.
- Fresh validated backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260813_095401.dump`, 42,497,126 bytes, 912 restore objects. Dump SHA-256 `ec5c767edfcb98fa2240fbe27041334a8d25b60c84a9a7851056bc5f3eb914c0`; restore-list SHA-256 `90fd02d0db542a329cb4d7131c8c5879e6ede8b85e46f246f5bed1eb150d102e`.
- All four required internal/public health and login checks returned HTTP 200. One Uvicorn parent with two workers is active, PostgreSQL used 15 of 100 connections, and recent backend/frontend logs and the signed-in browser contained no new application errors.

## Production Data Purge: 13 Screenshot Workflows (2026-08-13)

- At the operator's explicit request, the standalone branded-stock workflows
  shown in the supplied screenshots were completely removed from production:
  `PO-2026-000005`, `PO-2026-000008`, `PO-2026-000014`,
  `PO-2026-000086`, `PO-2026-000092`, and `PO-2026-000107` through
  `PO-2026-000114`. Their Cutting cards displayed the corresponding `SO-...`
  public numbers; none was a customer `sales_orders` row.
- A guarded transaction deleted exactly 13 production orders, 57 work orders,
  78 untouched size rows, and two production-material planning rows. All work
  counters and completed size quantities were zero. There were no Cutting or
  downstream records, batches, bundles, reservations, packages, stock
  movements, tasks, notifications, or denormalized order references.
- The 13 models, six branded-planning parent orders, and 12 referenced fabric
  batches were retained and compared unchanged inside the transaction. No
  inventory quantity or ledger record changed.
- Five exclusively referenced printing-instruction images were archived before
  deletion and removed from active storage afterward. The recovery archive is
  `/opt/milana-erp/shared/backups/screenshot_workflow_purge_20260813_090104/printing_attachments.tar.gz`
  (46,186 bytes; SHA-256
  `d7bf91e2026b99213478ea010c74b31ff30f576799fec3357c5093eebf6251d3`).
- Audit records `#12835` through `#12847` record the deletions; their 13-row
  hash-chain segment validates successfully. The full historical chain still
  has the pre-existing `prev_hash` mismatch at record `#744`.
- The verified pre-change PostgreSQL backup is
  `/opt/milana-erp/shared/backups/pre_screenshot_workflow_purge_20260813_090104.dump`
  (42,490,121 bytes; 912 restore objects; mode `0600`; SHA-256
  `d90f867e343ce09323ad6f69a0c8a3c5d5627e2494ca52d05a93ebb5e6b36301`).
  Its restore-list SHA-256 is
  `488483677f8545212952a6a65460f86004c4e828275a0e0cadc4a618612fb517`.
- Post-change checks found zero remaining target or linked rows, confirmed all
  preserved parent counts and fabric quantities, and returned HTTP 200 for all
  four internal/public health and login checks. Recent backend/frontend logs
  contained no new 5xx, traceback, exception, or application error. No
  deployment was performed; backend and frontend remain on release/image
  `20260813_075850` with Alembic `0093_payroll_reversal`.

## Payroll status/reversal fix and Piecework removal deployment (2026-08-13)

- Active production release: `20260813_075850` on backend and frontend. Immediate rollback release: `20260813_065330`.
- Because the previous backend image does not contain revision `0093`, rollback must first use the `20260813_075850` image to run `alembic downgrade 0092_sewing_role_access`, then repoint both symlinks and restart the previous image/service. The validated downgrade recreates empty Piecework tables and removes the reversal-link column; database rollback is not automatic.
- Backend image: `milana-backend:20260813_075850`, image SHA `7cf3c6f4feea1db8e7b7d3ce0ffd1ff1a1c38f9c9af9b97de5249e2264cba0c1`, published as `8000:10000`. Frontend build ID: `aGM_8coipzlObSHejD9GC`.
- Release archive SHA-256: `ca6a19a7933e671c5780110b655fb0af6f52ed79c3077f49dbab0e77eefa2fd8`; 529-file source-manifest SHA-256: `1b20d8102697457d0dca6aca9cf1e7c3d7ba603a65277becfa6a66764f19fa58`.
- Fresh validated backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260813_075850.dump`, 42,513,263 bytes, 964 restore objects, mode `0600`. Dump SHA-256 `987ab8103a558ad2cb4f99853c0d0cd374b31262fa2269e7acf043d75b2944d4`; restore-list SHA-256 `60610852d924c497a811ac0f0d3b62b0c9d84e3f385b15ae983fa54c3adc4742`.
- Payroll now translates the `recorded` ledger status in English, Russian, and Uzbek instead of rendering `statusValue.recorded`.
- The Payroll Records UI shows `Void` only while a record is editable. Records in locked, approved, or paid periods use `Reverse as adjustment`, which requires a reason and posts one linked deduction into a different draft/open payroll period.
- The backend preserves the finalized source record, links the deduction through `payroll_adjustments.source_payroll_record_id`, blocks duplicate reversals, and writes the dedicated `create_reversal_adjustment` audit event.
- The abandoned Piecework workspace was removed from the frontend route/navigation/authorization map and from the backend router/models/schemas/tests. Migration `0093_payroll_reversal` used exclusive table locks and a data guard before dropping `piecework_acceptances`, `piecework_assignments`, and `piecework_shifts`; it removed exactly six unused shift rows and no assignments, acceptances, payroll records, adjustments, or earnings.
- Validation: 29 focused payroll/factory tests passed, Python compilation passed, Alembic is at the single head `0093_payroll_reversal`, i18n validation passed for 2,536 keys per language, TypeScript passed, and both local and production Next.js builds passed without a `/payroll/piecework` route.
- All four internal/public health and login checks returned HTTP 200. One Uvicorn parent with two workers is active, PostgreSQL used 15 of 100 connections, and recent backend/frontend logs contained no new 5xx, traceback, exception, or application error.
- Signed-in read-only production QA confirmed Payroll Summary loads, no raw `statusValue.*` keys or console warnings/errors are visible, Piecework is absent from Payroll navigation, and `/payroll/piecework` returns 404. OpenAPI contains the reversal endpoint and no Piecework endpoints; the three Piecework tables are absent and the reversal source-link column is present.
- No payroll records or adjustments existed during migration or postflight. Outside the intentionally removed six empty Piecework shifts/tables, no business data was created or changed.

## Payroll factory-cascade deployment and isolated production test (2026-08-13)

- Active production release: `20260813_065330` on backend and frontend. Immediate rollback release: `20260813_111424`.
- Backend image: `milana-backend:20260813_065330`, SHA `d661f54caa24922475b0082db1df2eecd5b7551f2490673e642086e37c023d8b`, published as `8000:10000`. Frontend build ID: `kkf9zTD6PUiTz9N3Ua8PH`.
- Sewing Production Report reference options now cascade immediately by selected factory. Employee, production/sales order, cutting/batch, model, sewing-line, operation, and size lists are factory scoped; incompatible selected values are cleared when the factory changes.
- Source archive SHA-256: `ce50e64edf0e70ce1e53a193e25571acf61e2c22ee585753a715ae0f4fb8bedb`; 535-file source-manifest SHA-256: `0504eaf7095c42e98423f5193b8a20b16717cc68585f596c2119699e8d7fefa8`.
- Fresh validated backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260813_065330.dump`, 42,512,001 bytes, 964 restore objects, mode `0600`. Dump SHA-256 `8953daeecd79221f3ff4d0f6022678e2153f82ed8a74558189848d3f19b6bc33`; restore-list SHA-256 `a310b291ec8aa2e8368a824f7c694a22fe181806c38bb5412f34c70b2d766442`.
- Alembic remained at `0092_sewing_role_access (head)`. The focused payroll suite passed 25 tests, the broader payroll/piecework/factory suite passed 35 tests, and the production Next.js build passed.
- Signed-in production QA used fixture prefix `PAYQA-20260813-065330` and exercised Process QR configuration, QR Control, employee/work scanning, persistence, piecework assignment/acceptance, bonus adjustment, summary, sewing report, exact-order QR report, QR return, salary removal, rescan, active-duplicate rejection, and the open -> locked -> approved -> paid period lifecycle.
- Tested salary arithmetic: QR scan `10 * 250 = 2,500 UZS`; accepted piecework `4 * 250 = 1,000 UZS`; bonus `500 UZS`; net `4,000 UZS`. Returning the QR reduced net to `1,500 UZS`; rescanning restored exactly `4,000 UZS`. The database retained one voided historical scan and one active replacement, so no duplicate salary was created.
- Milana option assertions included the Milana fixture and excluded the Eco fixture for employees, lines, operations, models, orders, and sizes; the inverse assertions passed for Eco Cotton. Signed-in UI evidence also showed the Milana line dropdown without Eco lines.
- All temporary employees, lines, models, production prerequisites, bundles, payroll rows, QR labels, adjustments, piecework rows, and the period were deleted. Every tracked business-table count exactly matched its pre-test baseline afterward. Audit entries were intentionally retained as immutable test evidence. No inventory, stock, package, shipment, sales-order, or finance data was created or changed.
- All four internal/public health and login checks returned HTTP 200 after cleanup. Screenshot evidence and the full test narrative are under `outputs/payroll-e2e-20260813_065330/`.
- Newly confirmed payroll follow-ups: Process QR obtains sewing lines from the selected login factory instead of the selected order's routed factory; Piecework employee selection and assignment do not enforce the sewing flow's factory; untranslated `statusValue.*` keys appear in payroll UI; paid/locked records still render unusable Void buttons. These are separate from the deployed report-filter fix and remain unresolved.

## Searchable sewing report and payroll audit deployment (2026-08-13)

- Active production release: `20260813_111424` on backend and frontend. Immediate rollback release: `20260813_060025`.
- Backend image: `milana-backend:20260813_111424` (`8000:10000`), image SHA `f855496f4ff8bf781cee310d2b32f8df52f8023f60f471bea288a4a86708c6c2`. Frontend build ID: `jL1migYjmO9q6IPn3xKtc`.
- The Sewing Production Report now has typed, searchable employee, production/sales order, cutting/batch, model, sewing-line, operation, and size filters. Reference lists are available before the first payroll scan: active employees, current production orders/models/batches, active sewing lines, and configured sewing operations are included alongside historical payroll values.
- Release archive SHA-256: `422bd0260a506ab325daf1f1b0c4e338db6ca7c40a26a6e742896acf5933e4c5`; 535-file source-manifest SHA-256: `a7a04292761374ebfcac02b8b9d1173081d4af3495c6407090b2e4fe4307b4ba`.
- Fresh validated backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260813_111424.dump`, 42,511,763 bytes, 964 restore objects, mode `0600`. Dump SHA-256 `7b79db54d883981f5d82bc2873b0a6b8d4558cd1f6caa0ee532bceca19eeac4f`; restore-list SHA-256 `5efa5b71ec1cccf56fda4847d8d59c9041dd01ab511868a8cfcfe8c4199f90a0`.
- Alembic remained at `0092_sewing_role_access (head)`. No schema or business data changed. The final payroll suite passed 24 tests, both production builds passed, all four internal/public health and login checks returned HTTP 200, two Uvicorn workers are active, and PostgreSQL used 17 of 100 connections.
- Signed-in production QA confirmed that employee search returns real names, employee numbers, positions, and departments; operation search returns configured operation names/codes; the report rendered without browser console errors.
- The production payroll ledger is still empty: zero payroll records, QR labels, payroll periods, piecework assignments, and piecework acceptances. Six piecework shifts are open with no assignments or acceptances. No live payroll row needed repair.
- Configuration audit found 17,096 selected sewing-operation rows per factory with nonpositive rates, 825 per factory without standard time, and inconsistent currency codes (`UZB`, `UZS`, and one `UK`). These must be normalized and approved before live salary processing.
- The full logic review and prioritized remediation plan is in `docs/PAYROLL_LOGIC_AUDIT_2026-08-13.md`. The most urgent unresolved risk is that the legacy QR scanner and QR-issue endpoint accept client-supplied quantity, rate, currency, timestamp, and work metadata. Payroll must become server-authoritative before real salary records are created.

## Factory login and operational scope (deployed 2026-08-12)

- Login requires selecting Milana, Besttex, or Eco Cotton. Normal users may enter only their assigned factory; Super Admin may enter any factory.
- User records carry an admin-managed factory assignment and authenticated sessions carry the selected factory.
- Sales, planning, purchasing, inventory, warehouse, finance, payroll, models, master data, and other shared services remain shared.
- Only existing operational workflows are scoped: Milana has cutting, printing, sewing, and packaging; Besttex has sewing and packaging; Eco Cotton has cutting, sewing, and packaging.
- Besttex and Eco Cotton package data remains separate during packaging. Their finished packages continue into Milana's shared warehouse.
- Active release: `20260812_063934` on backend and frontend. Rollback release: `20260812_063343`.
- Database migration: `0090_user_factory_access` (head).
- Pre-migration backup: `/opt/milana-erp/shared/backups/milana_pre_20260812_061548.dump`, 42,484,584 bytes, 963 restore objects, mode `0600`.
- Backup SHA-256: dump `4f07145e2fb9a401e660b8510284e1ae7db863a8e194091170e0b47c02451ab9`; restore list `a5d78f60d7d559b5e11e7cb42f44979f8551a97aada1ad3fac448e0626fcf1b7`.
- Validation: 20 focused backend tests passed, the production Next.js build passed, all four internal/public health checks passed, two Uvicorn workers are active, and no new backend traceback/error was present after cutover.
- Broader workflow run: 85 passed and 8 failed. Six failures are unrelated existing workflow/test-state assertions; two old cross-factory routing tests now receive the intended `403` because their bearer token does not select Eco Cotton/Besttex. These tests must be updated for selected-factory sessions.
- Super Admin factory sections deployed in `20260812_062824`: Super Admin keeps access to all three factories simultaneously, with Milana, Besttex, and Eco Cotton operations shown as separate navigation sections and each section retaining its existing isolated operational dataset. Normal users remain restricted to their assigned factory.
- Correction deployed in `20260812_063343`: Super Admin may choose any factory at login, but the authenticated session displays and permits only the selected factory's operational sections. Shared departments remain visible. Selecting Milana shows only Milana operations; selecting Besttex shows only Besttex operations; selecting Eco Cotton shows only Eco Cotton operations.
- Pre-cutover backup for `20260812_063343`: `/opt/milana-erp/shared/backups/milana_pre_20260812_063343.dump`, 42,485,706 bytes, 964 restore objects, mode `0600`. Dump SHA-256 `cd28b43c98c991a91b2599a53a07662916834b0fe7539b4796df056872347a66`; restore-list SHA-256 `ddd613972c93d35d1713037a9072d4edf8427c23571be98615535365197d3041`.
- Deployed in `20260812_063934`: shared-service navigation and the shared dashboard are visible only in Milana sessions. Besttex sessions show and land in only the Besttex operational workspace; Eco Cotton sessions show and land in only the Eco Cotton operational workspace. Shared data remains centralized under Milana.
- Pre-cutover backup for `20260812_063934`: `/opt/milana-erp/shared/backups/milana_pre_20260812_063934.dump`, 42,485,701 bytes, 964 restore objects, mode `0600`. Dump SHA-256 `ef0d190d0009c9d86decc95ae6f550aa622d627cad628afce1120e53dc6c35e3`; restore-list SHA-256 `4df0570a3c669f7b277145bda090bbe6645ceecc72dd78bc8f5b8e3adb61abdc`.
- Pre-cutover backup for `20260812_062824`: `/opt/milana-erp/shared/backups/milana_pre_20260812_062824.dump`, 42,485,632 bytes, 964 restore objects, mode `0600`. Dump SHA-256 `56c4dc8763a536898e2abe986846001d30de6113064c3e422812b4d422ed6007`; restore-list SHA-256 `7a11b7d2a930992c9acc8ada84fae64b8ff5f410f866b7c47a64a222cc364c41`.

## Payroll QR return and reports deployment (2026-08-13)

- Active production release: `20260813_051049` on backend and frontend. Immediate rollback release: `20260812_125819`.
- Backend image: `milana-backend:20260813_051049`, published as `8000:10000`, with one Uvicorn parent and two workers, zero restarts, and no OOM kill after cutover. Frontend build ID: `s3idQl_P7OaULSACYLE8W`.
- Returning a payroll work QR now voids its old payroll record, removes the active payroll association, and makes the QR available for scanning again. The scanner also clears stale local history for returned labels.
- Added the Sewing Production Report with production/payroll filters, CSV export, printing, and pagination.
- Added the Order QR Status report. Users first select an exact sales or production order, then see issued/scanned/not-scanned quantities by operation and size plus an exact QR-detail list. Returned labels appear as available/not scanned.
- Source archive SHA-256: `db40f3306c0671f578576cbfa7975ab82dc9c9314f9e417125ed715a6bac409d`; 536-file source manifest SHA-256: `db80aea1ddc313bf71f1bb52a51fef067878a4ae400706890a6f8d0c498bd327`.
- Validated pre-deployment backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260813_051049_20260813_051643.dump`, 42,510,661 bytes, 964 restore objects, mode `0600`. Dump SHA-256: `05cedaa296fade41524b740008e9d21b17b7b8ae543a9c225a73f570035203fd`; restore-list SHA-256: `b48f421ea4c26bde30ddc3b1369ca0eb3c392eef9d375070920f6804255213a2`.
- Alembic remained at `0092_sewing_role_access (head)`; no schema or business data changed. All four required internal/public health and login checks returned HTTP 200. PostgreSQL used 16 of 100 connections after deployment; recent backend and frontend logs contained no new errors.
- The public report routes returned HTTP 200, both report APIs are present in the production OpenAPI document, and the protected report API returned HTTP 401 without authentication. An authenticated visual smoke test was not completed because available browser sessions were logged out; no credentials were bypassed or reused.
- The production frontend dependency install still reports seven known npm advisories (one moderate, six high). No unreviewed dependency upgrade was included in this payroll deployment.

This is the repository copy of the durable context for future Milana ERP work.
It was consolidated from 181 ERP-associated Codex sessions dated 2026-05-12
through 2026-07-23: 127 user-facing chats, 42 internal review sessions, and 12
daily monitoring runs. Passwords, tokens, and other secrets are intentionally
excluded.

## What This Project Is

Milana ERP is the real production system for a garment/textile factory, not a
demo. It covers:

`Sales Order -> Planning -> Cutting -> Bundle QR/barcode -> optional Printing
-> Sewing -> Packaging -> Package QR/barcode -> Finished Goods -> Shipment`

It also includes branded-stock production, Besttex and Eco Cotton flows,
material and accessory inventory, purchasing, reservations, waste, payroll,
finance/1C integration, customers, audit history, forecasting, traceability,
tasks, notifications, user/role management, daily sewing reports, and an
AI/MCP assistant.

The repository is `C:\ERP`.

## Paid-Operation Sewing Factory Separation

Production release `20260811_100247` separates model paid operations into
Milana Sewing, Besttex Sewing, and Eco Cotton Sewing sections. Migration
`0086_paid_operation_factories` copies every existing operation into all three
sections with the same current values, producing three independent rows that
can be edited separately afterward. Every operation newly added from the model
editor or payroll QR editor is also saved with an explicit sewing-factory
value.

For users with the `Sewing` role whose department is `MIL`, `BST`, or `ECO`,
model API responses include only that user's own factory operations. Scoped
model saves reject cross-factory rows and merge the user's visible changes with
the hidden factory rows, preventing an update from deleting or overwriting
another factory's configuration. Piecework operation selection is also
filtered to the production order or batch's routed sewing factory, while the
original operation key is retained for historical piecework compatibility.
Migration `0086_paid_operation_factories` is active in production.

Production release `20260811_120743` adds a single sewing-factory selector to
Process QR. The paid-operation table and generated label preview now contain
only the selected factory, and new operations inherit that factory. Work-label
identifiers and compact QR payloads also carry the factory code (`MIL`, `BST`,
or `ECO`) so otherwise identical labels cannot collide across factories. A
Sewing-role user in department `MIL`, `BST`, or `ECO` is locked to that
department's factory; admins can switch among all three. Separate payroll-page
access for the three future sewing-master accounts remains future work.

## Local Cutting-Sheet Batch QR Sewing Acceptance

Local-only source changes on 2026-08-11 replace the cutting sheet's batch
traceability QR with a sewing-acceptance QR. On the Sewing bundle scanner, the
operator scans the cutting-sheet QR and a dialog shows the batch details and
asks which sewing line is accepting it. Confirming the dialog atomically
receives every sewing-ready bundle in that exact production batch and creates
or confirms one batch-scoped `SewingAssignment` for the selected line, so no
second assignment step is required. Other batches from the same production
order remain separate and can be accepted by different lines. Repeat scans on
the same line are idempotent, while conflicting line assignments, incomplete
Printing handoffs, order-level assignments, external-factory bundles,
inactive lines, and completed-assignment conflicts are rejected.

The Sewing workspace allowlist now includes `/bundles/scan/sewing`. Every user
assigned the shared `Sewing` role, including the 1st-, 2nd-, and 3rd-floor
sewing accounts, can see and open the scanner; the existing `sewing.bundles`
backend permission remains required for the acceptance API.

The isolated active-production-baseline candidate passed Ruff, Python
compilation, a full Next.js production build, and two focused backend tests
covering the cutting-sheet QR plus two batches, two lines, four bundle
receipts, conflicting-line rejection, and repeat-scan idempotency.

Candidate release `20260811_054429` was built and uploaded to both application
VMs with archive SHA-256
`347202d64703c1de4613f9e581d0c890a5e4b8ce596115dfec2d71ea9adf7c1e` and
matching 449-file source-manifest SHA-256
`e532b0787bc78bcd7e9fa14c0a2dcce9c694897de75dcfe1a249259bc45adaab`.
The fresh validated backup is
`/opt/milana-erp/shared/backups/pre_sewing_batch_qr_20260811_054429.dump`
(26,284,246 bytes; 960 objects; SHA-256
`f307418c8b3adf0a4a765c10491635add90a71e61bc6d9aaaf0145a461ab3fa1`);
its restore-list SHA-256 is
`18307c3f1e21c91da339eacffb46f6f4e6c25b6c4b3fb88aa9cba794cc58e724`.
Alembic remained at `0084_model_group_key (head)`.

The backend candidate briefly passed its direct health check, but frontend
activation was denied because the `admilana` deployment account cannot restart
`milana-frontend` non-interactively. Both hosts were therefore rolled back to
release `20260811_090217`; the four internal/public health checks returned 200,
the backend had zero restarts and no OOM kill, and PostgreSQL had 85 of 100
connections free. No business data or schema changed. The candidate remains
built but is not active. Deployment requires narrowly authorized
non-interactive service-restart access (or an administrator present for the
frontend cutover). The rolled-back active backend also showed one Uvicorn
server process rather than the two-worker topology documented in
`DEPLOYMENT.md`; this pre-existing operational discrepancy remains open.

## Purchase Request Master Data Names

## Production Order Model Label Consistency

Production release `20260810_101545` fixes production-order detail pages that
showed a raw model database ID when the linked model was absent from the
page's separately loaded catalog slice. The detail API now returns the linked
model code and name directly, and the page uses that authoritative payload for
both the summary and edit fallback. This applies to every production-order
detail, not only the reported order.

Production data for `SO-2026-000071` was verified as internally consistent:
production order `#75` links to model `#7113`, business code
`ХJ3062-V-5658`, its primary model image, and assigned fabric batch `YOD1`.
The model and material images serve different documented purposes and were not
changed. No business data was modified.

Both VMs point to `/opt/milana-erp/releases/20260810_101545`; the backend runs
`milana-backend:20260810_101545` with two workers and frontend build ID
`srzZn2lUnPLGoJ9Crzocr` is active. Alembic remains at
`0083_employee_number`. The verified pre-change backup is
`/opt/milana-erp/shared/backups/pre_model_label_consistency_20260810_101545.dump`
(26,265,915 bytes; 959 restore objects; SHA-256
`f6470a0c3837589ecb5033b020241aa991ee271bd7f8c333f56afda3ec8328a4`).
Its restore-list SHA-256 is
`9c22667013a42243051a8caa9b67dcc0bd98b209bc83fdbb0c62a1ca7bea103f`.
All four internal/public checks returned HTTP 200, recent logs had no errors,
and PostgreSQL had no blocking locks. Release `20260810_094959` is the
immediate rollback.

## Allocated Batch Material Reassignment

Production release `20260810_094959` extends the existing force-inventory
override so an authorized user can reassign a reserved or historically used
stock batch from an archived/deleted Master Data material to another active
material in the same inventory group and unit. Reservations, production-order
and Cutting links, batch quantities, and other batch references remain intact;
the batch's stock movements are relinked to the selected material so inventory
reporting stays consistent. No material or other business record was edited
during deployment.

Both VMs point to `/opt/milana-erp/releases/20260810_094959`; the backend runs
`milana-backend:20260810_094959` with two workers and the frontend build ID is
`dRLfp3D91eBNBnTSBnIYw`. Alembic remains at `0083_employee_number`. The
verified pre-change backup is
`/opt/milana-erp/shared/backups/pre_batch_material_reassignment_20260810_094959.dump`
(26,264,333 bytes; 959 restore objects; SHA-256
`c1e4ed8f032994346c2566c3055120784b11f8a82ecaeabcb56cbfdeb8c70cde`).
Its restore-list SHA-256 is
`8671c06c04406fd5cedef1a9e730b0ac2fc39cd34d68c2bed21bdbfd3f5a7143`.
All four internal/public checks returned HTTP 200, recent logs had no errors,
and PostgreSQL had no blocking locks. Release `20260810_071821` is the
immediate rollback.

## Allocated Inventory Override for Mubina

Production release `20260810_071821` adds a narrow force-inventory override.
Administrators and users with the new `inventory.force_override` permission
can reduce material or batch kilograms below the currently reserved quantity.
Linked Master Data deletion archives the item instead of breaking historical
references; linked batch deletion records an issue adjustment, sets the batch
quantity to zero, and places it on hold while preserving reservations,
movements, production-order assignments, Cutting evidence, BOM links, and
waste history.

Mubina (`mubina@milanapremium.uz`, user `#8`) retained her Storage role and
existing additional permission and received only
`inventory.force_override`. Audit record `#12241` records the user-specific
grant. No other user or role permission changed. Both VMs point to
`/opt/milana-erp/releases/20260810_071821`; the backend runs
`milana-backend:20260810_071821` with two Uvicorn workers, and frontend build
ID `vUovejDMrKBlLp8R9uDFt` is active. Alembic remains at
`0083_employee_number`.

The verified pre-change backup is
`/opt/milana-erp/shared/backups/pre_inventory_force_override_20260810_071821.dump`
(26,240,433 bytes; 959 restore objects; SHA-256
`d10fec4283bec8da456aaa78514bbde1aa4be3910779c64c10e44b5e7f791841`).
Its restore-list SHA-256 is
`f656a7034872e82cf31c64618aa3f6fa60b91e96f04f0dad2afe1714c53afa2b`.
All four internal/public health and login checks returned HTTP 200, recent
backend/frontend logs had no 5xx or traceback errors, and PostgreSQL had no
blocking locks. Release `20260810_104020` is the immediate rollback.

Production release `20260810_104020` keeps the Purchase Request product
dropdown backed by Inventory Master Data item IDs while displaying and sorting
only the clean material/accessory names. Batch-like SKU text is no longer shown
in the dropdown; request creation still stores the correct selected item ID.

The release was rebuilt from exact active release `20260810_101625` with only
the purchasing frontend page overlaid. Both VMs point to
`/opt/milana-erp/releases/20260810_104020`; the backend runs
`milana-backend:20260810_104020` with one parent and two workers, zero restarts,
and about 0.46 percent CPU. Alembic completed at head and all four required
internal/public health and login checks returned HTTP 200. No schema or
business data changed. Release `20260810_101625` is the immediate rollback.

## Backend Two-Worker Runtime Recovery

On 2026-08-10, release `20260810_101625` was restarted with one Uvicorn parent
and two workers after its initial deployment used the image's one-worker
default command. The single worker reached approximately 100 percent CPU and
caused intermittent internal and public `/health` timeouts even though the VM,
PostgreSQL, memory, disk, and frontend remained healthy.

The recovery kept the same release and image, ran Alembic once, set
`RUN_SEED_ON_STARTUP=false` for worker startup, and launched Uvicorn with
`--workers 2`. After recovery, backend CPU was about 0.43 percent, memory was
about 427 MiB, PostgreSQL had three connections and zero active queries, and
all four required internal/public health and login checks returned HTTP 200.
No schema or business data changed. The current image default still starts one
worker, so future container recreation must preserve the explicit two-worker
runtime command until the image startup command is corrected.

## Production Data Purge: PO-2026-000061 and PO-2026-000063

On 2026-08-10, at the operator's explicit request, the standalone
branded-stock workflows `PO-2026-000061` (`SJ4022-3806`) and
`PO-2026-000063` (`PJ1204-V-5647`) were completely removed from production.
The guarded transaction deleted exactly two production orders, eight work
orders, ten size rows, three material-planning rows, two production batches,
two Cutting records, one waste row, one Cutting passport, 605 untouched
bundles and their 605 creation-only scans, and eight linked notifications. It
found no Sewing, packaging, finished-goods, shipment, replacement-work, or
linked-task activity. The 605 bundle QR files were removed from active storage
after verified archival under
`/opt/milana-erp/shared/backups/po61_po63_workflow_purge_20260810_101145/`.

Fabric was intentionally not returned. Consumption movements `#1334` (147 kg
from batch `5173`) and `#1335` (68 kg from batch `8373`) remain unchanged, for
215 kg retained consumption. The batch balances remain 416 kg and 81.6 kg,
respectively. Historical movement `#64`, an unrelated older record with a
numeric Cutting-record reference collision, and its batch balance were also
preserved. Both models and branded-planning order `0010` were retained.

Audit records `#12006` and `#12007` record the deletion and form a valid
two-row hash-chain segment. The verified pre-change PostgreSQL backup is
`/opt/milana-erp/shared/backups/pre_po61_po63_workflow_purge_20260810_101145.dump`
(26,226,777 bytes; 959 restore objects; SHA-256
`825e7d759c2abebc5dd11c16cce7a92eaf5991657bfbe5e283b1a9d81510390c`).
Its restore-list SHA-256 is
`8272e83feb81920317b89f67eb1f5863c6ffcadf0d6f81024651c42c22dee976`.
The 605-file QR archive SHA-256 is
`8e49a379503ef5a5de2fee27a2df330626c4553d3e665621c4bd71082e65bc59`.
Post-change assertions found zero remaining target workflow rows; all four
internal/public health and login checks returned HTTP 200, and recent backend
logs had no 5xx/traceback errors. No application deployment was performed;
release/image `20260808_125730` remained active.

## Pending Replacement Work Removed Without Work-Order Changes

On 2026-08-10, at the operator's explicit request, the two untouched pending
replacement-work cards for `SO-2026-000001` (12 pieces, line Bozorova) and
`SO-2026-000060` (4 pieces, line Botirova Muxlisa) were removed from
production. Replacement-request rows `#2` and `#3` were both still
`waiting_cutting` with zero cut and zero replaced pieces. Their four
replacement-specific notifications (`#241`, `#242`, `#296`, and `#297`) were
also removed; unrelated order, bundle, packaging, and storage notifications
were preserved.

The guarded transaction locked and compared all eight work orders before and
after deletion and confirmed that every field and counter remained unchanged.
Both production orders, their source Sewing records (including the recorded
12 and 4 failed pieces), original Cutting records, batches, bundles, packages,
and all other production evidence were preserved. Audit records `#12004` and
`#12005` record the narrow deletion and form a valid hash-chain segment.

The verified pre-change PostgreSQL backup is
`/opt/milana-erp/shared/backups/pre_remove_replacement_work_20260810_093138.dump`
(26,226,279 bytes; 959 restore objects; SHA-256
`0cce27b40d72ed6ef7afbba112f3733053bc5329599ce0c43c801661ed0f381d`).
Its restore-list SHA-256 is
`8d13c2902ca6e52d1320bc8c1d085f8762364dc590e0ec1f8e8aa926f2dc28ad`.
Post-change checks found zero target replacement requests and notifications,
all four internal/public health and login checks returned HTTP 200, and recent
backend logs had no 5xx/traceback errors. No application deployment was
performed; release/image `20260808_125730` remained active.

## Production Data Purge: 19 Branded Workflows Without Fabric Return

On 2026-08-10, at the operator's explicit request, the 19 branded-stock
production workflows shown in the supplied screenshots were completely
removed from production:
`SO-2026-000004`, `SO-2026-000018`, `SO-2026-000019`,
`SO-2026-000020`, `SO-2026-000025` through `SO-2026-000030`,
`SO-2026-000033`, `SO-2026-000035` through `SO-2026-000042`.
These UI numbers mapped to standalone `production_orders`; none was a customer
`sales_orders` row.

The guarded transaction deleted exactly 19 production orders, 76 work orders,
114 size rows, 16 material-planning rows, five production batches, five
Cutting records, five Cutting material-usage rows, five waste rows, three
Cutting passports, 24 untouched bundles and their 24 creation-only scans, and
16 linked incoming-bundle notifications. It found no package, packaging
receipt, material reservation, piecework, sewing report, replacement request,
or linked task. The 24 bundle QR files were removed from active storage after
being archived recoverably under
`/opt/milana-erp/shared/backups/bulk_branded_workflow_purge_20260810_090801/`.

Fabric was intentionally not returned. The five real consumption movements
`#727`, `#750`, `#769`, `#774`, and `#775` remain unchanged, preserving
1,131 kg consumed by the four workflows that had Cutting activity. Their
source batches remain at zero. Historical movement `#40`, an unrelated older
record that collides with Cutting record numeric ID `7`, was also preserved.
All other referenced fabric batches and their quantities were unchanged.
Models, branded-planning parents, and historical audit rows were retained.

Audit records `#11967` through `#11985` record the deletion and form a valid
19-row hash-chain segment. The verified pre-change PostgreSQL backup is
`/opt/milana-erp/shared/backups/pre_bulk_branded_workflow_purge_20260810_090801.dump`
(26,226,904 bytes; 959 restore objects; SHA-256
`0fdce355316e340a88b508151d703172fae6021fef5953528532cd985ccaeb54`).
Its restore-list SHA-256 is
`3849bf9a76b7b71a9fb039fa4b38f3e422b4a3906f2e638e3363a0f14ad5d50e`.
The 24-file QR archive SHA-256 is
`83961c23d486da26a9449527dac04b0cc1ee4ee83a5f5c54058297ebe0fccfa3`.
Post-change database assertions found zero remaining target rows; all four
internal/public health and login checks returned HTTP 200, and recent backend
logs had no 5xx/traceback errors. No application deployment was performed;
release/image `20260808_125730` remained active.

## Employee Roster Import and Staff IDs

Production release `20260808_065111` added a separate, optional, unique Staff
ID (`employees.employee_no`) and displays it beside each employee name in the
Employee form and table. The API validates numeric Staff IDs and returns HTTP
409 for duplicates. Alembic migration `0083_employee_number` is active.

The sewing roster in `tikuvchilar.xlsx` was transliterated to Latin and
imported into department `MIL` (Milana Sewing Factory) as active `Tikuvchi`
employees. The workbook contained 314 filled rows: eight exact repeated
ID/name rows were collapsed, producing 306 employees with unique numeric Staff
IDs. No existing employee was overwritten; the pre-existing unnumbered
employee was preserved. Audit log `#11844` records the import. Production
verification found 306 numbered employees and 307 employees total, and the UI
showed separate `Full name` and `Staff ID` columns without browser errors.

Before the schema/data change, PostgreSQL was backed up to
`/opt/milana-erp/shared/backups/pre_employee_import_20260808_065111.dump`
(26,189,145 bytes; SHA-256
`050f9c86f9c7988065f6945d846d3ee170e2fbb99ac179155c1926f18cc025ff`;
958 restore objects). The restore-list SHA-256 is
`0ca282cdd520116c83f4f0fca5bfc36431e0de130f385d3a3d6c9a175e33a8ed`.
Both VMs point to `/opt/milana-erp/releases/20260808_065111`; the backend runs
`milana-backend:20260808_065111` with two workers. All four required internal
and public health/login checks returned HTTP 200. Release `20260808_064555`
and its backend image remain the immediate rollback. The frontend install
still reports seven inherited npm audit findings (one moderate and six high).

## Payroll Daily Sewing Report Access

Production release `20260808_113444` gives the seeded Payroll role the narrow
`sewing.daily_reports.view` permission. Payroll users can open the existing
Daily Sewing Report page, select a date, review line totals and entries, and
generate Excel or PDF reports. Sewing entry creation and correction remain
restricted to `sewing.workspace` users at both the frontend and API layers.

The release was rebuilt from exact active release `20260808_062552` and
overlaid with five scoped source files. Both VMs point to
`/opt/milana-erp/releases/20260808_113444`; the backend runs
`milana-backend:20260808_113444`, the frontend service is active, Alembic
completed at head, and all four required internal/public health and login
checks returned HTTP 200. Startup seeding updated only role permission data;
no schema or business records changed. Release `20260808_062552` remains the
immediate rollback. The frontend install still reports seven inherited npm
audit findings (one moderate and six high), and local/GitHub history remains
divergent from production.

## Production Data Reset: PO-2026-000071 Cutting Restart

On 2026-08-08, at the operator's explicit request, production order
`PO-2026-000071` was reset to the start of Cutting so the work can be entered
again correctly. The six original bundles `BND-2026-000088` through
`BND-2026-000093` (462 pieces total), their 12 creation/Sewing-receipt scans,
Cutting record `18`, material-usage row `16`, waste row `17`, production batch
`0075-01`, and unstarted Sewing assignment `10` were removed. Preflight checks
confirmed there was no Sewing output, piecework/payroll, packaging receipt,
package, or warehouse evidence linked to those bundles.

The matching 215 kg stock consumption movement `1142` was reversed by removing
that movement and restoring batch `8363` from 0 to 215 kg. An older unrelated
movement that happened to reference a historical Cutting record with the same
numeric ID was preserved. The order remains linked to passed-QC batch `YOD1`
(7,181 kg) for the new entry. The Cutting work order is `in_progress` with zero
counters; Sewing, Packaging, and Storage are `waiting` with zero counters. The
production order status is `cutting`, and it has no production batch, Cutting
record, bundle, waste, or Sewing assignment remaining.

Audit log `#11842` records the reset. The pre-change PostgreSQL backup is
`/opt/milana-erp/shared/backups/pre_po_2026_000071_cutting_reset_20260808_111922.dump`
(26,188,769 bytes; SHA-256
`fdf3b613dc66bf84d364927079583107cc81f3e82c7020fa03e2b40f88af6500`;
958 restore objects). Its restore-list SHA-256 is
`ed1d0872dbce458a89273f143d00286c977260eef75758f525088b0fad9fae52`.
Post-change database assertions and all four health checks passed. No
application deployment was performed during the reset; release
`20260808_061002` remained active at that point.

## Sewing Restored to the Pre-Partial-Size Form

After the operator clarified the requested rollback, production release
`20260808_064555` restored Sewing to the form used before the 2026-08-08
partial-by-size request: Input quantity, Output, and Defect only. The per-size
entry table and its API request are no longer used by the form, and Rework and
Rejected are also absent. General Sewing submissions explicitly send zero for
the two compatibility fields and use the operator-entered aggregate input and
output quantities. Release `20260808_063909`, which briefly restored Rework and
Rejected because of a misunderstanding, was superseded without submitting any
business record.

The database remains at `0082_sewing_size_quantities`; its nullable compatibility
column and backend endpoint were intentionally retained unused to avoid a
destructive schema downgrade. Both VMs point to
`/opt/milana-erp/releases/20260808_064555`. The backend runs
`milana-backend:20260808_064555` with the unchanged image SHA-256
`be6ddc6635d0c20b85fe3950167632d2fd5430ef64cf55c851f865c4a0873a9c`.
The 443-file source manifest SHA-256 is
`59408be42a7a0b7e728a7a7147a092f8c3e14f84f6ee687a126acf811f648ffc`,
the archive SHA-256 is
`f049a0c6a47a2e19958f65b46b6ae30ab268611e008217e52db87aea5c875bc1`,
and the frontend build ID is `M_2Ef2f-bFJPM1qF56wdb`.

The most recent verified database backup, taken before the two frontend-only
correction cutovers, is
`/opt/milana-erp/shared/backups/pre_sewing_fields_restore_20260808_063909.dump`
(26,189,146 bytes; SHA-256
`000b91c8e75b2cacb4f4b4aa6a8c6ebb49cab4bc58d46b57e0128f0b63143fb8`;
958 restore objects). Its restore-list SHA-256 is
`7e0d8f904ca8b7562e756f8bcb69299f182e84af8f4894627b37a4e082606a12`.
The baseline UI contract, TypeScript, targeted ESLint, local and remote builds,
source manifests, all four health checks, and signed-in read-only UI QA passed.
The live Uzbek form shows `Kirish miqdori`, `Chiqish`, and `Brak`, with no size
table, `Qayta ishlash`, or `Rad etilgan`, and no browser-console errors. No
business or schema data was changed.

## Sewing Rework and Rejected Controls Removed Again (Superseded)

Production release `20260808_062552` restores the intended Sewing form after
the partial-size deployment accidentally reintroduced the retired Rework and
Rejected controls. The July removal had been deployed directly but was not
preserved in the later local/GitHub sewing page; applying the partial-size page
from that stale source brought the controls back. Defect remains the only
operator-facing rejected-piece quantity. General and replacement Sewing
submissions explicitly send zero for the two compatibility fields, and the
partial-size contract now fails if either retired control returns.

Both VMs point to `/opt/milana-erp/releases/20260808_062552`. The backend runs
`milana-backend:20260808_062552` with two Uvicorn workers and zero restarts;
its unchanged image SHA-256 is
`be6ddc6635d0c20b85fe3950167632d2fd5430ef64cf55c851f865c4a0873a9c`.
The 443-file source manifest SHA-256 is
`52e54527b7528309c3587f77b8c6b151d4f01a62f2f0a358f96e16eefb0138c7`,
the archive SHA-256 is
`a3464785ee4027879008483e0eab1f2f72b45fb35ebb5aed1d5ba52f7dafb8d1`,
the frontend build ID is `oCPtnfh05iVQ_2e6jlWDn`, and Alembic remains at
`0082_sewing_size_quantities`.

The verified pre-cutover backup is
`/opt/milana-erp/shared/backups/pre_sewing_fields_regression_20260808_062552.dump`
(26,189,123 bytes; SHA-256
`24a1ae784cb27cfb19954590f7fafbf745b0e8483eb5c9cc8c1bcbd7e44be1af`;
958 restore objects). Its restore-list SHA-256 is
`6ee7a5c0d674565e47a63230fa9995d4fc7e8fec307ae1cf6db608ac2a308889`.
Local contract, TypeScript, targeted ESLint and production-build checks, both
remote builds, source manifests, all four health checks, and signed-in
read-only UI QA passed. The live form shows Failed, Line name, Defect reason,
and Notes with no Rework or Rejected controls and no browser-console errors.
No business or schema data was changed. Release `20260808_061002` is the
immediate rollback.

## Intermediate Production Data Correction: PO-2026-000071 Material Relink (Superseded)

On 2026-08-08, production order `PO-2026-000071` was repaired after the
operator retried Cutting while its original fabric batch `8363` was depleted.
Three successful zero-material Cutting submissions (records `35`, `36`, and
`37`) had created 1,800 duplicate pieces, 36 untouched bundles, and three
duplicate waste rows. All affected bundles were still in Cutting with only
their automatic `created` scan, had no packaging receipt, and had no stock
movement or material-usage evidence.

After a verified PostgreSQL backup, only those three submissions and their
untouched dependent rows were removed. Cutting counters returned from 2,262 to
the legitimate 462 pieces, and Sewing, Packaging, and Storage plans returned
from 2,262 to the original 600-piece plan. The original six bundles already
received by Sewing and the legitimate 215 kg consumption from batch `8363`
were preserved.

The production order and its material row were relinked from empty batch
`8363` to the operator-selected passed-QC batch `YOD1`, which had 7,181 kg
available. No stock was created or adjusted. Audit log `#11841` records the
correction. The pre-change backup is
`/opt/milana-erp/shared/backups/pre_po_2026_000071_material_repair_20260808_111115.dump`
(26,189,366 bytes; SHA-256
`77c08b7d4435f386641fd687620db400680d65022aea91e3ebf79b89a16fad72`;
958 restore objects). Its restore-list SHA-256 is
`5173d2557164ab7323b7fcbef29ac47d0776db03dc441be14a0d3458541b7630`.
All four health checks passed at that intermediate point. The later full reset
documented above superseded the preserved-bundle state and occurred after
release `20260808_061002` became active.

The current Cutting endpoint still permits a selected fabric batch with zero
input kilograms and has no submission idempotency key. A separate application
fix and deployment are still required to prevent this retry pattern from
recurring.

## Partial Sewing Output by Size Deployed

On 2026-08-08, the Sewing work-order form was extended to record partial
completed output for each garment size. For the selected internal production
batch, the form now shows each size's planned, previously recorded, remaining,
and current-entry quantities. Operators can save any completed subset and
return later to record the rest; the normal sewing, assignment, replacement,
packaging-handoff, and work-order totals still use the summed record output.

Each new sewing record persists its exact size breakdown in
`sewing_records.size_quantities`. The backend rejects unknown sizes, a size
quantity above its remaining plan, or a size sum that differs from the passed
output. Size plans use the selected batch's non-cancelled cutting bundles when
available and fall back to the production-order color/size breakdown. Existing
aggregate API clients remain compatible. Alembic migration
`0082_sewing_size_quantities` added the nullable JSON size breakdown column.

Production release `20260808_061002` originally deployed this change on both VMs. The backend ran
`milana-backend:20260808_061002` with two Uvicorn workers; the image SHA-256 is
`be6ddc6635d0c20b85fe3950167632d2fd5430ef64cf55c851f865c4a0873a9c`.
The 443-file source manifest SHA-256 is
`56563e8ee1c1bbc07f4f5f64159c3af4ba3b6f545d7d960295d0789782b61929`,
the frontend build ID is `9SsA_iXU7ytiXtoqUWlZF`, and Alembic is at
`0082_sewing_size_quantities`.

Before migration, PostgreSQL was backed up to
`/opt/milana-erp/shared/backups/pre_sewing_partial_size_20260808_060043.dump`
(26,188,811 bytes; SHA-256
`66983ee9bd7daed0d4a883584a926c2c7765dbdc669d2c9a7f1957613134969b`;
958 restore objects). Its restore-list SHA-256 is
`026d9fad8a30e89d5f02efbb607c66012bef78f48aef1ca47cb2cf50a0da297f`.

The focused batched-size regression, six broader sewing/replacement/packaging
regressions, Ruff, Python compilation, frontend contract and translation
checks, targeted ESLint, TypeScript, local and remote production builds, all
four health checks, runtime and database-headroom checks, and signed-in
read-only UI QA passed. The deployed form showed six size rows with correct
0-to-remaining input bounds and no browser-console errors. No business record
was created or changed; only the schema migration ran. Release
`20260807_102220` remains the application rollback, and backend image
`milana-backend:20260807_102220-db0082` is its tested migration-aware rollback
image. The inherited frontend audit reports seven findings (one moderate, six
high).

## Purchasing Request Screen Simplified

On 2026-08-07, production release `20260807_102220` simplified Purchase
Requests. The photo, item, supplier, material-name, and notes fields are hidden
until the purchaser presses New request / `Namuna yaratish`; the opened form
uses equal-width aligned field columns and explicit Cancel/Create actions. The
sales-order shortages panel and its frontend data requests were removed.
Rejected requests disappear from the approval queue immediately after a
successful rejection and remain excluded on reload.

Both VMs point to `/opt/milana-erp/releases/20260807_102220`; the backend runs
`milana-backend:20260807_102220` with two Uvicorn workers. The 441-file source
manifest SHA-256 is
`02bde4adbd87db9fc29c7e5330c52c53ccad9df8049e012d296ef1a8ff54ba6a`;
the frontend build ID is `5_laotyijqB5UA18GGxy1`. Alembic remains at
`0081_purchasing_approval_details`. Focused UI-contract and translation checks,
local and remote production builds, all four health checks, runtime checks,
and signed-in UI QA passed. The browser console and recent backend logs were
clean; PostgreSQL used 15 of 100 connections. No business or schema data was
changed.

Before cutover, PostgreSQL was backed up to
`/opt/milana-erp/shared/backups/pre_purchasing_clean_ui_20260807_102220.dump`
(26,166,164 bytes; SHA-256
`1f9981d5bc919117c99d1a431c9f56845124e197eeaf13a3c07a88545ee040dc`;
958 restore objects). The restore-list SHA-256 is
`8302c006158899d7600beec2f35aa254c769983ad7456f1626e1d042f82e154b`.
Release/image `20260807_101135` is the immediate rollback. The inherited
frontend audit still reports six findings (one moderate, five high).

## Purchasing Approval-to-Order Workflow Deployed

On 2026-08-07, production release `20260807_101135` changed Purchase Requests
into a persisted approval-to-order workflow. Each request line retains its
photo, material name, and supplier, and approval is blocked until all three are
present. After approval, the purchaser must enter a positive order quantity
for every line and an expected date. Ordering moves the same line details into
the Active Purchase Orders table while preserving warehouse receiving.

For that deployment, both VMs pointed to `/opt/milana-erp/releases/20260807_101135`; the backend ran
`milana-backend:20260807_101135` with two Uvicorn workers. The 440-file source
manifest SHA-256 is
`42c4558499f1504bf7ab1af39faa767514b7ae0d0a05a2d469d808612b9628be`;
the frontend build ID is `X-2yo9XtcqYwGah04ZFeA`. Alembic is at
`0081_purchasing_approval_details`. All four required health checks, runtime
and connection-headroom checks, and signed-in read-only QA of Purchase Requests
and Active Purchase Orders passed with no browser-console or recent backend
errors.

Before migration, PostgreSQL was backed up to
`/opt/milana-erp/shared/backups/pre_purchasing_approval_orders_20260807_101135.dump`
(26,164,538 bytes; SHA-256
`cb93595405538905c7201c5a09ce04ecc344819ffa340595b4f76b639a7bbefa`;
957 restore objects). The restore-list SHA-256 is
`a5c6cc8bf4bc77d316808fbef941cf93fef07c64d7a265a186e6a60618da3e3b`.
The migration enriched the one existing purchase-request line with its material
name; it had no item photo to backfill. No purchase order, request, or other
business record was created. Release/image `20260807_092952` is the immediate
application rollback; schema rollback would require the validated database
backup or a deliberate corrective migration. The inherited frontend audit
reports six findings (one moderate, five high).

## Warehouse Map Bulk Package Move Deployed

On 2026-08-07, production release `20260807_092952` added multi-package
movement to Warehouse Map. An occupied cell/shelf now shows a compact checkbox
list with Select all, Clear selection, a selected-count readout, and Move
selected. Operators may select any number of packages, choose the destination
cell/shelf, and confirm once. A one-package selection retains the existing
single-package path; larger selections use the existing authorized
`/api/packages/batch/place-on-map` endpoint.

The existing mixed-model rule now checks every selected package together with
the destination contents. Packages already at the selected destination are not
moved again. The batch endpoint remains transactional: a focused regression
proved that four packages move together and that when one of three packages is
rejected, the other two remain at their original location. English, Russian,
and Uzbek text is aligned.

The focused 14-check frontend contract, translation alignment, TypeScript,
targeted ESLint, three backend placement tests, Ruff, deterministic archive,
clean local and remote production builds, Alembic, two-worker/runtime checks,
and all four deployment health checks passed. Signed-in production QA selected
all 9 packages shown in one live cell, verified `9 of 9 selected`, cleared the
selection, and restored the original one-package selection. Move was never
armed or confirmed; no package location, scan log, audit row, or other business
data changed during QA, and the browser console remained clean.

For that deployment, both VMs pointed to `/opt/milana-erp/releases/20260807_092952`; the backend ran
`milana-backend:20260807_092952` with two Uvicorn workers. The 439-file source
manifest SHA-256 is
`d9defaa4399a9b3710040a8039ff1ac012bad1d5021ddeee795af92fbd8af4b0`;
the frontend build ID is `Hq7rCLKNr5BGDYhSbAAvE`. Alembic remains at
`0080_piecework_assignments`; no migration was required.

Before cutover, PostgreSQL was backed up to
`/opt/milana-erp/shared/backups/pre_warehouse_map_bulk_move_20260807_092952.dump`
(26,129,298 bytes; SHA-256
`de4afc22387302571918c65dd6ab0ad365bed48720b8714c0a21435998178489`;
957 restore objects). The restore-list SHA-256 is
`b3cd0ca7742d14f5045a78ae1056f7db8235c0ce0067ff857dc78bd48e409ae4`.
Release/image `20260807_140648` is the immediate rollback. The remote frontend
dependency audit still reports six inherited findings (one moderate, five
high).

## Material Batch Edit Action Restored

On 2026-08-07, production release `20260807_140648` restored the edit action
for older and imported fabric stock batches on the Material Warehouse page.
The page loads at most the newest 500 material master items, but previously
showed the pencil only when a batch's item was present in that limited lookup.
Valid older batches therefore showed Delete without Edit even though the
existing authorized backend batch-update endpoint fully supported them.

The frontend now derives the minimal editable material identity from the
batch payload when the full master item is outside the 500-item lookup. The
current batch material is also merged into the edit dialog's material choices,
so its value remains visible and selectable. Batchless aggregate rows still
require a loaded master item and are not made editable from incomplete data.
No backend behavior or authorization changed.

The focused material-edit availability contract, the existing supplier-edit
contract, translation alignment, TypeScript with import extensions enabled,
targeted ESLint, deterministic archive checks, the clean remote production
build, Alembic, service/runtime checks, and all four deployment health checks
passed. The ordinary repository typecheck still has an unrelated existing
`.ts` import configuration failure in `session-logout-contract.test.ts`, and
the broad lint retains an unrelated exhaustive-deps warning in the Cutting
page. Signed-in visual QA could not be completed because the available ERP
browser sessions had expired; no forms were submitted and no business data
was changed.

Both VMs point to `/opt/milana-erp/releases/20260807_140648`; the backend runs
`milana-backend:20260807_140648` with two Uvicorn workers. The 438-file source
manifest SHA-256 is
`f8287a8566aad73d4f98d2da8e50240275fbf6919a1212bc38503b2e833ea178`;
the frontend build ID is `LHw-F-2ZZDhOGKZ9S04V7`. Alembic remains at
`0080_piecework_assignments`; no migration was required.

Before cutover, PostgreSQL was backed up to
`/opt/milana-erp/shared/backups/pre_material_batch_edit_action_20260807_140648.dump`
(26,128,391 bytes; SHA-256
`46a7962f508ca1d94b552fe8f0bc5086b48a72a00d5df6f8f59b67b43321d9d4`;
957 restore objects). The restore-list SHA-256 is
`8fe92f45f19a09993d2a81cf7bd35f6bdd0b0f7bab00d3af710a359d3c28afc5`.
Release/image `20260806_180420` is the immediate rollback. The remote frontend
dependency audit still reports six inherited findings (one moderate, five
high).

## Package Label Variant Picture and 4-Up Portrait Layout Deployed

On 2026-08-06, production release `20260806_180420` deployed the approved
package-label design. Package labels now print four per A4 portrait page in a
2 x 2 grid (each label is 98.5 x 142 mm) with large client, order, model,
article, color, product, fabric, batch, size/quantity, weight, and total
quantity fields. The scan area keeps a 31 mm package QR and adds the exact
picture used by the Models variant catalog. Locally stored pictures and QR
images are embedded as data URIs so the normal frontend Blob print flow does
not lose authenticated storage images.

The single-label and four-label routes now share one escaped card renderer.
The Models variant-picture selection order is variant-specific material image,
variant fabric/BOM image, then the primary model picture. A missing picture is
shown explicitly without affecting QR placement. The print geometry was
rendered to PDF and visually inspected with four real ERP package records; all
four labels fit one A4 sheet without clipping. Signed-in production QA confirmed
four complete 370 x 370 QR images and four loaded 721 x 1280 variant pictures,
and the Packages page successfully opened the generated Package Label Sheet.
No package, order, stock, shipment, or other business data was created or
changed during QA.

Both application VMs point to `/opt/milana-erp/releases/20260806_180420`, and
the backend runs `milana-backend:20260806_180420` with two Uvicorn workers.
The 437-file source manifest SHA-256 is
`7f34748498e84dd8f47f3f08fb0e5c0d64d1b4acd3f882e45b289d08ecb75501`;
the frontend build ID is `iiA-FUIgGBwB55NarJO3g`. Alembic remains at
`0080_piecework_assignments`; no migration was required. Two focused label and
HTML-escaping tests, Ruff, Python compilation, deterministic archive checks,
local/remote builds, all four health checks, two-worker/runtime checks, and
signed-in read-only QA passed. A broader shared-database test selection passed
95 tests and exposed three unrelated order-dependent sewing failures; none
were in the package-label path.

Before cutover, PostgreSQL was backed up to
`/opt/milana-erp/shared/backups/pre_package_label_variant_picture_20260806_180420.dump`
(26,127,953 bytes; SHA-256
`474a7fe487dc3d06b4bc62bb311cf00554cb16c0a9b21c509bc6b2f6e5236e94`;
957 restore objects). The restore-list SHA-256 is
`5c1bfd644d28ba23aab0d33161aaefcf6b8030b51e864f1aa3e80a0546355ffc`.
Release/image `20260806_120747` is the immediate rollback. The remote frontend
dependency audit still reports six inherited findings (one moderate, five
high).

## Production Data Correction: Batch 0099-01 Moved to SEW-06

On 2026-08-06, the active sewing assignment for displayed order
`SO-2026-000095` (stored production `PO-2026-000095`), model number `РJ1002`,
batch `0099-01 - Batch 1`, was moved from `SEW-09` to `SEW-06` because the
work is physically being sewn on SEW-06. The guarded transaction changed
sewing assignment `13` and the single-assignment work-order primary flow on
work order `383` from SEW-09 to SEW-06. Planned quantity remains 600 and
completed quantity remains zero.

There were no Daily Sewing Report rows or piecework/payroll assignments for
this assignment. Sewing record `8` was a zero-quantity placeholder (all input,
sewn, passed, failed, rework, and rejected quantities were zero); only its line
snapshot changed from the old SEW-09 name `Dilafruz opa` to the current SEW-06
name `Botirova Shaxnoza`. No production quantity, stock, bundle, payroll, or
report output was changed. Audit row `11651` records the transfer, and its new
hash-chain segment verified successfully.

Before the correction, PostgreSQL was backed up to
`/opt/milana-erp/shared/backups/pre_sewing_assignment_move_0099_01_20260806_123527.dump`
(26,126,349 bytes; SHA-256
`9afe7571f16b392a497f058459e725fb2497ee91b6b253e6532dcd8195702cb5`;
957 restore objects). The restore-list SHA-256 is
`b744819724709272abba77b57eb12216d720a50f3f9ba6a8dba035866f9ece2e`.
Signed-in UI readback showed the exact `0 / 600` card under SEW-06 and no
active work under SEW-09. All four health checks, two-worker verification, and
recent-error checks passed. No application deployment was required; active
release/image remains `20260806_120747`.

## Branded-Stock Fabric Type Override Restored

On 2026-08-06, production release `20260806_120747` removed the stale rule
that forced the selected fabric batch to match the model BOM fabric type when
Planning creates branded-stock production. Planning may now deliberately
choose any available fabric or semi-finished batch. Matching model fabric is
still sorted first as the preferred choice, while failed/rejected QC batches,
non-fabric inventory, and batches without positive available stock remain
blocked. The selected batch's actual item, SKU, unit, and stock batch continue
to drive the production order and material reservation plan.

The restriction was present in both the branded-stock form and
`create_production_order`, so both checks were removed together. A focused
backend regression creates an available fabric batch outside the model BOM and
confirms branded production accepts it; a frontend contract protects the
all-batches selector, stock/QC filters, and matching-first ordering. Two focused
backend tests, Ruff, the frontend contract, TypeScript, ESLint, i18n alignment,
local and remote production builds, all four health checks, two-worker/runtime
checks, and signed-in read-only page QA passed. No production order, stock,
reservation, or other business record was created or changed during QA.

Both application VMs point to `/opt/milana-erp/releases/20260806_120747`, and
the backend runs `milana-backend:20260806_120747` with two Uvicorn workers.
The 437-file source manifest SHA-256 is
`fde477e93960079c574eff566125976371a234a7c0dc14081f48487a224b1749`;
the frontend build ID is `d1x3RPshEH4ycZIMuC2pi`. Alembic remains at
`0080_piecework_assignments`; no migration was required. Before cutover,
PostgreSQL was backed up to
`/opt/milana-erp/shared/backups/pre_branded_fabric_type_override_20260806_120747.dump`
(26,122,669 bytes; SHA-256
`bf26677604521172a1dd34c5f731fc55a8c55708cede2c7dcc8ab5006cda32eb`;
957 restore objects). The restore-list SHA-256 is
`e683ae055a7f1dd2a851c3a0c6df2c6d08d207eef2976a30845f5aeb4400ebbe`.
Release/image `20260806_115255` is the immediate rollback. The remote frontend
dependency audit reports six inherited findings (one moderate, five high).

## Warehouse Receiving Queue and Shipment Order Table Deployed

On 2026-08-06, production release `20260806_115255` deployed a durable
Warehouse Scan Package queue and a picture-backed Shipment order selector.
Scanning a packed package now records a server-side `queued_storage` event, so
the queue survives navigation and browser reloads. A second scan of the same
waiting package is rejected under a package-row lock. Manual removal records
`removed_storage_queue`; successful storage receipt records the existing
`received_storage` event and automatically removes the package from the queue.
The design reuses immutable `package_scan_logs`, so no migration was required.

The Shipment page replaces its sales-order dropdown with a compact table that
shows customer, item-level model pictures, color, size, ordered quantity, ready
quantity, deadline, and status, with an explicit per-order Create and Scan
action. The eligible-orders API returns those item details and image URLs.

At that deployment, both application VMs pointed to
`/opt/milana-erp/releases/20260806_115255`, and the backend ran
`milana-backend:20260806_115255` with two Uvicorn workers.
The 436-file source manifest SHA-256 is
`9343b95b8182aa34852f14673d17885d7b995d7b341871b86c06c9c56c8af82a`.
Before cutover, PostgreSQL was backed up to
`/opt/milana-erp/shared/backups/pre_warehouse_receiving_shipment_ui_20260806_115255.dump`
(26,104,638 bytes; SHA-256
`b315395f2aa44ffce3114cb1b62be12ede4b66a44edbbeec41b44403305b02b5`;
957 restore objects). The restore-list SHA-256 is
`4d1cd217f056d269ef1b5f6dd8eed8d5ab05e45b94c9ad03758483781bdaffc1`.

Three focused backend tests, five existing receiving/shipment regression tests,
Ruff, ESLint, the frontend contract test, TypeScript, i18n alignment, Python
compilation, both remote builds, all four health checks, two-worker/runtime
checks, and signed-in read-only UI QA passed. Production had zero queued
receipts and zero shipment-eligible sales orders during QA, so no package,
receipt, shipment, or sales-order business data was created or changed. The
signed-in screens showed the durable empty receiving queue and the new Shipment
table with no sales-order dropdown; browser and backend logs were clean.
Release/image `20260806_111903` is the immediate rollback. The remote frontend
dependency audit reports six inherited findings (one moderate, five high).

## Daily Sewing Report Save Fix Deployed

On 2026-08-06, production release `20260806_111903` fixed the Daily Sewing
Report workflow, with SEW-07 as the confirmed affected case. Multi-row daily
entries now use one atomic batch request: either every row is saved or none is.
The request carries an idempotency key, so retrying the same submission cannot
create duplicate rows. The backend now recognizes all seven sectioned sewing
lines (`SEW-01`, `06`, `07`, `09`, `10`, `12`, and `13`). Existing single-row
API clients remain compatible.

Report lists, summaries, Excel, and PDF now resolve the current Sewing Flow
code and name. Thus existing SEW-07 rows whose immutable snapshot still says
`Jalilova` are displayed and exported as `Jalolova Nargiza`; the historical
snapshot and quantities were intentionally not rewritten. A direct production
readback for 2026-08-05 returned three SEW-07 rows under the current name with
the unchanged total of 650 and zero defects.

That release ran on both application VMs as
`milana-backend:20260806_111903` with two Uvicorn workers.
Alembic remains at `0080_piecework_assignments`; no migration was required.
Before cutover, PostgreSQL was backed up to
`/opt/milana-erp/shared/backups/pre_daily_sewing_report_save_fix_20260806_111903.dump`
(26,087,700 bytes; SHA-256
`f2f92576ca73c58905fb0c9429347abe3f18d3a7e967526d2702eb61d2aee786`;
957 restore objects). Ten focused backend tests, the frontend save-contract
test, TypeScript checking with the repository's required import-extension
allowance, both remote builds, production readback, recent-log checks, and all
four local/public health checks passed. Signed-in UI QA confirmed the current
SEW-07 name in the selector; no production report was created or edited for
QA. Release/image `20260806_122034` was its immediate rollback. The remote
frontend dependency audit reports five inherited high-severity findings, and
plain `npm run typecheck` still encounters the unrelated pre-existing
`.ts`-extension configuration error in `scripts/session-logout-contract.test.ts`.

## Production Sewing-Line Names Updated

On 2026-08-06, production release `20260806_122034` changed the seven active
Sewing Flow display names while preserving their stable codes and IDs:

- `SEW-01`: `Bozorova Nargiza`
- `SEW-06`: `Botirova Shaxnoza`
- `SEW-07`: `Jalolova Nargiza`
- `SEW-09`: `Akbarova Dilafruz`
- `SEW-10`: `Maxmudova Nargiza - 1`
- `SEW-12`: `Botirova Muxlisa`
- `SEW-13`: `Maxmudova Nargiza - 2`

The immutable candidate was rebuilt from exact active release
`20260806_065623`; local and GitHub history remained divergent from production.
The candidate differs in exactly three backend files: canonical seed data, the
focused consolidation test, and a guarded dry-run-by-default production rename
script. Its 433-file source manifest SHA-256 is
`54e24ddbd32d7a61d8660ec76b4de646a36e669024dc05ee4d70180b131a4eaf`.
Both application VMs now point to `/opt/milana-erp/releases/20260806_122034`,
and the backend runs `milana-backend:20260806_122034` with two Uvicorn workers.

Before the update, PostgreSQL was backed up to
`/opt/milana-erp/shared/backups/pre_sewing_line_rename_20260806_122034.dump`
(26,082,528 bytes; SHA-256
`761f9f973bebbb4fe2342b17e990effac47b1b0f5156c92750abcc00a3a71958`;
957 restore objects). The guarded serializable transaction changed exactly
seven `sewing_flows.name` values and created audit entries `11516` through
`11522`; that audit segment verified successfully. Stable flow IDs, work-order
links, assignment links, capacities, active states, and historical daily-report
and payroll name snapshots were not changed. Alembic remains at
`0080_piecework_assignments` with no schema migration.

Two focused backend tests, Ruff, compilation, the production dry run, both
remote builds, identical manifests, all four local/public health checks,
two-worker runtime checks, recent-log checks, and signed-in production UI QA
passed. The Sewing Flows page showed all seven requested names with unchanged
loads and no browser-console warnings or errors. Release/image
`20260806_065623` is the immediate rollback. The inherited frontend dependency
audit still reports six findings (one moderate, five high).

## Material Inventory Supplier Editing Deployed

On 2026-08-06, production release `20260806_065623` added the Supplier selector
to the top row of the Material Inventory batch editor, beside Material Name.
The editor loads the exact batch's existing supplier, offers the production
supplier list, and preserves the existing exact-batch update behavior. The
signed-in production check opened an existing material batch read-only,
confirmed the selected supplier and choices, then canceled without saving; no
business data was changed.

The immutable candidate was rebuilt from the exact previously active production
release `20260805_121306`, because the local working tree and GitHub were both
behind/divergent from production. The source manifest contains 432 files and
has SHA-256
`96b3a56c94df03c2246b85735eac9a3cac70c60912ec97537a706f8168b86f9a`.
At that deployment, both application VMs pointed `/opt/milana-erp/current` to
`/opt/milana-erp/releases/20260806_065623`; the backend ran image
`milana-backend:20260806_065623` with two Uvicorn workers. Alembic remains at
`0080_piecework_assignments`; this release contained no migration or database
schema change.

The pre-deployment PostgreSQL custom backup is
`/opt/milana-erp/shared/backups/pre_inventory_supplier_edit_20260806_065623.dump`
(26,082,524 bytes; SHA-256
`b5941be81e0d52f332cab614da4832e825a437ebab3b75e8ebb951cb28ae0d43`).
At that time, release `20260805_121306` and its backend image were retained as
the immediate rollback. Frontend build, strict TypeScript, focused lint, i18n parity, the
supplier-edit contract, and the focused backend exact-batch test passed. All
four local/public health checks returned HTTP 200, the frontend service was
active, both release manifests matched, and recent backend logs contained no
5xx, traceback, or critical entry. Inherited validation debt remains: npm audit
reported six dependency findings (one moderate, five high), while the full
backend suite had six unrelated failures and Ruff reported two pre-existing
catalog forward-reference warnings; the changed path's focused checks passed.

## Production Data Correction: Batch 0062-02 Returned to Bundle Inventory

On 2026-08-04, the six bundles in extra batch `0062-02` for production order
`PO-2026-000058` were returned from Milana Sewing to Cutting Bundle Inventory
after the user confirmed they had been received at Sewing by mistake. The
legitimate extra batch and Cutting evidence were preserved. All six bundles,
totaling 600 pieces, moved from `received_sewing` / `MIL` back to `created` /
`CUT`, while their intended next department and sewing factory remain `MIL`.
The aggregate Sewing received quantity was corrected from 1,200 to 600; the
correctly received first batch and its assignment were not changed.

The correction was guarded by checks confirming batch `0062-02` had no Sewing
assignment, Sewing record, piecework assignment, package, or packaging record.
The mistaken receive scans remain in history, followed by six explicit
`returned_to_inventory` reversal scans. Audit log `#11242` records the old and
new states, and its hash-chain tail verifies successfully. The verified
pre-correction PostgreSQL backup is
`/opt/milana-erp/shared/backups/pre_return_batch_0062_02_to_inventory_20260804_104618.dump`
(26,044,441 bytes; 957 restore objects; SHA-256
`03e1f7aa6800e7e003133db6aa254fbda57860172f53368453b50cd572a2a29f`;
restore-list SHA-256
`8b3182a735884a759835b52d31eefb45671b6e060f09e3dcfecf383e3e1b3201`).
This was a data-only correction; the active application release remains
`20260804_034454`.

## Production Data Correction: Batch 0020-02

On 2026-08-04, production batch `0020-02` in production order
`PO-2026-000017` was corrected before packaging. Its sewing record had
incorrectly reported 272 usable and 43 defective pieces from 315 input. The
confirmed quantities are 260 usable and 55 defective. The guarded transaction
updated the sewing record, aggregate sewing work order, completed replacement
request, and sewing-defect waste evidence by the same 12-piece difference.
Packaging now calculates 260 remaining, zero replacement pending, and no
package or packaging record was changed or created. Audit log `#11205` records
the old and new values, and its hash-chain tail verifies successfully.

The verified pre-correction PostgreSQL backup is
`/opt/milana-erp/shared/backups/pre_batch_0020_02_quantity_correction_20260804_054421.dump`
(26,030,201 bytes; 957 restore objects; SHA-256
`efc587c546c1ddba3c729622c01f16b91490157b8c8634e0196f84e6ae1694d5`;
restore-list SHA-256
`e7d835a37289e2c277b85e090b68a8ecce8022e7cb22eac2ab68c8305e171a0f`).
This was a data-only correction; the active application release remains
`20260804_034454`.

## Package Labels (Deployed)

Release `20260804_034454` redesigns the printable package sticker to resemble
the factory's former landscape package label while keeping the ERP QR payload.
Each sticker is 140 x 95 mm, and the sheet endpoint lays out four labels in a
2 x 2 grid on one A4 landscape page with print-safe margins and cut gaps. The
label automatically shows the client, order, model, article, color, product,
exact material picture, fabric/composition, batch allocation, size breakdown,
weight, and quantity. Single-label and sheet printing use the same escaped
server-rendered card, so database text cannot inject label HTML.

The release was rebuilt from exact active release `20260804_032115` and changes
exactly the package-label route and its production-flow regression test; it
adds no migration or business-data change. Both application VMs serve the same
445-file manifest with SHA-256
`e6624a4391ab6ce155905b4c89e5f3d219b027735ee14c8fd04a9bfd3dbc297c`.
The deterministic release archive SHA-256 is
`631ca720c563f97dd4b2d2f76f73ff3fdd954e5f532ee29121fb782f6e4bd9ed`.
The verified PostgreSQL backup is
`/opt/milana-erp/shared/backups/pre_package_label_20260804_034454.dump`
(26,028,380 bytes; 957 restore objects; SHA-256
`1e89fc581d581265557541479a76025fc0d83e341cf417a8ed4c1b2ffe007ecb`;
restore-list SHA-256
`e3e5cd4580f7a865cdfeff59efe3f0c327f71a0af5559f596ac2a63f6e9b0009`).
Focused Ruff, all 383 backend tests, the production frontend build, Alembic
validation, all four required health checks, two-worker/runtime/log checks,
and a signed-in read-only Packages-page check passed. Production has zero
package rows, so verification created no preview package or other business
record. Release `20260804_034454` is now retained as the rollback for
`20260804_053848`; `20260804_032115` also remains intact. Its authoritative source is the
immutable release folder and
`.codex-work/package-label-deploy-20260804_034454/candidate`.

## Piecework Payroll (Deployed)

### Multiple-process assignment (deployed)

Release `20260804_053848` lets a supervisor choose one or more sewing processes
and assign the same employee, size, and quantity to all selected processes in
one action. The quantity applies independently to every selected process; it
is not divided between them. The API validates every selection first and
commits the assignments as one transaction, so an invalid or over-allocated
process creates no partial assignments. The original single-assignment API
remains compatible.

The release was rebuilt from exact former live release `20260804_034454` and
changes exactly five source/test files; it adds no migration or business-data
change. Both application VMs serve the same 445-file manifest with SHA-256
`47d8f19154277756a1d751f98f67119d87cb2109e6b241fbc94fa498956414bf`.
The deterministic release archive is 1,185,181 bytes with SHA-256
`08180cd5ae7b213a8a79357d638bb5b1fe92fd69162a680e0066c0b04299bc6a`.
The verified PostgreSQL backup is
`/opt/milana-erp/shared/backups/pre_piecework_multi_process_20260804_053848.dump`
(26,030,200 bytes; 957 restore objects; SHA-256
`9385351d2c4b199b9745bd642593731a0dcd7be4a4352c3dc1e877d65bb33fc2`;
restore-list SHA-256
`cc902b3dbeaa35ecc389f91918b00b0b266aced2115bbb62cb78d169b90429eb`).

All 384 backend tests, focused Ruff, translation parity, TypeScript, targeted
ESLint, local and production frontend builds, Alembic validation, all four
required health checks, two-worker/runtime/log checks, connection-headroom
checks, and signed-in read-only production QA passed. QA selected `Front body
sewing` and `Back body sewing` together, showed `2 ta ish tanlandi`, and showed
the per-process quantity wording and bulk-submit label without submitting the
form; the browser console remained clean. The deployment created no business
record: zero demo identifiers remain, with four existing shifts, zero
assignments, and zero acceptances. Production is on release `20260804_053848`
and migration `0080_piecework_assignments`; rollback release
`20260804_034454` remains intact. The authoritative deployed source is the
immutable release folder and
`.codex-work/piecework-multi-process-20260804/candidate`. The production npm
install still reports three moderate dependency-audit findings that predate
this five-file change.

Release `20260804_032115` adds a clearly labeled model picture and exact
variant picture below the selected order on `/payroll/piecework`. The API uses
the same model-image and variant-catalog resolution rules as Production Orders,
eager-loads the related images/BOM data to avoid per-order query waterfalls,
and returns neutral `No picture` placeholders when an image is unavailable.
The release was rebuilt from exact active release `20260803_125716` and changes
exactly five source/test files; it adds no schema or business-data change.

Both application VMs serve the same 445-file manifest with SHA-256
`d7481e71d7c4bd10c07958dfe25a08bd13d18e23ce1f1720c2225623dcf293be`.
The release archive SHA-256 is
`de0c197d9bb679b66842622feac01274f3c038b26bed8025f40441f19fbb964e`.
The verified PostgreSQL backup is
`/opt/milana-erp/shared/backups/pre_piecework_payroll_20260804_032115.dump`
(26,028,212 bytes; 957 restore objects; SHA-256
`661ecc8fd0718c6d5c353565f6f0df05d5c7994dc9da09a1e82b3152b411eb2d`;
restore-list SHA-256
`27370d7f0e270eb77d0a86b2e27e000db67e965e46c58e63bd05a0f5b528e12d`).
Five focused backend tests, translation parity, TypeScript, targeted ESLint,
local and production frontend builds, Alembic validation, all four required
health checks, runtime worker/log checks, and a signed-in read-only production
check passed. On `SEW-09` / `SO-2026-000062`, both the model image and exact
variant image loaded successfully with no browser-console errors. Deployment
created or changed no production business rows; zero demo identifiers remain,
and piecework counts remained one existing shift, zero assignments, and zero
acceptances. The active release is `20260804_032115`; rollback release
`20260803_125716` remains intact. The authoritative deployed source is the
immutable release folder and
`.codex-work/piecework-pictures-20260804/candidate`.

Release `20260803_125716` deploys the sewing piecework workspace at
`/payroll/piecework`. It was rebuilt from the exact former live release
`20260803_112751`, not from the divergent dirty local tree. Migration
`0080_piecework_assignments` follows production head `0079` and adds shifts,
assignments, and an append-preserving acceptance journal. Supervisors assign
approved model operations by production order, sewing flow, size, optional
batch, employee, and quantity. The server snapshots the approved model rate,
caps work by the order and flow plan, rejects client-supplied pay amounts, and
creates existing `PayrollRecord` ledger rows only for accepted good pieces.
Defects remain traceable but unpaid; reversals preserve history, require a
reason, void the ledger row, and are blocked after shift or payroll-period
finalization. Acceptance requests are idempotent, and payroll period status
jumps or record changes in finalized periods are blocked.

The production UI uses large guided `Give work` and `Receive finished work`
steps, hides technical codes and history by default, supports English, Russian,
and Uzbek, and requires `payroll.manage`. The local `DEMO-PW`, `PW-DEMO-001`,
`PO-PW-DEMO-001`, three `LOCAL DEMO` employees, two assignments, one shift,
two batches, and three size rows were deleted before deployment. Production
verification found zero demo identifiers and zero piecework business rows; no
shift, assignment, acceptance, payroll row, order, model, employee, or other
production business record was created during deployment or QA.

Both application VMs serve the same 445-file manifest with SHA-256
`a0ec448aca3bca36d040da061aa669639d62bd89b5926d0c37fa67140637ca79`.
The release archive SHA-256 is
`9a0bc34d8518178f2e327eac4bfbf63025d62656bf7fd62cd0775432ae068a85`.
The verified PostgreSQL backup is
`/opt/milana-erp/shared/backups/pre_piecework_payroll_20260803_125716.dump`
(26,003,501 bytes; 902 restore objects; SHA-256
`4c5e2b075cd37c7204581d3c48a1467a0931ef46354c0d1f08e15322f4af6d95`;
restore-list SHA-256
`46e232b12a32315e29b892a43b6e71c94d5d1b4b901e1345ff48c88d857b75e6`).
All 382 backend tests, focused Ruff, TypeScript, targeted ESLint, the production
frontend build, Alembic validation, all four required health checks, runtime
worker/log checks, and signed-in read-only UI verification passed. This release
is now retained as the rollback for `20260804_032115`.
The repository root remains a divergent dirty snapshot whose local Alembic
state still uses the former pilot revision `0075_piecework_assignments`; do not
deploy it directly. The authoritative deployed source is the immutable release
folder and `.codex-work/piecework-pictures-20260804/candidate`.

## Recent Production Change

Release `20260803_112751` changes the Sewing defect-reason input from a
single-choice field to four independent checkboxes, allowing one sewing
record to retain multiple defect reasons. Selected reasons are serialized in
a stable canonical order into the existing `defect_reason` audit field,
remain attached to replacement requests, and appear as translated labels on
Cutting and Sewing replacement cards. Printing and Daily Sewing Report inputs
are unchanged. The release was built from exact live release
`20260803_102654`, changes seven source files, adds no migration, and changes
no production business rows. A verified custom PostgreSQL backup was saved as
`/opt/milana-erp/shared/backups/pre_sewing_multiple_defects_20260803_112751.dump`
(902 restore objects). Both application VMs serve the same 436-file manifest,
all four required health checks passed, the active release is
`20260803_112751`, and the rollback release is `20260803_102654`.

Release `20260803_102654` adds an explicit, audited Sewing action to complete
an order with final defects when replacement material is unavailable. Sewing
may accept only the replacement balance that Cutting has not recreated;
replacement pieces already cut must still be sewn. Accepted defects remain in
the sewing and waste evidence, store the accepting user, time, and
`insufficient_material` reason, leave the good-output quantity unchanged, and
reduce the downstream Packaging and Storage completion target without
pretending defective pieces are good output. The corresponding Cutting inbox
work disappears and a Cutting work order reopened only for that replacement
returns to completed. Migration `0079_sewing_accepted_defects` adds the
accepted-defect audit fields and database constraints. The release was
rebased from exact live release `20260803_095057`, preserving its unrelated
audit-integrity, model-list performance, and release-cleanup changes. A
verified custom PostgreSQL backup was saved as
`/opt/milana-erp/shared/backups/pre_sewing_complete_with_defects_20260803_102654.dump`
(901 restore objects). No production business rows were changed during
deployment. Both application VMs serve the same 434-file manifest, all four
required health checks passed, and the active release is `20260803_102654`.

On 2026-08-03, production order `PO-2026-000095` (sales order
`SO-2026-000095`) was corrected while it was still in planning. Twelve
mistaken duplicate size rows were consolidated into sizes `46`, `48`, `50`,
`52`, `54`, and `56`, each with planned quantity 100; the order total remains
600. All four work orders were still waiting with zero actual quantities, and
there were no cutting, bundle, sewing, or packaging records. The supported
production-breakdown service recorded audit log `#11110`. A verified
custom-format backup was saved as
`/opt/milana-erp/shared/backups/pre_po95_size_correction_20260803_132400.dump`
(901 restore objects). No release or schema changed in that data-only
correction; the active release at that time was `20260803_065920`.

Release `20260803_065920` restores the missing Modeling-scoped
`GET /api/models/bom-items` endpoint required by the model Fabric &
Accessories editor. The live frontend had retained this request while the
backend route was absent, causing FastAPI to parse `bom-items` as the dynamic
integer model ID and return HTTP 422; the editor consequently showed No
matches. The endpoint returns only active fabric, semi-finished, accessory,
and packaging master items to users with `modeling.bom`, `modeling.models`, or
global permission. General Inventory access remains protected. The release
changes exactly the catalog route and its focused permission regression test;
it changes no schema or business data.

Release `20260803_061129` restores compact pictures to every stock-batch row
in the Branded Stock Orders Fabric selector. Each result uses only that exact
batch's `image_url`; batches without a picture show a neutral placeholder.
The shared searchable selector renders pictures only when the calling page
explicitly supplies the image field, so other selectors keep their previous
layout. The release was rebuilt from exact active release `20260801_130525`
and changes exactly four frontend source files: the Planning page, the shared
searchable selector, `package.json`, and a focused two-test regression file.
It changes no schema or existing inventory/production data.

Release `20260801_130525` makes the Daily Sewing Report Line entry date
read-only while keeping it visible and fixed to the current local date. The
Download report From date and To date inputs remain editable. Deployment
failed closed when production was found to have advanced from
`20260801_124221` to `20260801_124840`; the change was then rebuilt and
retested on the exact newer live source, preserving its dependency, finance
migration, and Daily Sewing line behavior. The final release changes exactly
the Daily Sewing Report page plus its focused contract test. It adds no schema
or business-data change.

Release `20260801_124221` replaces the standalone Binding kg panel in Cutting
with one compact input aligned in the same five-column desktop row as material
kg/layer, rolls, Nastilchi, and cut pieces. The Add line and Binding Remove
actions are gone. The field sums the latest Cutting Passport total and other
Beyka kg values into one compatibility quantity and updates whenever the
passport refresh returns changed data; passport polling remains every 15
seconds and on window focus. The release was rebuilt from exact active release
`20260801_123041` and changes exactly the Cutting page plus its focused
contract test. It changes no schema or business data.

Release `20260801_123041` removes the Beyka material/stock-batch chooser from
the Cutting execution form while retaining one or more Beyka kilogram fields,
including Cutting Passport autofill. Cutting now persists the summed
`cutting_records.beika_kg` compatibility value without sending
`beika_materials`, selecting a specific Beyka batch, or deducting exact Beyka
inventory. The backend schema, historical exact-batch usage records, and API
support remain available for the future department-specific form. The release
was rebuilt from exact active release `20260801_112744` and changes exactly
the Cutting page plus its focused contract test. It changes no schema or
business data.

Release `20260801_112744` automatically fills the Cutting execution form from
the latest Cutting Passport for the same production order, preferring a
passport whose lot number matches the selected material batch. It refreshes
every 15 seconds and on window focus. Actual primary-material usage is derived
as layer kg x total layers + scrap, with issued kg as the fallback; material
kg/layer, rolls, Nastilchi, cut pieces, waste, Beyka quantities, and notes are
also filled. Exact Beyka stock batches still require explicit operator
selection, and fields manually edited in Cutting are not overwritten by a
passport refresh. The release was rebased onto exact active release
`20260801_111815` and changes exactly four frontend files. It changes no schema
or business data.

Release `20260801_111815` replaces the native ERP order/model select in the
New Cutting Passport form with the application's accessible searchable
combobox. Users can type a production or sales order number, model code, model
name, or internal order ID and select with the mouse or Arrow keys plus Enter.
Selection still uses the existing callback, so order/model identity, Qolip,
image, material, quantity, and size defaults continue to auto-fill. The
release changes only
`frontend/src/app/(app)/cutting-passports/page.tsx`; it changes no schema or
business data.

Release `20260801_103647` fixes the Cutting Passport HTTP 500 that occurred
when a production order's complete size range exceeded the database's former
32-character limit. The exact failing value,
`2XL-52, 3XL-54, L-48, M-46, S-44, XL-50`, is 39 characters. Migration
`0077_cutting_passport_size_range` enlarges `cutting_passports.size_range` to
`varchar(255)`; the ORM now matches that limit and the create API validates
inputs at 255 characters, returning HTTP 422 for longer values instead of
allowing a database error. The release was rebased onto exact active release
`20260801_103034`, preserving its cutting-sheet layout and all earlier changes.
No Cutting Passport or other business record was created during verification;
only the column definition and Alembic version changed.

Release `20260801_103034` enlarges the model picture on the A4 landscape
cutting production sheet by approximately 1.25x while preserving its aspect
ratio and keeping the complete sheet on one page. The top identity section is
84 mm high, the model-photo area is 75 mm high, the process table is 70 mm
high, and the accessory rows are compacted without removing any of the ten
required material/accessory fields. The release was rebased onto exact active
release `20260801_102628`, so its legacy Qolip fallback remains intact. It
changes only `backend/app/services/cutting_sheet.py`; no schema or business
data was changed.

Release `20260801_102628` corrects the legacy Old ERP model-field mapping.
For migrated models, the value previously displayed as `Original name` is the
business `Qolip No`; it is now stored in canonical `general.qolip_no` and
`general.mold_no` fields while the original Old ERP provenance remains intact.
The duplicate/misleading `Original name` row is no longer displayed, and both
cutting-passport defaults and production cutting sheets automatically resolve
Qolip No from the model. A fail-closed, audited repair updated 6,440 model JSON
rows; one model was already correct, one conflicting Qolip value was corrected,
and the final verification found all 6,441 migrated models correct with zero
missing sources or pending updates.

Release `20260801_092153` fixes two related production UI workflows. Searching
Models by a variant number now returns the complete model family instead of a
temporary one-variant card, and the family card prioritizes the base model's
model photo. Signed-in QA for variant `2042` returned the full `ХJ3062` family
with 131 variants and the correct base-model photo. Cutting's existing
`Print cutting sheet` action now shows a batch/cutting-record selector whenever
more than one printable sheet exists; existing order `SO-2026-000017` exposed
Batch 1 / `CUT-12` and Batch 2 / `CUT-13`. The deployment changed no schema,
model, variant, cutting record, bundle, stock, order, or other business data.

Release `20260801_065032` adds one traceability QR to every batched
cutting production sheet. The QR encodes the authenticated ERP URL for the
exact `production_batch_id`; scanning it opens the existing Traceability page
in batch mode. The batch view strictly scopes cutting, bundles, printing,
sewing, packaging, package allocation, warehouse, and shipment evidence to
that production batch and reports planned, cut, usable, defective, actually
sewn, sewing-passed, packed, warehouse-received, and shipped quantities with
stage timestamps. Main-fabric consumption is exact to the cutting record and
stock batch. Accessory issues are shown honestly as production-order-level
usage because the current schema does not allocate accessories between
production batches. The deployment changed no schema or business data.

Release `20260801_064726` makes the Models editor Variants table show the
newest-created variant first. The frontend copies the API result and sorts by
descending model ID, which is the durable creation identity, so a newly added
automatic or manually numbered variant appears at the top without changing
backend ordering for other consumers. No schema, model, variant, stock, or
other business data was created or changed.

Release `20260801_050103` fixes the Models editor Add Variant failure introduced
by a frontend/backend contract mismatch. The active frontend requests
`GET /api/models/{id}/variants/next-number` and omits an unchanged automatic
number during create, while release `20260731_130330` lacked the preview route
and still required the number. The backend now restores the preview endpoint,
atomically reserves persistent `V-` numbers beginning at `V-5648` on create,
keeps manual numbers supported, and inherits the parent model's fabric when the
frontend does not send a separate fabric choice. No schema, model, variant,
stock, or other business data was created or changed.

Release `20260731_124817` enables the existing multi-section daily sewing
report form, including the `Add section` button and up to 20 section rows, for
lines `SEW-10`, `SEW-12`, and `SEW-13`. It reuses the same workflow already
enabled for lines 1, 6, 7, and 9. The change is frontend-only; no schema,
report, model, stock, or other business data was created or changed.

Release `20260731_120812` restores fabric and accessory choices for Modeling
users in the model BOM editor. The editor now reads a dedicated,
Modeling-scoped `/api/models/bom-items` endpoint instead of the protected
general Inventory endpoint. It returns only active fabric, semi-finished,
accessory, and packaging master items; Modeling users still receive HTTP 403
from `/api/inventory/items`. No schema, permission assignment, model, BOM row,
stock, or other business data was created or changed.

Release `20260731_114117` keeps the next model-variant number auto-filled while
making the field editable during variant creation. If the suggestion is left
unchanged, the frontend omits the number so the backend reserves the next
automatic number atomically; if the user changes it, the exact manual value is
sent and the existing duplicate protection applies. The change is
frontend-only and preserves release `20260731_111653`'s retry-safe combined
variant/photo workflow. No schema, model, variant, stock, or other business
data was created or changed.

Release `20260731_110458` adds the exact material-batch picture to every result
in the Fabric Batch selector of the Branded Stock add-production form. Each
option uses that stock batch's own `image_url` as a compact thumbnail and shows
a neutral image placeholder only when the exact batch has no picture. The
change is frontend-only; no schema, stock, order, or other business data was
created or changed.

The immediately preceding release, `20260731_110132`, deploys exact Beyka
inventory consumption in Cutting.
Cutting can add one or more Beyka rows, select the exact positive
material-inventory batch for each row, and enter kg beside it. The searchable
batch list now shows the exact stock-batch picture as a compact thumbnail and
uses a neutral placeholder only when that batch has no picture.

Saving a cutting record deducts all Beyka rows in the same atomic transaction
as main-fabric consumption and bundle creation, persists their batch links,
keeps `cutting_records.beika_kg` as the calculated compatibility total for
existing sheets, protects used batches from unsafe edits/deletion, and
refreshes inventory balances in the UI. A retry key prevents a timed-out save
from creating duplicate cutting records, bundles, or stock movements.
Migration `0076_cutting_beika_usage` added
`cutting_beika_material_usages`. Existing scalar-only historical Beyka values
were not assigned to invented batches.

## Technical Shape

- Backend: FastAPI, SQLAlchemy 2, Alembic, PostgreSQL, Pydantic, JWT/cookie
  authentication.
- Frontend: Next.js App Router, React, TypeScript, TailwindCSS.
- Local development: Docker Compose, frontend on port 3000 and backend on port
  8000.
- Production domain: `https://erp.milanapremium.uz`.
- Production topology:
  - PostgreSQL VM: `172.16.10.3`
  - FastAPI backend VM: `172.16.10.4`
  - Next.js frontend VM: `172.16.10.5`
  - Nginx Proxy Manager routes the public domain and forwards `/api`,
    `/storage`, and `/health` to the backend.
- Production releases live under `/opt/milana-erp/releases/<release_id>`.
- `/opt/milana-erp/current` points to the active release on both application
  VMs.
- Backend uses release-tagged Docker images and publishes container port
  `10000` as VM port `8000`.
- On the backend VM, Docker bind-mounts host `/app/storage` at container
  `/app/storage`; inventory/model images are physically under
  `/app/storage/model_files` and are served through `/storage/model-files/...`.
- Production data and uploaded files must stay outside release folders.
- `DEPLOYMENT.md` is the only authoritative deployment procedure. Old Vercel,
  Render, and Hugging Face deployment notes are historical.

## Current-State Warning

On 2026-07-23, a deployment was explicitly rolled back to release
`20260723_065753`. The abandoned release `20260723_132410`, its backend image,
staging archive, and test stock data were removed. Public health checks passed
after rollback.

As of the final 2026-08-03 verification, both application VMs point to active
release `20260803_065920`, and the backend runs image
`milana-backend:20260803_065920` with image ID
`sha256:e15b3cb0d30e9f53e22687b6d123a748d42c8ba85e9ea4c06935dce2a222be7c`.
Release/image `20260803_061129` is the immediate rollback. The active release
was built from that exact production source and differs in exactly two backend
files: the catalog route and its focused regression test.

Both VMs verified the deterministic 428-file manifest
`ff26c2475478c00c40f270eb01aabf3b533227a7346e1f12da9c28b3111b4a19`;
the release archive SHA-256 is
`4fae15b8f6a12a4b80e91dbd52a6dd8b32d77c46cd086d2e50780e46feed4c08`.
The production frontend build ID is `ktmbGIu9_TVWmXY10Z4V7`. The verified
pre-cutover backup is
`/opt/milana-erp/shared/backups/pre_model_bom_items_hotfix_20260803_065920.dump`
(25,959,168 bytes; 901 restore objects; SHA-256
`4815d6f4770f91e747415ac2f6d8816c81d3b1c1e8eac322b7084204e713cde8`).
Its restore-list SHA-256 is
`eb987492467dfaa606d77f6dfde4a0251db0ae61afbb29c3d5341e942c98b8aa`.

All 28 catalog tests, the focused Modeling permission test, Ruff, the
zero-vulnerability npm audit, the production 63-route frontend build, and
deterministic archive/manifest verification passed. Alembic remains at
`0078_finance_external_ids (head)`. All four required internal/public
endpoints returned HTTP 200; one Uvicorn parent plus two workers were healthy,
PostgreSQL used 13/100 connections at final verification, and fresh
post-cutover logs were clean. Signed-in production QA opened model
`PJ1149-4089`, expanded its Fabric selector, and confirmed 53 choices. The
backend logged HTTP 200 for `/api/models/bom-items`, and the browser console
had no errors. No form was saved and no model, BOM, inventory, or other
business data changed. Empty branded planning order `0014` from the preceding
fabric-thumbnail QA remains untouched because there is no supported deletion
action and direct database deletion was not authorized.

The preceding release's independent read-only headroom probe had a
shell-quoting error and
emitted a diagnostic traceback; its corrected rerun passed and did not affect
the service. Its signed-in
read-only QA opened existing Cutting Passport `8341` through work order 234
and confirmed automatic values of 283 kg primary material, 2.8 kg/layer, 13
rolls, Nastilchi `мохи`, 600 pieces, and 31.13 kg waste. A temporary client-side
roll edit remained intact through the 15-second passport refresh. The form was
closed without submission and no business row was created or changed. The
active source inherits six high-severity frontend dependency advisories and
one pre-existing Hooks lint warning in the Cutting page; neither unrelated
issue was changed in this narrow release.

The next rollback release `20260801_111815` runs image
`milana-backend:20260801_111815` with unchanged image ID
`sha256:396a37cf80391a3148dcc0c4225b24fe0f3d166d0caaad6fd6d3ee1d10bcdfbf`.
Release/image `20260801_103647` is its immediate rollback. It
was built from that exact production source and differs in exactly one file,
`frontend/src/app/(app)/cutting-passports/page.tsx`.

Both VMs verified the deterministic 409-file manifest
`a163e5cab7923ea43330ea5241665a17cd6aa053859ad1f5c337d14c98955f3a`;
the release archive SHA-256 is
`2a379de83156895d98442ada2a36f243128494e648cbb46a7b242b0e326ab086`.
The production frontend build ID is `phG3TeExmF63pbqF98-Qc`. The verified
pre-cutover backup is
`/opt/milana-erp/shared/backups/pre_cutting_passport_searchable_order_20260801_111815.dump`
(25,937,958 bytes; 899 restore objects; SHA-256
`580cb41879438d5598d1875b17f918ca7084576c21225b868323e45c520c4ab1`).
Its restore-list SHA-256 is
`91d0019c4f017599cc4a2166d7513384db31cedc6501040f1e16ba84a3eb4c49`.

TypeScript, targeted ESLint, local and production 63-route frontend builds,
and deterministic archive/manifest verification passed. Alembic remains at
`0077_cutting_passport_size_range (head)`. All four required internal/public
endpoints returned HTTP 200; one Uvicorn parent plus two workers were healthy,
the container had zero restarts, PostgreSQL used 20/100 connections at final
verification, and post-cutover logs contained no backend 5xx, traceback, or
application errors. Signed-in read-only QA searched existing order `000074`,
selected `SO-2026-000074 · ХJ3062-3472` with Enter, and confirmed model,
variant, order, Qolip, image, quantity, material, and size auto-fill. Typing
model variant `2042` returned `SO-2026-000073 · ХJ3062-2042`. The modal was
closed without submission, browser error logs were empty, and no business row
was created or changed. The active source inherits six high-severity frontend
dependency advisories; this unrelated issue was not changed in the narrow
release.

Immediately before this deployment, both application VMs pointed to active
release `20260801_103647`, and the backend ran image
`milana-backend:20260801_103647` with image ID
`sha256:396a37cf80391a3148dcc0c4225b24fe0f3d166d0caaad6fd6d3ee1d10bcdfbf`.
Release/image `20260801_103034` was its immediate rollback. Release
`20260801_103647` was built from that exact production source and differed in
exactly four files:
the Cutting Passport ORM and request schema, the focused production-flow
regression, and migration `0077_cutting_passport_size_range`.

Both VMs verified the deterministic 409-file manifest
`5a75d788a5895776507b288cfc364b3e83c4e97497f433c2c452566671470fe2`;
the release archive SHA-256 is
`c01dd06819e3a1645d7c519f7fab69855e6ac8a3baf4f39a653f3ccbfffd24bf`.
The production frontend build ID is `ScuV6PlNa3xd7uHkuBVic`. The verified
pre-migration backup is
`/opt/milana-erp/shared/backups/pre_cutting_passport_size_range_20260801_103647.dump`
(25,910,992 bytes; 899 restore objects; SHA-256
`36677f7f66116e4730b47fe913b8046aa8a4022ab5bfdcd3aa829125db53805e`).
Its restore-list SHA-256 is
`b768c60b7b240c1c0857ee7d3821fb086d8bc40b5123cb693d232bde70034001`.

All 68 production-flow regressions plus three focused Cutting Passport tests,
Ruff, Alembic head/offline SQL checks, the 63-route production frontend build,
and deterministic archive/manifest verification passed. Production reports
`cutting_passports.size_range` as `varchar(255)`, the create schema reports a
255-character maximum, and Alembic is at
`0077_cutting_passport_size_range (head)`. All four required internal/public
endpoints returned HTTP 200; one Uvicorn parent plus two workers were healthy,
the container had zero restarts, PostgreSQL used 21/100 connections at final
verification, and post-cutover logs contained no backend 5xx, traceback, or
application errors. No business row was inserted or updated. The active source
inherits six high-severity frontend dependency advisories; this unrelated
issue was not changed in the narrow release.

Immediately before release `20260801_103647`, both application VMs pointed to
release
`20260801_103034`, and the backend ran image
`milana-backend:20260801_103034` with image ID
`sha256:b3d78d4d00ec6966406950da13c8ed51f3950eac22c849ae52e6264f22fec3af`.
Release/image `20260801_102628` was its immediate rollback. Release
`20260801_103034` was built from that exact production source and differed in
exactly one file, `backend/app/services/cutting_sheet.py`; the preceding
release's Qolip logic was preserved byte for byte outside the requested layout
adjustments.

Both VMs verified the deterministic 408-file manifest
`f71364261087dab51c81760ed118aac7356c8300d3e01d00699c6128b362e08d`;
the release archive SHA-256 is
`a445ae112260cd34e2919eac7f3fd62b898d2f257422a238a64f8b65aa3decc1`.
The production frontend build ID is `HmVKyH3TwH2k06kCn-E4_`. The verified
pre-cutover backup is
`/opt/milana-erp/shared/backups/pre_cutting_sheet_large_model_20260801_103034.dump`
(25,910,990 bytes; 899 restore objects; SHA-256
`594d755437397cd0887309daf863ab12ca26cae46b4aa8e6ea3537ec9a8cb6e0`).
Its restore-list SHA-256 is
`0a67b6e74314976c1ce8c1de64bf788525a87ba34c73e9a5d440aec63d6e33a8`.

Seven focused cutting-sheet and legacy-Qolip regressions, Ruff, Python
compilation, TypeScript, local and production 63-route frontend builds, and
deterministic archive/manifest verification passed. Alembic remains at
`0076_cutting_beika_usage (head)`. All four required internal/public endpoints
returned HTTP 200; one Uvicorn parent plus two workers were healthy,
PostgreSQL used 15/100 connections, and post-cutover logs were clean.
Signed-in read-only QA opened existing batch `0036-01` (ID 14) and confirmed
its current Sewing stage, requested quantity counters, stage timestamps,
material usage, accessories, and timeline. Existing cutting record 15 rendered
the approved 84/75/70 mm layout, compact 7.4 mm accessory rows, and embedded
batch QR. No form was submitted and no business data was changed. The active
source inherits six high-severity frontend dependency advisories; this
unrelated issue was not changed in the narrow release.

The immediate rollback release `20260801_102628` runs image
`milana-backend:20260801_102628` with image ID
`sha256:162c144139ea04c51ada6e21b21fdc30a2256c769ab56dede9e7d38961c0fba0`.
Release/image `20260801_092153` is its immediate application rollback. That
release was built from that exact production source and differs in six
intended files: a guarded legacy-Qolip parser, repair script and regression
test; cutting-sheet and cutting-passport fallback wiring; and removal of the
misleading Old ERP `Original name` UI row.

Both VMs verified the deterministic 408-file manifest
`bb53cef2db9bd7ee9e021ffaa506242946a2482f6b64ca6dfdc89f84d6ee3499`;
the release archive SHA-256 is
`36b94e1e01f23a0f47a842ec1baad31d25207560ab2156a69cd30dfed86d6305`.
The production frontend build ID is `2_IUALWJTNORIMhjmMvx4`. The verified
pre-repair backup is
`/opt/milana-erp/shared/backups/pre_qolip_original_name_20260801_102628.dump`
(25,655,424 bytes; 899 restore objects; SHA-256
`c558d5094d701fd69cdec8f5f14e72c93d444669d84f8c67089dc0f82a284b3f`).
Its restore-list SHA-256 is
`99285f83da7076d364da0e72718dfb806086500c930e51f2f5cd401672417127`.

The exact pre-write repair plan covered 6,548 total models and 6,441 Old ERP
models: 6,440 updates, one already correct, one conflict, and zero missing
sources, with plan SHA-256
`b091c124ebc369c73674bf32209fe8dd3d696287e2839abf21e09634e586b981`.
The guarded transaction updated all 6,440 planned rows and wrote aggregate
audit action `repair_legacy_qolip`. Its post-check found 6,441 already correct,
zero conflicts, zero missing sources, and zero pending updates. Old ERP
provenance was preserved.

All 127 selected backend regressions, Ruff, TypeScript, targeted ESLint, the
cutting-selector contract, local and production 63-route frontend builds, and
deterministic archive/manifest verification passed. Alembic remains at
`0076_cutting_beika_usage (head)`. All four internal/public endpoints returned
HTTP 200; one Uvicorn parent plus two workers were healthy, PostgreSQL used
14/100 connections, and post-cutover logs had no backend 5xx, traceback, or
application errors. Signed-in read-only QA confirmed model `XJ3044-5532`
(ID 6335) has Qolip `4342` in the Pattern tab and no Old ERP `Original name`
row, while cutting work order 298 automatically shows `Qolip no: 4396` for
model `ХJ3062-3472`. Browser error logs were empty and no form was submitted.
The active source inherits six high-severity frontend dependency advisories;
this unrelated issue was not changed in the narrow release.

Release `20260801_102628`'s immediate rollback, `20260801_092153`, runs backend image ID
`sha256:f3c29857a3b9b370a3d093dae064cf1fdb65ef6a8cd783e1e9517da79bfecd72`.
Its own immediate rollback was release/image `20260801_065032`. Release
`20260801_092153` was built from that exact production source and differs in
exactly five intended files: the catalog grouping route and its regression
test, plus the Cutting page, translation dictionary, and selector contract
check.

Both VMs verified the deterministic 405-file manifest
`a88579ad665a0a2aafa0778e07531ce55c8fe46aa02f37d5f03dae37a6bbd1df`;
the release archive SHA-256 is
`cfae99425f3a8164ec264f726746a47ecf025f86998b8a4c3c3738741ea090ec`.
The production frontend build ID is `VsMCVCbxZX0bOjN3idbiS`. The verified
pre-cutover backup is
`/opt/milana-erp/shared/backups/pre_model_family_search_cutting_selector_20260801_092153.dump`
(25,651,536 bytes; 899 restore objects; SHA-256
`fd6a3a7afe63239d63b4610d4a799be173a43104f8475455cbad10edf2b03e94`).
Its restore-list SHA-256 is
`82681f2c1cb792d80bd84e9db8bb2f77ae96147b277b599e16e6a1c04cb17fbe`.

All 28 catalog regressions, Ruff, Python compilation, the cutting-selector
contract, TypeScript, targeted ESLint, local and production 63-route frontend
builds, and deterministic archive/manifest verification passed. Alembic
remains at `0076_cutting_beika_usage (head)`. All four required
internal/public endpoints returned HTTP 200; one Uvicorn parent plus two
workers were healthy, container restart count was zero, PostgreSQL used
13/100 connections, and post-cutover logs had no backend 5xx, traceback, or
application errors. Signed-in read-only QA confirmed `2042` stays in the full
`ХJ3062` family with the base-model photo and confirmed both existing cutting
sheet choices, including selecting Batch 2 / `CUT-13`. No print action or form
was submitted and no business record was created. The active source inherits
18 pre-existing i18n audit misses and six high-severity frontend dependency
advisories; neither unrelated issue was changed in this narrow release.

Immediately before this deployment, release `20260801_065032` ran backend
image ID
`sha256:fe82a1d7fca48aeeff3506032d26f0144d26288095039cc801e05db4343df9fe`.
It was built from release `20260801_064726`, preserved its newest-first
model-variant change byte for byte, and differed in exactly ten intended files:
five backend feature files, three frontend files, and two focused
regression-test files.

Both VMs verified the deterministic 404-file manifest
`cf1f9ff283c4b4b382b9a28874eadb9723ed8614d8d899b2fc4867e3b2d4573b`;
the release archive SHA-256 is
`0f9497de26874ededdb8635aa14ca442e9c1361498071c0e96fac89a6c976b4c`.
The production frontend build ID is `Z7UDAnP_6N06SeJEuTQsJ`. The verified
pre-cutover backup is
`/opt/milana-erp/shared/backups/pre_variant_newest_first_20260801_065032.dump`
(25,650,490 bytes; 899 restore objects; SHA-256
`840917e01569f821c3d364ccd4a9d499729908b78c767c26e9ffa7b79a88904d`).
Its restore-list SHA-256 is
`8e537891d0b3ed536556d45a44e4fe648c04d15d346398d147d98acb3385cb47`.

All 32 focused backend regressions, Ruff, Python compilation, TypeScript,
targeted ESLint, local and production 63-route frontend builds, and
deterministic archive/manifest verification passed. Alembic remains at
`0076_cutting_beika_usage (head)`. All four required internal/public endpoints
returned HTTP 200; one Uvicorn parent plus two workers were healthy,
PostgreSQL used 18/100 connections, and post-cutover logs had no backend 5xx,
traceback, or application errors. Signed-in read-only QA opened existing batch
`0036-01` (ID 14) and confirmed Sewing as its current process, all requested
quantity counters, stage timestamps, exact material batch `15805` consumption
of 557 kg, and the honest order-scoped accessory notice. Existing cutting
record 15 rendered an embedded PNG QR linked to `/traceability?batch=14`.
Browser error logs were empty, no form was submitted, and no business record
was created. The inherited frontend dependency audit still reports six
high-severity advisories.

Release `20260731_100256` deploys model-number normalization on create and
edit, removes only the separator between a leading letter prefix and first
digit, preserves later variant separators, and makes backend/frontend model
search hyphen-insensitive. The frontend helper supports Latin, Cyrillic, and
mixed letter prefixes. The clean candidate differs from exact active release
`20260731_100201` in exactly four files: catalog routes, model-search
normalization, focused catalog tests, and the shared frontend model-code
helper.

Both VMs verified the deterministic 400-file manifest
`6a5b8d102e0c83294c999654325873d09f07369094f70616f1799ca33552abb5`;
the release archive SHA-256 is
`a7afd37f19de596b1abb5ba09a5cadbed72b4ce5d5588e711c5a48db6e05a8db`.
The production frontend build ID is `994N45QU-JOq_wy5v0th5`; backend image ID
is
`sha256:842dde68cadddc1ceaef60fed58867e42ffc4ea105bdace8b701022525c4bc56`.
The verified pre-cutover backup is
`/opt/milana-erp/shared/backups/pre_model_number_normalization_20260731_100256.dump`
(25,547,889 bytes; 886 restore objects; SHA-256
`8881482d5980bf12fdb4bfcde60587b184aaa2d379824baf2b1333fa969ed9cf`).
Its restore list is
`/opt/milana-erp/shared/backups/pre_single_model_material_variants_20260731_100256.restore.list`
with SHA-256
`7cb97ac9625b1e395ec4b80da97c71c4551696a74e4b2aadcdfc45cf897b46ce`.

All 27 catalog tests, Ruff, TypeScript, targeted ESLint, direct Latin/Cyrillic
frontend behavior checks, local and production 63-route builds, and
deterministic archive verification passed. Alembic remains at
`0075_multi_fabric_cutting (head)`. All four required internal/public
endpoints returned HTTP 200; one Uvicorn parent plus two workers were healthy,
backend and frontend restart counts were zero, recent logs had no 5xx or
traceback errors, and PostgreSQL used 11/100 connections. Signed-in production
QA confirmed normalized `PJ1077`, Cyrillic-prefixed `РJ1102`, and that legacy
search `PJ-1077` returns exactly the single `PJ1077` model group. The new-model
form exposes a prefix selector plus a numeric-only number field. No QA model
was submitted and no business record was created. Browser warning/error logs
were empty. A post-deploy scan still found 6,536 models and zero remaining
prefix-hyphen-digit candidates. The inherited frontend dependency audit still
reports six high-severity advisories; no force-upgrade was included in this
narrow deployment.

On 2026-07-31, production model numbers were normalized so the single hyphen
between a leading letter prefix and the first digit was removed while later
variant separators were preserved. Examples are `PJ-1077` -> `PJ1077` and
`XJ-3044-V-5295` -> `XJ3044-V-5295`. The transaction updated 6,525 of 6,536
model rows and the same 6,525 embedded `details_json.general.model_no` values;
model IDs, row count, links, variants, and later hyphens were unchanged. Exact,
case-insensitive, and planned-result collision checks all returned zero before
the write, and a post-commit scan returned zero remaining matching codes. The
aggregate audit record is `#10479`; the deterministic plan SHA-256 is
`bf90621eb8adeabba019f1c0aeecfb5e6e4236090883d49e49c1e34e4c8a4b61`.

The verified pre-change backup is
`/opt/milana-erp/shared/backups/pre_model_number_hyphen_cleanup_20260731_144715.dump`
(25,855,778 bytes; 886 restore objects; SHA-256
`eccb3d710157aef0c1e8627fdefb96ea1af708c336907ec8b1db6d3baa792900`).
Its restore-list SHA-256 is
`3b5b97ff46f4600b6a576b87e5efb7bf5dd41ef688eab67b6f75101450c75aed`.
Signed-in production QA showed `PJ1077`, `PJ1145`, and `XJ3044`; searching
`XJ3044` returned the expected single 180-variant group and browser console
logs were clean. Internal backend health, internal frontend login, public
health, and public login all returned HTTP 200 after the concurrent rollout;
the backend was at Alembic `0075_multi_fabric_cutting`, with zero container
restarts and no recent startup errors.

The prevention code is now live in release `20260731_100256`; the earlier
local-only warning is resolved.

Release `20260731_091230` fixes base-model creation so a new model does not
create or display an inferred default variant. The create API canonicalizes a
model without explicit variant metadata as a base model and removes blank
`variant_no`/`variantNo` keys. The shared frontend model-code parser treats an
explicit `model_no` with no explicit variant as the complete model number, so
a value such as `TJ-2300` is not incorrectly split into model `TJ` and variant
`2300`. The model form also omits blank variant metadata when saving. Variants
remain empty until the user explicitly uses Add Variant, when the automatic
sequence beginning at `V-5648` applies.

The candidate was rebuilt from exact active release `20260731_065236` and
differs in exactly four files: catalog routes, focused catalog tests, the
shared model-code parser, and the model-detail page. All 26 catalog tests,
Ruff, TypeScript, targeted ESLint, the direct base/variant parser regression,
local and production 63-route frontend builds, deterministic source
verification, and signed-in production QA passed. Live read-only QA opened
base model `Ф-773` and confirmed its complete model number, `Variantlar 0`, an
empty variant table, and the explicit Add Variant action. No form was saved
and no model, variant, stock, order, or other business record was created or
changed.

Both VMs verified the same deterministic 397-file source manifest. The release
archive SHA-256 is
`cbf22de1ca7b1e081125743ac55af165480fb36c788b4e705817d61aff015eae`;
the manifest SHA-256 is
`dea14540f563a2600ad6341f1ef70b68123c77279536283fe008b13b40a4cd4a`.
The production frontend build ID is `Qsz1RHZkS5pAgMjEFGCua`; the backend image
ID is
`sha256:5b0cc2011dd4843d85d0776b500954998dae7ae7a58d8dac2ebb79ea636e16bb`.
The verified pre-cutover backup is
`/opt/milana-erp/shared/backups/pre_base_model_no_default_variant_20260731_091230.dump`
(25,854,099 bytes; mode `0600`; 886 restore objects; SHA-256
`73f28a421369dc31885f7eb100a5bd4a94b577b5be6ae96689c4358d2252e359`).
Its restore-list SHA-256 is
`0c185be5191b7a587dc31df889895a36e727fb4309ae796672207ad9572feacd`.
Alembic remains at `0075_multi_fabric_cutting (head)`. All four required
internal/public endpoints returned HTTP 200. Backend and frontend have zero
restarts and no recent errors; one Uvicorn parent and two workers were
healthy, and PostgreSQL used 14 of 100 connections at final verification time.

Release `20260731_095458` simplifies the Models editor Variants form so it
no longer offers a per-variant material/fabric chooser. New variants inherit
the parent model's first material BOM item automatically; edits normalize the
target variant to that parent item while preserving omitted color and image
data. Legacy clients may still send the same parent item ID or stock-batch ID,
but the API rejects a different item. Imported image-only variants with no BOM
remain editable for identity and image fields as a narrow
backward-compatible exception, but cannot assign material until the parent
model has a BOM material. Variant reads still expose their existing material
fields.

The candidate was rebased from the exact 399-file active source for
`20260731_094258` after a concurrent deployment completed. It changes exactly
five existing files (catalog routes, catalog tests, frontend package scripts,
the model-detail page, and supplemental translations) and adds one focused
frontend contract check. All 26 catalog tests, Ruff/Python compile checks, the
focused frontend contract check, TypeScript typecheck, targeted ESLint, and
the production Next.js build passed. The inherited dependency audit reports
six high-severity findings and remains open dependency-upgrade work.

Both VMs verified the same deterministic 400-file source manifest. The release
archive SHA-256 is
`587968f78ffe4384ca57ae1bf88179c249163fa388ffbe2ca41d902aaac2d254`;
the manifest SHA-256 is
`bd93c2b41ea6ea9f002a8b5e39a7c560d36d57df4feaf8815beb95fa729fe68d`.
The production frontend build ID is `eIl1K6n4P4AlQFoSqr3-l`; the backend image
ID is
`sha256:02c38fcb6efa5f9083e513fb5f099b5c66f6dd0a6280c3eb61e7242b9d7edae8`.
The verified pre-cutover backup is
`/opt/milana-erp/shared/backups/pre_single_model_material_variants_20260731_095458.dump`
(25,547,244 bytes; mode `0600`; 886 restore objects; SHA-256
`93e59678c2763b090a16ef48ad3df8e7b9d61e65c75f4258fe0210d53d59a953`).
Its restore-list SHA-256 is
`33c796ed6bdc19090e7bf8ae95b752c7d8bf46997b9bbe304282ad59ffa01f32`.
Alembic remains at `0075_multi_fabric_cutting (head)`. All four required
internal/public endpoints returned HTTP 200; one Uvicorn parent and two
workers were healthy, recent backend/frontend logs contained no application
errors, and PostgreSQL used 12 of 100 connections.

The first cutover attempt passed all application health checks but rolled back
automatically because the verification script requested an unsupported Docker
process column. Rollback to `20260731_094258` was independently verified with
all four endpoints at HTTP 200. After correcting only that read-only process
check, the second cutover and all runtime checks passed. Signed-in production
QA opened model `PJ1077-5404`, rendered the Add Variant form, confirmed that it
contains variant number, optional material color, and optional image but no
material chooser, then cancelled without submitting. No model, variant, stock,
order, or other business record was created or changed.

Release `20260731_065236` adds backend-authoritative automatic model-variant
numbering. New variants preview and reserve a persistent global sequence
starting at exactly `V-5648`; legacy/imported higher `V-` values do not advance
the new sequence, occupied numbers are skipped, and deleted automatic numbers
are not reused. The Models form shows the next number read-only before
creation, while existing-variant editing and explicit legacy API numbers stay
supported. Production read-only inspection found 234 existing `V-` variants,
including a legacy maximum of `V-17194`, but no occupied values from `V-5648`
through `V-5660`.

The release candidate was rebuilt from exact active release
`20260731_054535` and differs in exactly five files: the numbering service,
catalog schemas, catalog routes, focused catalog tests, and the model-detail
page. All 25 catalog tests, Ruff, TypeScript, targeted ESLint, local and
production 63-route frontend builds, deterministic source verification, and
signed-in production QA passed. Live QA opened an existing model's Variant
form and confirmed exactly one read-only `V-5648` input, then cancelled it.
No model, variant, stock, order, or other business record was created or
changed, and the first sequence value remains available for the first real
new-variant creation.

Both VMs verified the same deterministic 397-file source manifest. The release
archive SHA-256 is
`e9518118bd7d53afdd7857134159d212691197fe02c3d9dc40fbeb813c66cb3b`;
the manifest SHA-256 is
`8268d7cade41f38c5b446d067fd7b3eb9e2a17c00bd5288708c8d322eba22d30`.
The production frontend build ID is `3C3zAZwj4OSSnfu0jhAae`; the backend image
ID is
`sha256:3e7f767fd84ded3bbe0f50a50b2ca0d73fc781a3dda76b7315a1259e7a5482d7`.
The verified pre-cutover backup is
`/opt/milana-erp/shared/backups/pre_auto_variant_numbering_20260731_065236.dump`
(25,853,796 bytes; mode `0600`; 886 restore objects; SHA-256
`5070cf645bc45de077d44eb127fa3496a961a61bc408672bbca5d90bb578ff13`).
Its restore-list SHA-256 is
`1d1b551ea53b58e4aad138e35daa6877382105dbc74806035c07daaed7a22abf`.
Alembic remains at `0075_multi_fabric_cutting (head)`. All four required
internal/public endpoints returned HTTP 200. Backend and frontend have zero
restarts and no recent errors; two Uvicorn workers were healthy, and
PostgreSQL used 10 of 100 connections at final verification time.

Release `20260731_054535` adds garment sizes `66` and `68` to every bounded
size selector. A shared `GARMENT_SIZE_OPTIONS` list now supplies the model
size-range helper, new Sales Order start/end and per-line selectors, and
Branded Stock Planning per-line selectors. Cutting, bundles/QR, sewing,
packaging, finished stock, and reporting already carry size values
data-first and required no bounded-list change. The candidate was rebuilt
from exact active release `20260730_130207` and differs in exactly four
files: the new shared size-list module and the model-detail, new-sales-order,
and planning pages.

TypeScript, targeted ESLint, local and production 63-route frontend builds,
deterministic source verification, and signed-in production QA passed. Live
QA confirmed `44` through `68`, including `66` and `68`, in the new Sales
Order start/end/per-line selectors, the Branded Stock Planning line selector,
and the model size-range helper. Opening the planning form exposed an existing
behavior that immediately created empty group `0011`; verification confirmed
zero productions and the QA-only group was deleted immediately. Audit row
`10455` records that cleanup, and no production, stock, order line, or other
lasting business record was created or changed.

Both VMs verified the same deterministic 397-file source manifest. The release
archive SHA-256 is
`270b0ac9ea1de602ed833026eb4ce22b36d2911642b6cb5c6edcee0464fc2b23`;
the manifest SHA-256 is
`287553bf0ed4aaaf2248b7d01f84af5f2bbaf422f52d753eb730fd418723f842`.
The production frontend build ID is `QBKi4NyZ0lC-bc283gT0v`; the backend image
ID is
`sha256:41dc832a96a7341aa5bb79fb0bf4564e49f48f20f0741431a4bdc1aabc5561fc`.
The verified pre-cutover backup is
`/opt/milana-erp/shared/backups/pre_garment_sizes_20260731_054535.dump`
(25,852,748 bytes; mode `0600`; 886 restore objects; SHA-256
`74b8a525496ef0e5bdc7d09aea4d160f35215f2c9d35587a9d27408aa4428163`).
Its restore-list SHA-256 is
`052078965314e64e01f4c6ee6aca5e4fc9f6dcced24757bcee07f96d6ed4afda`.
Alembic remains at `0075_multi_fabric_cutting (head)`. All four required
internal/public endpoints returned HTTP 200. Backend and frontend have zero
restarts and no recent errors; two Uvicorn workers were healthy, and
PostgreSQL used 19 of 100 connections at final verification time.

On 2026-07-31, a user-authorized production-data-only merge consolidated the
remaining visually duplicated `Х-3044` family (Cyrillic `Х`) into canonical
`XJ-3044`. Read-only preflight found 175 canonical rows, 42 source rows, 37
normalized variant collisions, five source-only variants, and no downstream
references on any source row. The checksum-bound transaction preserved the
canonical `Халат к/р` name and original green-dress card picture, reconciled
the 37 collisions into their existing canonical rows, and renamed source-only
variants `4036`, `4153`, `4600`, `V-5567`, and `V-5568` under `XJ-3044`.
Five paid operations from colliding variant `5166` were added; conflicting
canonical values remained authoritative with the source value recorded in
merge provenance. No physical model image file was deleted.

Independent post-commit verification found one `XJ-3044` group with exactly
180 rows and 180 distinct variants, zero remaining `Х-3044` rows, zero exact
duplicate model codes, and all 436 image, 1,165 size, 173 color, 16 BOM, and
20 external-reference rows intact. The model-row total changed from 6,571 to
6,534 solely because 37 collision source rows were consolidated. Audit row
`10435` records the merge. Signed-in production QA searching `XJ-3044`
displayed one card with `Variantlar: 180`, the preserved name and picture, and
the expected first variants. The active release/image remained
`20260730_130207`, the backend retained zero restarts, all internal/public
health and login checks returned HTTP 200, and the post-change log scan found
no HTTP 500, traceback, exception, or error lines.

The validated rollback backup is
`/opt/milana-erp/shared/backups/pre_x3044_family_merge_20260731_053219.dump`
(25,813,377 bytes; mode `0600`; 886 restore objects; SHA-256
`34ed43899cf68c410ed6e421fdb4ca1767b2a1a9c2133d62d9f26ff4b69db796`).
Its restore-list SHA-256 is
`930cf112afee23107c938494a4cf7c6364c7cdd9d5e143773a389c7d66c2f31d`.

Release `20260730_130207` separates manually entered Daily Sewing Report model
identity from selected production work. Starting manual entry now presents
blank model/variant fields instead of copying the detected model, submits no
work-order or sewing-assignment link, hides the batch picker while manual mode
is active, and rejects mixed manual/linked payloads. Backend reads return a
clean manual identity with no borrowed production model name or images, and
editing a linked report into a manual report clears all production/work/batch
associations. No production report or other business record was created,
edited, or deleted during deployment or verification.

The clean release was reconciled from exact active release `20260730_102100`
and differs in exactly five files: the Daily Sewing Report route, schema,
focused tests, page, and manual-identity component. Seven focused backend
tests, Ruff, TypeScript, targeted ESLint, local and production 63-route builds,
and signed-in read-only production QA passed. The 17:35 SEW-06 rows now show
the three manually typed `Kj-13021`/`Pj-1118` identities without a borrowed
image or variant; the separately linked `РJ-1118` row correctly retains its
own image and variant `2922`.

Both VMs verified the same deterministic 396-file source manifest. The release
archive SHA-256 is
`50bcb8920efe219f03191c31d1cc90cea28a7f037b912e32bf6e2098567c39c5`;
the manifest SHA-256 is
`fe2de61c5b8f9b1695fb9211277b72f08fe39091fc02e58091fb1d0c28ab77cb`.
The production frontend build ID is `Lc0TSKMzdBW7pHvaKGWlU`; the backend image
ID is
`sha256:41dc832a96a7341aa5bb79fb0bf4564e49f48f20f0741431a4bdc1aabc5561fc`.
The verified pre-cutover backup is
`/opt/milana-erp/shared/backups/pre_daily_sewing_manual_identity_20260730_130207.dump`
(25,786,848 bytes; mode `0600`; 886 restore objects; SHA-256
`70e6aa3bcc05ff6fd20878394590c73bb8de0a24647d91578bc31867fef8dbd1`).
Its restore-list SHA-256 is
`47a4bdb7f3f0d4a3e768f817540b924e647b8d45e3883a6072d0082732705570`.
Alembic remains at `0075_multi_fabric_cutting (head)`. All four required
internal/public endpoints returned HTTP 200. Backend and frontend have zero
restarts and no recent errors; PostgreSQL used 13 of 100 connections at
verification time.

On 2026-07-30, a user-authorized master-data cleanup removed all nine active
`Material pending - Samo - ...` placeholders from Inventory Master Data.
Item `55` (`Material pending - Samo - 14359 - R7`) had no references and was
hard-deleted. Items `52`, `53`, `54`, and `56` through `60` each had one
zero-balance batch plus their original receive movement and matching full
issue adjustment, with no reservation, BOM, purchasing, production, cutting,
or waste links. Those eight items were made inactive instead of destroying
their stock audit history. The active matching count is now zero. Audit rows
`10257` through `10265` record the eight archives and one deletion.

The verified pre-change backup is
`/opt/milana-erp/shared/backups/pre_pending_material_cleanup_20260730_104121.dump`
(25,773,530 bytes; mode `0600`; 886 restore objects; SHA-256
`bb5ee2f2018c268fa94d8f439a313e36a42e24de07b9ff0dc0fee138d8911aad`).
Its restore-list SHA-256 is
`a99945ca01a2de9f4da9fd24938d19c154ba06ac17df5d4f62b36b9bc8d70e78`.
This was a production-data-only cleanup: active release/image
`20260730_102100` remained unchanged, the backend retained zero restarts, and
internal and public health checks returned HTTP 200.

Release `20260730_102100` fixes detached upward-opening `SearchableSelect`
menus across the ERP, including the fabric-batch selector on Branded Stock
Orders. Previously, an upward menu was positioned by its maximum allowed
height, so a short one-result menu could appear hundreds of pixels above its
field. Upward menus now anchor their bottom edge to the selector and translate
by their actual rendered height; the existing maximum-height constraint is
unchanged. The clean candidate was reconciled from exact active release
`20260730_084018` and differs in exactly
`frontend/src/components/SearchableSelect.tsx`.

Frontend typecheck, targeted ESLint, and local and production 63-route builds
passed. Signed-in production geometry QA used the live Branded Stock form with
fabric query `8364`: the one-result upward menu rendered 46 pixels tall and
its bottom edge was exactly 4 pixels above the selector wrapper, with the
computed `translateY(-100%)` transform. The temporary form was not submitted.
No production order, inventory, storage, schema, or other business data was
created or changed.

Both VMs independently verified the same deterministic 396-file source
manifest. The release archive SHA-256 is
`50f25c67b314bb5870e7fbd997583443370f8487d28e218cdce90f444e6e00b1`;
the manifest SHA-256 is
`8a725a7dc35b04570cfbd69fb447abf8da8fd2136af6f6641a7ca1114848e039`.
The production frontend build ID is `WWgzBxSKsXZWoXX9QVKob`; the backend image
ID is
`sha256:4fd0c6ebb9ff1fb4a68efc9ea5c994556010da582799974fb759bba12cd6217c`.
The verified pre-cutover backup is
`/opt/milana-erp/shared/backups/pre_searchable_select_anchor_20260730_102100.dump`
(25,773,252 bytes; mode `0600`; 886 restore objects; SHA-256
`82b8c468281bae1ac5e9cc27a4d317971481415ecfeabc6b00ded5d1c6ef1268`).
Its restore-list SHA-256 is
`744d9fa5eac59dc4092560e5b7ea8428626056ee561a6fbcb46a6c5cc146d168`.
Alembic remains at `0075_multi_fabric_cutting (head)`. All four required
internal/public endpoints returned HTTP 200. The backend has one Uvicorn
parent with two workers and zero restarts; the frontend is active with zero
restarts. Startup and request logs contain no new 5xx or traceback errors. At
verification time PostgreSQL used 15 of 100 connections and the database was
87,481,367 bytes.

On 2026-07-30, a user-authorized production-data-only correction changed
`SO-2026-000046` / `PO-2026-000046` from sizes
`46, 48, 50, 52, 54, 56` at 100 pieces each to sizes
`44, 46, 48, 50, 52` at 120 pieces each. This preserves the 600-piece order
total and an even size split. Before the change, Cutting, Sewing, Packaging,
and Storage were all waiting with zero input/output; the order had zero
production batches, cutting records, bundles, material reservations, and
completed item quantities. Those downstream counts and statuses remained
unchanged after the correction. Audit rows `10252` and `10253` record the
validated breakdown update and final ascending row normalization under System
Admin. Signed-in production QA confirmed the five corrected rows and the
600-piece total with no browser console errors.

The verified pre-change backup is
`/opt/milana-erp/shared/backups/pre_po46_size_correction_20260730_152036.dump`
(25,772,957 bytes; 886 restore objects; SHA-256
`1887fe021633aebb5eed79ccf91daf473b8c48f7276c298fdf81a959de807ce8`).
Its restore-list SHA-256 is
`e22b5e310748533c8571b9fa4e8c745687f0de8b4b15e8ad61142d634a854431`.
This was not an application deployment: active release/image
`20260730_084018` remained unchanged, backend restarts remained zero, internal
and public health returned HTTP 200, and the ten-minute backend error scan was
empty.

Release `20260730_084018` deploys the responsive UX hardening requested for
phone, tablet, browser-zoom, desktop, and wide-screen operation. It moves the
persistent desktop shell to the wide-screen breakpoint, keeps narrower and
zoomed layouts on drawer navigation, changes Process Tracking to cards below
the table breakpoint, makes filters/forms/actions wrap, contains wide tables
in explicit horizontal scrollers, allows sidebar labels to wrap, docks Tasks
in the Topbar, and portals the Tasks overlay to `document.body` so a blurred
Topbar cannot offset or clip it. QA-driven releases `20260730_080904` and
`20260730_083254` were superseded during the same deployment: the first
exposed contained table-scroll plus sidebar/FAB issues, and the second fixed
those but exposed a 56px Tasks-drawer offset. They remain in the release
history; `20260730_083254` is the tested rollback.

The release was built from the verified active production source because both
the dirty local tree and GitHub `origin/main` were older than production.
Both VMs independently verified the same deterministic 396-file manifest.
The final release differs from `20260730_083254` in exactly
`frontend/src/components/TasksDrawer.tsx`, where the already-tested drawer is
portaled to the document body. The release archive SHA-256 is
`e8140206d02c5eac62fcdae1bae28b6ba88d9f4e6e828418e93331dcba055580`;
the manifest SHA-256 is
`03ba86dc804f3a683a0b2814f86bea7939aa5e66cab18ba3900a97c39a7e27ae`.
The production frontend build ID is `gd0Knhu5wfmhcVn3Hr2uQ`; the backend image
ID is
`sha256:d9a4adb32abe90941e873c9c152a311d8dc8da21f88c155ff921b4da38ddaf37`.

The verified pre-cutover backup is
`/opt/milana-erp/shared/backups/pre_responsive_ux_20260730_084018.dump`
(25,735,423 bytes; mode `0600`; 886 restore objects; SHA-256
`4a289e34003f756bd6b734cd7494839e47505e2473dbee187e29dfb18b677529`).
Its restore-list SHA-256 is
`8ba6fe46b25a9587c512f51b55afa3e067b36706b9148c4e7f29b449c80402ef`.
Alembic remains at `0075_multi_fabric_cutting (head)`; there was no pending
schema migration. All four required internal/public checks returned HTTP 200.
The backend has one Uvicorn parent with two workers, the correct
`8000:10000` publication and `/app/storage` read-write mount, and zero
restarts; the frontend is active with zero restarts. Ten-minute backend and
frontend error scans were empty. At verification time, PostgreSQL used 14 of
100 connections and the database was 87,309,335 bytes; the backend release
volume had 138 GB free, shared storage 464 GB free, and the frontend release
volume 22 GB free.

Signed-in, read-only production geometry QA covered Process Tracking at
physical viewport widths 320, 390, 768, 1024, 1279, 1280, 1366, 1439, 1440,
1535, and 1920 pixels. Planning, Production Orders, Work Orders, Cutting
Passports, Models, an active production-order detail, and its Sewing form were
also checked at 320, 768, 1366, and 1920 pixels. The checks found no document
horizontal overflow, viewport-outside controls, hidden/clipped readable text,
or overlapping controls. The mobile Tasks drawer starts at viewport top 0,
fills the viewport, is attached beneath `document.body`, and closes normally.
Process factory labels for Milana, Besttex, and Eco Cotton remain present; the
Sewing form retains Input, Output, and Defect and has no retired Rework or
Rejected inputs. Browser console errors were empty. No workflow submission or
business, inventory, storage, or schema data was changed; read-only sign-in
may update ordinary authentication activity metadata.

Inherited validation debt remains outside this responsive release:
`npm audit --omit=dev` reports three high-severity production dependency
findings (the full development install reports six high findings), `pip-audit`
reports Pillow 12.2.0 with a 12.3.0 fix plus transitive ecdsa 0.19.2 with no
published fix, the i18n scanner reports nine existing missing keys, and ESLint
reports six existing warnings but zero errors. These findings were not
introduced by the responsive changes and should be handled as separate,
reviewed upgrades.

Release `20260730_065616` removes the separate Rework (`Qayta ishlash`) and
Rejected (`Rad etilgan`) inputs from the production Sewing work-order form.
The existing Defect (`Brak`) quantity remains the authoritative rejected-piece
entry and continues to drive replacement cutting, waste, assignment
completion, and reporting. New general sewing submissions explicitly send
zero for the two retired compatibility fields; replacement sewing submissions
already do the same. Historical database values, schema columns, and rejection
workflows outside this form were not deleted or changed.

The release was reconciled onto the exact active `20260730_064700` source so
its Process Tracking factory-label work remains present. The candidate differs
in exactly one intended frontend file. Frontend dependency installation, i18n
check, typecheck, targeted ESLint, and both local and production 63-route builds
passed. The i18n scanner still reports nine inherited warnings in unrelated
pages and this release adds none. Signed-in, read-only production QA confirmed
that the live Sewing form now contains exactly the Input, Output, and Defect
numeric fields, retains Defect reason and Save, has no Rework or Rejected
controls, and produces no browser console errors. No production record or
inventory data was submitted or changed during deployment or QA.

Both VMs independently verified the same 396-file source manifest. The release
archive SHA-256 is
`55365d1ca31e3af1863823eacebc0a7dddb17c625dc2446204a0abcdcff9df`;
the manifest SHA-256 is
`e121b0ad4eeebe39fefc302c098002b955ee1c2d82818c77b503fcca7c7e83cc`.
The production frontend build ID is `n2Y4giAayKlru1nNeCnHn`; the backend image
ID is
`sha256:d9a4adb32abe90941e873c9c152a311d8dc8da21f88c155ff921b4da38ddaf37`.
The verified pre-cutover backup is
`/opt/milana-erp/shared/backups/pre_sewing_fields_removal_20260730_065616.dump`
(25,735,414 bytes; 886 restore objects; SHA-256
`07bd9d1808ca395452d71b998f0392ff322e25eb32ff9d110939d1b619f049ae`).
Its restore-list SHA-256 is
`8ff973c7c9a69e5cf21337198e08c6ff81133e62f1e22525289b84567d24f3be`.
Alembic remains at `0075_multi_fabric_cutting (head)`. All four required
internal/public checks returned HTTP 200, the backend runs one Uvicorn parent
with two workers and zero restarts, the frontend is active with zero restarts,
and the post-cutover backend/frontend log scan found no 5xx, traceback, or
service errors.

Release `20260730_064700` adds compact cutting-department and sewing-factory
labels beneath each model on Process Tracking. Cutting comes from the cutting
work order's assigned department. Sewing comes from the actual non-cancelled
bundle routes when bundles exist, including mixed factory routes; before
bundles exist it falls back to the planned sewing work order and resolves the
generic sewing department to Milana. The frontend localizes `CUT`, `ECT`,
`MIL`, `BST`, and `ECO` in English, Russian, and Uzbek. No production order,
bundle, assignment, inventory row, or other business record was changed by
deployment or signed-in QA.

The release was reconciled onto the exact active `20260730_034311` archive and
differed in exactly three intended source files. Three focused backend routing
tests, Ruff, Python compilation, frontend typecheck, targeted ESLint, and both
local and production 63-route builds passed. The full i18n scanner still
reports nine inherited missing-key warnings in unrelated model and order
pages; this release introduced no new translation key. Signed-in production
QA confirmed the compact labels on live rows for Milana, Besttex, and Eco
Cotton sewing plus standard and Eco Cotton cutting, with no browser console
errors. The first frontend activation readiness check ran before Next.js was
ready and automatically rolled back to `20260730_034311`; the retry used a
bounded readiness wait and completed successfully.

Both VMs independently verified the same 396-file source manifest. The release
archive SHA-256 is
`c529e44932e094c666d6101b283b8ae8bd8db740e84b27978ea1b42226338c24`;
the manifest SHA-256 is
`0547260b8f16f5c34272f6859e4a283de5c01c15e0e3bec873721c3995ab5b2f`.
The production frontend build ID is `prOZQq48THB0wfcYHZhov`; the backend image
ID is
`sha256:4fd0c6ebb9ff1fb4a68efc9ea5c994556010da582799974fb759bba12cd6217c`.
The production npm audit reports five high-severity dependency advisories.

The verified pre-cutover backup is
`/opt/milana-erp/shared/backups/pre_process_factory_display_20260730_064700.dump`
(25,734,706 bytes; 886 restore objects; SHA-256
`ceb131b50db1223d5ec6175cba37beeea8b951f4338dfef1d6d82be4b3f4c736`).
Its restore-list SHA-256 is
`981e8c435712a0de374b385256440308edd6dce41212d4cd4e1b632bdb90bfd2`.
Alembic remains at `0075_multi_fabric_cutting (head)`. All four required
internal/public health checks returned HTTP 200, the backend runs one Uvicorn
parent with two workers and zero restarts, the frontend is active with zero
service restarts, PostgreSQL used 21 of 100 connections, and the post-cutover
backend/frontend log scan found no 5xx, traceback, exception, or service
errors.

On 2026-07-30, a production-data-only cleanup consolidated the 13 definite
duplicate model families authorized by the user: `PJ-1105`, `РJ-1142`,
`PJ1173`, `РJ-1183`, `ТJ-2026`, `TJ-2092`, `TJ-2124`, `TJ-2198`,
`ХJ-3033`, `XJ-3044`, `ХJ-3128`, `XJ-3150`, and `XJ-3152`. The operation
changed 29 duplicate-family model identities and reduced 390 affected variant
rows to 389 survivors; the total model-row count changed from 6,551 to 6,550,
and Models/PLM groups changed from 2,024 to 2,011. Slash-family candidates and
manual-review candidates were intentionally not changed. This was not an
application deployment: active release/image `20260730_034311` remained
unchanged.

The only variant collision was old row `7066` (`XJ3044-V-5036`) into surviving
row `6291` (`XJ-3044-5036`). The surviving name, code, primary picture, two
image rows, and all existing bundle/production-order references remained
authoritative. Missing category/details, five unique paid operations, old-ERP
receipts, six numeric sizes, and BOM row `95` were merged into the survivor.
Strict final verification found 49 paid operations, 12 sizes, one BOM, one
color, two images, six bundle references, six production-order-item
references, and one production-order reference. An ORM source-delete cascade
initially removed the six reassigned size rows and BOM row; they were restored
immediately with their original IDs and values, then covered by stricter
post-commit assertions. Duplicate source image database rows were removed,
but no physical image file was deleted and their URLs remain in the merge
provenance/audit record.

The 13 family merges are recorded in audit rows `10148` through `10160`; the
child-row correction is audit row `10161`. The checksum-bound dry-run used
pre-state SHA-256
`f42a6fcdc7933af4f2c4cae6653356d307342ec2e9dd090f3fc4aacf79f0b27f`
and merge-config SHA-256
`6ba86326fd02a9a23d7a485a523322b0cd23917250f84d7b0aa3f393cea14fc0`.
The rollback backup is
`/opt/milana-erp/shared/backups/pre_model_definite_merge_20260730_050011.dump`
(25,805,058 bytes; 886 restore objects; SHA-256
`0fb7c93e25ca72b13cbb4f07896c2483d1f49afb960888d46b3b521e2f6787f0`).
Its restore-list SHA-256 is
`2aa59dce475858b57bf490af7512fa4768b03df6219afa9cc9d102d80715b4d0`.
Independent post-commit database verification found all 13 canonical groups,
389 surviving affected rows, and zero exact duplicate model codes. All four
required health endpoints returned HTTP 200, the backend remained at zero
restarts, and the post-change log scan found no 5xx/traceback/internal-server
errors. Signed-in production QA confirmed one `XJ-3044` card with 175
variants, one `5036` result with `Suprem / Rotation`, the 12-size/49-operation
detail counts, and one `PJ-1105` card with 11 variants.

Release `20260730_034311` changes the Production Order summary editor so
material changes are selected from real inventory batches instead of typed as
a free-text material code. The editor supports multiple fabric rows, requires
a positive estimated quantity for each batch, derives the inventory unit, and
refreshes the material-reservation status after a save. The backend validates
that selected rows are unique material or semi-finished batches, QC-accepted,
and sufficiently available. A changed plan releases that order's unused open
material reservations so the old batch is not left locked; a consumed
reservation blocks the edit. Legacy scalar material fields remain synchronized
to the primary selected fabric for compatibility.

The release was reconciled onto the exact active `20260729_130726` source and
differed in exactly five intended source files. Ruff, all 17 material
reservation tests, two production-flow regression tests, frontend i18n check,
typecheck, targeted ESLint, and both local and production 63-route builds
passed. Signed-in production QA opened Production Order 30, confirmed its
existing selected inventory batch, quantity, unit, and 6,922 selectable
inventory choices, then used Cancel. No production order, reservation, stock,
or other business record was changed by deployment or QA.

Both VMs independently verified the same 396-file source manifest. The release
archive SHA-256 is
`620a53b1d311ec03773f799ce6278db4c81bf51579dc66d536b503df5e056f55`;
the manifest SHA-256 is
`d2686793b84cb96364342d96b87ed0c0e0ddeb7469f12a5e5b972dcab08c2a82`.
The production frontend build ID is `U9Dckrg1BnKPizDjP4UFU`; the backend image
ID is
`sha256:d0ba1aa2fbb9667da5b692318ec0f186ce5700c083dfce5832f9cf5aaef79405`.
The current npm audit reports six high-severity dependency advisories.

All four required internal/public health checks returned HTTP 200. Alembic
remains at `0075_multi_fabric_cutting (head)`. The backend runs one Uvicorn
parent with two workers and zero restarts, the frontend is active with zero
service restarts, PostgreSQL used 19 of 100 connections at final verification,
and the post-QA log scan found no HTTP 5xx responses, tracebacks, exceptions,
or frontend service errors.

The verified pre-cutover backup is
`/opt/milana-erp/shared/backups/pre_production_order_fabric_edit_20260730_034311.dump`
(25,804,928 bytes; 886 restore objects; SHA-256
`c5760c407cc77104bef992ad74a7412439f2f3524766e14aef6a12f6fdd9a388`).
The restore-list SHA-256 is
`dc821cb15aaa3a2a688712eea2c0931d1ebfcd5429ab6230bb3367a12731e2c8`.

The preceding production release was `20260729_130726`, which added the Daily
Sewing Report correction behavior described below.

Release `20260729_130726` adds correction support to the Daily Sewing Report.
Users with `sewing.workspace` permission can edit a saved report's date,
manual model/variant, kroy number, section and garment-part quantities, defect
quantity/reason, and notes. The correction updates only that daily report:
its production-order/flow association and workflow progress are not changed.
Every correction writes the full before/after values to the audit log. The
saved-record table now has a compact Edit action and an English/Russian/Uzbek
modal populated with the record's current values.

The release was reconciled onto the then-active `20260729_125531` source and
differed from it in exactly seven intended source files. Six focused backend
tests, Ruff, frontend typecheck, targeted ESLint, and the 63-route production
build passed. Signed-in production QA confirmed 24 visible Edit actions and a
correctly prefilled modal; QA used Cancel and changed no business data.

Both VMs independently verified the same 395-file source manifest. The release
archive SHA-256 is
`37c9ce3c821db01f2c8bf9096d532b4daed8a8038fbcffde9b20948d00cf9798`;
the manifest SHA-256 is
`f00eeb2b2c5ffb449f5208b4d6c650f12886967d51641f297b4133a5bb359e92`.
The production frontend build ID is `x1pzkQ-HJujCTw2oJdRMH`; the backend image
ID is
`sha256:a51c4505c6c78eeb181f39fe1576b2414833048d07ed43e143198468e69a390d`.
The current npm audit reports five high-severity dependency advisories.

All four required internal/public health checks returned HTTP 200. Alembic
remains at `0075_multi_fabric_cutting (head)`. The backend runs one Uvicorn
parent with two workers and zero restarts, the frontend is active with zero
service restarts, PostgreSQL used 16 of 100 connections, and the post-cutover
log scan found no HTTP 5xx responses, tracebacks, or frontend service errors.

The verified pre-cutover backup is
`/opt/milana-erp/shared/backups/pre_daily_sewing_edit_20260729_130726.dump`
(25,782,115 bytes; 886 restore objects; SHA-256
`1fe09798e9f27ae4e3e50cb140589f1728a7c5edcb2147d037545ead56be6012`).
The restore-list SHA-256 is
`d8993c23fd2ade79c2f7d8d112370c09a2a7b36f59ba8bd3748f6aedd7d4793b`.

The preceding production release was `20260729_125531`, which introduced the
multi-fabric planning and cutting behavior described below.

Release `20260729_125531` adds multi-fabric planning and cutting. A production
order can now contain two or more distinct fabric batches, with a required
positive estimated quantity for each fabric. Planning prevents duplicate
batches and preserves the first fabric in the legacy scalar fields for
compatibility. Cutting requires an actual consumed amount for every planned
fabric and commits all material consumption and bundle creation atomically.
Reservations are derived from the exact planned material rows, and inventory
batch update/deletion protection includes both planned and consumed
multi-fabric links. The new controls and validation messages support English,
Russian, and Uzbek.

Alembic migrated production from `0074_cutting_nastilchi` to
`0075_multi_fabric_cutting`, adding `production_order_materials` and
`cutting_material_usages`. The migration backfilled six existing legacy
cutting-material usages exactly; it created zero planned production-material
rows because no new production orders were created during deployment or QA.
No bundle, stock movement, reservation, production order, or other business
record was created by the deployment checks.

The release was reconciled onto the then-active `20260729_122902` source so
the cross-ERP Latin/Cyrillic model-search behavior remained intact. The
multi-fabric change differed from that release in exactly 13 intended source
files. Backend reconciliation regression tests passed (17 tests), and the
frontend production build passed with 63 routes. Signed-in production QA
confirmed the Planning “Mato qo‘shish” control, an existing Cutting material
amount/bundle workflow, and all 18 `PJ-1000` global-search results.

Both VMs independently verified the same 394-file source manifest. The release
archive SHA-256 is
`524749d8e743c84760b46031ecd5f76d5f87dab904f449a4c3486cd174977755`;
the manifest SHA-256 is
`98eee5865d400e834375eed1ad170b468916f7001ea133a8a660e5432a946244`.
The production frontend build ID is `lhJAUwcgVzTOgeUr6Vf9e`; the backend image
ID is
`sha256:95163b215c6b4a788910847882ed12750b9bfea6eb01d8af023959a9879bb056`.
The unchanged npm audit baseline reports six high-severity dependency
advisories.

All four required internal/public health checks returned HTTP 200. The backend
runs one Uvicorn parent with two workers and zero restarts, the frontend is
active with zero service restarts, and PostgreSQL used 13 of 100 connections
at verification time. Post-cutover logs showed normal startup and successful
requests with no observed HTTP 5xx responses or tracebacks.

The verified pre-migration backup is
`/opt/milana-erp/shared/backups/pre_multi_fabric_20260729_125531.dump`
(25,770,425 bytes; 860 restore objects; SHA-256
`39b9cb396ff412015b2e67686a9eceedcc843f22707ec185cc52523de14e1301`).
The restore-list SHA-256 is
`512a5ca3edd7da5e5d9ae291e40835719448086c82c76ac23706e946dacf432c`.

The preceding production release was `20260729_122902`, which introduced the
cross-ERP model-code search behavior described below.

Model-code search now treats visually identical Latin and Cyrillic characters
used in legacy model numbers as equivalent throughout the ERP, not only in
Models/PLM. The shared normalization is applied to model lists/options and
variant groups, top global search, Sales and Order History, Process Tracking,
Cutting inventory/passports, Sewing receive, Packaging receive/queue,
warehouse package lookup, Payroll QR control, accessory requests, and shared
frontend selectors. Models/PLM and the top search also search the full
server-side dataset, so pagination cannot hide an applicable model.

Typing either Latin `PJ-1000` or Cyrillic `РJ-1000` returns the same 18 model
records and the same four Models/PLM groups: `PJ-1000/4`, `PJ-1000/5`,
`PJ-1000/6`, and the 15-variant `РJ-1000` group. Authenticated production API
QA covered 15 search surfaces. Signed-in Chrome QA confirmed four model cards
on Models/PLM and all 18 model links in global search.

This release changed exactly 20 source files relative to active release
`20260729_115130`: 13 backend files and seven frontend files. It changed no
schema or business rows, and Alembic remains at
`0074_cutting_nastilchi`. Both VMs verified archive SHA-256
`a4ee0db4906cc20598fb5619d0c0cecc446850e0b6524132a7c52a23b1025336`
and the same 394-file source-manifest SHA-256
`d42a86d8767d3b68d14aba414c686371d5018c6524034404f70bfff6513ca0db`
before building. Backend Ruff and 32 focused tests passed. Frontend targeted
lint, typecheck, and the 63-route production build passed. The production
frontend build ID is `xhbhVPeMVjViNAS-kDOaY`; the unchanged npm audit baseline
still reports six high-severity dependency advisories.

All four required internal/public health checks are HTTP 200. The backend runs
one Uvicorn parent with two workers and zero restarts, the frontend is active
with zero service restarts, PostgreSQL used 16 of 100 connections, and the
post-cutover logs showed normal startup and successful requests with no
observed HTTP 5xx responses or tracebacks. QA was read-only and changed no
business data.

The verified pre-cutover custom backup is
`/opt/milana-erp/shared/backups/pre_model_search_everywhere_20260729_122902.dump`
(25,769,511 bytes; 860 restore objects; SHA-256
`e22a9cc941289ee46eb5fe02c2993a47f57591043b32042a550d7eca4f573a5b`).
The restore-list SHA-256 is
`82dd4a7a44a443eaae4c7f5f87ffeb76cbc80750caa59b89774bea9d6bcacada`.

The immediate rollback release `20260729_100001` changed the Cutting Passport
create/edit modal so it ignores outside/backdrop clicks and partially entered
form data stays visible until the user explicitly closes or cancels it. The
explicit X and Cancel actions still close it.

This frontend-only release changed exactly
`frontend/src/components/Modal.tsx` and
`frontend/src/app/(app)/cutting-passports/page.tsx`. It changed no schema or
business rows, and Alembic remains at `0074_cutting_nastilchi`. Both VMs
verified archive SHA-256
`a612162d6d4f5d1e6b0f74d96056352a0f9b507619511fd3c6c6116f76a05cae`
and the same 393-file source-manifest SHA-256
`0a9ce12f90389f330099380f170ed94e7d122dea7a7587e610fa927146738535`
before building. Local and production typechecks and Next.js builds passed;
the production frontend build ID is `OjJDF5EFoOXzhoGJ0BAYJ`. The existing
npm audit baseline still reports six high-severity dependency advisories.

All four required health checks are HTTP 200. The backend runs one Uvicorn
parent with two workers and zero restarts, the frontend is active with zero
service restarts, PostgreSQL used 14 of 100 connections, and the final
post-QA log scan found no frontend errors, backend HTTP 5xx responses,
tracebacks, exceptions, or errors. Signed-in Chrome QA entered a temporary
unsaved passport number, clicked the grey backdrop, and confirmed both the
modal and exact value remained. The explicit close button then dismissed the
form, and no business record was created.

The verified pre-cutover custom backup is
`/opt/milana-erp/shared/backups/pre_cutting_passport_modal_20260729_100001.dump`
(25,339,608 bytes; 860 restore objects; SHA-256
`75a6d29935b2c044a64e6706660739cae55d80d8a9045c4fb4df3c9db7d560ef`).
The restore-list SHA-256 is
`d0bb29535c6e10f9acde8d75a52b10eccee62566952fb98f3ab32c900f3bad4c`.

The immediate rollback release `20260729_090547` added an optional Nastilchi
(layup operator) name to Cutting records, exposed the field in the
English/Russian/Uzbek Cutting form and API, and printed it in the A4 Cutting
Sheet identity section. Older records fall back to the linked Cutting
Passport's manual operator name when available. The business name remains
separate from the authenticated ERP operator used for audit ownership.

Alembic is at `0074_cutting_nastilchi`; the migration added one nullable
`VARCHAR(128)` column and changed no existing business rows. The release was
built from the exact active `20260729_052401` source plus only nine reviewed
Nastilchi files. Both VMs verified archive SHA-256
`86002939af18e17522807ac938f4c9f01104093cd23d217b241f7a31f81477bd`
and the same 393-file source-manifest SHA-256
`4aaf95b5efb7f6ca11d75c5152512c5d30b54c9c247176e3d8297609ac50c58f`
before building. Focused backend flow and sheet tests passed, along with Ruff,
Python compilation, frontend typecheck, and local and production Next.js
builds. The active-release i18n checker has nine pre-existing missing-key
warnings; the candidate reproduced the exact baseline and added all three
Nastilchi translations.

All four required health checks are HTTP 200. The backend runs one Uvicorn
parent with two workers and zero restarts, the frontend has zero service
restarts, PostgreSQL used 14 of 100 connections, and post-cutover logs
contained no frontend errors, backend HTTP 5xx responses, tracebacks, or
errors. Signed-in Chrome QA showed the new field on waiting Cutting work order
`78`; the existing action generated Cutting Sheet `CUT-5`, and the production
sheet request returned HTTP 200. QA was read-only and created or changed no
business records.

The verified pre-cutover custom backup is
`/opt/milana-erp/shared/backups/pre_cutting_nastilchi_20260729_090547.dump`
(25,337,975 bytes; 860 restore objects; SHA-256
`747b5d0497a67d8d2ece24efb874a680b90ca1d75918fa59a4091a832cefb7a2`).
The restore-list SHA-256 is
`754c8d96b202d347ca9458bafd583da9a4d808eaadfda39dab8ef816700756e2`.

The previous `20260729_052401` release fixed Material Inventory's
Supplier filter and its interaction with search, dates, group changes, and
browser history. Production diagnosis proved that backend filtering was
already correct and occurred before pagination; the fault was frontend
navigation state. Native filter events, asynchronous Next router calls, and
the search debounce could cancel or overwrite one another, leaving the URL,
`useSearchParams`, and SWR request keys out of sync.

All imperative Inventory filters now commit through Next.js's patched browser
History API. Optimistic supplier intent is carried into competing filter
actions, delayed callbacks verify the exact route before committing, and
Back/Forward resynchronizes the controls and URL-derived API keys. The shared
URL builder enforces either `supplier_id=<positive integer>` or
`supplier_unassigned=true`, never both, and drops material-only supplier state
when entering Accessory Inventory. Supplier-option refreshes are explicit
after relevant material mutations, and All/No supplier labels are translated.
Signed-in production QA reconciled Asaka Textile at 2 item types/2 lines,
Dinar at 27/263, unassigned at 3/17, and all suppliers at 57/351. A rapid
Asaka-plus-`652/07` interaction committed both parameters and returned 0/0;
changing the query to `23302` preserved Asaka and returned the exact 1/1 row
with 533.30 kg and 18 pieces. Back/Forward and the pending-navigation route
guard also passed. Backend logs confirmed filtered stock and batch requests
with HTTP 200.

All four required health checks are HTTP 200. The backend runs one Uvicorn
parent with two workers and zero restarts, the frontend has zero service
restarts, PostgreSQL used 17 of 100 connections during verification, recent
backend logs contained no HTTP 5xx, traceback, or error, and Alembic remains
at `0073_archive_depleted_batches`. This release changed no business rows or
schema. Its verified pre-cutover custom backup is
`/opt/milana-erp/shared/backups/pre_supplier_filter_fix_20260729_052401.dump`
(25,209,177 bytes; 860 restore objects; SHA-256
`7a0dbcb2c5cc83febd93eae99306724904e233c5c7f25e03129d980351da7aa2`).
The restore-list SHA-256 is
`85aa5c661ed46fb22ec7ce02dd0fa35a0c3346187fe378bd4657b202d6f0e537`.
The release archive SHA-256 is
`ac816ca058cb13c6d6dca158d8ca9ea0d96d4586ad2126ad2c0a6b6bfe1622ef`;
both VMs produced source-manifest SHA-256
`626dce0cd7613f46215f1a52318b3e2b4c9dfe5b7f64913d3e474d7708c9ed88`
before building.

The earlier `20260729_034138` release added the destination sewing factory to
every Cutting Floor work card in small text. The inbox API
derives Milana, Besttex, or Eco Cotton from the sewing work order already
attached to the same production order, so the label follows the real route
instead of guessing from the cutting department. Signed-in production QA
showed the correct mixed Milana and Besttex labels on the live pending and
in-progress Cutting cards, with no browser console errors, backend HTTP 5xx
responses, or tracebacks. All four required health checks were HTTP 200, the
backend runs one Uvicorn parent with two workers and zero restarts, PostgreSQL
used 18 of 100 connections during verification, and Alembic remains at
`0073_archive_depleted_batches`. No business rows or schema were changed.

The verified pre-cutover custom backup for that earlier cutting release is
`/opt/milana-erp/shared/backups/pre_cutting_factory_label_20260729_034138.dump`
(25,198,759 bytes; 860 restore objects; SHA-256
`60a502bbcacbe51dfbc0434099e15ee1f3c854749c1003a281789176054456c2`).
Its restore-list SHA-256 is
`5d6c949d0de00047811af6450b378a8812b16d11d19f8c3e246fb3b4dfc0735e`.
The release archive SHA-256 is
`d173d5b31e2d9832c87599fc4bb9351372d29e8a8d56f22397882956429c068e`;
both VMs produced source-manifest SHA-256
`0d08447b5fcc476709e626a04eedd98cacd5fcc35506b36e55c0117e73ba0ea0`
before building.

On 2026-07-29, the user approved deletion of only six production workflows
routed to Besttex, which does not yet have ERP access:
`SO-2026-000006`, `SO-2026-000007`, `SO-2026-000009`,
`SO-2026-000010`, `SO-2026-000011`, and `SO-2026-000012`. A guarded
transaction deleted exactly six production orders, 24 work orders, 33 size
rows, two production batches, one cutting record, five bundles and their five
creation scans, and one waste record. Models, planning-order parents, material
batches, historical audit logs, and the two other Besttex workflows
`SO-2026-000005` and `SO-2026-000008` were preserved. The first deleted
workflow had recorded 430 physically cut pieces, five created bundles, 12 kg
of waste, and a 115 kg raw-material consumption. The consumption ledger entry
`#721` and stock batch `#31` at 82 kg were intentionally retained unchanged;
no raw stock was minted by reversing recorded physical consumption. The
pre-change backup is
`/opt/milana-erp/shared/backups/pre_besttex_six_workflow_delete_20260729_100600.dump`
(25,208,805 bytes; 860 restore objects; SHA-256
`4d30b02d77e0630ab2e228a68d7c073d86710a2c2982dcf8ca1a2de2065cf243`).
The five bundle QR images were archived and moved recoverably under
`/opt/milana-erp/shared/backups/besttex_six_workflow_delete_20260729_100600/`.
Audit records `#9951` through `#9956` form a valid new hash-chain segment.
Post-change reconciliation found zero target workflow rows and exactly the two
retained active Besttex workflows. All four required health checks passed.

The active release also retains the fix for the production
Models/PLM and Inventory performance incident. The main failure was
`GET /api/models/{id}/variants` loading the complete 6,500-plus-model catalog,
including images, BOM, and stock relations, before filtering one family in
Python; repeated requests transferred roughly 155 MB each through one Uvicorn
worker. Several Inventory, Sales, Production, Cutting, and Printing screens
also downloaded full model records when they only needed model labels. The
browser's 12-second upload abort then reported a misleading backend-down error
even when the server completed the upload, while the old upload-then-save flow
could leave a duplicate or orphan after a retry.

Production now filters variant-family identity in PostgreSQL, hydrates only
the matching rows, and serves a compact `/api/models/options` projection for
label selectors. Full-catalog frontend reads were replaced with that bounded
projection or exact ID-scoped lookups, cached and deduplicated for five
minutes. Variant create/edit plus an optional picture is one idempotent
multipart operation, the frontend keeps the same idempotency key across a
retry, upload timeouts are 60 seconds behind a 90-second/25 MB Next.js proxy
limit, and a failed background revalidation no longer blanks already loaded
model data. The backend starts two Uvicorn workers while running Alembic and
the optional seed exactly once, and logs requests taking at least two seconds
without query strings, headers, or bodies. Do not raise the worker count above
two without lowering the current 15-connection pool plus 10 overflow per
worker.

The exact candidate query resolved model `5795`'s nine-member family against
production in 0.941 seconds and returned all 6,531 lightweight model options
in 1.221 seconds before cutover. After cutover, all four required health checks
were HTTP 200; signed-in read-only QA loaded model `TJ-2199-5461` with nine
variants, Material Inventory with 53 item types and 317 lines, Accessory
Inventory, Receive Stock, Production Orders, Cutting Passports, and Sales
creation with 2,023 grouped model choices. Browser console errors, backend
HTTP 5xx responses, tracebacks, and requests over the two-second threshold
were all zero during verification. Alembic remains at
`0073_archive_depleted_batches`; no business rows or schema were changed by
this release. The verified pre-cutover custom backup is
`/opt/milana-erp/shared/backups/pre_performance_fix_20260728_131008.dump`
(25,196,917 bytes; 860 restore objects; SHA-256
`fbbf3d290c4a43f5b72e10e7d9d3d0bf8dfdfd7fcc585fb91cd480993716c418`).
The release archive SHA-256 is
`1b2b0241f968ff4f1cad305fae13da8e44a68664d72b7f84692020cff7618cc7`;
both VMs produced the same pre-build source-manifest SHA-256
`dc5bdbe4b1d4d7a6000d378cb526f6e080bbad6552c5efc2c01c34b1d37f36f3`.
Suspected files left by the earlier timed-out upload incident were not deleted
because ownership could not be proven safely.

This release retains the reviewed old-ERP
model migration and complete-detail display from `20260727_075027`, the
complete-catalog Models/PLM search from `20260727_092334`, supplier-scoped
Material Inventory viewing and reporting from `20260727_101728`, and adds
chosen-date Excel/PDF exports to the Daily Sewing Report from
`20260727_102911`. It also aligns the production Daily Sewing Report section
constraint with the existing UI/API limit of 20 sections. Fully depleted,
unreserved material batches that already have operational usage can now be
removed from active inventory without a second stock deduction: the batch is
archived while its movements and production links remain available for
traceability. Used batches with remaining stock and batches with active
reservations remain protected. Alembic is at
`0073_archive_depleted_batches`. The Models/PLM list now sorts all model groups
by model name A-Z before pagination by default, with user-selectable name,
model-number, newest, and oldest ordering. Release/image `20260728_052922` is
an older rollback. Planning branded-stock model selection now uses lightweight
server-side approved-model search instead of downloading all 6,516 approved
models with full images/BOM/details. Planning history separately loads display
details only for model IDs it actually references, preserving thumbnails and
fabric labels. The Packaging work-order page now clears a stale package
creation error as soon as the operator submits a new packaging record, so the
newly available full and partial package plan is not obscured by an error from
the earlier quantity state. Planning now assigns the destination sewing
factory—Milana (`MIL`), Besttex (`BST`), or Eco Cotton (`ECO`)—when creating
either client or branded-stock production. The sewing work order is created
under that factory department, and new Cutting bundles inherit the same
factory route. Cutting Bundle Inventory shows the factory per production order
and lets authorized Planning or Cutting users reroute all waiting bundles. The
API blocks rerouting after a sewing assignment, sewing receipt, or sewing
execution starts and audits successful changes. Internal sewing-line selection
remains a separate later-stage operation. Release/image `20260728_061308`
contained the superseded sewing-line interpretation; `20260728_060621` is the
safer functional rollback for this feature.
On 2026-07-28, production workflow/order test data was reset for a clean
operational start without changing the active application release. The guarded
transaction cleared all Sales, branded Planning, Production, Work Order,
Cutting, Sewing, Packaging, Bundle, Package, Finished Goods, Shipment,
order-linked purchasing, reservation, waste, payroll-QR, and Daily Sewing
Report rows, plus one package-change request. It also removed 81
workflow-linked notifications while preserving 23 admin notifications and the
full audit history; one `workflow_reset` audit entry records the action. All
affected identity sequences were reset, so new workflow IDs start from 1.
The 6,516 models and every protected catalog/material-inventory row remained
byte-for-byte unchanged by canonical row fingerprint: 58 items, 336 stock
batches, 423 stock movements, 11 warehouses, 5 suppliers, 1 brand, 11,884
model images, 24,529 model sizes, 5,065 model colors, and 42 BOM rows.
All 2,752 generated bundle/package barcode files were archived and removed;
model files and material pictures were not touched.
On 2026-07-28, production model variant `TJ-2064-V-5591` (model ID 7044)
was corrected from the generic `Suprem` material master (item ID 2) to
`30/1 P_CPM SUPREM` (item ID 27), matching available fabric batch `4461`.
Only the variant fabric metadata and its existing fabric BOM row (BOM ID 63)
changed; sizes, images, colors, quantities, and other model data were
preserved. A verified custom-format PostgreSQL backup was taken before the
correction, and an audit entry records the change.
Release `20260728_113559` lets Planning select any available fabric batch for
a branded-stock production, regardless of the fabric configured on the model.
The backend still requires the selected inventory batch to be a fabric or
semi-finished material with positive available stock. The chosen batch's
actual material master is carried into reservations so Cutting uses the
operator-selected stock rather than the model BOM's fabric. This supersedes
the narrower Suprem-family rule in `20260728_105903` and the failed initial
family-query implementation in `20260728_105320`.
Frontend authentication now distinguishes an explicit HTTP 401 from temporary
network/server errors. Temporary failures retry without clearing the HttpOnly
cookie or hiding already-loaded user data. A stale tab may redirect itself
after a confirmed 401 but can no longer call `/api/auth/logout` and destroy a
newer shared browser session. Manual logout remains unchanged. Department
inboxes now resolve the browser timezone before creating their SWR key, so
initial navigation makes one inbox request instead of UTC followed by
Asia/Tashkent; normal same-key background refresh keeps rendered data in
place. The follow-up production incident was traced to SQLAlchemy QueuePool
exhaustion (the former 5-connection pool plus 10 overflow connections) and
browser request starvation from hidden-tab polling and hundreds of eager
Material Inventory thumbnails. The active release uses a 15-connection pool
with 10 overflow connections, stops live polling while tabs are hidden,
revalidates immediately on focus/reconnect, and lazily loads inventory
thumbnails. A failed initial `/api/auth/me` check now keeps retrying and shows
an explicit Retry action instead of an endless full-page loader; it never
logs the user out for a transient failure. Two signed-in production reloads
kept the session, rendered the Material Inventory shell, and produced no
browser console errors; the live backend logs showed HTTP 200 for `/api/auth/me`
and inventory endpoints with no new QueuePool timeout. Release/image
`20260728_094050` is the immediate rollback; `20260728_063031` is the earlier
authentication rollback.
The ASTATKA ready-stock import remains removed; model-less legacy sales
support is still present in the active code and migrations but has no imported
ASTATKA stock to act on.

The reviewed old-ERP catalog is now live in production: 6,404 source identities
were verified exactly once, with 5,637 new models and 767 existing models
enriched without changing any of the 881 pre-existing names, codes, or image
rows. Production now contains 6,518 models, 11,884 model-image rows, 24,535
model-size rows, 5,065 model-color rows, and the unchanged 42 BOM rows.
All 6,518 production model/variant rows are approved as of the later
2026-07-27 catalog-wide approval described below.
All 69 protected operational table snapshots were unchanged. Fourteen
unresolved identities covering 23 old records remain quarantined and must not
be guessed.

The verified pre-code custom PostgreSQL backup is
`/var/backups/milana-erp/pre_old_erp_models_code_20260727_075027.dump`
(873 restore-list entries; SHA-256
`9006c0efef0cedc015f8b0fcd7171c41e15b0f69553b11ea394b2269babf2d05`).
The final pre-data plain backup is
`/var/backups/milana-erp/pre_old_erp_models_20260727_075027.sql`
(SHA-256
`8b8ff1f8fcf6dced6a5a40524bede6d9bd4a5196a80718af763404f76a3a1c21`),
and the rollback-complete media backup is
`/opt/milana-erp/shared/backups/pre_old_erp_model_media_20260727_075027_regular.tar`
(SHA-256
`40e42ea4756aad624a65e52920ad2724b3abc681fed25563aa7785f336850063`).
Older verified PostgreSQL backups remain stored as
`pre_inventory_reports_20260724_040430.dump`,
`pre_variant_image_fix_20260724_062842.dump`, and
`/var/backups/milana-erp/pre_models_performance_20260727_062443.dump`
(858 restore-list entries; SHA-256
`ceb127b3ebb7c9747229c431f4034b4626dd78b26974a086370fc3bedfc15c4d`).
The pre-import backup remains
`pre_astatka_ready_stock_20260725_045504.dump` with SHA-256
`33f105a084d5cd14114a43951444e0369c427ccbf254fc91272c24eceb316e5e`.
The verified backup immediately before removing the ASTATKA import is
`/var/backups/milana-erp/pre_astatka_ready_stock_purge_20260725_091323.dump`.
Its restore list contains 873 entries and its SHA-256 is
`94a341eef416792d37b501637fcaecb00f7dbefa51b125173a2ae4b446de107a`;
a matching local copy is retained under
`.codex-work/astatka-ready-stock-purge-20260725/backups/`.
The verified backup immediately before the supplier-scoped Material Inventory
release is
`/var/backups/milana-erp/pre_supplier_inventory_filter_20260727_101728.dump`.
Its restore list contains 873 entries, it is 25,156,362 bytes, and its SHA-256
is `8fbdd7399f35e1af77b784b7d77a709f2ca1173befce581f09822ab87a8efb98`.
The verified backup immediately before the Daily Sewing Report export release
is
`/opt/milana-erp/shared/backups/pre_daily_sewing_exports_20260727_102911.dump`.
Its restore list contains 873 entries, it is 25,160,670 bytes, and its SHA-256
is `2f508d3b7b8322530936f1bad9ca46b7f59564a2c9d0865a95ac20568771d02a`.
The verified backup immediately before expanding the Daily Sewing Report
section constraint is
`/var/backups/milana-erp/pre_sewing_section_limit_20260728_031503.dump`.
Its restore list contains 873 entries, it is 25,162,188 bytes, and its SHA-256
is `66857b7ac0f91804d9ab620dcd38095a9357851511f96757b9a9b183eabbff87`.
The verified backup immediately before enabling depleted used-batch archival
is
`/var/backups/milana-erp/pre_depleted_batch_archive_20260728_052922.dump`.
Its restore list is readable, it is 25,165,107 bytes, and its SHA-256 is
`c9e3dc92a055e06a42029ab09b5ccba3be185199fab5b09eaea3114448d291af`.
The verified backup immediately before the Packaging stale-notice fix is
`/opt/milana-erp/shared/backups/pre_packaging_stale_notice_20260728_060621.dump`.
Its restore list contains 875 entries, it is 25,170,329 bytes, and its SHA-256
is `f0240e7b99d7c9af68ea43a1097e5300f511174b1dc0dee31ed951eb4121eedd`.
The verified backup immediately before deleting mistaken branded-stock
production order `PO-2026-000037` is
`/var/backups/milana-erp/pre_po37_full_delete_20260725_175650.dump`. Its restore
list contains 873 entries, its SHA-256 is
`2dd08def4e911775fb9dcb601233b319e4a0de79d313554a388de04805c304dc`,
and a matching local copy is retained under
`.codex-work/po37-delete-20260725/backups/`.
The verified backup immediately before the full test workflow reset is
`/var/backups/milana-erp/pre_workflow_reset_20260728_091543.dump`. It is
25,168,819 bytes, its restore list contains 875 entries, and its SHA-256 is
`7801e3b4450be39f09d857dc8206737892ae53cb86102e49036ddec50fb6a918`.
The matching generated-barcode archive is
`/opt/milana-erp/shared/backups/pre_workflow_reset_barcodes_20260728_091543.tar.gz`;
it contains 2,752 files, is 1,550,940 bytes, and has SHA-256
`25951d793a7453f5de12e9d163a33bd6add6050a526f89b26b66b9fe13bb0b3a`.

Do not assume that same-day changes deployed after `20260723_065753` are still
active in production. Reverify before relying on:

- Per-batch material picture isolation.
- Restored Cutting access to Sewing Flows, Daily Sewing Report, and Sewing
  Floor.
- Daily Sewing Report Kroy number and two-part top/bottom quantity changes.
- Any other release created after `20260723_065753`.

The sales-to-warehouse shipping improvement was implemented and tested in the
local workspace, but the production deployment containing it was rolled back.
The desired behavior remains:

- Warehouse notification names each model/variant, color, size, quantity,
  customer, and destination.
- Notification opens the exact order in the shipping queue.
- Warehouse queue shows item-level details, not only address and total
  quantity.

At the time this context was written, the local Git working tree was very dirty,
contained extensive uncommitted work, and was 11 commits behind `origin/main`.
Always run fresh Git checks. Do not deploy by blindly taking only local HEAD or
only GitHub. First reconcile the production release, GitHub, and current local
changes in a clean staging checkout/worktree without altering the user's
working tree.

### Cutting Nastilchi Field

On 2026-07-29, a cutting change added an optional Nastilchi (layup
operator) name to each `CuttingRecord`. The Cutting work-order form saves the
name through the production API, and the A4 Cutting Sheet prints it in the
identity section. This business name is separate from the authenticated ERP
operator used for audit ownership. Older records fall back to the linked
Cutting Passport's manual operator name when available. Alembic migration
`0074_cutting_nastilchi` adds the nullable field; the local migration chain
from `0070` through `0073` was reconciled from the verified active production
source so the new migration has a valid parent. Focused backend flow and sheet
tests, Ruff, frontend typecheck, i18n validation, lint, and the production
frontend build passed. It was deployed in production release
`20260729_090547` with Alembic `0074_cutting_nastilchi`; no existing business
rows were changed.

## Local Old-ERP Model Migration

On 2026-07-25, the old ERP model catalog was migrated to localhost only for
review. The migration did not target, change, or deploy production. The frozen
source contained 3,065 model rows and 5,153 variant rows. Reconciliation
created 4,408 variants and 1,218 standalone models, bringing the local catalog
to 6,505 models, 11,856 image rows, 24,355 size rows, and 5,046 color rows.
Model BOM and all operational order, stock, package, shipment, user, and
finance data remained unchanged.

Duplicate reconciliation treats the current ERP as authoritative: existing
model names, codes, and pictures are immutable, and only missing metadata or
variants may be added. Twenty-nine ambiguous or conflicting source identities
were quarantined instead of guessed. A deterministic metadata correction
filled missing fields on 291 records created by the import; it did not target
pre-migration models or create additional catalog rows or files.
The final fixed-planner dry run was fully idempotent with zero catalog,
metadata, provenance, or media actions. An independent post-correction audit
passed 27/27 checks across all 71 database tables, 63 operational aggregates,
all 29 quarantines, and the complete 8,163-file media inventory.

The auditable source, plans, reports, quarantine list, and integrity inventories
are under
`.codex-work/old-erp-model-migration-local/2026-07-25T09-18-06-117Z/`.
Verified pre-import and pre-correction database/media backups are retained
under `local-backups/`. At migration handoff on 2026-07-25, the local database
remained at Alembic revision `0064_remove_fabric_pictures` and the backend was
deliberately not restarted.
For review, an isolated temporary frontend is bound to loopback at
`http://localhost:3001/models` because the pre-existing port-3000 frontend
proxy was returning errors. The catalog and representative `PJ-1106` master
and variant pictures were verified in that preview. The production release
remains `20260725_062442`.

On 2026-07-27, the stalled local Docker Desktop engine was recovered so the
localhost administrator credential could be rotated at the user's request.
Restarting the existing ERP containers advanced the local database to Alembic
revision `0069_legacy_finished_goods`. The local backend image was rebuilt to
install the already-declared `openpyxl` dependency, after which health and an
authenticated Super Admin login both returned HTTP 200. Previous sessions
were revoked and the reset was audit-recorded. No credential value is stored
in this context, and production was not changed or deployed.

Later on 2026-07-27, the localhost-only model migration was corrected from a
complete, hash-pinned extraction of the old ERP. The current old source has
3,072 model rows and 5,163 variant rows; its complete-detail evidence contains
28,272 operation rows and 1,929 recipe rows. For the original 3,065-model
receipt scope, 6,394 imported model records received missing legacy details
and 4,629 safe display names were changed to the exact old `Product` value.
Existing duplicates remained authoritative: their names and picture rows were
not changed, including eight source conflicts that were deliberately
preserved.

The reviewed append-only delta created ten variant model rows and enriched one
exact duplicate without changing that duplicate's name or pictures. It added
20 image rows, 29 size rows, and 10 color rows. The final local catalog has
6,515 models, 11,876 image rows, 24,384 size rows, and 5,056 color rows.
Model BOM and every checked order, stock, package, shipment, item, and finance
count remained unchanged. Seven new models whose authenticated source
operation list was empty were explicitly stored with zero paid operations;
the final repeat dry run had zero remaining creates, updates, renames, media,
size, or color actions.

The port-3000 localhost frontend now shows Product-based names, complete old
ERP provenance, recipes, and the expanded paid-operation fields. Browser QA
verified model `6113` (`TJ-2053`, 30 operations), model `7943`
(`PJ-1203-5581`, one recipe and zero source operations), model `7948`
(`XJ-3062-5583`, 45 operations), and protected duplicate model `6658`.
Fourteen unresolved identities covering 23 old model records remain held for
an explicit conflict policy; 22 have incompatible pictures and/or colors and
record `1683` has no usable identity. They must not be merged or split by
guessing.

The complete-correction artifacts are under
`.codex-work/old-erp-model-complete-correction-local/2026-07-27T03-41-35-375Z/`.
The latest pre-apply plain PostgreSQL backup is
`local-backups/pre_local_explicit_empty_paid_ops_20260727_104145.sql`
(SHA-256
`6e28a4024e704375193e1b6891cee272dd3dd411e9d78c67d49ccca8144b4e92`);
the verified current media snapshot is backed by
`local-backups/pre_local_delta_product_name_media_20260727_102802.tar`
(SHA-256
`f0ad89223f87bf6ec55a476e9163cac8d8a99b143f43ec5fe8511bd4cc291e31`).
This work touched localhost only; production was not changed or deployed.

Also on 2026-07-27, the localhost Models/PLM list was optimized after the
completed migration made its original all-record grouping query too slow.
Variant-group pagination now uses a lightweight identity pass, selects whole
groups, and hydrates only the requested page. Model-image binary data is not
loaded for list requests, and the frontend opts into a compact response that
keeps the names, model/variant identity, translations, composition, pictures,
and fabric information used by the list while omitting large migration-detail
sections that are only needed on model detail pages. The default API response
remains compatible.

The list now keeps existing rows during refresh, shows an accessible loading
indicator on first load and pagination, distinguishes errors from a successful
empty result, avoids off-screen card layout work, and disables repeated model
card prefetches. Signed-in localhost browser timings improved from about 3.30
to 1.81 seconds for 100 groups, from 4.35 to 2.55 seconds when selecting 500
groups, and from 4.79 to 2.85 seconds for page two at 500 groups. The page-one
backend path fell from 29 SQL statements and about 3.51 seconds to 4 statements
and about 1.66 seconds with the compact response; its decoded response shrank
from 531 KB to 127 KB. Catalog tests, Ruff, strict TypeScript, targeted ESLint,
translation parity, the production frontend build, health checks, and browser
loading-state checks passed. No database rows were changed. This optimization
was first reviewed on localhost. A production-adapted, five-file version was
subsequently deployed as release `20260727_062443` without importing any
localhost model or media data.

### Production Old-ERP Model Migration

On 2026-07-27, the reviewed model package was deployed to production through
release `20260727_075027`. The frozen package SHA-256 is
`941457e0299c8876b1cf5fe164c4238ef6d4085543a631c6706e67162eba2e85`.
The deterministic production plan SHA-256 is
`ca95920695d930d81d0026a5d48acc30cd1fe6378e239cc06f3d81ff67854483`;
the applied report file SHA-256 is
`d30cf15e2edba42e82d98f815af1d9e3932a18e998d4de94976d30676396318e`.

The migration processed all 6,404 reviewed identities: 5,637 were created and
767 exact duplicates were enriched. It added 9,580 image rows, 23,534 size
rows, 5,056 color rows, and 22,867 paid-operation entries. New model display
names use the old ERP `Product` field. Existing duplicate names, codes, and
pictures remained authoritative and were not changed. Recipes and complete
old-ERP provenance are shown on model detail pages. Seven authenticated
source records with empty operation lists remain explicitly represented with
zero paid operations.

The independent verifier passed with all 6,404 migration receipts present
exactly once, zero duplicate canonical identities, all 881 pre-existing model
name/code/image snapshots unchanged, and all 69 operational table hashes
unchanged. The final media inventory contains 8,584 files totaling
3,138,157,547 bytes; 4,966 files were newly created, while ten planned targets
already existed with identical content. The verifier file SHA-256 is
`afc2376ab15262afa54d121908f6d2b2b47e1b5780860bfe5e99b860a99b9432`.

Signed-in production browser QA checked model `5227` (`TJ-2053-879`, Product
name and 30 paid operations), model `3993` (`PJ-1203-5581`, one recipe and
zero source operations), model `6492` (`XJ-3062-5583`, 45 paid operations),
and protected existing model `3` (`TJ2026-V-4248`). Model `3` kept its exact
original name and primary picture while receiving missing old-ERP details.
The production catalog displayed its loading indicator and rendered 100 of
2,021 variant groups in about 2.1 seconds. Backend/internal, frontend/internal,
public health, and public login checks all returned HTTP 200; service logs
showed no deployment errors, and the signed-in browser console was empty.

Later on 2026-07-27, the user authorized approving the complete production
model catalog. One approval was made from the visible Models button and the
remaining 5,637 draft model/variant rows were approved sequentially through
the exact same canonical approval action. The final status is 6,518 approved
and zero draft models. Every approval records the System Admin approver,
timestamp, and audit entry. The verified pre-approval custom PostgreSQL backup
is
`/var/backups/milana-erp/pre_approve_all_models_20260727_085500.dump`
(873 restore-list entries; 24,405,205 bytes; SHA-256
`47ca688bb7a01afddf5576e9a12abd1d373bcce28afaf7f492b356caf4365309`).
Independent post-apply checks confirmed the model identity hash and all model
image, size, color, and BOM snapshots were unchanged; only approval metadata
and the expected 5,638 approval audit records changed. The post-verification
dry run found 6,518 approved models and zero remaining approval targets. All
four production health checks returned HTTP 200, service logs were clean, and
the Models UI showed no remaining Approve actions. The complete approval
evidence is under
`.codex-work/old-erp-model-production-migration-20260727/production-evidence/approval/`.

Also on 2026-07-27, release `20260727_092334` corrected the three Models/PLM
filter fields so they search the full server-side catalog before pagination
instead of filtering only the rows loaded on the current page. The frontend
debounces requests by 250 ms and keeps the existing loading indicator. The
release candidate was built from the exact active `20260727_075027` release
and changed only the catalog route, its regression tests, and the Models page.
The 15 catalog tests, Ruff, strict TypeScript, targeted ESLint, and the
production Next.js build passed. Signed-in production browser QA found
off-page records by model/variant number, name, and category, each with the
correct single result and no console errors. Both internal services and both
public endpoints returned HTTP 200, and the backend and frontend logs showed
no deployment errors. No database rows or schema were changed.

The verified pre-deployment custom PostgreSQL backup is
`/opt/milana-erp/shared/backups/pre_model_search_20260727_092334.dump`
(873 restore-list entries; 25,160,197 bytes; SHA-256
`25d928761b6ed86a2028d1e2066e301e21a0e036737e31738041675639a7cab7`).
Deployment evidence is under
`.codex-work/model-search-full-catalog-20260727/20260727_092334/`.

Fourteen unresolved identities covering 23 old model records remain
quarantined. The complete production package, backups, reports, verifier, and
run evidence are under
`.codex-work/old-erp-model-production-migration-20260727/` locally and
`/opt/milana-erp/shared/migrations/old-erp-models-20260727_075027/` on the
backend VM. The migration's original application rollback is release/image
`20260727_062443`; complete data rollback uses the verified pre-data database
and regular-file media backups listed in Current-State Warning. For the later
search-only release, the immediate application rollback is `20260727_075027`.

## Stable Business Rules

- The ERP must reflect real factory handoffs; do not add disconnected demo
  screens.
- Creating a Production Order starts Cutting automatically.
- Optional stages such as Printing must be skipped automatically when not
  required.
- Cutting overproduction becomes the real downstream planned quantity for
  Sewing, Packaging, and Storage.
- Cutting shortfall may close Cutting while remaining replacement work is
  tracked separately.
- Work must remain traceable by sales order, production order, work order,
  batch, bundle, package, model, variant, size, and responsible department.
- User-facing screens should show real names/numbers, not raw database IDs.
- Sales prices are net; tax calculation was removed.
- A branded-stock pack is commonly treated as 60 pieces where that flow
  applies.
- Package creation must respect the selected batch's packed quantity, including
  partial packages.
- Finished-goods stock must come from validated packaging/receipt evidence;
  never create stock casually for testing.
- Old ready-product balances may remain model-less when no exact current model
  exists, but must retain immutable source receipt evidence and their original
  source model code/name for search, stock display, labels, and shipment work.
- Material and accessory quantities use kilograms where applicable.
- Material pictures may belong to the model/BOM, shared material item, or exact
  stock batch. Batch-row uploads must affect only that batch. An assigned batch
  picture is operational material evidence and must not replace a model or
  variant identity picture.
- Model variants are primarily differentiated by variant number,
  fabric/color/pattern, and picture while remaining selectable for new orders.
  Process Tracking and Production Order identity surfaces must use the same
  canonical variant picture shown in Models.
- Employees may edit after deadlines; the post-deadline admin restriction was
  removed.
- Deletions must be narrowly scoped and blocked when records are already
  reserved, linked, or used.

## Departments and Special Production Flows

- Standard flow: Cutting -> optional Printing -> Sewing -> Packaging ->
  Finished Goods.
- Besttex has its own textile flow and packaging path.
- Eco Cotton has dedicated Cutting and Sewing departments/inboxes; Planning can
  route work to Main Cutting or Eco Cotton Cutting.
- Replacement work from Sewing defects goes back to Cutting, keeps the
  originating sewing line, and remains visible to Packaging as outstanding
  replacement quantity.
- Cutting Inventory holds created bundles until Sewing or Printing scans and
  receives them.
- Sewing lines were consolidated/renamed in earlier work. Read current live
  names and mappings from production before another migration.
- Sewing-role navigation is intended to show only Sewing Flows, Daily Sewing
  Report, and Sewing Floor, plus the internal work-order sewing action needed
  to record finished work.
- Cutting users were intentionally given access to the three Sewing workspace
  pages as an exception.
- On 2026-07-24, a user-approved duplicate-production cleanup retained the
  older `PO-2026-000038` and deleted the unused newer `PO-2026-000039`.
  The two orders had identical planning group, model, fabric, six size lines,
  600-piece quantity, deadline, and untouched waiting work orders. The deleted
  order had no batches, cutting records, bundles, reservations, or downstream
  links. Its six item rows and four work orders were removed atomically, and
  audit record `#3564` preserves the deletion evidence.
- On 2026-07-28, release `20260728_060621` fixed the Packaging work-order
  screen's stale package error. Work order 110 had 828 pieces packed, 720
  already assigned to twelve packages, and a valid 108-piece balance for one
  60-piece package plus one 48-piece package. The red `available 0` error came
  from an attempt made before the 108-piece packaging record was saved; the
  save refreshed the balance but did not clear that earlier message. The page
  now clears the package notice when a packaging record is submitted. The
  production validator accepts both remaining quantities. Deployment changed
  one frontend file only; order 27 remained at 828 packed, 720 packaged, and
  twelve packages. The clean candidate passed strict TypeScript, targeted
  ESLint, production frontend/backend builds, Alembic head, source hashing,
  clean service logs, and all four required health checks. No package, order,
  stock, or schema data changed. Immediate rollback is release/image
  `20260728_055733`.
- On 2026-07-28, release `20260728_063031` corrected planning-owned sewing
  routing to select a factory department, not an internal sewing line.
  Client-order and branded-stock production forms require Milana (`MIL`),
  Besttex (`BST`), or Eco Cotton (`ECO`). Work-order creation assigns the
  sewing work order to that department, and Cutting's bundle form inherits the
  choice automatically. Cutting Bundle Inventory shows the factory and
  provides a compact change-and-save control for all waiting bundles. The
  dedicated update API accepts Planning or Cutting permissions, synchronizes
  sewing and external-factory packaging destinations, audits changes, and
  returns HTTP 409 after assignment, receipt, or sewing work begins. Internal
  sewing-line assignment remains unchanged and separate. Release
  `20260728_061308` was superseded because it interpreted the request as a
  sewing-line selector. No production order, bundle, stock, or schema data
  changed during the correction deployment. Verification covered
  Ruff/compileall, strict TypeScript, targeted ESLint, production frontend
  builds locally and on the VM, 14 focused backend tests, deployed-source
  checks, Alembic head `0073_archive_depleted_batches`, and all four health
  checks. Chrome UI inspection reached the live login page but the saved
  session had expired, so no credentials or business data were entered.
  Immediate technical rollback is `20260728_061308`; use
  `20260728_060621` to avoid restoring the superseded line-selector behavior.

## Daily Sewing Report

This is a reporting ledger and is not supposed to mutate the main production
workflow automatically.

Important intended behavior:

- User chooses a sewing line and may select the active work from Sewing Floor.
- Order, model, variant, and Kroy number are detected where available.
- Model/variant and Kroy number can be entered manually when no
  order/model/passport is attached.
- Kroy number should come from the latest Cutting Passport when available.
- Reports record sewn quantity, defects, defect reason, and work date.
- Users can add more sections/work rows.
- Each section has a "2-part garment" checkbox:
  - Off: one sewn quantity.
  - On: separate Top quantity and Bottom quantity.
- Saved reports and summaries retain the manual identity and section
  quantities.
- A manual model identity is mutually exclusive with a production work-order
  identity. Manual entry must not inherit a selected model's image, name,
  variant, work order, sewing assignment, production order, or batch.

Because of the 2026-07-23 rollback, verify which of these fields are currently
live before making follow-up changes.

On 2026-07-28, release `20260728_031734` fixed the production-only failure
where the UI and request schema allowed up to 20 Daily Sewing Report sections
but PostgreSQL still rejected `section_no > 3`. Migration
`0072_sewing_report_sections` replaces the old `1..3` check with `1..20`, and
the model metadata now declares the same rule. A rolled-back production insert
proved section 4 is accepted and left zero verification rows. The affected
2026-07-27 save remains exactly three committed rows totaling 1,000 pieces;
the rejected 246-piece fourth section was not created or altered automatically.
Eight focused backend tests, Ruff, compilation, migration SQL review, frontend
production builds, clean service logs, Alembic head, and all four required
health checks passed. Failed candidate `20260728_031503` stopped before
cutover because its first revision identifier exceeded the legacy 32-character
Alembic column; PostgreSQL rolled it back and the candidate was never active.

## Inventory, Models, and QR

- Material Inventory and Accessory Inventory are separate views.
- On 2026-07-29, production Material Inventory was reconciled to five
  user-supplied supplier workbooks. The frozen source set contained 79 positive
  balance rows totaling 30,648.99 kg and 1,335 rolls/pieces. A guarded,
  serializable transaction created 37 missing batches and matching receipt
  movements, four precise material masters, and supplier `Asaka Textile`;
  corrected seven proven transcription/attribution errors on batches `114`,
  `117`, `416`, `424`, `446`, `454`, and `467`; and removed duplicate batches
  `112` and `470` while retaining source-exact batches `111` and `466`. The
  committed delta was +35 positive lines, +10,897.76 kg, and +472
  rolls/pieces. The immediate verified production state was 57 positive
  material types, 351 positive lines, 109,524.92 kg, and 5,033 rolls/pieces;
  all 79 source rows were covered. Eight optimized source photos were added.
  The two now-unreferenced duplicate photos were moved recoverably to
  `/opt/milana-erp/shared/backups/material_inventory_reconcile_20260729_084536/deleted_images/`.
  The immediate custom backup is
  `/opt/milana-erp/shared/backups/pre_material_inventory_reconcile_20260729_084536.dump`
  (25,198,754 bytes, 860 restore objects, SHA-256
  `ce4fd069e5208d2af450a94b1643cbba3768b1265bba5d81dc9050d9d5a0de07`).
  The 52 new audit entries form a valid hash-chain segment, although the
  pre-existing global failure at audit record `#744` remains.
  Duplicate-looking batches `113/416` and `205/206` were not auto-deleted
  because their source images prove distinct physical rows; supplier masters
  `masis` and `MASIS` also remain separate. Active release/image stayed
  `20260729_034138`. Signed-in QA found the Asaka `23302` row and exactly one
  result for each deduplicated lot `5249` and `652/07`; all four health checks
  returned HTTP 200, two backend workers remained healthy, and recent logs had
  no 5xx or traceback.
- On 2026-07-25, the user-approved `astatka.xlsx` ready-product balance was
  imported into production: 1,232 positive source rows and 437,636 pieces.
  Exact matches linked 305 rows (109,826 pieces) to existing models; 927 rows
  (327,810 pieces) were stored model-less with their original source identity.
  No models, model sizes, model colors, brands, or aliases were created. Five
  negative source rows were excluded (`PJ-1016-v1163` -6,
  `SJ-4044-v3372` -210, `xj-3062-v3903` -60, `tj-2170-v4478` -45, and
  `pj-1169-v4872` -60); the last row's separate +60 entry was also excluded
  because the pair nets to zero. The import created one immutable receipt,
  package, package item, finished-goods row, and storage scan per accepted
  source row. Post-import production totals were 1,255 packages, 1,370
  finished-goods rows, 438,976 pieces, and 438,376 available pieces; the model
  count remained 881. Database reconciliation, signed-in warehouse search for
  model-less item `F-2544`, migration `0070_model_less_legacy_stock`, focused
  regressions, frontend build/type checks, and all four production health
  checks passed. Audit record `#3632` records the import.
- Release `20260725_054453` added direct sales support for those old balances.
  A sales line can reference the exact finished-goods row and snapshot its
  original source model code/name while leaving `model_id` null. The sales form
  searches current and old ready stock together, reserves only the selected
  stock row, and shipment consumption supports partial sales from an aggregate
  legacy package without incorrectly selling the remainder. Migration
  `0071_model_less_legacy_sales` is active. A signed-in production check found
  1,140 sellable product/variant choices and successfully searched and selected
  `F-2544` as a 60-piece full pack without creating a test order. Production
  reconciliation still showed 881 models, 1,232 legacy receipts/packages,
  437,636 imported pieces, and zero imported reservations/sales immediately
  after deployment.
- Release `20260725_062442` removed the generic Incoming, Pending, In Progress,
  and Done Today columns from `/departments/FGS` only. The Finished Goods page
  now opens directly to Pending Package Intake and Ready to Ship. A signed-in
  production check confirmed both operational tables remained visible, the
  four workflow columns were absent, all four health checks passed, and no
  business data changed.
- Later on 2026-07-25, the user reversed the ASTATKA ready-stock decision and
  approved complete removal. A guarded transaction deleted exactly 1,232
  `ASTATKA_XLSX` receipts, packages, package items, finished-goods rows, and
  import scan logs totaling 437,636 pieces. The import had created zero catalog
  models; all 881 real models, including the 305 that had only been referenced
  by imported stock, were preserved.
- The only downstream use was a 120-piece reservation and package link for
  `SO-2026-000002` and `SH-2026-000002`. Both records were retained for audit
  and changed to `cancelled`; the reservation and shipment-package link were
  removed before the imported stock was deleted. Audit records `#3648` through
  `#3650` record the two cancellations and purge.
- Post-purge reconciliation shows zero legacy receipts, 23 packages, 1,340
  finished-goods pieces, 740 available pieces, 600 reserved pieces, zero sold
  pieces, and 881 models. All four health checks returned HTTP 200. No code
  release was deployed; active release remains `20260725_062442`.
- Inventory has searchable material/accessory groups and master-data management
  for materials, accessories, and suppliers.
- Mubina has narrowly scoped access to delete unused duplicate stock-batch
  rows; used/reserved rows must remain protected.
- On 2026-07-24, Fabric Storage stock-batch deletion was fixed for PostgreSQL.
  The delete query now locks only the `stock_batches` row instead of also
  locking the nullable eagerly joined material row, which previously caused a
  500 before safety checks ran. Receipt movements are also explicitly flushed
  before their parent batch is deleted, avoiding a PostgreSQL FK-ordering
  failure. Release `20260724_120725` passed all 23 inventory regression tests
  and all four required health checks.
- On 2026-07-24, a user-approved production-data correction changed
  `SO-2026-000033` from the wrong `4958 / Rotation` fabric row to the existing
  `4958 / SEKER SAKAR` row (559.6 kg). The now-unlinked wrong `Rotation` row
  containing 300 kg and its lone receipt movement were deleted atomically.
  Audit records `#3562` and `#3563` record the relink and deletion. No other
  inventory or production-order rows were changed.
- On 2026-07-25, the user confirmed that public order
  `SO-2026-000037`—the UI alias for standalone branded-stock
  `PO-2026-000037`—was entirely mistaken. A guarded, rollback-rehearsed
  transaction deleted exactly 1 production order, 6 production items, 4 work
  orders, 1 production batch, 1 cutting record, 6 untouched bundles, 6
  creation-only bundle scan logs, 1 recorded waste row, and 4 stale sewing
  notifications. There were no sales-order, package, shipment,
  finished-goods, reservation, payroll, invoice, or payment links.
- The mistaken cutting entry had consumed 256 kg from Fabric Storage batch
  `4958`. The cleanup restored that batch from 303.6 kg to 559.6 kg and
  retained original consume movement `#497` with compensating return movement
  `#499`. Shared planning order `0029`, sibling `PO-2026-000038`, model
  `Х-3044 / V-5567`, and all catalog/material records were preserved.
  Deletion audits are `#3657` and `#3658`; their new hash-chain segment passed.
- The six generated bundle QR files and six barcode files were archived and
  removed from live storage. Signed-in Cutting, Milana Sewing, and Production
  Orders pages contain no `SO-2026-000037`, `V-5567`, or links to work orders
  `152`/`153` or production order `37`; sibling `SO-2026-000038` remains
  visible. All four required health endpoints returned HTTP 200. No code
  release was deployed; active release remains `20260725_062442`.
- Reservations connect planned production to stock, and cutting consumption
  should not drift from reservations.
- Models and materials can have pictures; list pages use thumbnails for
  performance.
- On 2026-07-24, branded-stock Planning was fixed so a model without fabric
  BOM rows no longer hides Material Inventory batches or blocks order
  creation. The picker lists all positive, QC-accepted material batches,
  prioritizes exact BOM-item matches when present, and preserves a valid
  manually selected non-BOM batch. Production release `20260724_094140` was
  verified in the signed-in UI with model `ТJ-2107-3553` and batch `4957`
  (`Suprem`, 548.8 kg available), by frontend type/i18n/build checks, and by
  all four required health checks. No production order or stock movement was
  created during verification. Empty verification planning group `0032` was
  cancelled with zero productions and an audit record; the user's pre-existing
  open planning group `0031` was left unchanged.
- On 2026-07-23, the DINAR 2025 material workbook was imported into production:
  255 source rows, 66,653.51 kg, and 2,693 pieces/rolls were reconciled exactly.
  The import created 23 material masters and 254 stock batches; the previously
  tested batch 7758 was retained as the one exact existing row. Pictures were
  attached to all 198 rows that had embedded workbook images; 57 source rows
  had no embedded image. Because the ERP requires a batch number, the three
  blank source batches use traceable IDs `DINAR-XLSX-R6`, `DINAR-XLSX-R69`, and
  `DINAR-XLSX-R110`. No deployment or code release was performed for this
  operational data import.
- On 2026-07-23, the current positive balances from the SAFF workbook
  `Cафф.xlsx` were reconciled into production: 26 rows, 17,245.55 kg, and 475
  rolls. Four equivalent batches (`7450`, `7451`, `7678`, and `7679`) already
  existed and were retained; the source's stray leading backtick on `7679` was
  treated as the same batch. The import created 11 material masters and 22
  stock batches totaling 14,883.12 kg and 354 rolls, increasing the batch
  ledger from 377 to 399 rows. All 23 source rows with embedded pictures have
  batch pictures in the ERP; three source rows had no picture. New rows use
  supplier Saff, Fabric Storage, and QC status Qabul. No deployment or code
  release was performed.
- On 2026-07-24, the Samo positive-balance workbook was imported into
  production: 11 stock rows, 6,297.08 kg, and 285 rolls. Because the workbook
  contains no fabric names and the ERP requires every batch to have a material,
  the import created 11 independently renameable temporary masters named
  `Material pending - Samo - <batch>`; repeated batch numbers also include the
  Excel row suffix (`R2`, `R3`, etc.). All 11 workbook pictures are attached to
  their exact batch rows. New rows use color code `C0001`, supplier Samo,
  Fabric Storage, and QC status Qabul. The batch ledger increased from 399 to
  410 rows. These 11 temporary material names remain operational follow-up
  work; no deployment or code release was performed.
- On 2026-07-24, the inventory batch editor was deployed so Material Name
  selects an existing same-group, same-unit material instead of renaming the
  shared material master. Reassignment is limited to unused, unreserved
  batches, and the original receipt movements follow the reassigned batch.
  The live modal was checked without saving any inventory change.
- On 2026-07-24, Material Inventory reporting gained deployed Excel and PDF
  exports. Both reports include every material with positive on-hand stock,
  grouped material/SKU totals for batch rows, recorded rolls/pieces, and
  kilograms, plus a grand total. The PDF supports English, Russian, and Uzbek
  text, and the Excel grand totals use formulas. Production verification
  downloaded both files and reconciled 57 materials, 407 positive batch rows,
  6,182 recorded rolls/pieces, and 135,190.58 kg. The deployment passed the
  21-test inventory suite, frontend type/i18n/build checks, report-generation
  smoke tests, all four required health checks, and live browser verification.
- On 2026-07-27, release `20260727_101728` added a material-only Supplier
  filter to Material Inventory. Users can choose a named supplier or
  `No supplier`; the scope is preserved in the URL and applies consistently
  before pagination to item counts, positive stock, batch lines, search/date
  filtering, and both Excel and PDF exports. Filtered reports identify the
  selected supplier and are returned with `Cache-Control: no-store`. A narrow
  inventory supplier-options endpoint exposes only supplier IDs/names and
  whether unassigned positive stock exists. Production API results reconciled
  exactly to independent database totals: all suppliers 57 material types,
  428 positive batch lines, 144,789.76 kg, and 6,614 pieces; Dinar 29 types,
  341 lines, 100,234.44 kg, and 4,356 pieces; unassigned 5 types, 24 lines,
  9,977.77 kg, and 1,024 pieces. Existing referenced suppliers `masis` and
  `MASIS` remain separate records and were not merged. No material, supplier,
  stock, movement, or schema rows were changed. The focused 49-test backend
  suite, Ruff, compile checks, i18n parity, strict TypeScript, targeted ESLint,
  local signed-in UI QA, production frontend/backend builds, filtered
  Excel/PDF validation, Alembic head, service logs, and all four required
  health checks passed. The immediate rollback is release/image
  `20260727_092334`.
- On 2026-07-29, release `20260729_052401` repaired the Supplier filter's
  frontend state flow without changing its backend contract. The filter,
  search, date, and group controls now build one canonical Inventory URL and
  commit it through Next.js's patched History API; a local supplier-intent ref
  prevents rapid actions from losing the newest supplier, exact route guards
  prevent delayed callbacks from undoing Back/Forward, and committed URL state
  remains the sole source for stock/batch SWR keys. Six focused navigation
  regressions, strict TypeScript, targeted ESLint, local and production builds,
  independent review, signed-in live QA, service/runtime checks, and all four
  health endpoints passed. The deployment did not change inventory or schema
  rows. Immediate application rollback is `20260729_051641`.
- On 2026-07-27, release `20260727_102911` added chosen-date and date-range
  Excel/PDF exports to the Daily Sewing Report. Both formats include a
  line-level summary and the saved report rows with report/saved times, line,
  section, order, model, variant, Kroy number, sewn and defective quantities,
  reason, and notes. The Excel workbook contains `Summary` and `Entries`
  sheets with filters, frozen headers, typed dates, and summary formulas; the
  landscape PDF supports Unicode and page numbering. Access follows the
  existing Daily Sewing Report read permission. Existing report saves already
  persist in PostgreSQL table `sewing_daily_reports`; this release did not
  create or modify business rows and did not change the schema. The clean
  seven-file release passed six focused backend tests, Ruff, strict TypeScript,
  targeted ESLint, production frontend/backend builds, Alembic head, signed-in
  production UI and real Excel/PDF download validation, clean browser/service
  logs, and all four required health checks. The immediate rollback is
  release/image `20260727_101728`.
- On 2026-07-27, release `20260727_062443` optimized the production Models/PLM
  list from the exact active `20260727_060803` source. Variant-group requests
  now paginate complete groups before hydrating their members, omit binary
  image data from list hydration, and offer an opt-in compact response that
  retains every field used by the catalog. The frontend uses that compact
  response, preserves existing rows during refresh, shows accessible initial
  and refresh loading states, separates retryable errors from a true empty
  result, skips off-screen card layout, and disables numeric model-detail card
  prefetches. Signed-in production QA loaded 100 of 189 groups in 483 ms and
  all 189 groups through the 500-size option in 447 ms, with the spinner
  observed and no false empty/error state or console errors. The canonical
  five-file diff passed 14 catalog tests, Ruff, strict TypeScript, targeted
  ESLint, EN/RU/UZ parity, production builds, Alembic head
  `0071_model_less_legacy_sales`, exact deployed-source hashing, clean service
  logs, and all four required health checks. Production still has 881 model
  rows and 2,304 model-image rows; no business rows, media, packages, or
  migration revision changed. The verified pre-deploy backup is
  `/var/backups/milana-erp/pre_models_performance_20260727_062443.dump`
  (858 restore-list entries; SHA-256
  `ceb127b3ebb7c9747229c431f4034b4626dd78b26974a086370fc3bedfc15c4d`).
  Release `20260727_060803` and its backend image remain available for
  rollback. The unchanged frontend dependency tree still reports six
  high-severity npm audit findings.
- On 2026-07-27, release `20260727_060803` added targeted SWR background
  refresh to live operational data without globally polling all 207 data
  hooks. Process Tracking and department boards refresh every 10 seconds;
  operational queues, order/stock lists, maps, package detail, and Sewing Flow
  work lists refresh every 15 seconds; aggregate dashboards refresh every 30
  seconds. These bounded hooks also refresh in hidden tabs, on focus, and after
  reconnect, pause while offline, deduplicate same-key requests, and send GETs
  with `cache: no-store`. Large reference lists, editor/form hydration, and
  imperative scanner lookups remain excluded so typed quantities, filters,
  selections, and scan inputs are not reset. Cached Process Tracking and
  dashboard content stays rendered during background validation and transient
  errors; the Process Tracking Refresh button shows loading only for a manual
  click. Signed-in production verification observed three successful
  Process Tracking requests during a 23-second hidden-tab window and a
  Warehouse Stock request on its 15-second cadence with stable rendered rows.
  The exact 24-file frontend-only diff passed independent safety review,
  targeted ESLint, TypeScript, i18n, production builds, fixed-interval and
  no-store behavior checks, Alembic head `0071_model_less_legacy_sales`, and
  all four required production health checks. No business data or migration
  changed. The verified pre-deploy backup is
  `pre_background_refresh_20260727_060803.dump`.
- On 2026-07-27, release `20260727_051430` separated model/variant identity
  pictures from operational fabric-batch pictures. The Models catalog,
  Process Tracking list, Production Order list/detail, and Work Order API now
  resolve the same exact `variant_picture_url`; `material_image_url` remains
  batch-first for cutting, scanning, and other floor work. A database-level
  read-only production audit covered all 29 retained production orders and
  found 29/29 catalog matches in both list and detail, zero list/detail
  disagreements, and zero variant pictures replaced by batch images. Six
  orders had assigned batch pictures; all six retained those pictures
  separately as operational material evidence. Signed-in browser checks
  compared all six previously mismatched Process Tracking rows and confirmed
  `PO-2026-000034 / V-3637` matched the Models Variants tab and order Summary.
  No business rows, uploaded media, or migration revision changed. Focused
  backend image regressions, 79 broader backend tests aside from one unrelated
  order-dependent shared-session test that passes alone, Ruff, Python
  compilation, frontend i18n/type/build checks, Alembic head
  `0071_model_less_legacy_sales`, and all four required production health
  checks passed. The verified pre-deploy backup is
  `pre_variant_picture_consistency_20260727_051430.dump`.
- On 2026-07-24, exact model-variant material pictures were made authoritative
  over shared BOM/item fallback pictures in production tracking, production
  details, department inboxes, model previews, and labels. Creating or editing
  a variant now synchronizes its explicit material picture, preventing a shared
  BOM fabric photo from making unrelated variants look identical. An explicitly
  assigned stock-batch picture still takes precedence because it represents the
  actual fabric issued to that production order. The incorrect primary garment
  photo for `XJ3128-V-4683` was replaced from a verified source; the previous
  image record was retained for recovery. Release `20260724_063531` was verified
  against production orders `PO-2026-000024`, `000025`, `000027`, and `000028`,
  all four required health endpoints, Alembic head, automated tests, and the
  signed-in Process Tracking UI.
- On 2026-07-24, Process Tracking was corrected to use the production order's
  explicitly assigned stock-batch picture before the model-variant material
  fallback. This resolved the disagreement where `PO-2026-000033` showed the
  orange `XJ3044-V-5492` variant swatch in Process Tracking while Production
  Order Detail correctly showed the dark floral picture for assigned batch
  `4958 / SEKER SAKAR`. Release `20260724_124802` was staged from the prior
  active release with only the Process Tracking backend file changed. The
  focused batch-picture precedence and fallback tests passed, both application
  VMs and the backend image were verified on the new release, all four required
  health endpoints returned HTTP 200, and the live Process Tracking and
  Production Order APIs now return the same batch image URL.
- On 2026-07-24, four legacy variant material-image records were reconciled to
  their distinct, audit-confirmed original attachments: `ХJ-3030-V-5107`,
  `ХJ-3030-V-3637`, `Х-3044-V-5568`, and `Х-3044-V-5567`. Production orders
  `000034`, `000035`, `000037`, `000038`, and `000039` were verified through
  both the live API and signed-in Process Tracking UI. At that point, seven
  shown legacy variants had no separately attached original material picture
  in the new ERP audit history: `XJ3152-V-5411`, `PJ1173-V-5472`, `PJ1173-V-5473`,
  `PJ1173-V-4684`, `PJ1142-V-3506`, `XJ3044-V-5370`, and
  `XJ3044-V-5373`. The validated pre-repair backup is
  `pre_restore_variant_pictures_20260724_065150.dump`. This was a data repair;
  no new code release was required.
- Later on 2026-07-24, those seven missing material pictures were recovered
  from their exact variant records in the signed-in legacy ERP and imported
  into production. The extracted originals were visually checked and the
  uploaded copies matched them byte-for-byte. Production orders `000019`,
  `000020`, `000023`, `000025`, `000030`, `000031`, and `000032` were verified
  through the live API and signed-in Process Tracking DOM. The validated
  pre-import backup is `pre_old_erp_variant_import_20260724_070427.dump`.
  This was an audited data/file repair on active release `20260724_063531`; no
  code deployment was needed.
- Four of those legacy JPEGs (`XJ3152-V-5411`, `PJ1142-V-3506`,
  `XJ3044-V-5370`, and `XJ3044-V-5373`) were subsequently found to be missing
  only their final JPEG end marker. Browsers could decode the source files, but
  the thumbnail service correctly returned HTTP 415. The exact source files
  were preserved, the missing end marker was appended without recompression,
  and fresh audited picture URLs were assigned to avoid browser negative-cache
  entries. All seven recovered pictures then returned valid 160px WebP
  thumbnails and loaded with non-zero dimensions in the signed-in Process
  Tracking UI. The validated database backup is
  `/opt/milana-erp/shared/backups/pre_legacy_thumbnail_repair_20260724_071052.dump`;
  the four pre-repair source files are preserved under
  `/opt/milana-erp/shared/backups/legacy_thumbnail_sources_20260724_071052/`.
  Active release remained `20260724_063531`; no code deployment was needed.
- On 2026-07-24, 32,361 UZERP ready-product rows, 429,687 available pieces,
  158,079 package barcode aliases, and migration-only model placeholders were
  imported. Subsequent model linking did not meet the user's requirements.
  Treat the import and all reconciliation evidence as rejected historical work,
  not current production inventory.
- On 2026-07-25, the user explicitly requested complete removal of that import.
  A guarded purge matched and deleted exactly 32,361 legacy receipts, 32,361
  packages, 32,361 package items, 32,361 finished-goods rows, 32,361 import
  scan logs, 158,079 barcode aliases, 511 migration-only models, and the
  import-only `Legacy Stock` brand. It also removed the migration-only model
  children: 1 image, 2,000 sizes, 1,294 colors, and 2 BOM rows.
- The purge aborted on any reservation, shipment, sale, order link, batch
  allocation, or non-import scan. Production preflight found zero blockers.
  A transactionally equivalent dry-run produced the expected retained state
  before the apply was allowed to commit.
- Current production contains zero UZERP warehouse-18 receipts, zero
  `legacy_stock` packages from that import, zero related finished-goods rows,
  zero related barcode aliases, zero migration-only models, and no
  import-created `Legacy Stock` brand. The original ERP state remains: 23
  ready-product packages, 1,340 pieces, and 881 real model records.
- Signed-in production verification shows `Paket qabulini kutmoqda (23)` with
  quantity `1340`, Models/PLM has 189 real groups, and filtering model number
  by `LEGACY-` returns no results.
- Keep the old ERP frozen and retain it as a read-only audit source. Do not
  delete or unfreeze it; no old-ERP ready-product data is currently imported
  into the new ERP.
- New compact process QR formats were introduced for easier scanning while
  retaining compatibility with old JSON QR labels.
- Payroll labels are separate from operational bundle/package labels.
- Package and bundle labels can show material/model pictures, traceability, and
  package weight.

## Access, Security, and Audit

Implemented security foundations include HttpOnly browser sessions, bearer
tokens for machine clients, role-based permissions, CSRF origin checks,
security headers, login/password-reset rate limits, global API rate limiting,
signed attachment URLs, authenticated model files, and hash-chained audit
records.

However, the latest deep audit on 2026-07-11 found 14 confirmed/reportable
issues: 8 High, 4 Medium, and 2 Low. Treat the system as high risk until these
are explicitly fixed and retested:

1. A single production-stage permission could complete or overwrite other-stage
   work orders.
2. Packages could mint finished-goods stock without packaging evidence.
3. `mark-shipped` could bypass mandatory package-scan verification.
4. Shipments could be marked delivered before shipping, including empty
   shipments.
5. Payroll scan trusted client-supplied quantity, rate, and scan identity.
6. Finance invoice creation accepted draft orders and arbitrary amounts.
7. Sales-order invoice generation allowed broad pre-delivery statuses.
8. Sewing bundle receiving did not enforce the current user's sewing-factory
   scope.
9. A real `.env` contained secret-like production configuration; active status
   was not verified.
10. Proxy-based rate limiting trusted forwarded client IPs without a configured
    proxy allowlist.
11. Mobile dependencies had moderate advisories.
12. Backend dependency audit flagged the `python-ecdsa` timing advisory.
13. Frontend lint had an impure `Date.now()` render path.
14. Backend Ruff checks found unresolved catalog type names.

The audit-history chain has repeatedly failed at record `#744` in daily
monitoring. Investigate this before treating audit history as tamper-evident.

Passwords and infrastructure credentials appeared in earlier chats. They are
not copied here. Rotate credentials pasted into chat and keep them only in
approved secret/environment locations.

The production Linux deployment credential needed for VM administration is
stored outside the repository under the current Windows account in Windows
Credential Manager, target `MilanaERP/production-linux-sudo`. Only this
non-secret target reference may be documented or used by deployment tooling;
the credential value must never be written to source code, Git, notes, logs,
or command output. Other credentials from the supplied infrastructure document
were intentionally not copied into the project.

## Monitoring and Management Reporting

An active daily automation runs at 17:00 Asia/Tashkent:

- Generates a 24-hour ERP activity report.
- Converts it into a non-technical Uzbek manager summary.
- Emails it to the authenticated Gmail account.
- Reports active work orders, finished goods, late orders, defects, waste,
  department output, stock receipts, user activity, and audit-history
  consistency.

Recurring concerns are the audit-chain inconsistency at record `#744`, active
work orders without downstream entries, bulk edits/approvals that inflate audit
counts, waste, shortfalls, and replacement work.

## AI and Integrations

- 1C finance sync uses the existing backend API with a shared integration token
  and stable external IDs.
- A Python Milana ERP MCP server exists for an AI GM assistant.
- MCP reads must go through existing FastAPI APIs and ERP permissions, never
  directly to the database.
- GM access is broad read-only; writes are limited to confirmed notifications
  and optional task creation.
- Every MCP action should be audited, secrets must never be returned, and bulk
  actions need guardrails.
- The MCP integration previously failed because an ERP bearer token expired;
  token refresh restored `erp_me`.
- AI planning/optimization ideas should begin in shadow mode: calculate
  recommendations without changing live production until explicitly approved.

## UX and Language Preferences

- Important UI text supports English, Russian, and Uzbek.
- Fix Cyrillic/Latin inconsistencies and mojibake instead of adding duplicate
  translations.
- Tablet and phone layouts matter because operators use smaller screens.
- Operational screens should be compact, aligned, and easy to scan.
- Use dropdowns/search pickers instead of raw IDs.
- Scanner pages need large inputs, clear states, Enter-key support, and a
  visible next action.
- Printing layouts must match the real paper/label size and avoid unnecessary
  branding.
- On 2026-07-30, responsive UX hardening was deployed as release
  `20260730_084018`. The persistent desktop shell now starts at the wide-screen
  breakpoint; tablet/zoom widths use drawer navigation; Process Tracking uses
  auto-fitting filters and cards below its table breakpoint; wide tables
  scroll inside their cards; sidebar labels wrap; and shared headers, buttons,
  forms, modals, notifications, searchable dropdowns, and the portaled Tasks
  drawer stay inside the visual viewport. Signed-in geometry QA across 320px
  through 1920px found no horizontal overflow, clipped readable text, or
  control overlap on representative operational screens. Interim releases
  `20260730_080904` and `20260730_083254` were QA steps; `20260730_083254` is
  the immediate rollback. No business or schema data changed.

## How Future Work Should Proceed

1. Inspect the current production release, database migration head, local
   working tree, and GitHub state before changing or deploying anything.
2. Preserve unrelated local changes.
3. Make the smallest exact change requested.
4. Do not create business data unless explicitly requested.
5. Do not deploy unless requested or clearly included in the task.
6. Use `DEPLOYMENT.md`, take a verified database backup, build both sides before
   cutover, keep rollback releases, and run all four health checks.
7. Never overwrite `/opt/milana-erp/current` before successful builds and
   migrations.
8. Verify permissions at both frontend and backend levels.
9. Test the affected end-to-end factory handoff.
10. Report what changed, what data was touched, active release, checks run, and
    unresolved work.
11. Never echo secrets into chat or documentation.

## Local Old-ERP Sticker Import Trial

On 2026-08-10, the user's `sticker.zip` archive was processed locally only.
The archive contained 1,627 JPEG files and 1,398 unique image hashes. Direct
QR decoding found 941 unique valid old-ERP keys matching
`uzerp_ii_<number>_<number>`. The QR identity, frozen old-ERP ready-stock
snapshot, local reviewed model catalog, and multi-engine OCR were reconciled
fail-closed: only 59 sticker packages covering 5,055 pieces had all required
package-specific values and exactly one existing catalog model. Those 59 were
imported into localhost Finished Goods warehouse `7`; each package has one
immutable `UZERP_STICKER_PHOTO` receipt, one finished-goods row, one scan log,
and one old-QR alias. A repeat apply created nothing, and reconciliation found
59 receipts/packages/aliases/stock rows, 5,055 package and available pieces,
and zero quantity/barcode mismatches.

The other 882 decoded sticker records remain quarantined because at least one
printed field or exact catalog match was unreadable or unconfirmed. The review
workbook is
`C:\Users\User\.codex\visualizations\2026\08\10\019fea3b-fc0e-7c03-91be-d8c502121d3a\outputs\sticker-import-20260810\old-erp-sticker-corrections.xlsx`;
the source manifest, OCR evidence, quarantine JSON, and pre-import local
PostgreSQL backup are under `.codex-work/sticker-import-20260810/`.

Local code now resolves package scans through `PackageBarcodeAlias` and shows
the immutable sticker fields on package detail. Nine focused legacy-stock and
old-QR tests, frontend TypeScript, translation parity, a production frontend
build, authenticated API scanning, browser scanning, and package-detail UI QA
passed. The test UI is on `http://localhost:3001` and its isolated backend is
on `http://localhost:18080`. The normal compose backend startup remains
blocked in this dirty checkout because migration `0081` references the absent
local `0080_piecework_assignments` revision file; this unrelated chain was not
repaired or bypassed in source. Production was not changed or deployed.

## Open or Unfinished Work

- Decide whether empty branded planning order `0014`, created during the
  2026-08-03 fabric-thumbnail production QA, should be removed through a new
  guarded deletion workflow. Do not delete it directly from PostgreSQL without
  explicit approval and an audit-preserving plan.
- Deploy or reimplement the sales-to-warehouse item-detail notification safely
  after reconciling the rollback.
- Verify which post-`20260723_065753` features are absent from production and
  restore only the intended ones.
- Import the user's Excel model catalog by grouping duplicate model names into
  variants; discussion occurred, but the workbook import is incomplete.
- Investigate audit-history chain failure at record `#744`.
- Fix and regression-test the high-risk findings from the 2026-07-11 audit.
- Review/correct the 882 quarantined sticker records, approve the local trial,
  then reconcile and deploy the old-QR/import work only with explicit approval.
- Reconcile local changes with GitHub without losing uncommitted production
  work.
- Establish tested database backup/restore, RTO/RPO, monitoring alerts, and
  retention policies.
- Add end-to-end browser tests for login, RBAC, sales order creation, scanning,
  shipment, and logout.

## Useful References

- `DEPLOYMENT.md` - only production deployment procedure.
- `README.md` - project overview and local setup.
- `docs/ARCHITECTURE.md` - architecture and trust boundaries.
- `docs/PRODUCTION_READINESS.md` - readiness checklist.
- `docs/SECURITY_RUNBOOK.md` - security operations.
- `docs/DISASTER_RECOVERY.md` - backup and recovery planning.
- `docs/DEVELOPER_GUIDE.md` - codebase walkthrough.
- `docs/training/` and `output/pdf/training/` - department training material.
- `.codex-work/deep-security-quality-audit/final/` - latest deep audit evidence.
- `scripts/erp_daily_monitor.py` - daily management report source.

## Update Rule

After a significant ERP task, update only the affected sections and refresh the
date. Record the active production release and any rollback. Keep this as a
concise source of truth, not a transcript.
## 2026-08-10 Archived Material Batch Editing Deployment

- Active production release: `20260810_071821` on backend and frontend VMs.
- Previous rollback release: `20260810_101545`.
- Material Inventory now keeps the edit action available for batch rows whose original master-data material was archived/deleted. The editor reconstructs the archived current material from the batch row and allows reassignment to an active master-data material.
- Scope: frontend inventory page only; no business data rows were modified.
- Pre-migration PostgreSQL backup: `/opt/milana-erp/shared/backups/pre_inventory_archived_material_edit_20260810_071821.dump` (26,267,391 bytes; 959 objects; SHA-256 `d043d39c940adaa24758f8f774dd1b2eb21a262470f6a2f08beb84cf49630355`).
- Alembic remained at `0083_employee_number (head)`.
- Verification passed: direct backend health, direct frontend login, public health, and public login. Backend container was running with zero restarts and no OOM kill.
## 2026-08-10 Archived Material Batch Editing Corrective Deployment

- Corrected active production release: `20260810_154320` on backend and frontend VMs.
- Rollback release: `20260810_071821`.
- The previous deployment copied the wrong staged frontend source during retry handling. This release uses an explicit release ID end-to-end and verifies the served source contains both batch-aware edit-action call sites.
- Material Inventory now derives edit eligibility from either the stock row or underlying batch `item_id`, reconstructs archived current materials from batch data, and permits reassignment to active master-data materials.
- No business data rows were modified.
- Pre-migration PostgreSQL backup: `/opt/milana-erp/shared/backups/pre_inventory_archived_material_edit_retry_20260810_154320.dump` (26,267,386 bytes; 959 objects; SHA-256 `40b38613ab4c52feac21319f41125f168f4db45f9b516106a7f4c8d4ba784140`).
- Alembic remained at `0083_employee_number (head)`.
- Direct backend, direct frontend login, public health, and public login checks passed. Backend was running with zero restarts and no OOM kill.
## 2026-08-10 Supplier-Filtered Material Inventory Reports

- Active production release: `20260810_154844` on backend and frontend VMs.
- Rollback release: `20260810_154320`.
- Restored a supplier selector beside the Material Inventory date filters. The selected supplier is persisted in the inventory URL and scopes the material summary, visible stock batches, item count, Excel report, and PDF report.
- Supplier-specific totals include only stock batches belonging to the selected supplier; unattributable item-level adjustments and reservations are excluded from supplier-specific aggregation.
- No business data rows were modified.
- Pre-migration PostgreSQL backup: `/opt/milana-erp/shared/backups/pre_supplier_inventory_report_filter_20260810_154844.dump` (26,267,392 bytes; 959 objects; SHA-256 `097b46da1c1b8f185a64f7dae1ecb7ce8a69cc74dfb1165f845a35e149802a1c`).
- Alembic remained at `0083_employee_number (head)`.
- Direct backend, direct frontend login, public health, and public login checks passed. Backend was running with zero restarts and no OOM kill.
## 2026-08-10 Supplier Filter State Fix

- Active production release: `20260810_155856` on backend and frontend VMs.
- Rollback release: `20260810_155635`.
- Replaced unstable supplier-filter URL navigation with local React state. Selecting a supplier now refetches inventory and report data without resetting or reloading the page.
- Live signed-in verification selected Dinar (`supplier_id=2`): the selection remained active and all 84 rendered batch rows were Dinar.
- No business data rows were modified.
- Pre-migration PostgreSQL backup: `/opt/milana-erp/shared/backups/pre_supplier_filter_state_fix_20260810_155856.dump` (26,267,391 bytes; 959 objects; SHA-256 `7007b8c552a96bc289ad66ad7b62a193e75d2e17fb74268f41449f1bc6cdaf84`).
- Alembic remained at `0083_employee_number (head)`.
- Direct backend, direct frontend login, public health, and public login checks passed. Backend was running with zero restarts and no OOM kill.
## 2026-08-11 Package Label 2x2 A4 Deployment

- Active production release: `20260811_090217` on backend and frontend VMs.
- Rollback release: `20260810_121906`.
- The single-package sticker endpoint now repeats the same detailed package label four times in a 2-by-2 grid on one A4 portrait sheet. Each card remains 98.5 mm by 142 mm with a 3 mm grid gap and 5 mm page margins.
- The active production package-label source was reconciled into the local repository before the narrow layout change so newer production label fields were preserved.
- No business data rows were modified.
- Pre-migration PostgreSQL backup: `/opt/milana-erp/shared/backups/pre_package_label_2x2_20260811_090217.dump` (26,282,156 bytes; 960 objects; SHA-256 `4b05bf0f2f305e00c88ca63888b11e0668422546c7d0c244c2a3e93b07ad27df`).
- Alembic remained at `0084_model_group_key (head)`.
- Direct backend, direct frontend login, public health, and public login checks passed. Backend was running with zero restarts and no OOM kill.
## 2026-08-11 Safe Supplier Deletion for Mubina

- Active production release: `20260811_112556` on backend and frontend VMs.
- Rollback release: `20260811_090217`.
- Confirmed Mubina already has `storage.suppliers` through the Storage role. Her delete failures were caused by supplier dependency protection, not missing access.
- Supplier Delete now safely archives suppliers linked to stock batches, purchase requests, or purchase orders. Archived suppliers disappear from active supplier lists while historical references remain intact. Suppliers with no links are still physically deleted.
- Migration `0085_supplier_archiving` added non-null `suppliers.is_active` with a true default. Immediately after migration all 11 suppliers remained active; deployment archived or deleted none.
- Pre-migration PostgreSQL backup: `/opt/milana-erp/shared/backups/pre_supplier_archiving_20260811_112556.dump` (26,285,769 bytes; 960 objects; SHA-256 `fa1c18ecab7c05164db9af4482ccdf43f408ad6ddd2d69dfe4cd95868f14e5fa`).
- Direct backend, direct frontend login, public health, and public login checks passed. Backend was running with zero restarts and no OOM kill.

## Production Update - 2026-08-11 - Fabric inventory received-date range

- Active production release: `20260811_113640`.
- Rollback release: `20260811_112556`.
- Pre-deployment PostgreSQL backup: `/opt/milana-erp/shared/backups/pre_inventory_received_date_20260811_113640.dump`.
- Fabric inventory date ranges now consistently filter `StockBatch.received_date` across displayed batch rows, stock summary quantities, supplier-filtered totals, and Excel/PDF reports.
- Material master records are no longer filtered by their own creation date when a fabric inventory receipt-date range is selected.
- No business data or database schema was changed; Alembic remains at `0085_supplier_archiving`.
- Verified backend VM health, frontend VM login, public `/health`, and public `/login` after cutover.

## Production Update - 2026-08-11 - Paid operations by sewing factory

- Active production release: `20260811_100247` on backend and frontend VMs.
- Rollback release: `20260811_113640`.
- Release archive SHA-256: `417fdf9006b6c3b9327ccc23e9336666a4ee3921587b65ccb5d1aae03a8bf0d7`; the matching 452-file source-manifest SHA-256 is `767f1ba060a267cf3bee8e28e8b440ec885e3339964241cd7e28dbdd977b1eae` on both VMs.
- Pre-migration PostgreSQL backup: `/opt/milana-erp/shared/backups/milana_pre_20260811_100247.dump` (26,297,788 bytes; 960 restore objects; dump SHA-256 `6ac92a61323d6c9955b3099abc8e81a9ef34b39f9123b3a6862c07e95dc86788`; list SHA-256 `11f8cf8e03030961dadd77a489123a4498fd49344c4c886b9b2516d51b78286c`).
- Migration `0086_paid_operation_factories` updated `details_json` for 5,044 existing models: 191,911 legacy operations became 575,733 independent operations, exactly 191,911 for each of Milana, Besttex, and Eco Cotton. No models, users, orders, stock, packages, or other business records were created or deleted.
- Signed-in production UI verification on model `7158` showed three collapsible branches with 51 operations each. A live scoped Milana Sewing account received only its 51 Milana operations through the production HTTP API. Production currently has no active users in the Besttex or Eco Cotton sewing departments, so those two account-specific sign-in checks remain unavailable; focused authorization tests cover both scopes.
- Direct backend health, direct frontend login, public health, and public login passed. The backend is on the release-tagged image with one Uvicorn parent and two workers, zero restarts, no OOM kill, no new error/5xx logs, and 86 of 100 PostgreSQL connections available at verification time.

## Production Update - 2026-08-11 - Process QR factory selector

- Active production release: `20260811_120743` on backend and frontend VMs.
- Immediate rollback release: `20260811_100247`.
- Release archive SHA-256: `9a96455247f337ebf037f07e8dd4283911f89bb2f0720ec4b5274adaca264ea4`; the matching 452-file source-manifest SHA-256 is `c750ae1f4ab54db6dd1fa329bdfbce8b9ce68e2d3105224e3039a8708aa2b150` on both VMs.
- Pre-deployment PostgreSQL backup: `/opt/milana-erp/shared/backups/milana_pre_20260811_120743.dump` (42,475,848 bytes; 960 restore objects; dump SHA-256 `82bbc8a84ad02417069980f3bad10a6e53de5ee1c7b03c74606b4004b5764f52`; list SHA-256 `1135e42e4dd6f1d5d61ab2dcaea4e0bca4b94e8b6b97d7e2c32c0e2befb6e8c1`).
- Process QR now has one sewing-factory selector and shows only that factory's operations. New operations inherit the selected factory, and label IDs/payloads include the factory code.
- Signed-in production verification on model `7158` showed exactly 51 rows for each of Milana, Besttex, and Eco Cotton. With a sewing line selected, each factory generated 306 preview labels; all 306 named only the selected factory and zero named either other factory. No labels were printed and no model changes were saved during verification.
- No business data or schema changed in this release; Alembic remains at `0086_paid_operation_factories`.
- Direct backend health, direct frontend login, public health, and public login passed after cutover. The unchanged frontend dependency tree still reports seven inherited npm audit findings (one moderate and six high).

## Production Update - 2026-08-11 - Supplier folders for purchase requests

- Active production release: `20260811_171539`.
- Rollback release: `20260811_120743`.
- Pre-deployment PostgreSQL backup: `/opt/milana-erp/shared/backups/pre_supplier_folders_20260811_171539.dump`.
- The purchase-request approval queue is grouped into collapsible supplier folders, ordered by supplier name, with a request count on each folder.
- Existing request editing, approval, rejection, and purchase-order creation behavior is unchanged.
- The release was staged from the live `20260811_120743` source to preserve intervening production changes.
- No business data or database schema was changed; Alembic remains at `0085_supplier_archiving`.
- Verified backend VM health, frontend VM login, public `/health`, and public `/login` after cutover.

## Production Data Update - 2026-08-11 - Test active purchase orders removed

- Deleted test purchase orders `PUR-2026-000001` through `PUR-2026-000005` from production.
- Deleted exactly 5 `purchase_orders` rows and their 5 direct `purchase_order_lines` rows.
- All target orders had zero received quantity and no stock-movement references before deletion.
- Active purchase orders remaining after the transaction: 0.
- Originating purchase requests, suppliers, material master data, inventory batches, stock movements, and all unrelated data were left unchanged.
- Pre-deletion PostgreSQL backup: `/opt/milana-erp/shared/backups/pre_delete_test_active_purchase_orders_20260811_180000.dump`.

## 2026-08-12 Eco Cotton sewing deployment attempt

- Candidate release `20260812_040028` was built successfully on both application VMs but was not deployed.
- Candidate source archive SHA-256: `11406e51583e4fca6af51fdc28978f2e2f046cc279dde42cddb0e947b62c1caa`; source manifest SHA-256: `6cc225f99eb899624dd7b56bc8dacbf4ee113eb908ba5429221e47328ab04d47` (627 files).
- Fresh pre-migration backup: `/opt/milana-erp/shared/backups/pre_20260812_040028.dump`, 42,479,715 bytes, 960 restore objects. Dump SHA-256: `6ead907aaa47db51683573edbb337ee13f2599bb579f840e9b8c0183d00441fe`; restore-list SHA-256: `f5c1d28306965cb8ae69ccd6af69d90ff83a2340ae48e26889d516b139de1f21`.
- Migration `0087_sewing_flow_factories` upgraded successfully, but candidate backend startup failed because `backend/app/api/routes/packages.py` imports missing `PackageReceivingQueueRemoveIn` from `backend/app/schemas/tracking.py`.
- The frontend was never switched. Migration `0087` was safely downgraded to `0086_paid_operation_factories`, and the backend was restored to image/release `20260811_171539`.
- Post-rollback internal and public health/login checks returned HTTP 200. Active backend and frontend release: `20260811_171539`; active database revision: `0086_paid_operation_factories`.
- Deployment remains blocked until the unrelated package route/schema mismatch is reconciled and backend app import/tests pass.

## 2026-08-12 Eco Cotton sewing deployed

- Active backend and frontend release: `20260812_041925`.
- Eco Cotton sewing now has factory-scoped sewing lines, assignment availability, batch/manual receiving, scanning, daily reports, and exports. Existing sewing lines/history remain scoped to Milana.
- Added missing package receiving queue request schemas and the package label variant-image compatibility helper required for backend startup.
- Backend startup now honors `WEB_CONCURRENCY` and defaults to two Uvicorn workers; production verified with exactly two workers.
- Active database migration: `0087_sewing_flow_factories`.
- Release archive SHA-256: `906b133b0579391af7ebc87c14f5f16406426ad9f9a8e1c63412aafa6afc8d63`; source manifest SHA-256: `6803e03cada60732b414b2065bca63ba10581ef59e927c11a4e6bd3f48582868` (627 files).
- Fresh pre-release backup: `/opt/milana-erp/shared/backups/pre_20260812_041925.dump`, 42,480,741 bytes, 961 restore objects. Dump SHA-256: `02084737f86a7cecdd4fd8868f7898736dbf210a4841d6734d59e2d5d1ef0665`; restore-list SHA-256: `ae0351b9cad2435dfbaf9ac0010d5d8d854cb2c84e67f281d980406e39331071`.
- Frontend production build, backend candidate import, and Alembic single-head checks passed. Focused backend tests: 81 passed; two unrelated existing failures remain (package-label HTML expectation and test-database replacement-row isolation).
- Internal/public health and login endpoints returned HTTP 200. Signed-in read-only checks confirmed Eco Cotton sewing lines and daily-report pages load with Eco-scoped data.
- Working rollback release remains `20260811_171539`; database rollback would require downgrading `0087` before starting that older image.

## 2026-08-12 Eco Cotton sewing bands deployed

- Active backend and frontend release: `20260812_045633`.
- Active database migration: `0088_eco_cotton_sewing_bands`.
- Eco Cotton has exactly 20 active sewing bands named `1-Band` through `20-Band`, with codes `ECO-BAND-01` through `ECO-BAND-20`.
- Existing seven Eco Cotton line IDs were retained for bands 1-7 so linked assignments and reports remain attached. Milana remained unchanged at 30 sewing lines.
- Release archive SHA-256: `18a8865a1155565ae4080303d1386745d00db54d10e165cdd6aabb764d85452a`; source manifest SHA-256: `1e716c8999c1f48875c11840dfef7aed39fb7189b2cedfcda9e59d076d1940e9` (628 files).
- Fresh backup: `/opt/milana-erp/shared/backups/pre_20260812_045633.dump`, 42,482,670 bytes, 961 restore objects. Dump SHA-256: `df1922ada727ce5679c7b0f5dcdc356e3fcd52f3f4c4e394823206a6c241cdba`; restore-list SHA-256: `ba295da20299245e05abc59dc696d1540421ef543242e72b66f70af687473920`.
- Candidate FastAPI import, single Alembic head, frontend production build, backend image build, two-worker startup, internal/public health checks, and signed-in UI verification all passed.
- Previous release `20260812_041925` remains the rollback application release; database downgrade from `0088` is required before starting it.
## 2026-08-12 - Eco Cotton packaging separation (local, not deployed)

- Eco Cotton packaging now mirrors Milana packaging through the ECP department while keeping receive-from-sewing receipts, packing queues, package records, labels, and package change requests separated from PKG.
- Package ownership is derived from the routed packaging work order and enforced for packaging-department users. Storage receiving, storage maps, shipment, and finished-goods operations remain shared.
- Alembic migration 0089_packaging_departments adds and backfills packaging_department_code on packages and packaging_receipts.
- Frontend Eco Cotton navigation now exposes Packages, Packing Queue, and Receive from Sewing with ECP scope.
- Deployed to production in release 20260812_051646; details are recorded below.
## 2026-08-12 - Eco Cotton packaging deployed

- Active backend and frontend release: 20260812_051646.
- Previous rollback release retained: 20260812_045633.
- Source archive SHA-256: 06aaa772f5013dd4ed6a09543810779143c0c09cf9e82b7b4e21f3fa00fbc3ad.
- Source manifest SHA-256: b6482ab2b21112980387572c7c775ae6f92d5a479e4d1f89667bc8953a1cb4ff (518 files, verified on both VMs).
- Pre-migration backup: /opt/milana-erp/shared/backups/pre_20260812_051303.dump, 42,482,793 bytes, 961 restore objects.
- Backup SHA-256: 16bf5da70eceeaea613f10d042e8351b111060a1f3a83a189288662fb37e652b.
- Restore-list SHA-256: 2529213f64bdc29f1d474ca026b258205a7695b020a681b948230b52b521e008.
- Migration 0089_packaging_departments applied successfully; database current is 0089_packaging_departments.
- Repaired the historical duplicate Alembic branch by retaining 0075_piecework_assignments as a no-op placeholder and merging it into canonical 0080_piecework_assignments. Alembic now has one head.
- All four required health checks returned 200/ok. Backend runs one Uvicorn parent with two workers; startup logs had no traceback or new 5xx response.
- PostgreSQL connection usage at verification was 14 of 100.
- Existing package backfill: PKG=105, null package owners=0, null receipt owners=0.
- Signed-in read-only checks passed for ECP Packages, Receive from Sewing, and Packing Queue; all showed ECP-scoped empty state without backend errors. PKG Packages remained separate with 105 records.
## 2026-08-12 - Packaging sidebar scope fix deployed

- Active backend and frontend release: 20260812_052300.
- Previous rollback release retained: 20260812_051646.
- Source archive SHA-256: aa5cd3c1875703f16bdeda57fc8133f8c63f1d9bf954679840c9cd684134da6d.
- Source manifest SHA-256: 89a120aedd1dd16ff54f0602f34b0f586898a3708e7c7c4d2fb4c4930432580b (518 files, verified on both VMs).
- Pre-release backup: /opt/milana-erp/shared/backups/pre_20260812_052300.dump, 42,484,180 bytes, 963 restore objects.
- Backup SHA-256: 7b31131cfd22c7ebb81f47060c46259ce8bdcb6ea38ecc8f305f8433e2a5be0d.
- Restore-list SHA-256: 89c58ee663aa75a0f739dc2243b7540f19708ab7096ecbaf10e1a92555fc6db8.
- Database remained at 0089_packaging_departments; no new migration or business-data mutation was required.
- Sidebar active-state matching now includes packaging_department, so ECP and PKG package/queue/receive links do not highlight together.
- All four health checks passed. Backend runs one Uvicorn parent with two workers and startup logs showed no traceback or 5xx response.
- Signed-in read-only checks confirmed ECP highlights only /packages?packaging_department=ECP and PKG highlights only /packages?packaging_department=PKG, with no backend errors.

## Deployment 2026-08-12 11:55:41

- Active production release: `20260812_115541` on backend and frontend VMs.
- Rollback release: `20260812_063934`.
- Fixed Besttex factory parsing in Sewing Flows, Daily Sewing Report, and Bundle Scan so `BST` is no longer converted to `MIL`.
- Frontend production build and TypeScript passed; backend image is `milana-backend:20260812_115541`; Alembic confirmed existing head `0090_user_factory_access` with no new migration or business-data change.
- Post-deployment internal/public health and the three repaired BST route shells returned HTTP 200; no recent backend traceback/exception/error was found.
- Operational warning: the frontend VM `admilana` disk quota is exhausted while the filesystem still has free space. This release required root-owned candidate extraction/build via sudo. Release retention and account quota should be reviewed before the next large deployment; no historical release was deleted.
- The first activation attempt used a 3-second backend gate and automatically rolled back safely; the same candidate then activated successfully with a 90-second startup poll.
## Deployment 2026-08-12 12:10:48

- Active production release: `20260812_121048` on backend and frontend VMs.
- Rollback release: `20260812_115541`.
- Fixed direct/bookmarked cross-factory navigation for authorized users by adding an authenticated factory-session switch endpoint and having the frontend authorization gate switch before rendering.
- Authorization remains enforced: the public HTTPS test switched Super Admin from MIL to BST with HTTP 200 and `/api/auth/me` returned BST; a regular MIL user attempting BST remained HTTP 403.
- Frontend production build passed; local authentication suite passed 15 tests; the release-tagged backend candidate passed Alembic and live endpoint tests before activation.
- Internal/public backend health, frontend login, and `/sewing/flows?factory=BST` returned HTTP 200 after deployment. No recent backend traceback/exception/error was found.
- No migration or business-data change was made.
## Deployment 2026-08-12 12:59:58

- Active production release: `20260812_125958` on backend and frontend VMs.
- Rollback release: `20260812_121048`.
- Process QR paid operations, employee badges, employee badge preview, and work-label preview are independently collapsible. Sections remain mounted, retain selections/inputs, and expand for printing.
- Next.js production build and TypeScript passed; Alembic confirmed the existing database head with no migration or business-data change.
- Internal/public backend health, frontend login, and public `/process-qr` returned HTTP 200. Deployed file hashes match local source and no recent backend traceback/exception/error was found.
# 2026-08-12 WebP upload and thumbnail reliability release

- Active production release: `20260812_101111` on backend and frontend.
- Previous rollback release: `20260812_125958`.
- Backend image: `milana-backend:20260812_101111`; two Uvicorn workers, restart count `0`, OOM killed `false` after cutover.
- Production backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260812_101111.dump` (`42,490,100` bytes, `964` restore objects).
- Backup SHA-256: `58d0498020e911cc9653877f445ddea369687a213b469077b4295ca9f676374a`.
- Restore-list SHA-256: `2ae4165965c64ae3d9f507e45dd499d66c19c7ee69adcf36ca1536d305e6481b`.
- New image uploads are validated, orientation-corrected, atomically stored as WebP, and preserve alpha and embedded ICC profiles. PNG/BMP/TIFF/GIF or alpha-bearing sources use lossless WebP; photographic sources use high-quality WebP.
- Model, BOM, item, purchasing, company-logo, sales-printing, and production-printing image uploads use the shared converter. PDF/DXF/AI attachments remain unchanged.
- Model-file uploads prebuild `160px` and `320px` WebP thumbnails. The read-time compatibility fallback is serialized to one converter and writes atomically.
- Historical backfill generated `11,352` thumbnails, reused `3,524` cached thumbnails, skipped `0`, and failed `0`. The thumbnail cache contained `15,364` WebP files after backfill.
- Image-specific backend regression tests: `9 passed`. Frontend lint completed with `0` errors and `3` existing hook warnings; i18n, UI contract checks except the pre-existing inventory supplier-edit contract, TypeScript, strict TypeScript, and Next.js production build passed.
- Full backend suite: `395 passed`, `14 failed`; the remaining failures are pre-existing/unrelated catalog-family parsing, supplier deletion, legacy stock, payroll permission, factory authorization/routing, replacement-work, and purge expectations. The inventory supplier-edit frontend contract also remains a known unrelated failure.
- Required health checks all passed: backend internal `200`, frontend internal `200`, public health `200`, public login `200`.
- Production benchmark after cutover: cached `320px` WebP response `10.9 ms`; 14 parallel cached thumbnail requests `65.7 ms` total. Backend memory changed from `434 MB` to `456.2 MB`, with no worker death, restart, traceback, or 5xx. Packaging inbox remained `200` at `1.163 s` and is a separate query-optimization opportunity.
# Production data note - 2026-08-12 payroll QR test cleanup

- At the user's request, the isolated test issuance for production order `PO-2026-000073`, batch `0077-01`, was removed from production after a validated full PostgreSQL backup.
- Deleted exactly 270 available payroll QR labels and five already-voided payroll records. No piecework acceptance or other business records referenced them.
- Reset only the now-empty `payroll_qr_labels` and `payroll_records` ID sequences so the payroll QR workflow can start fresh.
- Preserved the existing issue/scan/return audit history and added a `delete_test_qr_batch` cleanup audit entry.
# Production deployment - 2026-08-12 Process QR collapsed defaults

- Active release: `20260812_113057`; rollback release: `20260812_101111`.
- Scope: only the existing Process QR collapsible groups now initialize closed; users can open each group with the existing controls.
- Candidate was built from the active production source baseline with only `frontend/src/app/(app)/process-qr/page.tsx` overlaid, avoiding unrelated dirty local and GitHub changes.
- Identical source archive SHA-256 on both VMs: `9bfa30dda2e797b1fe11e87186741521b820ec4dc1adc1d0f0198dfbea56e752`; 529-file manifest SHA-256: `1b3fb0a8ae5c646b85cf41e339f21aeca541fb485d5dc3e4ff1527d4a8387410`.
- Pre-deployment backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260812_113057_20260812_113238.dump`, 42,490,965 bytes, 964 restore objects, dump SHA-256 `26409e6898e50fd6f44f3f28fa27b27637cf98787243fc909699cc8a504a4338`, restore-list SHA-256 `a2a7d4f8cd24e70644169818ce631569577eb2534eb663f4cf185663a1262418`.
- Frontend and backend builds passed; Alembic remained at `0090_user_factory_access (head)`.
- Internal and public health/login checks returned HTTP 200. Backend runs two Uvicorn workers with no startup errors; 15 of 100 PostgreSQL connections were active after deployment.
- Authenticated visual verification was not completed because the available browser sessions were logged out; authentication was not bypassed.
# Pending permission change - Payroll workspace access

- The Payroll role is configured for `payroll.view`, `payroll.manage`, and `payroll.scan`, exposing Payroll Summary, Piecework workspace, Process QR, Payroll Scan, and QR Control.
- Payroll approval and payment permissions remain withheld.
- Migration `0091_payroll_workspace_access` updates the existing Payroll role when deployed. This change is not yet deployed.

# Pending permission change - Milana Sewing section access

- The Sewing role retains `sewing.workspace`, `sewing.records`, `sewing.bundles`, and `traceability.view`, and gains the missing `sewing.flows` permission so all Milana Sewing section actions are available.
- Existing factory scoping remains unchanged; Milana Sewing users remain restricted to factory `MIL`.
- Migration `0092_sewing_role_full_section_access` updates the existing Sewing role when deployed. This change is not yet deployed.
# Production deployment - 2026-08-12 Payroll and Milana Sewing access

- Active release: `20260812_124922`; rollback release: `20260812_113057`.
- Payroll role now has `payroll.view`, `payroll.manage`, `payroll.scan`, and `sewing.daily_reports.view`, exposing all five Payroll section pages without approval or payment authority.
- Sewing role now has `sewing.workspace`, `sewing.records`, `sewing.bundles`, `sewing.flows`, and `traceability.view`; Milana factory scoping remains unchanged.
- Alembic is at `0092_sewing_role_access`.
- Source archive SHA-256: `e2414231dd87cf83661af85e5cb9ad75d9e50d52f3409a340a49e270353c5b95`; 531-file manifest SHA-256: `2df2f1f82989c1606da436ca41323a9f0b95f8921365dabd27de305d13df41dd`.
- Validated pre-deployment backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260812_124922_20260812_125036.dump`, 42,494,325 bytes, 964 restore objects, dump SHA-256 `bcc32145dc6ca005b3da341f319ef0d99ccc37b1d03a28e76baf1efa0ff8b8a4`, restore-list SHA-256 `5beece3e2aa6bae2577072e3c307c3ae391d9c3bf636dd1c2d3f33221e9f0a8e`.
- Frontend/backend builds and migrations passed. Internal/public health and login endpoints returned HTTP 200; two Uvicorn workers started without errors and PostgreSQL had 15 of 100 connections active.
- An earlier candidate was never activated after its overlong Alembic revision identifier was rejected; the transaction rolled back fully and production remained unchanged until the corrected release passed.
# Production deployment - 2026-08-12 Milana Sewing sidebar fix

- Active release: `20260812_125819`; rollback release: `20260812_124922`.
- Fixed the Sewing-role navigation whitelist to compare URL paths without query strings, so Milana Sewing users now see Sewing Flows, Daily Sewing Report, Sewing Floor, and Scan Bundle.
- No role permissions or business data changed in this release.
- Source archive SHA-256: `9de0f83b66e7c9a549f2732394d4be4aa7403565927db9bcb895b1d62199e4b2`; 531-file manifest SHA-256: `1c21a114034a145be3d2d43e7e01260c78bce0a9ce6199baae8902586801011d`.
- Validated backup: `/opt/milana-erp/shared/backups/milana_erp_pre_20260812_125819_20260812_125927.dump`, 42,495,579 bytes, 964 restore objects, dump SHA-256 `c976121ec0abe40ef33fbde0fe04c8d806b3b8564198a08485d4fbcc8466944c`, restore-list SHA-256 `de55fc84973eba51e77ed9ff1d2dbcf27ad61a8e6eee7bb4aadfc84fb0e1ecaa`.
- Alembic remained at `0092_sewing_role_access`. All internal/public health and login checks returned HTTP 200; two Uvicorn workers and the frontend service started cleanly.
