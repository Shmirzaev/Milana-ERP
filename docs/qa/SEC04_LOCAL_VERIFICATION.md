# SEC04 local verification — 2026-10-26

## Disposable target and commands

Run from this tooling worktree. Docker Compose and a clean SEC04 candidate worktree
of the same repository are required. The launcher accepts only the candidate source;
PostgreSQL, uploads, shared-store URL, project name and loopback port are fixed by
the local Compose file. The launcher rejects remote Docker endpoints. It creates
fresh credentials in ignored, mode-0600 files.
The backend image runs Alembic to head, then seeds roles and one admin. The fixture
adds one Modeling user, one model/image record and one 160 × 160 PNG in its own
Docker storage volume. No serving host's `/app/storage` is mounted.

```sh
python3 scripts/sec04_local_stack.py up --candidate /absolute/path/to/clean/sec04-worktree
python3 scripts/sec04_local_stack.py fixture
cd /absolute/path/to/clean/sec04-worktree/frontend
npm ci --legacy-peer-deps
API_URL=http://127.0.0.1:18080 npm run dev -- --hostname 127.0.0.1
```

From this tooling worktree after the frontend listens on `127.0.0.1:3000`:

```sh
cd frontend && npm ci --legacy-peer-deps && cd ..
python3 scripts/sec04_local_stack.py browser
python3 scripts/sec04_local_stack.py reset
python3 scripts/sec04_local_stack.py fixture
python3 scripts/sec04_local_stack.py stress
python3 scripts/sec04_local_stack.py down
```

`reset` and `down` accept no project name, database URL or storage path. They act
only on the random `milana-sec04-local-*` project recorded by this launcher and
remove its named volumes. Keep the candidate frontend running across reset;
the backend loopback address remains the same. Browser and stress artifacts go to
ignored `outputs/sec04-verification/` and contain no session token or password.

## Gate 4 workload and limits, recorded before execution

Reviewer for these sensitive-workflow limits: Mirshoir — **review pending**.
This measures local SEC04 behavior, not production capacity.

| Bound | Planned value |
| --- | --- |
| Target/data | Candidate backend on `127.0.0.1:18080`; one active user, model and 160 × 160 PNG; full-file and thumbnail GETs |
| Phases | Active cookie, revoke user in the same run, retained-cookie refusal, fresh active-admin recovery |
| Requests/concurrency | 80 GETs per phase, alternating routes; maximum 8 concurrent; 240 total plus smoke/login/ready checks |
| Duration/timeouts | Entire run ≤45 s; each request ≤5 s |
| Expected responses | Active and recovery: 200; after committed revocation: 401; zero unexpected 5xx, 429 or post-revocation 200 |
| Latency | p95 ≤2,500 ms and p99 ≤4,000 ms in each phase |
| Database/recovery | Peak PostgreSQL client connections ≤20; `/ready` returns 200 after load; revoked user stays inactive; one image record and file remain |
| Stop | Any unexpected status, timeout, failed data readback, connection/latency bound or total-duration bound fails the run |

## Verification record (§5)

Task / operation / state / direct-user scope and corrections: RF-004 Part B,
SEC04 local gate tooling and evidence; **Gate 3 FAIL, Gate 4 technical PASS;
SEC04 remains unverified**. This tooling PR does not change SEC04 runtime behavior.

Baseline / candidate commit or frozen patch+file hashes / runtime build / environment:
`clone_main` tooling base `b92ee8ff`; SEC04 candidate
`9c90ea806b3bd357a1307c68fd64a41f2259c012`, backend Docker image from that
commit, Alembic head `0148_second_grade_packages`, PostgreSQL 16, SQLite shared
store and isolated Docker storage volume, Next dev frontend, Chromium via Playwright.
The candidate worktree had only Next dev's generated `next-env.d.ts` type path edit.

Engineer / reviewer / business acceptance owner: Dilmurod / Mirshoir / Shavkat.

Implementation model/session / independent verification model/session: Codex
implementation and executed checks; independent Mirshoir review pending.

Expected behavior and unaffected control workflow: Active user reads the model
file and thumbnail; old cookie gets 401 after user revocation; fresh active admin
can still read both; unrelated signed sales attachments remain under existing tests.

Operation/caller coverage and table/field/type ledger: SEC04 model-file and
thumbnail routes; User.is_active, Model, ModelImage, isolated file and shared-store
session. No schema or business-vocabulary change.

Automated: `python3 -m py_compile scripts/sec04_local_stack.py
scripts/sec04_local_fixture.py scripts/sec04_local_stress.py`, pinned Ruff 0.14.9
on those scripts, `node --check frontend/scripts/sec04-live.browser.mjs`,
`npm run typecheck:strict`, and `git diff --check` PASS. `npm run lint` PASS with
10 warnings in unchanged frontend files. Local launch, fixture, readback, reset
and rejection of a `tcp://` Docker host PASS. No backend runtime code changed;
the isolated browser and HTTP checks below exercised the SEC04 candidate.
No production or serving host was contacted.

Test validity: Existing SEC04 fail-first API evidence is on its own branch;
local UI/load checks must run against the identified candidate source.

Visual E2E: **FAIL**. `python3 scripts/sec04_local_stack.py browser` in a fresh
stack, after `fixture`, logged in through the real UI and displayed the model
picture on `/models`. Direct file and thumbnail navigations initially returned
200 and rendered the yellow square on blue. After the script committed
`User.is_active = false`, the retained cookie was unchanged, but Chromium returned
**200 for both routes** and still rendered the pictures. Its network trace recorded
three cache-served requests. File responses advertise
`Cache-Control: private, max-age=86400`; thumbnails advertise
`private, max-age=604800`. The persisted readback showed inactive user, one image
record and the file present. I visually inspected the model-list, initial thumbnail,
revoked-file and revoked-thumbnail screenshots. Evidence:
[browser responses](sec04-evidence/results.json),
[model page](sec04-evidence/01-model-list.png),
[initial thumbnail](sec04-evidence/03-thumbnail.png),
[revoked file](sec04-evidence/04-revoked-file.png),
[revoked thumbnail](sec04-evidence/05-revoked-thumbnail.png).
SEC04 needs a runtime cache-policy correction and this same browser check rerun.

Stress: **technical PASS, reviewer limits pending**. On a separate fresh fixture,
`python3 scripts/sec04_local_stack.py stress` completed 240 requests in 2.58 s
with maximum 8 concurrent requests. Active: 80/80 200, p50/p95/p99
21.8/27.5/30.0 ms; after committed revocation: 80/80 401,
17.6/21.1/22.7 ms; fresh admin recovery: 80/80 200,
21.5/24.3/27.4 ms. Zero 5xx, timeouts and post-revocation 200s on direct HTTP.
Baseline PostgreSQL client connections: 2; sampled peak: 3 (10 ms sampling).
`/ready` returned 200 after load; inactive user, one image record and file were
read back. These measurements describe this single-instance local stack only.
[Full load evidence](sec04-evidence/stress.json).

Independent review findings / resolution / outstanding requirements: Mirshoir's
review of the recorded sensitive-workflow limits and evidence is pending. The
browser-cache exposure blocks SEC04 Gate 3 even though direct HTTP Gate 4 passes.

Human checklist: Log in as the isolated Modeling user, open SEC04 Verification
Model, check its picture, revoke that user, retry file and thumbnail with the
retained session, inspect 401 and the persisted inactive user.

Human technical and visual/business acceptance: PENDING; Gate 3 is FAIL.

Merge / deployment / production operator acceptance: None; no production data touched.

Cleanup/rollback condition and remaining limitations: `down` removes only this
local Compose project and its volumes. No general QA environment is claimed.
