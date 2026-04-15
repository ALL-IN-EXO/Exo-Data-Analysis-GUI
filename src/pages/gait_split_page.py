#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Gait Split Tab — Detect and label gait cycle boundaries from hip angle data.
Uses peak detection on hip flexion angle (left, right, or both) to identify
cycle onsets, then exports a labeled / trimmed CSV.

Layout mirrors ExplorerPage: fixed left sidebar + overview strip + detail canvas.
"""

import os

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from PyQt5 import QtWidgets
from PyQt5.QtCore import Qt

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure

try:
    from scipy.signal import find_peaks, butter, filtfilt
    _SCIPY = True
except ImportError:
    _SCIPY = False

try:
    from matplotlib.widgets import SpanSelector
except ImportError:
    SpanSelector = None

# ── colors (PLOTTING_GUIDE.md) ───────────────────────────────────────────────
_COLOR_LEFT  = "#1f77b4"   # blue
_COLOR_RIGHT = "#ff7f0e"   # orange
_COLOR_ONSET = "#d62728"   # red

_TIME_CANDIDATES = ["Time_ms", "time_ms", "time", "timestamp", "time_s", "elapsed"]
_LEFT_CANDIDATES  = ("imu_LTx", "left_angle", "L_angle", "hip_L")
_RIGHT_CANDIDATES = ("imu_RTx", "right_angle", "R_angle", "hip_R")


# ─────────────────────────────── helpers ────────────────────────────────────

def _sanitize_time_axis(t: np.ndarray) -> np.ndarray:
    t = np.asarray(t, dtype=float)
    if t.size == 0:
        return t
    finite = np.isfinite(t)
    if finite.sum() < 2:
        return np.arange(len(t), dtype=float)
    if not finite.all():
        idx = np.arange(len(t), dtype=float)
        t = t.copy()
        t[~finite] = np.interp(idx[~finite], idx[finite], t[finite])
    t0 = t[0] if np.isfinite(t[0]) else t[np.where(np.isfinite(t))[0][0]]
    t = t - t0
    if not np.all(np.isfinite(t)):
        return np.arange(len(t), dtype=float)
    return t


def _time_bounds(t: np.ndarray):
    t = np.asarray(t, dtype=float)
    finite = t[np.isfinite(t)]
    if finite.size < 2:
        return 0.0, 1.0
    t0, t1 = float(np.nanmin(finite)), float(np.nanmax(finite))
    if not np.isfinite(t0) or not np.isfinite(t1) or t1 <= t0:
        return 0.0, 1.0
    return t0, t1


def _make_time_axis(series: pd.Series) -> np.ndarray:
    t_num = pd.to_numeric(series, errors="coerce")
    if t_num.notna().mean() > 0.9:
        t = t_num.to_numpy(dtype=float)
        finite = np.isfinite(t)
        if finite.sum() < 2:
            return np.arange(len(series), dtype=float)
        t_valid = t[finite]
        diffs = np.diff(t_valid)
        diffs = diffs[np.isfinite(diffs)]
        dt = np.nanmedian(np.abs(diffs)) if len(diffs) > 0 else 10.0
        t0 = t_valid[0]
        return _sanitize_time_axis((t - t0) / 1000.0 if 1.0 <= dt <= 1000.0 else (t - t0))
    t_dt = pd.to_datetime(series, errors="coerce")
    if t_dt.notna().mean() > 0.9 and t_dt.notna().any():
        first_valid = t_dt[t_dt.notna()].iloc[0]
        return _sanitize_time_axis((t_dt - first_valid).dt.total_seconds().to_numpy(dtype=float))
    return np.arange(len(series), dtype=float)


def _load_csv(path: str) -> pd.DataFrame:
    """Load CSV with automatic latin-1 fallback — same approach as ExplorerPage."""
    try:
        return pd.read_csv(path)
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding="latin-1")


def _lowpass(x: np.ndarray, fs: float, fc: float = 6.0, order: int = 2) -> np.ndarray:
    if not _SCIPY or fs <= 0 or len(x) < 15:
        return x
    wn = fc / (fs / 2.0)
    if wn >= 1.0:
        return x
    b, a = butter(order, wn, btype="low")
    return filtfilt(b, a, x)


def _detect_peaks(angle: np.ndarray, fs: float,
                  min_cycle_sec: float,
                  max_cycle_sec: float,
                  prominence: float,
                  negate: bool) -> np.ndarray:
    """
    Return indices of gait-cycle onset peaks.

    Parameters
    ----------
    negate : bool
        True when flexion is NEGATIVE — negates signal so valleys become peaks.
    """
    if not _SCIPY:
        return np.array([], dtype=int)
    sig = -angle if negate else angle
    distance = max(1, int(min_cycle_sec * fs))
    peaks, _ = find_peaks(sig, distance=distance, prominence=prominence)
    return peaks


# ─────────────────────────────── widget ─────────────────────────────────────

class GaitSplitPage(QtWidgets.QWidget):
    """Tab for detecting and labeling gait cycle boundaries."""

    def __init__(self, data_dir_provider=None, mapping_path_provider=None):
        super().__init__()
        self.data_dir_provider = data_dir_provider
        self.df = None
        self.csv_path = None
        self.time_col = None
        self.t = None
        self.fs = 100.0
        self.peaks_L = np.array([], dtype=int)   # full-array indices, left leg
        self.peaks_R = np.array([], dtype=int)   # full-array indices, right leg
        self.peaks = np.array([], dtype=int)     # primary leg, used for display
        self._span = (0.0, 1.0)                  # (t_min, t_max) driven by SpanSelector
        self._span_selector = None
        self._build_ui()

    # ─────────────────────────────────────────── UI ──────────────────────────

    def _build_ui(self):
        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        # ── LEFT SIDEBAR — fixed-width QScrollArea so content never gets squashed ──
        _left_scroll = QtWidgets.QScrollArea()
        _left_scroll.setWidgetResizable(True)
        _left_scroll.setFixedWidth(260)
        _left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        _left_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        left = QtWidgets.QWidget()
        left.setObjectName("sectionPanel")
        lv = QtWidgets.QVBoxLayout(left)
        lv.setContentsMargins(6, 6, 6, 6)
        lv.setSpacing(6)

        # Browse
        browse_btn = QtWidgets.QPushButton("  Browse CSV...")
        browse_btn.clicked.connect(self._browse)
        lv.addWidget(browse_btn)

        self.file_label = QtWidgets.QLabel("No file loaded")
        self.file_label.setWordWrap(True)
        lv.addWidget(self.file_label)

        # File Info
        info_title = QtWidgets.QLabel("File Info")
        info_title.setObjectName("sectionTitle")
        lv.addWidget(info_title)
        self.info_label = QtWidgets.QLabel("")
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("font-size: 11px;")
        lv.addWidget(self.info_label)

        # Signal Settings
        sig_title = QtWidgets.QLabel("Signal Settings")
        sig_title.setObjectName("sectionTitle")
        lv.addWidget(sig_title)

        sig_form = QtWidgets.QFormLayout()
        sig_form.setHorizontalSpacing(6)
        sig_form.setVerticalSpacing(4)

        self.col_L_combo = QtWidgets.QComboBox()
        self.col_R_combo = QtWidgets.QComboBox()
        self.leg_combo = QtWidgets.QComboBox()
        self.leg_combo.addItems(["Left", "Right", "Both (Left primary)"])

        sig_form.addRow("Left angle:", self.col_L_combo)
        sig_form.addRow("Right angle:", self.col_R_combo)
        sig_form.addRow("Split using:", self.leg_combo)

        self.negate_check = QtWidgets.QCheckBox("Flexion is negative (detect valley)")
        self.negate_check.setToolTip(
            "Check when hip flexion produces NEGATIVE angle values.\n"
            "The algorithm will detect local minima instead of maxima."
        )

        lv.addLayout(sig_form)
        lv.addWidget(self.negate_check)

        # Detection
        det_title = QtWidgets.QLabel("Detection")
        det_title.setObjectName("sectionTitle")
        lv.addWidget(det_title)

        det_form = QtWidgets.QFormLayout()
        det_form.setHorizontalSpacing(6)
        det_form.setVerticalSpacing(4)

        self.min_cycle_spin = QtWidgets.QDoubleSpinBox()
        self.min_cycle_spin.setRange(0.1, 5.0)
        self.min_cycle_spin.setSingleStep(0.1)
        self.min_cycle_spin.setValue(0.6)
        self.min_cycle_spin.setDecimals(2)
        self.min_cycle_spin.setToolTip("Minimum gait cycle duration (seconds)")

        self.max_cycle_spin = QtWidgets.QDoubleSpinBox()
        self.max_cycle_spin.setRange(0.5, 10.0)
        self.max_cycle_spin.setSingleStep(0.1)
        self.max_cycle_spin.setValue(2.5)
        self.max_cycle_spin.setDecimals(2)
        self.max_cycle_spin.setToolTip("Maximum gait cycle duration (seconds)")

        self.prom_spin = QtWidgets.QDoubleSpinBox()
        self.prom_spin.setRange(0.1, 50.0)
        self.prom_spin.setSingleStep(0.5)
        self.prom_spin.setValue(3.0)
        self.prom_spin.setDecimals(1)
        self.prom_spin.setToolTip(
            "Required peak prominence (deg).\n"
            "Increase to suppress noise; decrease if cycles are missed."
        )

        det_form.addRow("Min cycle (s):", self.min_cycle_spin)
        det_form.addRow("Max cycle (s):", self.max_cycle_spin)
        det_form.addRow("Prominence (deg):", self.prom_spin)

        lv.addLayout(det_form)

        self.detect_btn = QtWidgets.QPushButton("Detect Cycles")
        lv.addWidget(self.detect_btn)

        # Results (scrollable, like Explorer's Statistics)
        res_title = QtWidgets.QLabel("Results")
        res_title.setObjectName("sectionTitle")
        lv.addWidget(res_title)

        res_scroll = QtWidgets.QScrollArea()
        res_scroll.setWidgetResizable(True)
        res_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        res_container = QtWidgets.QWidget()
        res_vlayout = QtWidgets.QVBoxLayout(res_container)
        res_vlayout.setContentsMargins(2, 2, 2, 2)
        res_vlayout.setSpacing(0)
        self.result_label = QtWidgets.QLabel("Load a file to begin.")
        self.result_label.setWordWrap(True)
        self.result_label.setStyleSheet("font-family: monospace; font-size: 12px;")
        self.result_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.result_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        res_vlayout.addWidget(self.result_label)
        res_vlayout.addStretch()
        res_scroll.setWidget(res_container)
        lv.addWidget(res_scroll, 1)

        # Power Calculation
        pwr_title = QtWidgets.QLabel("Power Calculation")
        pwr_title.setObjectName("sectionTitle")
        lv.addWidget(pwr_title)

        pwr_form = QtWidgets.QFormLayout()
        pwr_form.setHorizontalSpacing(6)
        pwr_form.setVerticalSpacing(4)

        self.vel_L_combo  = QtWidgets.QComboBox()
        self.tor_L_combo  = QtWidgets.QComboBox()
        self.vel_R_combo  = QtWidgets.QComboBox()
        self.tor_R_combo  = QtWidgets.QComboBox()

        pwr_form.addRow("L velocity:", self.vel_L_combo)
        pwr_form.addRow("L torque:",   self.tor_L_combo)
        pwr_form.addRow("R velocity:", self.vel_R_combo)
        pwr_form.addRow("R torque:",   self.tor_R_combo)
        lv.addLayout(pwr_form)

        self.deg2rad_check = QtWidgets.QCheckBox("Velocity in deg/s → convert to rad/s")
        self.deg2rad_check.setChecked(True)
        self.deg2rad_check.setToolTip(
            "Multiply velocity × π/180 before computing power,\n"
            "so the result is in Watts (Nm × rad/s)."
        )
        lv.addWidget(self.deg2rad_check)

        vel_filt_row = QtWidgets.QHBoxLayout()
        self.vel_filter_check = QtWidgets.QCheckBox("Filter velocity  fc=")
        self.vel_filter_check.setChecked(True)
        self.vel_filter_check.setToolTip(
            "Apply Butterworth low-pass to the velocity signal before\n"
            "computing power, to suppress high-frequency noise."
        )
        self.vel_cutoff_spin = QtWidgets.QDoubleSpinBox()
        self.vel_cutoff_spin.setRange(0.5, 50.0)
        self.vel_cutoff_spin.setSingleStep(0.5)
        self.vel_cutoff_spin.setValue(6.0)
        self.vel_cutoff_spin.setDecimals(1)
        self.vel_cutoff_spin.setSuffix(" Hz")
        self.vel_cutoff_spin.setFixedWidth(80)
        vel_filt_row.addWidget(self.vel_filter_check)
        vel_filt_row.addWidget(self.vel_cutoff_spin)
        vel_filt_row.addStretch()
        lv.addLayout(vel_filt_row)

        # Torque components for 5th subplot
        self.show_5th_check = QtWidgets.QCheckBox("Torque Components (5th plot row)")
        self.show_5th_check.setObjectName("sectionTitle")
        self.show_5th_check.setChecked(False)
        lv.addWidget(self.show_5th_check)

        tor_comp_form = QtWidgets.QFormLayout()
        tor_comp_form.setHorizontalSpacing(6)
        tor_comp_form.setVerticalSpacing(4)
        self.rp_combo   = QtWidgets.QComboBox()
        self.rd_combo   = QtWidgets.QComboBox()
        self.rcmd_combo = QtWidgets.QComboBox()
        tor_comp_form.addRow("Residual (P/NN):",  self.rp_combo)
        tor_comp_form.addRow("Priority (D/vel):", self.rd_combo)
        tor_comp_form.addRow("Cmd torque:",        self.rcmd_combo)
        lv.addLayout(tor_comp_form)

        self.compute_power_btn = QtWidgets.QPushButton("Compute Power")
        lv.addWidget(self.compute_power_btn)

        _left_scroll.setWidget(left)
        root.addWidget(_left_scroll)

        # ── RIGHT PANEL ───────────────────────────────────────────────────────
        right = QtWidgets.QVBoxLayout()
        right.setSpacing(0)
        right.setContentsMargins(0, 0, 0, 0)

        # Overview canvas (short strip, same height as Explorer's)
        self.overview_fig = Figure(figsize=(10, 1.4))
        self.overview_fig.set_tight_layout(True)
        self.overview_canvas = FigureCanvas(self.overview_fig)
        self.overview_canvas.setMinimumHeight(80)
        self.overview_canvas.setMaximumHeight(140)

        # Toolbar belongs to detail canvas (like Explorer)
        self.detail_fig = Figure(figsize=(10, 5))
        self.detail_fig.set_tight_layout(True)
        self.detail_canvas = FigureCanvas(self.detail_fig)
        toolbar = NavigationToolbar(self.detail_canvas, self)

        # Action bar between overview and detail
        action_bar = QtWidgets.QHBoxLayout()
        action_bar.setContentsMargins(0, 4, 0, 4)
        action_bar.setSpacing(6)

        self.save_label_check = QtWidgets.QCheckBox("Add gait_cycle col")
        self.save_label_check.setChecked(True)
        self.save_label_check.setToolTip(
            "Appends gait_cycle_L and/or gait_cycle_R columns\n"
            "(1-based integer, NaN for rows outside detected cycles)"
        )
        self.save_trim_check = QtWidgets.QCheckBox("Trim to yellow span")
        self.save_trim_check.setToolTip(
            "When saving, discard all rows outside the yellow selection\n"
            "on the overview strip — only the selected time window is kept."
        )
        self.save_btn = QtWidgets.QPushButton("Save CSV")

        action_bar.addWidget(self.save_label_check)
        action_bar.addWidget(self.save_trim_check)
        action_bar.addWidget(self.save_btn)

        action_bar.addWidget(QtWidgets.QLabel("|"))

        self.plot_profiles_btn = QtWidgets.QPushButton("Plot Gait Profiles")
        self.plot_profiles_btn.setToolTip(
            "4-panel plot (angle / velocity / torque / power)\n"
            "normalised to gait-cycle %, mean ± std, saved as PDF"
        )
        self.power_metrics_btn = QtWidgets.QPushButton("Power Metrics")
        self.power_metrics_btn.setToolTip(
            "Mean positive/negative power and positive power ratio\n"
            "for left and right leg (averaged over all detected cycles)"
        )
        action_bar.addWidget(self.plot_profiles_btn)
        action_bar.addWidget(self.power_metrics_btn)
        action_bar.addStretch(1)

        right.addWidget(toolbar)
        right.addWidget(self.overview_canvas)
        right.addLayout(action_bar)
        right.addWidget(self.detail_canvas, 1)
        root.addLayout(right, 1)

        # ── connect ───────────────────────────────────────────────────────────
        self.detect_btn.clicked.connect(self._detect)
        self.save_btn.clicked.connect(self._save_csv)
        self.compute_power_btn.clicked.connect(self._compute_power)
        self.plot_profiles_btn.clicked.connect(self._plot_gait_profiles)
        self.power_metrics_btn.clicked.connect(self._show_power_metrics)

    # ─────────────────────────────── helpers ──────────────────────────────────

    def _estimate_fs(self) -> float:
        if self.df is None or self.time_col is None:
            return 100.0
        t_raw = pd.to_numeric(self.df[self.time_col], errors="coerce").dropna().to_numpy()
        if len(t_raw) < 2:
            return 100.0
        dt = np.nanmedian(np.diff(t_raw))
        if dt <= 0:
            return 100.0
        return 1000.0 / dt if dt > 10 else 1.0 / dt

    def _get_detection_signal(self):
        """Return (angle_array, side_label) for the primary detection leg."""
        leg  = self.leg_combo.currentText()
        cL   = self.col_L_combo.currentText()
        cR   = self.col_R_combo.currentText()
        hasL = cL != "<None>" and cL in self.df.columns
        hasR = cR != "<None>" and cR in self.df.columns

        if leg == "Left" and hasL:
            return self.df[cL].to_numpy(dtype=float), "L"
        if leg == "Right" and hasR:
            return self.df[cR].to_numpy(dtype=float), "R"
        if leg.startswith("Both") and hasL:
            return self.df[cL].to_numpy(dtype=float), "L"
        if hasL:
            return self.df[cL].to_numpy(dtype=float), "L"
        if hasR:
            return self.df[cR].to_numpy(dtype=float), "R"
        return None, ""

    # ─────────────────────────────── file loading ────────────────────────────

    def _browse(self):
        start_dir = self.data_dir_provider() if self.data_dir_provider else ""
        if not start_dir and self.csv_path:
            start_dir = os.path.dirname(self.csv_path)
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open CSV File", start_dir, "CSV Files (*.csv);;All Files (*)"
        )
        if not path:
            return
        if os.path.basename(path).startswith("._"):
            return
        self._load_csv(path)

    def _load_csv(self, path: str):
        try:
            df = _load_csv(path)
        except Exception as exc:
            self.file_label.setText(f"Error: {exc}")
            return

        self.df = df
        self.csv_path = path
        self.file_label.setText(os.path.basename(path))

        # Time column
        self.time_col = next((c for c in _TIME_CANDIDATES if c in df.columns), None)
        self.t = _make_time_axis(df[self.time_col]) if self.time_col else np.arange(len(df), dtype=float)
        self.fs = self._estimate_fs()
        self.peaks_L = np.array([], dtype=int)
        self.peaks_R = np.array([], dtype=int)
        self.peaks   = np.array([], dtype=int)
        t0, t1 = _time_bounds(self.t)
        self._span = (t0, t0 + max((t1 - t0) * 0.2, 0.1))

        # File info
        self.info_label.setText(
            f"{len(df):,} rows  {len(df.columns)} cols\n"
            f"Duration: {max(0.0, t1 - t0):.1f} s\n"
            f"FS ≈ {self.fs:.0f} Hz"
        )

        # Populate column combos
        num_cols = [c for c in df.columns
                    if c != self.time_col and pd.api.types.is_numeric_dtype(df[c])]
        for combo in (self.col_L_combo, self.col_R_combo):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("<None>")
            combo.addItems(num_cols)
            combo.blockSignals(False)

        # Auto-select canonical column names
        for name in _LEFT_CANDIDATES:
            if name in num_cols:
                self.col_L_combo.setCurrentText(name)
                break
        for name in _RIGHT_CANDIDATES:
            if name in num_cols:
                self.col_R_combo.setCurrentText(name)
                break

        self._populate_power_combos(num_cols)
        self.result_label.setText("File loaded.\nClick 'Detect Cycles' to begin.")
        self._draw_overview()
        self._draw_detail()

    # ─────────────────────────────── plotting ─────────────────────────────────

    def _draw_overview(self):
        """Overview strip: full signal(s) + SpanSelector (yellow drag region)."""
        self.overview_fig.clf()
        self._span_selector = None      # old selector is invalidated after clf()
        ax = self.overview_fig.add_subplot(111)
        self._overview_ax = ax

        if self.df is None:
            self.overview_canvas.draw()
            return

        cL = self.col_L_combo.currentText()
        cR = self.col_R_combo.currentText()
        t  = _sanitize_time_axis(self.t)
        t0, t1 = _time_bounds(t)

        # downsample for speed (same as Explorer: max 2000 pts in overview)
        step = max(1, len(t) // 2000)
        t_ds = t[::step]

        if cL != "<None>" and cL in self.df.columns:
            ax.plot(t_ds, self.df[cL].to_numpy()[::step],
                    color=_COLOR_LEFT, lw=0.6, alpha=0.85, label=cL)
        if cR != "<None>" and cR in self.df.columns:
            ax.plot(t_ds, self.df[cR].to_numpy()[::step],
                    color=_COLOR_RIGHT, lw=0.6, alpha=0.85, label=cR)

        # mark detected peaks on overview too
        if len(self.peaks) > 0:
            cL_ok = cL != "<None>" and cL in self.df.columns
            cR_ok = cR != "<None>" and cR in self.df.columns
            _peak_col = cL if cL_ok else (cR if cR_ok else None)
            if _peak_col:
                ax.scatter(t[self.peaks],
                           self.df[_peak_col].to_numpy()[self.peaks],
                           color=_COLOR_ONSET, s=15, zorder=5, linewidths=0)

        ax.set_xlim(t0, t1)
        ax.set_ylabel("deg", fontsize=8)
        ax.tick_params(labelsize=7)
        ax.grid(True, ls="--", alpha=0.3)
        ax.legend(loc="upper right", fontsize=7)

        # ── SpanSelector (yellow, same props as ExplorerPage) ──────────────
        # Only reset span if it falls outside the loaded data's time range.
        # Preserves user's selection across Detect / redraw cycles.
        s0, s1 = self._span
        if not (t0 <= s0 < s1 <= t1):
            self._span = (t0, t0 + max((t1 - t0) * 0.2, 0.1))

        if SpanSelector is not None:
            try:
                self._span_selector = SpanSelector(
                    ax,
                    self._on_span_select,
                    "horizontal",
                    useblit=True,
                    props=dict(facecolor="#ffd54f", alpha=0.35),
                    interactive=True,
                    drag_from_anywhere=True,
                )
                self._span_selector.extents = self._span
            except TypeError:
                # older matplotlib without interactive/drag_from_anywhere
                self._span_selector = SpanSelector(
                    ax,
                    self._on_span_select,
                    "horizontal",
                    useblit=True,
                    rectprops=dict(facecolor="#ffd54f", alpha=0.35),
                )

        self.overview_canvas.draw()

    def _on_span_select(self, t_min, t_max):
        """Called when user drags the yellow span on the overview."""
        if t_max - t_min < 0.01:
            return
        self._span = (t_min, t_max)
        self._draw_detail()

    def _draw_detail(self, highlight_range=None):
        """
        Detail view: angle subplots with onset markers + cycle shading.

        Parameters
        ----------
        highlight_range : (first_cycle, last_cycle) 1-based inclusive, or None
        """
        self.detail_fig.clf()
        if self.df is None:
            self.detail_canvas.draw()
            return

        cL   = self.col_L_combo.currentText()
        cR   = self.col_R_combo.currentText()
        hasL = cL != "<None>" and cL in self.df.columns
        hasR = cR != "<None>" and cR in self.df.columns
        t    = self.t

        n_rows = 2 if (hasL and hasR) else 1
        axes = self.detail_fig.subplots(n_rows, 1, sharex=True)
        if n_rows == 1:
            axes = [axes]

        leg_sel  = self.leg_combo.currentText()
        primary_L = leg_sel in ("Left", "Both (Left primary)") or not hasR
        primary_R = leg_sel == "Right"

        def _plot_angle(ax, col, color, is_primary):
            data = self.df[col].to_numpy(dtype=float)
            ax.plot(t, data, color=color, lw=0.8, alpha=0.85, label=col)
            if is_primary and len(self.peaks) > 0:
                ax.scatter(t[self.peaks], data[self.peaks],
                           color=_COLOR_ONSET, s=30, zorder=5,
                           label="Onset", linewidths=0)
                for i in range(len(self.peaks) - 1):
                    s, e = self.peaks[i], self.peaks[i + 1]
                    fc = "#1f77b418" if i % 2 == 0 else "#ff7f0e18"
                    ax.axvspan(t[s], t[e], facecolor=fc, linewidth=0)
            ax.set_ylabel("Angle (deg)")
            ax.legend(loc="upper right", fontsize=8)
            ax.grid(True, ls="--", alpha=0.4)

        if n_rows == 2:
            if hasL:
                _plot_angle(axes[0], cL, _COLOR_LEFT,  primary_L)
            if hasR:
                _plot_angle(axes[1], cR, _COLOR_RIGHT, primary_R or not primary_L)
        else:
            col = cL if hasL else cR
            clr = _COLOR_LEFT if hasL else _COLOR_RIGHT
            _plot_angle(axes[0], col, clr, True)

        axes[-1].set_xlabel("Time (s)")
        n_cycles = max(0, len(self.peaks) - 1)
        axes[0].set_title(
            "Hip Angle" if n_cycles == 0
            else f"Gait Cycle Detection — {n_cycles} cycles  |  red = onset"
        )

        # Zoom detail view to the selected span
        t_min, t_max = self._span
        for ax in axes:
            ax.set_xlim(t_min, t_max)

        # Green highlight for selected cycle range
        if highlight_range is not None and len(self.peaks) >= 2:
            c1, c2  = highlight_range
            n_cyc   = len(self.peaks) - 1
            i0 = max(0, min(c1 - 1, n_cyc - 1))
            i1 = max(i0, min(c2 - 1, n_cyc - 1))
            t0 = t[self.peaks[i0]]
            t1 = t[self.peaks[i1 + 1]] if i1 + 1 < len(self.peaks) else t[-1]
            for ax in axes:
                ax.axvspan(t0, t1, facecolor="#2ca02c28", linewidth=0, zorder=2)
                ax.axvline(t0, color="#2ca02c", lw=1.5, ls="--", zorder=3)
                ax.axvline(t1, color="#2ca02c", lw=1.5, ls="--", zorder=3)

        self.detail_fig.tight_layout()
        self.detail_canvas.draw()

    # ─────────────────────────────── slots ───────────────────────────────────

    def _detect_in_span(self, angle_full: np.ndarray) -> np.ndarray:
        """
        Detect peaks within the current yellow span only.
        Returns indices into the *full* arrays (self.t, self.df rows).
        Numbering of cycles always starts at 1 from the first peak in the span.
        """
        t_min, t_max = self._span
        mask = (self.t >= t_min) & (self.t <= t_max)
        indices = np.where(mask)[0]
        if len(indices) < 10:
            return np.array([], dtype=int)
        local_peaks = _detect_peaks(
            angle_full[indices], self.fs,
            min_cycle_sec=self.min_cycle_spin.value(),
            max_cycle_sec=self.max_cycle_spin.value(),
            prominence=self.prom_spin.value(),
            negate=self.negate_check.isChecked(),
        )
        return indices[local_peaks]   # map back to full-array indices

    def _detect(self):
        if self.df is None:
            QtWidgets.QMessageBox.warning(self, "No Data", "Load a CSV file first.")
            return

        leg  = self.leg_combo.currentText()
        cL   = self.col_L_combo.currentText()
        cR   = self.col_R_combo.currentText()
        hasL = cL != "<None>" and cL in self.df.columns
        hasR = cR != "<None>" and cR in self.df.columns

        do_L = leg in ("Left", "Both (Left primary)") and hasL
        do_R = leg in ("Right", "Both (Left primary)") and hasR
        if leg == "Right":
            do_L = False
            do_R = hasR

        if not do_L and not do_R:
            QtWidgets.QMessageBox.warning(self, "No Column",
                                          "Select valid angle column(s) for the chosen leg.")
            return

        self.peaks_L = self._detect_in_span(self.df[cL].to_numpy(dtype=float)) if do_L \
                       else np.array([], dtype=int)
        self.peaks_R = self._detect_in_span(self.df[cR].to_numpy(dtype=float)) if do_R \
                       else np.array([], dtype=int)

        # primary peaks for display (prefer L if both detected)
        self.peaks = self.peaks_L if len(self.peaks_L) > 0 else self.peaks_R

        # ── build result text ──────────────────────────────────────────────
        lines = []
        for label, pk in (("L", self.peaks_L), ("R", self.peaks_R)):
            if len(pk) == 0:
                continue
            n_cyc = max(0, len(pk) - 1)
            durs  = np.diff(self.t[pk])
            lines.append(
                f"── {label} leg ──\n"
                f"Peaks  : {len(pk)}\n"
                f"Cycles : {n_cyc}\n"
                f"Mean   : {np.mean(durs):.3f} s\n"
                f"Std    : {np.std(durs):.3f} s\n"
                f"Range  : {np.min(durs):.3f}–{np.max(durs):.3f} s"
            )

        if lines:
            self.result_label.setText("\n\n".join(lines))
        else:
            self.result_label.setText(
                "No cycles detected.\n"
                "Try lowering Prominence\nor adjusting Min/Max."
            )

        self._draw_overview()
        self._draw_detail()

    def _save_csv(self):
        if self.df is None:
            QtWidgets.QMessageBox.warning(self, "No Data", "Load a CSV file first.")
            return
        if not self.save_label_check.isChecked() and not self.save_trim_check.isChecked():
            QtWidgets.QMessageBox.warning(self, "Nothing to Save",
                                          "Enable at least one export option.")
            return
        if len(self.peaks_L) < 2 and len(self.peaks_R) < 2:
            QtWidgets.QMessageBox.warning(self, "No Cycles",
                                          "Run cycle detection first.")
            return

        out_df = self.df.copy()

        def _make_cycle_col(peaks):
            """Build a float array: 1,2,3… per cycle, NaN outside."""
            col = np.full(len(out_df), np.nan)
            for i in range(len(peaks) - 1):
                s, e = peaks[i], peaks[i + 1]
                col[s:e] = i + 1      # 1-based, starting from first detected cycle
            return col

        # ── Add gait_cycle_L / gait_cycle_R columns ───────────────────────
        if self.save_label_check.isChecked():
            if len(self.peaks_L) >= 2:
                out_df["gait_cycle_L"] = _make_cycle_col(self.peaks_L)
            if len(self.peaks_R) >= 2:
                out_df["gait_cycle_R"] = _make_cycle_col(self.peaks_R)

        # ── Trim to yellow span (keep only rows within the SpanSelector region) ──
        if self.save_trim_check.isChecked():
            t_min, t_max = self._span
            mask = (self.t >= t_min) & (self.t <= t_max)
            out_df = out_df[mask].reset_index(drop=True)

        base    = os.path.splitext(self.csv_path)[0] if self.csv_path else "output"
        default = base + "_gaitsplit.csv"
        save_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save Gait-Split CSV", default, "CSV files (*.csv)"
        )
        if not save_path:
            return

        try:
            out_df.to_csv(save_path, index=False)
            QtWidgets.QMessageBox.information(
                self, "Saved", f"Saved {len(out_df):,} rows to:\n{save_path}"
            )
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Save Error", str(exc))

    # ─────────────────────────── power calculation ────────────────────────────

    def _populate_power_combos(self, num_cols):
        """Fill velocity/torque combos; auto-select canonical names."""
        _vel_L  = ("imu_Lvel", "left_vel", "L_vel", "vel_L")
        _vel_R  = ("imu_Rvel", "right_vel", "R_vel", "vel_R")
        _tor_L  = ("M2_torque_command", "left_torque", "L_torque", "torque_L")
        _tor_R  = ("M1_torque_command", "right_torque", "R_torque", "torque_R")
        _rp     = ("R_P",)
        _rd     = ("R_D",)
        _rcmd   = ("M1_torque_command", "R_torque_command", "torque_cmd_R")

        all_combos = (
            self.vel_L_combo, self.tor_L_combo,
            self.vel_R_combo, self.tor_R_combo,
            self.rp_combo, self.rd_combo, self.rcmd_combo,
        )
        for combo in all_combos:
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("<None>")
            combo.addItems(num_cols)
            combo.blockSignals(False)

        for names, combo in (
            (_vel_L, self.vel_L_combo), (_vel_R, self.vel_R_combo),
            (_tor_L, self.tor_L_combo), (_tor_R, self.tor_R_combo),
            (_rp,    self.rp_combo),    (_rd,    self.rd_combo),
            (_rcmd,  self.rcmd_combo),
        ):
            for name in names:
                if name in num_cols:
                    combo.setCurrentText(name)
                    break

    def _compute_power(self):
        """Compute instantaneous power and add power_L / power_R columns to df."""
        if self.df is None:
            QtWidgets.QMessageBox.warning(self, "No Data", "Load a CSV file first.")
            return

        scale    = np.pi / 180.0 if self.deg2rad_check.isChecked() else 1.0
        do_filt  = self.vel_filter_check.isChecked()
        filt_fc  = self.vel_cutoff_spin.value()
        added    = []

        for side, v_combo, t_combo, col_name in (
            ("L", self.vel_L_combo, self.tor_L_combo, "power_L"),
            ("R", self.vel_R_combo, self.tor_R_combo, "power_R"),
        ):
            vc = v_combo.currentText()
            tc = t_combo.currentText()
            if vc == "<None>" or tc == "<None>":
                continue
            if vc not in self.df.columns or tc not in self.df.columns:
                continue
            vel_raw = self.df[vc].to_numpy(dtype=float)
            vel     = (_lowpass(vel_raw, self.fs, fc=filt_fc) if do_filt else vel_raw) * scale
            torque  = self.df[tc].to_numpy(dtype=float)
            self.df[col_name] = vel * torque
            added.append(col_name)

        if added:
            QtWidgets.QMessageBox.information(
                self, "Power Computed",
                f"Added columns: {', '.join(added)}\n"
                "Units: W  (Nm × rad/s)"
                if self.deg2rad_check.isChecked() else
                f"Added columns: {', '.join(added)}\n"
                "Units: Nm·deg/s  (velocity not converted)"
            )
        else:
            QtWidgets.QMessageBox.warning(
                self, "Nothing Computed",
                "Select velocity and torque columns for at least one leg."
            )

    # ─────────────────────────── gait profile plot ───────────────────────────

    def _normalize_signal_by_peaks(self, signal, peaks, n_points=101):
        """
        Slice signal at peak boundaries and interpolate each slice to n_points.
        Returns (mean, std) arrays of shape (n_points,), or (None, None) if no cycles.
        """
        cycles = []
        for i in range(len(peaks) - 1):
            s, e = int(peaks[i]), int(peaks[i + 1])
            seg = signal[s:e]
            if len(seg) < 5:
                continue
            x_old = np.linspace(0, 1, len(seg))
            x_new = np.linspace(0, 1, n_points)
            cycles.append(np.interp(x_new, x_old, seg))
        if not cycles:
            return None, None
        arr = np.array(cycles)
        return np.mean(arr, axis=0), np.std(arr, axis=0)

    def _plot_gait_profiles(self):
        """
        Gait profile figure: angle / velocity / torque / power (+ optional torque
        components), normalised to 0-100 % gait cycle, mean ± std.

        Layout:
          - Only one leg detected  → 1 column, that leg's color
          - Both legs detected     → 2 columns (Left | Right), independent peaks
        """
        if self.df is None:
            QtWidgets.QMessageBox.warning(self, "No Data", "Load a CSV file first.")
            return
        has_L = len(self.peaks_L) >= 2
        has_R = len(self.peaks_R) >= 2
        if not has_L and not has_R:
            QtWidgets.QMessageBox.warning(self, "No Cycles",
                                          "Run cycle detection first.")
            return

        def _get(col):
            if col != "<None>" and col in self.df.columns:
                return self.df[col].to_numpy(dtype=float)
            return None

        cL_ang = _get(self.col_L_combo.currentText())
        cR_ang = _get(self.col_R_combo.currentText())
        cL_vel = _get(self.vel_L_combo.currentText())
        cR_vel = _get(self.vel_R_combo.currentText())
        cL_tor = _get(self.tor_L_combo.currentText())
        cR_tor = _get(self.tor_R_combo.currentText())
        cL_pwr = self.df["power_L"].to_numpy(dtype=float) if "power_L" in self.df.columns else None
        cR_pwr = self.df["power_R"].to_numpy(dtype=float) if "power_R" in self.df.columns else None

        sig_c1   = _get(self.rp_combo.currentText())
        sig_c2   = _get(self.rd_combo.currentText())
        sig_c3   = _get(self.rcmd_combo.currentText())
        has_5th  = self.show_5th_check.isChecked()

        both   = has_L and has_R
        n_cols = 2 if both else 1
        n_rows = 5 if has_5th else 4
        x_pct  = np.linspace(0, 100, 101)

        # columns: each entry = (peaks, color, label, signals_per_row)
        # signals_per_row order: angle, velocity, torque, power
        if both:
            cols_spec = [
                (self.peaks_L, _COLOR_LEFT,  "Left",
                 [cL_ang, cL_vel, cL_tor, cL_pwr]),
                (self.peaks_R, _COLOR_RIGHT, "Right",
                 [cR_ang, cR_vel, cR_tor, cR_pwr]),
            ]
        elif has_L:
            cols_spec = [
                (self.peaks_L, _COLOR_LEFT, "Left",
                 [cL_ang, cL_vel, cL_tor, cL_pwr]),
            ]
        else:
            cols_spec = [
                (self.peaks_R, _COLOR_RIGHT, "Right",
                 [cR_ang, cR_vel, cR_tor, cR_pwr]),
            ]

        row_labels = ["Angle (deg)", "Velocity (deg/s)", "Torque (Nm)", "Power (W)"]

        fig_w = 7 * n_cols + 1
        fig, axes_raw = plt.subplots(
            n_rows, n_cols,
            figsize=(fig_w, 2.4 * n_rows + 1),
            sharex=True, squeeze=False,
        )
        fname = os.path.basename(self.csv_path or "Gait Profiles")
        fig.suptitle(f"{fname}\nMean ± SD per gait cycle", fontsize=11)

        def _plot_band(ax, sig, peaks, color, label):
            if sig is None or len(peaks) < 2:
                return False
            m, s = self._normalize_signal_by_peaks(sig, peaks)
            if m is None:
                return False
            ax.plot(x_pct, m, color=color, lw=1.8, label=label)
            ax.fill_between(x_pct, m - s, m + s, color=color, alpha=0.20)
            return True

        # ── rows 0-3: angle / velocity / torque / power ───────────────────────
        for row_i, ylabel in enumerate(row_labels):
            for col_i, (peaks, color, leg_label, sigs) in enumerate(cols_spec):
                ax = axes_raw[row_i, col_i]
                plotted = _plot_band(ax, sigs[row_i], peaks, color, leg_label)
                ax.axhline(0, color="#888", lw=0.6, ls="--")
                ax.set_ylabel(ylabel, fontsize=9)
                ax.grid(True, ls="--", alpha=0.35)
                if plotted:
                    ax.legend(loc="upper right", fontsize=8)
            # column header on first row
            if row_i == 0 and both:
                axes_raw[0, 0].set_title("Left Leg", color=_COLOR_LEFT,  fontsize=10)
                axes_raw[0, 1].set_title("Right Leg", color=_COLOR_RIGHT, fontsize=10)

        # ── row 4 (optional): torque components ───────────────────────────────
        if has_5th:
            _comp_colors = {
                "Residual (P/NN)":  "#9467bd",
                "Priority (D/vel)": "#8c564b",
                "Cmd torque":       "#2ca02c",
            }
            comp_sigs = [
                (sig_c1, "Residual (P/NN)"),
                (sig_c2, "Priority (D/vel)"),
                (sig_c3, "Cmd torque"),
            ]
            for col_i, (peaks, _color, _leg, _sigs) in enumerate(cols_spec):
                ax5 = axes_raw[4, col_i]
                for sig, label in comp_sigs:
                    if sig is None:
                        continue
                    m, s = self._normalize_signal_by_peaks(sig, peaks)
                    if m is None:
                        continue
                    clr = _comp_colors[label]
                    ax5.plot(x_pct, m, color=clr, lw=1.8, label=label)
                    ax5.fill_between(x_pct, m - s, m + s, color=clr, alpha=0.15)
                ax5.axhline(0, color="#888", lw=0.6, ls="--")
                ax5.set_ylabel("Torque (Nm)", fontsize=9)
                ax5.grid(True, ls="--", alpha=0.35)
                ax5.legend(loc="upper right", fontsize=8)

        for col_i in range(n_cols):
            axes_raw[-1, col_i].set_xlabel("Gait Cycle (%)")
        fig.tight_layout()

        # ── Embed in QDialog ──────────────────────────────────────────────────
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Gait Profiles")
        dlg.resize(fig_w * 80 + 60, int(2.4 * n_rows + 1) * 80 + 100)
        dlg_layout = QtWidgets.QVBoxLayout(dlg)
        dlg_layout.setContentsMargins(4, 4, 4, 4)
        dlg_layout.setSpacing(4)

        canvas = FigureCanvas(fig)
        toolbar = NavigationToolbar(canvas, dlg)
        dlg_layout.addWidget(toolbar)
        dlg_layout.addWidget(canvas, 1)

        btn_row = QtWidgets.QHBoxLayout()
        save_btn  = QtWidgets.QPushButton("Save as PDF / PNG…")
        close_btn = QtWidgets.QPushButton("Close")
        btn_row.addWidget(save_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(close_btn)
        dlg_layout.addLayout(btn_row)

        def _save_figure():
            base    = os.path.splitext(self.csv_path)[0] if self.csv_path else "gait_profile"
            default = base + "_gait_profiles.pdf"
            save_path, _ = QtWidgets.QFileDialog.getSaveFileName(
                dlg, "Save Gait Profile Figure", default,
                "PDF (*.pdf);;PNG (*.png);;All files (*)"
            )
            if not save_path:
                return
            try:
                fig.savefig(save_path, dpi=300, bbox_inches="tight")
                QtWidgets.QMessageBox.information(dlg, "Saved", f"Figure saved to:\n{save_path}")
            except Exception as exc:
                QtWidgets.QMessageBox.critical(dlg, "Save Error", str(exc))

        save_btn.clicked.connect(_save_figure)
        close_btn.clicked.connect(dlg.close)
        dlg.exec_()

    # ─────────────────────────── power metrics ───────────────────────────────

    def _show_power_metrics(self):
        """
        Compute and display per-leg power metrics averaged across all detected cycles.

        Metrics (units: W when velocity was converted to rad/s):
          mean_positive_power  – mean of all P > 0 samples, averaged over cycles
          mean_negative_power  – mean of all P < 0 samples, averaged over cycles
          positive_power_ratio – |pos| / (|pos| + |neg|), averaged over cycles
        """
        if self.df is None:
            QtWidgets.QMessageBox.warning(self, "No Data", "Load a CSV file first.")
            return

        has_pwr_L = "power_L" in self.df.columns
        has_pwr_R = "power_R" in self.df.columns
        if not has_pwr_L and not has_pwr_R:
            QtWidgets.QMessageBox.warning(self, "No Power",
                                          "Click 'Compute Power' first.")
            return

        unit = "W" if self.deg2rad_check.isChecked() else "Nm·deg/s"
        lines = [f"Power Metrics  (unit: {unit})\n"]

        for side, col, peaks in (
            ("L", "power_L", self.peaks_L),
            ("R", "power_R", self.peaks_R),
        ):
            if col not in self.df.columns or len(peaks) < 2:
                continue
            power = self.df[col].to_numpy(dtype=float)
            n_cyc = len(peaks) - 1

            # ── Pool ALL samples from all detected cycles into one array ──────
            # This is the global-integration approach: each sample gets equal
            # weight, so longer cycles contribute proportionally more — correct.
            segs = [power[int(peaks[i]):int(peaks[i + 1])]
                    for i in range(n_cyc)]
            all_seg   = np.concatenate(segs)          # all in-cycle power samples
            N_total   = len(all_seg)                  # total sample count
            T_total   = N_total / self.fs             # total duration (s) of all cycles

            pos_vals  = all_seg[all_seg > 0]
            neg_vals  = all_seg[all_seg < 0]

            # Work (J): Σ P × dt = Σ P / fs  (dt constant, fs already used above)
            W_pos = float(np.sum(pos_vals)) / self.fs   # J
            W_neg = float(np.sum(np.abs(neg_vals))) / self.fs   # J (magnitude)

            # ── Ratio: positive work / total absolute work ────────────────────
            # dt cancels in numerator and denominator, so equivalent to
            # Σ(P>0) / [Σ(P>0) + Σ|P<0|]
            W_tot = W_pos + W_neg
            ratio = W_pos / W_tot if W_tot > 0 else 0.0

            # ── Mean instantaneous power when positive / negative (W) ─────────
            mean_pos_inst = float(np.mean(pos_vals)) if len(pos_vals) > 0 else 0.0
            mean_neg_inst = float(np.mean(neg_vals)) if len(neg_vals) > 0 else 0.0

            # ── Per-second: average power delivery rate over walking time ─────
            # = total work (J) ÷ total time (s)
            pos_per_s = W_pos / T_total   # W
            neg_per_s = -W_neg / T_total  # W (negative)

            # ── Per-cycle: average work done each step ────────────────────────
            # = total work (J) ÷ number of cycles  → unit: J/cycle
            pos_per_cyc = W_pos / n_cyc   # J per cycle
            neg_per_cyc = -W_neg / n_cyc  # J per cycle (negative)

            # fraction of samples that are positive / negative
            f_pos = len(pos_vals) / N_total if N_total > 0 else 0.0
            f_neg = len(neg_vals) / N_total if N_total > 0 else 0.0

            lines.append(
                f"── {side} leg  ({n_cyc} cycles,  T_total = {T_total:.1f} s) ──\n"
                f"\n"
                f"  ① Total work (global integral)\n"
                f"     positive work W+  : {W_pos:+.3f} J\n"
                f"     negative work W-  : {-W_neg:+.3f} J\n"
                f"     positive_power_ratio = W+ / (W+ + |W-|) = {ratio:.4f}  ({ratio*100:.1f} %)\n"
                f"\n"
                f"  ② Active-phase mean  [mean(P) only when P>0 or P<0]\n"
                f"     (describes HOW negative/positive the bursts are when they occur;\n"
                f"      does NOT reflect how often — compare with ③)\n"
                f"     mean when positive : {mean_pos_inst:+.3f} {unit}  "
                f"({f_pos*100:.1f} % of samples)\n"
                f"     mean when negative : {mean_neg_inst:+.3f} {unit}  "
                f"({f_neg*100:.1f} % of samples)\n"
                f"\n"
                f"  ③ Per-second  [W+ or |W-| ÷ T_total]\n"
                f"     = active-phase mean × fraction-of-time  (so ③ = ② × fraction)\n"
                f"     positive : {pos_per_s:+.3f} W   "
                f"(≈ {mean_pos_inst:.2f} × {f_pos:.2f})\n"
                f"     negative : {neg_per_s:+.3f} W   "
                f"(≈ {mean_neg_inst:.2f} × {f_neg:.2f})\n"
                f"\n"
                f"  ④ Per-cycle  [W+ or |W-| ÷ N_cycles]  unit: J/cycle\n"
                f"     positive : {pos_per_cyc:+.3f} J/cycle\n"
                f"     negative : {neg_per_cyc:+.3f} J/cycle\n"
            )

        # Show in a dialog with copyable text
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Power Metrics")
        dlg.resize(420, 280)
        layout = QtWidgets.QVBoxLayout(dlg)

        text = QtWidgets.QTextEdit()
        text.setReadOnly(True)
        text.setFontFamily("monospace")
        text.setPlainText("\n".join(lines))
        layout.addWidget(text)

        btn_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        btn_box.rejected.connect(dlg.reject)
        layout.addWidget(btn_box)
        dlg.exec_()
