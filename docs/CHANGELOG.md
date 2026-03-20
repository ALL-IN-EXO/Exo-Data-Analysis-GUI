# Changelog

All notable changes to this project will be documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [v1.0] - 2026-03-10

### Added
- **Analyzer Tab**: Interactive dual-leg signal visualization with multi-axis plotting
  - Signals: angle, velocity, torque command, raw/filtered torque, P-term, D-term, power
  - Time range selection with start/end spinboxes, sliders, and pan window
  - Tag/action filtering from CSV `tag` column
  - Global low-pass Butterworth filter (0.5-50 Hz, order 2)
  - Velocity scale adjustment (1-200x)
  - Signal inversion toggle
  - PDF export (300 dpi)
- **Gait Cycle Tab**: Normalized gait cycle extraction and comparison
  - Cycle detection from angle peaks (scipy.signal.find_peaks)
  - Normalization to configurable sample points (50-500, default 101)
  - Statistical bands: std, percentile (5-95), min-max
  - Inter-motion mode: compare tags within one file
  - Inter-subject mode: compare files for one tag
- **Filter-Delay Tab**: Streaming filter and delay alignment
  - Streaming Butterworth low-pass filter (configurable cutoff, order)
  - Temporal delay adjustment (-2000 to +2000 ms)
  - Group delay estimation
  - Power statistics: positive/negative sums, energy ratio
- **Report Tab**: Batch summary metrics
  - Per-file/tag metrics: RMS torque, torque/angle/velocity ranges, peak values, power stats
  - CSV export with per-file and averaged summaries
- **Column Mapping**: Interactive dialog for mapping dataset columns to expected names
  - Auto-detection of common synonyms
  - Persistent storage in `.column_mapping.json`
- **Sample Data**: 7 subject datasets included

### Known Issues
- `make_time_axis()` is duplicated in 3 files (to be consolidated)
