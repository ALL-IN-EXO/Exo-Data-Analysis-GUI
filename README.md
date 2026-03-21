# Hip Exo Data Analyzer

A PyQt5 desktop application for analyzing hip exoskeleton biomechanical data.
Interactive visualization of angles, velocities, torques, power, and gait cycles.

**Current Version: v1.1** (2026-03-20) | [Full Changelog](docs/CHANGELOG.md)

## Project Structure

```
Exo-Data-Analysis-GUI/
├── data_analyzer_main.py   # Main entry point (run this)
├── CLAUDE.md               # AI assistant guide (auto-loaded by Claude Code)
├── environment.yaml        # Conda environment specification
│
├── src/                    # Source code modules
│   ├── utils.py            # Signal processing utilities (filters, gait detection)
│   └── pages/              # GUI tab modules
│       ├── explorer_page.py       # Generic CSV explorer tab (v1.1)
│       ├── gait_cycle_page.py     # Gait cycle analysis tab
│       ├── filter_delay_page.py   # Filter-delay alignment tab
│       └── report_page.py         # Batch reporting tab
│
├── docs/                   # Documentation
│   ├── CHANGELOG.md        # Version history and updates
│   ├── CONTRIBUTING.md     # Collaboration guide (branching, PR, code style)
│   ├── PLOTTING_GUIDE.md   # Plotting conventions and best practices
│   └── DATA_FORMAT.md      # Data format specification and column mapping
│
├── scripts/                # Utility shell scripts and Git guide
│
├── data_output/            # All data and output in one place
│   ├── sample_data/        # Example CSV datasets
│   ├── debug_data/         # Debug/test datasets
│   └── output/             # Auto-generated figures and reports
```

## Data Format (Quick Reference)

Input: CSV files with biomechanical time-series data.

| Column | Required | Description |
|--------|----------|-------------|
| `Time_ms` | Yes | Timestamp (ms, seconds, or datetime) |
| `imu_LTx` | Yes | Left hip angle (deg) |
| `imu_RTx` | Yes | Right hip angle (deg) |
| `imu_Lvel` | Yes | Left hip angular velocity |
| `imu_Rvel` | Yes | Right hip angular velocity |
| `M1_torque_command` | No | Right motor torque command |
| `M2_torque_command` | No | Left motor torque command |
| `raw_LExoTorque` | No | Raw left actuator torque |
| `raw_RExoTorque` | No | Raw right actuator torque |
| `tag` | No | Motion type label (e.g., "walk", "run") |

Column names can vary across datasets. The app provides an interactive **Column Mapping** dialog that persists mappings in `.column_mapping.json`.

For full data format details, see [docs/DATA_FORMAT.md](docs/DATA_FORMAT.md).

## Quick Start

### Install
```bash
# Option A: pip
pip install pyqt5 matplotlib pandas numpy scipy

# Option B: conda
conda env create -f environment.yaml
```

### Run
```bash
python data_analyzer_main.py
```

### Basic Workflow
1. Set data folder and click **Refresh List**
2. Select a CSV file and click **Load**
3. If columns don't match, use **Column Mapping** to map them
4. Switch between tabs to analyze:
   - **Explorer** -- Generic CSV viewer: browse any CSV, select columns, explore with crosshair, tag data, apply transforms (v1.1)
   - **Analyzer** -- Interactive time-series plotting
   - **Gait Cycle** -- Normalized gait cycle comparison
   - **Filter-Delay** -- Raw torque filtering and delay alignment
   - **Report** -- Batch summary metrics with CSV export
5. Use **View** menu to switch Dark/Light theme and font size

## Documentation

| Document | Description |
|----------|-------------|
| [CHANGELOG](docs/CHANGELOG.md) | Version history and release notes |
| [CONTRIBUTING](docs/CONTRIBUTING.md) | How to collaborate: branching, PRs, code style |
| [PLOTTING_GUIDE](docs/PLOTTING_GUIDE.md) | Plotting conventions, colors, axes, units |
| [DATA_FORMAT](docs/DATA_FORMAT.md) | Data format spec, column mapping, adding new data sources |
