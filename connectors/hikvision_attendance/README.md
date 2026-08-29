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

On Windows, `setup_windows.ps1 -RegisterTask` creates a current-user scheduled
task and stores both passwords with Windows DPAPI. The plaintext secrets exist
only in the connector process environment while a sync is running.
