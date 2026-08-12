$repoRoot = $PSScriptRoot
$python = Join-Path $repoRoot ".build-venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    Write-Error @"
Photon Cruncher development Python was not found at:
  $python
Create the repository's .build-venv environment before running .\dev-aurora.ps1.
"@
    exit 1
}

$previousDevMode = $env:PHOTON_CRUNCHER_DEV
$auroraExitCode = 1
try {
    $env:PHOTON_CRUNCHER_DEV = "1"
    & $python -m photon_cruncher.aurora_main @args
    $auroraExitCode = $LASTEXITCODE
}
finally {
    if ($null -eq $previousDevMode) {
        Remove-Item Env:PHOTON_CRUNCHER_DEV -ErrorAction SilentlyContinue
    }
    else {
        $env:PHOTON_CRUNCHER_DEV = $previousDevMode
    }
}

exit $auroraExitCode
