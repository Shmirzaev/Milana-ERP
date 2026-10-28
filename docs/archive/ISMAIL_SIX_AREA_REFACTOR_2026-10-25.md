# Ismail six-area refactor candidate — 25 October 2026

Owner: **Ismail**. Technical reviewer: **Mirshoir** (requested on
[draft PR #308](https://github.com/Shmirzaev/Milana-ERP/pull/308)). Business acceptance:
**Shavkat** with operators. Neither human review nor production acceptance is claimed.

## Candidate and scope

Application commit: `995f81cd9062ec52b09670438629622b026b2007`, on temporary candidate
branch `codex/ismail-finance-pilot-20261025`. The branch name predates the expanded
six-area scope. Integration directory in the Codex task workspace:
`work/ismail-finance-integration-20261025`. No merge, database migration or deployment.

MiniMax M3.1-Flash implemented Catalog, Purchasing, Sales, Inventory, Planning and
Finance through two coordinators and six scoped workers. Codex integrated their
separate checkouts, reviewed the combined result and performed independent checks.

Business operations now live in `backend/app/models/<group>/*_service.py`;
entity-named Pydantic contracts live in `backend/app/libs/dto/<group>/`.
SQLAlchemy definitions remain under `schemas/`. Existing shared helpers are reused
at `models/` root. See [the actual module map](../REFACTOR_MAP.md#service-destinations)
and each group's README for its interface, callers and transaction responsibilities.
This extraction preserves existing rules; it is not a complete RBAC redesign,
enum conversion, cross-domain isolation audit or multitenancy implementation.

## Automated evidence

All evidence filenames below are relative to the parent Codex workspace's
`outputs/` directory, outside the application repository. No test credentials or
browser sessions are committed here.

| Check | Result and evidence |
| --- | --- |
| Combined Finance/Purchasing/Sales | 397 passed, zero skips; `commercial-candidate-tests.xml` |
| Planning, Finance paging and adjacent callers | 206 passed, zero skips; `planning-finance-candidate-tests.xml` |
| Final Inventory/Catalog and affected workflows | 694 passed, zero assertion failures, zero skips; 18 temporary-directory setup errors in `final-inventory-candidate-tests.xml` |
| Recovery of exactly those 18 setup-blocked cases | 18 passed, zero skips under normal Windows user permissions; `catalog-permission-recovery-tests.xml` |
| Separate real PostgreSQL stock-adjustment races | 2 passed; `stock-adjustment-candidate-tests.xml` |
| Final Sales photo fixture | 1 passed; `sales-photo-fixture-test.xml`; fixture-only correction after application commit |
| Public contracts | Full canonical OpenAPI and PostgreSQL DDL identical: 577 registered routes, 475 documented paths, 97 mapped tables; `compare_finance_contracts.py` |
| Static checks | Ruff, Python 3.11 compilation and Git whitespace checks passed |

The final 712 affected cases passed across the 694-case run and 18-case recovery,
not in a single uninterrupted run. Earlier suites overlap; do not add their counts
to claim a larger unique total. Required PostgreSQL cases were actually run locally.
The restricted Windows token could not access pytest's temporary-directory ACLs;
the recovery changed process permissions, not application behavior or assertions.

Separate Catalog and Sales fixtures used random hexadecimal suffixes after
`variant-`; an all-numeric suffix could look like a conflicting source variant.
MiniMax changed the fixture names to include `variant-photo-`, preserving the
runtime image-isolation guard and assertions. These are test corrections, not
relaxations of factory/image policy. The Sales fixture received an independent
one-case rerun after integration.

CI on application commit `995f81c`: backend and frontend checks passed in both the
[push run](https://github.com/Shmirzaev/Milana-ERP/actions/runs/40195039680) and
[PR run](https://github.com/Shmirzaev/Milana-ERP/actions/runs/40195044119), including
their PostgreSQL stages. Release jobs were skipped. Check the PR for later
documentation/test-fixture commit checks; this record does not certify pending
jobs as passed.

## Actual UI, readback and bounded stress

Final candidate UI: `http://localhost:58624`, API `http://127.0.0.1:8102`.
Disposable PostgreSQL database: `commercial_qa_ead3d51f2ee0` on local port 51716.
The earlier personal test app at port 58623 was retained separately.
The final server was started before the application commit, then its complete
application file hashes were proved equivalent to `995f81c`; later changes are
documentation and a test fixture only. Launch manifest: `commercial-runtime-source-hashes.json`.

- **Catalog:** created draft `QA-RF-0001`, updated its name, uploaded an actual file,
  added 0.5000 kg BOM usage with 5% waste and reopened the result. The stored WebP
  decoded successfully. Viewed `combined-catalog-image-upload.png` and
  `combined-catalog-bom-added.png`; database values matched.
- **Purchasing:** request photo → approval → order → partial 40/100 kg receipt →
  remaining 60 kg receipt. Deliberately lost the real response after its commit,
  then retried through the UI's saved-receipt action. Exactly two batches, five
  rolls and 100 kg persisted, with no duplicated receipt. Twelve same-key replays
  at concurrency 3 and sixty reads at concurrency 6 preserved the stored result.
  Evidence: `commercial-receipt-recovery-proof.json`, `commercial-receipt-load.json`
  and `commercial-receipt-retry-success.png`.
- **Sales/Finance:** created and confirmed `SO-0003`, 10 pieces at $20, issued one
  $200 invoice and checked history. Earlier payment flows settled $4,000 against
  sales from $4,025 received, preserving a $25 advance. Final candidate pages
  retained those totals after integration. Evidence: `commercial-sales-load-proof.json`,
  `finance-entrypoints-final-ledger-load.json`, `combined-final-sales.png` and
  `combined-final-finance.png`.
- **Planning/Inventory handoff:** created production for `SO-0003`, planned 10 pieces
  with a 14 kg estimate and verified the generated Cutting, Sewing, Packaging and
  Storage work orders. Reserved 15.12 kg from `QA-PUR-002`, released it, then
  reserved again. Final stock stayed 40 + 60 kg; the selected batch shows 15.12 kg
  reserved and 44.88 kg available. Thread and polybag shortages remain explicit;
  no downstream output was fabricated. Viewed `combined-inventory-stock.png`,
  `combined-inventory-reserved-again.png` and `combined-production-handoff.png`.
- **Final combined challenge:** 60 reads across eight Catalog/Planning/Inventory/
  Purchasing/Sales/Finance endpoints, at most six concurrent; all responses stable,
  p50 119.6 ms, p95 186.8 ms, health recovered/passed. Fingerprints of 15 business
  tables were unchanged. `combined-six-area-qa-proof.json` records exact checks.
  This small local workload proves stated integrity cases, not production capacity.

Existing UI findings remain open in [bugs/bugs.md](../../bugs/bugs.md): partial-payment
confirmation wording, revenue-chart refresh and the receiving quantity-column
label/order mismatch. No bug was moved to Finished and no production data was used.

## Ismail's local human check

Open `http://localhost:58624` using the disposable local account supplied separately.
Refresh each record; do not use production for these synthetic actions.

1. `/models/2?mode=edit`: `QA-RF-0001`, name `QA refactor sample verified`, one
   attached image and the 0.5000 kg / 5% waste BOM line.
2. `/inventory`: `QA-PUR-001` is 40 kg; `QA-PUR-002` is 60 kg, with 15.12 kg reserved
   and 44.88 kg available. The completed purchase has left `/purchasing/receiving`.
3. `/sales-orders/3`: `SO-0003`, ten pieces, $200, now Planning with Cutting waiting.
4. `/production-orders/1` and `/planning`: correct ten-piece plan, 14 kg estimate,
   one active 15.12 kg reservation, one released reservation and visible thread/
   packaging shortages. Confirm that these are the business outcomes Shavkat expects.
5. `/finance`: three invoices; `INV-2026-000003` is $200 unpaid. Applied receipts
   $4,000 and received receipts $4,025 agree with the saved ledger.

Record any disagreement with its screen, steps and expected outcome. Mirshoir
reviews transaction boundaries, permission parity and compatibility before merge;
Shavkat/operator signs off workflow behavior. Release work must re-fetch
`clone_main`, reconcile urgent fixes and follow DEPLOYMENT.md with fresh production
identities, backup and retained rollback. Historical tag
`production/20261024_093619` points to `1fce86b5`; it is not fresh runtime verification.
