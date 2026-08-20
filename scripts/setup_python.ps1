# CacheLikesFromTwitter Windows dependency setup.
# Code version: v1.0.0-codex.1

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "resolve_python.ps1")
$Python = $env:CACHELIKES_RESOLVED_PYTHON
$PythonArgs = if ($env:CACHELIKES_RESOLVED_PYTHON_ARGS) {
    $env:CACHELIKES_RESOLVED_PYTHON_ARGS -split ' '
} else {
    @()
}

Push-Location $ProjectRoot
try {
    Write-Host "Using Python: $Python $($PythonArgs -join ' ')"
    & $Python @PythonArgs -m pip install --upgrade pip
    & $Python @PythonArgs -m pip install -r (Join-Path $ProjectRoot "requirements-dev.txt")
    if ($env:CACHELIKES_SKIP_PLAYWRIGHT_INSTALL -ne "1") {
        & $Python @PythonArgs -m playwright install chromium
    }
    Write-Host "Environment is ready."
    Write-Host "Run tests with: .\scripts\test.ps1"
    Write-Host "Run the quality gate with: .\scripts\check.ps1"
    Write-Host "Run the app with: .\scripts\run_app.ps1"
} finally {
    Pop-Location
}
