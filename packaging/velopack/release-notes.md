# Photon Cruncher 1.2.1

## Analysis correction

The 405 control fit now predicts the signal from the control before subtraction.
Previous stable versions fitted the reverse relationship and applied those
coefficients to the control. This correction can change z-scores and figures.
Reprocess recordings together with the same version/settings for comparisons;
do not mix older exports with newly processed results without validation.

## Fixes and improvements

- Prevents same-named recordings from overwriting one another in batch exports.
- Adds source, version, settings, and trial details in neighboring analysis JSON
  files; existing sidecars protect another recording's exports from replacement.
- Supports smoothing windows longer than the extracted trace.
- Rejects baseline windows containing fewer than two downsampled samples.
- Counts an artifact trial once even when both paired channels reject it.
- Saves batch figures as each recording is processed, reducing retained memory
  and avoiding a second load of every recording.
- Reports batch failures and skipped epocs instead of silently skipping errors.
- Ignores unused Cam1, Cam2, and Tick epocs in MAT and TDT inputs.
- Adds automated macOS and Windows regression tests for the stable branch.
