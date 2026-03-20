#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import shutil
from dataclasses import dataclass

import numpy as np
import pandas as pd

from PyQt5 import QtCore, QtWidgets
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QPalette, QColor
from PyQt5.QtWidgets import QStyle

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure

try:
    from scipy.signal import savgol_filter, butter, filtfilt
except Exception:  # pragma: no cover - optional at runtime
    savgol_filter = None
    butter = None
    filtfilt = None

from src.pages.gait_cycle_page import GaitCyclePage
from src.pages.filter_delay_page import FilterDelayPage
from src.pages.report_page import ReportPage


DEFAULT_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
MAPPING_FILENAME = ".column_mapping.json"


def make_time_axis(time_series: pd.Series) -> np.ndarray:
    """
    将 Time 列统一转换为以秒为单位、从 0 开始的时间轴。
    支持：全数字（可能是毫秒）、时间戳字符串、其他无法识别时退化为行号。
    """
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




def lowpass_butter(x, fs, fc=6.0, order=2):
    if butter is None or filtfilt is None:
        return x
    if fs <= 0 or len(x) < 5:
        return x
    wn = fc / (fs / 2.0)
    if wn >= 1.0:
        return x
    b, a = butter(order, wn, btype="low")
    pad = 3 * max(len(a), len(b))
    if len(x) <= pad:
        return x
    return filtfilt(b, a, x)


@dataclass
class DataBundle:
    df: pd.DataFrame
    time_s: np.ndarray
    tags: list


class ColumnMappingDialog(QtWidgets.QDialog):
    def __init__(self, parent, columns, current_map):
        super().__init__(parent)
        self.setWindowTitle("Column Mapping")
        self.resize(520, 420)
        self.columns = ["<None>"] + list(columns)
        self.combos = {}

        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()

        fields = [
            ("Time_ms", "Time (required)"),
            ("imu_LTx", "Left Angle"),
            ("imu_RTx", "Right Angle"),
            ("imu_Lvel", "Left Velocity"),
            ("imu_Rvel", "Right Velocity"),
            ("M1_torque_command", "Right Torque"),
            ("M2_torque_command", "Left Torque"),
            ("raw_LExoTorque", "Raw Torque L"),
            ("raw_RExoTorque", "Raw Torque R"),
            ("filtered_LExoTorque", "Filtered Torque L"),
            ("filtered_RExoTorque", "Filtered Torque R"),
            ("L_P", "Left P-term"),
            ("L_D", "Left D-term"),
            ("R_P", "Right P-term"),
            ("R_D", "Right D-term"),
            ("tag", "Tag/Action"),
        ]

        for key, label in fields:
            combo = QtWidgets.QComboBox()
            combo.addItems(self.columns)
            cur = current_map.get(key)
            if cur in self.columns:
                combo.setCurrentText(cur)
            else:
                combo.setCurrentIndex(0)
            self.combos[key] = combo
            form.addRow(label, combo)

        layout.addLayout(form)

        note = QtWidgets.QLabel("Note: At minimum, Time_ms / imu_LTx / imu_RTx / imu_Lvel / imu_Rvel are required.")
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_mapping(self):
        mapping = {}
        for key, combo in self.combos.items():
            val = combo.currentText()
            if val != "<None>":
                mapping[key] = val
        return mapping


class MMEAnalyzer(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Hip Exo Data Analyzer (v1.0)")
        self.resize(1300, 820)

        self.data_bundle = None
        self.current_path = None
        self.data_dir = DEFAULT_DATA_DIR
        self.raw_df = None
        self.column_map = {}
        self.all_columns = []

        self._build_ui()
        self._apply_theme()
        self._load_default_dataset()

    # ---------------------- UI ----------------------
    def _build_ui(self):
        splitter = QtWidgets.QSplitter(Qt.Horizontal)
        self.setCentralWidget(splitter)

        # Tabs
        self.tabs = QtWidgets.QTabWidget()
        splitter.addWidget(self.tabs)

        # -------- Tab 1: Main Analyzer --------
        main_tab = QtWidgets.QWidget()
        main_layout = QtWidgets.QHBoxLayout(main_tab)
        main_layout.setContentsMargins(0, 0, 0, 0)

        controls = QtWidgets.QWidget()
        controls_layout = QtWidgets.QVBoxLayout(controls)
        controls_layout.setContentsMargins(8, 8, 8, 8)
        controls_layout.setSpacing(8)

        # File controls
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
        self.dataset_combo = QtWidgets.QComboBox()
        self.refresh_button = QtWidgets.QPushButton("Refresh List")
        self.load_button = QtWidgets.QPushButton("Load")
        self.map_button = QtWidgets.QPushButton("Column Mapping")
        self.file_label = QtWidgets.QLabel("No file loaded")
        self.file_label.setWordWrap(True)

        self.folder_edit = QtWidgets.QLineEdit(self.data_dir)
        self.folder_browse = QtWidgets.QPushButton("Browse...")
        self.folder_apply = QtWidgets.QPushButton("Use Folder")
        self.folder_edit.setMinimumWidth(320)

        file_layout.addWidget(QtWidgets.QLabel("Data Folder:"), 0, 0)
        file_layout.addWidget(self.folder_edit, 0, 1)
        file_layout.addWidget(self.folder_browse, 1, 0)
        file_layout.addWidget(self.folder_apply, 1, 1)

        file_layout.addWidget(QtWidgets.QLabel("Sample CSV:"), 2, 0)
        file_layout.addWidget(self.dataset_combo, 2, 1, 1, 2)
        file_layout.addWidget(self.refresh_button, 3, 0)
        file_layout.addWidget(self.load_button, 3, 1)
        file_layout.addWidget(self.map_button, 3, 2)
        file_layout.addWidget(self.file_label, 4, 0, 1, 3)

        # Filters
        filter_group = QtWidgets.QWidget()
        filter_group.setObjectName("sectionPanel")
        filter_group_layout = QtWidgets.QVBoxLayout(filter_group)
        filter_group_layout.setContentsMargins(10, 10, 10, 10)
        filter_group_layout.setSpacing(6)
        filter_title = QtWidgets.QLabel("Filters")
        filter_title.setObjectName("sectionTitle")
        filter_group_layout.addWidget(filter_title)
        filter_layout = QtWidgets.QGridLayout()
        filter_group_layout.addLayout(filter_layout)
        self.tag_combo = QtWidgets.QComboBox()
        self.tag_combo.setEditable(False)

        self.start_spin = QtWidgets.QDoubleSpinBox()
        self.end_spin = QtWidgets.QDoubleSpinBox()
        self.start_spin.setDecimals(3)
        self.end_spin.setDecimals(3)
        self.start_spin.setSingleStep(0.1)
        self.end_spin.setSingleStep(0.1)
        self.full_range_btn = QtWidgets.QPushButton("Full Range")

        self.window_spin = QtWidgets.QDoubleSpinBox()
        self.window_spin.setDecimals(3)
        self.window_spin.setSingleStep(0.1)
        self.window_spin.setRange(0.1, 3600.0)
        self.window_spin.setValue(5.0)
        self.pan_slider = QtWidgets.QSlider(Qt.Horizontal)
        self.pan_slider.setRange(0, 1000)
        self.pan_slider.setValue(0)

        filter_layout.addWidget(QtWidgets.QLabel("Action/Tag:"), 0, 0)
        filter_layout.addWidget(self.tag_combo, 0, 1, 1, 2)
        self.start_slider = QtWidgets.QSlider(Qt.Horizontal)
        self.end_slider = QtWidgets.QSlider(Qt.Horizontal)
        self.start_slider.setRange(0, 1000)
        self.end_slider.setRange(0, 1000)
        self.start_slider.setValue(0)
        self.end_slider.setValue(1000)

        filter_layout.addWidget(QtWidgets.QLabel("Start (s):"), 1, 0)
        filter_layout.addWidget(self.start_spin, 1, 1)
        filter_layout.addWidget(QtWidgets.QLabel("End (s):"), 2, 0)
        filter_layout.addWidget(self.end_spin, 2, 1)
        filter_layout.addWidget(self.full_range_btn, 1, 2, 2, 1)

        filter_layout.addWidget(QtWidgets.QLabel("Start Slider:"), 3, 0)
        filter_layout.addWidget(self.start_slider, 3, 1, 1, 2)
        filter_layout.addWidget(QtWidgets.QLabel("End Slider:"), 4, 0)
        filter_layout.addWidget(self.end_slider, 4, 1, 1, 2)
        filter_layout.addWidget(QtWidgets.QLabel("Window (s):"), 5, 0)
        filter_layout.addWidget(self.window_spin, 5, 1)
        filter_layout.addWidget(QtWidgets.QLabel("Pan:"), 6, 0)
        filter_layout.addWidget(self.pan_slider, 6, 1, 1, 2)

        # Options
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
        self.scale_spin = QtWidgets.QDoubleSpinBox()
        self.scale_spin.setDecimals(2)
        self.scale_spin.setSingleStep(1.0)
        self.scale_spin.setRange(1.0, 200.0)
        self.scale_spin.setValue(5.0)
        self.global_lowpass = QtWidgets.QCheckBox("Low-pass (Vel/P/D/Power)")
        self.global_lowpass.setChecked(True)
        self.lowpass_cutoff = QtWidgets.QDoubleSpinBox()
        self.lowpass_cutoff.setDecimals(2)
        self.lowpass_cutoff.setSingleStep(0.5)
        self.lowpass_cutoff.setRange(0.5, 50.0)
        self.lowpass_cutoff.setValue(6.0)
        self.fs_spin = QtWidgets.QDoubleSpinBox()
        self.fs_spin.setDecimals(2)
        self.fs_spin.setSingleStep(1.0)
        self.fs_spin.setRange(0.0, 5000.0)
        self.fs_spin.setValue(100.0)
        self.fs_spin.setToolTip("Default 100 Hz; set 0 for auto from time axis")
        self.invert_check = QtWidgets.QCheckBox("Invert Signals (except Power)")
        self.invert_check.setChecked(False)
        self.flexion_label = QtWidgets.QLabel("Flexion sign: Negative")

        option_layout.addWidget(QtWidgets.QLabel("Velocity Scale:"), 0, 0)
        option_layout.addWidget(self.scale_spin, 0, 1)
        option_layout.addWidget(self.global_lowpass, 1, 0, 1, 2)
        option_layout.addWidget(QtWidgets.QLabel("Cutoff (Hz):"), 2, 0)
        option_layout.addWidget(self.lowpass_cutoff, 2, 1)
        option_layout.addWidget(QtWidgets.QLabel("FS (Hz, 0=auto):"), 3, 0)
        option_layout.addWidget(self.fs_spin, 3, 1)
        option_layout.addWidget(self.invert_check, 4, 0, 1, 2)
        option_layout.addWidget(self.flexion_label, 5, 0, 1, 2)

        # Curve selection
        curve_group = QtWidgets.QWidget()
        curve_group.setObjectName("sectionPanel")
        curve_group_layout = QtWidgets.QVBoxLayout(curve_group)
        curve_group_layout.setContentsMargins(10, 10, 10, 10)
        curve_group_layout.setSpacing(6)
        curve_title = QtWidgets.QLabel("Curves")
        curve_title.setObjectName("sectionTitle")
        curve_group_layout.addWidget(curve_title)
        curve_layout = QtWidgets.QVBoxLayout()
        curve_group_layout.addLayout(curve_layout)
        self.curve_checks = {}
        self.curve_area = QtWidgets.QScrollArea()
        self.curve_area.setWidgetResizable(True)
        self.curve_area.setMinimumHeight(260)
        self.curve_widget = QtWidgets.QWidget()
        self.curve_widget_layout = QtWidgets.QVBoxLayout(self.curve_widget)
        self.curve_widget_layout.setAlignment(Qt.AlignTop)
        self.curve_area.setWidget(self.curve_widget)
        curve_layout.addWidget(self.curve_area)

        # Save
        save_group = QtWidgets.QWidget()
        save_group.setObjectName("sectionPanel")
        save_group_layout = QtWidgets.QVBoxLayout(save_group)
        save_group_layout.setContentsMargins(10, 10, 10, 10)
        save_group_layout.setSpacing(6)
        save_title = QtWidgets.QLabel("Save Figure")
        save_title.setObjectName("sectionTitle")
        save_group_layout.addWidget(save_title)
        save_layout = QtWidgets.QHBoxLayout()
        save_group_layout.addLayout(save_layout)
        self.save_name = QtWidgets.QLineEdit("figure")
        self.save_btn = QtWidgets.QPushButton("Save PDF")
        save_layout.addWidget(self.save_name)
        save_layout.addWidget(self.save_btn)

        # Plot button
        self.plot_btn = QtWidgets.QPushButton("Update Plot")

        controls_layout.addWidget(file_group)
        controls_layout.addWidget(filter_group)
        controls_layout.addWidget(option_group)
        controls_layout.addWidget(curve_group)
        controls_layout.addWidget(save_group)
        controls_layout.addWidget(self.plot_btn)
        controls_layout.addStretch(1)

        # Panels styled by object name (sectionPanel/sectionTitle)

        # Right panel: plot
        plot_widget = QtWidgets.QWidget()
        plot_layout = QtWidgets.QVBoxLayout(plot_widget)
        self.figure = Figure(figsize=(8, 5))
        self.canvas = FigureCanvas(self.figure)
        self.toolbar = NavigationToolbar(self.canvas, self)
        plot_layout.addWidget(self.toolbar)
        plot_layout.addWidget(self.canvas, 1)

        main_layout.addWidget(controls)
        main_layout.addWidget(plot_widget, 1)
        self.tabs.addTab(main_tab, "Analyzer")

        # -------- Tab 2: Gait Cycle Analyzer --------
        gait_tab = GaitCyclePage(
            data_dir_provider=lambda: self.data_dir,
            mapping_path_provider=self._mapping_config_path,
        )
        self.tabs.addTab(gait_tab, "Gait Cycle")

        # -------- Tab 3: Filter-Delay Analyzer --------
        delay_tab = FilterDelayPage(
            data_dir_provider=lambda: self.data_dir,
            mapping_path_provider=self._mapping_config_path,
        )
        self.tabs.addTab(delay_tab, "Filter-Delay")

        # -------- Tab 4: Report --------
        report_tab = ReportPage(
            data_dir_provider=lambda: self.data_dir,
            mapping_path_provider=self._mapping_config_path,
        )
        self.tabs.addTab(report_tab, "Report")

        splitter.setStretchFactor(0, 1)

        # Signals
        self.refresh_button.clicked.connect(self._refresh_dataset_list)
        self.load_button.clicked.connect(self._load_selected_dataset)
        self.folder_browse.clicked.connect(self._browse_folder)
        self.folder_apply.clicked.connect(self._apply_folder)
        self.map_button.clicked.connect(self._on_mapping_clicked)
        self.full_range_btn.clicked.connect(self._set_full_range)
        self.plot_btn.clicked.connect(self.update_plot)
        self.save_btn.clicked.connect(self.save_figure)
        self.start_spin.valueChanged.connect(self._clamp_range)
        self.end_spin.valueChanged.connect(self._clamp_range)
        self.start_slider.valueChanged.connect(self._slider_changed)
        self.end_slider.valueChanged.connect(self._slider_changed)
        self.window_spin.valueChanged.connect(self._window_changed)
        self.pan_slider.valueChanged.connect(self._pan_changed)
        self.tag_combo.currentTextChanged.connect(self._on_tag_changed)
        self.scale_spin.valueChanged.connect(self._recompute_velocity)
        self.global_lowpass.toggled.connect(self.update_plot)
        self.lowpass_cutoff.valueChanged.connect(self.update_plot)
        self.fs_spin.valueChanged.connect(self.update_plot)
        self.invert_check.toggled.connect(self._on_invert_toggled)

        self._refresh_dataset_list()

        # Icons
        self.refresh_button.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        self.load_button.setIcon(self.style().standardIcon(QStyle.SP_DialogOpenButton))
        self.map_button.setIcon(self.style().standardIcon(QStyle.SP_FileDialogDetailedView))
        self.folder_browse.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        self.folder_apply.setIcon(self.style().standardIcon(QStyle.SP_DialogApplyButton))
        self.plot_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.save_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogSaveButton))

    def _apply_theme(self):
        self.setFont(QFont("Segoe UI", 10))
        pal = QPalette()
        pal.setColor(QPalette.Window, QColor("#F8F5FF"))
        pal.setColor(QPalette.WindowText, QColor("#1C1B1F"))
        pal.setColor(QPalette.Base, QColor("#FFFFFF"))
        pal.setColor(QPalette.AlternateBase, QColor("#F2EDFF"))
        pal.setColor(QPalette.Text, QColor("#1C1B1F"))
        pal.setColor(QPalette.Button, QColor("#FFFFFF"))
        pal.setColor(QPalette.ButtonText, QColor("#1C1B1F"))
        pal.setColor(QPalette.Highlight, QColor("#6750A4"))
        pal.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
        self.setPalette(pal)
        self.setStyleSheet(
            """
            QWidget { color: #1C1B1F; }
            QGroupBox {
                background: #FFFFFF;
                border: 1px solid #E7E1F0;
                border-radius: 16px;
                margin-top: 12px;
            }
            QWidget#sectionPanel {
                background: #FFFFFF;
                border: 1px solid #E7E1F0;
                border-radius: 16px;
            }
            QLabel#sectionTitle {
                color: #1F1B2E;
                font-weight: 700;
                font-size: 12pt;
                background: #EDE7F6;
                border-radius: 6px;
                padding: 2px 8px;
            }
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
                background: #FFFFFF;
                border: 1px solid #E7E1F0;
                border-radius: 12px;
                padding: 8px 12px;
            }
            QPushButton {
                background: #EEE7FF;
                color: #1C1B1F;
                border: 1px solid #D0C7E8;
                border-radius: 14px;
                padding: 8px 14px;
            }
            QPushButton:pressed { background: #E0D7FA; }
            QPushButton:hover { border: 1px solid #B5A8E0; }
            QTabWidget::pane { border: none; }
            QTabBar::tab {
                background: #F2EDFF;
                border-radius: 14px;
                padding: 8px 16px;
                margin-right: 6px;
            }
            QTabBar::tab:selected {
                background: #FFFFFF;
                border: 1px solid #D0C7E8;
            }
            QSlider::groove:horizontal {
                height: 6px;
                background: #E7E1F0;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                width: 16px;
                margin: -5px 0;
                border-radius: 8px;
                background: #4E6E81;
                border: 1px solid #3E5C6B;
            }
            QScrollBar:vertical {
                background: #F2EDFF;
                width: 10px;
                margin: 2px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background: #D0C7E8;
                min-height: 20px;
                border-radius: 5px;
            }
            """
        )

    # ---------------------- Data ----------------------
    def _refresh_dataset_list(self):
        self.dataset_combo.clear()
        if not os.path.isdir(self.data_dir):
            return
        items = sorted([f for f in os.listdir(self.data_dir) if f.lower().endswith(".csv")])
        self.dataset_combo.addItems(items)
        self.all_columns = self._collect_columns_from_dir()

    def _load_default_dataset(self):
        if self.dataset_combo.count() == 0:
            self._refresh_dataset_list()
        if self.dataset_combo.count() > 0:
            self.dataset_combo.setCurrentIndex(0)
            self._load_selected_dataset()

    def _load_selected_dataset(self):
        name = self.dataset_combo.currentText().strip()
        if not name:
            return
        path = os.path.join(self.data_dir, name)
        self.load_csv(path)

    def _browse_folder(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Data Folder", self.data_dir)
        if path:
            self.folder_edit.setText(path)
            self._apply_folder()

    def _apply_folder(self):
        path = self.folder_edit.text().strip()
        if not path:
            return
        if not os.path.isdir(path):
            self.statusBar().showMessage(f"Folder not found: {path}", 5000)
            return
        self.data_dir = path
        self._refresh_dataset_list()
        # Notify subpages to reload data from new folder
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if hasattr(w, "refresh_data"):
                w.refresh_data()
        self._load_default_dataset()

    def load_csv(self, path):
        if not os.path.exists(path):
            self.statusBar().showMessage(f"File not found: {path}", 5000)
            return
        df = pd.read_csv(path)
        self.raw_df = df
        if not self.all_columns:
            self.all_columns = self._collect_columns_from_dir()
        if not self.all_columns:
            self.all_columns = list(df.columns)

        saved_map = self._load_mapping_config()
        if saved_map:
            self.column_map = saved_map
        else:
            self.column_map = self._init_column_map(self.all_columns)
        if not self._validate_column_map():
            if not self._open_mapping_dialog():
                self.statusBar().showMessage("Column mapping required. Load canceled.", 5000)
                return
        self._save_mapping_config()
        req_missing, opt_missing = self._missing_columns()
        if req_missing:
            QtWidgets.QMessageBox.critical(
                self,
                "Missing Time Column",
                f"Time column mapping is required but missing: {req_missing}"
            )
            return
        if opt_missing:
            QtWidgets.QMessageBox.warning(
                self,
                "Missing Optional Columns",
                "Some optional columns are not mapped and will be unavailable:\n"
                + ", ".join(opt_missing)
            )

        df = self._apply_column_map(df)
        if "Time_ms" not in df.columns:
            self.statusBar().showMessage("Missing column: Time_ms (after mapping)", 5000)
            return

        time_s = make_time_axis(df["Time_ms"])

        df = df.copy()
        df["t_sec"] = time_s

        tags = []
        if "tag" in df.columns:
            tags = [str(t) for t in pd.Series(df["tag"]).dropna().unique().tolist()]
            tags = sorted(tags)

        self.data_bundle = DataBundle(df=df, time_s=time_s, tags=tags)
        self.current_path = path
        self.file_label.setText(path)
        self._populate_tag_combo()
        self._populate_curve_checks()
        self._set_full_range()
        self.update_plot()

    def _populate_tag_combo(self):
        self.tag_combo.clear()
        self.tag_combo.addItem("all")
        if self.data_bundle and self.data_bundle.tags:
            self.tag_combo.addItems(self.data_bundle.tags)

    def _populate_curve_checks(self):
        for cb in self.curve_checks.values():
            cb.setParent(None)
        self.curve_checks = {}
        self.curve_groups = {}

        if not self.data_bundle:
            return

        df = self.data_bundle.df
        groups = {
            "Angle": ["imu_LTx", "imu_RTx"],
            "Velocity": ["imu_Lvel", "imu_Rvel"],
            "Torque Cmd": ["M1_torque_command", "M2_torque_command"],
            "Raw Torque": ["raw_RExoTorque", "raw_LExoTorque"],
            "Filtered Torque": ["filtered_RExoTorque", "filtered_LExoTorque"],
            "P-term": ["L_P", "R_P"],
            "D-term": ["L_D", "R_D"],
        }
        self.curve_groups = {}

        for label, cols in groups.items():
            if any(col in df.columns for col in cols):
                cb = QtWidgets.QCheckBox(label)
                cb.setChecked(label in ["Angle", "Torque Cmd"])
                cb.stateChanged.connect(self.update_plot)
                self.curve_widget_layout.addWidget(cb)
                self.curve_checks[label] = cb
                self.curve_groups[label] = [c for c in cols if c in df.columns]

        power_cb = QtWidgets.QCheckBox("Power")
        power_cb.setChecked(True)
        power_cb.stateChanged.connect(self.update_plot)
        self.curve_widget_layout.addWidget(power_cb)
        self.curve_checks["__power__"] = power_cb

        self.curve_widget_layout.addStretch(1)

    def _init_column_map(self, columns):
        cols = list(columns)
        lower_map = {c.lower(): c for c in cols}
        synonyms = {
            "Time_ms": ["time_ms", "time", "timestamp", "t", "time_s", "time_sec"],
            "imu_LTx": ["imu_ltx", "l_tx", "left_tx", "left_angle", "angle_l", "l_angle"],
            "imu_RTx": ["imu_rtx", "r_tx", "right_tx", "right_angle", "angle_r", "r_angle"],
            "imu_Lvel": ["imu_lvel", "l_vel", "left_vel", "vel_l", "l_velocity"],
            "imu_Rvel": ["imu_rvel", "r_vel", "right_vel", "vel_r", "r_velocity"],
            "M1_torque_command": ["m1_torque_command", "torque_r", "right_torque", "m1_torque"],
            "M2_torque_command": ["m2_torque_command", "torque_l", "left_torque", "m2_torque"],
            "raw_LExoTorque": ["raw_lexotorque", "raw_l_exotorque", "raw_left_torque", "raw_torque_l"],
            "raw_RExoTorque": ["raw_rexotorque", "raw_r_exotorque", "raw_right_torque", "raw_torque_r"],
            "filtered_LExoTorque": ["filtered_lexotorque", "filt_l_exotorque", "filtered_left_torque", "filtered_torque_l"],
            "filtered_RExoTorque": ["filtered_rexotorque", "filt_r_exotorque", "filtered_right_torque", "filtered_torque_r"],
            "L_P": ["l_p", "lp", "left_p"],
            "L_D": ["l_d", "ld", "left_d"],
            "R_P": ["r_p", "rp", "right_p"],
            "R_D": ["r_d", "rd", "right_d"],
            "tag": ["tag", "label", "action"],
        }
        mapping = {}
        for logical, keys in synonyms.items():
            found = None
            for k in keys:
                if k in lower_map:
                    found = lower_map[k]
                    break
            if found is None and logical in cols:
                found = logical
            if found is not None:
                mapping[logical] = found
        return mapping

    def _validate_column_map(self):
        required = ["Time_ms", "imu_LTx", "imu_RTx", "imu_Lvel", "imu_Rvel"]
        available = set(self.raw_df.columns) if self.raw_df is not None else set()
        for key in required:
            if key not in self.column_map:
                return False
            actual = self.column_map.get(key)
            if actual is None:
                return False
            if available and actual not in available:
                return False
        return True

    def _apply_column_map(self, df):
        df2 = df.copy()
        for logical, actual in self.column_map.items():
            if actual and actual in df2.columns:
                if logical not in df2.columns or logical != actual:
                    df2[logical] = df2[actual]
        return df2

    def _open_mapping_dialog(self):
        if self.raw_df is None:
            return False
        columns = self.all_columns if self.all_columns else list(self.raw_df.columns)
        dialog = ColumnMappingDialog(self, columns, self.column_map)
        ok = dialog.exec_() == QtWidgets.QDialog.Accepted
        if not ok:
            return False
        self.column_map = dialog.get_mapping()
        self._save_mapping_config()
        return True

    def _missing_columns(self):
        required = ["Time_ms"]
        optional = [
            "imu_LTx", "imu_RTx", "imu_Lvel", "imu_Rvel",
            "M1_torque_command", "M2_torque_command",
            "raw_LExoTorque", "raw_RExoTorque",
            "filtered_LExoTorque", "filtered_RExoTorque",
            "L_P", "L_D", "R_P", "R_D",
            "tag",
        ]
        required_missing = []
        optional_missing = []
        available = set(self.raw_df.columns) if self.raw_df is not None else set()
        for k in required:
            actual = self.column_map.get(k)
            if not actual or actual not in available:
                required_missing.append(k)
        for k in optional:
            actual = self.column_map.get(k)
            if not actual or actual not in available:
                optional_missing.append(k)
        return required_missing, optional_missing

    def _on_mapping_clicked(self):
        if self._open_mapping_dialog():
            self._rebuild_from_mapping()

    def _mapping_config_path(self):
        return os.path.join(os.path.dirname(__file__), MAPPING_FILENAME)

    def _legacy_mapping_path(self):
        return os.path.join(self.data_dir, MAPPING_FILENAME)

    def _load_mapping_config(self):
        path = self._mapping_config_path()
        if not os.path.exists(path):
            legacy = self._legacy_mapping_path()
            if os.path.exists(legacy):
                try:
                    shutil.move(legacy, path)
                except Exception:
                    try:
                        shutil.copy2(legacy, path)
                    except Exception:
                        pass
            if not os.path.exists(path):
                return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            return None
        return None

    def _save_mapping_config(self):
        path = self._mapping_config_path()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.column_map, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _collect_columns_from_dir(self):
        if not os.path.isdir(self.data_dir):
            return []
        cols = set()
        for name in os.listdir(self.data_dir):
            if not name.lower().endswith(".csv"):
                continue
            path = os.path.join(self.data_dir, name)
            try:
                tmp = pd.read_csv(path, nrows=1)
                cols.update(list(tmp.columns))
            except Exception:
                continue
        return sorted(cols)

    def _rebuild_from_mapping(self):
        if self.raw_df is None:
            return
        df = self._apply_column_map(self.raw_df)
        if "Time_ms" not in df.columns:
            self.statusBar().showMessage("Missing column: Time_ms (after mapping)", 5000)
            return
        time_s = make_time_axis(df["Time_ms"])
        df = df.copy()
        df["t_sec"] = time_s
        tags = []
        if "tag" in df.columns:
            tags = [str(t) for t in pd.Series(df["tag"]).dropna().unique().tolist()]
            tags = sorted(tags)

        self.data_bundle = DataBundle(df=df, time_s=time_s, tags=tags)
        self._populate_tag_combo()
        self._populate_curve_checks()
        self._set_full_range()
        self.update_plot()

    def _set_full_range(self):
        if not self.data_bundle:
            return
        tmin, tmax = self._get_time_bounds()
        if tmax <= tmin:
            return
        self.start_spin.blockSignals(True)
        self.end_spin.blockSignals(True)
        self.start_spin.setRange(tmin, tmax)
        self.end_spin.setRange(tmin, tmax)
        self.start_spin.setValue(tmin)
        self.end_spin.setValue(tmax)
        self.start_spin.blockSignals(False)
        self.end_spin.blockSignals(False)
        self.window_spin.blockSignals(True)
        self.window_spin.setValue(tmax - tmin)
        self.window_spin.blockSignals(False)
        self.pan_slider.blockSignals(True)
        self.pan_slider.setValue(0)
        self.pan_slider.blockSignals(False)
        self._sync_sliders_from_spins()
        self._sync_pan_from_spins()

    def _clamp_range(self):
        if self.start_spin.value() > self.end_spin.value():
            if self.sender() is self.start_spin:
                self.end_spin.setValue(self.start_spin.value())
            else:
                self.start_spin.setValue(self.end_spin.value())
        self._sync_sliders_from_spins()
        self.update_plot()

    def _get_time_bounds(self):
        if not self.data_bundle:
            return 0.0, 1.0
        df = self.data_bundle.df
        tag_value = self.tag_combo.currentText().strip()
        if tag_value and tag_value != "all" and "tag" in df.columns:
            df = df[df["tag"].astype(str) == tag_value]
        t = df["t_sec"].to_numpy(dtype=float)
        if len(t) == 0:
            return 0.0, 1.0
        return float(np.nanmin(t)), float(np.nanmax(t))

    def _sync_sliders_from_spins(self):
        tmin, tmax = self._get_time_bounds()
        if tmax <= tmin:
            return
        start = self.start_spin.value()
        end = self.end_spin.value()
        start_ratio = (start - tmin) / (tmax - tmin)
        end_ratio = (end - tmin) / (tmax - tmin)
        start_val = int(max(0, min(1000, round(start_ratio * 1000))))
        end_val = int(max(0, min(1000, round(end_ratio * 1000))))
        self.start_slider.blockSignals(True)
        self.end_slider.blockSignals(True)
        self.start_slider.setValue(start_val)
        self.end_slider.setValue(end_val)
        self.start_slider.blockSignals(False)
        self.end_slider.blockSignals(False)

    def _slider_changed(self):
        if not self.data_bundle:
            return
        tmin, tmax = self._get_time_bounds()
        if tmax <= tmin:
            return
        start_val = self.start_slider.value()
        end_val = self.end_slider.value()
        if self.sender() is self.start_slider and start_val > end_val:
            end_val = start_val
            self.end_slider.blockSignals(True)
            self.end_slider.setValue(end_val)
            self.end_slider.blockSignals(False)
        if self.sender() is self.end_slider and end_val < start_val:
            start_val = end_val
            self.start_slider.blockSignals(True)
            self.start_slider.setValue(start_val)
            self.start_slider.blockSignals(False)

        start = tmin + (tmax - tmin) * (start_val / 1000.0)
        end = tmin + (tmax - tmin) * (end_val / 1000.0)
        self.start_spin.blockSignals(True)
        self.end_spin.blockSignals(True)
        self.start_spin.setValue(start)
        self.end_spin.setValue(end)
        self.start_spin.blockSignals(False)
        self.end_spin.blockSignals(False)
        self._sync_pan_from_spins()
        self.update_plot()

    def _on_tag_changed(self, *args):
        self._set_full_range()
        self.update_plot()

    def _on_invert_toggled(self):
        self.flexion_label.setText(
            "Flexion sign: Positive" if self.invert_check.isChecked() else "Flexion sign: Negative"
        )
        self.update_plot()

    def _window_changed(self):
        self._apply_pan_window()
        self.update_plot()

    def _pan_changed(self):
        self._apply_pan_window()
        self.update_plot()

    def _sync_pan_from_spins(self):
        tmin, tmax = self._get_time_bounds()
        if tmax <= tmin:
            return
        window = max(0.001, min(self.window_spin.value(), tmax - tmin))
        self.window_spin.blockSignals(True)
        self.window_spin.setValue(window)
        self.window_spin.blockSignals(False)
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
        if not self.data_bundle:
            return
        tmin, tmax = self._get_time_bounds()
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
        self._sync_sliders_from_spins()

    def _recompute_velocity(self):
        self.update_plot()

    # ---------------------- Plot ----------------------
    def update_plot(self):
        self.figure.clear()
        ax_left = self.figure.add_subplot(211)
        ax_left_r = ax_left.twinx()
        ax_left_p = ax_left.twinx()
        ax_left_p.spines["right"].set_position(("outward", 52))
        ax_left_p.patch.set_visible(False)
        ax_right = self.figure.add_subplot(212, sharex=ax_left)
        ax_right_r = ax_right.twinx()
        ax_right_p = ax_right.twinx()
        ax_right_p.spines["right"].set_position(("outward", 52))
        ax_right_p.patch.set_visible(False)

        if not self.data_bundle:
            self.canvas.draw()
            return

        df = self.data_bundle.df

        # Filter by tag
        tag_value = self.tag_combo.currentText().strip()
        if tag_value and tag_value != "all" and "tag" in df.columns:
            df = df[df["tag"].astype(str) == tag_value]

        if df.empty:
            ax_left.set_title("No data for selected tag")
            self.canvas.draw()
            return

        # Time range
        t0 = self.start_spin.value()
        t1 = self.end_spin.value()
        df = df[(df["t_sec"] >= t0) & (df["t_sec"] <= t1)]
        if df.empty:
            ax_left.set_title("No data in selected time range")
            self.canvas.draw()
            return

        t = df["t_sec"].to_numpy(dtype=float)

        vel_scale = float(self.scale_spin.value())
        vel_map = {
            "imu_Lvel": "imu_Lvel",
            "imu_Rvel": "imu_Rvel",
        }

        # Power
        power_right = None
        power_left = None
        power_enabled = self.curve_checks.get("__power__")
        if power_enabled is not None and power_enabled.isChecked():
            if "M1_torque_command" in df.columns and vel_map.get("imu_Rvel") in df.columns:
                vel_r_raw = pd.to_numeric(df[vel_map["imu_Rvel"]], errors="coerce").to_numpy(dtype=float)
                vel_r = np.deg2rad(vel_r_raw)
                power_right = pd.to_numeric(df["M1_torque_command"], errors="coerce").to_numpy(dtype=float) * vel_r
            if "M2_torque_command" in df.columns and vel_map.get("imu_Lvel") in df.columns:
                vel_l_raw = pd.to_numeric(df[vel_map["imu_Lvel"]], errors="coerce").to_numpy(dtype=float)
                vel_l = np.deg2rad(vel_l_raw)
                power_left = pd.to_numeric(df["M2_torque_command"], errors="coerce").to_numpy(dtype=float) * vel_l


        left_allowed = {
            "imu_LTx", "imu_Lvel",
            "M2_torque_command", "L_P", "L_D",
            "raw_LExoTorque", "filtered_LExoTorque",
        }
        right_allowed = {
            "imu_RTx", "imu_Rvel",
            "M1_torque_command", "R_P", "R_D",
            "raw_RExoTorque", "filtered_RExoTorque",
        }

        col_labels = {
            "imu_LTx": "Angle L",
            "imu_RTx": "Angle R",
            "imu_Lvel": "Velocity L",
            "imu_Rvel": "Velocity R",
            "M1_torque_command": "Torque R",
            "M2_torque_command": "Torque L",
            "raw_RExoTorque": "Raw Torque R",
            "raw_LExoTorque": "Raw Torque L",
            "filtered_RExoTorque": "Filtered Torque R",
            "filtered_LExoTorque": "Filtered Torque L",
            "L_P": "P-term L",
            "R_P": "P-term R",
            "L_D": "D-term L",
            "R_D": "D-term R",
        }
        col_colors = {
            "imu_LTx": "#1f77b4",
            "imu_RTx": "#ff7f0e",
            "imu_Lvel": "#2ca02c",
            "imu_Rvel": "#d62728",
            "M1_torque_command": "#9467bd",
            "M2_torque_command": "#8c564b",
            "raw_RExoTorque": "#4c78a8",
            "raw_LExoTorque": "#72b7b2",
            "filtered_RExoTorque": "#f58518",
            "filtered_LExoTorque": "#e45756",
            "L_P": "#17becf",
            "R_P": "#7f7f7f",
            "L_D": "#bcbd22",
            "R_D": "#e377c2",
        }

        fs_override = float(self.fs_spin.value())
        if fs_override > 0:
            fs = fs_override
        else:
            diffs = np.diff(t)
            diffs = diffs[np.isfinite(diffs) & (diffs > 0)]
            dt = float(np.nanmedian(diffs)) if len(diffs) else 0.0
            fs = 1.0 / dt if dt > 0 else 0.0
        fc = float(self.lowpass_cutoff.value())
        if fs > 0:
            fc = min(fc, 0.45 * fs)
        if self.global_lowpass.isChecked():
            if butter is None or filtfilt is None:
                self.statusBar().showMessage("Low-pass disabled: scipy not available.", 5000)
            elif fs <= 0 or fc <= 0:
                self.statusBar().showMessage("Low-pass disabled: invalid fs/fc.", 5000)

        def plot_side(ax_l, ax_t, ax_p, side_allowed, power_series, title):
            lines = []
            labels = []
            for group, cb in self.curve_checks.items():
                if group == "__power__":
                    continue
                if not cb.isChecked():
                    continue
                cols = self.curve_groups.get(group, [])
                for col in cols:
                    plot_key = col
                    if col in vel_map:
                        plot_key = vel_map[col]
                    if plot_key not in df.columns:
                        continue
                    if plot_key not in side_allowed:
                        continue

                    y = pd.to_numeric(df[plot_key], errors="coerce").to_numpy(dtype=float)
                    if plot_key in {"imu_Lvel", "imu_Rvel"}:
                        if self.global_lowpass.isChecked() and fs > 0 and fc > 0:
                            y = lowpass_butter(y, fs, fc=fc, order=2)
                        y = y / vel_scale
                    if plot_key in {"L_P", "R_P", "L_D", "R_D"}:
                        if self.global_lowpass.isChecked() and fs > 0 and fc > 0:
                            y = lowpass_butter(y, fs, fc=fc, order=2)
                    if self.invert_check.isChecked():
                        y = -y
                    color = col_colors.get(plot_key)
                    if plot_key in {"imu_LTx", "imu_RTx", "imu_Lvel", "imu_Rvel"}:
                        line = ax_l.plot(t, y, linewidth=1.6, color=color)[0]
                    else:
                        line = ax_t.plot(t, y, linewidth=1.6, linestyle="--", color=color)[0]
                    lines.append(line)
                    labels.append(col_labels.get(plot_key, plot_key))

            if power_series is not None:
                if self.global_lowpass.isChecked() and fs > 0 and fc > 0:
                    power_series = lowpass_butter(power_series, fs, fc=fc, order=2)
                p_color = "#0020f1" if "Left" in title else "#ff0000"
                line = ax_p.plot(t, power_series, linewidth=1.4, color=p_color)[0]
                ax_p.fill_between(t, 0, power_series, where=(power_series >= 0), color="#2ca02c", alpha=0.30)
                ax_p.fill_between(t, 0, power_series, where=(power_series < 0), color="#d62728", alpha=0.30)
                lines.append(line)
                labels.append(f"{title} Power")

            ax_l.set_ylabel("Angle / Velocity")
            ax_t.set_ylabel("Torque")
            ax_p.set_ylabel("Power")
            ax_l.grid(True, linestyle="--", alpha=0.4)
            ax_l.set_title(title)
            if lines:
                ax_l.legend(lines, labels, loc="upper right")

        plot_side(ax_left, ax_left_r, ax_left_p, left_allowed, power_left, "Left Leg")
        plot_side(ax_right, ax_right_r, ax_right_p, right_allowed, power_right, "Right Leg")

        ax_right.set_xlabel("Time (s)")

        title_tag = f"Tag: {tag_value}" if tag_value else "Tag: all"
        if power_right is not None and len(power_right):
            denom_r = float(np.sum(np.abs(power_right)))
            pos_r = float(np.sum(power_right[power_right > 0]) / denom_r) if denom_r > 0 else 0.0
        else:
            pos_r = 0.0
        if power_left is not None and len(power_left):
            denom_l = float(np.sum(np.abs(power_left)))
            pos_l = float(np.sum(power_left[power_left > 0]) / denom_l) if denom_l > 0 else 0.0
        else:
            pos_l = 0.0
        pos_text = f"Positive Power Ratio  L: {pos_l:.3f}  R: {pos_r:.3f}"
        self.figure.suptitle(f"{os.path.basename(self.current_path)} | {title_tag}\n{pos_text}")

        self.figure.tight_layout(rect=[0, 0, 1, 0.96])
        self.canvas.draw()

    # ---------------------- Save ----------------------
    def save_figure(self):
        name = self.save_name.text().strip() or "figure"
        out_dir = os.path.join(os.path.dirname(__file__), "output")
        os.makedirs(out_dir, exist_ok=True)
        filename = os.path.join(out_dir, f"{name}.pdf")
        self.figure.savefig(filename, format="pdf", dpi=300, bbox_inches="tight")
        self.statusBar().showMessage(f"Saved: {filename}", 5000)


def main():
    app = QtWidgets.QApplication(sys.argv)
    win = MMEAnalyzer()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
