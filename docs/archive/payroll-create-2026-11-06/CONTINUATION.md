# Payroll continuation — 6 November 2026

User correction after #511: do not stop for browser access; user owns one combined browser block at end. Retain host servers PostgreSQL 20000, backend 20001 and frontend 20002. When hosted CI is green, mark #511 ready and merge; same rule for subsequent operation PRs. Continue every remaining inventory operation with two commits each, stack shared code. Adjustments/reversals require PostgreSQL characterization with zero skips, including totals after each and after both with locked periods; inability to run those checks requires stopping and explanation. Browser delegation is not a recorded visual PASS or deployment approval.

Owner Dilmurod, lead Mirshoir (review delegated), independent AI reviewer `/root/review_payroll_create`; author email dilmurod111804@gmail.com. Integration base 0da97aea; every candidate is a short-lived operation branch. Only coordinator writes payroll route/service/shared persistence. Named reviewers inspect frozen operation diffs. Production work-evidence contracts must remain unchanged.

## Ledger

- CREATE: #511, characterization ebe3afee; extraction 932f0f54. Hosted CI pending at continuation start. Previous browser BLOCKED state retained historically; user now explicitly performs that gate.
- LIST PERIODS: characterization 0a5ed1db; baseline and candidate six passed / zero skips, including SQLite/PostgreSQL qualification: bonus changes source 2500→3000; locking preserves total; source reversal posts -2500 only to separate open target; combined all-period total 500 (with bonus) or 0; both periods locked reject further adjustment/reversal without duplicate rows. Period/record/audit readback checked. No reversal is written into a locked target. New listing preserves status/factory filter and denied-user 403. Pure read: no commit or schema change. Source DTO/status strings retained for no behavior change; enum adoption remains separate pending work.

Actual test reports retained at /private/tmp/payroll-qualification.xml and /private/tmp/payroll-list-periods-candidate.xml. Server checks: non-admin payroll role GET periods 200, denied role 403, frontend login HTTP 200. Required browser block is USER-OWNED/PENDING, not PASS. Full hosted CI handles unaffected groups; no release/deployment authorization.
