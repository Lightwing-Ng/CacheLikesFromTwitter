# CacheLikesFromTwitter Windows test entrypoint.
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
    & $Python @PythonArgs -m pytest @args
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
