# #314 connected-browser results — 31 October 2026

Checker: Claude, using the Claude in Chrome extension in the user's real Chrome on macOS.
Target: http://localhost:58860, head 31eaf5da, factory MIL. Session ran 21:23–21:28 Asia/Seoul.

**Result: PASS on every check that was run. Phone layout was not checked** (see "Not covered").

## Tasks created

| Title | By | Priority | Due | Assignee |
| --- | --- | --- | --- | --- |
| CB314-A high self | API02 manager | High | 2026-11-20 | API02 manager |
| CB314-B low to recipient | API02 manager | Low | 2026-11-25 | API02 recipient |
| CB314-C restricted own | API02 denied | Medium | none | Myself |

No task was created by either blank-title attempt.

## Results

**1. Manager create, assign, Mine/All, Start/Done/Reopen: PASS**
- Both manager tasks were created with the right priority, date and assignee.
- **Mine** shows CB314-A and the shortage task. **All** also shows CB314-B under API02 recipient.
- CB314-A: Start → "in progress", then Done (struck through), then Reopen.
- Each state survived a full page reload and reopening the drawer. After Reopen the task shows Start again, so reopening returns it to new, not in progress.

**2. "API02 fixture shortage committed": PASS**
- Shows "Planning shortage" and HIGH, assigned to API02 manager.
- Start, Done and Reopen all worked and survived a reload.

**3. Blank title and dates: PASS (refused), with two wording notes**
- A spaces-only title was refused, and no task was added.
  - EN shows the raw backend text: "422: title: Value error, field must not be blank".
  - RU shows a translated generic message: "422: Проверьте обязательные поля и введённые значения."
  - Both keep the "422:" status prefix.
- Dates: the native date input rejects an impossible date (2026-02-31 becomes empty), so it can't be entered through the UI.

**4. Restricted role: PASS**
- The drawer reads "Your assigned tasks."
- No Mine/All tabs and no assignee selector.
- The manager-only shortage task is not visible.
- CB314-C was created as its own task, marked Done, and stayed Done after a reload.
- `GET /api/tasks?scope=all` from this session returned **403** {"detail":"Only managers can list all tasks"}.
- `GET /api/tasks` returned only "CB314-C restricted own".

**5. Languages**
- Desktop EN, RU and UZ: the drawer, tabs, form, priorities and buttons are translated, and the layout is intact.
- Small non-#314 notes:
  - The dashboard KPI line "Planning + confirmed + in production" stays English in RU and UZ.
  - Dates show as MM/DD/YYYY in all three languages.

## Side observations (outside #314)
- The restricted account's dashboard shows "Could not load active production. Please try again." instead of an access message, and still shows the "New Order" button.
- The greeting reads "Good morning" at 21:23 Seoul time.

## Not covered
- **Phone layout:** the Chrome window wouldn't resize (it's probably maximized), so only desktop was checked. The earlier standalone-Chromium phone evidence still stands.
- **Entity-reference fields and editing an existing task's date:** not exposed in this UI, as Codex noted.
- **Database readback:** Codex compares the persisted rows.
- Not marked verified or accepted.

Screenshots: pr314_manager_tasks_RU.jpg, pr314_manager_tasks_UZ.jpg, pr314_blank_title_refused_RU.png, pr314_restricted_tasks_EN.jpg.
