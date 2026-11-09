# Hikvision attendance connector

This LAN-side connector mirrors Hikvision people, face pictures, and access
events from one or more turnstiles into the isolated ERP attendance area. It is deliberately read-only on
the device side: only HTTP GET and Hikvision search POST endpoints are allowed.
It contains no person/card/face update, door-control, PUT, PATCH, or DELETE
operation.

The ERP backend cannot route to the device's `10.100.50.0/24` network, so run
this connector on an always-on Windows computer at the factory that can reach
both the turnstile and `https://erp.milanapremium.uz`.

Configuration secrets must be supplied through `HIKVISION_USERNAME`,
`HIKVISION_PASSWORD`, and `ATTENDANCE_INTEGRATION_TOKEN`. Do not put them in
`config.json` or source control. Pin the turnstile's self-signed TLS certificate
using a separate `hikvision_cert_sha256` for every configured device; the
connector stops that device's sync if its certificate changes. Other configured
turnstiles are still processed, and the scheduled run reports a failure so the
problem is visible.

Commands:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item config.example.json config.json
.\.venv\Scripts\python.exe read_only_connector.py fingerprint --config config.json
.\.venv\Scripts\python.exe read_only_connector.py all --config config.json
```

Use the `devices` array in `config.json` to give every turnstile a unique
`device_key`, name, URL, certificate fingerprint, and state file. The ERP keeps
raw events tied to their source device while the daily view merges people by
their Hikvision employee ID. Set `sync_photos` on one designated profile device
and disable it on replicated lanes to avoid downloading and storing the same
employee picture six times.

For routine operation, execute `scheduled` every minute. Events use a five-minute
overlap and ERP-side unique IDs, so retries are safe. Profiles and photos refresh
once every 24 hours.

Every roster and event upload includes a timezone-aware `source_snapshot_at`
captured by this connector before it reads the device. ERP uses that explicit
capture time to reject late older rosters and stale device metadata; it does not
depend on any undocumented Hikvision or Dahua sequence field. Event rows remain
append-only even when their accompanying metadata is stale. Once a device has
sent an explicitly versioned upload, unversioned roster uploads are acknowledged
but ignored so an older legacy payload cannot replace current presence state.

On Windows, `setup_windows.ps1 -RegisterTask` creates a current-user scheduled
task and stores both passwords with Windows DPAPI. The plaintext secrets exist
only in the connector process environment while a sync is running.

## Upgrade an existing Windows reader

Do not rerun initial setup over a working installation: it rebuilds configuration
and can change the existing `main-turnstile` key and per-device state filenames.
Those identities must stay unchanged to preserve attendance history and cursors.

Prepare a source-only update in a **new** directory, without accessing devices:

```powershell
python stage_update.py C:\MilanaUpdates\attendance-candidate
```

The staged files and their SHA-256 hashes are recorded in `UPDATE_MANIFEST.json`.
No configuration, credentials, photos, cursors or task wrapper is included. An
existing destination is refused, including the current installed directory.
`tzdata` is explicit because Windows needs the IANA database for Asia/Tashkent.

Activation is a separate authorized deployment, not part of preparing/testing the
package. The operator must first stop the scheduled reader and wait for any
running instance to finish. Back up the exact installed source and requirements,
plus its private configuration/state/DPAPI files in protected local storage.
Verify all package hashes, install its requirements into the existing dedicated
virtual environment, and replace only `read_only_connector.py`,
`run_scheduled.ps1`, `requirements.txt` and `README.md`.

Preserve `config.json`, every `state*.json`, `secrets.dpapi.json`, the hidden VBS
wrapper, the virtual-environment path and the scheduled task's identity/actions.
Do not reset cursors or perform a fresh 30-day import. From the installed reader
directory, run `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run_scheduled.ps1 -Mode events`
once under the scheduled task's Windows account (which owns the DPAPI secrets).
Check success and cursor progress for each lane, then
re-enable the existing task. Run/verify the next roster pass separately and
confirm versioned checkpoints in ERP. A changed certificate must still stop its
lane; never repin automatically. Keep the prior source for rollback, but after
versioned rosters begin ERP deliberately ignores older unversioned snapshots.

This package still reads attendance only. It cannot enroll or modify a person,
replace a terminal face credential, revoke access or operate a door.
