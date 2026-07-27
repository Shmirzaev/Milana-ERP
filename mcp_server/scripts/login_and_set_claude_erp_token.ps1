$ErrorActionPreference = "Stop"

function ConvertFrom-SecureStringPlainText {
    param([Parameter(Mandatory = $true)][securestring]$SecureString)

    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureString)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    } finally {
        if ($bstr -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
        }
    }
}

function Set-JsonProperty {
    param(
        [Parameter(Mandatory = $true)]$Object,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)]$Value
    )

    $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value -Force
}

function Read-ClaudeConfig {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (Test-Path -LiteralPath $Path) {
        $content = Get-Content -Raw -LiteralPath $Path
        if ($content.Trim()) {
            return $content | ConvertFrom-Json
        }
    }

    return [pscustomobject]@{}
}

function Write-ClaudeConfig {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Config,
        [Parameter(Mandatory = $true)][string]$Token
    )

    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $parent | Out-Null

    if ($null -eq $Config.mcpServers) {
        Set-JsonProperty -Object $Config -Name "mcpServers" -Value ([pscustomobject]@{})
    }

    if ($null -eq $Config.mcpServers."milana-erp") {
        $server = [pscustomobject]@{
            command = "C:\ERP\mcp_server\.venv\Scripts\python.exe"
            args = @("-m", "milana_erp_mcp.server")
            env = [pscustomobject]@{}
        }
        Set-JsonProperty -Object $Config.mcpServers -Name "milana-erp" -Value $server
    }

    if ($null -eq $Config.mcpServers."milana-erp".env) {
        Set-JsonProperty -Object $Config.mcpServers."milana-erp" -Name "env" -Value ([pscustomobject]@{})
    }

    $envConfig = $Config.mcpServers."milana-erp".env
    Set-JsonProperty -Object $envConfig -Name "ERP_API_BASE_URL" -Value "https://erp.milanapremium.uz"
    Set-JsonProperty -Object $envConfig -Name "ERP_MCP_BEARER_TOKEN" -Value $Token
    Set-JsonProperty -Object $envConfig -Name "ERP_MCP_REQUIRE_CONFIRMATION" -Value "true"

    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($Path, ($Config | ConvertTo-Json -Depth 80), $utf8NoBom)
}

Write-Host "Milana ERP -> Claude MCP token refresh"
Write-Host "Enter your ERP Super Admin credentials. The password will be hidden."

$email = Read-Host "ERP email"
$securePassword = Read-Host "ERP password" -AsSecureString
$password = ConvertFrom-SecureStringPlainText -SecureString $securePassword

if ([string]::IsNullOrWhiteSpace($email) -or [string]::IsNullOrWhiteSpace($password)) {
    throw "Email and password are required."
}

Write-Host "Requesting ERP token..."
$tokenResponse = Invoke-RestMethod `
    -Method Post `
    -Uri "https://erp.milanapremium.uz/api/auth/token" `
    -ContentType "application/x-www-form-urlencoded" `
    -Body @{ username = $email; password = $password }

$token = $tokenResponse.access_token
if ([string]::IsNullOrWhiteSpace($token)) {
    throw "ERP did not return an access_token."
}

Write-Host "Verifying token with ERP..."
$me = Invoke-RestMethod `
    -Method Get `
    -Uri "https://erp.milanapremium.uz/api/auth/me" `
    -Headers @{ Authorization = "Bearer $token" }

$paths = @(
    Join-Path $env:APPDATA "Claude\claude_desktop_config.json",
    Join-Path $env:LOCALAPPDATA "Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json"
)

foreach ($path in $paths) {
    $config = Read-ClaudeConfig -Path $path
    Write-ClaudeConfig -Path $path -Config $config -Token $token
}

Write-Host "Token verified and Claude config updated."
Write-Host ("Connected ERP user: {0} ({1})" -f $me.name, $me.role)

Write-Host "Restarting Claude Desktop..."
Get-Process | Where-Object { $_.ProcessName -match "Claude" } | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Start-Process "shell:AppsFolder\Claude_pzs8sxrjxfjjc!Claude"

Write-Host "Done. Open a new Claude Home chat and try erp_me again."
Read-Host "Press Enter to close"
