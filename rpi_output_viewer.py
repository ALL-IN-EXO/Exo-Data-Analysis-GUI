#!/usr/bin/env python3
"""
Interactive viewer for RPi_Unified output CSV logs.

Features:
- Auto open latest CSV from ./output if no file is specified
- Drag on overview axis to choose time range
- Visualize angle, speed, torque, and power
- Show basic statistics for selected time window
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from typing import Optional

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.widgets import Button, Slider


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RPi output CSV viewer")
    parser.add_argument(
        "csv_path",
        nargs="?",
        default=None,
        help="CSV file path. If omitted, open file picker dialog",
    )
    parser.add_argument(
        "--torque-source",
        choices=["filtered", "raw", "actuator", "auto"],
        default="auto",
        help="Torque column source for torque/power plots (default: auto)",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Initial directory for file picker (default: auto-detect)",
    )
    return parser.parse_args()


def choose_latest_csv(base_dir: pathlib.Path) -> pathlib.Path:
    files = sorted(base_dir.glob("PI5_*.csv"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise FileNotFoundError(f"No PI5_*.csv found in: {base_dir}")
    return files[-1]


def detect_data_dirs(script_path: pathlib.Path) -> list[pathlib.Path]:
    script_dir = script_path.resolve().parent
    root_dir = script_dir.parent
    candidates = [
        script_dir / "pull_history" / "_mirror_output",
        script_dir / "mirror_output",
        root_dir / "data_pi" / "pull_history" / "_mirror_output",
        root_dir / "RPi_Unified" / "output",
        root_dir / "output",
    ]
    uniq: list[pathlib.Path] = []
    seen = set()
    for p in candidates:
        r = p.resolve()
        if str(r) in seen:
            continue
        seen.add(str(r))
        uniq.append(r)
    return uniq


def pick_csv_via_dialog(initial_dir: pathlib.Path) -> Optional[pathlib.Path]:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:
        return None

    try:
        root = tk.Tk()
        root.withdraw()
        selected = filedialog.askopenfilename(
            title="Select PI output CSV",
            initialdir=str(initial_dir),
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        root.destroy()
    except Exception:
        return None

    if not selected:
        return None
    return pathlib.Path(selected).expanduser().resolve()


def _pick_torque_columns(df: pd.DataFrame, source: str) -> tuple[str, str, str]:
    candidates = {
        "filtered": ("filtered_LExoTorque", "filtered_RExoTorque"),
        "raw": ("raw_LExoTorque", "raw_RExoTorque"),
        "actuator": ("L_command_actuator", "R_command_actuator"),
    }
    if source != "auto":
        l_col, r_col = candidates[source]
        if l_col not in df.columns or r_col not in df.columns:
            raise KeyError(f"Missing torque columns for source='{source}'")
        return l_col, r_col, source

    for src in ("filtered", "raw", "actuator"):
        l_col, r_col = candidates[src]
        if l_col in df.columns and r_col in df.columns:
            return l_col, r_col, src

    raise KeyError("No valid torque column pair found.")


class RPiOutputViewer:
    MAX_PLOT_POINTS = 3500

    def __init__(self, csv_path: pathlib.Path, torque_source: str):
        self.csv_path = csv_path
        self.df = pd.read_csv(csv_path)
        self._validate_columns()

        self.time_s, self.time_label = self._build_time_axis(self.df["Time_ms"])
        self.angle_l = pd.to_numeric(self.df["imu_LTx"], errors="coerce").to_numpy()
        self.angle_r = pd.to_numeric(self.df["imu_RTx"], errors="coerce").to_numpy()
        self.vel_l = pd.to_numeric(self.df["imu_Lvel"], errors="coerce").to_numpy()
        self.vel_r = pd.to_numeric(self.df["imu_Rvel"], errors="coerce").to_numpy()

        self.torque_l_col, self.torque_r_col, self.torque_source = _pick_torque_columns(
            self.df, torque_source
        )
        self.torque_l = pd.to_numeric(self.df[self.torque_l_col], errors="coerce").to_numpy()
        self.torque_r = pd.to_numeric(self.df[self.torque_r_col], errors="coerce").to_numpy()

        # Assume velocity is in deg/s, convert to rad/s for mechanical power in W.
        omega_l = np.deg2rad(self.vel_l)
        omega_r = np.deg2rad(self.vel_r)
        self.power_l = self.torque_l * omega_l
        self.power_r = self.torque_r * omega_r
        self.power_total = self.power_l + self.power_r

        self.t_lo = float(np.nanmin(self.time_s))
        self.t_hi = float(np.nanmax(self.time_s))
        self.duration = max(1e-9, self.t_hi - self.t_lo)
        self.window_len = min(10.0, self.duration)
        self.window_center = self.t_lo + self.window_len * 0.5
        self.t_min = self.t_lo
        self.t_max = self.t_lo + self.window_len

        self._window_patch = None

        self._create_figure()
        self._refresh_window()

    def _validate_columns(self) -> None:
        required = {"Time_ms", "imu_LTx", "imu_RTx", "imu_Lvel", "imu_Rvel"}
        missing = required - set(self.df.columns)
        if missing:
            raise KeyError(f"Missing required columns: {sorted(missing)}")

    @staticmethod
    def _build_time_axis(raw_time: pd.Series) -> tuple[np.ndarray, str]:
        t = pd.to_numeric(raw_time, errors="coerce").to_numpy()
        if np.isnan(t).all():
            raise ValueError("Time_ms column is not numeric.")
        t = t.astype(float)

        finite = t[np.isfinite(t)]
        if finite.size == 0:
            raise ValueError("No valid time values.")

        # Heuristic: if values look like real milliseconds, convert to seconds.
        if np.nanmax(finite) > 1e4:
            return t / 1000.0, "Time (s, converted from ms)"
        return t, "Time (s)"

    def _create_figure(self) -> None:
        self.fig = plt.figure(figsize=(16, 10))
        self.fig.suptitle(
            f"{self.csv_path.name} | torque={self.torque_source}",
            fontsize=12,
        )

        gs = self.fig.add_gridspec(
            5, 4,
            width_ratios=[3, 3, 3, 2],
            height_ratios=[0.8, 1, 1, 1, 1],
            hspace=0.25,
            wspace=0.25,
        )

        self.ax_nav = self.fig.add_subplot(gs[0, :3])
        self.ax_speed = self.fig.add_subplot(gs[1, :3])
        self.ax_angle = self.fig.add_subplot(gs[2, :3], sharex=self.ax_speed)
        self.ax_torque = self.fig.add_subplot(gs[3, :3], sharex=self.ax_speed)
        self.ax_power = self.fig.add_subplot(gs[4, :3], sharex=self.ax_speed)
        self.ax_stats = self.fig.add_subplot(gs[:, 3])
        self.ax_stats.axis("off")

        nav_step = max(1, int(np.ceil(len(self.time_s) / self.MAX_PLOT_POINTS)))
        self.ax_nav.plot(
            self.time_s[::nav_step],
            np.nan_to_num(np.abs(self.power_total[::nav_step]), nan=0.0),
            color="#7f7f7f",
            linewidth=1.0,
            label="|Total power| overview",
        )
        self.ax_nav.set_ylabel("|P|")
        self.ax_nav.set_xlabel(self.time_label)
        self.ax_nav.grid(alpha=0.25)
        self.ax_nav.legend(loc="upper right")

        self.line_speed_l, = self.ax_speed.plot([], [], color="#1f77b4", label="L speed")
        self.line_speed_r, = self.ax_speed.plot([], [], color="#ff7f0e", label="R speed")
        self.ax_speed.set_ylabel("Speed (deg/s)")
        self.ax_speed.grid(alpha=0.3)
        self.ax_speed.legend(loc="upper right")

        self.line_angle_l, = self.ax_angle.plot([], [], color="#1f77b4", label="L angle")
        self.line_angle_r, = self.ax_angle.plot([], [], color="#ff7f0e", label="R angle")
        self.ax_angle.set_ylabel("Angle (deg)")
        self.ax_angle.grid(alpha=0.3)
        self.ax_angle.legend(loc="upper right")

        self.line_torque_l, = self.ax_torque.plot([], [], color="#1f77b4", label="L torque")
        self.line_torque_r, = self.ax_torque.plot([], [], color="#ff7f0e", label="R torque")
        self.ax_torque.set_ylabel("Torque (Nm)")
        self.ax_torque.grid(alpha=0.3)
        self.ax_torque.legend(loc="upper right")

        self.line_power_l, = self.ax_power.plot([], [], color="#1f77b4", label="L power")
        self.line_power_r, = self.ax_power.plot([], [], color="#ff7f0e", label="R power")
        self.line_power_t, = self.ax_power.plot([], [], color="#2ca02c", linestyle="--", label="Total power")
        self.ax_power.set_ylabel("Power (W)")
        self.ax_power.set_xlabel(self.time_label)
        self.ax_power.grid(alpha=0.3)
        self.ax_power.legend(loc="upper right")

        self.stats_text = self.ax_stats.text(
            0.02,
            0.98,
            "",
            va="top",
            ha="left",
            family="monospace",
            fontsize=10,
            bbox={"boxstyle": "round", "facecolor": "#f5f5f5", "alpha": 0.95},
            transform=self.ax_stats.transAxes,
        )

        self.fig.text(0.10, 0.115, "Top controls: set window length and center", fontsize=9, color="#444444")

        len_max = max(self.duration, 1.0)
        len_min = max(0.1, min(0.2, len_max))
        len_init = max(len_min, min(self.window_len, len_max))

        center_ax = self.fig.add_axes([0.10, 0.055, 0.42, 0.025])
        len_ax = self.fig.add_axes([0.10, 0.020, 0.42, 0.025])
        btn_ax = self.fig.add_axes([0.54, 0.020, 0.09, 0.060])
        self.sld_center = Slider(center_ax, "Center(s)", self.t_lo, self.t_hi, valinit=self.window_center)
        self.sld_window = Slider(len_ax, "Window(s)", len_min, len_max, valinit=len_init)
        self.sld_center.on_changed(self._on_slider_change)
        self.sld_window.on_changed(self._on_slider_change)

        self.btn_reset = Button(btn_ax, "Full")
        self.btn_reset.on_clicked(self._on_reset)

    def _valid_mask(self) -> np.ndarray:
        mask = (self.time_s >= self.t_min) & (self.time_s <= self.t_max)
        return mask

    def _refresh_window(self) -> None:
        self.window_center = float(self.sld_center.val)
        self.window_len = float(self.sld_window.val)
        half = 0.5 * self.window_len

        t_min = self.window_center - half
        t_max = self.window_center + half

        if t_min < self.t_lo:
            t_max += (self.t_lo - t_min)
            t_min = self.t_lo
        if t_max > self.t_hi:
            t_min -= (t_max - self.t_hi)
            t_max = self.t_hi

        self.t_min = max(self.t_lo, t_min)
        self.t_max = min(self.t_hi, t_max)

        self._update_nav_patch()
        self._update_signal_lines()
        self._refresh_stats()
        self.fig.canvas.draw_idle()

    def _update_nav_patch(self) -> None:
        if self._window_patch is not None:
            self._window_patch.remove()
        self._window_patch = self.ax_nav.axvspan(self.t_min, self.t_max, alpha=0.2, color="#ffd54f")

    def _update_signal_lines(self) -> None:
        i0 = int(np.searchsorted(self.time_s, self.t_min, side="left"))
        i1 = int(np.searchsorted(self.time_s, self.t_max, side="right"))
        i1 = min(i1, len(self.time_s))

        if i1 - i0 < 2:
            for line in (
                self.line_speed_l, self.line_speed_r, self.line_angle_l, self.line_angle_r,
                self.line_torque_l, self.line_torque_r, self.line_power_l, self.line_power_r, self.line_power_t,
            ):
                line.set_data([], [])
            return

        count = i1 - i0
        step = max(1, int(np.ceil(count / self.MAX_PLOT_POINTS)))
        sl = slice(i0, i1, step)

        t = self.time_s[sl]
        self.line_speed_l.set_data(t, self.vel_l[sl])
        self.line_speed_r.set_data(t, self.vel_r[sl])
        self.line_angle_l.set_data(t, self.angle_l[sl])
        self.line_angle_r.set_data(t, self.angle_r[sl])
        self.line_torque_l.set_data(t, self.torque_l[sl])
        self.line_torque_r.set_data(t, self.torque_r[sl])
        self.line_power_l.set_data(t, self.power_l[sl])
        self.line_power_r.set_data(t, self.power_r[sl])
        self.line_power_t.set_data(t, self.power_total[sl])

        for ax in (self.ax_speed, self.ax_angle, self.ax_torque, self.ax_power):
            ax.relim()
            ax.autoscale_view()
            ax.set_xlim(self.t_min, self.t_max)

    def _refresh_stats(self) -> None:
        m = self._valid_mask()
        t = self.time_s[m]

        if t.size < 3:
            self.stats_text.set_text("Not enough points in selected range.")
            return

        dt = np.diff(t)
        dt = dt[np.isfinite(dt) & (dt > 0)]
        fs = (1.0 / np.median(dt)) if dt.size else float("nan")

        vel_l = self.vel_l[m]
        vel_r = self.vel_r[m]
        ang_l = self.angle_l[m]
        ang_r = self.angle_r[m]
        tau_l = self.torque_l[m]
        tau_r = self.torque_r[m]
        p_l = self.power_l[m]
        p_r = self.power_r[m]
        p_t = self.power_total[m]

        duration = float(t[-1] - t[0])
        try:
            integrate = np.trapezoid
        except AttributeError:
            integrate = np.trapz
        work_total = float(integrate(np.nan_to_num(p_t, nan=0.0), t))
        work_pos = float(integrate(np.clip(np.nan_to_num(p_t, nan=0.0), 0, None), t))
        work_neg = float(integrate(np.clip(np.nan_to_num(p_t, nan=0.0), None, 0), t))

        stats = (
            f"File: {self.csv_path.name}\n"
            f"Torque source: {self.torque_source}\n"
            f"Range: {self.t_min:.3f} - {self.t_max:.3f} s\n"
            f"Duration: {duration:.3f} s\n"
            f"Samples: {t.size}\n"
            f"Fs (est): {fs:.2f} Hz\n"
            "\n"
            "==== Speed (deg/s) ====\n"
            f"L mean abs: {np.nanmean(np.abs(vel_l)):.3f}\n"
            f"R mean abs: {np.nanmean(np.abs(vel_r)):.3f}\n"
            f"L peak abs: {np.nanmax(np.abs(vel_l)):.3f}\n"
            f"R peak abs: {np.nanmax(np.abs(vel_r)):.3f}\n"
            "\n"
            "==== Angle (deg) ====\n"
            f"L range: {np.nanmin(ang_l):.3f} .. {np.nanmax(ang_l):.3f}\n"
            f"R range: {np.nanmin(ang_r):.3f} .. {np.nanmax(ang_r):.3f}\n"
            "\n"
            "==== Torque (Nm) ====\n"
            f"L RMS: {np.sqrt(np.nanmean(np.square(tau_l))):.3f}\n"
            f"R RMS: {np.sqrt(np.nanmean(np.square(tau_r))):.3f}\n"
            f"L peak abs: {np.nanmax(np.abs(tau_l)):.3f}\n"
            f"R peak abs: {np.nanmax(np.abs(tau_r)):.3f}\n"
            "\n"
            "==== Power (W) ====\n"
            f"L mean: {np.nanmean(p_l):.3f}\n"
            f"R mean: {np.nanmean(p_r):.3f}\n"
            f"Total mean: {np.nanmean(p_t):.3f}\n"
            f"Total peak abs: {np.nanmax(np.abs(p_t)):.3f}\n"
            f"Work total: {work_total:.3f} J\n"
            f"Work +: {work_pos:.3f} J\n"
            f"Work -: {work_neg:.3f} J\n"
        )
        self.stats_text.set_text(stats)

    def _on_slider_change(self, _val) -> None:
        self._refresh_window()

    def _on_reset(self, _event) -> None:
        self.sld_window.set_val(self.duration)
        self.sld_center.set_val((self.t_lo + self.t_hi) * 0.5)

    def show(self) -> None:
        plt.show()


def main() -> int:
    args = parse_args()
    script_path = pathlib.Path(__file__)
    candidates = detect_data_dirs(script_path)
    preferred_dir = (
        pathlib.Path(args.data_dir).expanduser().resolve()
        if args.data_dir
        else next((p for p in candidates if p.is_dir()), candidates[0])
    )

    if args.csv_path is not None:
        csv_path = pathlib.Path(args.csv_path).expanduser().resolve()
    else:
        picked = pick_csv_via_dialog(preferred_dir)
        if picked is None:
            print("No file selected.")
            return 1
        csv_path = picked

    if not csv_path.exists():
        print(f"CSV not found: {csv_path}")
        return 1

    viewer = RPiOutputViewer(csv_path=csv_path, torque_source=args.torque_source)
    viewer.show()
    return 0


if __name__ == "__main__":
    sys.exit(main())
