# #311 connected-browser results — 31 October 2026

Checker: Claude, using the Claude in Chrome extension in the user's real Chrome on macOS.
Target: frontend http://localhost:56426, backend http://localhost:56425, head ca6df656.
Account: sec04-viewer@example.com. Fixture: SEC04-VERIFY-001. Times are Asia/Seoul, with UTC in brackets.
Outage run: store down at 23:00:00, restored at 23:03:00. This was the re-armed run; the 22:30 run was
missed because the browser waited on a site-permission prompt.

**Result: readiness behaved as intended, the session survived, and Retry recovered without
reloading or logging in again.** The pre-existing `/api/auth/me` 500 during the outage was seen as expected.

## Timeline

| Time | Observation |
| --- | --- |
| 22:25:03 (13:25:03Z) | Baseline. The model list and View for SEC04-VERIFY-001 load, and the blue/yellow image is served from /storage/model-files. Screenshot: `pr311_2225_baseline_model_view.jpg` |
| 22:43:32 (13:43:32Z) | `/ready` 200 `{"postgresql":"ok","shared_store":"ok"}` (20 ms); `/health` 200 (5 ms) |
| 22:59:14 (13:59:14Z) | Models page loads normally |
| **23:00:00.8 (14:00:00.8Z)** | Probe log: first `/ready` **503** |
| 23:00:11 (14:00:11Z) | `/ready` **503** `{"status":"not_ready","checks":{"postgresql":"ok","shared_store":"unavailable"}}` (13 ms). `/health` **200** (8 ms) |
| 23:00:15 (14:00:15Z) | Models page refreshed. It shows "Unable to check your session. Check your connection and retry." with a **Retry** button. Not sent to login, not logged out. `/api/auth/me` **500** `{"detail":"Internal server error"}` (18 ms). Screenshot: `pr311_2300_outage_session_retry.jpg` |
| 23:01:17 (14:01:17Z) | Retry clicked during the outage: same message, still not logged out. `/ready` 503 (14 ms), `/health` 200 (13 ms) |
| **23:03:00.8 (14:03:00.8Z)** | Probe log: first `/ready` **200** again, under 1 s after the scheduled restore, with no app restart |
| 23:03:2x (14:03:2xZ) | Retry clicked once, with no reload and no re-login. The Models list returned with the model and its image, still signed in as SEC04 Viewer. Screenshot: `pr311_2303_after_retry_models.jpg` |
| 23:03:35 (14:03:35Z) | Opened View, then a full reload: "View: SEC04-VERIFY-001" with the model image loaded. Screenshot: `pr311_2303_reloaded_model_view.jpg` |

**Probe log** (`/ready` and `/health` every 2 s; 215 samples from 22:43:34 to 23:03:42):
- Only two transitions: 200→503 at 23:00:00.8, and 503→200 at 23:03:00.8.
- 90 samples fell in the outage. Every one answered: `/ready` within 25 ms, `/health` within 20 ms.
- `/health` was never anything other than 200.
- No probe hung or timed out.

## Findings

1. **#311 works as intended:**
   - `/ready` reports the store outage within 1 s and names the failing check.
   - It recovers on its own within 1 s of the restore.
   - `/health` stays up throughout.
2. **The user experience during the outage is reasonable.** The session screen offers Retry rather than a logout, and Retry fully recovers once the store is back. This is UI01 behaving correctly.
3. **Known and pre-existing:** `/api/auth/me` returns 500 during the outage, and every protected page is blocked until the store returns. This is the behavior question already with Mirshoir (refuse cleanly / keep working / mixed).

## Side observation
- The "viewer" account sees Create new model, Edit, Delete, Clone and Attach picture on the model pages. None were pressed, so whether the server refuses them was not tested.

## Not covered
- **Phone layout:** not checked, because the Chrome window wouldn't resize.
- **RU and UZ:** not checked. The outage screen has no language switcher, and time was spent on the timeline.
- No production access. Nothing is marked verified or accepted.
