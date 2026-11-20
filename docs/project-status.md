# Photon Cruncher project status

The stable source on `main` uses the Aurora workspace. Published stable installers
and their version are listed on the [latest release](https://github.com/oliver-brandon/photon-cruncher/releases/latest).
The previous lab desktop line ended with [v1.2.1](https://github.com/oliver-brandon/photon-cruncher/releases/tag/v1.2.1).

The `dev` branch contains Aurora development releases with package ID
`com.photoncruncher.aurora.dev` and `aurora-dev-*` channels. The stable app
retains package ID `com.photoncruncher.app` and `stable-*` channels. The stable
installer name remains Photon Cruncher for continuity; the workspace is
Photon Cruncher Aurora.

## Scientific compatibility

Version 1.2.1 corrected 405 regression and warns against mixing earlier exports.
See [maintenance validation](maintenance-1.2.1.md) for the numerical change,
synthetic golden fixture, and historical MAT/TDT comparisons. Aurora provides
provenance sidecars and QC findings. Use consistent versions and settings for
comparisons and a fresh output folder when older exports have no sidecars.

## Release verification

Before announcing the stable release, confirm:

- Local regression, metadata and diff checks pass, including the frozen numeric
  fixture and meaningful recording comparisons where available.
- Hosted Windows and macOS regressions pass on the release commit.
- Windows and macOS builds and publication succeed from the matching `main`
  commit and `v*` tag. macOS must be Developer ID signed and notarized.
- Both installer assets, full and delta packages when applicable, and
  OS-specific stable feeds are present and identify the intended package and
  version. Windows installers are not Authenticode signed.
- On disposable Windows and macOS runners, install v1.2.1, apply the staged stable
  full package with its installed updater and check the restarted app. Exercise
  the packaged GUI and CLI with synthetic MAT/TDT inputs. The macOS check uses
  a user-writable copy of the installed app. These tests cover local apply and
  restart. Public feed discovery in an installed app, administrator prompts and
  the user's Dock are separate live checks.
- Exercise loading a MAT file and TDT block, analysis and export on each
  supported platform, using representative recordings with preserved source
  files. Never commit lab recordings.

Architecture and development entry points are in
[architecture-aurora.md](architecture-aurora.md). Current backend benchmark
methods are in [backend-performance.md](backend-performance.md).
