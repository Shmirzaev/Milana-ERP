# Separate Hikvision management worker

Local candidate; factory activation and physical acceptance are pending. Keep the
existing attendance reader, its scheduled task, configuration, keys, pins, state
and previous ERP connection intact. This directory also contains the independent
read-only reader; its existing update allowlist excludes the writer modules.

The management worker submits only exact-person operations: observe, add, name
edit, face replacement, revoke, restore and delete. It has no door-control,
network-setting, deployment, subscription, disconnect or reboot commands.
Revoke retains the profile and credentials. Delete requires prior revocation,
one exact-person delete request, bounded completion reads and verified absence of
face/card/fingerprint credentials. HR/payroll/attendance/audit records remain.
Unavailable native readback is a refusal or unknown result, never a success.

## Prepare without activation

Stage into a **new** directory with `python stage_live_worker.py <new-directory>`.
The stager reads source only, refuses existing destinations, writes a SHA-256
manifest, and performs no device/ERP I/O. Keep this package outside the installed
reader directory. Create a separate Windows Python environment and install
`requirements-live.txt` from the reviewed package. Test-only synthetic HTTPS
checks additionally use pytest, cryptography and Pillow; these are not reader
or worker runtime dependencies.

Copy `live-config.example.json` to a private writer config only when the operator
is ready. Configure exact verified device keys, private HTTPS IPs and pins, a
dedicated per-device backend worker-token environment variable, and an explicit
employee-number allowlist for **both observation and writing**. The backend must
independently authorize the same employee and device. Device username/password
come only from `HIKVISION_USERNAME` / `HIKVISION_PASSWORD`; worker tokens must not
be reader-ingestion tokens. Do not store plaintext credentials in the config,
command line, logs, source control or this package. Use the operator's protected
secret-launch mechanism under a dedicated Windows account and clear process
environment secrets when it exits.

Protect the writer config, Python environment and journal directory with Windows
ACLs limited to that account and administrators. Journals use current-user DPAPI,
fsync and write-through replacement. Directory modes alone do not set Windows
ACLs. Keep the journal outside the reader and config directory. Preserve journals
through restarts and updates; they contain protected evidence required to avoid
repeating a possibly accepted write. Do not share the writer account.

No task is registered by this source. The explicit one-shot command is:

```powershell
.\.venv\Scripts\python.exe live_worker.py --config <private-writer-config>
```

This can observe but refuses mutations. Writing additionally requires the explicit
`--approve-device-writes` flag, local `writes_enabled=true`, backend live mode,
enabled per-device write policy, named approved access/validity rules and an
agreed handover reference. Keep all write gates off while the previous ERP is
the writer. A controlled supervised pilot needs an expressly agreed limited
handover scope; enabling two unrestricted writers is not supported.

## Recovery

The worker never retries a physical mutation or resumes a partially dispatched
sequence. On restart it reads pending journals and performs read-only recovery;
a saved final result may be resent exactly. A lost permit also requires review.
Never delete a journal to retry. The backend blocks further writes on a device
with an uncertain job, while allowing a fresh observation.

Only a quiescent failure with **zero dispatches** can use
`POST /api/turnstile-live/jobs/{id}/retry-unsent`, at most three claims. Its
immutable identity/policy/photo and previous results remain recorded. UI exposes
this action only for failed requests; the server rechecks every condition.

For unknown/dispatched work, the operator must stop and prove the former worker
cannot resume, review/remove its exact stale `worker.lock` if present, verify
the terminal operation has settled, then submit a fresh read-only observation.
An administrator can call `POST /api/turnstile-live/jobs/{id}/resolve` with
`worker_stopped_reference` and `observation_job_id`. This closes ambiguity as
needs-review/conflict, never converts an unknown delete into successful credential
removal. Review the resulting identity and baseline before another explicit
action. A blocked partial enrollment may need a reviewed face repair then a
separate Restore; no automatic compensation or identity recycling is allowed.

## Physical acceptance before deployment activation

Use the owner's reviewed employee number and approved access-plan/validity
reference. Verify each firmware's exact routes, new security flags, face upload
and independent byte readback, async deletion progress and credential searches.
Main device's existing-profile readback omitted `doubleLockRight`; new enrollment
currently requires explicit false for it and `localUIRight`. An omitted flag
is refused in the capability preflight before creating a profile. If a terminal
advertises the flag but omits or elevates it after creation, the profile stays
blocked and the result unknown. Do not weaken this check
without reviewed vendor evidence and regression coverage. JPEG recompression can
also prevent exact verification. FDLib Count and corrected root-level exact FPID
credential reads work on all six devices. All six return 404 for the native
deletion-progress endpoint; absent-test-identity credential queries returned 400
on the main device. Vendor-supported completion and absence verification remain
deletion compatibility gates; an HTTP error is never treated as credential absence.

During the supervised pilot verify actual passage, name/photo changes, revoke,
restore, delete, offline/unknown recovery, unchanged unrelated profiles and scan
arrival in **both** ERPs. Confirm previous ERP cannot recreate or overwrite the
pilot identity. Final handover, QA-master review, latest-source integration,
database backup/migration/rollback and deployment approval are separate gates.
