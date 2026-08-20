# CacheLikesFromTwitter Python resolver.
# Code version: v1.0.0-codex.1

$ErrorActionPreference = "Stop"

function Test-SupportedPython([string]$Executable, [string[]]$Arguments = @()) {
    try {
        $version = & $Executable @Arguments -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        return $version -match '^3\.(13|14)$'
    } catch {
        return $false
    }
}

if ($env:CACHELIKES_PYTHON) {
    if (Test-SupportedPython $env:CACHELIKES_PYTHON) {
        $env:CACHELIKES_RESOLVED_PYTHON = $env:CACHELIKES_PYTHON
        return
    }
    throw "CACHELIKES_PYTHON must point to Python 3.13 or 3.14."
}

$python = Get-Command py -ErrorAction SilentlyContinue
if ($python -and (Test-SupportedPython $python.Source @("-3.13"))) {
    $env:CACHELIKES_RESOLVED_PYTHON = $python.Source
    $env:CACHELIKES_RESOLVED_PYTHON_ARGS = "-3.13"
    return
}

$python = Get-Command python -ErrorAction SilentlyContinue
if ($python -and (Test-SupportedPython $python.Source)) {
    $env:CACHELIKES_RESOLVED_PYTHON = $python.Source
    return
}

throw "Install Python 3.13 or 3.14, or set CACHELIKES_PYTHON to a supported interpreter."
