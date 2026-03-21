#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json

import numpy as np
import pandas as pd

from PyQt5 import QtWidgets
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QStyle

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure

try:
    from src.utils import lowpass_filter, StreamingButterworth
except Exception:  # pragma: no cover
    lowpass_filter = None
    StreamingButterworth = None
try:
    from scipy.signal import group_delay
except Exception:  # pragma: no cover
    group_delay = None


def make_time_axis(time_series: pd.Series) -> np.ndarray:
    t_num = pd.to_numeric(time_series, errors="coerce")
    if t_num.notna().mean() > 0.9:
        t = t_num.to_numpy()
        dt_med = np.nanmedian(np.diff(t)) if len(t) > 1 else 10.0
        if 1.0 <= dt_med <= 1000.0:
            return (t - t[0]) / 1000.0
        return (t - t[0])
    t_dt = pd.to_datetime(time_series, errors="coerce")
    if t_dt.notna().mean() > 0.9:
        return (t_dt - t_dt.iloc[0]).dt.total_seconds().to_numpy()
    return np.arange(len(time_series), dtype=float)


def estimate_fs_from_time(t_series):
    t = pd.to_numeric(t_series, errors="coerce").to_numpy(dtype=float)
    t = t[np.isfinite(t)]
    if len(t) < 2:
        return 100.0
    dt = np.nanmedian(np.diff(t))
    if not np.isfinite(dt) or dt <= 0:
        return 100.0
    if dt > 10:
        return 1000.0 / dt
    return 1.0 / dt


class FilterDelayPage(QtWidgets.QWidget):
    def __init__(self, data_dir_provider, mapping_path_provider):
        super().__init__()
        self.data_dir_provider = data_dir_provider
        self.mapping_path_provider = mapping_path_provider
        self.cache = {}
        self._build_ui()
        self._refresh_files()

    def _build_ui(self):
        layout = QtWidgets.QHBoxLayout(self)

        controls = QtWidgets.QWidget()
        controls_layout = QtWidgets.QVBoxLayout(controls)
        controls_layout.setContentsMargins(8, 8, 8, 8)
        controls_layout.setSpacing(8)

        file_group = QtWidgets.QWidget()
        file_group.setObjectName("sectionPanel")
        file_group_layout = QtWidgets.QVBoxLayout(file_group)
        file_group_layout.setContentsMargins(10, 10, 10, 10)
        file_group_layout.setSpacing(6)
        file_title = QtWidgets.QLabel("Data")
        file_title.setObjectName("sectionTitle")
        file_group_layout.addWidget(file_title)
        file_layout = QtWidgets.QGridLayout()
        file_group_layout.addLayout(file_layout)
        self.file_combo = QtWidgets.QComboBox()
        self.refresh_btn = QtWidgets.QPushButton("Refresh")
        self.tag_combo = QtWidgets.QComboBox()
        self.leg_combo = QtWidgets.QComboBox()
        self.leg_combo.addItems(["left", "right"])
        file_layout.addWidget(QtWidgets.QLabel("File:"), 0, 0)
        file_layout.addWidget(self.file_combo, 0, 1, 1, 2)
        file_layout.addWidget(self.refresh_btn, 1, 0)
        file_layout.addWidget(QtWidgets.QLabel("Tag:"), 2, 0)
        file_layout.addWidget(self.tag_combo, 2, 1, 1, 2)
        file_layout.addWidget(QtWidgets.QLabel("Leg:"), 3, 0)
        file_layout.addWidget(self.leg_combo, 3, 1, 1, 2)

        range_group = QtWidgets.QWidget()
        range_group.setObjectName("sectionPanel")
        range_group_layout = QtWidgets.QVBoxLayout(range_group)
        range_group_layout.setContentsMargins(10, 10, 10, 10)
        range_group_layout.setSpacing(6)
        range_title = QtWidgets.QLabel("Time Range (s)")
        range_title.setObjectName("sectionTitle")
        range_group_layout.addWidget(range_title)
        range_layout = QtWidgets.QGridLayout()
        range_group_layout.addLayout(range_layout)
        self.start_spin = QtWidgets.QDoubleSpinBox()
        self.end_spin = QtWidgets.QDoubleSpinBox()
        for sp in (self.start_spin, self.end_spin):
            sp.setDecimals(3)
            sp.setSingleStep(0.1)
        self.full_btn = QtWidgets.QPushButton("Full Range")
        self.window_spin = QtWidgets.QDoubleSpinBox()
        self.window_spin.setDecimals(2)
        self.window_spin.setSingleStep(0.5)
        self.window_spin.setRange(0.5, 600.0)
        self.window_spin.setValue(10.0)
        self.pan_slider = QtWidgets.QSlider(Qt.Horizontal)
        self.pan_slider.setRange(0, 1000)
        self.pan_slider.setValue(0)
        range_layout.addWidget(QtWidgets.QLabel("Start:"), 0, 0)
        range_layout.addWidget(self.start_spin, 0, 1)
        range_layout.addWidget(QtWidgets.QLabel("End:"), 1, 0)
        range_layout.addWidget(self.end_spin, 1, 1)
        range_layout.addWidget(self.full_btn, 0, 2, 2, 1)
        range_layout.addWidget(QtWidgets.QLabel("Window (s):"), 2, 0)
        range_layout.addWidget(self.window_spin, 2, 1)
        range_layout.addWidget(QtWidgets.QLabel("Pan:"), 3, 0)
        range_layout.addWidget(self.pan_slider, 3, 1, 1, 2)

        filter_group = QtWidgets.QWidget()
        filter_group.setObjectName("sectionPanel")
        filter_group_layout = QtWidgets.QVBoxLayout(filter_group)
        filter_group_layout.setContentsMargins(10, 10, 10, 10)
        filter_group_layout.setSpacing(6)
        filter_title = QtWidgets.QLabel("Filter + Delay")
        filter_title.setObjectName("sectionTitle")
        filter_group_layout.addWidget(filter_title)
        filter_layout = QtWidgets.QGridLayout()
        filter_group_layout.addLayout(filter_layout)
        self.cutoff_spin = QtWidgets.QDoubleSpinBox()
        self.cutoff_spin.setDecimals(2)
        self.cutoff_spin.setSingleStep(0.5)
        self.cutoff_spin.setRange(0.5, 50.0)
        self.cutoff_spin.setValue(6.0)
        self.order_spin = QtWidgets.QSpinBox()
        self.order_spin.setRange(1, 8)
        self.order_spin.setValue(2)
        self.delay_spin = QtWidgets.QDoubleSpinBox()
        self.delay_spin.setDecimals(3)
        self.delay_spin.setSingleStep(1.0)
        self.delay_spin.setRange(-2000.0, 2000.0)
        self.delay_spin.setValue(0.0)
        filter_layout.addWidget(QtWidgets.QLabel("Cutoff (Hz):"), 0, 0)
        filter_layout.addWidget(self.cutoff_spin, 0, 1)
        filter_layout.addWidget(QtWidgets.QLabel("Order:"), 1, 0)
        filter_layout.addWidget(self.order_spin, 1, 1)
        filter_layout.addWidget(QtWidgets.QLabel("Delay (ms):"), 2, 0)
        filter_layout.addWidget(self.delay_spin, 2, 1)

        self.plot_btn = QtWidgets.QPushButton("Update Plot")
        self.stats_label = QtWidgets.QLabel("Positive/Negative power stats will appear here.")
        self.stats_label.setWordWrap(True)

        controls_layout.addWidget(file_group)
        controls_layout.addWidget(range_group)
        controls_layout.addWidget(filter_group)
        controls_layout.addWidget(self.plot_btn)
        controls_layout.addWidget(self.stats_label)
        controls_layout.addStretch(1)

        plot_widget = QtWidgets.QWidget()
        plot_layout = QtWidgets.QVBoxLayout(plot_widget)
        self.figure = Figure(figsize=(8, 6))
        self.canvas = FigureCanvas(self.figure)
        self.toolbar = NavigationToolbar(self.canvas, self)
        plot_layout.addWidget(self.toolbar)
        plot_layout.addWidget(self.canvas, 1)

        layout.addWidget(controls)
        layout.addWidget(plot_widget, 1)

        self.refresh_btn.clicked.connect(self._refresh_files)
        self.file_combo.currentTextChanged.connect(self._on_file_change)
        self.tag_combo.currentTextChanged.connect(self._on_tag_change)
        self.full_btn.clicked.connect(self._set_full_range)
        self.plot_btn.clicked.connect(self.plot)
        self.start_spin.valueChanged.connect(self._on_range_changed)
        self.end_spin.valueChanged.connect(self._on_range_changed)
        self.window_spin.valueChanged.connect(self._window_changed)
        self.pan_slider.valueChanged.connect(self._pan_changed)
        self.cutoff_spin.valueChanged.connect(self.plot)
        self.order_spin.valueChanged.connect(self.plot)
        self.delay_spin.valueChanged.connect(self.plot)
        self.leg_combo.currentTextChanged.connect(self.plot)

    def refresh_data(self):
        self.cache = {}
        self._refresh_files()

        self.refresh_btn.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        self.full_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogResetButton))
        self.plot_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))

    def _refresh_files(self):
        self.file_combo.clear()
        data_dir = self.data_dir_provider()
        if not os.path.isdir(data_dir):
            return
        files = sorted([f for f in os.listdir(data_dir) if f.lower().endswith(".csv")])
        self.file_combo.addItems(files)
        if files:
            self.file_combo.setCurrentIndex(0)
            self._on_file_change(files[0])

    def _on_file_change(self, name):
        if not name:
            return
        df = self._load_df(os.path.join(self.data_dir_provider(), name))
        self._populate_tags(df)
        self._set_full_range()

    def _on_tag_change(self, *args):
        self._set_full_range()

    def _populate_tags(self, df):
        self.tag_combo.clear()
        if df is None or "tag" not in df.columns:
            return
        tags = [str(t) for t in pd.Series(df["tag"]).dropna().unique().tolist()]
        tags = sorted(tags)
        self.tag_combo.addItems(tags)

    def _set_full_range(self):
        df = self._get_filtered_df()
        if df is None or df.empty or "t_sec" not in df.columns:
            return
        t = df["t_sec"].to_numpy(dtype=float)
        tmin, tmax = float(np.nanmin(t)), float(np.nanmax(t))
        self.start_spin.setRange(tmin, tmax)
        self.end_spin.setRange(tmin, tmax)
        win = min(float(self.window_spin.value()), tmax - tmin)
        if win <= 0:
            win = min(10.0, tmax - tmin) if tmax > tmin else 1.0
        self.window_spin.blockSignals(True)
        self.window_spin.setValue(win)
        self.window_spin.blockSignals(False)
        self.start_spin.setValue(tmin)
        self.end_spin.setValue(tmin + win)
        self._sync_pan_from_spins()
        self.plot()

    def _on_range_changed(self):
        if self.start_spin.value() > self.end_spin.value():
            self.end_spin.setValue(self.start_spin.value())
        self._sync_pan_from_spins()
        self.plot()

    def _window_changed(self):
        self._apply_pan_window()
        self.plot()

    def _pan_changed(self):
        self._apply_pan_window()
        self.plot()

    def _sync_pan_from_spins(self):
        df = self._get_filtered_df()
        if df is None or df.empty or "t_sec" not in df.columns:
            return
        t = df["t_sec"].to_numpy(dtype=float)
        tmin, tmax = float(np.nanmin(t)), float(np.nanmax(t))
        if tmax <= tmin:
            return
        window = max(0.001, min(self.window_spin.value(), tmax - tmin))
        start = self.start_spin.value()
        max_start = tmax - window
        if max_start <= tmin:
            pan = 0.0
        else:
            pan = (start - tmin) / (max_start - tmin)
        pan_val = int(max(0, min(1000, round(pan * 1000))))
        self.pan_slider.blockSignals(True)
        self.pan_slider.setValue(pan_val)
        self.pan_slider.blockSignals(False)

    def _apply_pan_window(self):
        df = self._get_filtered_df()
        if df is None or df.empty or "t_sec" not in df.columns:
            return
        t = df["t_sec"].to_numpy(dtype=float)
        tmin, tmax = float(np.nanmin(t)), float(np.nanmax(t))
        if tmax <= tmin:
            return
        window = max(0.001, min(self.window_spin.value(), tmax - tmin))
        max_start = tmax - window
        if max_start <= tmin:
            start = tmin
        else:
            pan = self.pan_slider.value() / 1000.0
            start = tmin + pan * (max_start - tmin)
        end = start + window
        self.start_spin.blockSignals(True)
        self.end_spin.blockSignals(True)
        self.start_spin.setValue(start)
        self.end_spin.setValue(end)
        self.start_spin.blockSignals(False)
        self.end_spin.blockSignals(False)

    def _load_mapping(self):
        path = self.mapping_path_provider()
        if not path or not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            return {}
        return {}

    def _apply_mapping(self, df, mapping):
        df2 = df.copy()
        for logical, actual in mapping.items():
            if actual and actual in df2.columns:
                df2[logical] = df2[actual]
        return df2

    def _load_df(self, path):
        if path in self.cache:
            return self.cache[path]
        try:
            try:
                df = pd.read_csv(path)
            except UnicodeDecodeError:
                df = pd.read_csv(path, encoding="latin-1")
        except Exception:
            return None
        mapping = self._load_mapping()
        if mapping:
            df = self._apply_mapping(df, mapping)
        if "Time_ms" in df.columns:
            df = df.copy()
            df["t_sec"] = make_time_axis(df["Time_ms"])
        self.cache[path] = df
        return df

    def _get_filtered_df(self):
        fname = self.file_combo.currentText().strip()
        if not fname:
            return None
        df = self._load_df(os.path.join(self.data_dir_provider(), fname))
        if df is None:
            return None
        tag = self.tag_combo.currentText().strip()
        if tag and "tag" in df.columns:
            df = df[df["tag"].astype(str) == tag].reset_index(drop=True)
        return df

    def plot(self):
        self.figure.clear()
        ax1 = self.figure.add_subplot(311)
        ax2 = self.figure.add_subplot(312, sharex=ax1)
        ax3 = self.figure.add_subplot(313, sharex=ax1)

        df = self._get_filtered_df()
        if df is None or df.empty:
            self.canvas.draw()
            return

        t = df["t_sec"].to_numpy(dtype=float) if "t_sec" in df.columns else make_time_axis(df["Time_ms"])
        t0, t1 = self.start_spin.value(), self.end_spin.value()
        sel = (t >= t0) & (t <= t1)
        if sel.sum() < 5:
            self.canvas.draw()
            return
        t = t[sel]
        df = df.loc[sel].reset_index(drop=True)

        leg = self.leg_combo.currentText()
        if leg == "left":
            raw_col = "raw_LExoTorque"
            cmd_col = "M2_torque_command"
            vel_col = "imu_Lvel"
        else:
            raw_col = "raw_RExoTorque"
            cmd_col = "M1_torque_command"
            vel_col = "imu_Rvel"

        raw = pd.to_numeric(df.get(raw_col), errors="coerce").to_numpy(dtype=float)
        cmd = pd.to_numeric(df.get(cmd_col), errors="coerce").to_numpy(dtype=float)
        vel = pd.to_numeric(df.get(vel_col), errors="coerce").to_numpy(dtype=float)

        fs = estimate_fs_from_time(df["Time_ms"]) if "Time_ms" in df.columns else 100.0
        cutoff = float(self.cutoff_spin.value())
        order = int(self.order_spin.value())

        raw_f = raw.copy()
        filter_delay_ms = None
        if StreamingButterworth is not None:
            sb = StreamingButterworth(fc=cutoff, nyq=fs / 2.0, order=order, num_joints=1)
            raw_f = np.array([sb.filter_step([x])[0] for x in raw_f], dtype=float)
            if group_delay is not None and fs > 0:
                w = 2.0 * np.pi * (cutoff / fs)
                try:
                    _, gd = group_delay((sb.b, sb.a), w=[w])
                    if len(gd):
                        filter_delay_ms = float(gd[0]) / fs * 1000.0
                except Exception:
                    filter_delay_ms = None
        elif lowpass_filter is not None:
            raw_f = lowpass_filter(raw_f, cutoff=cutoff, fs=fs, order=order)

        delay = float(self.delay_spin.value()) / 1000.0
        if abs(delay) > 1e-6:
            t_shift = t + delay
            raw_f = np.interp(t, t_shift, raw_f, left=np.nan, right=np.nan)

        ax1.plot(t, raw, label="Raw Torque", color="#999999", alpha=0.6)
        ax1.plot(t, raw_f, label="Filtered+Delayed Raw", color="#1f77b4")
        ax1.plot(t, cmd, label="Command Torque", color="#d62728")
        ax1.set_ylabel("Torque (Nm)")
        ax1.grid(True)
        ax1.legend(loc="upper right")

        ax2.plot(t, raw_f - cmd, label="Raw(cmd aligned) - Command", color="#2ca02c")
        ax2.axhline(0, color="#666666", lw=1)
        ax2.set_ylabel("Diff (Nm)")
        ax2.grid(True)

        vel_rad = np.deg2rad(vel)
        power = raw_f * vel_rad
        power_valid = power[np.isfinite(power)]
        pos = power_valid[power_valid > 0]
        neg = power_valid[power_valid < 0]
        pos_sum = float(np.sum(pos)) if len(pos) else 0.0
        neg_sum = float(np.sum(neg)) if len(neg) else 0.0
        denom = float(np.sum(np.abs(power_valid))) if len(power_valid) else 0.0
        ratio = (pos_sum / denom) if denom > 0 else 0.0

        ax3.plot(t, power, label="Power (Command)", color="#9467bd")
        ax3.fill_between(t, 0, power, where=(power >= 0), color="#2ca02c", alpha=0.30)
        ax3.fill_between(t, 0, power, where=(power < 0), color="#d62728", alpha=0.30)
        ax3.axhline(0, color="#666666", lw=1)
        ax3.set_ylabel("Power (W, vel in rad/s)")
        ax3.set_xlabel("Time (s)")
        ax3.grid(True)

        delay_ms = float(self.delay_spin.value())
        fd_text = "N/A" if filter_delay_ms is None else f"{filter_delay_ms:.1f} ms"
        self.stats_label.setText(
            "Positive power sum: {:.3f}\n"
            "Negative power sum: {:.3f}\n"
            "Positive power ratio: {:.3f}\n"
            "Power uses vel(rad/s)\n"
            "Manual delay: {:.1f} ms\n"
            "Filter delay: {}\n".format(pos_sum, neg_sum, ratio, delay_ms, fd_text)
        )

        self.figure.tight_layout()
        self.canvas.draw()
