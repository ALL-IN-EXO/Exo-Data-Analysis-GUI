# CLAUDE.md - AI Assistant Guide

This file is automatically loaded by Claude Code at the start of every conversation.
It tells the AI where to find things and how to work in this project.

## Project Overview

Hip Exo Data Analyzer: a PyQt5 desktop GUI for analyzing hip exoskeleton biomechanical CSV data.
Main entry point: `data_analyzer_main.py`

## Project Structure

```
data_analyzer_main.py    # Main entry, Analyzer tab UI — run this
src/utils.py             # Shared signal processing (filters, gait detection, I/O)
src/pages/               # One file per GUI tab (gait_cycle, filter_delay, report)
data_output/             # All data (sample_data/, debug_data/) and output (output/)
docs/                    # All documentation (see below)
scripts/                 # Utility scripts + Git guide
```

## Key Documentation — Read These When Relevant

| When you need to... | Read this |
|---------------------|-----------|
| Understand data columns, CSV format, column mapping | `docs/DATA_FORMAT.md` |
| Follow plotting conventions (colors, axes, units) | `docs/PLOTTING_GUIDE.md` |
| Know Git workflow, branching, PR process | `docs/CONTRIBUTING.md` |
| Check version history and what changed | `docs/CHANGELOG.md` |

## Development Rules

1. **Never push directly to `main`** — always use a feature branch + PR
2. **One branch per task** — name it `feature/xxx`, `fix/xxx`, or `docs/xxx`
3. **After making code changes**, update `docs/CHANGELOG.md` under `[Unreleased]`
4. **New data columns** must be documented in `docs/DATA_FORMAT.md`
5. **New plots or visual changes** must follow `docs/PLOTTING_GUIDE.md`
6. **New tabs** go in `src/pages/` as a separate file, then register in `data_analyzer_main.py`
7. **Shared utilities** (filters, math, I/O) go in `src/utils.py`
8. **Output paths** use `data_output/output/` — never create output files elsewhere

## Common Commands

```bash
# Run the app
python data_analyzer_main.py

# Install dependencies
pip install pyqt5 matplotlib pandas numpy scipy
# or
conda env create -f environment.yaml
```

## Code Conventions

- Python 3.8+, snake_case functions, CamelCase classes
- PyQt5 for UI, matplotlib for plotting, pandas for data, scipy for signal processing
- Each page module is self-contained (own UI + logic)
- Column mapping persisted in `.column_mapping.json` (auto-generated, do not manually edit)
