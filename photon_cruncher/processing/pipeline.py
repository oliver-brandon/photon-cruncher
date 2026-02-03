from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np

from photon_cruncher.model import Epoc, PhotometrySession


@dataclass
class ProcessingSettings:
    trange: tuple[float, float] = (-2.0, 7.0)
    baseline_per: tuple[float, float] = (-3.0, -1.0)
    base_adjust: float = -30.0
    plot_smooth: bool = True
    set_baseline: bool = True
    downsample_factor: int = 10
    smooth_factor: int = 10
    artifact_405: float = np.inf
    artifact_465: float = np.inf


@dataclass
class ProcessedSignal:
    ts: np.ndarray
    zall: np.ndarray
    zall_smooth: np.ndarray
    mean_z: np.ndarray
    sem_z: np.ndarray
    mean_z_smooth: np.ndarray
    sem_z_smooth: np.ndarray
    num_artifacts: int


def _moving_mean(trace: np.ndarray, window: int) -> np.ndarray:
    if window <= 1:
        return trace.copy()
    kernel = np.ones(window, dtype=float) / window
    return np.convolve(trace, kernel, mode="same")


def _extract_trials(stream: np.ndarray, fs: float, onsets: np.ndarray, trange: tuple[float, float]) -> list[np.ndarray]:
    time = np.arange(stream.size) / fs
    trials: list[np.ndarray] = []
    for onset in onsets:
        start_time = onset + trange[0]
        end_time = onset + trange[1]
        start_idx = int(np.searchsorted(time, start_time, side="left"))
        end_idx = int(np.searchsorted(time, end_time, side="right"))
        if end_idx > start_idx:
            trials.append(stream[start_idx:end_idx])
    return trials


def _remove_artifacts(trials: list[np.ndarray], artifact: float) -> tuple[list[np.ndarray], np.ndarray]:
    good_mask = []
    for trial in trials:
        has_pos = np.any(trial > artifact)
        has_neg = np.any(trial < -artifact)
        good_mask.append(not (has_pos or has_neg))
    good_mask_array = np.array(good_mask, dtype=bool)
    filtered = [trial for trial, keep in zip(trials, good_mask_array) if keep]
    return filtered, good_mask_array


def _trim_trials(trials: list[np.ndarray], min_length: int) -> list[np.ndarray]:
    return [trial[:min_length] for trial in trials]


def _downsample_trials(trials: list[np.ndarray], factor: int) -> np.ndarray:
    if factor <= 1:
        return np.vstack([trial for trial in trials])
    downsampled = []
    for trial in trials:
        bins = trial.size // factor
        trimmed = trial[: bins * factor]
        reshaped = trimmed.reshape(bins, factor)
        downsampled.append(reshaped.mean(axis=1))
    return np.vstack(downsampled)


def _baseline_correct(z_data: np.ndarray, ts: np.ndarray, base_adjust: float) -> np.ndarray:
    idx_candidates = np.where(ts > base_adjust)[0]
    if idx_candidates.size == 0:
        return z_data
    idx = idx_candidates[0]
    corrected = z_data.copy()
    for row in range(corrected.shape[0]):
        val = corrected[row, idx]
        diff = 0 - val
        if val < 0:
            corrected[row, :] = corrected[row, :] + abs(diff)
        elif val > 0:
            corrected[row, :] = corrected[row, :] - abs(diff)
    return corrected


def process_channel(
    session: PhotometrySession,
    iso_stream: str,
    signal_stream: str,
    epoc: Epoc,
    settings: ProcessingSettings,
) -> ProcessedSignal:
    stream_405 = session.streams[iso_stream]
    stream_465 = session.streams[signal_stream]

    trials_405 = _extract_trials(stream_405.data, stream_405.fs, epoc.onset, settings.trange)
    trials_465 = _extract_trials(stream_465.data, stream_465.fs, epoc.onset, settings.trange)

    trials_405, good_405 = _remove_artifacts(trials_405, settings.artifact_405)
    trials_465, good_465 = _remove_artifacts(trials_465, settings.artifact_465)
    num_artifacts = int((~good_405).sum() + (~good_465).sum())

    if not trials_405 or not trials_465:
        raise ValueError("No trials remain after artifact removal.")

    min_len_405 = min(trial.size for trial in trials_405)
    min_len_465 = min(trial.size for trial in trials_465)
    trials_405 = _trim_trials(trials_405, min_len_405)
    trials_465 = _trim_trials(trials_465, min_len_465)

    f405 = _downsample_trials(trials_405, settings.downsample_factor)
    f465 = _downsample_trials(trials_465, settings.downsample_factor)

    min_length1 = f405.shape[1]
    min_length2 = f465.shape[1]

    mean_signal1 = f405.mean(axis=0)
    std_signal1 = f405.std(axis=0, ddof=1) / np.sqrt(f405.shape[0])
    dc_signal1 = mean_signal1.mean()

    mean_signal2 = f465.mean(axis=0)
    std_signal2 = f465.std(axis=0, ddof=1) / np.sqrt(f465.shape[0])
    dc_signal2 = mean_signal2.mean()

    _ = std_signal1
    _ = std_signal2

    ts1 = settings.trange[0] + (np.arange(1, min_length1 + 1) / stream_405.fs * settings.downsample_factor)
    ts2 = settings.trange[0] + (np.arange(1, min_length2 + 1) / stream_465.fs * settings.downsample_factor)

    mean_signal1 = mean_signal1 - dc_signal1
    mean_signal2 = mean_signal2 - dc_signal2

    bls = np.polyfit(f465.flatten(order="F"), f405.flatten(order="F"), 1)
    y_fit_all = bls[0] * f405 + bls[1]
    y_df_all = f465 - y_fit_all

    zall = np.zeros_like(y_df_all)
    baseline_mask = (ts2 < settings.baseline_per[1]) & (ts2 > settings.baseline_per[0])
    for i in range(y_df_all.shape[0]):
        zb = y_df_all[i, baseline_mask].mean()
        zsd = y_df_all[i, baseline_mask].std(ddof=1)
        zall[i, :] = (y_df_all[i, :] - zb) / zsd

    zall_smooth = np.zeros_like(zall)
    for k in range(zall.shape[0]):
        zall_smooth[k, :] = _moving_mean(zall[k, :], settings.smooth_factor)

    if settings.set_baseline:
        zall_smooth = _baseline_correct(zall_smooth, ts1, settings.base_adjust)

    mean_z_smooth = zall_smooth.mean(axis=0)
    sem_z_smooth = zall_smooth.std(axis=0, ddof=1) / np.sqrt(zall_smooth.shape[0])

    if settings.set_baseline:
        zall = _baseline_correct(zall, ts1, settings.base_adjust)

    mean_z = zall.mean(axis=0)
    sem_z = zall.std(axis=0, ddof=1) / np.sqrt(zall.shape[0])

    return ProcessedSignal(
        ts=ts2,
        zall=zall,
        zall_smooth=zall_smooth,
        mean_z=mean_z,
        sem_z=sem_z,
        mean_z_smooth=mean_z_smooth,
        sem_z_smooth=sem_z_smooth,
        num_artifacts=num_artifacts,
    )


def available_channels(session: PhotometrySession) -> dict[str, tuple[str, str, int]]:
    mapping: dict[str, tuple[str, str, int]] = {}
    if "x405A" in session.streams:
        if "x465A" in session.streams:
            mapping["A_465"] = ("x405A", "x465A", 10)
        if "x560A" in session.streams:
            mapping["A_560"] = ("x405A", "x560A", 30)
    if "x405C" in session.streams:
        if "x465C" in session.streams:
            mapping["C_465"] = ("x405C", "x465C", 50)
        if "x560C" in session.streams:
            mapping["C_560"] = ("x405C", "x560C", 20)
    return mapping


def default_settings_for_channel(channel_key: str) -> ProcessingSettings:
    settings = ProcessingSettings()
    channel_map = {
        "A_465": 10,
        "A_560": 30,
        "C_465": 50,
        "C_560": 20,
    }
    settings.smooth_factor = channel_map.get(channel_key, 10)
    return settings
