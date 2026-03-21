# Contributing Guide

## Git Workflow

### Branch Strategy
- **`main`**: Stable, working version. Never push directly.
- **`feature/<name>`**: New features (e.g., `feature/add-emg-tab`)
- **`fix/<name>`**: Bug fixes (e.g., `fix/gait-cycle-crash`)
- **`docs/<name>`**: Documentation updates

### Workflow
1. Pull latest `main`
2. Create a feature/fix branch
3. Make changes, test locally (`python data_analyzer_main.py`)
4. Push branch and open a Pull Request
5. At least one reviewer approves before merging
6. Squash merge into `main`

### Commit Messages
Use clear, descriptive messages:
```
add: gait cycle export to CSV
fix: crash when loading CSV without tag column
update: increase default filter order to 4
docs: add EMG data format specification
```

## Code Organization

```
data_analyzer_main.py      # Main window, Analyzer tab, entry point
src/
  utils.py            # Shared utilities (filters, gait detection, I/O)
  pages/
    explorer_page.py  # Generic CSV explorer (browse, plot, tag, transform)
    gait_cycle_page.py
    filter_delay_page.py
    report_page.py
```

### Adding a New Tab
1. Create `src/pages/your_page.py` with a class extending `QtWidgets.QWidget`
2. Import and add the tab in `data_analyzer_main.py` (search for `addTab`)
3. Use the same pattern as existing pages: accept `load_csv_func` and `get_bundles_func` callbacks
4. Add documentation in `docs/`

### Code Style
- Python 3.8+ compatible
- Use `snake_case` for functions and variables
- Use `CamelCase` for classes
- Keep each page module self-contained (own UI + logic)
- Shared signal processing goes in `src/utils.py`

## Testing

Before submitting a PR, verify:
1. App launches without errors: `python data_analyzer_main.py`
2. All 5 tabs load correctly (Explorer, Analyzer, Gait Cycle, Filter-Delay, Report)
3. Load at least one sample CSV and confirm plots render
4. If you changed signal processing, test with multiple datasets

## Updating Documentation

When you add or change functionality:
1. Update `docs/CHANGELOG.md` under an `[Unreleased]` section
2. If you add a new data column, update `docs/DATA_FORMAT.md`
3. If you change plotting behavior, update `docs/PLOTTING_GUIDE.md`
