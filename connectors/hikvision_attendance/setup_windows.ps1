param(
    [string[]]$DeviceUrls = @(
        "https://10.100.50.73",
        "https://10.100.50.31",
        "https://10.100.50.91",
        "https://10.100.50.41",
        "https://10.100.50.115",
        "https://10.100.50.104"
    ),
    [string]$ErpUrl = "https://erp.milanapremium.uz",
    [switch]$RegisterTask
)

$ErrorActionPreference = "Stop"
$connectorDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $connectorDir ".venv\Scripts\python.exe"
$systemPython = (Get-Command python -ErrorAction Stop).Source
$configPath = Join-Path $connectorDir "config.json"
$secretPath = Join-Path $connectorDir "secrets.dpapi.json"

if (-not (Test-Path -LiteralPath $python)) {
    & $systemPython -m venv (Join-Path $connectorDir ".venv")
}
& $python -m pip install --disable-pip-version-check -r (Join-Path $connectorDir "requirements.txt")

$devices = @()
for ($index = 0; $index -lt $DeviceUrls.Count; $index++) {
    $uri = [Uri]$DeviceUrls[$index]
    $suffix = ($uri.Host -split '\.')[-1]
    $devices += @{
        hikvision_base_url = $DeviceUrls[$index]
        hikvision_cert_sha256 = "pending"
        device_key = "turnstile-$suffix"
        device_name = "Turnstile $($index + 1)"
        state_path = "state.turnstile-$suffix.json"
        sync_photos = ($suffix -eq "41")
    }
}
$bootstrap = @{
    erp_base_url = $ErpUrl
    initial_event_days = 30
    people_sync_hours = 24
    page_size = 30
    devices = $devices
}
$bootstrap | ConvertTo-Json | Set-Content -LiteralPath $configPath -Encoding UTF8
$fingerprintsJson = (& $python (Join-Path $connectorDir "read_only_connector.py") fingerprint --config $configPath).Trim()
$fingerprints = $fingerprintsJson | ConvertFrom-Json
Write-Host "Hikvision TLS certificate SHA-256 fingerprints:" -ForegroundColor Cyan
foreach ($fingerprint in $fingerprints) {
    Write-Host "$($fingerprint.device_key) $($fingerprint.hikvision_base_url) $($fingerprint.hikvision_cert_sha256)"
}
$confirmation = Read-Host "Confirm these are all six turnstiles by typing YES"
if ($confirmation -cne "YES") {
    throw "Certificates were not confirmed; setup stopped"
}
foreach ($device in $bootstrap.devices) {
    $match = $fingerprints | Where-Object { $_.device_key -eq $device.device_key }
    if ($null -eq $match) {
        throw "No certificate fingerprint was returned for $($device.device_key)"
    }
    $device.hikvision_cert_sha256 = [string]$match.hikvision_cert_sha256
}
$bootstrap | ConvertTo-Json | Set-Content -LiteralPath $configPath -Encoding UTF8

$username = Read-Host "Hikvision username (normally admin)"
$hikvisionPassword = Read-Host "Hikvision password" -AsSecureString
$erpTokenPlain = & $systemPython (Join-Path $connectorDir "get_saved_erp_token.py") 2>$null
if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($erpTokenPlain)) {
    $erpToken = ConvertTo-SecureString $erpTokenPlain -AsPlainText -Force
    $erpTokenPlain = $null
}
else {
    $erpToken = Read-Host "ERP attendance integration token" -AsSecureString
}
if ([string]::IsNullOrWhiteSpace($username)) {
    throw "Hikvision username is required"
}
$protected = @{
    hikvision_username = $username
    hikvision_password = ConvertFrom-SecureString $hikvisionPassword
    erp_token = ConvertFrom-SecureString $erpToken
}
$protected | ConvertTo-Json | Set-Content -LiteralPath $secretPath -Encoding UTF8

if ($RegisterTask) {
    $runner = Join-Path $connectorDir "run_scheduled.ps1"
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$runner`""
    $trigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(1)) -RepetitionInterval (New-TimeSpan -Minutes 1)
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 20)
    Register-ScheduledTask -TaskName "Milana Hikvision Attendance (Read Only)" -Action $action -Trigger $trigger -Settings $settings -Description "Read-only Hikvision attendance mirror for Milana ERP" -Force | Out-Null
}

Write-Host "Running the initial read-only import..." -ForegroundColor Cyan
& (Join-Path $connectorDir "run_scheduled.ps1") -Mode all
if ($LASTEXITCODE -ne 0) {
    throw "Initial attendance import failed"
}
Write-Host "Attendance connector setup completed." -ForegroundColor Green
