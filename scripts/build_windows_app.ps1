$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$PythonBin = if ($env:PYTHON_BIN) { $env:PYTHON_BIN } else { "python" }
$VenvDir = Join-Path $ProjectRoot ".build-venv-windows"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$SpecFile = Join-Path $ProjectRoot "packaging\windows\PhotonCruncher.spec"
$DistDir = Join-Path $ProjectRoot "dist"
$AppName = "Photon Cruncher Aurora v2.0"
$AppDir = Join-Path $DistDir $AppName
$CliExe = Join-Path $DistDir "photon-cruncher-cli.exe"
$CliTarget = Join-Path $AppDir "photon-cruncher-cli.exe"
$ZipPath = Join-Path $DistDir "Photon-Cruncher-Aurora-v2.0-Windows.zip"

$RunningOnWindows = ($env:OS -eq "Windows_NT") -or ($PSVersionTable.Platform -eq "Win32NT")
if (-not $RunningOnWindows) {
    throw "This build script creates a Windows app bundle and must be run on Windows."
}

if (-not (Test-Path $VenvPython)) {
    & $PythonBin -m venv $VenvDir
}

& $VenvPython -m pip install --upgrade pip setuptools wheel
& $VenvPython -m pip install -e "$ProjectRoot\photon_cruncher[build]"
& $VenvPython -m pip install "PySide6-WebEngine>=6.6"
& $VenvPython -m PyInstaller `
    --clean `
    --noconfirm `
    --distpath $DistDir `
    --workpath (Join-Path $ProjectRoot "build\windows") `
    $SpecFile

if (Test-Path $ZipPath) {
    Remove-Item $ZipPath -Force
}

if (Test-Path $CliExe) {
    Copy-Item $CliExe $CliTarget -Force
}

Compress-Archive -Path $AppDir -DestinationPath $ZipPath -Force

Write-Host ""
Write-Host "Built Aurora app:"
Write-Host "  $AppDir"
Write-Host ""
Write-Host "Built command-line access point:"
Write-Host "  $CliTarget"
Write-Host ""
Write-Host "Built zip for GitHub/download sharing:"
Write-Host "  $ZipPath"
Write-Host ""
Write-Host "Unzip Photon-Cruncher-Aurora-v2.0-Windows.zip and double-click 'Photon Cruncher Aurora v2.0.exe'."
