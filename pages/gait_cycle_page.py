#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
from dataclasses import dataclass

import numpy as np
import pandas as pd

from PyQt5 import QtWidgets
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QStyle

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure

try:
    from utils import detect_cycle_peaks_from_angle, normalize_cycles_by_peaks, mean_and_band, lowpass_filter
except Exception:  # pragma: no cover
    detect_cycle_peaks_from_angle = None
    normalize_cycles_by_peaks = None
    mean_and_band = None
    lowpass_filter = None


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


@dataclass
class GaitProfile:
    angle: tuple
    vel: tuple
    torque: tuple
    power: tuple


class GaitCyclePage(QtWidgets.QWidget):
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

        mode_group = QtWidgets.QWidget()
        mode_group.setObjectName("sectionPanel")
        mode_group_layout = QtWidgets.QVBoxLayout(mode_group)
        mode_group_layout.setContentsMargins(10, 10, 10, 10)
        mode_group_layout.setSpacing(6)
        mode_title = QtWidgets.QLabel("Compare Mode")
        mode_title.setObjectName("sectionTitle")
        mode_group_layout.addWidget(mode_title)
        mode_layout = QtWidgets.QVBoxLayout()
        mode_group_layout.addLayout(mode_layout)
        self.mode_tags = QtWidgets.QCheckBox("Compare tags within one file")
        self.mode_files = QtWidgets.QCheckBox("Compare files for one tag")
        self.mode_tags.setChecked(True)
        self.mode_files.setChecked(False)
        mode_layout.addWidget(self.mode_tags)
        mode_layout.addWidget(self.mode_files)

        file_group = QtWidgets.QWidget()
        file_group.setObjectName("sectionPanel")
        file_group_layout = QtWidgets.QVBoxLayout(file_group)
        file_group_layout.setContentsMargins(10, 10, 10, 10)
        file_group_layout.setSpacing(6)
        file_title = QtWidgets.QLabel("Files")
        file_title.setObjectName("sectionTitle")
        file_group_layout.addWidget(file_title)
        file_layout = QtWidgets.QVBoxLayout()
        file_group_layout.addLayout(file_layout)
        self.file_combo = QtWidgets.QComboBox()
        self.file_list = QtWidgets.QListWidget()
        self.file_list.setMaximumHeight(120)
        file_layout.addWidget(QtWidgets.QLabel("Single file (tag compare):"))
        file_layout.addWidget(self.file_combo)
        file_layout.addWidget(QtWidgets.QLabel("Multi file (tag fixed):"))
        file_layout.addWidget(self.file_list)

        tag_group = QtWidgets.QWidget()
        tag_group.setObjectName("sectionPanel")
        tag_group_layout = QtWidgets.QVBoxLayout(tag_group)
        tag_group_layout.setContentsMargins(10, 10, 10, 10)
        tag_group_layout.setSpacing(6)
        tag_title = QtWidgets.QLabel("Tags")
        tag_title.setObjectName("sectionTitle")
        tag_group_layout.addWidget(tag_title)
        tag_layout = QtWidgets.QVBoxLayout()
        tag_group_layout.addLayout(tag_layout)
        self.tag_list = QtWidgets.QListWidget()
        self.tag_list.setMaximumHeight(140)
        self.tag_combo = QtWidgets.QComboBox()
        tag_layout.addWidget(QtWidgets.QLabel("Multi tag (one file):"))
        tag_layout.addWidget(self.tag_list)
        tag_layout.addWidget(QtWidgets.QLabel("Single tag (multi file):"))
        tag_layout.addWidget(self.tag_combo)

        option_group = QtWidgets.QWidget()
        option_group.setObjectName("sectionPanel")
        option_group_layout = QtWidgets.QVBoxLayout(option_group)
        option_group_layout.setContentsMargins(10, 10, 10, 10)
        option_group_layout.setSpacing(6)
        option_title = QtWidgets.QLabel("Options")
        option_title.setObjectName("sectionTitle")
        option_group_layout.addWidget(option_title)
        option_layout = QtWidgets.QGridLayout()
        option_group_layout.addLayout(option_layout)
        self.leg_combo = QtWidgets.QComboBox()
        self.leg_combo.addItems(["left", "right"])
        self.samples_spin = QtWidgets.QSpinBox()
        self.samples_spin.setRange(50, 500)
        self.samples_spin.setValue(101)
        self.show_band = QtWidgets.QCheckBox("Show min/max band")
        self.show_band.setChecked(True)
        self.band_combo = QtWidgets.QComboBox()
        self.band_combo.addItems(["std","minmax", "p05p95"])
        self.min_cycle_spin = QtWidgets.QDoubleSpinBox()
        self.min_cycle_spin.setDecimals(2)
        self.min_cycle_spin.setSingleStep(0.05)
        self.min_cycle_spin.setRange(0.2, 5.0)
        self.min_cycle_spin.setValue(0.6)
        self.max_cycle_spin = QtWidgets.QDoubleSpinBox()
        self.max_cycle_spin.setDecimals(2)
        self.max_cycle_spin.setSingleStep(0.05)
        self.max_cycle_spin.setRange(0.4, 10.0)
        self.max_cycle_spin.setValue(1.6)
        self.prom_spin = QtWidgets.QDoubleSpinBox()
        self.prom_spin.setDecimals(2)
        self.prom_spin.setSingleStep(0.1)
        self.prom_spin.setRange(0.0, 10.0)
        self.prom_spin.setValue(1.0)
        self.filter_vel = QtWidgets.QCheckBox("Low-pass velocity")
        self.filter_vel.setChecked(False)
        self.filter_power = QtWidgets.QCheckBox("Low-pass power")
        self.filter_power.setChecked(False)
        self.filter_cutoff = QtWidgets.QDoubleSpinBox()
        self.filter_cutoff.setDecimals(2)
        self.filter_cutoff.setSingleStep(0.5)
        self.filter_cutoff.setRange(0.5, 50.0)
        self.filter_cutoff.setValue(6.0)
        option_layout.addWidget(QtWidgets.QLabel("Leg:"), 0, 0)
        option_layout.addWidget(self.leg_combo, 0, 1)
        option_layout.addWidget(QtWidgets.QLabel("Samples:"), 1, 0)
        option_layout.addWidget(self.samples_spin, 1, 1)
        option_layout.addWidget(QtWidgets.QLabel("Band type:"), 2, 0)
        option_layout.addWidget(self.band_combo, 2, 1)
        option_layout.addWidget(QtWidgets.QLabel("Min cycle (s):"), 3, 0)
        option_layout.addWidget(self.min_cycle_spin, 3, 1)
        option_layout.addWidget(QtWidgets.QLabel("Max cycle (s):"), 4, 0)
        option_layout.addWidget(self.max_cycle_spin, 4, 1)
        option_layout.addWidget(QtWidgets.QLabel("Peak prominence:"), 5, 0)
        option_layout.addWidget(self.prom_spin, 5, 1)
        option_layout.addWidget(self.filter_vel, 6, 0, 1, 2)
        option_layout.addWidget(self.filter_power, 7, 0, 1, 2)
        option_layout.addWidget(QtWidgets.QLabel("Filter cutoff (Hz):"), 8, 0)
        option_layout.addWidget(self.filter_cutoff, 8, 1)
        option_layout.addWidget(self.show_band, 9, 0, 1, 2)

        self.plot_btn = QtWidgets.QPushButton("Plot Gait Cycles")
        self.save_name = QtWidgets.QLineEdit("gait_cycle")
        self.save_btn = QtWidgets.QPushButton("Save PDF")

        controls_layout.addWidget(mode_group)
        controls_layout.addWidget(file_group)
        controls_layout.addWidget(tag_group)
        controls_layout.addWidget(option_group)
        controls_layout.addWidget(self.plot_btn)
        controls_layout.addWidget(self.save_name)
        controls_layout.addWidget(self.save_btn)
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

        self.mode_tags.toggled.connect(self._sync_modes)
        self.mode_files.toggled.connect(self._sync_modes)
        self.file_combo.currentTextChanged.connect(self._on_file_change)
        self.plot_btn.clicked.connect(self.plot)

    def refresh_data(self):
        self.cache = {}
        self._refresh_files()
        self.save_btn.clicked.connect(self.save_pdf)

        self.plot_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.save_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogSaveButton))

    def _sync_modes(self):
        if self.sender() is self.mode_tags and self.mode_tags.isChecked():
            self.mode_files.setChecked(False)
        if self.sender() is self.mode_files and self.mode_files.isChecked():
            self.mode_tags.setChecked(False)
        if not self.mode_tags.isChecked() and not self.mode_files.isChecked():
            self.mode_tags.setChecked(True)

    def _refresh_files(self):
        self.file_combo.clear()
        self.file_list.clear()
        data_dir = self.data_dir_provider()
        if not os.path.isdir(data_dir):
            return
        files = sorted([f for f in os.listdir(data_dir) if f.lower().endswith(".csv")])
        self.file_combo.addItems(files)
        for f in files:
            item = QtWidgets.QListWidgetItem(f)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.file_list.addItem(item)
        if files:
            self.file_combo.setCurrentIndex(0)
            self._on_file_change(files[0])

    def _on_file_change(self, name):
        if not name:
            return
        data_dir = self.data_dir_provider()
        path = os.path.join(data_dir, name)
        df = self._load_df(path)
        self._populate_tags_from_df(df)

    def _populate_tags_from_df(self, df):
        self.tag_list.clear()
        self.tag_combo.clear()
        if df is None or "tag" not in df.columns:
            return
        tags = [str(t) for t in pd.Series(df["tag"]).dropna().unique().tolist()]
        tags = sorted(tags)
        for t in tags:
            item = QtWidgets.QListWidgetItem(t)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.tag_list.addItem(item)
        self.tag_combo.addItems(tags)

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
            df = pd.read_csv(path)
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

    def _get_selected_files(self):
        files = []
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if item.checkState() == Qt.Checked:
                files.append(item.text())
        return files

    def _get_selected_tags(self):
        tags = []
        for i in range(self.tag_list.count()):
            item = self.tag_list.item(i)
            if item.checkState() == Qt.Checked:
                tags.append(item.text())
        return tags

    def _compute_profile(self, df, tag, leg, n=200):
        if df is None or "tag" not in df.columns:
            return None
        dfx = df[df["tag"].astype(str) == str(tag)].reset_index(drop=True)
        if len(dfx) < 30:
            return None
        t = dfx["t_sec"].to_numpy(dtype=float) if "t_sec" in dfx.columns else make_time_axis(dfx["Time_ms"])
        if leg == "left":
            angle = pd.to_numeric(dfx.get("imu_LTx"), errors="coerce").to_numpy(dtype=float)
            vel = pd.to_numeric(dfx.get("imu_Lvel"), errors="coerce").to_numpy(dtype=float)
            torque = pd.to_numeric(dfx.get("M2_torque_command"), errors="coerce").to_numpy(dtype=float)
        else:
            angle = pd.to_numeric(dfx.get("imu_RTx"), errors="coerce").to_numpy(dtype=float)
            vel = pd.to_numeric(dfx.get("imu_Rvel"), errors="coerce").to_numpy(dtype=float)
            torque = pd.to_numeric(dfx.get("M1_torque_command"), errors="coerce").to_numpy(dtype=float)

        if detect_cycle_peaks_from_angle is None or normalize_cycles_by_peaks is None or mean_and_band is None:
            return None

        fs = estimate_fs_from_time(dfx["Time_ms"]) if "Time_ms" in dfx.columns else 100.0
        min_cycle = float(self.min_cycle_spin.value())
        max_cycle = float(self.max_cycle_spin.value())
        prominence = float(self.prom_spin.value())

        if self.filter_vel.isChecked() and lowpass_filter is not None:
            vel = lowpass_filter(vel, cutoff=float(self.filter_cutoff.value()), fs=fs, order=4)

        vel_rad = np.deg2rad(vel)
        power = torque * vel_rad
        if self.filter_power.isChecked() and lowpass_filter is not None:
            power = lowpass_filter(power, cutoff=float(self.filter_cutoff.value()), fs=fs, order=4)

        peaks = detect_cycle_peaks_from_angle(angle, fs, min_cycle_sec=min_cycle, prominence=prominence)
        if peaks is None or len(peaks) < 2:
            return None

        ang_cycles, _ = normalize_cycles_by_peaks(angle, peaks, fs, n_points=n, min_cycle_sec=min_cycle, max_cycle_sec=max_cycle)
        vel_cycles, _ = normalize_cycles_by_peaks(vel, peaks, fs, n_points=n, min_cycle_sec=min_cycle, max_cycle_sec=max_cycle)
        tor_cycles, _ = normalize_cycles_by_peaks(torque, peaks, fs, n_points=n, min_cycle_sec=min_cycle, max_cycle_sec=max_cycle)
        pow_cycles, _ = normalize_cycles_by_peaks(power, peaks, fs, n_points=n, min_cycle_sec=min_cycle, max_cycle_sec=max_cycle)

        if len(ang_cycles) == 0 or len(vel_cycles) == 0 or len(tor_cycles) == 0 or len(pow_cycles) == 0:
            return None

        band = self.band_combo.currentText()
        return GaitProfile(
            angle=mean_and_band(ang_cycles, band=band),
            vel=mean_and_band(vel_cycles, band=band),
            torque=mean_and_band(tor_cycles, band=band),
            power=mean_and_band(pow_cycles, band=band),
        )

    def plot(self):
        self.figure.clear()
        ax1 = self.figure.add_subplot(411)
        ax2 = self.figure.add_subplot(412, sharex=ax1)
        ax3 = self.figure.add_subplot(413, sharex=ax1)
        ax4 = self.figure.add_subplot(414, sharex=ax1)

        data_dir = self.data_dir_provider()
        leg = self.leg_combo.currentText()
        n = int(self.samples_spin.value())
        show_band = self.show_band.isChecked()

        series = []

        if self.mode_tags.isChecked():
            file_name = self.file_combo.currentText().strip()
            if not file_name:
                self.canvas.draw()
                return
            tags = self._get_selected_tags()
            if not tags:
                self.canvas.draw()
                return
            df = self._load_df(os.path.join(data_dir, file_name))
            for tag in tags:
                prof = self._compute_profile(df, tag, leg, n)
                if prof:
                    series.append((f"{file_name}:{tag}", prof))
        else:
            files = self._get_selected_files()
            tag = self.tag_combo.currentText().strip()
            if not files or not tag:
                self.canvas.draw()
                return
            for f in files:
                df = self._load_df(os.path.join(data_dir, f))
                prof = self._compute_profile(df, tag, leg, n)
                if prof:
                    series.append((f"{f}:{tag}", prof))

        if not series:
            self.canvas.draw()
            return

        x = np.linspace(0, 100, n, endpoint=False)
        for label, prof in series:
            ang_m, ang_min, ang_max = prof.angle
            vel_m, vel_min, vel_max = prof.vel
            tor_m, tor_min, tor_max = prof.torque
            pow_m, pow_min, pow_max = prof.power
            ax1.plot(x, ang_m, label=label)
            ax2.plot(x, vel_m, label=label)
            ax3.plot(x, tor_m, label=label)
            ax4.plot(x, pow_m, label=label)
            if show_band:
                ax1.fill_between(x, ang_min, ang_max, alpha=0.15)
                ax2.fill_between(x, vel_min, vel_max, alpha=0.15)
                ax3.fill_between(x, tor_min, tor_max, alpha=0.15)
                ax4.fill_between(x, pow_min, pow_max, alpha=0.15)

        ax1.set_ylabel("Angle (deg)")
        ax2.set_ylabel("Velocity")
        ax3.set_ylabel("Torque (Nm)")
        ax4.set_ylabel("Power (W)")
        ax4.set_xlabel("Gait Cycle (%)")
        ax1.grid(True)
        ax2.grid(True)
        ax3.grid(True)
        ax4.grid(True)
        ax1.legend(loc="upper right")

        self.figure.tight_layout()
        self.canvas.draw()

    def save_pdf(self):
        name = self.save_name.text().strip() or "gait_cycle"
        out_dir = os.path.join(os.path.dirname(__file__), "..", "output")
        out_dir = os.path.abspath(out_dir)
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"{name}.pdf")
        self.figure.savefig(path, format="pdf", dpi=300, bbox_inches="tight")
