# #373 connected-browser rerun — 3 November 2026

Source: checker-supplied `BROWSER_RESULTS_378_and_373_2026-11-03.md`; isolated local stack only.

## #373: signed-in check during the store outage — NOT COMPLETED

Stack: http://localhost:63151 (rebuilt by Codex after the disk recovery). Account: sec04-admin@example.com, MIL.

- **The rebuilt frontend is broken:** /login and /profile return **"Internal Server Error"** (a page render
  500), while /health and the API work. The page checks couldn't be done at all.
- Signed in through the API from the same browser tab (cookie session): /api/auth/me **200**,
  /api/tasks **200**, "Shared-store outage test task" present (19:22:19).
- **The scheduled outage (store down 19:30:24 to 19:33:24) didn't happen, as far as the browser could tell.** A logged-out
  dummy login still returned **401 "Invalid credentials"** at 19:30:31, 19:30:58, 19:31:19 and
  19:32:02. On 3 Nov at 17:39 the same call correctly returned 503 during a real outage. At 19:32:37 the
  dummy login returned **429 "Too many failed login attempts"**, which uses the store, so the store was up. That
  429 came from the checker's own dummy attempts (7 in total), so those requests count as lockout tests,
  not outage evidence.
- Signed-in me and tasks stayed 200 throughout, but **without an outage that proves nothing.**

**Recommendation:** record #373's signed-in behavior as covered by Codex's HTTP rehearsal (36 samples,
me and tasks at 200 during a real outage) rather than spending more stack time on it. Then remove this stack.


## Coverage

Phone layout and RU/UZ inside the app were not covered. No production access, AI verification, or human acceptance is claimed.
