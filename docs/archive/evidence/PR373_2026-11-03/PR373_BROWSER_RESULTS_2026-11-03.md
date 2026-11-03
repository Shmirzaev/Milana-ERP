# #373 connected-browser results — 3 November 2026

Checker: Claude, using the Claude in Chrome extension in the user's real Chrome on macOS.
Target: http://localhost:63151, the isolated copy for #373 (commit 5c967f39). Times are Asia/Seoul, with UTC in brackets.
Scheduled outage: shared store down from 17:39 to 17:42, restored automatically.

**Result: PARTIAL.** The logged-out half passed. **The signed-in half was NOT covered**: the
session was never signed in. The test password lives beside Codex's checklist and wasn't provided,
and nobody signed in on the Mac before the outage. So whether /api/auth/me and the task list stay at 200 for a
signed-in user during the outage was not checked in the browser. Codex's HTTP rehearsal covers that.

## Timeline

| Time | Check | Result |
| --- | --- | --- |
| 17:23:46 (08:23:46Z) | Tab opened, not signed in | /api/auth/me 401, as expected |
| **17:34:06 (08:34:06Z)** | /api/auth/me, not signed in, **before the outage** | **500, once.** It was 401 again at 17:34:14 and stayed 401 for all 157 samples after. Unexplained, and not part of the scheduled outage. |
| 17:34:24 (08:34:24Z) | Baseline: login with a dummy wrong password, sent without cookies (form POST /api/auth/login) | **401** JSON `{"detail":"Invalid credentials"}` |
| 17:35:10 | Login page | Normal. `pr373_1735_login_baseline.jpg` |
| **17:39:16 (08:39:16Z)** | Same dummy login, store down | **503** JSON `{"detail":"Authentication is temporarily unavailable. Try again later."}`, in 15 ms. Not 500. |
| 17:39:29–17:39:39 | Same dummy login through the real login form | The button showed "Signing in..." for about 6–10 s, then: **"503: 503: Authentication is temporarily unavailable. Try again later."** `pr373_1739_login_refused_503.jpg` |
| 17:40:27 (08:40:27Z) | Password-reset request (POST /api/auth/forgot-password), store down | **503**, same JSON message (37 ms). Not 500. |
| 17:41:10 (08:41:10Z) | Dummy login, store down | **503** (14 ms) |
| **17:42:13 (08:42:13Z)** | Dummy login after the restore | **401** "Invalid credentials" (228 ms). Recovered without a restart. |
| 17:42:24 | Login form submitted again | Shows "401: Invalid credentials". `pr373_1742_login_recovered_401.jpg` |

**/api/auth/me probe, not signed in:** 157 samples every 3 s from 17:34:34 to 17:42:22,
all **401**, including all through the outage. Before #373, this route returned 500 during an outage. It now
refuses normally.

To avoid triggering login lockout, the checker sent only 5 dummy login attempts in total.

## Findings

1. **Login and password reset refuse cleanly during the outage:** a 503 with a clear JSON message, never 500.
   Once the store is back, they return to normal without a restart. This matches the 3 Nov decision.
2. **An unauthenticated /api/auth/me refuses normally (401) during the outage,** where it used to return 500.
3. **Cosmetic:** the login form shows the status twice: "503: 503: Authentication is temporarily
   unavailable…". It also sits on "Signing in…" for about 6–10 s before showing the error,
   probably retrying. Worth a small follow-up.
4. **One unexplained 500 from /api/auth/me at 17:34:06, outside the outage window.** It didn't
   repeat. It could be the store controller arming early, or something else; the backend logs for 08:34:06Z will say.

## Not covered
- **The signed-in user during the outage** (/profile, the Tasks drawer, the "Shared-store outage test
  task", me and tasks at 200): **not checked in the browser.**
- Phone layout and RU/UZ.
- Nothing is marked verified or accepted. No production access.
