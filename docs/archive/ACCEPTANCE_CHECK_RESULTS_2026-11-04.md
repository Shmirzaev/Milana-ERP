# Shavkat acceptance results — 4 November 2026

The owner asked the agent to execute the checks and request only information
that cannot be independently established. These are agent observations against
the isolated synthetic lab running exact live commit `11f80a29`. They are not
operator sign-off, and API evidence is identified separately from browser work.
Production release blue `20261103_094602` was unchanged; green
`20261103_112256` remains the verified rollback. No production business data,
application code, permissions, credentials or routing were changed.

The original handout is preserved. Its historical fixture commit is not the
actual runtime baseline. Setup and the detailed Part C answers are in
[the environment report](ACCEPTANCE_SHAVKAT_2026-11-04.md).

## Results

Seventeen checks are accepted: fifteen have the specified behavior verified
with the coverage below, and the owner explicitly accepted A5 and A12 as passed
on 4 November 2026 after reviewing their observed differences. Those observations
remain recorded; no application fix or additional test is implied by acceptance.
Two checks, A4 and A14, have incomplete screen/print coverage.
Do not interpret this as nineteen completed human screen checks.

| Check | Result | Evidence and limits |
| --- | --- | --- |
| A1 Employee status | Verified — browser/API | Saved On leave, reloaded/reopened, restored Active and reloaded/reopened. Persisted readback agrees. |
| A2 Salary bounds | Verified — browser/API | Saved/reopened 1,500,000; negative input refused, 10,000,000,000 rejected with 422 and maximum 9,999,999,999.99. Valid salary retained. |
| A3 Employee/manager pagination | Verified — browser | Loaded 501 unique employees including Alice at position 501; direct search 910001 worked. Manager 910500 remained selected after clearing search; dialog closed unsaved. |
| A4 Live manager history | Partial — read-only production DB | Audit 144572 maps to Akbaraliyeva Muslima, 144573 to Alixonova Yodgoraxon Durbek qizi. Both current managers are Milana Akbarova Dilafruz, employee number 321. Audit transitions 129→313 retained. Distinct Milana manager 503 and its history remain separate. Live employee-card/history UI has not been checked. |
| A5 Accepted attendance/raw history | Passed — owner acceptance, 4 November 2026 | Failed 07:00 and unknown 19:00 raw events are retained in DB; HR and attendance screens use accepted 08:00 arrival only, with no departure. The raw event-history screen/control requested by the handout is absent from this release. The owner accepted this observed behavior as passed. |
| A6 Same-day attendance | Verified — browser/API | Both screens show Alice on 31 October, 00:30–23:30 Tashkent. HR shows 8 scheduled hours and 23 actual hours. |
| A7 Rapid/unknown badge scans | Verified — browser/API | Alice→Bob→work auto-saved one Bob earning, record 415. Unknown badge cleared selection and created no earning. Current UI auto-saves; the handout's separate Save instruction is stale. |
| A8 Issued rate/scan-only limits | Verified — browser/API | Issued 20 pieces at locked rate 1.25 saved as 25 UZS, record 416. Scan-only issue and arbitrary manual-pay requests both returned 403. |
| A9 Unmatched-date visibility | Verified — browser/API | Open-period view includes HISTORY-0001 after pagination and excludes unmatched September work. All periods shows that work dated 1 September with no payroll period. |
| A10 Adjustments | Verified — API mutations/browser readback | Bonus 1,000.50 and deduction 500 changed Alice's net 36.75→1,037.25→537.25. Invalid 10.555 and 256-character reason refused. Both saved adjustments appear after browser reload. |
| A11 More than 300 rows | Verified — browser/API | Browser loaded 407 open-period records, 401 employee groups and 403 adjustments with unique rows and stable totals. Independent API pagination passed. Counts reflect test mutations, not just the seed. |
| A12 Recorded split correction | Passed — owner acceptance, 4 November 2026 | Corrected 7/13 to 8/12, pay 10/15 UZS, original work date retained. Invalid 9/12 and stale revision rejected; scan-only editing denied. Browser correction dialog/readback and sticker names, quantities and QR values agree. **Printed stickers omit the rate**; the owner accepted this difference from the handout as passed. |
| A13 Returned split correction | Verified — API/persisted readback | Returned 53-piece row stayed unassigned at 2.5 until re-scan. Bob's scanned 52-piece row stayed 65 UZS at 1.25. Re-scan created Alice's single 132.50 UZS earning. The full editing sequence was exercised through the API rather than replayed in the browser. |
| A14 Package labels | Partial — HTTP/generated document/Edge DOM | Six QA-PKG-0001…0006 cards group 4 then 2 in explicit A4 page sections. All six QR images loaded at natural width 370. Generated content contains no Page footer. Native print-dialog pagination and Headers and footers off remain unverified; no physical print was submitted. |
| A15 Cutting-sheet customer | Verified — HTTP/Edge rendered DOM | GET preview for QA-PO-PRINT displays Acceptance Customer & Textile and QA-SO-SHORTAGE. QA-PO-PRINT-NO-CUSTOMER has no customer field/name. No cutting-completion POST was made. Native dialog/layout inspection remains a coverage limit. |
| A16 Sales shortage task | Verified — API/persisted readback | Exactly one first reserve attempt on QA-SO-SHORTAGE-FIRST produced 0 reservations, one 25-piece shortage and one pending High task, ID 2, due 7 November at 08:00 Tashkent (stored timestamp includes seconds). Repeated reads retained the single task. Planning Tasks-card UI was not replayed. |
| A17 Reset-token invalidation | Verified — API/captured test mail | Two fresh reset emails; newer link changed the synthetic password and new login worked; older link returned 400. A third fresh reset restored the documented test password. No production mail or password was touched. Browser password-change submission was not performed. |
| A18 Protected admin | Verified — API/persisted readback | Limited manager's protected-admin DELETE returned 403; account still exists. Admin-screen Delete control was not separately verified. |
| A19 Last full administrator | Verified — API/persisted readback | Synthetic mover changed MIL→BST and readback agrees. Deactivation of the last MIL full admin returned 400; account remained active and re-login/users access passed. Admin-screen controls were not separately verified. |

## Evidence

- [API checks and persisted results](acceptance-shavkat-20261104/api-results.json).
- [Browser observations](acceptance-shavkat-20261104/browser-results.json).
- [Print-document assertions](acceptance-shavkat-20261104/print-results.json).
- [HR attendance screenshot](acceptance-shavkat-20261104/A5-A6-hr.png).
- [Attendance overview screenshot](acceptance-shavkat-20261104/A5-A6-turnstile.png).
- [Split sticker preview showing the missing rate](acceptance-shavkat-20261104/A12-stickers.png).

Native Windows Computer Use could not establish the browser URL with sufficient
confidence and stopped before print-dialog inspection. Chrome and Edge attempts
were stopped when directed. Edge browser APIs could read the documents, while
screenshot capture timed out. This is a tooling coverage limit, not evidence of
an application printing failure. A new Edge window was tried at the owner's
request. No browser security settings were changed or safety barriers bypassed.

## Data touched and repeatability

All acceptance writes were confined to the disposable lab. Relative to the seed:
three saved scan earnings (fast Bob scan, issued Alice scan, corrected returned
Alice scan), two payroll adjustments and one shortage task were added. The
recorded split is now 8/12; the returned split was corrected and re-scanned.
Alice is Active at salary 1,500,000; manager-search selection was not saved.
The mover admin is now in BST. The reset test account's documented password was
restored. Captured test-reset emails remain in the isolated inbox.

The A16 first-click fixture is now consumed. Do not repeat the original checklist
against this database while claiming seed-state evidence. Use the saved results
or reseed a separately verified disposable lab. Original seed and handout copies
remain unchanged except for the prepared handout's two URL replacements.

## Owner information still needed

No credentials or ordinary ERP test input are needed to continue verification.
Physical infrastructure and business ownership cannot be inferred from the ERP:
PBS/Proxmox location, power/storage failure domains, independently recoverable
backup/encryption keys and restore ownership; DNS/TLS and Windows attendance
connector owners; approved vault owner/backup person and a quiet rotation window.
Only names, locations, inventory references and timing are needed, never secrets.
The full unknowns and existing server findings remain in Part C of the setup
report. Part B was not rerun; its pending #358/#359 and PERF37 approval are not
accepted merely because its heading says proven.

## Handoff

Worktree `C:\ERP\.codex-work\acceptance-shavkat-20261104`, branch
`codex/acceptance-shavkat-20261104`, based on exact runtime `11f80a29`.
This follow-up changes documentation and sanitized evidence only. No merge,
production deployment, application fix or credential rotation was performed.
