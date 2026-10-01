# Photon Cruncher Aurora 2.0.6

- Keeps same-named recordings in separate batch export folders and protects
  existing exports belonging to another recording.
- Makes Trial Explorer plots and CSVs match the selected trials when channels
  lose different incomplete edge trials.
- Handles smoothing windows longer than the extracted trace without errors.
- Reports invalid baseline windows before exporting unusable results.
- Reduces memory retained during large batch exports.
- Limits saved heatmap tick labels to keep large figures readable and faster
  to export.
- Preserves CLI error details and distinguishes failed analyses from selections
  with no matching trials.
- Adds automated macOS and Windows regression checks and refreshes behavioral
  epoc benchmarks.
