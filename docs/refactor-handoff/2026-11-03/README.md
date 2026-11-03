# DRAFT HANDOFF — DEVELOPMENT AND VERIFICATION INCOMPLETE

**Do not merge or deploy this PR.** The owner explicitly requested one preservation/handoff PR containing the remaining local refactor work so a successor can continue. Publication is not acceptance.

Base: `clone_main` at `75cf9c53930bdf3508e0d8a38f755a0aa6737a0b`, including merged PR370 (Catalog Size/Color CREATE and Mini Post) and PR371 (Identity). Those changes are preserved, not recreated. This draft does not modify Identity, People, Support or Work Management implementations.

Owner: Ismail, including the Mirshoir Production/Packaging/Fulfillment takeover. One integrator owns this draft. Models: Sol6.1 medium leader and Terra6.1 medium delegated roles only.

## Included work and precise stop conditions

| Operation | Included | Remaining work / blockers |
|---|---|---|
| Item UPDATE | Typed update command, stock service to same-session schema persistence; three source regression/PG tests | Category/unit vocabulary decisions and inventory adjacency remain unresolved. Revalidate real PG/helper compatibility, actual desktop/mobile UI, persistence/audit, integrity/recovery and independent complete-operation review on this combined source. |
| ModelSize DELETE | Canonical scope through both routes/service, schema-owned delete, four test modules | Native preview/cancel/printing adjacency, linked/orphan semantics and deletion authority remain unresolved. Do not invent deletion guards or policy. Mixed old candidates were not copied wholesale. |
| Purchase APPROVE | Verification/test module and its required-case registration only | The business service extraction already existed. This is not a new app extraction. Complete classification/type, exact-source real PG, UI/recipient/audit and integrity gates; old scoped results are not current acceptance. |
| Production whole-order factory routing Option A | Same-session schema-owned factory-setting persistence and two dedicated source tests | Prior candidate frozen BLOCKED: stress not completed, observer identity/lag qualification unresolved, broader grouped service/route transaction/internal typing OptionB unresolved. Historical scoped PG/visual observations do not clear these gates. |
| Sales CONFIRM | Partial typed backend/service and frontend planning/contracts, frontend contract checker; five draft characterization runners archived below | ORM enum adoption, complete caller/type coverage, combined regression, build, real PG, actual UI, bounded stress/integrity/recovery and independent review remain open. These are partial changes, not completion. |
| Catalog parent GET scope | Three canonical-scope caller/service hunks and two contract tests with immutable synthetic golden | Full output/status/legacy vocabulary decisions remain unresolved; exact combined PG/readback/permission/refusal/UI and integrity gates remain open. Historical leak challenge was TEST-INJECTED, not a proven baseline production leak. |

## Verification status

No historical PASS is promoted to a combined-source PASS. PR370 acceptance applies only to its covered CREATE/MiniPost source, not these remaining operations. The successful prior29 PostgreSQL checks do not certify this draft's DELETE/Item/Production/Sales changes. Fresh draft checks and exact results are recorded in `CHECKS.md`. Missing required checks are BLOCKED. No human/factory acceptance or production deployment is claimed.

The existing shared PG helper from PR370 is deliberately preserved. Added Item/DELETE/Purchase required-case registrations retain exact test identities; the global required registry is219. These older candidate fixtures still require compatibility review against that helper: do not reconstruct target owners, replay unknown transactions or silently loosen the helper to make tests green. Required tests may fail or block; this is why the PR is draft.

Experimental Sales runners and the Production PostgreSQL draft are in `draft-tests/`, outside normal backend collection. They are preserved source, NOT passing regression coverage. Sales files include sibling-import and DRAFT harness assumptions requiring a reviewed real runner/path. Do not move them into CI without studying them. The PG draft has unresolved lifecycle assumptions.

## Successor execution checklist

1. Read repository AGENTS.md, engineering workflow, verification and milana-refactor plus milana-dev-safety skills. Check the shared message log and agree one writer before touching an existing session's paths. Re-fetch current clone_main and reconcile every overlapping PR; keep370/371 and future fixes. Do not force push.
2. Work one operation at a time. Study routes, services, every caller/DTO/enum/schema field, permissions, downstream handoffs and transaction/audit/notification/idempotency effects. Retain unresolved business/type decisions explicitly. Prefer approved recorded decisions, not repeated routine confirmation questions.
3. Lock baseline behavior, finish the exact application/type work, then run meaningful automated checks in rootless Docker. Reconcile fixture ownership with canonical helper before real disposable PostgreSQL. Preserve locks and same suppliedSession/one outer service transaction. No genericrepository or recreated services directory.
4. Use two Terra QA lanes with separate privateqa_visual contexts and distinct candidate ports. Test actual desktop and exact390px mobile on owned synthetic fixtures, inspect screenshots, reopen records and independently read persisted rows/audit/recipient state. Baseline login smoke and DOM-only are not visual acceptance. Save private evidence under the authorized test-artifact directory, never commit credentials or raw private logs.
5. Complete bounded concurrency/integrity/recovery and independent AI review on the exact combined candidate. Record all PASS/FAIL/BLOCKED gaps. Personal Ismail visual review was waived for the conditional landing workflow, not invented as completed; factory full visual review is a separate unperformed predeployment gate.
6. Only when applicable technical, actual visual, independent review and requiredCI gates pass, serialize normal push/merge under the owner's standing authorization. No further routine proceed question. This draft itself is NOT permission to merge an unfinished change. No deployment.

## Local evidence locator — do not publish private artifacts

Original development workspace: `/home/ismoil/workspaces/remote_work/refactor-omx-20261101`. Operation records under `.codex-work/refactor-omx-20261101/`: `item-update/operation-packet.md`, `purchase-approve/packet.md`, `production-factory/frozen-blocked-status-20261101.json`, `sales-confirm/combined-progress-receipt.json`, and `catalog-parent-get-scope-operation-packet-v1-20261102.md`. Those local paths are locators only, not current acceptance or resource authority. Full source provenance for this draft is in `SOURCE_PROVENANCE.json`.

Shared handoff messages live locally at `.codex-work/refactor-omx-20261101/cross-session/visual-qa-messages.jsonl`. Append only, preserve unknown/HOLD owners, and never mutate another session's hook-owned .omx state. A message file cannot wake an inactive agent.

## Explicit exclusions

No production data/credentials, databases, environment files, auth/session caches, screenshot traces, raw private logs, runtime fixture credentials, old unknown/HOLD control state, node_modules or workflow-state directories are included. Local rescue bundles and historical evidence stay preserved locally. Old root documentation/coverage copies are not blindly overlaid on current371 documents; this self-contained handoff supersedes stale completion claims for these slices. No full-system completion is claimed.
