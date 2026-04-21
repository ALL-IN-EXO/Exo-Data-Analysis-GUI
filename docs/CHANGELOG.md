# Changelog

All notable changes to this project will be documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- **Explorer quick file switching** (`src/pages/explorer_page.py`)
  - Added a folder-level CSV list in Explorer for one-click switching between files in the same directory
  - Added folder refresh control and folder path display inside Explorer
- **Global file -> Explorer sync** (`data_analyzer_main.py`, `src/pages/explorer_page.py`)
  - Loading a file from the main Data panel now auto-loads the same file into Explorer
  - Main dataset selection now updates Explorer's folder list selection
- **Explorer one-click filename copy** (`src/pages/explorer_page.py`)
  - Added a `Copy Filename` button to copy the currently loaded file name to clipboard
- **Explorer cadence + speed-level estimate** (`src/pages/explorer_page.py`)
  - Added automatic cadence estimation for the selected span
  - Added speed-level labels based on cadence: 慢走 / 走路 / 快走 / 慢跑

### Changed
- **Analyzer/Filter-Delay/Gait Cycle control panel layout** (`data_analyzer_main.py`, `src/pages/filter_delay_page.py`, `src/pages/gait_cycle_page.py`)
  - Left controls now use a scroll container with a fixed minimum width to reduce control crowding on smaller Linux screens
- **Analyzer slider responsiveness** (`data_analyzer_main.py`)
  - Added debounced plot updates for time sliders/pan and related controls for smoother interaction during drag
- **Plot readability and legend placement** (`data_analyzer_main.py`, `src/pages/filter_delay_page.py`, `src/pages/gait_cycle_page.py`)
  - Improved line color contrast and line-style hierarchy (raw vs filtered vs command/terms)
  - Moved dense legends outward with reserved right margin to avoid clipping

### Fixed
- **Gait Cycle compare-mode state leakage** (`src/pages/gait_cycle_page.py`)
  - Mode switch now hides irrelevant controls and clears stale checklist selections from the previous mode
- **Missing feedback for failed multi-file tag compare** (`src/pages/gait_cycle_page.py`)
  - Added pre-checks for tag existence per file and explicit in-UI error messages instead of blank plots
- **Explorer file access regression** (`data_analyzer_main.py`)
  - Restored `Browse CSV` entry in Explorer so users can open files outside the current global data folder
- **Crash on files with NaN/Inf timestamps** (`data_analyzer_main.py`, `src/pages/explorer_page.py`, `src/pages/gait_split_page.py`, `src/pages/gait_cycle_page.py`, `src/pages/filter_delay_page.py`, `src/utils.py`)
  - Added robust time-axis sanitization (interpolate sparse invalid points, fallback to index when invalid)
  - Replaced fragile x-limits derived from raw `t[0]/t[-1]` with finite bounds handling in plot views

## [v1.2] - 2026-04-07

### Added
- **Gait Split Tab** (`src/pages/gait_split_page.py`): Detect, label, and analyze gait cycles from hip angle data

  **Layout** mirrors ExplorerPage: fixed left sidebar + overview strip + detail canvas.

  **Gait Cycle Detection**
  - Browse any CSV; auto-detects time column and canonical angle column names (`imu_LTx` / `imu_RTx`)
  - Yellow SpanSelector on overview strip — drag to select the time window for detection; detail canvas zooms to match
  - Choose detection leg: Left, Right, or Both (independent detection per leg)
  - Flexion-sign toggle: detect peaks (flexion = positive) or valleys (flexion = negative)
  - Configurable parameters: min/max cycle duration (s), peak prominence (deg)
  - Detection result: red onset dots on both overview and detail plots, alternating cycle shading
  - Results panel: peak count, cycle count, mean/std/min/max duration per leg

  **Export — Save CSV**
  - `Add 'gait_cycle' col`: appends `gait_cycle_L` and/or `gait_cycle_R` (1-based integer, NaN outside cycles)
    - Left leg selected → `gait_cycle_L`; Right → `gait_cycle_R`; Both → both columns, independently numbered
  - `Trim to yellow span`: keep only rows within the yellow SpanSelector region on the overview strip
  - Output filename: `<original>_gaitsplit.csv`

  **Power Calculation** (left sidebar — Power Calculation section)
  - Select velocity and torque columns independently for left and right leg
  - Auto-selects canonical names: `imu_Lvel` / `M2_torque_command`, `imu_Rvel` / `M1_torque_command`
  - Optional deg/s → rad/s conversion (π/180 scale), so output is in **Watts (Nm·rad/s)**
  - Optional velocity low-pass filter before power computation (configurable cutoff, default 6 Hz)
  - **Compute Power** button: adds `power_L` and/or `power_R` columns to the in-memory DataFrame (written on next Save CSV)

  **Plot Gait Profiles** (action bar button — opens interactive QDialog)
  - Layout adapts to detection results:
    - One leg detected → 1 column in that leg's color
    - Both legs detected → 2 columns (Left | Right) with independent cycle normalization
  - 4 rows: Angle (deg) / Velocity (deg/s) / Torque (Nm) / Power (W), each normalised to 0–100 % gait cycle; solid line = mean, shaded band = ±1 SD
  - Optional 5th row (torque components): enable via **"Torque Components (5th plot row)"** checkbox in sidebar
    - Select up to 3 signals: Residual (P/NN), Priority (D/vel), Cmd torque
    - Normalized by the detected leg's cycle boundaries (R preferred, L as fallback)
  - Figure shown immediately in a resizable dialog with NavigationToolbar; save via "Save as PDF / PNG…" button

  **Power Metrics** (action bar button)
  - Popup dialog with per-leg power metrics computed by global integration over all detected cycles:
    - ① Total work (J) and positive power ratio = W+ / (W+ + |W-|)
    - ② Active-phase mean instantaneous power when positive / negative (W), with % of samples shown
    - ③ Per-second average power delivery (W = J ÷ total time)
    - ④ Per-cycle average work (J/cycle = J ÷ number of cycles)
  - Note: ③ = ② × fraction-of-time (explained in dialog)
  - Requires "Compute Power" to have been run first

- **Explorer Tab — Single/Multiple view toggle** (`src/pages/explorer_page.py`)
  - Two buttons added to the action bar between overview and detail canvas: **Single** and **Multiple**
  - **Multiple** (default): each selected column in its own stacked subplot (original behavior)
  - **Single**: all selected columns overlaid on one shared axis with a legend; useful for comparing signals on the same scale

### Changed
- Gait Split: torque component combo labels renamed to **Residual (P/NN)** / **Priority (D/vel)** / **Cmd torque** to reflect controller terminology more accurately

## [v1.1] - 2026-03-20

### Added
- **Explorer Tab**: Generic CSV viewer for initial data exploration
  - Browse any CSV file, auto-detect time column and data types
  - Overview strip with interactive SpanSelector (drag/resize to select range)
  - Stacked detail subplots: one subplot per selected column, shared X-axis
  - Column checkboxes with type display and NaN count indicator (orange highlight)
  - Column search box: instant filter by name when columns are many
  - Crosshair cursor: hover to see linked vertical line + exact values across all subplots
  - Right-click context menu on columns/subplots:
    - Reorder: Move Up / Move Down (change subplot order without unchecking)
    - Transforms: Negate, Absolute Value, Offset, Scale, Derivative, Smooth
    - Reset to Original (non-destructive, original data always preserved)
  - Tagging system: view existing tags from any string column, write tags to any column (user-defined column name, no hardcoded "tag")
  - Statistics panel: scrollable, 13px monospace, mean/std/min/max + NaN count per column
  - Save as `_edited.csv` by default (never overwrites original)
- **Theme & Font Controls** (View menu):
  - Dark mode (Catppuccin Mocha palette) / Light mode toggle
  - Font size: Small (8px), Medium (10px), Large (13px, default), Extra Large (16px)
- **Screen Size Adaptation**: Window auto-sizes to 70% of screen (max 1200×750, min 600×400)

### Fixed
- CSV encoding crash: added latin-1 fallback for non-UTF-8 files (all tabs)
- macOS `._` hidden files no longer appear in dataset list
- Font "Segoe UI" → "Helvetica" for cross-platform compatibility

### Changed
- Project restructured: pages moved to `src/pages/`, utils to `src/utils.py`
- Data paths consolidated under `data_output/`
- Import paths updated across all modules

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
- `make_time_axis()` is duplicated in multiple files (to be consolidated)
