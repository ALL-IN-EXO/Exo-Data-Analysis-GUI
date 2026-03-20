# conda activate mass

# 工具函数

from scipy.signal import butter, filtfilt, savgol_filter
from scipy.signal import find_peaks, lfilter, lfilter_zi
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import ipywidgets as widgets
from ipywidgets import VBox, HBox
from scipy.signal import savgol_filter


def lowpass_filter(data, cutoff=1.5, fs=50, order=4):
    nyq = 0.5 * fs          # 奈奎斯特频率
    normal_cutoff = cutoff / nyq
    b, a = butter(order, normal_cutoff, btype='low', analog=False)
    filtered_data = filtfilt(b, a, data)  # 双向滤波，避免相位偏移
    return filtered_data


class StreamingButterworth(object):
    def __init__(self, fc=5.0, nyq=100.0, order=2, num_joints=2):
        self.fc = float(fc)
        self.nyq = float(nyq)
        self.order = int(order)
        self.num_joints = int(num_joints)
        self.b, self.a = butter(self.order, self.fc / self.nyq, btype="low")
        self.zi = None

    def reset(self, x0):
        x0 = np.asarray(x0, dtype=float).reshape(self.num_joints)
        base = lfilter_zi(self.b, self.a)
        self.zi = np.tile(base[:, None], (1, self.num_joints)) * x0

    def filter_step(self, x):
        x = np.asarray(x, dtype=float).reshape(self.num_joints)
        if self.zi is None:
            self.reset(x)
        y = np.empty_like(x, dtype=float)
        for i in range(self.num_joints):
            yi, zi = lfilter(self.b, self.a, [x[i]], zi=self.zi[:, i])
            y[i] = yi[0]
            self.zi[:, i] = zi
        return y



def apply_filters_to_df(df,cutoff=1.5):
    """
    对整个 df 进行全局滤波：
    - 角度 imu_LTx, imu_RTx: low-pass 6 Hz
    - 角速度 imu_Lvel, imu_Rvel: SG smoothing
    - 力矩 M1/M2, P/D, HumanHip: low-pass 8 Hz
    """
    # ============ 角度滤波 ============
    for col in ["imu_LTx", "imu_RTx"]:
        if col in df.columns:
            df[col] = lowpass_filter(df[col],cutoff)

    # ============ 角速度滤波 ============
    for col in ["imu_Lvel", "imu_Rvel"]:
        if col in df.columns:
            df[col] = lowpass_filter(df[col],cutoff)
    # ============ 力矩滤波 ============
    torque_cols = [
        #"M1_torque_command", "M2_torque_command",
        "L_P","L_D","R_P","R_D",
        "HumanR_Hip_tau","HumanL_Hip_tau",
        "dHumanR_Hip_tau","dHumanL_Hip_tau","Left_Activation","Right_Activation"
    ]
    for col in torque_cols:
        if col in df.columns:
           df[col] = lowpass_filter(df[col],cutoff)

    return df


# ====== 工具函数 ======
def make_time_axis(time_series: pd.Series) -> np.ndarray:
    """
    将 Time 列统一转换为以秒为单位、从 0 开始的时间轴。
    支持：全数字（可能是毫秒）、时间戳字符串、其他无法识别时退化为行号。
    """
    t_num = pd.to_numeric(time_series, errors="coerce")
    if t_num.notna().mean() > 0.9:  # 大部分可当数字
        t = t_num.to_numpy()
        dt_med = np.nanmedian(np.diff(t)) if len(t) > 1 else 10.0  # 10ms 仅作占位
        # 若中位采样间隔在 1~1000（疑似毫秒），按毫秒处理
        if 1.0 <= dt_med <= 1000.0:
            return (t - t[0]) / 1000.0
        return (t - t[0])
    # 尝试解析为日期时间
    t_dt = pd.to_datetime(time_series, errors="coerce")
    if t_dt.notna().mean() > 0.9:
        return (t_dt - t_dt.iloc[0]).dt.total_seconds().to_numpy()
    # 兜底：用行号（秒）
    return np.arange(len(time_series), dtype=float)

def robust_read_csv(path, usecols):
    last_err = None
    for sep in ["\t", None, ","]:  # 先试制表符，再自动推断，最后逗号
        try:
            return pd.read_csv(path, sep=sep, engine="python", usecols=usecols, on_bad_lines="skip")
        except Exception as e:
            last_err = e
    raise RuntimeError(f"读取失败，请检查文件/分隔符/列名是否正确：{last_err}")

# =========================================================
# 速度计算
# =========================================================
def compute_smoothed_velocity(df, scale=30, window_length=31, polyorder=3):
    t = df["Time_ms"].values 
    angle_L = df["imu_LTx"].values
    angle_R = df["imu_RTx"].values

    vel_L_raw = np.gradient(angle_L, t)
    vel_R_raw = np.gradient(angle_R, t)

    vel_L_filt = savgol_filter(vel_L_raw, window_length, polyorder)
    vel_R_filt = savgol_filter(vel_R_raw, window_length, polyorder)

    df["imu_Lvel"] = vel_L_filt / scale
    df["imu_Rvel"] = vel_R_filt / scale
    return df

def rad2degree(df):
    df["imu_LTx"] = np.degrees(df["imu_LTx"])
    df["imu_RTx"] = np.degrees(df["imu_RTx"])
    df["imu_Lvel"] = np.degrees(df["imu_Lvel"])
    df["imu_Rvel"] = np.degrees(df["imu_Rvel"])
    return df

def compute_power(df):
    if "M2_torque_command" in df.columns:
        df["ExoL_Hip_power"] = df["M2_torque_command"] * df["imu_Lvel"]
        df["ExoR_Hip_power"] = df["M1_torque_command"] * df["imu_Rvel"]
    if "HumanL_Hip_tau" in df.columns:
        df["HumanL_Hip_power"] = df["HumanL_Hip_tau"] * df["imu_Lvel"]
        df["HumanR_Hip_power"] = df["HumanR_Hip_tau"] * df["imu_Rvel"]
    return df

def detect_cycle_peaks_from_angle(angle, fs, min_cycle_sec=0.6, prominence=None):
    """
    只用角度 angle 检测 gait cycle 起点（峰值）。
    返回 peaks（index数组）
    """
    distance = int(min_cycle_sec * fs)
    peaks, _ = find_peaks(angle, distance=distance, prominence=prominence)
    return peaks

def normalize_cycles_by_peaks(signal, peaks, fs, n_points=101, min_cycle_sec=0.6, max_cycle_sec=1.6):
    """
    使用同一组 peaks（来自角度）切分 signal，并归一化到 [0..1] 的 n_points。
    """
    cycles = []
    keep_pairs = []

    for i in range(len(peaks) - 1):
        s, e = int(peaks[i]), int(peaks[i+1])
        dur = (e - s) / fs
        if dur < min_cycle_sec or dur > max_cycle_sec:
            continue

        seg = signal[s:e]
        if len(seg) < 5:   # 防止极短段
            continue

        x_old = np.linspace(0, 1, len(seg))
        x_new = np.linspace(0, 1, n_points)
        cycles.append(np.interp(x_new, x_old, seg))
        keep_pairs.append((s, e))

    return np.asarray(cycles), keep_pairs



def mean_and_band(cycles, band='std'):
    mean = np.mean(cycles, axis=0)

    if band == 'std':
        std = np.std(cycles, axis=0)
        lo, hi = mean - std, mean + std
    elif band == 'p05p95':
        lo = np.percentile(cycles, 5, axis=0)
        hi = np.percentile(cycles, 95, axis=0)
    elif band == 'minmax':
        lo = np.min(cycles, axis=0)
        hi = np.max(cycles, axis=0)
    else:
        raise ValueError("band must be one of: std, p05p95, minmax")

    return mean, lo, hi
