$ErrorActionPreference = "Continue"

$projectRoot = $PSScriptRoot
$logDir = Join-Path $projectRoot "tmp"
$logPath = Join-Path $logDir "quote0-burnout-scheduled.log"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Get-DotEnv {
    $envValues = @{}
    Get-Content -LiteralPath (Join-Path $projectRoot ".env") | ForEach-Object {
        $line = $_.Trim()
        if ($line -match '^export\s+([A-Za-z_][A-Za-z0-9_]*)="(.*)"\s*$') {
            $envValues[$matches[1]] = $matches[2]
        }
    }
    return $envValues
}

function Switch-NextContent {
    $envValues = Get-DotEnv
    $apiKey = $envValues["QUOTE0_API_KEY"]
    $deviceId = $envValues["QUOTE0_DEVICE_ID"]

    if (-not $apiKey -or -not $deviceId) {
        throw "QUOTE0_API_KEY or QUOTE0_DEVICE_ID is missing"
    }

    $headers = @{
        Authorization = "Bearer $apiKey"
        "Content-Type" = "application/json"
    }
    $uri = "https://dot.mindreset.tech/api/authV2/open/device/$deviceId/next"
    Invoke-RestMethod -Uri $uri -Headers $headers -Method Post | ConvertTo-Json -Depth 10
}

$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -LiteralPath $logPath -Value ""
Add-Content -LiteralPath $logPath -Value "[$stamp] start"

try {
    # Source env but force refreshNow=false for scheduled quiet updates
    $envVals = Get-DotEnv
    foreach ($kv in $envVals.GetEnumerator()) {
        [Environment]::SetEnvironmentVariable($kv.Key, $kv.Value, "Process")
    }
    $env:QUOTE0_REFRESH_NOW = "false"

    $python = Join-Path $projectRoot ".venv\Scripts\python.exe"
    $output = & $python (Join-Path $projectRoot "display.py") 2>&1 | Out-String
    $exitCode = $LASTEXITCODE
    Add-Content -LiteralPath $logPath -Value $output -Encoding UTF8
    if ($exitCode -eq 0) {
        $nextOutput = Switch-NextContent | Out-String
        Add-Content -LiteralPath $logPath -Value $nextOutput -Encoding UTF8
    }
    $end = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $logPath -Value "[$end] exit=$exitCode" -Encoding UTF8
    exit $exitCode
}
catch {
    $end = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $logPath -Value "[$end] error=$($_.Exception.Message)" -Encoding UTF8
    exit 1
}
