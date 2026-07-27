$ErrorActionPreference = "Stop"

try {
    & (Join-Path $PSScriptRoot "login_and_set_claude_erp_token.ps1")
} catch {
    Write-Host ""
    Write-Host "Token refresh failed:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Nothing was changed unless the script said the token was verified and Claude config was updated."
    Read-Host "Press Enter to close"
    exit 1
}
