# Hip Exo Data Analyzer (v1.0)

## Overview
This application provides a complete workflow for analyzing hip exoskeleton CSV data:
1. Interactive signal visualization (angles, velocities, torques, PD, power).
2. Gait cycle extraction and comparison across tags or subjects.
3. Streaming filter + delay alignment for raw torque.
4. Batch reporting for all files/tags with CSV export.

System Requirements
1. Python 3.8+.
2. Packages: `PyQt5`, `matplotlib`, `pandas`, `numpy`, `scipy`.

## 1. Quick Start
Install
1. Install dependencies with pip:
```bash
pip install pyqt5 matplotlib pandas numpy scipy
```
2. Or use the environment file:
```bash
conda env create -f environment.yaml
```

Run
```bash
python data_analyzer.py
```

## 2. Project Structure
1. `data_analyzer.py` — Main UI and Analyzer tab.
2. `pages/gait_cycle_page.py` — Gait cycle tab.
3. `pages/filter_delay_page.py` — Filter-Delay tab.
4. `pages/report_page.py` — Report tab.
5. `utils.py` — Shared utilities.
6. `data/` — Sample CSV data.
7. `output/` — Saved figures and reports (auto-created).

## 3.Data Setup
1. Place CSV files in a folder (default: `data/`).
2. Use `Data Folder` to point at any directory of CSVs.
3. Click `Refresh List`, select a file, then click `Load`.
4. If column names do not match, click `Column Mapping` and map required columns.
5. Mapping is stored in `.column_mapping.json` at project root.

## 4.Analyzer Tab (Main)
Purpose: interactive plotting for raw time-series signals.
Steps:
1. Select a file and tag.
2. Adjust Start/End or use Window + Pan to move a fixed time window.
3. Select curves (Angle, Velocity, Torque Cmd, Raw Torque, Filtered Torque, P-term, D-term, Power).
4. Use Velocity Scale to scale velocity for visualization.
5. Optional: enable low-pass for Velocity/P/D/Power and set cutoff/FS.
6. Click `Save PDF` to export figure to `./output/`.

Notes:
1. Power is computed as torque × velocity(rad/s).
2. Positive power ratio is energy-based: sum(pos) / sum(abs).
3. Global invert will invert all signals except power.

## 5.Gait Cycle Tab
Purpose: compute gait-cycle mean and band from angle peaks.
Modes:
1. Inter-motion compare(Compare tags within one file.)
2. Inter-subject compare(Compare files for one tag.)

Steps:
1. Select file(s) and tag(s).
2. Choose leg, samples, band type.
3. Set min/max cycle duration and peak prominence.
4. Click `Plot Gait Cycles`.
5. Save figure with `Save PDF`.

## 6. Filter-Delay Tab
Purpose: streaming low-pass on raw torque, delay alignment, compare with command torque.
Steps:
1. Select file, tag, and leg.
2. Set time window (default 10s) and pan.
3. Set cutoff, order, and delay (ms).
4. View filtered+delayed raw torque vs command torque.
5. Power stats show positive/negative sums, energy ratio, manual delay, and filter delay.

Report Tab
Purpose: compute summary metrics for all CSV files and selected tags.
Steps:
1. Select tags (multi-select).
2. Enter output name.
3. Click `Generate + Save CSV`.
4. Files saved to:
   - `./output/<name>.csv`
   - `./output/<name>_avg.csv`

## 7.Report Metrics
1. RMS torque.
2. Torque range (min/max).
3. Angle range (min/max).
4. Peak angle.
5. Velocity range (min/max).
6. Peak velocity.
7. Mean positive power.
8. Mean negative power.
9. Positive power ratio (energy ratio).
