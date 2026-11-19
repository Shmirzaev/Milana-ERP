# Planning price request creation — frozen candidate

Base: febe73c69434032737bcca1f5f305aa7702e3ba8. Engineer owner Ismail; reviewer Mirshoir. Agent: planning_request_create_dev. Scope: POST creation only, no change to policy, DDL or idempotency. Shared pricing paths overlap #391/#399/#400; integrator must reconcile and verify combined candidate.

Trace: sales.orders authorization; model lookup; model details costing target_margin_pct is free-form parsed Decimal, negative accepted; invalid precision returns 422; request inserted and flushed before audit and deduplicated active department notifications; service commits and refreshes. Repeated POST creates separate records. Existing audit and notification schema-owned persistence remains participating writer. Insert persistence now accepts the same session and flushes without commit.

Types: model_id integer, actor ID integer, parsed margin Decimal or None; costing JSON is free-form. No fixed-vocabulary contracts converted by this narrow creation slice. Remaining table-by-table types and other operations unresolved; no area-wide completion claimed.

Tests: creation persistence and workflow tests added; container first failed mount permissions, second timed out, third interrupted by coordinator. No test pass claimed. Independent review, exact combined integration, visual/browser, PostgreSQL persisted readback, stress and human checklist remain pending. No AI_VERIFIED_AWAITING_HUMAN claim. No push, merge or deployment.
