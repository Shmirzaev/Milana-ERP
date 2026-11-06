# Ismail operation checkpoint — 26 October 2026

The full six-area refactor and system-wide enum/type adoption remain incomplete.
Engineer: Ismail. Technical human reviewer: Mirshoir. Business acceptance: Shavkat.
MiniMax M3.1-Flash authored application code; Codex integrated and independently checked it.
No application merge to clone_main, deployment or human acceptance is recorded.

## Purchasing creation: AI verified, awaiting human

**PUR-01 at `1a71f16b6558ebe8b929d3fa992e1954c55bfc3f`: AI_VERIFIED_AWAITING_HUMAN.**
This covers direct/from-Sales request creation and its actual typed consumers.
Approval, rejection, conversion and receiving are separate, unfinished operations.

- Canonical backend input/output/internal command and actual frontend status types;
  schema-owned request/line/audit/notification writes, same supplied Session.
- 51 integrated checks and 21 independent real PostgreSQL checks passed, zero skips;
  both endpoints, authorization, real SQL-fault rollback/retry and concurrent creation.
- Full frontend TypeScript, focused ESLint and existing UI checks passed; a negative
  enum/subset challenge was correctly refused. Backend validates the wire enum;
  TypeScript generics are not runtime validation.
- Actual browser: required/missing-photo refusals, synthetic photo, one PR-0003
  creation and reload. Requester can open the form but has no approval controls;
  view-only user has neither creation nor approval controls.
- PR-0004 was created once through the existing from-Sales API, then inspected and
  reloaded in Purchasing: SO-0003, thread 0.20 roll and bags 10.00 pcs, pending status,
  no supplier/photo. No frontend from-Sales button exists or is claimed clicked.
- Independent persisted readback, decoded photo, all 33 audit hashes and exact
  notification passed. Eight adjacent tables stayed unchanged. After role checks,
  twelve reads at at most three concurrent requests left all twelve observed
  business tables unchanged (local p50 42.6ms, maximum 129.7ms).
- The primary assistant personally viewed the images; the independent reviewer
  reconciled source, technical, PostgreSQL, browser and readback evidence.
  These synthetic checks do not establish production capacity or acceptance.

## Remaining candidate checkpoints

| Operation | Evidence on its frozen draft | Still required |
| --- | --- | --- |
| CAT-01 paid-process creation | 42 focused +15 PostgreSQL pass | Canonical scope query and precise used return contracts; actual browser/human gates |
| FIN-01 invoice payment | 40 focused +22 PostgreSQL +120 downstream pass | Actual frontend enum consumer, combined operation and browser/human gates |
| INV-01 stock receipt | 69 focused +21 PostgreSQL pass | Frontend QC types with unchanged create/edit subsets/defaults; combined writer and browser/human gates |
| PLN-01 branded planning order | 65 focused pass | Derived cutting-progress enum through both DTOs/map/helper; truthful used return types; alternate Production writer remains pending |
| SAL-01 sales creation | 103 focused +10 PostgreSQL pass | Mirshoir-owned typed Fulfillment reservation boundary and schema-owned stock/metadata writers |

Local `075110fa16dec84f05d7e777ffac5787d94adb86` combines 23 reviewed Finance/Catalog
paths with the shared writers. Its selected run passed 180 checks; all eight
required PostgreSQL skips were then recovered as eight passes on an owned database,
which was dropped. Independent combined operation reruns also passed: Finance22
and Catalog15 real PostgreSQL checks, zero skips, both owned databases dropped.
Source hashes and focused lint/diff checks pass. This is draft evidence; the open
contract/frontend and browser/human gates above remain.

The [whole-ERP ledger](../REFACTOR_COVERAGE.md) retains all 97 tables/1,303 fields,
their owners and pending field/consumer/writer acceptance. Passing one operation
does not close its domain. Additional operations remain queued there.

## Ismail's additional local check

Use the isolated candidate, currently `http://127.0.0.1:58624/purchasing`, with the
agreed synthetic QA accounts. Confirm its source revision before recording approval.

1. Reload PR-0003: checker photo, TexFab Mills, pending approval, existing 0kg behavior.
2. Inspect PR-0004 linked to SO-0003: 0.20 roll thread and 10pcs bags; no supplier/photo.
3. Use the requester: open/cancel New request; no approval controls should appear.
4. Use the view-only account: requests remain visible; no create/approval controls.
5. Record pass/failure, source revision and reviewer. Leave existing requests
   unapproved; lifecycle actions need their own operation checks.

Human technical/visual and business acceptance are unrecorded. This checkpoint
does not authorize production cutover or retirement of the previous implementation.
