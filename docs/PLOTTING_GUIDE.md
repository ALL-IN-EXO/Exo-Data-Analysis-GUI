# Plotting Guide

## Color Scheme

The application uses a consistent color palette across all tabs:

| Signal | Color | Hex |
|--------|-------|-----|
| Left Angle | Blue | `#1f77b4` |
| Right Angle | Orange | `#e66100` |
| Left Velocity | Green | `#2ca02c` |
| Right Velocity | Red | `#d62728` |
| Left Torque Command | Deep Blue | `#084594` |
| Right Torque Command | Deep Red | `#7f0000` |
| Left Raw / Filtered Torque | Light/Deep Blue | `#6baed6` / `#08519c` |
| Right Raw / Filtered Torque | Light/Deep Red | `#fb6a4a` / `#cb181d` |
| Left P/D terms | Green family | `#31a354` / `#74c476` |
| Right P/D terms | Orange family | `#f16913` / `#fdae6b` |
| Power fill (positive/negative) | Green / Red | `#66bb6a` / `#ef5350` |

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
- Legend: place outside plotting area when many curves are shown (e.g., `bbox_to_anchor=(1.01, 1.0)` with a reserved right margin)

### Gait Cycle Plots
- X-axis always normalized to 0-100%
- Mean line: solid, linewidth=2
- Band fill: semi-transparent (alpha=0.2-0.3)
- Left/right leg: use consistent color mapping (left=blue tones, right=red/orange tones)

### Filter-Delay Plots
- Raw signal: lighter/thinner line
- Filtered signal: darker/thicker line
- Command signal: dashed, high-contrast color against filtered signal
- Positive power: shaded green region
- Negative power: shaded red region

## Best Practices for New Plots

1. **Always label axes with units** -- a plot without units is incomplete
2. **Use consistent colors** -- same signal should be the same color everywhere
3. **Title format**: `<Subject/File> - <Tag> - <What is shown>`
4. **Keep it readable** -- limit to 6-8 curves per subplot; split into subplots if needed
5. **Export quality** -- use 300 DPI, vector format (PDF) preferred over raster
6. **Accessibility** -- avoid red-green only distinctions; consider colorblind-friendly palettes for publications
