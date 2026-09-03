$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot

Get-Content -LiteralPath ".env" | ForEach-Object {
    $line = $_.Trim()
    if ($line -match '^export\s+([A-Za-z_][A-Za-z0-9_]*)="(.*)"\s*$') {
        [Environment]::SetEnvironmentVariable($matches[1], $matches[2], "Process")
    }
}

& ".\.venv\Scripts\python.exe" "display.py" @args
