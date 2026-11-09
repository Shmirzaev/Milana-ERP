# Preserve the active previous ERP during HR readiness testing

Date: 9 November 2026. Status: AI_VERIFIED_AWAITING_HUMAN for the local transport
hardening. Old-ERP recent scan receipt remains unconfirmed; full physical
turnstile management is not ready. Local work only, no activation.

The owner explicitly requires the previous active ERP and its terminal connections
to remain operating throughout Milana testing. His supplied address is
`https://10.100.50.199:8443/uzerp/index.htm`. The earlier choice of a future sole
Milana writer remains conditional on an agreed handover; it authorizes no change
to the current writer, reader, credentials, terminal settings, profiles or rights.
The owner will add himself for the final supervised pilot, which remains deferred.

Base: `b71f8ac6bbcc1dd9d2d02d66d41b56600ea159cb`, worktree
`C:/ERP/.codex-work/hr-readiness-fixes-20261109`, branch
`codex/hr-readiness-fixes-20261109`. Fresh fetch still finds shared source
`14f6670de874f66eba3112281ab5a8dd4f388280`; both production release/manifests
still match recorded `20261109_035740` / `e5d56b822d8a48d327429a5e6a59cd87111b81bb193a2fd8cf120d007a7fafb1`.
No merge, push, deployment or connector activation is authorized.

People/connectors owner: Dilmurod. Human technical reviewer: Mirshoir, pending.
Implementation: Codex `/root`; independent AI reviewer: `/root/review_hr_scope`.
Operator/business acceptance remains unrecorded.

## Operation and acceptance contract

The attendance reader's public GET/search methods -> HTTPX transport or urllib
fallback -> configured pinned Hikvision HTTPS endpoint. No ERP write worker,
backend route, DTO, table, schema vocabulary, permission or frontend change.
Existing GET prefixes and the three search POST paths are retained.

Review identified two local transport-boundary gaps: search POSTs check only the
URL path, allowing an absolute foreign-origin URL with an allowed search path;
the urllib fallback inherits automatic redirect following. Neither was exploited
against physical devices or the previous ERP during testing. Regression tests
must fail on the baseline and prove that forbidden destinations/methods cannot
reach either transport, including through redirects. Valid pinned-origin reads,
search payloads and fallback behavior must continue working. Device failure must
continue to the other configured lanes and retain a failed task result.

Owned source: `read_only_connector.py`, a focused connector transport test file,
connector README and this record. State/configuration/credentials and the installed
scheduled reader are excluded. The four-file upgrade package is re-staged into a
new directory after verification; the prior candidate remains preserved.

Actual hardware checks permit bounded GETs for information, capabilities,
counts and deployment-session information, plus the existing allowlisted search
POSTs for a one-result compatibility check. No biometric image bytes or personal
fields are retained from the search samples. Session presence is an observation,
not proof that the old ERP receives scans or a guarantee it cannot disconnect
independently. No alarm-stream subscription, disconnect/deploy command, remote
door command, restart, certificate repin, event deletion, profile/photo change,
task change or ingestion upload is allowed in this continuation.

## Initial evidence and remaining inputs

The previous ERP's TCP port 8443 is reachable. Default verified HTTPS failed;
the already-authorized Edge browser reports `ERR_CERT_COMMON_NAME_INVALID`.
No warning was bypassed and no credentials were entered by the agent. The owner
then explicitly opened and signed in himself. Using that existing Edge session,
the agent inspected the real `dashboard.htm` and `users.htm` pages read-only.
The initial certificate problem is not relabeled as fixed, but does not block
reading that owner-opened session. Its visible menus did not expose a turnstile
attendance report; the agent asked the owner to open that report or identify its
menu. The final browser observation showed the login page again; no logout was
submitted and the cause is unknown. This does not establish a terminal connection
failure. Current scan receipt in the old ERP is still unconfirmed. Evidence: ignored
`outputs/hr-readiness/previous-erp-availability.json`. No Connect/Connect UHF,
save/import, user editing or device/settings action was submitted.

The preceding verified HR fix set and full-readiness limits remain in
[the task packet](../HR_READINESS_FIXES_20261109.md).

## Final local implementation and tests

The common `_approved_path` guard now validates both public methods and both
transport entry points before any I/O: configured HTTPS scheme/host/effective
port, no URL credentials/fragments, no dot/backslash/encoded path escapes, the
existing GET prefixes and exactly three search POST paths. It dispatches a
normalized same-origin path/query. HTTPX cannot override redirect refusal; the
urllib handler closes and rejects redirect responses, including same-origin
redirects. Digest challenges remain supported. No persistence or app contract
changed; HTTP method strings remain the existing external protocol vocabulary.

Evidence under ignored `outputs/hr-readiness/`:

| Check | Result / evidence |
| --- | --- |
| Final connector suite, fresh dependency-installed Windows environment | 136 passed, zero failures/errors/skips; `connector-preservation-tests.xml` |
| Validity challenge using exact b71f8ac6b source in an isolated output directory | The 87 final new tests produced 73 failures / 14 passes on the baseline; `transport-boundary-full-baseline-red.xml` and log. No repository source was reverted and all HTTP was synthetic |
| Initial red challenge | Earlier 48-test version produced 39 failures / 9 passes; retained separately |
| Independent AI run | Different agent ran all 87 new transport tests successfully and found no blocking source issue |
| Bounded local transport stress | 100 mixed attempts, 4 threads, 5-second completion limit: 50 valid GETs and 50 refused deployment/write commands; no forbidden request reached the in-memory transport |
| Linux backend / isolated PostgreSQL and disposable SQLite | Fresh 505 passed, zero failures/errors/skips; `backend-preservation-linux.xml`, 254.05 seconds |
| Frontend | Fresh full `npm run build -- --webpack`, strict TypeScript, scoped ESLint and seven HR/payroll/turnstile/attendance contract scripts passed; `frontend-preservation-build.log` |
| Production health | All four supported internal/public health/login checks plus internal readiness returned 200; backend release `20261109_035740`; `closing-health-erp-preservation.json` |

There are no frontend changes in this continuation. Prior 15 actual Edge
organization saves/reload/DB/audit checks remain evidence for the unchanged HR
page. The actual old-ERP session was inspected separately; this is not an old-ERP
turnstile-ingestion pass. The previous three PostgreSQL simulator stress scripts
also remain valid for the unchanged backend, not physical write support.

The first small health-check harness reused `status` for HTTP and application
status and failed its assertion; the harness was corrected to separate those
fields and all five checks passed. A first read-only production metadata lookup
targeted the stopped legacy `milana-backend` container; it was not started or
modified. The correct active `milana-backend-blue` was then queried in a read-only
transaction with a five-second statement timeout. These initial diagnostic
failures are not product-health failures or silently claimed passes.

## Physical connections and preservation evidence

Two snapshots (`previous-erp-terminal-sessions-before.json` and `...-after.json`)
each show all six configured pins and device-information/person-count/deployment
GETs passing, with 1,500 people on each lane. Lane 4's earlier 11:12–11:13 timeout
was no longer present at 12:10 or the closing recheck. No restart, network change
or certificate change was made to produce that recovery; intermittent behavior
remains worth observing. Do not report the earlier timeout as a current outage.

All six `/ISAPI/AccessControl/DeployInfo` responses had empty deployment-session
lists before and after. These lists neither prove disconnection nor establish
the old ERP's polling/delivery status. A signed-in dashboard only proves UI
availability; recent attendance rows or operator confirmation are still required.

`installed-reader-preservation-before.json` and `...-after.json` verify exact
unchanged hashes for installed configuration, DPAPI ciphertext file, reader
source, requirements and both wrappers, plus an unchanged scheduled-task
definition. Private file contents/hashes are not committed. At the closing
snapshot the task was Ready with result 0 from the 12:20:08 Tashkent run.
Existing task/state updates continued normally; no task was stopped or run
manually and no state/cursor was reset or edited by the agent.

Read-only production metadata confirms all six devices remain `read_only=true`
and `sync_enabled=true`, each reports 1,500 people, strict security is true and
provisioning mode is `disabled`. Latest ingestion checkpoints were 12:20:10–
12:20:16 Tashkent; these are successful poll/upload checkpoints, not proof of a
physical scan on every lane in that interval. See `production-reader-preservation.json`.

A one-result `UserInfo/Search` read on the designated profile lane returned a
same-host HTTPS URL under the approved photo prefix; no picture bytes, name,
number or exact personal URL was retained. A one-result `FDSearch` probe returned
HTTP 400 / `MessageParametersLack` on both the exact baseline and candidate.
This is preserved in `face-index-baseline-parity.json`, not called a pass or a
new hardening regression. The existing reader has an inline-profile URL fallback.
Full photo indexing/readback/enrollment compatibility remains part of the future
live integration and supervised pilot; this sample is not full photo acceptance.

The final four-file reader candidate is staged in
`outputs/hr-readiness/attendance-candidate-preserve-active-erp/` with its exact
SHA-256 manifest. The earlier staged candidate is retained. Neither package was
installed, activated or submitted to the old ERP. No deploy/disconnect command,
terminal write, remote-door action or production business-data write occurred.

## Remaining readiness gates

1. Open/identify the previous ERP's attendance report and verify recent arrivals
   while its current connection remains in service. Do not guess success from
   an empty deployment list or a working dashboard.
2. Implement and verify the real scoped Hikvision LAN write worker and reviewed
   occupied-profile adoption; simulator completion is not hardware support.
3. Approve access lanes/plans, validity and privacy/retention rules. Keep HR Save
   separate from explicit gate application and archive separate from revoke.
4. Complete the deferred supervised pilot with the owner's own profile, including
   real readback, passage, photo/edit/revoke and unknown/offline recovery, without
   changing another profile. Verify current face capacity and older firmware.
5. Integrate the exact patch with latest shared source and rerun combined QA.
   Release, reader activation and any sole-writer handover require separate owner
   authorization and the supported backup/rollback/deployment procedure. Until
   then, keep the previous ERP writer and current reader operating unchanged.

Human technical/visual acceptance remains pending. At handoff retain private
evidence, stop only owned local test services, report the local commit and keep
push/merge/deployment state explicit. No rollback of production is needed because
it was not changed; a future source revert cannot undo already written data.
