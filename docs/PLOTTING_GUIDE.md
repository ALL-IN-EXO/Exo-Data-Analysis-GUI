# Plotting Guide

## Color Scheme

The application uses a consistent color palette across all tabs:

| Signal | Color | Hex |
|--------|-------|-----|
| Left Angle | Blue | `#1f77b4` |
| Right Angle | Orange | `#ff7f0e` |
| Left Velocity | Green | `#2ca02c` |
| Right Velocity | Red | `#d62728` |
| Torque Command | Purple | `#9467bd` |
| Raw Torque | Brown | `#8c564b` |
| Filtered Torque | Pink | `#e377c2` |
| P-term | Gray | `#7f7f7f` |
| D-term | Olive | `#bcbd22` |
| Power | Cyan | `#17becf` |

When adding new signals, pick colors that are visually distinct from existing ones. Avoid using the same color for signals that may appear on the same plot.

## Axes and Units

### Standard Axis Labels
| Quantity | Unit | Axis Label |
|----------|------|------------|
| Time | seconds | `Time (s)` |
| Angle | degrees | `Angle (deg)` |
| Angular Velocity | deg/s | `Velocity (deg/s)` |
| Torque | Nm | `Torque (Nm)` |
| Power | W | `Power (W)` |
| Gait Cycle Phase | % | `Gait Cycle (%)` |

### Multi-Axis Plotting
- The Analyzer tab uses up to 3 Y-axes per subplot (angle/velocity, torque, power)
- Additional Y-axes are offset using matplotlib spine positioning
- Always include axis labels with units to avoid ambiguity

## General Conventions

### Grid and Layout
- Grid lines: dashed style, alpha=0.4
- Figure DPI: 300 for export, screen default for interactive
- Legend: placed to avoid overlapping data; use `loc='best'` or manual positioning

### Gait Cycle Plots
- X-axis always normalized to 0-100%
- Mean line: solid, linewidth=2
- Band fill: semi-transparent (alpha=0.2-0.3)
- Left/right leg: use consistent color mapping (left=blue tones, right=red/orange tones)

### Filter-Delay Plots
- Raw signal: lighter/thinner line
- Filtered signal: darker/thicker line
- Positive power: shaded green region
- Negative power: shaded red region

## Best Practices for New Plots

1. **Always label axes with units** -- a plot without units is incomplete
2. **Use consistent colors** -- same signal should be the same color everywhere
3. **Title format**: `<Subject/File> - <Tag> - <What is shown>`
4. **Keep it readable** -- limit to 6-8 curves per subplot; split into subplots if needed
5. **Export quality** -- use 300 DPI, vector format (PDF) preferred over raster
6. **Accessibility** -- avoid red-green only distinctions; consider colorblind-friendly palettes for publications
