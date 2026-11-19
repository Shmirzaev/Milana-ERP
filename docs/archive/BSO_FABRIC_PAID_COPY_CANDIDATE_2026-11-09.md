# BSO, fabric receipts and paid-operation copy candidate — 9 November 2026

## State and authority

**Not deployed.** At final readback both hosts still serve blue `20261109_035740`,
app `4f33eba776284b2e950e201a29c9da06cf7bd237`, manifest
`e5d56b822d8a48d327429a5e6a59cd87111b81bb193a2fd8cf120d007a7fafb1`.
Schema remains `0155_eco_gate_merge`. Corrected candidate is green `20261109_163130`,
app `271c5005e12d1efc65d6358756862d8c243685a5`, manifest
`535aa197ba218b0d0e867480d6a6570a25273307dfdea2185ce28d383f4e56d7`.
PR552 and corrective [PR553](https://github.com/Shmirzaev/Milana-ERP/pull/553) are
normally merged on owner-approved `clone_main`. Neither candidate was activated.

User requested all three features, chose Edge and waived 30-minute monitoring.
After the separately disclosed named QA-master requirement, the owner instructed
“It shouldn’t stay cutting it should say Milana or Eco Cotton fix and deploy fast”.
This was disclosed as a narrow owner override of that pending human record; no
human approval is claimed. It does not waive the newly measured timing failure.
An explicit question described both exact failed medians and the +10% rule and
asked whether to approve that specific exception or optimize first. No answer has
been received. Operator acceptance remains pending. No observer/start anchor ran.

## Candidate and verification

The BSO table and appended Excel column T use exact existing CUT→Milana and
ECT→Eco Cotton mappings, retaining unknown stored names. Existing 19 columns,
other sheets, pictures, formula safety, API department names and routing remain.
Fabric active inventory adds nullable current-unit RECEIVE sum in one grouped
query, separately from remaining stock; no missing-evidence balance fallback.
“Received amount” is implemented as received quantity, not monetary value.
Paid-operation copying uses authorized existing model reads and target Save,
retains factories/rates/metadata and target details, resets draft quantities and
preserves the source. Empty/self/malformed/failed reads cannot clear the target.
Copying creates an unsaved draft. Existing factory scope and catalog namespaces
remain authoritative. No permission or schema was changed.

[CI42655675048](https://github.com/Shmirzaev/Milana-ERP/actions/runs/42655675048)
passed all five jobs for exact app271c: 6,651 backend tests / 1,568 skips /
36 subtests, mandatory PostgreSQL, frontend, security policy and image publication.
Focused backend67, frontend16render cases (red before canonical-label correction,
green after), strict TypeScript, scoped Ruff/compile/diff and independent source
review passed. Earlier isolated local PostgreSQL and actual saved-copy/reload/DB
readback passed. No live business Save was performed.

Actual signed Edge candidate BSO0083 has one Eco Cotton and thirteen Milana rows;
its downloaded 6,708,698-byte workbook independently parses the same values in T.
Batch7586 shows 576.80kg received / 196.80kg remaining on desktop and actual narrow
mobile screenshot360x780. SourceTJ2026-V-983 copies111 draft rows,37 per factory;
self-copy is disabled. Full reload restores original targetmodel3's126 operations.
Four actual console captures are empty; four screenshots were visually reviewed
independently. Download-await tooling timed out after the completed workbook was
saved; the existing file was read rather than redownloaded. A stale owned test tab
was closed by its exact documented tab ID; unrelated user tabs were preserved.
Temporary viewport overrides were reset.

## Preserved timing failure and complete read bracket

Original paired report `5df0b93366a6f9f9e60977b0f6c1759a1edff711120349a63d98a1ab55c50498`
remains `passed=false`, `STOP_INSPECT`, exit1. Its sole failures are:

| Metric | Baseline ms | Candidate ms | Ratio | Limit |
| --- | --- | --- | --- | --- |
| AB fabric-batch median | 36.716455 | 43.049344 | 1.1724809489369274 | 1.10 |
| BA fabric-batch median | 37.422517 | 42.847368 | 1.1449622161972697 | 1.10 |

All measured p95/payload/ordered-fact checks passed. The canonical runner stopped
at four of six endpoint names:384 samples/386 GETs. A separately reviewed bounded
continuation measured only untouched inventory-stock and shipment-report names:
192 samples/194 GETs, original AB/BA3warmup+21measured protocol and unchanged
10%median/15%p95/15%payload limits. It passed; failed names were never retried.
The first continuation proposal failed source review before execution because
its two-name input met a canonical full-endpoint guard; the fixed AST-derived
suffix dispatch passed actual fake-call and independent fault tests. Original
proposal and failure remain preserved as review evidence, not runtime evidence.

Strict serial bracket: contract-before→original failed paired→public baseline
freeze→untouched continuation→contract-after. Complete selected BSO/order/model/
options, old19 Excel columns/four sheets/seven rows/fourteen pictures, full selected
batch and receipt ledger match at both ends. All phases bind exact images,
containers, config and both-host CAS. Global snapshots are concurrency evidence,
not quiescence or per-mode functional SQL claims. Public baseline144samples passed;
public-after-cutover checks have not occurred because cutover did not occur.

Independent nineteen-input technical review explicitly records `passed=false`,
`technical_evidence_validated=true`, `specific_owner_exception_pending=true` and
`activation_authority=false`. The separate twenty-input acceptance validator
requires an actual owner record approving only these two exact medians. Its
pending owner input cannot pass; no user record was synthesized.

## Images, backup and cleanup

Backend: `ghcr.io/shmirzaev/milana-erp-backend@sha256:f56b85118b14635a0c0a1dca63ffb2a054cefdf7943b0cfc8dea21652c5fda67`.
Frontend: `ghcr.io/shmirzaev/milana-erp-frontend@sha256:0af5d5d280f0336659f02004b36b964ec372ccf8d1eb9141654237a4df27c0c6`.
Fresh validated PostgreSQL dump,116,292,545bytes/mode0600/1,395 restore objects:
`/app/storage/.milana-backup-archive/milana_erp_pre_20261109_163130_20261109_170724.dump`,
SHA256 `ec5953f23ca3721307d0b43575031e119ee048e7ebed51ba1e46640b7bf2d379`;
restore-list SHA256 `7de243a05612bca73d6c4e41a1a48baf2feb2830d8fe5087cf4b6cf0bd073a14`.
Restore-list validation does not claim an executed full restore. No migrations,
backfill, production business QA writes, retention deletions or image pruning ran.

Both owned deployment leases were released. Four exact start-time/executable/
command/parent-verified preview processes were stopped; ports3211/18109/13109 are
closed. Fresh read-only checks confirm unchanged full active/staged snapshots and
healthy stable blue and inactive green on both hosts, zero restarts/OOM and strict
sources/workers/routes/readiness/database/log guards. Production-base JSON remains
unchanged. The active blue container is the retained compatible recovery target
for any later green activation. Old rollback metadata still names the earlier
green release; the physical inactive slot now contains this unactivated candidate,
as explicitly recorded in the journal. No final deployed closing or public-after
acceptance is claimed.

Security policy passed with retained backend51HIGH/0CRITICAL and frontend1MEDIUM
findings. Existing baseline log126Traceback/21HTTP5xx/42ERROR/147Exception markers
remain explicitly historical failures; all new markers fail. No risk was hidden or
relabelled as zero. Disk maintenance and previously documented ERP security risks
remain follow-ups.

## Evidence and continuation

Worktree `C:\ERP\.codex-work\bso-fabric-paid-copy-20261109`, branch
`codex/bso-fabric-paid-copy-20261109`; legacy checkout preserved. Exact evidence is
retained in ignored `.qa-bso-fabric-copy/deploy-20261109_163130/` and independent
review outputs under `C:\ERP\.codex-work\bso-deploy-log-adapter-20261109\outputs\deployment`.

| Evidence | SHA256 |
| --- | --- |
| Frozen helper | `7266f665fb4e05ad1f4ad57c4d73a974e7ee34d1b7d83e9cec9ed65fcaf591a9` |
| Frozen config | `679dac9430c0884b64d4cbe764fbfc1384d12065603c3fbec389c8b738c7ac0f` |
| Candidate browser | `dc9b58574244ae92e0291b957094402904887b7e7761184fb5e31494386cfbaa` |
| Contract before | `1ea391650ad4e792f7e94b18c3ff8126802c5c0d2491cdc68d81255fd635d148` |
| Contract after | `cb903b6e81e054ba2cbc72adcf31a2e8b6261a35eed257c783b235671bf69b01` |
| Public baseline freeze | `eb79c56c4c77c22e52946b2f93b110a33e4e3595b8e99d3b9d157b43f12e8003` |
| Untouched endpoint continuation | `7d12c52747289837495cfb3c4fbc9540a47a64b644b068f71656b10152a1b0b9` |
| Technical review, owner pending | `d34fb3fddad0bef857e7eae2c1f324a6673df7a4d667783c078e68274feb269c` |
| Exact pre-release journal snapshot | `4f96194ccf85d1ba8037297015191ef925febaaf3edb6e9a194d2d45b20f06d9` |
| Final active/staged readback, leases absent | `ad6ed1e88c84d0156bccb734eb41a64f3475c2c54bd0c5df41bb7ab521f11a04` |

The live journal legitimately gained lease-release entries after the technical
review. `pre-release-journal-snapshot.json` preserves the earlier exact bytes,
verified against its already approved manifest hash; it was derived by removing
only those release entries with original Windows serialization. The current
journal was never rewritten to pretend leases remain held. Local LF serialization
initially failed the hash check before any snapshot write, then exact CRLF bytes
matched. No remote action was retried or evidence overwritten.

After a real owner answer, use fresh owned-lease/runtime/expiry/source guards and a
new reviewed continuation configuration; do not reuse a released operation journal
or expired log/selection evidence. Successful activation still requires backend
then frontend, actual public Edge checks, public comparison at unchanged limits,
final internal workflow contract, all four supported health checks and fresh
closing/rollback guards. Monitoring remains explicitly waived. Future metadata
commits do not change the application image or establish deployment.
