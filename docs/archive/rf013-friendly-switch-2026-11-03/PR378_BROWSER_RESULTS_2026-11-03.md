# #378 connected-browser results — 3 November 2026

Source: checker-supplied `BROWSER_RESULTS_378_and_373_2026-11-03.md`; three screenshots inspected. Isolated local stack only.

## #378: friendly page during a failed slot switch — PASS

Stack: built images, b85d9bd1. Account: rf013-admin@example.com.

**Setup issue:** logging in at **http://localhost:53875 failed with "403: Untrusted request origin"**.
The same stack at **http://127.0.0.1:53875** worked, so the stack's trusted origins list 127.0.0.1 but not
localhost. That's a stack config gap, not a #378 defect. The whole session used 127.0.0.1.

| Time | Observed |
| --- | --- |
| 19:20:45 (10:20:45Z) | Signed in. Settings shows Default currency **USD**. `pr378_1920_baseline_settings_USD.jpg` |
| 19:27:41 (10:27:41Z) | After the scheduled 19:27:25 failed activation, a reload of /settings shows **"Back in a moment"**: "We are restoring the service. This page retries every 10 seconds.", then the same in Russian and Uzbek. Plain page, tab title "Back in a moment", `<meta http-equiv=refresh>` set to **10** seconds. `pr378_1927_back_in_a_moment.jpg` |
| 19:27:50 (10:27:50Z) | Same origin, **/api/auth/me → 503 JSON** `{"detail":"Service unavailable"}`. |
| 19:28:58 and 19:30:31 | The tab is still on "Back in a moment" (not touched). |
| **19:30:59 (10:30:59Z)** | **The tab returned to the app by itself** (title "Milana Ecosystem", /settings), between 19:30:31 and 19:30:59, after recovery began at 19:30:25. No click, no reload. |
| 19:31:29 (10:31:29Z) | **Still signed in** (/api/auth/me 200). Default currency **USD**. `pr378_1931_auto_returned_USD.jpg` |
| 19:31:32 | After a manual reload: still **USD**. |

**Findings:** the friendly page replaced the bare 503. It's in three languages, retries every 10 seconds, the API
keeps a JSON 503, and users come back automatically, still signed in, with their data intact.


## Coverage and tooling follow-up

Phone layout and RU/UZ inside the app were not covered. The 503 page itself displayed EN/RU/UZ. No production access or human acceptance is claimed. The local rehearsal config now lists both `localhost` and `127.0.0.1` as trusted frontend origins; this browser run used `127.0.0.1` before that config correction.
