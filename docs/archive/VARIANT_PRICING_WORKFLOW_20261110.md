# Variant pricing workflow — 10 November 2026

User scope: automatically request missing variant prices after a Cutting Passport;
Purchasing/Abbosxon and Accessories submit independently; Finance explicitly
confirms selling price; provide pending/current/history reports and complete Excel.
Existing prices are reused. User explicitly requires unchanged order workflow and
authorized clone_main as base after the root AGENTS.md baseline conflict.

Base: 8ae2429cbd39c5f33ba17aab75d36949180e0c19. Both production hosts were verified
on 20261110_070607, app 843adaf3bda1b1f2d234e68b6763bbc649d3b72a, manifest
7bf0a59c139cf8a46fc6af7a3a0c5457795ba7b1de7fe57e70c76b31481fac32.
Production schema: 0155_eco_gate_merge. No deployment authorized.

Accountable domains: Planning/Finance/Catalog Ismail, reviewer Mirshoir;
passport integration Production Mirshoir, reviewer Ismail. Implementation agent
/root; independent technical review /root/pricing_review. Human review is not
claimed. Owned paths: pricing route/service/DTO/schema/enums, narrow passport
integration, department pricing pages/hook/report/locales, scoped tests/migration
and this record/context. No Sales, manufacturing, stock or shipment policy changes.

Contract: one active request per exact variant; department drafts do not submit;
only both submissions plus complete passport evidence allow Finance approval;
approval atomically freezes evidence and attaches price, and never rewrites saved
order lines. Same-model locks serialize concurrent creation/approval/evidence edits.
Legacy requests/prices remain evidence, never fabricated approvals. Existing
duplicates are not deleted or silently merged by migration. No production backfill.

Value/type inventory: existing three derived stage values retained; new lifecycle,
department and queue vocabulary uses canonical Planning enums in DTO/service/UI.
Factory/catalogue vocabulary reuses Identity/Catalog types; names, notes and model
references remain configurable/free text. ORM writes use schema-owned helpers.

Implementation: automatic passport-save participant, independent department drafts
and submission, explicit Finance approval/correction/cancellation/repricing,
factory/catalogue-scoped pending and approval queues, current-price register and
immutable history. Excel exports the entire filtered result, with Variant Prices,
Cost Breakdown and Approval History sheets. Searches cover model/variant/Kroy;
register filters are all/pending/approval/priced. Date-range filters are not added.
Critical UI actions support English, Russian and Uzbek.

The managed request projection uses explicit material rates and kg/metre
consumption, sewing, required printing, accessories or an explicit no-accessories
reason, and fixed USD 0.10 packaging per piece. Both cost submissions are required
before the net total is ready for approval. USD prices are net; UZS net cost is
derived from the exchange rate. Client-supplied UZS totals are not authoritative.
Saving Finance drafts never publishes a variant price. Existing imported prices
retain their source. Repricing requires a reason and retains the current price
until a replacement is explicitly approved. Source changes invalidate submissions;
stale revisions and externally changed price baselines refuse approval. Source
deletion/moves detach historical records without reviving cancelled requests.

Migration 0156 is additive: existing rows become read-only legacy history, without
merging/deleting duplicates or inventing approvals. The new approval permission is
added to the existing Finance role; custom roles need an explicit grant. Finance
viewing alone cannot approve. Existing explicit deny rules remain authoritative.
The reconciliation script defaults to read-only preview, requires an existing
Finance approver/factory/catalogue, and applies missing requests only with --apply.
Neither migration nor production reconciliation has run.

Verification evidence (10 November, dedicated local candidate):

- SQLite: final focused batch 92 passed; complementary pricing/import and adjacent
  manufacturing/Sales/packaging/shipment batch 188 passed. The final manual-draft
  seam was rechecked in the focused batch. Protected fact comparisons include
  saved Sales unit prices/totals, production orders/items, work orders/batches,
  stock/movements/reservations, bundles, Printing, Sewing, Packaging, finished goods
  and shipments. A real passport-to-Cutting execution still hands work downstream.
- PostgreSQL 16: 25 passed, zero skips, across the six existing pricing operation
  modules and the new workflow module, on disposable approved-instance fixtures
  migrated from empty through 0156. Existing 21 required case identities remain;
  assertions now require deduplication and explicit submission/approval. Tests
  observe finalized hashed audits, staged-write failures, real deferred commit
  failures, rollback/retry, actual pg_blocking_pids waits and stale-write refusal.
- Bounded stress: eight simultaneous signed creates produce one active request,
  one creation audit and one notice per team; two simultaneous contributions cause
  one stale conflict then a successful retry and one Finance notice; competing
  approvals attach one price/audit. No unbounded/load-at-production test was run.
- CI required PostgreSQL gate includes all four new workflow cases; offline gate
  validator 53 passed, including missing/replacement/duplicate/skipped/failure/error
  challenges for each added case. The entire 643-case PG gate was not run locally.
- Backend Ruff, compileall and a single Alembic head pass. Frontend lint passes
  with 14 inherited warnings, strict TypeScript passes, and npm run build passes
  its existing contract checks and optimized 103-page production compilation.
- Connected Edge on local loopback UI/backend and synthetic SQLite records:
  Purchasing save remains Pending; Submit removes it and Completed retains it
  read-only. Accessories independently saves/submits. Finance sees net USD 4.70,
  proposes USD 6 at 12,500 UZS/USD, and saving leaves the variant unpriced. Explicit
  confirmation publishes exactly USD 6 with immutable cost/approver evidence.
  Another imported variant stays USD 9. Full reload/history and database readback
  agree; Excel downloaded through the real screen contains all three sheets and
  numeric amounts. API tests separately export 65 rows past the 50-row page and
  neutralize formula-like names. Pricing-screen console errors: none observed.
  English, Russian tablet (820x1180) and Uzbek phone (390x844) inspected; table
  scrolling remains available and viewport restored. Scanner/labels/printing UI
  not affected. Local screenshots/workbook remain in ignored .pricing-qa/.
- Full native backend collection is BLOCKED by inherited create-user extraction
  fixture parametrization and missing local zxingcpp. Those files are unchanged;
  this is not a full-suite pass. No production business records were created.

Status: AI_VERIFIED_AWAITING_HUMAN for this scoped candidate. Independent reviewer
/root/pricing_review approved the runtime, tests and required-gate changes with no
remaining blocker and independently ran all 53 gate validator tests. Reviewed
working-source aggregate (49 code/test/gate files, sorted path + NUL + raw bytes +
NUL) SHA-256: b4a061750090d0246cd3a4ecebaae4291d648bfb4b11111d4fcaa7b233f079de.
Human engineering/operator acceptance and QA-master pre-deployment review remain
open. Broader full-suite collection remains BLOCKED as recorded above.

The final manual Cutting draft was exercised again through the real editor after
removing the legacy helper: 0.8 kg consumption persisted, both submissions remain
unset, no price was attached, one draft audit was written and no premature Finance
notification appeared. Only isolated synthetic data was written throughout QA.

Worktree: C:/ERP/.codex-work/variant-pricing-workflow-20261110.
Branch: codex/variant-pricing-workflow-20261110, based on verified
origin/clone_main 8ae2429cbd39c5f33ba17aab75d36949180e0c19; final fetch found no
upstream movement. Commit identity is available from this branch's task commit;
no merge or deployment is included in this handoff.

Human checklist: create a passport for a missing-price variant; submit each team
separately and verify the queue handoff; check full net cost and save/confirm
separation; return a cost for correction; verify imported/reused price and exact
variant; download a filtered report; continue the same order through Cutting and
its next department without pricing blocking stage execution.

Release handling: not merged or deployed. Active blue 20261110_070607 and retained
green 20261109_163130 remain untouched. Before any deployment: reconcile current
clone_main/live release again, complete QA-master review, back up PostgreSQL, build
the exact reviewed commit and follow DEPLOYMENT.md. A downgrade deliberately
refuses to destroy approval history. An old application image is not an approved
rollback for new managed requests: use a reviewed forward-compatible recovery
image or restore the matching backup/data state. No destructive rollback tested.
