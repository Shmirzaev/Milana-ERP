# ECO inventory release — deployed 4 November 2026

## Final release and rollback

Both hosts are active blue `20261104_080711` / exact runtime
`984aeffb22aedd3262d7cd61e2d88a905b589e8d`, manifest
`0221829adfc216391679b744ae512b6c4d96913bb0316c31dfe12fb9a1641be7`.
Backend reactivated 11:20:29 UTC; frontend 11:20:32 UTC (16:20 Tashkent).
Database is `0154_eco_receipt_details`. Compatible running rollback is green
`20261104_093330` / `bd7d572282b50886e9d03a650bcf886ca9109175`, manifest
`c7b225466e539d4359e5022f37795f0ab2c065cbffdddc6ff1e8dd73563426dd`.
Both actual immutable backend defaults were cold-tested on 0154. Never downgrade
schema or restart original 11f/0150 image. Startup seeds/schema sync remain false.

Owner deployment authority and 30-minute observation waiver were honored.
Specific public failures were each recovered first and explicitly accepted.
No timed observation, performance resampling, threshold changes or relabeling
failures occurred. Technical verification does not invent human acceptance.
[PR #406](https://github.com/Shmirzaev/Milana-ERP/pull/406) is pushed, draft and
unmerged; reconcile unrelated integration and migration graph separately.
The live runtime is the narrow reviewed 984 image, not clone_main.

## User entry points

- ECO inventory -> Materials and suppliers -> Materials / Accessories / Suppliers
  maintains the shared catalog. Receive materials -> Opening stock enters existing
  stock; Supplier delivery enters new deliveries. ECO quantities remain separate.
- Detailed receipts include batch/color/date/document, warehouse/order, unit cost,
  QC, images and notes; fabric adds roll weights, width/grammage and length.
- Separate fabric/accessory stock and history track incoming/outgoing/available.
- Milana factory fabric transfers dispatches QC-passed stock with driver Excel;
  ECO Incoming transfers receives quantities, including partial receipt, with
  conserved ledgers and traceable status.
- ECO accessory plans discover assigned orders/models/BSO; approval reserves
  after BSO and before sewing; physical issue deducts once. Shared work, direct
  lines, batch scope and supported historical aliases are covered.
- Legacy model/variant, actual sewing-factory package/warehouse fields and filters,
  and cutting-passport Excel are present. Actual downloaded workbook contains
  632 passport rows/12 columns and 690 material rows/32 columns.

## Verification and accepted failures

[Exact feature CI 41797100345](https://github.com/Shmirzaev/Milana-ERP/actions/runs/41797100345)
passed 5,041 backend cases (560 skipped), mandatory PostgreSQL, frontend lint/strict
types/build; extra PG 41797099817 passed. Bridge CI 41808512414 passed 5,031 backend
cases plus PG/frontend and actual default-image cold boots on 0150/0154.
Feature isolated immutable default-image cold QA verified 0154, integrity, zero
business fixtures and owned cleanup. Independent source/config/ops/visual reviews
passed. Both seven-endpoint paired comparisons passed 120 samples + 5 warmups per side.

Final public bridge inventory p95 failed 163.779272 -> 199.866143 ms (+22.033845%);
median +1.69%, same 50 rows/45,365 bytes/fingerprint. Original 0150 runtime was restored
and verified first. Owner: **"Continue with this specific p95 exception"**.
Same bridge images were reactivated after fresh backup, without resampling.

Final public feature failures:

| Endpoint | p95 baseline -> candidate | Median change | Data |
| --- | --- | --- | --- |
| Model groups |214.274114 -> 271.350464 ms (+26.637072%)|+1.204172%|Same 1 row/5,437 bytes/fingerprint|
| Process tracking |1194.976115 -> 1515.793387 ms (+26.847170%)|+0.910562%|Same 1 row/5,606 bytes/fingerprint|
| Print runs |Latency improved|Improved|50 rows both, fingerprint changed; 161,420 -> 131,024 bytes|

Compatible green was restored immediately; all four health checks passed.
Owner: **"Continue with these specific exceptions"**. Original failures remain
FAIL, accepted only for this exact release/result. Source review found no added
database work on failed GETs; 23 earlier route matches are possible constant overhead,
not an established cause. The p95 cause remains unproven.

One-shot structural diagnosis found 16 new print runs after baseline start and
identical current two-runtime 50-row responses. This supports live page turnover,
not equivalence to the original dataset or proof that all 16 existed at its exact
print measurement. Inline SQL source was not archived, so its bounds were not
independently reviewed; saved JSON consistency and payloads were. This is not a
new passing benchmark.

The shared branch advanced from febe73c6 to 7f847987 during final reactivation.
The integration-head guard refused before any activation intent/traffic change.
Independent review of the 6-path PR #393 sales-filter delta confirmed it is unrelated
and excluded. Only that pin changed in a reviewed config/wrapper/new ledger;
preflight/preparation/fresh backup/adoption repeated. Failed attempt is preserved.

Final upgraded-schema backup: 111,953,078 bytes, mode 0600, 1,329 restore objects,
96,150 restore-list bytes; SHA
`a5539d47e3ccbbf7594b28a6e163775baaf67dd1072706aa980a1b17cb9b2f95`.
Earlier pre-migration backup and failed/recovery ledgers remain retained.
All four health checks (internal/public API/UI), schema/router/source, immutable
image/container/worker continuity, pools/headroom and startup/log checks passed.
Disk stayed below 80% after narrowly reclaiming unused Milana image caches;
active, rollback, candidate, volumes, backups and business data were preserved.

Final API readback passed 9 invariants, unchanged balances/users/roles and no business
rows created/deleted within its window. All 7 new ECO tables remain empty. Real users
continued operating throughout. Actual Edge inspected 12 candidate screens and actual
Excel, then live receipt/catalog screens. Candidate proxies forwarded 244 GETs/zero
writes; two 404 paths were unknown. Final closing proxy forwarded 16 GET/HEADs
(15x200, 1x304), zero writes/5xx and unchanged exact identities. Forty-one cumulative
external extension errors, zero ERP console errors. A first live proxy without
PTY was interrupted without closing JSON; this incomplete attempt is retained.
A separate PTY closing session verified continuity. One full-page screenshot
timed out; ordinary screenshot succeeded. QA performed no production business
Save/Dispatch/Receive/Approve/Issue/Print or role/user creation.

Leases released and QA proxies stopped. Local review remains running at
http://127.0.0.1:13085. Optional supplier placeholder says "No production order";
actual choices/validation work. This cosmetic follow-up remains. Human acceptance
of business handoffs is separate; isolated PostgreSQL CI covers lifecycle/races.
Evidence hashes and immutable image pointers are in the adjacent JSON record.

## Preserved earlier preparation checkpoints

The notes below describe earlier states, not the final release status.

The owner explicitly instructed: **"deploy without 30 minute monitoring"** after
local review of PR375. This authorizes release of that feature and waives the
timed observation period only. Backup, immutable builds, source reconciliation,
candidate QA, performance and immediate/final health gates remain required.

## Exact scope and baseline

Both production hosts were freshly verified as blue20261103_094602, source
`11f80a2995daeeb90b5c01318aec9e9c6a40f1c9`, manifest
`ee765f999e782193878390897873c7b5865749460d4d776cf321fcd28490f8a9`,
database0150_package_customer_release. Green20261103_112256 is the recorded
compatible rollback. Source manifests pass full verification on both hosts.

The narrow release worktree starts at that exact active commit. Only the
73 reviewed PR375 feature paths are ported from its d6c2edd8→f49c2675 diff;
broad context/bug files and local demo runner are excluded. Existing active
customer-pack safeguards and FG numbering/tests remain. Unrelated HR, finance,
identity, platform and catalog refactors on clone_main are not released.
No production stock/order/material model or role grant is created by this work.

Package origin/display needs no migration. ECO adds its seven ledger/approval
tables;0154 adds typed receipt snapshots and merges the ECO branch with the
already deployed0150 package branch. HR migration0151 is deliberately excluded.
Original ECO revision identities remain intact.

## Review and remaining gates

Independent package review confirmed the exact10 runtime files and preservation
of shipped guards. Independent rollback review identified that old runtime's
exact Alembic-head check would refuse restart after0154. A separate compatibility
rollback, derived from the exact active source, is required before migration.
It must cold-start on both verified predecessor and complete successor schemas
and protect new ECO evidence while the ECO UI is unavailable during rollback.
Do not stamp/downgrade/drop new ledger tables to make an old image start.

The review also found source QC could be promoted to passed through transfer.
This candidate now filters non-passed batches before source pagination and
refuses their direct dispatch. Four regressions cover pending/hold/failed/rejected
stock with source conservation and no transfer creation after refusal.

Proportional local checks:152 focused receipt/approval/sewing/package/query-growth
cases passed; Ruff and compileall passed. Full local backend, frontend gates,
exact immutable CI, PostgreSQL gates, compatible rollback, backups, candidate QA,
performance and cutover remain pending until their actual evidence is recorded.

Preflight disk usage was79.15% backend and78.58% frontend (both below80% staging
stop, above70% alert). Retention dry runs are recorded under ignored
outputs/deployment. No cleanup, migration, staging or traffic switch has occurred.

Status: PREPARING. Timed monitoring: waived, not run. User deployment authority
does not fabricate a separate operator acceptance record.

## Shared-assignment approval gate correction

Independent rollback review reproduced the analogous feature bypass on exact
`f1e41f03`: an ECO assignment on a shared SEW work order, with either no bundle
or a Milana bundle, committed positive Sewing output without any ECO approval.
Eight new regression cases were red before the correction, including missing
approval, shared-work block ownership and the complete issue handoff.

Implementation agent `/root/review_packages` used isolated worktree
`C:\ERP\.codex-work\eco-sewing-gate-release-fix-20261104` from `f1e41f03`.
The coordinator independently reviews and integrates this patch. Existing
assignment ownership/status and batch validation now run before the gate;
the canonical assigned factory and resolved batch are authoritative. ECO BSO
discovery, material order selection and issue also recognize valid ECO line
assignments. Cancelled/transferred assignments grant no new ECO ownership.
Shared block updates use the valid assigned work IDs and preserve separate
MIL/BST checks, including pending ECO work on the same shared work order.

No stored vocabulary, schema, permissions, approval/issue timing or stock
calculation changes. Approved allocation still permits handoff; issuing still
deducts physical stock exactly once. Existing SEW work-order authorization is
preserved by this bounded correction. The new factory projection returns the
canonical `SewingFactoryCode`; existing persisted assignment-status values and
the route's accepted action subset remain unchanged.

The affected local regression selection passed 122 cases; the final assignment
boundary file passed 11 cases; full-app Ruff and compilation passed.
PostgreSQL/immutable CI, candidate browser and release checks require their own
exact-source evidence. All reproduction rows
were isolated test data. This worker changed no production state or business
rows and did not push or deploy.

## Sewing factory aliases and direct-line follow-up

Independent review reproduced two remaining compatibility cases against
`cf23c065`: a historical `BESTTEX` bundle reached the new enum conversion and
raised `ValueError`, and an unsplit shared SEW work order assigned directly to
an ECO line could record output without approval. Eighteen new assertions failed
before this follow-up. The gate now uses the existing bundle alias map lazily,
returns canonical factory values before selecting the approval path, and refuses
unknown factories with HTTP400. SQL ownership, assigned work selection and
historical sewing evidence recognize the same supported alias spellings.

The persisted primary line is authoritative only without any active split
assignment. Its work-order batch remains the gate scope; a stale former primary
line cannot override active MIL/BST splits. Direct ECO work participates in order
selection, approval blocks and historical grandfathering. Tests include no
assignment, cancelled/transferred splits, real positive MIL/BST output, all
supported legacy factory families, refusal of unknown factories, batch isolation
and approved direct ECO allocation through output and exactly-once issue.

The independent package reviewer probed BESTTEX, unknown values, direct ECO
refusal with zero output, direct MIL positive output, history/batch predicates
and stale-primary suppression and found no remaining actionable blocker.
The affected local selection passed 219 distinct cases (96 ECO/transfer/bundle
cases and 123 sewing/receiving/quantity/query-growth cases); the final boundary
file passed 38 cases after adding real legacy positive-output assertions.
Full-app Ruff, compilation and diff checks passed. Real PostgreSQL, immutable
CI and deployment verification remain coordinator gates.
This follow-up added no schema, permissions or production data changes.
