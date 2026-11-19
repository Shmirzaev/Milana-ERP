# Verified integration checkpoint — 28 October 2026

Source checkpoint: clone_main merge `1f0022ad55d9f326212694e4ac5d4e16b63bb713`, tree `c59b4624ffe0282384730a3dc33593a755d0d898`. These are local and hosted observations, not production deployment or human business acceptance. The detailed contemporaneous receipts are held in the working evidence packet `pr-review-20261027/PR335_ACTUAL_VISUAL_VERIFICATION_20261028.md`, `PR336_ACTUAL_VISUAL_VERIFICATION_20261028.md` and `PR337_ACTUAL_VISUAL_VERIFICATION_20261028.md` outside this repository.

- PR335 merged as `c22c88e2592d628cf78bc818c9e1c49cf18ec7fc`, tree `c82d1c7b6041ac2a58d6ff31b3fd4977c1ee6946`. The exact candidate passed 107 required plus 17 supplemental PostgreSQL cases; API/PostgreSQL evidence covered implicit branded planning creation. The normal UI requires a selected order: its local visual test and Cutting handoff did not exercise the implicit branch.
- PR336 merged as `898dcc3926ac10003954896784bb84372632fcdd`; candidate `2b0b7075b305db80dfdd4db20cab39b1caee945b`, tree `e802e97a52ff3b7c9fcdee5d9129d917b42831a0`: Customer create via Customers and Sales Order dialog, persisted readback and audit; Brand description edited and restored under explicit authorization. 116 required plus 17 supplemental PostgreSQL cases passed. Mobile overflow and untested Brand fields/denied role remain limitations.
- PR337 candidate `d75582fce5e9a3d6d26dc05f07ac16d0e561cb63`, tree `c59b4624ffe0282384730a3dc33593a755d0d898`: Supplier create, persisted readback and audit, and selection in Receiving without receipt. 123 required plus 17 supplemental PostgreSQL cases passed. Permission tests override user context and do not prove the complete token/DB-role chain; denied-role GUI was not covered.

These scoped tests used the genuine f27 frontend artifact with matching frontend tree; it was not relabeled as built from the later candidate. The repaired artifact supported actual local login and UI. Earlier failed probes are not retroactively passes. At this earlier checkpoint Customer UPDATE draft PR339, dependencies PR331 and tooling PR338 remained pending. Full type and operation coverage, human production acceptance and deployment remain separate.

## Later integration checkpoint: PR338 and PR339

CI tooling PR338 merged as `e6f597891489e38207e01b6bfcca3d8df1b7adea`.
Customer UPDATE PR339 merged as `61b1a7020c5e1465aa076acc238d94ea1ad7dd03`,
tree `a943af045834ff43227ddd4640504f11ddccb69b`. Candidate
`b313e87418e075db7735fcea0f5c96e3ccfbb458` had six hosted checks passed,
release skipped, and 128 required plus 17 supplemental PostgreSQL cases without
skips or failures. These cover scoped permissions, field semantics, rollback/retry
and distinct-customer concurrency; they do not establish same-row ordering or
normal login/get_db production teardown.

The human-approved edit and restore of Customer3 occurred in V23 at
`f86de0899afa7f72aac84014e077a97cc34a6f9c`, producing audits 136 and 137.
Readonly integrity evidence confirms restored fields and audit chain. V23 stopped
when available physical memory fell below its reserve guard and final reload failed, so that window remains FAILED/
INCOMPLETE. The backend app tree `3542f35e3fcefdb605b01fe2dc9b77e3bf1f6734`
and frontend tree `5ecf4a50f6649e335f32ff4a5d1ce55d6af93577` match between
f86 and b313, according to separate root and independent Git closure checks;
the writes remain attributed to f86, not relabeled as b313 writes.

Fresh b313 V25 performed read-only Customer list and profile reload and persisted
readback, then stopped normally; no new save or audit occurred. Independent visual
review passed that narrow scope, not the earlier failed window. The reviewer did
not independently access the Git objects and the mobile image did not show the
payment section. The genuine f27 frontend artifact remains correctly attributed.
The detailed receipts are in the external working packet
`pr-review-20261027/PR339_ACTUAL_VISUAL_VERIFICATION_20261028.md` and
`PR339_V25_CUSTOMER_GUI_INDEPENDENT_REVIEW_20261028.md`.

Supplier UPDATE remains pending. Dependency PR331 remains pending: native V2/V3
failed and the installer was not run. Full operation/type coverage, human
production acceptance and deployment remain separate.

## Superseded context at this checkpoint

The following preserves the prior current-context wording as historical evidence; it is not the current state:

QA artifact entry is currently blocked by `QA-APP-ROUTES-20261028` in
[the active tracker](../../bugs/bugs.md): real `/login` and `/` navigation returned
404 although health passed. The packager omitted two Next runtime inputs.
The repair must reconcile declared runtime files, smoke-test the extracted
artifact's login page, and repeat connected-browser/readback checks. Earlier
build, hash and health results do not establish a usable QA website or acceptance.

The current reservation compatibility correction preserves raw input spelling for
retry fingerprints and failure audits while keeping canonical typed business
values. Empty category fallback and invalid input have distinct private tags;
invalid input must reach the original domain refusal point. Mapping/attribute
validation, assignment and both Pydantic copy APIs have independent regression
controls. The shared Catalog BOM page also clears stale success and reports a
refused write without clearing the form. These corrections require their own
combined PostgreSQL/build/browser evidence; earlier ff7c UI passes do not verify
this source. Full enum adoption and human acceptance remain open.

The [manual Finance invoice candidate](FINANCE_MANUAL_INVOICE_CREATE_2026-10-27.md)
moves its insert into schema-owned persistence and types its actual UI response.
Existing policies are preserved; independent review, candidate visual checks and
human acceptance remain separate. It does not complete Finance or the refactor.

The isolated three-operation candidate `1d4f00da` combines Sales confirmation persistence, typed Catalog BOM PATCH persistence and the typed Finance customer-order payment projection. It preserves the complete reviewed author chains and records all source bytes in the integration freeze. The BOM PG ledger still requires 54 cases with the updated canonical-role PATCH node. Source review and individual author tests do not substitute for renewed combined application, PostgreSQL, frontend and actual browser evidence. Human acceptance remains separate. Serving `6f280c6d` does not include these three additions.
