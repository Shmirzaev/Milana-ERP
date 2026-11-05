# Planning, floor pictures and BST visual review

Feature state: **HUMAN_APPROVED** for the visual/business checklist on exact narrow runtime source
94e4cfc54c6cc4fd5787bcbc7ba8483f4518a507. After the AI checks and concrete preview
checklist, the owner replied “Visual QA approved” on5 November2026. This approval
does not mean production activation or immutable-image readiness. The release
performance/health gates remain separate and pending.

## Actual isolated application verification

Edge exercised the existing optimized frontend and real FastAPI application with
normal HttpOnly-cookie login, real PostgreSQL and no dependency overrides or
response mocks. The candidate's existing Alembic chain reached0154 on a new
owned loopback-only database. All models, orders, employees, accounts and outputs
used for these checks are synthetic and outside production.

- Planning: actual planner saved PO-0001 CUT to ECT, reloaded and reopened it.
  Independent PostgreSQL readback found only the Cutting work order department
  and ordinary updated_at timestamp changed, with one audit. Production order,
  item quantities, downstream plans, batches and reservations were unchanged.
  Recorded-work PO-0002 and assigned-operator PO-0003 visibly refused changes
  with Save disabled. A Cutting operator received Access denied on Planning and
  had no factory-change button. English, Russian, Uzbek and390px phone layout
  were visually inspected; no horizontal page overflow on the phone dialog.
- Floors: Cutting, Printing, generic Packaging, ECO BandFloor and the separate
  awaiting-Packaging table rendered order artwork and exact-model fallback beside
  the original model/material thumbnails. The actual signed full-size preview
  loaded; images had nonzero natural sizes and contain fit. PDF-only rows had no
  artwork image. Normal Band authentication constrained the page to its assigned
  ECO band. Saved output projections showed6 sewn against12 planned and6 ready
  for Packaging. No package, receipt or finished-goods stock was created.
- BST: the guarded handoff ran only on eight synthetic employees and two test
  flows after a real local custom-format backup/restore-list check. Actual
  readback equaled the preview, old identities were unchanged, one audit existed
  and retry added no audit. Edge displayed both new flow names; reopening workers
  showed the exact selected new manager for both teams. The separately captured
  real production plan remains unapplied: the aggregate handoff is42/40 workers,
  preserving original identities and history. Exact production identifiers and
  roster relationships remain in the ignored private plan.

All inspected application console-error logs were empty. Screenshots and detailed
readbacks are in ignored runtime outputs/visual-20261105 and outputs/qa-20261105.
The initial local fixture had an invalid test email TLD and one incomplete
assignment payload. Those attempts failed rather than passing. Their corrections
were limited to test infrastructure; a frozen reviewed continuation skipped
already committed fixture steps and retained the422 evidence. No application
guard, assertion, output row or production data was patched to make the check pass.

## Automated, integrity and recovery evidence

Exact94e CI41835800604 and PostgreSQL gate41835800637 passed. Backend full suite:
5116 passed,606 optional skips; explicit Planning19, BST27 and ECO8 PostgreSQL
gates passed alongside the dedicated existing database gates. Final local focused
109 cases and both frontend component suites (9 Planning/14 artwork) passed.
Existing query budgets were retained and independently retested, including the
real stale-source PostgreSQL race. BST concurrency/retry/timeout/audit rollback
and protected-history checks passed; these are the bounded stress and recovery
evidence, not a claim of unlimited production load capacity.

The latest source-only clone_main reconciliation separately passed207 focused
cases (31 initially skipped without a PostgreSQL target), then61 cases with the
owned PostgreSQL target and zero skips. Its independent merge review confirmed
69 incoming blobs identical and the sole overlap equal to the clean three-way
merge, preserving all108 other task paths. That source branch still requires
the separately approved migration-graph package before full deployment.

## Human visual checklist

Use these Edge preview pages; sessions have been prepared locally:

1. [Planning](http://127.0.0.1:3089/planning): open Change cutting factory.
   PO-0001 should show Eco Cotton after reload; PO-0002 and PO-0003 should explain
   their refusals and disable Save. Any test changes here affect only synthetic data.
2. [ECO Packaging](http://localhost:3089/departments/ECP): confirm the print-picture
   column, positive artwork on PO-0004/0005 and no image for PDF-only PO-0006;
   inspect the awaiting-Packaging table and its6-piece ready quantities.
3. [BST flows](http://localhost:3089/sewing/flows?factory=BST) and
   [employees](http://localhost:3089/hr/employees): confirm the two QA-prefixed
   replacement names and the workers' current manager selections. Local sample
   groups have two workers each; the reviewed real plan is42/40.

Record approval or describe the issue against source94e. Existing deployment
authorization remains valid; this is the repository's distinct human visual gate.
Production still serves20261104_080711, and no production worker handoff or source
cutover has happened. The owner waived30-minute observation only; exact images,
backup, read-only inactive-slot QA, performance and final health remain required.
