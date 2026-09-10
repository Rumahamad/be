$ErrorActionPreference = "Stop"
$backendRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $backendRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    Write-Error "Backend virtual environment was not found: $pythonPath"
    exit 2
}

Push-Location $backendRoot
try {
    & $pythonPath "scripts\process_all_jobs.py"
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
