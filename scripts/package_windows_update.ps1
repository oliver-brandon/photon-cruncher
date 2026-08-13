$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$BuildScript = Join-Path $ProjectRoot "scripts\build_windows_app.ps1"
$VersionScript = Join-Path $ProjectRoot "scripts\version_metadata.py"
$PythonBin = if ($env:PYTHON_BIN) { $env:PYTHON_BIN } else { "python" }
$VpkBin = if ($env:VPK_BIN) { $env:VPK_BIN } else { "vpk" }
$OutputDir = if ($env:VELOPACK_OUTPUT_DIR) {
    $env:VELOPACK_OUTPUT_DIR
} else {
    Join-Path $ProjectRoot "dist\velopack-releases"
}
$StageDir = Join-Path $ProjectRoot "build\velopack\windows"
$ReleaseNotes = Join-Path $ProjectRoot "packaging\velopack\release-notes.md"
$IconPath = Join-Path $ProjectRoot "photon_cruncher\assets\icons\photon-cruncher.ico"

if ($env:VELOPACK_SKIP_BUILD -ne "1") {
    & $BuildScript
}

$Version = (& $PythonBin $VersionScript --field version).Trim()
$AppName = (& $PythonBin $VersionScript --field app_name).Trim()
$BundleAppName = (& $PythonBin $VersionScript --field bundle_app_name).Trim()
$PackageId = (& $PythonBin $VersionScript --field update_package_id).Trim()
$Channel = (& $PythonBin $VersionScript --field update_channel).Trim()
$Runtime = (& $PythonBin $VersionScript --field update_runtime).Trim()
$ExpectedChannel = "stable-$Runtime"

if ($Channel -ne $ExpectedChannel) {
    throw "Refusing unexpected update channel: $Channel"
}

$SourceDir = Join-Path $ProjectRoot "dist\$BundleAppName"
$SourceExe = Join-Path $SourceDir "$BundleAppName.exe"
if (-not (Test-Path $SourceExe)) {
    throw "PyInstaller executable not found: $SourceExe"
}

if (Test-Path $StageDir) {
    Remove-Item $StageDir -Recurse -Force
}
New-Item -ItemType Directory -Path $StageDir -Force | Out-Null
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
Copy-Item (Join-Path $SourceDir "*") $StageDir -Recurse -Force
Rename-Item (Join-Path $StageDir "$BundleAppName.exe") "$AppName.exe"

& $VpkBin pack `
    --outputDir $OutputDir `
    --channel $Channel `
    --runtime $Runtime `
    --packId $PackageId `
    --packVersion $Version `
    --packDir $StageDir `
    --mainExe "$AppName.exe" `
    --packTitle "$AppName" `
    --packAuthors "Brandon Oliver" `
    --releaseNotes $ReleaseNotes `
    --icon $IconPath

if ($LASTEXITCODE -ne 0) {
    throw "Velopack packaging failed with exit code $LASTEXITCODE"
}

$Feed = Join-Path $OutputDir "releases.$Channel.json"
$Setup = Get-ChildItem $OutputDir -Filter "*Setup*.exe" | Select-Object -First 1
$FullPackage = Get-ChildItem $OutputDir -Filter "*-full.nupkg" | Select-Object -First 1
if (-not (Test-Path $Feed) -or -not $Setup -or -not $FullPackage) {
    throw "Velopack did not create the installer, full update package, and feed."
}

Write-Host "Built stable update channel $Channel`:"
Write-Host "  Installer: $($Setup.FullName)"
Write-Host "  Full package: $($FullPackage.FullName)"
Write-Host "  Feed: $Feed"
