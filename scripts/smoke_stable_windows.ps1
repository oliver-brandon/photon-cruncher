# Run only on a fresh GitHub-hosted Windows runner. Tests a real v1.2.1
# install and candidate package apply without publishing the candidate feed.
param(
    [Parameter(Mandatory = $true)][string]$CandidateDirectory,
    [Parameter(Mandatory = $true)][string]$CandidateVersion
)
$ErrorActionPreference = "Stop"
if ($env:GITHUB_ACTIONS -ne "true" -or -not $env:RUNNER_TEMP) {
    throw "Run this smoke check only on an ephemeral GitHub Actions runner."
}
$install = Join-Path $env:RUNNER_TEMP "photon-stable-upgrade"
$setup = Join-Path $env:RUNNER_TEMP "photon-v1.2.1-setup.exe"
if (Test-Path $install) { throw "Upgrade test installation path already exists." }
$feed = Get-Content (Join-Path $CandidateDirectory "releases.stable-win-x64.json") -Raw | ConvertFrom-Json
$assets = @($feed.Assets | Where-Object { $_.Version -eq $CandidateVersion -and $_.Type -eq "Full" -and $_.PackageId -eq "com.photoncruncher.app" })
if ($assets.Count -ne 1) { throw "Candidate feed does not contain exactly one stable full package." }
$CandidateDirectory = (Resolve-Path -LiteralPath $CandidateDirectory).Path
$package = Join-Path $CandidateDirectory $assets[0].FileName
if (-not (Test-Path $package)) { throw "Candidate package is missing." }
if ((Get-FileHash $package -Algorithm SHA256).Hash -ne $assets[0].SHA256) { throw "Candidate package hash mismatch." }
$uri = "https://github.com/oliver-brandon/photon-cruncher/releases/download/v1.2.1/Photon-Cruncher-v1.2.1-Windows.exe"
Invoke-WebRequest -Uri $uri -OutFile $setup
$proc = $null
$old = $null
$apply = $null
$restarted = $null
$reopened = $null
try {
    $proc = Start-Process -FilePath $setup -ArgumentList @("--silent", "--installto", ('"' + $install + '"')) -PassThru
    if (-not $proc.WaitForExit(180000)) { throw "Previous installer did not finish." }
    if ($proc.ExitCode -ne 0) { throw "Previous installer returned $($proc.ExitCode)." }
    $updater = Join-Path $install "Update.exe"
    $previous = Join-Path $install "current\Photon Cruncher.exe"
    if (-not (Test-Path $updater) -or -not (Test-Path $previous)) {
        throw "v1.2.1 installation does not contain expected updater and application."
    }
    function Assert-InstalledIdentity($version) {
        $manifestPath = Join-Path $install "current\sq.version"
        if (-not (Test-Path -LiteralPath $manifestPath)) { throw "Installed package manifest is missing." }
        [xml]$manifest = Get-Content -LiteralPath $manifestPath -Raw
        $idNode = $manifest.SelectSingleNode("//*[local-name()='metadata']/*[local-name()='id']")
        $versionNode = $manifest.SelectSingleNode("//*[local-name()='metadata']/*[local-name()='version']")
        if (-not $idNode -or -not $versionNode -or $idNode.InnerText -ne "com.photoncruncher.app" -or $versionNode.InnerText -ne $version) {
            throw "Installed package identity or version is incorrect: expected com.photoncruncher.app $version."
        }
    }
    Assert-InstalledIdentity "1.2.1"
    function Wait-ForWindow($process, $label) {
        $until = (Get-Date).AddSeconds(90)
        while ((Get-Date) -lt $until) {
            $process.Refresh()
            if ($process.HasExited) { throw "$label exited before opening a window." }
            if ($process.MainWindowHandle -ne 0 -and $process.MainWindowTitle -eq "Photon Cruncher v1.2.1") { return }
            Start-Sleep -Milliseconds 500
        }
        throw "$label did not open a window."
    }
    # Preserve and test the actual shortcut created for the previous stable install.
    $startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
    $shortcuts = @(Get-ChildItem -Path $startMenu -Filter "*.lnk" -Recurse -ErrorAction SilentlyContinue)
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $null
    foreach ($link in $shortcuts) {
        $resolved = $shell.CreateShortcut($link.FullName)
        if ($resolved.TargetPath -eq $previous -or $resolved.TargetPath -eq (Join-Path $install "Photon Cruncher.exe")) { $shortcut = $link.FullName; break }
    }
    if (-not $shortcut) { throw "v1.2.1 Start Menu shortcut not found." }
    $old = Start-Process -FilePath $previous -PassThru
    Wait-ForWindow $old "v1.2.1"
    # Exercise Velopack's real wait-for-app-exit and restart path.
    $apply = Start-Process -FilePath $updater -ArgumentList @("--silent", "apply", "--waitPid", $old.Id, "--package", ('"' + $package + '"')) -PassThru
    $old.CloseMainWindow() | Out-Null
    if (-not $old.WaitForExit(30000)) { throw "v1.2.1 did not close." }
    if (-not $apply.WaitForExit(180000)) { throw "Updater did not finish applying candidate." }
    if ($apply.ExitCode -ne 0) { throw "Updater returned $($apply.ExitCode)." }
    $expected = Join-Path $install "current\Photon Cruncher.exe"
    if (-not (Test-Path $expected)) { throw "Updated Aurora executable not found." }
    Assert-InstalledIdentity $CandidateVersion
    $until = (Get-Date).AddSeconds(90)
    $restarted = $null
    while ((Get-Date) -lt $until) {
        $restarted = Get-Process -Name "Photon Cruncher" -ErrorAction SilentlyContinue |
            Where-Object { $_.Path -eq $expected -and $_.MainWindowHandle -ne 0 -and $_.MainWindowTitle -eq "Photon Cruncher Aurora" } | Select-Object -First 1
        if ($restarted) { break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $restarted) { throw "Updated Aurora was not restarted into its main window." }
    $restarted.CloseMainWindow() | Out-Null
    if (-not $restarted.WaitForExit(30000)) { throw "Updated Aurora did not close." }
    if (-not (Test-Path $shortcut)) { throw "The original Start Menu shortcut disappeared." }
    $target = $shell.CreateShortcut($shortcut).TargetPath
    if (-not (Test-Path $target)) { throw "The original Start Menu shortcut no longer resolves." }
    Start-Process -FilePath $shortcut
    # Start-Process may return the execution stub, so locate the real application.
    $until = (Get-Date).AddSeconds(90)
    $reopened = $null
    while ((Get-Date) -lt $until) {
        $reopened = Get-Process -Name "Photon Cruncher" -ErrorAction SilentlyContinue |
            Where-Object { $_.Path -eq $expected -and $_.MainWindowHandle -ne 0 -and $_.MainWindowTitle -eq "Photon Cruncher Aurora" } | Select-Object -First 1
        if ($reopened) { break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $reopened) { throw "Original Start Menu shortcut failed to open Aurora." }
    $reopened.CloseMainWindow() | Out-Null
    if (-not $reopened.WaitForExit(30000)) { throw "Updated Aurora did not close." }
    Write-Host "Verified v1.2.1 startup, candidate apply, automatic restart, and original shortcut."
} finally {
    # Stop only processes whose executable is inside this run's test install.
    $owned = @(Get-Process -Name "Photon Cruncher", "Update" -ErrorAction SilentlyContinue | Where-Object {
        $_.Path -and $_.Path.StartsWith("$install\", [System.StringComparison]::OrdinalIgnoreCase)
    })
    foreach ($process in @($proc, $old, $apply, $restarted, $reopened) + $owned) {
        if ($null -ne $process) {
            try {
                $process.Refresh()
                if (-not $process.HasExited -and ($process.Path -eq $setup -or $process.Path.StartsWith("$install\", [System.StringComparison]::OrdinalIgnoreCase))) {
                    $process.Kill()
                    $process.WaitForExit(5000) | Out-Null
                }
            } catch { Write-Warning "Could not stop test process $($process.Id): $_" }
        }
    }
}
