# BSO factories, fabric receipts and operation copying — 10 November 2026

## Verified production and authority

Both hosts serve **green `20261109_163130`**, app
`271c5005e12d1efc65d6358756862d8c243685a5`, source manifest
`535aa197ba218b0d0e867480d6a6570a25273307dfdea2185ce28d383f4e56d7`.
Backend activated 04:04:10.921097 UTC (09:04 Tashkent), frontend 04:04:49.823435 UTC.
Running compatible rollback is **blue `20261109_035740`** / app
`4f33eba776284b2e950e201a29c9da06cf7bd237`. Schema remains `0155_eco_gate_merge`.

Backend image:
`ghcr.io/shmirzaev/milana-erp-backend@sha256:f56b85118b14635a0c0a1dca63ffb2a054cefdf7943b0cfc8dea21652c5fda67`.
Frontend image:
`ghcr.io/shmirzaev/milana-erp-frontend@sha256:0af5d5d280f0336659f02004b36b964ec372ccf8d1eb9141654237a4df27c0c6`.
The exact previously staged immutable containers were verified and adopted; no
rebuild, pull, restage, source modification or migration occurred during resumption.

The owner requested deployment, chose Edge, waived 30-minute monitoring and
separately overrode the disclosed pending named QA-master requirement. No human
QA approval is claimed. Two separately disclosed timing exceptions were explicitly
approved: original paired fabric-batch medians, then the three actual public p95s.
Operator acceptance remains pending. The historical [9 November stopped attempt](BSO_FABRIC_PAID_COPY_CANDIDATE_2026-11-09.md)
did not activate the candidate then; its pending-approval statements describe that
earlier attempt.

## Delivered behavior and actual checks

BSO page and appended Excel factory column map CUT to Milana and ECT to Eco Cotton,
retaining unknown stored names. Existing 19 columns, other sheets, pictures and
formula safety remain. Public BSO0083 shows one Eco Cotton and thirteen Milana rows;
fresh Edge download `0083 (1).xlsx` independently parsed the same T3:T16 values
and four sheets. Readback SHA `726fbbc7d2eae424aef57a9a1ad5f66cd35f0ca3574664acbb51a2703b0b4247`.

Fabric active inventory displays nullable current-unit RECEIVE sum separately from
remaining stock, with no balance fallback. Public batch7586 shows received576.80kg
and remaining196.80kg. This is quantity, not monetary value. Desktop was rechecked
publicly; prior actual narrow mobile verification belongs to these identical sources.

Paid-operation copying retains all factories/rates/metadata and target details,
resets draft quantities, preserves source and requires normal target Save. Public
target model3 had126 operations; source ТJ2026-V-983 copied111 draft operations,
37 each for Milana, Besttex and Eco Cotton Sewing. Self-copy was disabled. Full
reload restored126 without Save. Earlier isolated saved-copy/reopen/database
checks passed; no production business QA data was created or saved.

[Exact-source CI42655675048](https://github.com/Shmirzaev/Milana-ERP/actions/runs/42655675048)
passed all five jobs: 6,651 backend tests / 1,568 skips / 36 subtests, mandatory
PostgreSQL, frontend, security policy and image publication. Focused backend67,
frontend16 render cases, strict TypeScript, scoped Ruff/compile and independent
reviews passed. Full selected BSO/order/model/options/batch/receipt and original
19-column/four-sheet workbook contracts passed before and after the new read phase,
and again internally after the public postcutover measurement.

## Preserved failures and exact owner decisions

| Metric | Baseline ms | Candidate ms | Limit | Actual owner approval |
| --- | --- | --- | --- | --- |
| Paired AB fabric-batch median | 36.716455 | 43.049344 | +10% | Approved exact original exception |
| Paired BA fabric-batch median | 37.422517 | 42.847368 | +10% | Approved exact original exception |
| Public search p95 | 217.138172 | 268.111250 | +15% | Approved these three exceptions and keep live |
| Public model-groups p95 | 216.329771 | 283.766796 | +15% | Same exact public decision |
| Public stock p95 | 161.392943 | 191.490336 | +15% | Same exact public decision |

Original machine reports remain **false / exit1**, with unchanged budgets and no
measurement retries. All other measured limits, full ordered facts, receipts and
payload checks passed. Public postcutover report contains144 samples/145 HTTP200
GETs and exact active/runtime/CAS bindings. No blanket performance pass is claimed.
Original owner record `9055e7130b269fdb66612f72dbd18b2adef35a337049202741a90fe36a22d3ea`
and new public owner record `dbe5ce05c624b4b8772439bdbf1796088544cb0fb0182a9833219076a570637c`
are separately validated; neither grants any other technical waiver.

Normal factory activity changed three frozen fields overnight: matching active
batches907→901 and item87 quantity47032.98→45228.08/available46509.98→44705.08.
Four canonical SQL counts and exact six newly depleted archives explain the count;
seven prior StockBatchAdjustment issues4377–4383 total1804.90kg and independently
reconcile the stock delta, with reserved523kg unchanged. Fresh all-six-endpoint
A/B complete parity passed. No quantities, rows, ordering or receipt fields were
dropped or normalized. Global snapshots remain concurrency evidence, not quiescence.
The initial old-dataset baseline failure and total-only bridge rejection remain false.

The initial public UI console attempt remains failed: two rapid-query AbortErrors
from unchanged useModelOptions/api code plus external extension errors. A separate
settled UI attempt has **zero ERP errors/warnings**, while two exact ad-blocker
JSON configuration errors remain in full raw console. An independently reviewed
exact-message/extension-stack/route classifier rejects all unknown, mixed, app or
warning records. Raw console is explicitly **not globally clean**; the app AbortErrors
were not allowlisted. No browser extension or application source was changed.

## Backup, closing and cleanup

Validated dump `/app/storage/.milana-backup-archive/milana_erp_pre_20261109_163130_20261110_033641.dump`:
116,508,154bytes, mode0600, 1,395 restore-list objects, SHA
`d8197e1e6e7a97379b8f8351c6716f40f7daf3071edac12cf1c5087617d4a762`.
Restore-list SHA `4e5235f0bf0e8a092e6257d9d0b45e304c9b72b1f4004a3bd5ee138f77abf951`.
This validates the list; it does not claim an executed full restore.

Fresh formal closing passed backend at04:24:02UTC and frontend at04:24:25UTC:
all four supported internal/public health/login endpoints, readiness, exact sources,
images/default CMD/two workers, zero restart/OOM, routers, database/schema/index/
headroom, conserved historical logs and healthy retained blue recovery. Owned
leases were released04:24:31UTC. Preview process identities were verified before
stopping; ports3211/18109/13109 are closed. All owned QA tabs closed, menu state
restored and no viewport override remains. No observer or substitute monitor ran.
No production business QA writes, migration, backfill, retention deletion or image prune.

Existing security findings remain: backend51HIGH/0CRITICAL, frontend1MEDIUM;
historical log failures and broader ERP audit risks were not fixed by this release.
Disk maintenance and operator acceptance remain follow-ups. Initial cancellation
console behavior remains a pre-existing UI quality issue, despite settled verification.

## Exact local evidence and source handoff

Dedicated worktree `C:\ERP\.codex-work\bso-fabric-paid-copy-20261109`, branch
`codex/bso-fabric-paid-copy-20261109`; app PR553 and prior metadata PR554 merged
on owner-approved `clone_main`. This release record is a documentation-only follow-up
to clean integration `8813c2918bcdec6760a2fd9e3a57ba05689bc04b`; it changes no images.
Evidence is retained under ignored `.qa-bso-fabric-copy/deploy-resume-20261110/`;
independent validators/proofs are in the reviewer worktree's `outputs/deployment/`.

| Evidence | SHA-256 |
| --- | --- |
| Final released journal | `46cead632b55a12cd8f0993aaba3fa9412ce8771be1e8384bbf7b06d7f2bc90c` |
| Independent 38-input final conjunction | `c4e62683742f302dfe3fd7c51c69a299eb388655c230b715434f60106d01f70b` |
| Final 38-input manifest | `efdcb1797ce24438b74ef0439dc9a27b21eb88875d76196d3d6a423d20b8e723` |
| Actual failed public report | `7067ace1ee6ff2cdb3200b48927bb5862d7d85adf10c0004b9403313096dd77b` |
| Fresh public baseline | `fe4309ca9428beefd8aa5869343feee883b0133d56242aecb1136a87ce19d904` |
| Final protected internal contract | `35e6fa092a46e48c06aaa9be7613c279678240fea7ecc60690656b231607ade2` |
| Public browser record | `d19b90d0766b63b1d0e9b6c509a75e80845461d99c0f6d88383e2c1817113c75` |
| Full final raw console | `8213126ab325d3a575b8f51894b15a309b9e0597d12ef0e28a3f2fe954f3726d` |
| Preserved initial UI failure | `5254f599599af5ad0e98907781cef0c211b6cbf6bbf60615337f5812a032afa5` |
| Preview cleanup | `d3d418e54c001ee787e564c4f27f2651c0ad8bc28aa9ad2b5b4f2b50d7edd92e` |

Formal postflight gate `6c416b6e3d858a97f5e3631acc31b41cdc50d1230a996fbe3467f21fbfdacfdd`
binds the reviewed 38-input conjunction; the final closing journal additionally
records fresh canonical checks and exact owned-lease release. No human acceptance,
all-security-fixed claim or globally clean console/performance claim is inferred.
