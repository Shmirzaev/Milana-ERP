# November pricing request scope — 11 November 2026

Owner instruction: “this is the latest prices only keep the undpriced variants
created after nov 1 do not request for usluga variants”. Source: `11-11.xlsx`.
The earlier USD 0.30 addition, exact model-and-variant preference and globally
unique variant fallback remain authorized. Deployment is authorized; the owner
waived 30-minute monitoring. Earlier two measured performance exceptions are not
blanket exceptions for this release.

Additional owner corrections: “we don't need each fabric price just keep box for
fabric price and all the formula is there”; “no need for kro no now, you can
replace it with order no”. Purchasing now supplies one Fabric price USD for all
recorded fabric/binding consumption rows. Consumption evidence and the existing
net-cost formula remain unchanged. Explicit per-material API inputs and approved
historical breakdowns remain compatible. Cards display the linked order's public
number, falling back to the passport's manual order number or a dash; the Kroy
identity remains internal evidence for Cutting. Approval freezes the order label.

Base: clone_main c02f83ac03d22d98575ed23887e883925b3c3581. Verified production
before edits: blue 20261110_135430, application cfe03885e03e4310e9b7c86ec9649ff350565d65,
manifest 1abc90b9e4b87f3e16ef0e255fe1829d15e9b510d6f61f1b2c030baf33fa89a3,
schema 0156_variant_price_workflow. This candidate needs no schema migration.

Only standard, unpriced variants with Model.created_at from 1 November 2026,
00:00 Asia/Tashkent (31 October 19:00 UTC), qualify for active pricing. Request
creation dates do not qualify older variants. Automatic passport creation skips
excluded variants without blocking Cutting. Manual creation, repricing, cost
updates/submissions and Finance approval cannot bypass the rule. Pending views
and pending Excel reports use the same policy. All/history reports retain old
records and existing prices. The obsolete priced-variant repricing control is
removed. No Sales order prices, quantities, manufacturing or inventory rules change.

Excluded active requests are explicitly cancelled, never deleted. Submitted
costs, submission timestamps, source evidence and history survive cancellation
and passport unlinking. The administrative CLI defaults to read-only preview;
apply requires an exact reviewed request/model/revision list, locks Models before
requests and commits once. A stale list refuses the whole operation. It requires
an active global Finance approver, not merely a factory wildcard.

Workbook SHA256: d9086c9af59cbd1388bb7e9d65faa37b5fce12f3ac6f3c93366eac143c3bb1ee.
Reviewed manifest v3 canonical SHA256:
697865bce5c759d405c0edfb546749b2fe26056da751a073430c2fbcd378a162.
There are 9,670 positive source rows. Read-only comparison selected 6,435 standard
variants: 6,421 existing prices already agree and 14 missing prices total USD83.60.
No existing priced amount changes. Column F plus USD0.30 is applied exactly once;
blank F with a cached G value of USD0.30 is excluded. Exact structured pair wins
over punctuation-compatible code matches; variant-only uniqueness includes every
catalogue, including Usluga. Ambiguities are excluded.

Initial queue preview: retire 131 older requests, retain 36 recent unpriced
requests (33 Milana, 3 Eco Cotton standard), zero Usluga. All retirements have no
submitted costs. Eleven of the fourteen fills intersect the older requests:
retire the fresh reviewed exclusions FIRST, then import the fourteen prices.
Normal factory activity can change previews; recheck identities and revisions
immediately before writes. Back up production PostgreSQL before material changes.
Neither this document nor initial counts establish that production was changed.

Domain owners: Planning/Finance/Catalog Ismail, independent human reviewer
Mirshoir; Production Mirshoir, reviewer Ismail; Shavkat supplies operator business
acceptance. Implementation /root; independent AI review /root/pricing_review.
Human QA-master acceptance is not claimed by AI test results.

Local evidence: 56 focused SQLite workflow/import/scope cases; 10 real PostgreSQL
cases including whole-transaction commit-failure recovery and retirement racing
with Finance approval/import; 53 offline required-gate validator cases. Ruff,
compile, frontend ESLint, strict TypeScript and pricing workflow regression pass.
The required PostgreSQL inventory adds exactly four case identities (649 total).
Evidence is private under outputs/pricing-november-scope; no workbook, credentials
or production dumps are committed.

Additional verification after the two UI corrections: 48 legacy pricing,
purchasing bounds/transactions/status and PERF23 pagination/query checks pass.
The exact response contract adds order_no and asserts null for unlinked requests;
all prior fields and query budgets remain. Independent AI source review approves
the runtime. An actual connected browser exercised Purchasing save/reopen/submit,
Accessories save/submit, Finance draft and explicit confirmation on isolated
SQLite: USD5 shared rate over four consumption rows produces USD6.80 net cost;
USD8 remains unpublished in the draft and attaches only after confirmation.
Order QA-ORDER-20261111 is frozen in approval. Actual Excel download has all three
sheets, USD8 price and USD6.80 component sum. A separate localhost cookie host
isolates this fixture from the production preview session. Six isolated execution
helper tests pass 51 refusal/success/failure controls, including uncertain timeout,
foreign container, stale backup, changed reviewed target and no-replay behavior.
These are AI technical checks; human production acceptance is still unrecorded.

## Deployment and persisted results

Deployed 11 November 2026. Both roles use green release `20261111_052632`, source
`519c9fa36f3d90905f935caf08fe781417cf7e24`, manifest
`55d0edc9b7893df95987102cc6d9ccbe5b59a89f3c369eb5ea1f46a9868d4520`.
Backend activated 06:07:50 UTC, frontend 06:07:58 UTC. Full-app rollback remains
running in blue: `20261110_135430` / `cfe03885e03e4310e9b7c86ec9649ff350565d65`.
No schema migration; revision remains `0156_variant_price_workflow`.

The exact-source [official CI](https://github.com/Shmirzaev/Milana-ERP/actions/runs/42965784953)
passed 6,735 backend tests, 1,589 explicitly reported skips and 36 subtests.
Supplementary real-PG groups include P2 207, Sales 11, Forecast 20 and schema
185 passes / 17 reported skips; migration/concurrency/numbering checks also passed.
The separate [required PG run](https://github.com/Shmirzaev/Milana-ERP/actions/runs/42965788647)
passed all 649 required cases and its supplements/contracts. Frontend lint,
strict TypeScript, browser/Node checks and build, security and immutable image
publication passed. Superseded 04063 CI failed only the PERF23 exact-key test;
519c adds the intended order_no contract and passed. Superseded artifacts were
never staged. Runtime image digests:

- Backend: `sha256:bab9cb8d252325db94c1ea08eb417e1647dd5b160ac5f2473706565d8a81b1c9`.
- Frontend: `sha256:7186276fd4032ed00e566aaecd92232a7dbd63bb03e8b179f5750f40455ef4f0`.

All 2,485 archived source files were compared with the exact Git commit. Source
archive SHA256 is `83417ce5f674e4d5ada3c6052bb874b3e0c68845f7d01ef6092d6569e1d4984b`.
Both hosts prepared/staged through owned leases, full source/runtime/controller/
router CAS and the installed pinned blue/green controller. Default two backend
workers and disabled startup seed/schema synchronization were verified.

The pre-cutover and pre-write custom PostgreSQL dump, created 06:06:08 UTC,
contains 120,731,206 bytes and 1,400 verified restore-list objects, mode 0600,
SHA256 `bcb36e819afc08b292d50c5d209d6ea2d1d61623445487e97f3c14d5a245febc`.
Both writes checked the actual dump hash, mode and age below 15 minutes.

Fresh preview still selected exactly 131 older requests/revisions, all standard,
none submitted. The one retirement committed before the price import and passed
independent persisted readback: only active/state/reason/revision/updated_at changed;
all request costs, source data, submissions and history stayed intact. All 8,234
Model full-row fingerprints were identical across retirement. Normal staff activity
had created three more eligible requests since the initial 36 preview, so final
active requests total 39: 36 MIL and 3 ECO, all recent unpriced standard variants,
zero Usluga. No extra historical requests were generated.

The full v3 catalogue comparison remained the verification contract. Production
available memory was below the conservative 6 GiB threshold for loading all 6,435
Model JSON rows; the full import was not attempted. A separately reviewed exact
14-entry subset retained every original identity, source row, amount and expected
baseline. Subset canonical SHA256 is
`4a0cf86078f7237ce005987b5ba83de97923fa7f5b870d88a7b1ec0efa22e21a`.
The unchanged immutable import CLI ran with a 1 GiB memory/swap cap, 4 GiB minimum
available host memory, one CPU, read-only filesystem and owned no-replay tracking.
Its actual read-only 14/0/14 preview used 84,951,040 peak bytes, all cgroup memory
events zero, no OOM, and over 5 GiB available afterward. The amended actual renderer
passed six isolated tests / 51 failure, refusal, success and no-replay controls;
independent review approved the observed preview before the one apply.

At 06:11:34 UTC exactly 14 missing prices were committed, USD83.60 in total, with
catalogue/USD provenance and workbook/subset hashes in audits. There were no
additional request cancellations. Complete persisted verification proved all
6,435 full-comparison prices correct, all 6,421 existing Model full rows unchanged,
all 171 request rows unchanged by import, and only five price/provenance fields
plus automatic updated_at changed on those 14 Models. Exactly 146 expected audits exist: 131 request
cancellations, 14 Model imports and one import summary, all attributed to actor1.
All 36 protected tables, 119,419 rows, have identical complete-row fingerprints
before retirement, after retirement and after import. Orders, saved order prices,
production, packaging, stock, reservations, invoices and shipments were untouched.

## Performance, public QA and closing

Initial old-blue baseline evidence is preserved. A staff consume movement4440,
322 kg from batch2083 for CuttingRecord1225 at 05:28:18 UTC, changed four quantity
fields before any candidate was staged. Independent review approved one fresh
old-blue baseline with the same fixed selectors, full ordered facts and limits.
That 280-GET epoch passed; the 550-GET staged paired gate passed all limits.

The 280-GET public after gate preserved every complete fact, median and payload
limit but failed two p95 limits: model options 162.1302 to 202.9676 ms (+25.1880%),
Cutting passports 154.3287 to 647.9422 ms (+319.8455%), against +15%. The owner
explicitly accepted these two new-release exceptions and authorized finishing
the 131 retirements and 14 prices. Prior-release exceptions were not reused.
Cause remains unproven; failed samples and strict budgets are retained. There
was no replacement timing epoch or claim that all performance gates passed.
After both writes, all 30 final full-fact GET comparisons (ten paths across public,
active green and rollback blue) matched the same frozen baseline.

Actual signed Edge staging/public Admin checks verified Purchasing, Accessories,
Finance pending/approval/report, single fabric input and Order No. PO-0818. A live
MF9013/V-6421 report shows USD4.30/catalog and preserved cancelled-request history,
including original consumption and packaging amount. The actual complete Excel
download has 6,596 Variant Prices, 835 Cost Breakdown and 158 Approval History rows
in the selected MIL view. Its complete price projection contains all 6,435 matched
prices, including the 14 fills; all 121 MIL retirements appear cancelled in history.
Excel SHA256: `694fe15d47964ae715b26ebf7c3b4db8e4ad2ca8648d2208f055603b2d3c6e95`.
Browser logs contain one external ad-blocker extension error and zero ERP errors;
global console cleanliness is not claimed. No production costs or approvals were
entered for QA. Isolated full handoff evidence above remains separate.

Fresh post-write formal closing on both hosts passed all source hashes, immutable
images, pointers, routers, loopback ports, rollback health, two backend workers,
seed/schema flags, database revision/invalid-index checks, logs and all four health
checks. Backend disk 77.36%, frontend 77.84%: above 70% alert, below 80% stop;
no retention deletion occurred in this task. Database had 39/100 connections and
zero invalid indexes. The owner waived the 30-minute observation; no observer or
substitute monitor ran. Both original and post-write closing evidence is retained.

Independent AI final source/helper/data/conservation review approved the actual
results. Human QA-master/operator acceptance and staff account-to-team mapping
remain unrecorded; do not relabel AI verification as human acceptance.
Runtime was fast-forwarded to clone_main; later context/production-base metadata
does not change the deployed 519c application. Worktree:
`C:/ERP/.codex-work/pricing-november-scope-20261111`, branch
`codex/pricing-november-scope-20261111`. Legacy C:/ERP changes were preserved.

Human visual checklist: open Purchasing and Accessories as administrator; verify
only recent unpriced standard variants remain; verify old and Usluga requests
cannot be submitted; open Finance pending/approval and full Excel; verify history
retains cancelled rows and imported prices retain source; create an ordinary
Cutting Passport for an excluded variant and verify normal downstream handoff on
isolated QA data. Production business data must not be fabricated for this check.
