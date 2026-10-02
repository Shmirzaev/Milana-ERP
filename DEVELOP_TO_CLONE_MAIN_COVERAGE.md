# develop to clone_main: audit transfer coverage

**Snapshot: 2026-10-02.** Compared `clone_main` `0e873f83` with `develop` `2f549f9b`. Read-only Git analysis; no production changes.

## Percentage and what it measures

**97 of 435 reviewed develop fix commits are retained: 22.3%.** The remaining 338 are 334 not traced and four known selective reversions. This denominator is the earlier fix-labeled commit pool, not all branch commits, lines changed, development effort or 127 resolved bugs. Four recent owner-approved code fixes were written separately on clone_main and are outside that source commit pool.

| Recorded fix coverage across 127 audit rows | Rows | Percentage |
| --- | ---: | ---: |
| all traced | 26 | 20.5% |
| some traced | 12 | 9.4% |
| none traced | 83 | 65.4% |
| no recorded fix | 6 | 4.7% |

**This is commit-transfer evidence, not a fresh bug-status audit.** All traced means every fix commit cited by that ledger row is found by ancestry, cherry-pick origin or equivalent patch, excluding the four known reversions. It does not prove that later edits retained every behavior, that every follow-up is listed by the ledger, or that a partial develop finding is complete. Some/none traced means recorded source commits are not fully accounted for; an existing main implementation or a new clone_main implementation may still solve the same bug. Consequently, an exact percentage of the 127 bugs successfully resolved on clone_main is not established by this comparison.

Of the 106 rows marked fixed on develop, 25 have all cited fix commits traced, four have some, and 77 have none. Those 77 are candidates for code/regression review, not 77 proven live bugs. The audit ledger itself is absent from clone_main.

## New owner-approved work and scope exceptions

- FN07: USD <= $1.00 settlement and four-decimal unit cost storage are implemented and tested (`6c5bf63c`, `40baf767`). These two approved subrules do not establish that every other FN07 bounds/precision fix from develop was transferred.
- FN08: received-payment revenue and shipped unpaid debt are implemented (`ece87130`); historical cost and currency policy remain pending.
- OPS09: 1C was retired (`561a0393`). Missing former integration fixes do not need porting into an intentionally removed connector; historical records remain.
- WF08: historical waste repair is outside current scope. Missing historical repair commits do not authorize a backfill or deletion.
- OPS03/04 hosting, OPS06/10 recovery and OPS11 credential approvals are recorded; live implementation/evidence remains pending. Six ledger rows have no fix commit even on develop.

## Exact finding-by-finding map

Row numbers distinguish repeated finding IDs. Commit references and statuses come from the [develop audit ledger at this snapshot](https://github.com/Shmirzaev/Milana-ERP/blob/2f549f9b202ef1a66ed6ffe17be07b5497ccdeab/docs/audit_backlog.json). Present / cited counts are history coverage only; inspect each source commit for its exact changes.

| # / ID | Concrete finding from develop | Develop status | Recorded fixes found | Transfer coverage | Untraced / reverted source fixes |
| --- | --- | --- | ---: | --- | --- |
| 1 / ST01 | Same receipt adds stock twice: five becomes ten. | fixed | 0/1 | none traced | 3881177 |
| 2 / ST02 | Issuing four from ten leaves ten in stock. | fixed | 0/1 | none traced | 3881177 |
| 3 / ST02 | Movement accepts an item with another item's batch. | fixed | 0/1 | none traced | 3881177 |
| 4 / ST03 | W1 movement changes W2's reported balance. | fixed | 0/1 | none traced | 3881177 |
| 5 / ST11 | Concurrent reservations accept twenty against ten available. | fixed | 0/1 | none traced | 3881177 |
| 6 / FN02 | Payments total 120 against 100; invoice stays partially paid. | fixed | 0/1 | none traced | 3881177 |
| 7 / FN04 | Concurrent requests create two invoices for one order. | fixed | 0/2 | none traced | 3881177, 6843712 |
| 8 / SEC03 | Concurrent audit entries break chain verification. | fixed | 1/1 | all traced | — |
| 9 / SEC02 | Deleting a user changes hashed historical records. | fixed | 1/1 | all traced | — |
| 10 / DB04 | Fresh database setup fails at migration 0039. | fixed | 1/1 | all traced | — |
| 11 / SEC01 | Legacy factory wildcard bypasses newer grant restrictions. | fixed | 1/1 | all traced | — |
| 12 / SEC10 | Limited user-manager can delete a Super Admin without wildcard. | fixed | 0/1 | none traced | 3881177 |
| 13 / API06 | Changing own name grants pricing-list access. | fixed | 0/1 | none traced | d89059e |
| 14 / SEC04 | Disabled user's cookie still downloads model files. | fixed | 0/1 | none traced | 3881177 |
| 15 / SEC05 | Older unused reset link works after another reset succeeds. | fixed | 0/1 | none traced | 3881177 |
| 16 / SEC07 | Wrong-factory flow utilization returns data. | fixed | 0/1 | none traced | 40c681e |
| 17 / SEC07 | Wrong-factory passport GET exposes its notes. | fixed | 1/1 | all traced | — |
| 18 / SEC07 | Wrong-factory assignment DELETE succeeds. | fixed | 0/1 | none traced | 3881177 |
| 19 / PY01 | Fast employee switch credits work to previous employee. | fixed | 0/1 | none traced | 3881177 |
| 20 / UI01 | Temporary 503/network failure logs user out. | fixed | 0/1 | none traced | 3881177 |
| 21 / UI02 | Timeout stops at headers; response body can hang. | fixed | 0/1 | none traced | 3881177 |
| 22 / UI03 | Rejected pending receipt blocks corrected submission. | fixed | 0/5 | none traced | 3ef1c83, 0056773, e2a6d8c, 641c058, 3532e8e |
| 23 / PERF01 | Package list uses 152 SELECTs for fifty rows. | fixed | 0/1 | none traced | 3881177 |
| 24 / PERF07 | One-label payroll page uses 155 SELECTs with fifty reference groups; old code used seven. | fixed | 0/1 | none traced | 6f5ee2e |
| 25 / PERF41 | Eco history uses 54 SELECTs for fifty dispatches. | fixed | 0/1 | none traced | 732b65d |
| 26 / UI04 | Management dashboard forces labeled demo data. | fixed | 0/1 | none traced | a445cc0 |
| 27 / ST05 | Accessory returns are deducted from two issue groups. | fixed | 1/1 | all traced | — |
| 28 / ST06 | Concurrent accessory returns share an unlocked allowance. | fixed | 0/1 | none traced | 712ccf1 |
| 29 / ST07 | Legacy finished-goods reservations lack shared locking. | fixed | 1/1 | all traced | — |
| 30 / ST08 | Legacy release can restore already-shipped stock. | fixed | 1/1 | all traced | — |
| 31 / ST09 | Damaged packages remain reservable. | fixed | 0/2 | none traced | 9e336ce, f40f4e4 |
| 32 / ST10 | Purchase-request conversion can race. | fixed | 1/1 | all traced | — |
| 33 / WF01 | Generic production PATCH accepts internal fields. | fixed | 0/1 | none traced | 859b7ca |
| 34 / WF02 | Generic work-order commands skip some stage/factory checks. | fixed | 0/3 | none traced | 84c322a, 62a3544, d8cd060 |
| 35 / WF03 | Legacy package creation can bypass missing production evidence. | fixed | 0/1 | none traced | 37258c7 |
| 36 / WF04 | Output/input conservation is not consistently checked. | fixed | 4/5 | some traced | 65586e0 |
| 37 / WF05 | Legacy package model can differ from its order. | fixed | 1/1 | all traced | — |
| 38 / WF06 | Packaging retains target counters loaded before its lock wait. | fixed | 1/1 | all traced | — |
| 39 / WF12 | Daily reports and sewing writes lock parent/child in different orders. | fixed | 1/1 | all traced | — |
| 40 / WF07 | Generic sales PATCH can skip legal status transitions. | fixed | 1/1 | all traced | — |
| 41 / WF08 | Waste sales lack consistent quantity and remaining-stock checks. | partial | 0/4 | none traced | 6cb2d3a, 2948674, c13d638, 01e0ee1 |
| 42 / WF09 | Waste decisions can repeat or reopen completed disposal. | fixed | 1/1 | all traced | — |
| 43 / WF10 | Viewing waste commits recalculated historical values. | fixed | 1/1 | all traced | — |
| 44 / WF11 | Usluga handover and material edits use different lock rules. | fixed | 1/1 | all traced | — |
| 45 / AT01 | Failed/unknown device events can count as attendance. | fixed | 0/1 | none traced | 6afe7eb |
| 46 / AT02 | Incomplete device download advances the checkpoint. | fixed | 1/1 | all traced | — |
| 47 / AT03 | Roster-refresh failure stops event collection. | fixed | 1/1 | all traced | — |
| 48 / AT04 | Removing device profiles hides earlier attendance in reports. | fixed | 1/1 | all traced | — |
| 49 / AT05 | HR and attendance use different day boundaries; weak hours validation. | fixed | 0/1 | none traced | 76388c2 |
| 50 / AT06 | Concurrent or out-of-order attendance imports conflict. | fixed | 0/3 | none traced | 853d2e4, b13bfdc, 135d669 |
| 51 / PY02 | Payroll writers can race with period finalization. | fixed | 0/1 | none traced | b285877 |
| 52 / PY03 | Scanner paths can accept caller-supplied payable values. | fixed | 0/1 | none traced | 900641e |
| 53 / PY04 | Missing date match falls back to latest open period. | fixed | 0/1 | none traced | adc79f7 |
| 54 / PY05 | QR return uses different locks from scan/finalization. | fixed | 0/1 | none traced | a208223 |
| 55 / FN01 | 1C import continues after a failed database flush. | fixed | 0/1 | none traced | ccf409a |
| 56 / FN03 | Moving a payment refreshes only the new invoice. | fixed | 1/1 | all traced | — |
| 57 / FN05 | One-cent advance can leave payment undefined. | fixed | 1/1 | all traced | — |
| 58 / FN06 | Legacy retry keys lack caller isolation and atomic conflict handling. | fixed | 0/1 | none traced | c21e50b |
| 59 / FN07 | Financial types, states and input lists lack consistent bounds. | partial | 4/26 | some traced | 5a68d12, 5c08c2c, a66321b, 77205c9, 652f754, 47f0411, 37527f4, 7e4d055, 3e75ca6 (reverted), ac6c3d6, 0b3950b, 5638b8a, 3e50527, 50cbbe8, 41700e6, e27c514, 9d368e9, ee75b88, 3de6182, f7ff339, 6304934b, 68c794cc |
| 60 / FN08 | Reports mix cancelled invoices, current costs and unclear currency rules. | partial | 0/1 | none traced | 285b69d |
| 61 / SEC06 | Administrator PATCH locks membership; DELETE does not. | fixed | 0/1 | none traced | 74a2973 |
| 62 / SEC08 | Super Admin raw edits bypass domain services. | fixed | 0/3 | none traced | e7782ec, 297d808, df1d08f |
| 63 / SEC09 | Same-second token rotation, incomplete profile response and weak reset-proxy handling remain. | fixed | 2/4 | some traced | b926fba, f35a62e |
| 64 / API01 | Task creator can reassign through PATCH despite stricter creation rules. | fixed | 1/1 | all traced | — |
| 65 / API02 | Task fields lack consistent state/date/reference validation. | fixed | 0/3 | none traced | 22593e7, 31350dc, 73d7ca4 |
| 66 / API03 | Settings PATCH can reset omitted fields or return 500. | fixed | 1/1 | all traced | — |
| 67 / API04 | HR scope, salary/date ranges and required values are inconsistent. | fixed | 1/1 | all traced | — |
| 68 / API05 | Global reports and forecast relationships need explicit business rules. | fixed | 1/7 | some traced | 064be49, fc450a5, 0e9bb6ba, feb7415f, 49d3c200, 4a5c0b2b |
| 69 / PERF02 | Accessory queue computes every candidate before paging. | fixed | 0/8 | none traced | 2c30d5d, 704abef, 3a74e5a, 74211ab, 12579f6, 314265f, 6aaf2ba, 90b7f21 |
| 70 / PERF03 | Reservation planning repeats item and batch reads. | fixed | 0/1 | none traced | 8671636 |
| 71 / PERF04 | Bundle checks repeat accessory checks: B × A query component. | fixed | 0/1 | none traced | c72fcb7 |
| 72 / PERF05 | Label issuance performs roughly two lookups per label, up to 5,000 labels. | fixed | 0/1 | none traced | 538ff66 |
| 73 / PERF06 | Unbounded bulk payroll repeats validation and refreshes. | fixed | 1/5 | some traced | f42637c, 8240fc9, 67f0309, c625aad |
| 74 / PERF08 | Receiving queue loads all packages and detailed children. | fixed | 0/5 | none traced | 890177e, 3da6174, cbebcd4, 2dd8ef8, 330374c |
| 75 / PERF09 | Package writes repeat allocation, costing and workflow queries. | fixed | 0/6 | none traced | 0066d32, a51eb6f, a3f8948, cd6ec8b, 0ce77fb, a93409d |
| 76 / PERF10 | Receiving/placement repeats package, stock and member reads. | fixed | 0/4 | none traced | ba1fe9a, 749ea5a, 4bfc9b3, b6ab791 |
| 77 / PERF11 | Print-run listing reads members separately per run. | fixed | 0/1 | none traced | 7dacb8d |
| 78 / PERF12 | Label printing repeats model/asset/allocation lookups. | fixed | 0/8 | none traced | f27e240, 9fe1c14, 7f5b30d, d990aa6, 4fba5f1, f378278, 2f92465, 6277260 |
| 79 / PERF13 | Bundle receiving repeats legacy lookups and gates. | fixed | 0/7 | none traced | ef9cb88, 952b569, 49fdeea, df862ca, fb79677, f4c8723, f5977d0 |
| 80 / PERF14 | Passport operations repeat order/material lookups. | fixed | 0/6 | none traced | a3f8127, 2279d2d, 8bf780a, 9cac5fb, 5890272, 10198ea |
| 81 / PERF15 | Planning loads BOM per sales line and stock per item. | fixed | 0/1 | none traced | f72d71b |
| 82 / PERF16 | Flow utilization repeats assignment/work-order queries. | fixed | 0/2 | none traced | 3e29732, 5e9418a |
| 83 / PERF17 | Daily sewing reports repeat passport/model lookups. | fixed | 0/1 | none traced | 3e2ff6a |
| 84 / PERF18 | Receive options process all scopes before limiting output. | fixed | 0/4 | none traced | 3217856, b61e210, 3aa28b9, 96d7a61 |
| 85 / PERF19 | Cutting reconciliation repeats aggregates per work order. | fixed | 0/3 | none traced | 87c1b76, 7ebe82b, cf7e606 |
| 86 / PERF20 | Cutting/packaging paths repeat bundle, log, stock and BOM reads. | fixed | 0/6 | none traced | 57a0b35, b4e91e5, 82824ef, 4a0ee8e, 5d8a765, 05206df |
| 87 / PERF21 | Traceability expands related histories with repeated queries. | fixed | 0/9 | none traced | 2f8f951, ae88bb5, 4447c97, a4f005a, 24bba90, 6acfa70, 16d9ec4, 403af90, 873979a |
| 88 / PERF22 | Usluga list is unpaged with repeated child reads. | fixed | 0/7 | none traced | d1c4117, c8ac9f3, 0005ff3, bec46dd, 55fef7f, 9c5d9c9, cadb035 |
| 89 / PERF23 | Pricing lists lazily load model assets/BOM; screens poll frequently. | fixed | 0/3 | none traced | b6b5aab, 7823723, c280884 |
| 90 / PERF24 | Sales/shipment serializers conditionally fetch missing related records. | fixed | 0/2 | none traced | 93f8b59, d687557 |
| 91 / PERF25 | Sales history loads/sorts all candidates before summary output. | fixed | 0/3 | none traced | 565d1cd, 71a496f, be84006 |
| 92 / PERF26 | Legacy branded reservation repeats variant checks/repair. | fixed | 0/3 | none traced | 5a89e27, 2cc66e0, fbdda65 |
| 93 / PERF27 | Shipment operations repeat package checks and order synchronization. | fixed | 0/4 | none traced | 9d1755e, c0ff783, 8de1073, 02e8db8 |
| 94 / PERF28 | Purchasing repeats per-line reference and audit-head reads. | fixed | 0/8 | none traced | 1efce38, 67f0309, 4137431, d200161, b4b2da0, 23d149a, 5698e99, cda1df0 |
| 95 / PERF29 | Customer/1C processing recalculates payments per invoice/row. | fixed | 0/4 | none traced | 91f2f73, 8235602, 138420b, a11fd43 |
| 96 / PERF30 | Catalog clone/rename/approval repeats probes and broad scans. | fixed | 0/6 | none traced | bb93fbc, 4a4d0e6, 0775eaf, acea29d, a5631ea, b4db4b4 |
| 97 / PERF31 | Attendance person import reads each person separately. | fixed | 0/1 | none traced | a0b9862 |
| 98 / PERF32 | Inbox/forecast helpers conditionally load assets and references. | fixed | 0/9 | none traced | f79d195, 6c2c5ac, b40cace, 491058b, 8574264, 3cc7e67, 7f0d085, 0e2bd6d, ed4be77 |
| 99 / PERF33 | Stocktake loads all results before paging; exports build whole output. | fixed | 0/14 | none traced | 7fe32ef, 1610476, a47de56, caa430c, 2f941d2, ea2202f, 9c57d56, 263d2b5, 95111b5, 056badd, 5bf12ec, 9278f60, 44faa28, 31b4254 |
| 100 / PERF34 | Shipment document repeatedly searches lists. | fixed | 0/1 | none traced | a14827f |
| 101 / PERF35 | Growing business lists/reports/exports may load everything. | partial | 1/74 | some traced | ac27943, 9e50847, 35182b8, 2978048, a66321b, a8307d8, 7b45c23, 58b9317, 64f97e9, 0c51202, ee43ff3, 39aded7, 0760289, 9993e26, 1974b3d, 3188ee4, e9c37b4, 37d6bc6, edf17ac, a1ceb96, 851e015, 972ed0b, a65b621, 754bbab, b7c6453, ba8b25f, 321c4d0, f05bfdd, 33a19cd, 58a50bc, c7e2754, af59e49, 95e961d, 2b40ac4, 28c8246, 49c8e71, 3427714, a3db96b, c0208ba, c1ecec2, 57acf05, 18a6e99, 9a9d0b3, 3234b03, c3b40cb, c89c5f7, 78c7477, 444a4bd, 61f57bf, a5a20ec, e5cbce5, a39f245, bdf94a9, 1c888c6, d946d3a, 7eefc6d, 6d12669, 5856d7b, d78ca27, 0c3a1c3, 764af78, 7c0a404, 339e4c2, 32eb372, 2f941d2, 9e2d34d, 68f9c59, 1070ffb, 5125049, 2e25fb2, bc3e63f, d2a65b9, fddd73ae |
| 102 / PERF36 | Notification/task fan-out and admin table counts grow with recipients/schema. | fixed | 0/5 | none traced | c5b2483, b6a8beb, 1785a88, ebe8399, bd36441 |
| 103 / PERF37 | Async middleware calls blocking SQLite rate-store writes. | fixed | 0/1 | none traced | 25fd549 |
| 104 / PERF38 | Historical per-IP budget is shared by office users. | fixed | 0/1 | none traced | a8b1707 |
| 105 / PERF39 | Frontend has dependent requests, duplicate keys and hidden-section fetches. | fixed | 0/20 | none traced | ada4aaf, 5a85dcd, 0094748, fd5bf6e, 4c75160, 8589ba4, be696e1, 55468e1, 7d841b1, ea3acaa, 7445ad4, b3f3d9f, 7f947c5, d025ee8, cb2ba52, e101d30, 1da4f66, 044e121, 534c8bf, b669bd4 |
| 106 / PERF40 | Async uploads do synchronous image/SQL/disk work; file lifecycle gaps remain. | partial | 2/14 | some traced | 170200f, 940acd5, 056009d, 81887a1, 64f98a5, 3452166, 31a3a3c, 623c169, b2958f0, b607eda, 359df00, 1f13f27f |
| 107 / PERF42 | Sewing line context repeats capacity sums per row. | fixed | 0/1 | none traced | 2166dba |
| 108 / DB01 | Alternate writers enforce different quantity/reference/state rules. | partial | 1/25 | some traced | 3d15874, 287fab2, 1610d50, df14ad6, 5b4ac7c, 59ea70b, f691900, 91fb323, 5d031ca, 88c22c6, 0e117fe, 5904c4b, db3a94c, 3712c9e, 5b037dc, de8585f, 4508120, 9404a6fe, f224b6f5, efbae11f, a229d40d, eedfe49b, 6779a1e2, 69ceef4e |
| 109 / DB02 | Some commands use loose strings/raw dictionaries. | partial | 3/18 | some traced | bf36441, 7fdc2cb, f03259b, f2ff6e8, bed96e7, b0e9e71, 2de9bf7, 57cb07f, 8711c96, 9748ead, e267e56, 9bdf79c4, cb0af8e3, a9bce608, 0b2b6820 |
| 110 / DB03 | Editable JSON structures need shape/version validation. | partial | 1/20 | some traced | 8d386cf, ada93f8, 30119aa, 4def8fb, 7453b9b, d034a12, 9748ead, 708475d, a87466c, 2b79edd3, 4f4efcb8, 3a513e93, de3bda68, 7767ee3c, aa7f27c2, 941c8cf8, acab0a9c, a5e98b11, 6ee3b032 |
| 111 / DB05 | Some migrations change permissions or repair/delete data. | partial | 0/12 | none traced | d23738c, 0df2c17, 2901212, f81cb47, dea28bb, fd86104, da20712, f3dd734, 75fd0fb, 7cd06cb, 87c16a05, 6118771b |
| 112 / DB06 | Saved catalog has duplicate constraints/indexes and missing-index candidates. | partial | 0/1 | none traced | a590222 |
| 113 / DB07 | Four-digit order/bundle namespaces have finite capacity. | fixed | 0/2 | none traced | b350c4f, 11aabc1 |
| 114 / OPS01 | No correlated peak-time browser/API/SQL/network trace. | open | 0/0 | no recorded fix | no recorded fix |
| 115 / OPS02 | Worker/pool connection budget is not proven. | partial | 1/1 | all traced | — |
| 116 / OPS03 | ERP shares infrastructure with other workloads/backups. | open | 0/0 | no recorded fix | no recorded fix |
| 117 / OPS04 | ERP VMs share a physical host. | open | 0/0 | no recorded fix | no recorded fix |
| 118 / OPS05 | Basic health endpoint does not prove dependency readiness. | partial | 2/3 | some traced | c275be7 |
| 119 / OPS06 | Uploads depend on server-local storage. | partial | 0/1 | none traced | 13f5994 |
| 120 / OPS07 | Firewall, shaping, DNS and actual branch paths are incompletely checked. | open | 0/0 | no recorded fix | no recorded fix |
| 121 / OPS08 | Old dependency/lifecycle findings need a fresh scan. | partial | 0/4 | none traced | 1896408, f288ada, f0a1536, 06705b9 |
| 122 / OPS09 | Historical headers/proxy trust/integration identity need review. | partial | 1/4 | some traced | aa8fac1, 0ad74a69, f961a65c |
| 123 / OPS10 | Restore targets, retention and witnessed recovery are unproven. | open | 0/0 | no recorded fix | no recorded fix |
| 124 / OPS11 | Credentials were shared through handover documents. | open | 0/0 | no recorded fix | no recorded fix |
| 125 / DB08 | ORM-only test schemas differ from the migration-created database. | fixed | 0/1 | none traced | 1141d40 |
| 126 / SEC11 | Quality-check creation accepts a work order without checking its factory. | fixed | 1/1 | all traced | — |
| 127 / UI05 | Legacy home Production KPI adds cutting, printing, sewing and packaging quantities. | fixed | 0/1 | none traced | a0818c4 |

Method: read develop `docs/audit_backlog.json`; resolve each cited hash; compare against clone_main ancestry, cherry-pick origin trailers and `git cherry` stable patch equivalence; exclude reverted sources `b097037e`, `6a902d7a`, `3544b1f4`, `3e75ca62`. No working-tree merge trial, production verification or full regression audit was performed for this report.
