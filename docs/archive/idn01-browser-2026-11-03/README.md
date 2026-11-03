# IDN-01 factory-switch browser evidence — 3 November 2026

Candidate: #386, `34e111fc`, isolated `http://localhost:18820` copy. The connected-browser checker used the user's Chrome. The [received report](PR386_BROWSER_RESULTS_2026-11-03.md) and five [screenshots](pr386_1_multi_MIL.jpg) are preserved here; the other images are [ECO](pr386_2_multi_ECO.jpg), [back to MIL](pr386_3_multi_back_MIL.jpg), [limited sidebar](pr386_4_milonly_sidebar.jpg), and [denied ECO](pr386_5_milonly_ECO_denied.jpg).

I inspected all five screenshots. They show the MIL heading and test line, the ECO heading and factory-specific band view, the MIL-only sidebar, and the plain “Access denied.” page. The “back to MIL” image is byte-for-byte identical to the first MIL image, so it is not independent screenshot proof of the return; the checker’s timed report and the replay below support that step. The ECO screenshot is cropped before the reported `IDN01 Eco Test Line` is visible; that specific visual claim comes from the checker’s report. The isolated API readback also returned the `IDN01-ECO` fixture row.

The selected factory is a session-token claim, not a stored `users` selection. I replayed the same switches with test accounts and compared `/api/auth/me` with PostgreSQL after every step. Raw, password-free values are in [readback-comparison.json](readback-comparison.json).

| Step | Selected in `/me` | Stored primary factory | Audit rows for user |
| --- | --- | --- | --- |
| Two-factory user, before switch | MIL | MIL | 0 |
| After switch to ECO | ECO | MIL | 0 |
| After switch back to MIL | MIL | MIL | 0 |
| MIL-only user, before denied ECO attempt | MIL | MIL | 0 |
| After denied ECO attempt (403) | MIL | MIL | 0 |

For each account, the compared stored assignment, active flag, role, grants, policy and audit count were identical before and after the switches. The denied attempt left both the selected factory and those stored values unchanged. This matches #386's no-switch-audit behavior; a later, separately scoped PR changes that behavior.

**Not covered:** phone layout and RU/UZ. The browser check and database comparison do not mark the operation AI-verified or human-accepted. The full #322 suite on #386 still has the two recorded Sales/PERF26 and Inventory/S06 baseline failures.
