param(
    [ValidateSet("scheduled", "people", "events", "all")]
    [string]$Mode = "scheduled"
)

$ErrorActionPreference = "Stop"
$connectorDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$secretPath = Join-Path $connectorDir "secrets.dpapi.json"
if (-not (Test-Path -LiteralPath $secretPath)) {
    throw "Run setup_windows.ps1 first"
}
$protected = Get-Content -LiteralPath $secretPath -Raw | ConvertFrom-Json
$hikvisionPassword = ConvertTo-SecureString $protected.hikvision_password
$erpToken = ConvertTo-SecureString $protected.erp_token
$env:HIKVISION_USERNAME = [string]$protected.hikvision_username
$env:HIKVISION_PASSWORD = [System.Net.NetworkCredential]::new("", $hikvisionPassword).Password
$env:ATTENDANCE_INTEGRATION_TOKEN = [System.Net.NetworkCredential]::new("", $erpToken).Password
try {
    & (Join-Path $connectorDir ".venv\Scripts\python.exe") (Join-Path $connectorDir "read_only_connector.py") $Mode --config (Join-Path $connectorDir "config.json")
    exit $LASTEXITCODE
}
finally {
    Remove-Item Env:HIKVISION_USERNAME -ErrorAction SilentlyContinue
    Remove-Item Env:HIKVISION_PASSWORD -ErrorAction SilentlyContinue
    Remove-Item Env:ATTENDANCE_INTEGRATION_TOKEN -ErrorAction SilentlyContinue
}

