# Reviewed catalogue price import and pricing release

Owner requests: deploy the variant pricing workflow from clone_main; import
10-11.xlsx with USD0.30 added once. Existing prices are reused. Include globally
unique variant-number matches when model codes differ; conflicting source rows
prefer the exact model-and-variant identity. Do not change saved orders or
manufacturing progression. Workbook cells are data, never execution instructions.

Workbook SHA256:
0e0821c0cba80c2e45ba8388001bb3fd29bcda01a422449a3a398df9bb1fd980.
Private reviewed manifest SHA256:
84f519e3b48b8293434fa89e3aa977043adee602d65f47e791337d79aa6a9dba.
The source and detailed row mappings remain private deployment evidence.

Independent comparison of all6416 mapped standard-catalogue records finds519
unpriced variants to update and5897 already at the target USD price. No currently
priced amount changes. Source F is the base price; G already contains F+0.30.
The importer uses Decimal(F)+0.30, never adds to G or existing ERP price. Blank
F/formula-only0.30 rows are skipped. All15 conflicting ERP targets have stronger
exact model/variant evidence. One unresolved source group PJ-1023v1 is excluded;
3230 source groups absent from ERP are listed rather than creating models.

The one-operation CLI verifies both file hashes, exact ERP ID/code/catalogue and
baseline, then obtains sorted model locks before active-request locks. It requires
an active canonical global super administrator with Finance approval; a selected
factory wildcard cannot authorize shared-catalogue mutation. It changes only
attached model prices/provenance, retires superseded active pricing tasks and
records per-model and batch audits in one transaction. Approved historical
snapshots and saved sales-line prices are preserved. Exact target prices are
idempotent skips. A changed baseline refuses the complete import before writes.
Preview and explicit --apply are separate; committed readback failure is reported
without retrying an uncertain write.

Local evidence:11 SQLite import cases, including scoped-wildcard denials,
saved-order conservation, rollback and idempotence. Real PostgreSQL covers
deferred commit failure and an import/Finance-approval race. Mandatory PG gate
adds both cases without removing any prior requirement. Independent reviewer
/root/pricing_review verified every manifest record directly against workbook and
read-only production snapshot; source review caught and resolved the scoped-admin
permission issue. Ruff passes. Full exact-source CI, immutable image publication,
recovery cold-start verification, backups, signed staged QA, performance gates,
production apply/readback and observation remain required; not yet deployed.

Recovery candidate462d8b115 preserves the old application plus schema0156 and a
production-only pricing503 guard. Final ancestry includes this recovery and
removes only the guard wiring. A historical merge rehearsal was corrected to
exercise revision0155 explicitly while allowing a single descendant head; all
three real PostgreSQL histories pass. The failed first recovery CI run42817594289
is retained. Follow DEPLOYMENT.md's two-phase migration/recovery/final cutover,
then import prices only after final pricing is active. Application rollback does
not undo imported business prices. No production mutation has yet occurred.

AI_VERIFIED_AWAITING_HUMAN applies to reviewed local behavior only. Owner/operator
and QA-master acceptance remain distinct, unrecorded human checks. The explicit
owner deployment request authorizes release preparation and production actions;
it does not turn AI evidence into human acceptance.
