# Stable v1.2.1 Maintenance Validation

This release backports targeted reliability fixes to the existing PySide lab
app. The stable package remains `com.photoncruncher.app`, with the `stable-*`
updater channels. Aurora branding, UI, CLI, and dev updater identities are not
part of this release.

## Numerical Change

The linear fit now estimates `signal = slope * control + intercept`, then
subtracts that prediction from the signal. Previous stable versions estimated
the inverse relationship and applied its coefficients to the control.
Downsampling, Fortran-order trial flattening, trial alignment, baseline
normalization, and endpoint-shrinking smoothing conventions are preserved.

This changes scientific output. Reprocess comparison datasets consistently
with the same version and settings, preserving previous exports separately.
New `_analysis.json` sidecars identify the app version, source, settings,
pipeline, retained trial numbers, and removals. Older exports without these
sidecars cannot be identified by the overwrite guard; use a fresh output folder
for reprocessing.

## Checks

- The stable suite passes 53 tests, including new synthetic regression tests.
- Seven output arrays match the tracked synthetic golden fixture at
  `rtol=1e-12, atol=1e-12`.
- Adding a known linear 405 contribution plus an offset leaves the recovered
  z-score traces unchanged within `1e-10` tolerance.
- Four private MAT recordings, each with three channels, match the Aurora
  reference pipeline at `rtol=1e-10, atol=1e-10` using identical settings.
- Two corresponding MAT/TDT recordings have matching retained trials and
  processed z-scores within `1e-6`. Their epoc timestamps differ by at most
  about 1.069 microseconds due to input precision; this check also verifies
  stream shapes, samples, and sampling rates before comparing processed data.
- Qt integration tests exercise figure-only and CSV-plus-figure batch exports,
  one load per source, sidecar creation, and completion reporting.
- Memory tests verify completed batch records do not retain sessions or matrices.
- Tests also cover duplicate names, cross-source overwrite prevention,
  oversized smoothing, insufficient baseline samples, artifact counting,
  and ignored camera/clock epocs.

Private recordings remain under ignored `local-test-data/`. CI uses synthetic
data and skips private-fixture tests when those recordings are absent.
Interactive native UI automation was unavailable during this validation;
automated Qt integration checks passed.

## Release Checks

Require passing macOS and Windows regression jobs before dispatching the stable
publication workflow. Verify signed/notarized macOS output, both installers,
full/delta packages, and public feeds against the released source commit.
An installed-app update/restart smoke test is separate from these checks.
