#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
from pathlib import Path

import numpy as np
import pandas as pd

from PyQt5 import QtWidgets
from PyQt5.QtCore import Qt


def match_motion_tag(series, keywords):
    s = series.astype(str)
    mask = None
    for k in keywords:
        m = s.str.contains(k, case=False, na=False)
        mask = m if mask is None else (mask | m)
    if mask is None or not mask.any():
        mask = s.isin(keywords)
    return mask


def safe_stat(x):
    x = pd.to_numeric(x, errors="coerce")
    return x.replace([np.inf, -np.inf], np.nan)


def compute_metrics(sub_df, angle_col, vel_col, torque_col, scale):
    angle = safe_stat(sub_df[angle_col])
    vel = safe_stat(sub_df[vel_col])
    torque = safe_stat(sub_df[torque_col]) * scale
    vel_rad = np.deg2rad(vel)
    power = torque * vel_rad

    rms_torque = np.sqrt(np.nanmean(torque ** 2))
    t_min, t_max = np.nanmin(torque), np.nanmax(torque)
    a_min, a_max = np.nanmin(angle), np.nanmax(angle)
    v_min, v_max = np.nanmin(vel), np.nanmax(vel)

    torque_range = f"[{t_min:.3f},{t_max:.3f}]"
    angle_range = f"[{a_min:.3f},{a_max:.3f}]"
    velocity_range = f"[{v_min:.3f},{v_max:.3f}]"

    peak_angle = np.nanmax(np.abs(angle))
    peak_velocity = np.nanmax(np.abs(vel))

    pos = power[power > 0]
    neg = power[power < 0]
    mean_positive_power = np.nanmean(pos) if len(pos) else np.nan
    mean_negative_power = np.nanmean(neg) if len(neg) else np.nan
    denom = np.nansum(np.abs(power))
    positive_power_ratio = np.nansum(pos) / denom if denom and np.isfinite(denom) else np.nan

    return {
        "rms_torque": rms_torque,
        "torque_range": torque_range,
        "angle_range": angle_range,
        "peak_angle": peak_angle,
        "velocity_range": velocity_range,
        "peak_velocity": peak_velocity,
        "mean_positive_power": mean_positive_power,
        "mean_negative_power": mean_negative_power,
        "positive_power_ratio": positive_power_ratio,
    }


def parse_range(s):
    s = str(s)
    if not s.startswith("["):
        return (np.nan, np.nan)
    try:
        a, b = s.strip("[]").split(",")
        return (float(a), float(b))
    except Exception:
        return (np.nan, np.nan)


class ReportPage(QtWidgets.QWidget):
    def __init__(self, data_dir_provider, mapping_path_provider):
        super().__init__()
        self.data_dir_provider = data_dir_provider
        self.mapping_path_provider = mapping_path_provider
        self.summary_df = None
        self.summary_avg = None
        self._build_ui()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        control = QtWidgets.QWidget()
        control.setObjectName("sectionPanel")
        control_layout = QtWidgets.QVBoxLayout(control)
        control_layout.setContentsMargins(10, 10, 10, 10)
        control_layout.setSpacing(6)
        control_title = QtWidgets.QLabel("Report")
        control_title.setObjectName("sectionTitle")
        control_layout.addWidget(control_title)
        form = QtWidgets.QGridLayout()
        control_layout.addLayout(form)
        self.file_name = QtWidgets.QLineEdit("mme_summary")
        self.gen_btn = QtWidgets.QPushButton("Generate + Save CSV")
        self.tag_list = QtWidgets.QListWidget()
        self.tag_list.setMaximumHeight(140)
        self.tag_all_btn = QtWidgets.QPushButton("Select All Tags")
        self.tag_none_btn = QtWidgets.QPushButton("Clear Tags")
        self.status = QtWidgets.QLabel("Ready.")
        self.status.setWordWrap(True)
        form.addWidget(QtWidgets.QLabel("Output name:"), 0, 0)
        form.addWidget(self.file_name, 0, 1)
        form.addWidget(self.gen_btn, 0, 2)
        form.addWidget(QtWidgets.QLabel("Tags:"), 1, 0)
        form.addWidget(self.tag_list, 1, 1, 1, 2)
        form.addWidget(self.tag_all_btn, 2, 1)
        form.addWidget(self.tag_none_btn, 2, 2)
        form.addWidget(self.status, 3, 0, 1, 3)

        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(0)
        self.table.setRowCount(0)

        layout.addWidget(control)
        layout.addWidget(self.table, 1)

        self.gen_btn.clicked.connect(self.generate_and_save)
        self.tag_all_btn.clicked.connect(self._select_all_tags)
        self.tag_none_btn.clicked.connect(self._clear_tags)
        self._populate_tags()

    def refresh_data(self):
        self._populate_tags()

    def _populate_tags(self):
        self.tag_list.clear()
        data_dir = self.data_dir_provider()
        if not os.path.isdir(data_dir):
            return
        tags = set()
        for fp in Path(data_dir).glob("*.csv"):
            try:
                df = pd.read_csv(fp, usecols=["tag"])
            except Exception:
                continue
            if "tag" in df.columns:
                tags.update([str(t) for t in df["tag"].dropna().unique().tolist()])
        for t in sorted(tags):
            item = QtWidgets.QListWidgetItem(t)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.tag_list.addItem(item)

    def _selected_tags(self):
        tags = []
        for i in range(self.tag_list.count()):
            item = self.tag_list.item(i)
            if item.checkState() == Qt.Checked:
                tags.append(item.text())
        return tags

    def _select_all_tags(self):
        for i in range(self.tag_list.count()):
            self.tag_list.item(i).setCheckState(Qt.Checked)

    def _clear_tags(self):
        for i in range(self.tag_list.count()):
            self.tag_list.item(i).setCheckState(Qt.Unchecked)

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

    def _set_table(self, df):
        self.table.clear()
        if df is None or df.empty:
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            return
        self.table.setColumnCount(len(df.columns))
        self.table.setRowCount(len(df))
        self.table.setHorizontalHeaderLabels(list(df.columns))
        for r in range(len(df)):
            for c, col in enumerate(df.columns):
                val = df.iloc[r, c]
                item = QtWidgets.QTableWidgetItem(str(val))
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()

    def generate_and_save(self):
        data_dir = self.data_dir_provider()
        if not os.path.isdir(data_dir):
            self.status.setText(f"Data dir not found: {data_dir}")
            return

        negate_cols = [
            "imu_LTx", "imu_Lvel", "imu_RTx", "imu_Rvel",
            "M1_torque_command", "M2_torque_command",
            "raw_LExoTorque", "raw_RExoTorque",
            "filtered_LExoTorque", "filtered_RExoTorque",
        ]

        torque_scale_map = {}

        use_cols = [
            "Time_ms", "imu_RTx", "imu_LTx", "imu_Rvel", "imu_Lvel",
            "M1_torque_command", "M2_torque_command",
            "raw_LExoTorque", "raw_RExoTorque",
            "filtered_LExoTorque", "filtered_RExoTorque",
            "tag",
        ]

        rows = []
        mapping = self._load_mapping()
        files = sorted(Path(data_dir).glob("*.csv"))
        if not files:
            self.status.setText("No CSV files found.")
            return

        for fp in files:
            subject = fp.stem
            try:
                df = pd.read_csv(fp)
            except Exception:
                continue
            if mapping:
                df = self._apply_mapping(df, mapping)
            cols = [c for c in use_cols if c in df.columns]
            df = df[cols].dropna(how="all").reset_index(drop=True)

            for c in negate_cols:
                if c in df.columns:
                    df[c] = -pd.to_numeric(df[c], errors="coerce")

            selected_tags = self._selected_tags()
            if not selected_tags:
                if "tag" in df.columns:
                    selected_tags = sorted({str(t) for t in df["tag"].dropna().unique().tolist()})
            for tag in selected_tags:
                if "tag" not in df.columns:
                    continue
                motion_df = df[df["tag"].astype(str) == str(tag)].reset_index(drop=True)
                if motion_df.empty:
                    continue
                scale = torque_scale_map.get(tag, 1.0)

                if all(c in motion_df.columns for c in ["imu_LTx", "imu_Lvel", "M2_torque_command"]):
                    mL = compute_metrics(motion_df, "imu_LTx", "imu_Lvel", "M2_torque_command", scale)
                    rows.append({"subject": subject, "tag": tag, "leg": "L", **mL})

                if all(c in motion_df.columns for c in ["imu_RTx", "imu_Rvel", "M1_torque_command"]):
                    mR = compute_metrics(motion_df, "imu_RTx", "imu_Rvel", "M1_torque_command", scale)
                    rows.append({"subject": subject, "tag": tag, "leg": "R", **mR})

        summary_df = pd.DataFrame(rows)
        if summary_df.empty:
            self.status.setText("No rows generated.")
            return

        summary_df = summary_df[[
            "subject", "tag", "leg",
            "rms_torque", "torque_range", "angle_range", "peak_angle",
            "velocity_range", "peak_velocity",
            "mean_positive_power", "mean_negative_power", "positive_power_ratio",
        ]]

        metrics = [
            "rms_torque", "torque_range", "angle_range", "peak_angle",
            "velocity_range", "peak_velocity",
            "mean_positive_power", "mean_negative_power", "positive_power_ratio",
        ]
        L_df = summary_df[summary_df["leg"] == "L"].drop(columns=["leg"]).rename(
            columns={m: f"L_{m}" for m in metrics}
        )
        R_df = summary_df[summary_df["leg"] == "R"].drop(columns=["leg"]).rename(
            columns={m: f"R_{m}" for m in metrics}
        )
        summary_wide = pd.merge(L_df, R_df, on=["subject", "tag"], how="outer")
        summary_wide = summary_wide[[
            "subject", "tag",
            "L_rms_torque", "R_rms_torque",
            "L_torque_range", "R_torque_range",
            "L_angle_range", "R_angle_range",
            "L_peak_angle", "R_peak_angle",
            "L_velocity_range", "R_velocity_range",
            "L_peak_velocity", "R_peak_velocity",
            "L_mean_positive_power", "R_mean_positive_power",
            "L_mean_negative_power", "R_mean_negative_power",
            "L_positive_power_ratio", "R_positive_power_ratio",
        ]]

        avg_cols = [
            "angle_range", "velocity_range", "torque_range", "rms_torque",
            "mean_positive_power", "mean_negative_power", "positive_power_ratio",
        ]
        avg_rows = []
        for _, row in summary_wide.iterrows():
            out = {"subject": row["subject"], "tag": row["tag"]}
            for m in ["rms_torque", "mean_positive_power", "mean_negative_power", "positive_power_ratio"]:
                L = row.get(f"L_{m}")
                R = row.get(f"R_{m}")
                out[m] = np.nanmean([L, R])
            for m in ["angle_range", "velocity_range", "torque_range"]:
                L_min, L_max = parse_range(row.get(f"L_{m}", np.nan))
                R_min, R_max = parse_range(row.get(f"R_{m}", np.nan))
                avg_min = np.nanmean([L_min, R_min])
                avg_max = np.nanmean([L_max, R_max])
                out[m] = f"[{avg_min:.3f},{avg_max:.3f}]"
            avg_rows.append(out)

        summary_avg = pd.DataFrame(avg_rows)
        summary_avg = summary_avg[["subject", "tag"] + avg_cols]

        out_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data_output", "output")
        out_dir = os.path.abspath(out_dir)
        os.makedirs(out_dir, exist_ok=True)

        base = self.file_name.text().strip() or "mme_summary"
        out_main = os.path.join(out_dir, f"{base}.csv")
        out_avg = os.path.join(out_dir, f"{base}_avg.csv")

        summary_wide.to_csv(out_main, index=False)
        summary_avg.to_csv(out_avg, index=False)

        self.summary_df = summary_wide
        self.summary_avg = summary_avg
        self._set_table(summary_wide)
        self.status.setText(f"Saved: {out_main} | {out_avg} (overwritten if existed)")
