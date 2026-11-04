# Reservation plan readiness contract — 4 November 2026

Candidate based on `4e17b4aa`; Inventory owner Ismail, reviewer Mirshoir.
This narrowly types the non-persisted material reservation plan readiness; it
is separate from the material reservation lifecycle and accessory-issue plan.
The row vocabulary is `ready`, `shortage`, `partial`; aggregate adds `no_bom`.
An empty BOM continues to report `no_bom` and `is_complete: true`. Arithmetic,
stock policy, storage, transaction boundaries, and JSON string values are unchanged.

This intentionally changes the OpenAPI response schemas from unrestricted strings
to enum references, and response DTO validation now rejects unknown readiness
values, including `no_bom` on a row. Clients generating types from OpenAPI may
need regeneration. Production status and audit consumers, frontend consumers and
legacy audit JSON/hash serialization require combined verification; no production
code or audit history is changed by this candidate. Internal producer dictionaries
remain dynamically shaped: annotating their full shape would require independently
modeling BOM rows, suggestions and downstream consumers; a partial or `Any`-heavy
TypedDict would imply a precision not established here. The actual status values
are canonical Enum instances and both response fields carry precise Enum types.

Automated, PostgreSQL, browser, persisted-data, stress and independent review gates
remain pending on the exact combined candidate. This record is not human acceptance,
merge or deployment authority. Preserve existing holds and operation ledger.
