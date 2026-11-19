# Model variant creation refactor — 18 November 2026

Draft candidate based on b0a5473b2f96b60a9b56f34aec92e3023d49605e. Engineer owner: Ismail; reviewer: Mirshoir. Human review is not recorded.

Variant creation previously performed Model, size, color, BOM, image and collection-link writes in the business service. The service now calls schema-owned persistence operations with its existing Session, while retaining source/family locks, numbering, permission context, validation, material selection, approval inheritance, audit and the single outer commit. Existing schema-owned color/image helpers are reused without adding a flush. clone_model is unchanged. No migration or intentional API/value change.

CatalogScope is canonical in the internal creation command. Model status uses the existing draft/approved creation subset; table-wide status, copied legacy BOM roles, image discriminators and actual stored-value/consumer audits remain unresolved. This slice does not complete Catalog or system-wide enum adoption.

## Verification

On isolated VM107 rootless Docker, the unchanged baseline and candidate each passed 26 focused existing SQLite-fixture tests; the candidate's standalone rollback/copy test passed once. Zero failures/skips in those completed reports. Independent source review found no concrete behavior regression. Diff and syntax checks passed.

The PostgreSQL tests cover late queued-audit rollback/retry, child and image copying, numbering and deterministic two-worker contention. PostgreSQL execution did not complete: the identity-pinned database lifecycle guard entered HOLD during DROP DATABASE teardown, and no completed PostgreSQL JUnit report exists. Passing progress markers are not accepted as passes. Exact retained resources and diagnostic traceback remain in the local task evidence; no uncertain DROP was replayed or cleaned up. Combined-candidate acceptance is unresolved.

Visual QA and persisted browser readback are blocked because qa_visual tools were unavailable. Audit-chain finalization/commit fault injection is not covered. This candidate is not AI_VERIFIED_AWAITING_HUMAN and must remain draft until required gates pass. No production release or merge is authorized by this evidence.

## Remaining human/QA checklist

Exercise standard and Usluga variants under allowed and denied roles; explicit and automatic numbers; selected fabric/BOM and copied sizes/colors; pattern versus explicit material/print images; approval/audit; duplicate and invalid-material refusal. Reopen and compare persisted rows and adjacent planning selection. Resolve the PostgreSQL lifecycle HOLD through its established procedure, then revalidate the exact source and bounded lock/integrity cases before acceptance.
