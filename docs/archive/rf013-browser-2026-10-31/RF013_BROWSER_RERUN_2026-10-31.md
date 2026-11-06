# RF-013 connected-browser rerun — 31 October 2026

Checker: Claude, using the Claude in Chrome extension in the user's real Chrome on macOS.
Stack: tooling #366 (f9e55970). Old release ec02b5f8, candidate 111a05c5. **Both frontend slots run
the built production images.** Frontend http://localhost:60533, backend health http://localhost:60530.
Account: rf013-admin@example.com. Times are Asia/Seoul, with UTC in brackets.

**Result: every logged-in check passed.** The data survived the rollback and the failed-activation recovery, and the session survived the rollback. The one gap is that the 23:44 rollback switch itself wasn't watched live.

## Timeline

| Time | Step | Observation |
| --- | --- | --- |
| 23:17:52 (14:17:52Z) | Start, candidate | Logged in. Default currency **USD**. `rf013b_2317_start_USD.jpg` |
| 23:38:28 (14:38:28Z) | Baseline save, candidate | Currency set to UZS; the Financial Settings Save shows "saved." |
| 23:38:31 (14:38:31Z) | Baseline readback | After a reload: **UZS**. `rf013b_2338_baseline_UZS_saved.jpg` |
| 23:44:00 | Rollback (scheduled) | **Not watched live**, because the reminder fired at 23:45:16. The background probe was throttled to one sample a minute; backend /health was 200 at 23:43:38, 23:44:38 and 23:45:31. Codex's logs give the exact switch timing. |
| 23:45:35 (14:45:35Z) | After rollback | Settings loads with no re-login: **the session survived** (/api/auth/me 200). Currency **UZS**, so the baseline write survived the rollback. `rf013b_2345_after_rollback_UZS.jpg` |
| 23:45:49 (14:45:49Z) | Save on the old release | Currency set to USD; Save shows "saved." |
| 23:45:53 (14:45:53Z) | Readback | After a reload: **USD**. `rf013b_2345_rollback_USD_saved.jpg` |
| **23:52:15 (14:52:15Z)** | Failed frontend activation | The router's bare page: "503 Service Unavailable / No server is available to handle this request." No app styling, no Retry. `rf013b_2352_failed_activation_503.jpg` |
| 23:52:24 (14:52:24Z) | Same moment, backend | Backend /health **200** (11 ms). Only the frontend route was down. |
| 23:52:34 – 23:53:56 | During the outage | Ten reloads about 10 s apart, on /settings and once on /login: all the same bare 503. |
| **23:54:07 (14:54:07Z)** | Recovery | Settings loads again: the first good reload, about 1m52s after the first 503 I saw. |
| 23:54:15 (14:54:15Z) | After recovery | /api/auth/me 200 (the session survived this too). Currency **USD**. `rf013b_2354_recovered_USD.jpg` |
| 23:54:41 (14:54:41Z) | Fresh login | Logged out, logged in again, reopened Settings: **USD** persists. `rf013b_2354_relogin_USD.jpg` |

**Backend probe:** 164 samples from 23:23:26 to 23:54:38, and every one was /health 200. It ran throttled
in a background tab at about one sample a minute, so it can't rule out short backend gaps; Codex's
logs are the timing source for those.

**Browser-visible failed-activation window:** the first 503 was seen at 23:52:15 and the last at
23:53:56; it was working again by 23:54:07.

## Findings
1. Writes survived both the rollback and the failed-activation recovery. Nothing was lost or reverted.
2. Sessions survived both. No logout was forced, and a fresh login works afterwards.
3. During a failed frontend activation, users get the router's bare 503 page with no Retry for about
   2 minutes. Same as the first run, and still Mirshoir's question 10.

## Not covered
- **The rollback switch at 23:44:** not watched live. The browser saw the state just before (23:38) and just after (23:45:35), which covers persistence and the session, but not what users saw during the switch.
- **Phone layout, and RU/UZ:** not checked.
- No production access. No independent or human gates are filled. Nothing is marked verified or accepted.
