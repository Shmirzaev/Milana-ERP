# #386 (IDN-01 factory switch) connected-browser results — 3 November 2026

Checker: Claude, using the Claude in Chrome extension in the user's real Chrome on macOS.
Target: http://localhost:18820 (isolated stack, head 34e111fc). Times are Asia/Seoul, with UTC in brackets.

**Result: PASS on every step that was run.**

| Time | Step | Observed |
| --- | --- | --- |
| 23:13:52 (14:13:52Z) | Two-factory account, logged in with Milana, opened /sewing/flows?factory=MIL | Heading **"Milana - Sewing Flows"**, and **IDN01 Milana Test Line** is listed; no Eco test line. The sidebar shows Milana sections. `pr386_1_multi_MIL.jpg` |
| 23:14:06 (14:14:06Z) | Same tab: ?factory=ECO | Switched: heading **"Eco Cotton - Sewing Flows"**, **IDN01 Eco Test Line** present, Milana line gone. The sidebar changed to Eco Cotton sections. `pr386_2_multi_ECO.jpg` |
| 23:14:11 | Reloaded ?factory=ECO | Still Eco Cotton, with its line. |
| 23:14:25 | Extra: plain /sewing/flows, no factory parameter | Still **Eco Cotton**. The switch persists in the session; it isn't just following the URL. |
| 23:14:32 (14:14:32Z) | ?factory=MIL again | Back to **"Milana - Sewing Flows"** with the Milana line. `pr386_3_multi_back_MIL.jpg` |
| 23:14:52 (14:14:52Z) | Logged out, then logged in with the MIL-only account (Milana) | Dashboard loads. The sidebar has only Milana sections, **no Eco Cotton section**. `pr386_4_milonly_sidebar.jpg` |
| 23:15:07 (14:15:07Z) | MIL-only account opens /sewing/flows?factory=ECO directly | **"Access denied."** No Eco data is shown, and /api/auth/me still reports factory **MIL**, so the account didn't switch. `pr386_5_milonly_ECO_denied.jpg` |
| 23:15:12 | MIL-only account, plain /sewing/flows | "Milana - Sewing Flows" with the Milana line. The denied attempt left the session in MIL. |

## Notes (not IDN-01 regressions)
- For the two-factory user, the sidebar only ever shows the **currently selected** factory's sections. So "no Eco section in the sidebar" for the MIL-only user is expected either way. The strong evidence is the direct-URL denial at 23:15:07.
- The "Access denied." page is plain text with no link back. Usable, but bare.
- The greeting says "Good morning" at 23:14 Seoul time (seen before; it looks like it uses UTC).

## Not covered
- Phone layout and RU/UZ.
- The old-token behavior after a switch is covered by #382's tests, not by this browser check.
- Database readback is Codex's comparison. Nothing is marked verified or accepted. No production access.
