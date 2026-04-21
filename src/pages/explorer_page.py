#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Explorer Tab — Generic CSV viewer with interactive span selection and tagging.
No assumptions about column names. Browse any CSV, pick columns, explore, tag.
"""

import os

import numpy as np
import pandas as pd

from PyQt5 import QtWidgets
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QCursor

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
import matplotlib.colors as mcolors

try:
    from matplotlib.widgets import SpanSelector
except ImportError:
    SpanSelector = None

try:
    from scipy.signal import find_peaks
except ImportError:
    find_peaks = None


# --------------- helpers ---------------

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


def _make_time_axis(time_series: pd.Series) -> np.ndarray:
    t_num = pd.to_numeric(time_series, errors="coerce")
    if t_num.notna().mean() > 0.9:
        t = t_num.to_numpy(dtype=float)
        finite = np.isfinite(t)
        if finite.sum() < 2:
            return np.arange(len(time_series), dtype=float)
        t_valid = t[finite]
        diffs = np.diff(t_valid)
        diffs = diffs[np.isfinite(diffs)]
        dt_med = np.nanmedian(np.abs(diffs)) if len(diffs) > 0 else 10.0
        t0 = t_valid[0]
        if 1.0 <= dt_med <= 1000.0:
            return _sanitize_time_axis((t - t0) / 1000.0)
        return _sanitize_time_axis(t - t0)
    t_dt = pd.to_datetime(time_series, errors="coerce")
    if t_dt.notna().mean() > 0.9 and t_dt.notna().any():
        first_valid = t_dt[t_dt.notna()].iloc[0]
        return _sanitize_time_axis((t_dt - first_valid).dt.total_seconds().to_numpy(dtype=float))
    return np.arange(len(time_series), dtype=float)


_TIME_CANDIDATES = ["Time_ms", "time_ms", "time", "timestamp", "time_s", "elapsed"]
_CADENCE_PRIMARY_COLS = ("imu_LTx", "imu_RTx")
_CADENCE_HINTS = ("ltx", "rtx", "angle", "hip")

MAX_OVERVIEW_PTS = 2000
MAX_DETAIL_PTS = 5000
MAX_CHECKED = 8

# colors for tag shading (distinct, semi-transparent)
_TAG_COLORS = [
    "#2ca02c", "#1f77b4", "#ff7f0e", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#17becf", "#bcbd22", "#7f7f7f",
]


# --------------- main widget ---------------

class ExplorerPage(QtWidgets.QWidget):
    def __init__(self, data_dir_provider=None, mapping_path_provider=None, show_browse=True):
        super().__init__()
        self.data_dir_provider = data_dir_provider
        self.mapping_path_provider = mapping_path_provider
        self._show_browse = bool(show_browse)
        self.df = None
        self.df_original = None  # pristine copy for non-destructive edits
        self.csv_path = None
        self._folder_path = None
        self.time_col = None
        self.t = None
        self.numeric_cols = []
        self.string_cols = []
        self._span = (0.0, 1.0)
        self._span_selector = None
        self._checkboxes = []
        self._col_order = []  # ordered list of (col_name, col_type) for checked columns
        self._tag_color_map = {}  # tag_value -> color
        self._cursor_lines = []   # vertical lines on detail subplots
        self._cursor_texts = []   # value annotations
        self._cursor_cid = None   # mpl event connection id
        self._debounce = QTimer()
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(80)
        self._debounce.timeout.connect(self._do_update)
        self._view_mode = "multiple"   # "single" | "multiple"
        self._build_ui()
        self.refresh_data()

    # ============================================================
    # UI
    # ============================================================
    def _build_ui(self):
        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)

        # ---------- left panel ----------
        left = QtWidgets.QWidget()
        left.setMinimumWidth(240)
        left.setMaximumWidth(360)
        left.setObjectName("sectionPanel")
        lv = QtWidgets.QVBoxLayout(left)
        lv.setContentsMargins(8, 8, 8, 8)
        lv.setSpacing(6)

        # browse
        self.browse_btn = QtWidgets.QPushButton("  Browse CSV...")
        self.browse_btn.clicked.connect(self._browse_file)
        self.browse_btn.setVisible(self._show_browse)
        lv.addWidget(self.browse_btn)

        # folder file list (quick switch)
        folder_title = QtWidgets.QLabel("Folder CSVs")
        folder_title.setObjectName("sectionTitle")
        lv.addWidget(folder_title)
        self.folder_path_label = QtWidgets.QLabel("No folder selected")
        self.folder_path_label.setWordWrap(True)
        self.folder_path_label.setStyleSheet("font-size: 10px; color: #777;")
        lv.addWidget(self.folder_path_label)
        self.folder_list = QtWidgets.QListWidget()
        self.folder_list.setMaximumHeight(140)
        self.folder_list.itemSelectionChanged.connect(self._on_folder_file_selected)
        lv.addWidget(self.folder_list)
        self.folder_refresh_btn = QtWidgets.QPushButton("Refresh Folder List")
        self.folder_refresh_btn.clicked.connect(self._refresh_folder_files_from_context)
        lv.addWidget(self.folder_refresh_btn)

        self.file_label = QtWidgets.QLabel("No file loaded")
        self.file_label.setWordWrap(True)
        lv.addWidget(self.file_label)
        self.copy_filename_btn = QtWidgets.QPushButton("Copy Filename")
        self.copy_filename_btn.setEnabled(False)
        self.copy_filename_btn.clicked.connect(self._copy_current_filename)
        lv.addWidget(self.copy_filename_btn)

        # file info
        info_title = QtWidgets.QLabel("File Info")
        info_title.setObjectName("sectionTitle")
        lv.addWidget(info_title)
        self.info_label = QtWidgets.QLabel("")
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("font-size: 11px;")
        lv.addWidget(self.info_label)

        # -------- column checkboxes --------
        col_title = QtWidgets.QLabel("Columns (check to plot)")
        col_title.setObjectName("sectionTitle")
        lv.addWidget(col_title)

        self._col_search = QtWidgets.QLineEdit()
        self._col_search.setPlaceholderText("Search columns...")
        self._col_search.setClearButtonEnabled(True)
        self._col_search.textChanged.connect(self._filter_checkboxes)
        lv.addWidget(self._col_search)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._cb_container = QtWidgets.QWidget()
        self._cb_layout = QtWidgets.QVBoxLayout(self._cb_container)
        self._cb_layout.setContentsMargins(2, 2, 2, 2)
        self._cb_layout.setSpacing(2)
        self._cb_layout.addStretch()
        scroll.setWidget(self._cb_container)
        lv.addWidget(scroll, 1)

        # stats
        stats_title = QtWidgets.QLabel("Statistics (selected range)")
        stats_title.setObjectName("sectionTitle")
        lv.addWidget(stats_title)
        self.cadence_label = QtWidgets.QLabel("Cadence: N/A | Level: N/A")
        self.cadence_label.setWordWrap(True)
        self.cadence_label.setStyleSheet("font-family: monospace; font-size: 12px;")
        lv.addWidget(self.cadence_label)

        stats_scroll = QtWidgets.QScrollArea()
        stats_scroll.setWidgetResizable(True)
        stats_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._stats_container = QtWidgets.QWidget()
        self._stats_layout = QtWidgets.QVBoxLayout(self._stats_container)
        self._stats_layout.setContentsMargins(2, 2, 2, 2)
        self._stats_layout.setSpacing(0)
        self.stats_label = QtWidgets.QLabel("Load a file to begin.")
        self.stats_label.setWordWrap(True)
        self.stats_label.setStyleSheet("font-family: monospace; font-size: 13px;")
        self.stats_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.stats_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._stats_layout.addWidget(self.stats_label)
        self._stats_layout.addStretch()
        stats_scroll.setWidget(self._stats_container)
        lv.addWidget(stats_scroll, 1)

        root.addWidget(left)

        # ---------- right panel ----------
        right = QtWidgets.QVBoxLayout()

        # overview canvas (short)
        self.overview_fig = Figure(figsize=(10, 1.4))
        self.overview_fig.set_tight_layout(True)
        self.overview_canvas = FigureCanvas(self.overview_fig)
        self.overview_canvas.setMinimumHeight(80)
        self.overview_canvas.setMaximumHeight(140)

        # detail canvas
        self.detail_fig = Figure(figsize=(10, 5))
        self.detail_fig.set_tight_layout(True)
        self.detail_canvas = FigureCanvas(self.detail_fig)
        self.detail_canvas.setContextMenuPolicy(Qt.CustomContextMenu)
        self.detail_canvas.customContextMenuRequested.connect(self._on_detail_right_click)
        self._detail_axes_cols = []  # [(ax, col_name)] mapping for right-click detection
        toolbar = NavigationToolbar(self.detail_canvas, self)

        # -------- tagging bar (single row between overview & detail) --------
        tag_bar = QtWidgets.QHBoxLayout()
        tag_bar.setContentsMargins(0, 2, 0, 2)
        tag_bar.setSpacing(4)

        # ── Single / Multiple view toggle ────────────────────────────────────
        self._btn_single   = QtWidgets.QPushButton("Single")
        self._btn_multiple = QtWidgets.QPushButton("Multiple")
        for btn in (self._btn_single, self._btn_multiple):
            btn.setCheckable(True)
            btn.setFixedWidth(72)
        self._btn_multiple.setChecked(True)
        self._btn_single.setToolTip(
            "Plot all selected columns on one shared axis"
        )
        self._btn_multiple.setToolTip(
            "Plot each selected column in its own subplot (stacked)"
        )
        self._btn_single.clicked.connect(self._set_view_single)
        self._btn_multiple.clicked.connect(self._set_view_multiple)
        tag_bar.addWidget(self._btn_single)
        tag_bar.addWidget(self._btn_multiple)
        tag_bar.addWidget(QtWidgets.QLabel("  "))   # spacer

        tag_bar.addWidget(QtWidgets.QLabel("View:"))
        self.tag_col_combo = QtWidgets.QComboBox()
        self.tag_col_combo.setFixedWidth(110)
        self.tag_col_combo.addItem("(none)")
        self.tag_col_combo.currentTextChanged.connect(self._on_tag_col_changed)
        tag_bar.addWidget(self.tag_col_combo)

        tag_bar.addWidget(QtWidgets.QLabel("Write to:"))
        self.tag_write_col = QtWidgets.QComboBox()
        self.tag_write_col.setEditable(True)
        self.tag_write_col.setFixedWidth(110)
        self.tag_write_col.lineEdit().setPlaceholderText("column name")
        tag_bar.addWidget(self.tag_write_col)

        self.tag_input = QtWidgets.QLineEdit()
        self.tag_input.setPlaceholderText("tag value...")
        self.tag_input.setFixedWidth(110)
        tag_bar.addWidget(self.tag_input)

        tag_apply_btn = QtWidgets.QPushButton("Tag Selection")
        tag_apply_btn.clicked.connect(self._apply_tag)
        tag_bar.addWidget(tag_apply_btn)

        tag_save_btn = QtWidgets.QPushButton("Save CSV")
        tag_save_btn.clicked.connect(self._save_csv)
        tag_bar.addWidget(tag_save_btn)

        self.tag_status = QtWidgets.QLabel("")
        self.tag_status.setStyleSheet("font-size: 10px; color: #666;")
        tag_bar.addWidget(self.tag_status, 1)

        right.addWidget(toolbar)
        right.addWidget(self.overview_canvas)
        right.addLayout(tag_bar)
        right.addWidget(self.detail_canvas, 1)
        root.addLayout(right, 1)

    # ============================================================
    # File loading
    # ============================================================
    def _browse_file(self):
        start_dir = os.path.dirname(self.csv_path) if self.csv_path else ""
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open CSV File", start_dir, "CSV Files (*.csv);;All Files (*)"
        )
        if not path:
            return
        if os.path.basename(path).startswith("._"):
            return
        self.load_csv(path)

    def _load_csv(self, path, sync_folder=True):
        if sync_folder:
            self._refresh_folder_files(os.path.dirname(path), selected_file=os.path.basename(path))
        try:
            try:
                df = pd.read_csv(path)
            except UnicodeDecodeError:
                df = pd.read_csv(path, encoding="latin-1")
        except Exception as e:
            self.file_label.setText(f"Error: {e}")
            return

        self.df = df
        self.df_original = df.copy()
        self.csv_path = path
        self.copy_filename_btn.setEnabled(True)
        try:
            self._detect_columns()
            self._update_file_info(path)
            self._populate_tag_col_combo()
            self._populate_checkboxes()
            self._plot_overview()
            self._update_detail()
            self._update_stats()
            self.tag_status.setText("")
        except Exception as e:
            self.file_label.setText(f"Render Error: {e}")
            self.tag_status.setText("File loaded but failed to render. Check time column for invalid values.")

    def load_csv(self, path, sync_folder=True):
        if not path or not os.path.exists(path):
            return
        self._load_csv(path, sync_folder=sync_folder)

    def _copy_current_filename(self):
        if not self.csv_path:
            self.tag_status.setText("No file loaded to copy.")
            return
        filename = os.path.basename(self.csv_path)
        QtWidgets.QApplication.clipboard().setText(filename)
        self.tag_status.setText(f"Copied filename: {filename}")

    def set_folder(self, folder_path, selected_file=None):
        self._refresh_folder_files(folder_path, selected_file=selected_file)

    def _refresh_folder_files_from_context(self):
        if self.csv_path and os.path.isfile(self.csv_path):
            folder = os.path.dirname(self.csv_path)
            selected = os.path.basename(self.csv_path)
        elif callable(self.data_dir_provider):
            folder = self.data_dir_provider()
            selected = None
        else:
            folder = self._folder_path
            selected = None
        self._refresh_folder_files(folder, selected_file=selected)

    def _refresh_folder_files(self, folder_path, selected_file=None):
        self.folder_list.blockSignals(True)
        self.folder_list.clear()

        if not folder_path or not os.path.isdir(folder_path):
            self._folder_path = None
            self.folder_path_label.setText("No folder selected")
            self.folder_list.blockSignals(False)
            return

        self._folder_path = folder_path
        self.folder_path_label.setText(folder_path)
        files = sorted(
            [f for f in os.listdir(folder_path) if f.lower().endswith(".csv") and not f.startswith("._")]
        )
        self.folder_list.addItems(files)
        if files:
            target = selected_file if selected_file in files else files[0]
            matches = self.folder_list.findItems(target, Qt.MatchExactly)
            if matches:
                self.folder_list.setCurrentItem(matches[0])
        self.folder_list.blockSignals(False)

    def _on_folder_file_selected(self):
        if self.folder_list.signalsBlocked() or not self._folder_path:
            return
        item = self.folder_list.currentItem()
        if item is None:
            return
        path = os.path.join(self._folder_path, item.text())
        if self.csv_path and os.path.abspath(path) == os.path.abspath(self.csv_path):
            return
        self.load_csv(path, sync_folder=False)

    # ============================================================
    # Column detection
    # ============================================================
    def _detect_columns(self):
        self._detect_time_column()
        self.numeric_cols = []
        self.string_cols = []
        for col in self.df.columns:
            if col == self.time_col:
                continue
            if pd.api.types.is_numeric_dtype(self.df[col]):
                self.numeric_cols.append(col)
            elif self.df[col].dtype == object:
                self.string_cols.append(col)

    def _detect_time_column(self):
        for c in _TIME_CANDIDATES:
            if c in self.df.columns:
                self.time_col = c
                self.t = _make_time_axis(self.df[c])
                return
        lower_map = {col.lower(): col for col in self.df.columns}
        for c in _TIME_CANDIDATES:
            if c.lower() in lower_map:
                self.time_col = lower_map[c.lower()]
                self.t = _make_time_axis(self.df[self.time_col])
                return
        self.time_col = None
        self.t = np.arange(len(self.df), dtype=float)

    # ============================================================
    # UI updates
    # ============================================================
    def _update_file_info(self, path):
        nrows, ncols = self.df.shape
        t_finite = self.t[np.isfinite(self.t)] if self.t is not None else np.array([])
        duration = float(t_finite[-1] - t_finite[0]) if len(t_finite) > 1 else 0.0
        if len(t_finite) > 1 and self.time_col is not None:
            dt = np.nanmedian(np.diff(t_finite))
            fs = 1.0 / dt if dt > 0 else 0
            fs_text = f"{fs:.1f} Hz"
        else:
            fs_text = "N/A"
        self.file_label.setText(os.path.basename(path))
        self.info_label.setText(
            f"Path: {path}\n"
            f"Rows: {nrows:,}   Columns: {ncols}\n"
            f"Time col: {self.time_col or '(row index)'}\n"
            f"Sample rate: {fs_text}   Duration: {duration:.2f} s"
        )

    def _populate_tag_col_combo(self):
        # --- view combo (read-only) ---
        self.tag_col_combo.blockSignals(True)
        self.tag_col_combo.clear()
        self.tag_col_combo.addItem("(none)")
        # add all string/object columns as viewable tag sources
        for col in self.string_cols:
            self.tag_col_combo.addItem(col)
        # also add "tag"/"label" if numeric-ish
        for name in ("tag", "label", "labels", "category"):
            if name in self.df.columns and name not in self.string_cols:
                self.tag_col_combo.addItem(name)
        # auto-select first tag-like column
        for candidate in ("tag", "label", "labels", "category"):
            idx = self.tag_col_combo.findText(candidate)
            if idx >= 0:
                self.tag_col_combo.setCurrentIndex(idx)
                break
        self.tag_col_combo.blockSignals(False)

        # --- write combo (editable, user can type new column name) ---
        self.tag_write_col.blockSignals(True)
        self.tag_write_col.clear()
        # offer existing string columns + common new names
        for col in self.string_cols:
            self.tag_write_col.addItem(col)
        for name in ("tag", "label", "category"):
            if self.tag_write_col.findText(name) < 0:
                self.tag_write_col.addItem(name)
        # default to "tag" if nothing tag-like exists yet
        idx = self.tag_write_col.findText("tag")
        if idx >= 0:
            self.tag_write_col.setCurrentIndex(idx)
        self.tag_write_col.blockSignals(False)

    def _populate_checkboxes(self):
        for cb in self._checkboxes:
            cb.deleteLater()
        self._checkboxes = []
        # clean up old "show more" button if any
        if hasattr(self, '_show_more_btn') and self._show_more_btn is not None:
            self._show_more_btn.deleteLater()
            self._show_more_btn = None

        MAX_VISIBLE = 30  # show at most this many before folding
        all_cols = []
        for col in self.numeric_cols:
            all_cols.append((col, str(self.df[col].dtype), "numeric"))
        for col in self.string_cols:
            all_cols.append((col, "str", "string"))

        self._all_col_defs = all_cols
        self._showing_all = len(all_cols) <= MAX_VISIBLE

        visible = all_cols if self._showing_all else all_cols[:MAX_VISIBLE]
        for col, dtype_str, ctype in visible:
            self._add_checkbox(col, dtype_str, ctype)

        if not self._showing_all:
            hidden = len(all_cols) - MAX_VISIBLE
            self._show_more_btn = QtWidgets.QPushButton(f"Show {hidden} more columns...")
            self._show_more_btn.setStyleSheet("font-size: 10px; color: #888; padding: 4px;")
            self._show_more_btn.clicked.connect(self._show_all_columns)
            self._cb_layout.insertWidget(self._cb_layout.count() - 1, self._show_more_btn)
        else:
            self._show_more_btn = None

    def _add_checkbox(self, col, dtype_str, ctype):
        # show NaN count on label
        n_nan = int(self.df[col].isna().sum()) if self.df is not None else 0
        nan_str = f"  {n_nan} NaN" if n_nan > 0 else ""
        cb = QtWidgets.QCheckBox(f"{col}  [{dtype_str}]{nan_str}")
        cb.setProperty("col_name", col)
        cb.setProperty("col_type", ctype)
        if n_nan > 0:
            cb.setStyleSheet("color: #c06000;")  # orange-ish for columns with NaN
        elif ctype == "string":
            cb.setStyleSheet("color: #888;")
        cb.stateChanged.connect(self._on_checkbox_changed)
        cb.setContextMenuPolicy(Qt.CustomContextMenu)
        cb.customContextMenuRequested.connect(
            lambda pos, _cb=cb: self._show_col_context_menu(_cb, pos)
        )
        self._cb_layout.insertWidget(self._cb_layout.count() - 1, cb)
        self._checkboxes.append(cb)

    def _show_all_columns(self):
        if self._show_more_btn:
            self._show_more_btn.deleteLater()
            self._show_more_btn = None
        # add remaining columns
        MAX_VISIBLE = 30
        remaining = self._all_col_defs[MAX_VISIBLE:]
        for col, dtype_str, ctype in remaining:
            self._add_checkbox(col, dtype_str, ctype)
        self._showing_all = True

    def _filter_checkboxes(self, text):
        """Show/hide checkboxes based on search text."""
        query = text.strip().lower()
        for cb in self._checkboxes:
            col = cb.property("col_name").lower()
            cb.setVisible(query == "" or query in col)

    def _on_checkbox_changed(self, _state):
        checked = self._get_checked_columns()
        if len(checked) > MAX_CHECKED:
            sender = self.sender()
            sender.blockSignals(True)
            sender.setChecked(False)
            sender.blockSignals(False)
            return
        # maintain _col_order: add newly checked, remove unchecked
        checked_set = {c for c, _ in checked}
        self._col_order = [(c, t) for c, t in self._col_order if c in checked_set]
        for c, t in checked:
            if c not in {x[0] for x in self._col_order}:
                self._col_order.append((c, t))
        self._debounce.start()

    def _get_checked_columns(self):
        """Return list of (col_name, col_type) for checked boxes."""
        return [
            (cb.property("col_name"), cb.property("col_type"))
            for cb in self._checkboxes if cb.isChecked()
        ]

    # ============================================================
    # Tagging
    # ============================================================
    def _on_tag_col_changed(self, text):
        self._build_tag_color_map()
        self._redraw_overview_tags()

    def _get_active_tag_col(self):
        """Return the column name currently used for viewing/editing tags."""
        sel = self.tag_col_combo.currentText()
        if sel == "(none)" or self.df is None:
            return None
        if sel in self.df.columns:
            return sel
        return None

    def _build_tag_color_map(self):
        """Assign a color to each unique tag value."""
        self._tag_color_map = {}
        col = self._get_active_tag_col()
        if col is None or self.df is None:
            return
        unique_tags = [v for v in self.df[col].dropna().unique() if str(v).strip()]
        for i, tag in enumerate(unique_tags):
            self._tag_color_map[str(tag)] = _TAG_COLORS[i % len(_TAG_COLORS)]

    def _apply_tag(self):
        if self.df is None:
            self.tag_status.setText("No file loaded.")
            return
        tag_value = self.tag_input.text().strip()
        if not tag_value:
            self.tag_status.setText("Enter a tag value first.")
            return
        write_col = self.tag_write_col.currentText().strip()
        if not write_col:
            self.tag_status.setText("Enter a column name to write to.")
            return

        t_min, t_max = self._span
        mask = (self.t >= t_min) & (self.t <= t_max)
        n_tagged = int(np.sum(mask))
        if n_tagged == 0:
            self.tag_status.setText("No rows in selected range.")
            return

        # create column if it doesn't exist
        if write_col not in self.df.columns:
            self.df[write_col] = ""
            if write_col not in self.string_cols:
                self.string_cols.append(write_col)
            # add to both combos
            if self.tag_col_combo.findText(write_col) < 0:
                self.tag_col_combo.addItem(write_col)
            if self.tag_write_col.findText(write_col) < 0:
                self.tag_write_col.addItem(write_col)

        # auto-switch view to this column so user sees the result
        self.tag_col_combo.setCurrentText(write_col)

        # write tag to the selected range
        self.df.loc[mask, write_col] = tag_value

        # update colors and redraw
        self._build_tag_color_map()
        self._redraw_overview_tags()
        self.tag_status.setText(
            f"'{write_col}' ← \"{tag_value}\" ({n_tagged:,} rows, "
            f"{t_min:.2f}–{t_max:.2f} s)"
        )

    def _save_csv(self):
        if self.df is None or self.csv_path is None:
            self.tag_status.setText("No file to save.")
            return
        # default to _edited suffix to preserve original
        base, ext = os.path.splitext(self.csv_path)
        if not base.endswith("_edited"):
            default_path = f"{base}_edited{ext}"
        else:
            default_path = self.csv_path
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save CSV (original is preserved)", default_path,
            "CSV Files (*.csv)"
        )
        if not path:
            return
        self.df.to_csv(path, index=False)
        self.tag_status.setText(f"Saved: {os.path.basename(path)}")

    # ============================================================
    # Overview with SpanSelector + tag shading
    # ============================================================
    def _plot_overview(self):
        self.overview_fig.clear()
        self._overview_ax = self.overview_fig.add_subplot(111)
        ax = self._overview_ax

        if self.df is None or len(self.numeric_cols) == 0:
            self.overview_canvas.draw()
            return
        t_all = _sanitize_time_axis(self.t)
        finite_t = t_all[np.isfinite(t_all)]
        if len(finite_t) < 2:
            ax.text(0.5, 0.5, "Invalid time axis in this file",
                    ha="center", va="center", fontsize=11, color="#999",
                    transform=ax.transAxes)
            self.overview_canvas.draw()
            return

        # auto-pick up to 2 columns for overview
        preview_cols = self._pick_overview_cols()

        n = len(t_all)
        step = max(1, n // MAX_OVERVIEW_PTS)
        t_ds = t_all[::step]

        colors = ["#1f77b4", "#ff7f0e"]
        for i, col in enumerate(preview_cols):
            y = pd.to_numeric(self.df[col], errors="coerce").to_numpy(dtype=float)
            ax.plot(t_ds, y[::step], label=col, linewidth=0.8,
                    color=colors[i % len(colors)], alpha=0.7)

        t0 = float(np.nanmin(finite_t))
        t1 = float(np.nanmax(finite_t))
        if not np.isfinite(t0) or not np.isfinite(t1) or t1 <= t0:
            t0, t1 = 0.0, 1.0
        ax.set_xlim(t0, t1)
        ax.legend(loc="upper right", fontsize=7)
        ax.tick_params(labelsize=7)
        ax.set_ylabel("Overview", fontsize=8)
        ax.grid(True, alpha=0.2)

        # draw tag shading
        self._build_tag_color_map()
        self._draw_tag_shading(ax)

        # span selector (on top of tag shading)
        t_range = t1 - t0
        initial_start = t0
        initial_end = t0 + max(t_range * 0.2, 0.1)
        self._span = (initial_start, initial_end)

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
                self._span_selector = SpanSelector(
                    ax,
                    self._on_span_select,
                    "horizontal",
                    useblit=True,
                    rectprops=dict(facecolor="#ffd54f", alpha=0.35),
                )

        self.overview_canvas.draw()

    def _draw_tag_shading(self, ax):
        """Draw colored shading for tagged regions on the overview axis."""
        col = self._get_active_tag_col()
        if col is None or self.df is None:
            return
        if col not in self.df.columns:
            return

        tags = self.df[col].astype(str).values
        t = self.t

        # find contiguous runs of the same tag
        i = 0
        n = len(tags)
        while i < n:
            tag = tags[i]
            if not tag or tag == "" or tag == "nan":
                i += 1
                continue
            # find end of this run
            j = i + 1
            while j < n and tags[j] == tag:
                j += 1
            # draw shading
            color = self._tag_color_map.get(tag, "#cccccc")
            t_start = t[i]
            t_end = t[min(j - 1, n - 1)]
            ax.axvspan(t_start, t_end, alpha=0.18, color=color, zorder=0)
            # label at center
            t_mid = (t_start + t_end) / 2
            ax.text(t_mid, ax.get_ylim()[1], tag,
                    ha="center", va="top", fontsize=6,
                    color=color, fontweight="bold", alpha=0.8)
            i = j

    def _redraw_overview_tags(self):
        """Redraw just the tag shading without rebuilding the whole overview."""
        if not hasattr(self, '_overview_ax') or self._overview_ax is None:
            return
        ax = self._overview_ax
        # remove old tag patches and texts (keep signal lines and span)
        to_remove = []
        for child in ax.get_children():
            # axvspan creates Polygon patches; tag labels are Text objects with fontsize 6
            from matplotlib.patches import Polygon
            from matplotlib.text import Text
            if isinstance(child, Polygon) and child.get_alpha() is not None and abs(child.get_alpha() - 0.18) < 0.01:
                to_remove.append(child)
            elif isinstance(child, Text) and child.get_fontsize() == 6:
                to_remove.append(child)
        for item in to_remove:
            item.remove()

        self._draw_tag_shading(ax)
        self.overview_canvas.draw()

    def _pick_overview_cols(self):
        """Pick 1-2 columns for the overview strip, preferring angle/velocity."""
        angle_kw = ["angle", "ltx", "rtx", "imu_l", "imu_r"]
        vel_kw = ["vel", "speed", "omega"]
        picked = []
        for col in self.numeric_cols:
            cl = col.lower()
            if any(k in cl for k in angle_kw):
                picked.append(col)
                break
        for col in self.numeric_cols:
            cl = col.lower()
            if col not in picked and any(k in cl for k in vel_kw):
                picked.append(col)
                break
        if not picked:
            picked = self.numeric_cols[:2]
        elif len(picked) < 2 and len(self.numeric_cols) > 1:
            for col in self.numeric_cols:
                if col not in picked:
                    picked.append(col)
                    break
        return picked[:2]

    def _on_span_select(self, t_min, t_max):
        if t_max - t_min < 0.01:
            return
        self._span = (t_min, t_max)
        self._debounce.start()

    # ============================================================
    # Detail plot
    # ============================================================
    def _set_view_single(self):
        self._view_mode = "single"
        self._btn_single.setChecked(True)
        self._btn_multiple.setChecked(False)
        self._update_detail()

    def _set_view_multiple(self):
        self._view_mode = "multiple"
        self._btn_single.setChecked(False)
        self._btn_multiple.setChecked(True)
        self._update_detail()

    def _do_update(self):
        self._update_detail()
        self._update_stats()

    def _update_detail(self):
        self.detail_fig.clear()
        self._detail_axes_cols = []

        if self.df is None:
            self.detail_canvas.draw()
            return

        checked = self._col_order if self._col_order else self._get_checked_columns()
        if not checked:
            ax = self.detail_fig.add_subplot(111)
            ax.text(0.5, 0.5, "Check columns on the left to plot",
                    ha="center", va="center", fontsize=12, color="#999",
                    transform=ax.transAxes)
            self.detail_canvas.draw()
            return

        t_min, t_max = self._span
        mask = (self.t >= t_min) & (self.t <= t_max)
        t_sel = self.t[mask]

        if len(t_sel) < 2:
            ax = self.detail_fig.add_subplot(111)
            ax.text(0.5, 0.5, "Selected range too small",
                    ha="center", va="center", fontsize=12, color="#999",
                    transform=ax.transAxes)
            self.detail_canvas.draw()
            return

        step = max(1, len(t_sel) // MAX_DETAIL_PTS)
        t_plot = t_sel[::step]

        # only plot numeric columns
        plot_cols = [(c, t) for c, t in checked if t == "numeric"]
        if not plot_cols:
            ax = self.detail_fig.add_subplot(111)
            ax.text(0.5, 0.5, "Select numeric columns to plot",
                    ha="center", va="center", fontsize=12, color="#999",
                    transform=ax.transAxes)
            self.detail_canvas.draw()
            return

        tag_runs = self._get_tag_runs_in_range(t_min, t_max)

        default_colors = [
            "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728",
            "#9467bd", "#8c564b", "#e377c2", "#17becf",
        ]

        xlabel = "Time (s)" if self.time_col else "Row Index"

        if self._view_mode == "single":
            # ── Independent Y axis per column (twinx), shared X ──────────────
            # Column 0 → primary left axis.
            # Columns 1..N-1 → twinx, spine offset 65px each to the right.
            n = len(plot_cols)
            ax0 = self.detail_fig.add_subplot(111)
            all_axes = [ax0]
            for i in range(1, n):
                tw = ax0.twinx()
                tw.spines["right"].set_position(("outward", 65 * (i - 1)))
                all_axes.append(tw)

            for idx, ((col, _), tax) in enumerate(zip(plot_cols, all_axes)):
                y = pd.to_numeric(self.df[col], errors="coerce").to_numpy(dtype=float)
                color = default_colors[idx % len(default_colors)]
                tax.plot(t_plot, y[mask][::step], linewidth=1.0, color=color)
                tax.set_ylabel(col, color=color, fontsize=8)
                tax.tick_params(axis="y", labelcolor=color, labelsize=7)
                tax.tick_params(axis="x", labelsize=7)
                self._detail_axes_cols.append((tax, col))

            # tag shading and x-axis decorations only on primary axis
            for ts, te, tag in tag_runs:
                tc = self._tag_color_map.get(tag, "#cccccc")
                ax0.axvspan(ts, te, alpha=0.12, color=tc, zorder=0)
            ax0.set_xlabel(xlabel, fontsize=9)
            ax0.set_xlim(t_min, t_max)
            ax0.grid(True, alpha=0.3)

            # adjust right margin to expose offset spines (65px each extra axis)
            right_margin = max(0.72, 0.97 - 0.065 * max(0, n - 1))
            self.detail_fig.subplots_adjust(left=0.10, right=right_margin,
                                            top=0.96, bottom=0.10)
            axes = all_axes

        else:
            # ── Stacked subplots (Multiple mode, original behavior) ───────────
            n = len(plot_cols)
            axes = self.detail_fig.subplots(n, 1, sharex=True, squeeze=False)
            axes = [axes[i, 0] for i in range(n)]

            for idx, ((col, _), ax) in enumerate(zip(plot_cols, axes)):
                y = pd.to_numeric(self.df[col], errors="coerce").to_numpy(dtype=float)
                color = default_colors[idx % len(default_colors)]
                ax.plot(t_plot, y[mask][::step], linewidth=1.0, color=color)
                ax.set_ylabel(col, fontsize=8)
                ax.grid(True, alpha=0.3)
                ax.set_xlim(t_min, t_max)
                ax.tick_params(labelsize=7)
                self._detail_axes_cols.append((ax, col))
                for ts, te, tag in tag_runs:
                    tc = self._tag_color_map.get(tag, "#cccccc")
                    ax.axvspan(ts, te, alpha=0.12, color=tc, zorder=0)

            axes[-1].set_xlabel(xlabel, fontsize=9)
            self.detail_fig.tight_layout(h_pad=0.3)

        # setup crosshair cursor
        self._cursor_lines = []
        self._cursor_texts = []
        for ax, col in self._detail_axes_cols:
            vl = ax.axvline(x=0, color="#888", linewidth=0.7, linestyle="--", visible=False)
            self._cursor_lines.append(vl)
            txt = ax.text(0, 0, "", fontsize=7, color="#333",
                          bbox=dict(facecolor="white", alpha=0.8, edgecolor="none", pad=1),
                          visible=False, zorder=10)
            self._cursor_texts.append(txt)
        if self._cursor_cid is not None:
            self.detail_canvas.mpl_disconnect(self._cursor_cid)
        self._cursor_cid = self.detail_canvas.mpl_connect(
            "motion_notify_event", self._on_detail_mouse_move
        )

        self.detail_canvas.draw()

    def _on_detail_mouse_move(self, event):
        """Crosshair cursor: show vertical line + value on all subplots."""
        if event.inaxes is None or not self._cursor_lines:
            # hide all
            for vl in self._cursor_lines:
                vl.set_visible(False)
            for txt in self._cursor_texts:
                txt.set_visible(False)
            self.detail_canvas.draw_idle()
            return

        x = event.xdata
        if x is None:
            return

        # find nearest time index
        idx = int(np.searchsorted(self.t, x, side="left"))
        idx = max(0, min(idx, len(self.t) - 1))
        t_val = self.t[idx]

        for i, ((_ax, col), vl, txt) in enumerate(
            zip(self._detail_axes_cols, self._cursor_lines, self._cursor_texts)
        ):
            vl.set_xdata([t_val, t_val])
            vl.set_visible(True)

            # get value at this index
            y_raw = pd.to_numeric(self.df[col], errors="coerce")
            if idx < len(y_raw):
                val = y_raw.iloc[idx]
                if np.isfinite(val):
                    txt.set_text(f" {val:.3f}")
                    txt.set_position((t_val, val))
                    txt.set_visible(True)
                else:
                    txt.set_visible(False)
            else:
                txt.set_visible(False)

        self.detail_canvas.draw_idle()

    def _get_tag_runs_in_range(self, t_min, t_max):
        """Return list of (t_start, t_end, tag_name) for tag runs in range."""
        tag_col = self._get_active_tag_col()
        if not tag_col or tag_col not in self.df.columns:
            return []
        tags = self.df[tag_col].astype(str).values
        t_all = self.t
        i_start = int(np.searchsorted(t_all, t_min, side="left"))
        i_end = int(np.searchsorted(t_all, t_max, side="right"))
        runs = []
        i = i_start
        while i < i_end:
            tag = tags[i]
            if not tag or tag == "" or tag == "nan":
                i += 1
                continue
            j = i + 1
            while j < i_end and tags[j] == tag:
                j += 1
            runs.append((t_all[i], t_all[min(j - 1, len(t_all) - 1)], tag))
            i = j
        return runs

    # ============================================================
    # Stats
    # ============================================================
    def _speed_level_from_cadence(self, cadence_spm: float) -> str:
        if cadence_spm < 90:
            return "慢走"
        if cadence_spm < 120:
            return "走路"
        if cadence_spm < 145:
            return "快走"
        return "慢跑"

    def _pick_cadence_columns(self):
        cols = []
        for c in _CADENCE_PRIMARY_COLS:
            if self.df is not None and c in self.df.columns and pd.api.types.is_numeric_dtype(self.df[c]):
                cols.append(c)
        if cols:
            return cols
        for c in self.numeric_cols:
            cl = c.lower()
            if any(h in cl for h in _CADENCE_HINTS):
                cols.append(c)
            if len(cols) >= 2:
                break
        return cols

    def _estimate_leg_cadence(self, t_sel: np.ndarray, y_sel: np.ndarray):
        finite = np.isfinite(t_sel) & np.isfinite(y_sel)
        t = t_sel[finite]
        y = y_sel[finite]
        if len(t) < 20:
            return None

        dt = np.diff(t)
        dt = dt[np.isfinite(dt) & (dt > 0)]
        if len(dt) == 0:
            return None
        fs = 1.0 / float(np.nanmedian(dt))
        if fs <= 0:
            return None

        y = y - float(np.nanmedian(y))
        smooth_win = max(3, int(fs * 0.12))
        if smooth_win % 2 == 0:
            smooth_win += 1
        if smooth_win >= 5 and len(y) > smooth_win:
            kernel = np.ones(smooth_win, dtype=float) / float(smooth_win)
            y = np.convolve(y, kernel, mode="same")

        y_std = float(np.nanstd(y))
        if not np.isfinite(y_std) or y_std <= 1e-6:
            return None

        min_dist = max(1, int(fs * 0.35))
        prominence = max(0.15 * y_std, 0.2)
        if find_peaks is not None:
            peaks, _ = find_peaks(y, distance=min_dist, prominence=prominence)
        else:
            peaks = np.where((y[1:-1] >= y[:-2]) & (y[1:-1] > y[2:]))[0] + 1
            filtered = []
            for p in peaks:
                if not filtered or (p - filtered[-1]) >= min_dist:
                    filtered.append(int(p))
            peaks = np.asarray(filtered, dtype=int)

        if len(peaks) < 3:
            return None

        intervals = np.diff(t[peaks])
        intervals = intervals[np.isfinite(intervals) & (intervals >= 0.35) & (intervals <= 2.5)]
        if len(intervals) < 2:
            return None

        stride_sec = float(np.nanmedian(intervals))
        if stride_sec <= 0:
            return None
        return 120.0 / stride_sec

    def _update_cadence_estimate(self):
        if self.df is None:
            self.cadence_label.setText("Cadence: N/A | Level: N/A")
            return

        t_min, t_max = self._span
        mask = (self.t >= t_min) & (self.t <= t_max) & np.isfinite(self.t)
        if int(np.sum(mask)) < 20:
            self.cadence_label.setText("Cadence: N/A | Level: N/A (selected range too short)")
            return

        t_sel = self.t[mask]
        dur = float(np.nanmax(t_sel) - np.nanmin(t_sel)) if len(t_sel) > 1 else 0.0
        if dur < 2.0:
            self.cadence_label.setText("Cadence: N/A | Level: N/A (selected range < 2s)")
            return

        cols = self._pick_cadence_columns()
        if not cols:
            self.cadence_label.setText("Cadence: N/A | Level: N/A (no angle column found)")
            return

        cadence_vals = []
        for col in cols:
            y = pd.to_numeric(self.df[col], errors="coerce").to_numpy(dtype=float)
            cad = self._estimate_leg_cadence(t_sel, y[mask])
            if cad is not None and np.isfinite(cad):
                cadence_vals.append(float(cad))

        if not cadence_vals:
            self.cadence_label.setText("Cadence: N/A | Level: N/A (insufficient gait peaks)")
            return

        cadence_spm = float(np.nanmedian(cadence_vals))
        level = self._speed_level_from_cadence(cadence_spm)
        self.cadence_label.setText(f"Cadence: {cadence_spm:.1f} steps/min | Level: {level}")

    def _update_stats(self):
        if self.df is None:
            self.stats_label.setText("Load a file to begin.")
            self.cadence_label.setText("Cadence: N/A | Level: N/A")
            return
        self._update_cadence_estimate()
        checked = self._col_order if self._col_order else self._get_checked_columns()
        if not checked:
            self.stats_label.setText("Check columns to see statistics.")
            return

        t_min, t_max = self._span
        mask = (self.t >= t_min) & (self.t <= t_max)
        n_pts = int(np.sum(mask))

        # build HTML — one column per stat, big and readable
        html = (
            f"<div style='font-size:13px; font-family:monospace; line-height:1.6;'>"
            f"<b>{t_min:.2f} – {t_max:.2f} s</b> &nbsp; ({n_pts:,} pts)"
            f"<hr style='border:1px solid #ccc;'>"
        )
        for col, ctype in checked:
            html += f"<div style='margin-top:8px;'><b style='font-size:14px;'>{col}</b><br>"
            if ctype == "numeric":
                y = pd.to_numeric(self.df[col], errors="coerce").to_numpy(dtype=float)
                y_sel = y[mask]
                y_v = y_sel[np.isfinite(y_sel)]
                n_nan = int(np.sum(~np.isfinite(y_sel)))
                if len(y_v) == 0:
                    html += "no valid data"
                else:
                    html += (
                        f"mean = {np.mean(y_v):.4f}<br>"
                        f"std &nbsp;= {np.std(y_v):.4f}<br>"
                        f"min &nbsp;= {np.min(y_v):.4f}<br>"
                        f"max &nbsp;= {np.max(y_v):.4f}"
                    )
                    if n_nan > 0:
                        html += f"<br><span style='color:#c06000;'>NaN = {n_nan}</span>"
            else:
                s = self.df[col].iloc[mask.nonzero()[0]] if n_pts > 0 else pd.Series(dtype=str)
                uniq = s.dropna().unique()
                n_unique = len(uniq)
                if n_unique > 50:
                    html += f"{n_unique} unique values (too many)"
                else:
                    top = s.value_counts().head(5)
                    html += f"{n_unique} unique values<br>"
                    for val, cnt in top.items():
                        pct = cnt / max(n_pts, 1) * 100
                        html += f"&nbsp;&nbsp;{val}: {cnt} ({pct:.0f}%)<br>"
                    if n_unique > 5:
                        html += f"<span style='color:#888;'>... +{n_unique - 5} more</span>"
            html += "</div>"
        html += "</div>"
        self.stats_label.setText(html)

    # ============================================================
    # Context menu (right-click on checkbox or subplot)
    # ============================================================
    def _show_col_context_menu(self, cb, pos):
        col = cb.property("col_name")
        ctype = cb.property("col_type")
        self._build_context_menu(col, ctype, cb.mapToGlobal(pos))

    def _on_detail_right_click(self, pos):
        """Right-click on the detail canvas → find which subplot, show menu."""
        if not self._detail_axes_cols:
            return
        # convert widget pos to figure coords
        h = self.detail_canvas.height()
        fig_y = 1.0 - pos.y() / h  # figure coords: 0=bottom, 1=top
        for ax, col in self._detail_axes_cols:
            bbox = ax.get_position()
            if bbox.y0 <= fig_y <= bbox.y1:
                self._build_context_menu(col, "numeric",
                                         self.detail_canvas.mapToGlobal(pos))
                return

    def _build_context_menu(self, col, ctype, global_pos):
        menu = QtWidgets.QMenu(self)

        # ---- reorder ----
        move_up = menu.addAction("Move Up")
        move_down = menu.addAction("Move Down")
        menu.addSeparator()

        # ---- transforms (numeric only) ----
        transforms = []
        if ctype == "numeric":
            transforms = [
                ("Negate  (× -1)", "negate"),
                ("Absolute Value  |x|", "abs"),
                ("Offset  (+ value)", "offset"),
                ("Scale  (× factor)", "scale"),
                ("Derivative  (d/dt)", "derivative"),
                ("Smooth  (moving avg)", "smooth"),
            ]
            for label, _ in transforms:
                menu.addAction(label)
            menu.addSeparator()
            reset_act = menu.addAction("Reset to Original")
        else:
            reset_act = None

        # ---- modified indicator ----
        if self.df_original is not None and col in self.df_original.columns:
            if ctype == "numeric" and not self.df[col].equals(self.df_original[col]):
                info = menu.addAction("(modified)")
                info.setEnabled(False)

        action = menu.exec_(global_pos)
        if action is None:
            return

        text = action.text()
        if action == move_up:
            self._move_column(col, -1)
        elif action == move_down:
            self._move_column(col, +1)
        elif reset_act and action == reset_act:
            self._reset_column(col)
        else:
            # match transform
            for label, key in transforms:
                if text == label:
                    self._apply_transform(col, key)
                    break

    def _move_column(self, col, direction):
        """Move a column up (-1) or down (+1) in the plot order."""
        # ensure _col_order is populated
        if not self._col_order:
            self._col_order = list(self._get_checked_columns())
        idx = None
        for i, (c, _) in enumerate(self._col_order):
            if c == col:
                idx = i
                break
        if idx is None:
            return
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(self._col_order):
            return
        self._col_order[idx], self._col_order[new_idx] = \
            self._col_order[new_idx], self._col_order[idx]
        self._debounce.start()

    def _apply_transform(self, col, key):
        """Apply a transform to a numeric column in self.df."""
        if self.df is None or col not in self.df.columns:
            return
        y = pd.to_numeric(self.df[col], errors="coerce")

        if key == "negate":
            self.df[col] = -y
        elif key == "abs":
            self.df[col] = y.abs()
        elif key == "offset":
            val, ok = QtWidgets.QInputDialog.getDouble(
                self, "Offset", f"Add value to '{col}':", 0.0, -1e9, 1e9, 4
            )
            if not ok:
                return
            self.df[col] = y + val
        elif key == "scale":
            val, ok = QtWidgets.QInputDialog.getDouble(
                self, "Scale", f"Multiply '{col}' by:", 1.0, -1e9, 1e9, 4
            )
            if not ok:
                return
            self.df[col] = y * val
        elif key == "derivative":
            if self.t is not None and len(self.t) > 1:
                dy = np.gradient(y.to_numpy(dtype=float), self.t)
                self.df[col] = dy
            else:
                return
        elif key == "smooth":
            win, ok = QtWidgets.QInputDialog.getInt(
                self, "Smooth", f"Window size for '{col}':", 5, 3, 501, 2
            )
            if not ok:
                return
            if win % 2 == 0:
                win += 1  # ensure odd
            self.df[col] = y.rolling(win, center=True, min_periods=1).mean()

        self._debounce.start()

    def _reset_column(self, col):
        """Restore a column to its original values."""
        if self.df_original is not None and col in self.df_original.columns:
            self.df[col] = self.df_original[col].copy()
            self._debounce.start()

    # ============================================================
    # Compat
    # ============================================================
    def refresh_data(self):
        if callable(self.data_dir_provider):
            self.set_folder(self.data_dir_provider(), selected_file=None)
