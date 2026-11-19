# Variant pricing production release, 11 November 2026

Application deployed; price import and historical queue backfill are complete.
Final functional/public/health closing results are recorded below; the post-import
performance comparison remains incomplete because of audited live stock activity.

Active on both hosts: blue 20261110_135430, runtime commit
cfe03885e03e4310e9b7c86ec9649ff350565d65, schema 0156_variant_price_workflow.
Source manifest1abc90b9e4b87f3e16ef0e255fe1829d15e9b510d6f61f1b2c030baf33fa89a3.
Retained compatible green recovery 20261110_135420, commit
6f72351eda41ba47857643d5c046e2a0bd319088, source manifest
77bf4f4a6918f4282142011f45cfeb719869418faf4279270e3bff6a1eda4aa1.
Exact immutable image references are recorded in the production release manifest;
no source or image was edited on a serving VM. Runtime commit was fast-forwarded
to owner-selected clone_main; origin/main was untouched.

Full immutable CI final42828846448 passed 6710 backend tests,1585 skips and 36
subtests; recovery42828839622 passed 6678 tests,1579 skips and 36 subtests, plus
both candidates' PostgreSQL, frontend, strict TypeScript/build and security gates.
Final requiredPG42828851638 passed 645 required,17 Purchasing and 84 runner-contract
cases without failures/errors/skips. Earlier failed runs remain historical evidence.
Independent source/artifact review and actual recovery-image strict cold-start,
worker replacement/restart, schema compatibility and protected-ledger proof passed.
AI_VERIFIED_AWAITING_HUMAN does not represent operator or QA-master acceptance.

Pre-schema backup: milana_erp_pre_variant_pricing_20261111_035608.dump,
119765663 bytes,1,395 restore objects, SHA256
f64ca9aaac071ded07dd0a3163d645c7c2588f0bd5b9c1074ff7788ceef877c3.
Pre-price backup: milana_erp_pre_variant_pricing_20261111_042430.dump,
119968723 bytes,1,400 restore objects, SHA256
2efcc610c1d2706c580f718a099837985ae2709c74696fa33aaecda390f73824.
Both are private 0600 verified custom PostgreSQL dumps under shared/backups.
Migration ran once from the exact recovery image, then strict 0156 startups passed.

The first backend recovery activation switched routing but its immediate stable
release assertion failed before source-pointer completion. Failed evidence was
retained. Fresh identity/health/source checks justified one separately reviewed
pointer-only completion; activation/routing was not replayed. Final backend
activation used a reviewed bounded 20-second served-identity readiness convergence
before unchanged strict postconditions. Both final roles activated once and passed.

One fresh still-old-blue business epoch was independently adopted after externally
audited new-model and stock activity; five original protected order/ProcessQR
projections stayed identical. Original evidence remains retained. Recovery and
final paired gates each passed 550 complete GETs. Final public-before-import gate
returned 280 HTTP200 with all full facts identical and all medians/payload sizes
within limits. Two p95 limits genuinely failed: Sales 139.743→243.381ms(+74.16%)
and Cutting passports 148.100→184.632ms(+24.67%). Internal paired p95 improved;
read-only diagnostics showed no current CPU/memory/DB/lock/index bottleneck. Cause
is unproven, not attributed to network. Owner explicitly answered
"Accept these two exceptions and finish" after the exact measurements and
material-write consequence were presented. No automatic retiming or rebaseline.

Owner explicitly requested deployment without 30-minute monitoring. Only the timed
1,800-second observation is waived; no observer or substitute monitor was run and
no observation-complete claim is made. Final public QA and closing remain required.

The original 768 MiB read-only import preview was OOM-killed 137 before any write:
preview code has no write/commit and the process death closes its read transaction.
Failed named container/outcome remain retained. Independently reviewed recovery
required exact failed CID/ownership/image/command, absent canonical preview report,
MemAvailable≥6 GiB and 3 GiB RAM+swap cap. One explicit recovery succeeded with
6416 mapped targets,5897 unchanged and 519 updates; original failures remain intact.

Actual staged Admin browser verified both submission screens, Finance pending,
approval, history and complete 6296-row Excel export beyond its 50-row page.
Sales SO-0001 retained 450 units and saved unit/total price 0. ProcessQR BJ5039-V6795
retained 20 operations totaling 5,760 UZS, zero labels issued; no business records
were fabricated. Public signed-in Admin confirmed the new department screens.
The screenshot's SJ4013/V-6242 (model 8159) is a reviewed source-row 454 target:
F 5.00+0.30 gives USD 5.30. The persisted import and public Finance screen verify that exact variant.

Price import committed once at 04:26:33.844809 UTC. All 6416 mapped model records
passed independent selected-column readback:519 new USD/catalog prices,5897 exact
prior price/currency/source/request/timestamp baselines preserved,519 per-model
audits and one batch audit. No active requests needed cancellation. Model 8159 /
SJ4013-V-6242 is now USD 5.30, also verified in the actual public Finance screen;
its old request remains read-only historical evidence, outside submission queues.
Saved Sales table/item fingerprints are identical across the import. Concurrent
staff user 3 actions at 04:26:02–08 split PO-0862 (ID 906), created CuttingRecord 1221 and completed
WorkOrder 3622; their audits precede import timestamp and explain observed Cutting
business-ledger activity. We do not claim the live factory database was frozen.

Actual post-import historical preview contained 166 unique models and passports,
MIL 153 / ECO 13 / BST 0, no factory overlap and no 519 import-target intersection.
The owner explicitly said "Queue existing unpriced variants too". A separately
reviewed helper acquired sorted passport NOWAIT locks before sorted Model NOWAIT
locks, rechecked the exact list, preserved complete targeted-model and all existing
request data, and called the deployed sync service in one transaction. One apply
created 166 collecting requests with no costs, rates, submissions or approvals.
Persisted 166-row readback passed. All 36 protected business-table fingerprints
were identical immediately before/after this backfill. Normal authorized audit and
notification rows are the only related side effects. No staff permissions changed.

The real staff-created passport 894 already automatically created managed request 2
for PG10518-V-6847 at 04:24:03 by user 3, before either bulk data action. That request
and legacy request 1 were preserved by the backfill. Persisted readback confirms
168 requests,167 active (154 MIL including that automatic request and 13 ECO).

A post-import public check stopped before any HTTP/timing sample because staff user 2
had created models 8978 and 8979 at 04:19:24 and 04:24:16, changing the helper's latest-
model selector. Its failed zero-sample evidence is retained. A reviewed fixed-input
adapter resolves the exact prior BJ5024-V-6867 code in the standard catalogue; byte
comparison proves only that selector query changes. It retains all other selectors,
full JSON identity, original limits and samples; no facts or baseline are replaced.
Final signed public checks and strict closing results are recorded below.
Staff identities for Abbosxon, Accessories and Finance have not been inferred or
granted permissions. Admin wildcard already provides both screens. New pricing
requests notify existing authorized departmental accounts through the normal
application workflow; no costs or selling prices are invented for unpriced work.

Worktree C:/ERP/.codex-work/variant-pricing-workflow-20261110;
branch codex/variant-pricing-workflow-20261110. The runtime commit is immutable;
subsequent release-record commits contain documentation/baseline pointers only.

## Closing evidence

The fixed-input post-import benchmark stopped after 85 samples at inventory_batches
full-fact equality, not a latency-limit result. All 50 IDs, order, counts and envelope
were unchanged; only batch 2084 quantity/available quantity changed 535.4→345.4.
StockMovement 4439 records exactly 190 kg consumed by staff user 3 for CuttingRecord 1220
at 04:24:22.518814 UTC, before import. Item 141's aggregate changed 17742.9→17552.9.
Failed partial samples remain NOT COMPLETE. No further benchmark, replacement
baseline, ignored field or broader performance waiver was used. The last complete
public benchmark is the 280-sample pre-import gate with its two explicit owner p95
exceptions. A fresh complete post-import performance closing remains an explicit
limitation; no claim that all performance gates passed is made.

Independent review approved a separate one-shot functional closing: all 10 original
paths returned 30 HTTP200 responses across public/finalblue/recoverygreen. Every
ordered full JSON body matched all three origins. Eight noninventory bodies were
fully equal to the original approved frozen facts; the two inventory bodies matched
the complete original payload plus exactly the audited 190 kg quantities above.
No additional change or result-count drift was accepted. This proves functional
parity/current-data correctness and does not constitute a new timing benchmark.

Actual public Admin verified enabled Purchasing rate/sewing/printing draft controls
and Accessories entry controls, separate Submit costs buttons, and Finance pending
team states with Confirm disabled before submissions. No draft/cost/approval was
saved during public QA. Existing user login was used normally; no browser token
was extracted or injected. Clean public-tab console errors: zero. Actual public
Excel download contains 6,587 Variant Prices,818 Cost Breakdown and 155 Approval
History rows, exceeding the visible 50-row page. Its SJ4013/V-6242 row is numeric 5.30,
USD/catalog; SHA256d582eb4cea6747529195698fbc5de377cef38680c785696a325c41a2581a0f49.
Eco Usluga historical preview finds zero requests or source exceptions to create.

Final database readback:168 requests total,154 MIL collecting,13 ECO collecting,
one preserved legacy request; all 166 bulk-created requests have no costs,
submissions or approval. Ordinary staff-driven PO-0862 progressed Cutting completed
(150 actual) to Sewing in_progress while this release was serving; no agent created
or modified that order. Saved Sales prices remain unchanged.

Fresh formal closing on both hosts passed exact current/rollback source manifests,
immutable image/revision/container checks, strict 0156 two-worker startup, seed=false,
loopback-only slot ports, stable routers, database/index checks, current-start logs,
all four supported health checks and served release identity. Backend disk 77.02%,
frontend 77.67%: above 70% alert, below 80% stop; no blanket cleanup occurred. Retained
recovery's explicit pricing 503 guard remains healthy and is not a pricing-capable
rollback; imported prices are business data and are not undone by code rollback.

Final helper review preserves the original frozen plan and adds separately approved
resource recovery, exact 166-row backfill, fixed test input and audited-data functional
closing. Failed readiness, OOM, dynamic-selector and partial benchmark evidence is
retained. No 1,800-second observer or substitute monitoring window was run. Staff role
mapping and human engineering/operator/QA-master acceptance remain open.
