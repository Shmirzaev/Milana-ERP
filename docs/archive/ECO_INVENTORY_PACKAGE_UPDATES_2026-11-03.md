# ECO inventory and package visibility: local-review candidate

## Scope and authority

User requests all five changes: complete Cutting Passport Excel export; explicit
legacy package model/variant identity; sewing-factory package filtering and
Warehouse Inventory column; separate ECO fabric/accessory stock; two-sided fabric
dispatch/receipt with an Excel driver document; accessory requirements, approval
after BSO creation and before sewing, allocation and stock-backed issuing.

On 3 November the user explicitly authorized a separate PR into `clone_main`
and local review before any production release. No merge or deployment is authorized.
Base: `77d090f69c293f716adf9e2df6227d9543552442`. Dedicated worktree:
`C:\ERP\.codex-work\eco-inventory-package-updates-20261103`, branch
`codex/eco-inventory-package-updates-20261103`.

Implementation: Codex coordinating agent and isolated package/material workers.
Human domain ownership remains Ismail/Mirshoir for Inventory and
Mirshoir/Ismail for Production, Packaging and Fulfillment; their review has not
been supplied. Independent AI review and Shavkat's local business acceptance are
separate gates. Shared router/navigation/context changes have one writer, the
coordinating agent. No team messages or review approvals are fabricated.

## Baseline and preservation

The legacy checkout has 167 modified tracked paths; preserve them in place.
`origin/main` is stale. `clone_main` records green `20261102_063110`, runtime
`42078704df340558c8a21bf1ef14bf74cc87b222`, schema `0149_besttex_cutting_access`,
with blue `20261031_092951` retained. These are recorded assertions, not fresh
live checks: SSH key authentication was refused. Local-only development was
explicitly authorized following disclosure of this baseline discrepancy.

Existing passport export already has summary and material sheets, filtering and
EN/RU/UZ headers; verify it before making changes. Existing ECO dispatch/return
register is a custody ledger, explicitly without ECO receipts. Preserve it and
introduce the requested inventory transfer separately. Usluga customer-supplied
fabric remains outside factory-owned stock.

## Intended acceptance examples

- Export the authorized filtered passports with all material rows and numeric
  quantities; original output is not multiplied by dashboard-only rules.
- Scan a legacy package: show model and variant numbers using trustworthy
  catalog/import evidence, with unavailable values explicit rather than invented.
- Filter packages by actual sewing evidence; preserve mixed/unknown provenance.
- Dispatch available Milana fabric: remove available source stock, retain an
  in-transit record and Excel document. ECO receives only confirmed quantities;
  repeated requests cannot create duplicate stock. Preserve batch identity,
  units, source/receipt references, actor and history.
- ECO receiving/consumption/history cannot read or mutate Milana balances.
- Requirements attach to an ECO production order/model with an existing BSO.
  Approval allocates stock, issue deducts stock, and unapproved requirements
  cannot pass the applicable sewing handoff. Existing sewn work is not replayed.

## Evidence ledger

Status: IMPLEMENTING. No runtime, browser, PostgreSQL, stress or human gate is
claimed passed. Each operation's exact checks and limitations will be recorded
after implementation. Production access/deployment and business-data changes:
none. Local test fixtures must use disposable isolated databases only.

New fixed vocabularies must use canonical enums; stock units, names and model
identities remain data. New ORM writes belong in schema persistence operations,
business rules/transaction ownership in services and HTTP binding in routes.
