$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$PythonBin = if ($env:PYTHON_BIN) { $env:PYTHON_BIN } else { "python" }
$VenvDir = Join-Path $ProjectRoot ".build-venv-windows"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$SpecFile = Join-Path $ProjectRoot "packaging\windows\PhotonCruncher.spec"
$DistDir = Join-Path $ProjectRoot "dist"
$AppDir = Join-Path $DistDir "Photon Cruncher Dev v1.1.1"
$ZipPath = Join-Path $DistDir "Photon-Cruncher-Dev-v1.1.1-Windows.zip"

$RunningOnWindows = ($env:OS -eq "Windows_NT") -or ($PSVersionTable.Platform -eq "Win32NT")
if (-not $RunningOnWindows) {
    throw "This build script creates a Windows app bundle and must be run on Windows."
}

if (-not (Test-Path $VenvPython)) {
    & $PythonBin -m venv $VenvDir
}

& $VenvPython -m pip install --upgrade pip setuptools wheel
& $VenvPython -m pip install -e "$ProjectRoot\photon_cruncher[build]"
& $VenvPython -m PyInstaller `
    --clean `
    --noconfirm `
    --distpath $DistDir `
    --workpath (Join-Path $ProjectRoot "build\windows") `
    $SpecFile

if (Test-Path $ZipPath) {
    Remove-Item $ZipPath -Force
}

Compress-Archive -Path $AppDir -DestinationPath $ZipPath -Force

Write-Host ""
Write-Host "Built app:"
Write-Host "  $AppDir"
Write-Host ""
Write-Host "Built zip for GitHub/download sharing:"
Write-Host "  $ZipPath"
Write-Host ""
Write-Host "You can unzip Photon-Cruncher-Dev-v1.1.1-Windows.zip anywhere and double-click Photon Cruncher Dev v1.1.1.exe."
