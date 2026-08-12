from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import numpy as np

from photon_cruncher.model import Epoc, PhotometrySession


SAMPLE_INDEX_EPSILON = 0.005


@dataclass
class ProcessingSettings:
    trange: tuple[float, float] = (-2.0, 5.0)
    baseline_per: tuple[float, float] = (-3.0, -1.0)
    base_adjust: float = -30.0
    plot_smooth: bool = True
    set_baseline: bool = True
    downsample_factor: int = 10
    smooth_factor: int = 10
    artifact_405: float = np.inf
    artifact_465: float = np.inf
    use_isosbestic: bool = True
    polynomial_degree: int = 1


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
    num_edge_trials: int = 0
    dropped_edge_trials: list[int] = field(default_factory=list)
    trial_numbers: list[int] = field(default_factory=list)
    trial_labels: list[str] = field(default_factory=list)
    trial_times: list[float] = field(default_factory=list)
    baseline_standard_deviations: list[float] = field(default_factory=list)


@dataclass
class ExtractedTrials:
    trials: list[np.ndarray]
    trial_numbers: list[int]
    dropped_edge_trials: list[int]


def _moving_mean(trace: np.ndarray, window: int) -> np.ndarray:
    if window <= 1:
        return trace.copy()
    kernel = np.ones(window, dtype=float)
    summed = np.convolve(trace, kernel, mode="same")
    counts = np.convolve(np.ones_like(trace, dtype=float), kernel, mode="same")
    return summed / counts


def _moving_mean_rows(data: np.ndarray, window: int) -> np.ndarray:
    if window <= 1:
        return data.copy()
    if data.size == 0:
        return data.copy()
    smoothed = np.empty_like(data, dtype=float)
    for row_idx in range(data.shape[0]):
        smoothed[row_idx, :] = _moving_mean(data[row_idx, :], window)
    return smoothed


def _extract_trials(
    stream: np.ndarray,
    fs: float,
    onsets: np.ndarray,
    trange: tuple[float, float],
    t0: float = 0.0,
) -> list[np.ndarray]:
    return _extract_trials_with_edge_drops(stream, fs, onsets, trange, t0).trials


def _extract_trials_with_edge_drops(
    stream: np.ndarray,
    fs: float,
    onsets: np.ndarray,
    trange: tuple[float, float],
    t0: float = 0.0,
) -> ExtractedTrials:
    trials: list[np.ndarray] = []
    trial_numbers: list[int] = []
    dropped_edge_trials: list[int] = []
    stream_size = int(stream.size)
    for trial_idx, onset in enumerate(onsets, start=1):
        start_time = onset + trange[0]
        end_time = onset + trange[1]
        start_idx = int(np.rint((start_time - t0) * fs + SAMPLE_INDEX_EPSILON))
        end_idx = int(np.rint((end_time - t0) * fs + SAMPLE_INDEX_EPSILON)) + 1
        if start_idx < 0 or end_idx > stream_size:
            dropped_edge_trials.append(trial_idx)
            continue
        if end_idx > start_idx:
            trials.append(stream[start_idx:end_idx])
            trial_numbers.append(trial_idx)
    return ExtractedTrials(
        trials=trials,
        trial_numbers=trial_numbers,
        dropped_edge_trials=dropped_edge_trials,
    )


def _artifact_mask(trials: list[np.ndarray], artifact: float) -> np.ndarray:
    if not trials:
        return np.array([], dtype=bool)
    if np.isinf(artifact):
        return np.ones(len(trials), dtype=bool)

    lengths = {trial.size for trial in trials}
    if len(lengths) == 1:
        arr = np.vstack(trials)
        return (arr.max(axis=1) <= artifact) & (arr.min(axis=1) >= -artifact)

    good_mask = np.empty(len(trials), dtype=bool)
    for idx, trial in enumerate(trials):
        good_mask[idx] = not (np.any(trial > artifact) or np.any(trial < -artifact))
    return good_mask


def _remove_artifacts(trials: list[np.ndarray], artifact: float) -> tuple[list[np.ndarray], np.ndarray]:
    good_mask_array = _artifact_mask(trials, artifact)
    filtered = [trial for trial, keep in zip(trials, good_mask_array) if keep]
    return filtered, good_mask_array


def _trim_trials(trials: list[np.ndarray], min_length: int) -> list[np.ndarray]:
    return [trial[:min_length] for trial in trials]


def _downsample_trials(trials: list[np.ndarray], factor: int) -> np.ndarray:
    if not trials:
        return np.empty((0, 0), dtype=float)
    if factor <= 1:
        return np.vstack(trials)

    lengths = {trial.size for trial in trials}
    if len(lengths) == 1:
        arr = np.vstack(trials)
        bins = arr.shape[1] // factor
        if bins == 0:
            return np.empty((arr.shape[0], 0), dtype=float)
        trimmed = arr[:, : bins * factor]
        return trimmed.reshape(arr.shape[0], bins, factor).mean(axis=2)

    downsampled = []
    for trial in trials:
        bins = trial.size // factor
        trimmed = trial[: bins * factor]
        reshaped = trimmed.reshape(bins, factor)
        downsampled.append(reshaped.mean(axis=1))
    return np.vstack(downsampled)


def _mean_and_sem(z_data: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mean = z_data.mean(axis=0)
    if z_data.shape[0] <= 1:
        sem = np.zeros_like(mean)
    else:
        sem = z_data.std(axis=0, ddof=1) / np.sqrt(z_data.shape[0])
    return mean, sem


def _baseline_correct(z_data: np.ndarray, ts: np.ndarray, base_adjust: float) -> np.ndarray:
    idx_candidates = np.where(ts > base_adjust)[0]
    if idx_candidates.size == 0:
        return z_data
    idx = int(idx_candidates[0])
    vals = z_data[:, idx]
    return z_data - vals[:, None]


def _zscore_trials(y_df_all: np.ndarray, baseline_mask: np.ndarray) -> np.ndarray:
    if y_df_all.size == 0:
        return y_df_all.copy()
    base = y_df_all[:, baseline_mask]
    zb = base.mean(axis=1, keepdims=True)
    zsd = base.std(axis=1, ddof=1, keepdims=True)
    return (y_df_all - zb) / zsd


def process_channel(
    session: PhotometrySession,
    iso_stream: str | None,
    signal_stream: str,
    epoc: Epoc,
    settings: ProcessingSettings,
) -> ProcessedSignal:
    stream_465 = session.streams[signal_stream]

    extracted_465 = _extract_trials_with_edge_drops(
        stream_465.data,
        stream_465.fs,
        epoc.onset,
        settings.trange,
        stream_465.t0,
    )
    trials_by_number_465 = dict(zip(extracted_465.trial_numbers, extracted_465.trials))
    if settings.use_isosbestic:
        if settings.polynomial_degree < 1:
            raise ValueError("Polynomial fit degree must be at least 1.")
        if not iso_stream or iso_stream not in session.streams:
            raise ValueError(
                "A paired 405 isosbestic stream is required when isosbestic fitting is enabled."
            )
        stream_405 = session.streams[iso_stream]
        extracted_405 = _extract_trials_with_edge_drops(
            stream_405.data,
            stream_405.fs,
            epoc.onset,
            settings.trange,
            stream_405.t0,
        )
        trials_by_number_405 = dict(
            zip(extracted_405.trial_numbers, extracted_405.trials)
        )
        kept_trial_numbers = sorted(
            set(trials_by_number_405).intersection(trials_by_number_465)
        )
        trials_405 = [
            trials_by_number_405[number] for number in kept_trial_numbers
        ]
        trials_465 = [
            trials_by_number_465[number] for number in kept_trial_numbers
        ]
        dropped_edge_trials = sorted(
            set(extracted_405.dropped_edge_trials)
            | set(extracted_465.dropped_edge_trials)
        )

        if not trials_405 or not trials_465:
            raise ValueError("No complete trials remain after dropping edge trials.")

        good_405 = _artifact_mask(trials_405, settings.artifact_405)
        good_465 = _artifact_mask(trials_465, settings.artifact_465)
        good_trials = good_405 & good_465
        num_artifacts = int((~good_trials).sum())
        trials_405 = [
            trial for trial, keep in zip(trials_405, good_trials) if keep
        ]
        trials_465 = [
            trial for trial, keep in zip(trials_465, good_trials) if keep
        ]
        kept_trial_numbers = [
            number
            for number, keep in zip(kept_trial_numbers, good_trials)
            if keep
        ]

        if not trials_405 or not trials_465:
            raise ValueError("No trials remain after artifact removal.")

        min_len_405 = min(trial.size for trial in trials_405)
        min_len_465 = min(trial.size for trial in trials_465)
        trials_405 = _trim_trials(trials_405, min_len_405)
        trials_465 = _trim_trials(trials_465, min_len_465)

        f405 = _downsample_trials(trials_405, settings.downsample_factor)
        f465 = _downsample_trials(trials_465, settings.downsample_factor)
        common_length = min(f405.shape[1], f465.shape[1])
        f405 = f405[:, :common_length]
        f465 = f465[:, :common_length]
    else:
        kept_trial_numbers = list(extracted_465.trial_numbers)
        dropped_edge_trials = list(extracted_465.dropped_edge_trials)
        trials_465 = list(extracted_465.trials)
        if not trials_465:
            raise ValueError("No complete trials remain after dropping edge trials.")

        good_465 = _artifact_mask(trials_465, settings.artifact_465)
        num_artifacts = int((~good_465).sum())
        trials_465 = [
            trial for trial, keep in zip(trials_465, good_465) if keep
        ]
        kept_trial_numbers = [
            number
            for number, keep in zip(kept_trial_numbers, good_465)
            if keep
        ]
        if not trials_465:
            raise ValueError("No trials remain after artifact removal.")

        min_len_465 = min(trial.size for trial in trials_465)
        trials_465 = _trim_trials(trials_465, min_len_465)
        f465 = _downsample_trials(trials_465, settings.downsample_factor)

    min_length2 = f465.shape[1]
    ts2 = settings.trange[0] + (
        np.arange(1, min_length2 + 1) / stream_465.fs * settings.downsample_factor
    )

    if settings.use_isosbestic:
        if settings.polynomial_degree >= f405.size:
            raise ValueError(
                "Polynomial fit degree must be smaller than the number of fitted samples."
            )
        # Fit the control stream to the signal stream, preserving the
        # MATLAB-compatible Fortran-order trial flattening.
        bls = np.polyfit(
            f405.flatten(order="F"),
            f465.flatten(order="F"),
            settings.polynomial_degree,
        )
        y_fit_all = np.polyval(bls, f405)
        y_df_all = f465 - y_fit_all
    else:
        y_df_all = f465

    baseline_mask = (ts2 < settings.baseline_per[1]) & (ts2 > settings.baseline_per[0])
    baseline_standard_deviations = (
        y_df_all[:, baseline_mask].std(axis=1, ddof=1).astype(float).tolist()
    )
    zall = _zscore_trials(y_df_all, baseline_mask)
    zall_smooth = _moving_mean_rows(zall, settings.smooth_factor)

    if settings.set_baseline:
        zall_smooth = _baseline_correct(zall_smooth, ts2, settings.base_adjust)

    mean_z_smooth, sem_z_smooth = _mean_and_sem(zall_smooth)

    if settings.set_baseline:
        zall = _baseline_correct(zall, ts2, settings.base_adjust)

    mean_z, sem_z = _mean_and_sem(zall)

    return ProcessedSignal(
        ts=ts2,
        zall=zall,
        zall_smooth=zall_smooth,
        mean_z=mean_z,
        sem_z=sem_z,
        mean_z_smooth=mean_z_smooth,
        sem_z_smooth=sem_z_smooth,
        num_artifacts=num_artifacts,
        num_edge_trials=len(dropped_edge_trials),
        dropped_edge_trials=dropped_edge_trials,
        trial_numbers=kept_trial_numbers,
        baseline_standard_deviations=baseline_standard_deviations,
    )


def subset_processed_signal(
    processed: ProcessedSignal,
    selected_trial_numbers: Iterable[int],
) -> ProcessedSignal:
    selected = {int(number) for number in selected_trial_numbers}
    if not selected:
        raise ValueError("Select at least one trial.")

    trial_numbers = (
        processed.trial_numbers
        if processed.trial_numbers
        else list(range(1, processed.zall.shape[0] + 1))
    )
    keep_mask = np.array([number in selected for number in trial_numbers], dtype=bool)
    if not keep_mask.any():
        raise ValueError("None of the selected trials are available for this channel.")

    zall = processed.zall[keep_mask, :].copy()
    zall_smooth = processed.zall_smooth[keep_mask, :].copy()
    mean_z, sem_z = _mean_and_sem(zall)
    mean_z_smooth, sem_z_smooth = _mean_and_sem(zall_smooth)
    kept_trial_numbers = [
        number for number, keep in zip(trial_numbers, keep_mask) if keep
    ]
    trial_labels = (
        [
            label
            for label, keep in zip(processed.trial_labels, keep_mask)
            if keep
        ]
        if len(processed.trial_labels) == len(trial_numbers)
        else []
    )
    trial_times = (
        [
            time
            for time, keep in zip(processed.trial_times, keep_mask)
            if keep
        ]
        if len(processed.trial_times) == len(trial_numbers)
        else []
    )
    baseline_standard_deviations = (
        [
            value
            for value, keep in zip(
                processed.baseline_standard_deviations,
                keep_mask,
            )
            if keep
        ]
        if len(processed.baseline_standard_deviations) == len(trial_numbers)
        else []
    )

    return ProcessedSignal(
        ts=processed.ts.copy(),
        zall=zall,
        zall_smooth=zall_smooth,
        mean_z=mean_z,
        sem_z=sem_z,
        mean_z_smooth=mean_z_smooth,
        sem_z_smooth=sem_z_smooth,
        num_artifacts=processed.num_artifacts,
        num_edge_trials=processed.num_edge_trials,
        dropped_edge_trials=list(processed.dropped_edge_trials),
        trial_numbers=kept_trial_numbers,
        trial_labels=trial_labels,
        trial_times=trial_times,
        baseline_standard_deviations=baseline_standard_deviations,
    )


def available_channels(session: PhotometrySession) -> dict[str, tuple[str | None, str, int]]:
    """Return signal channels, with a paired 405 stream when available.

    Signal-only sessions remain analyzable when isosbestic fitting is disabled.
    Corrected processing still requires the corresponding 405 stream.
    """
    mapping: dict[str, tuple[str | None, str, int]] = {}
    channel_specs = (
        ("A_465", "x405A", "x465A", 10),
        ("A_560", "x405A", "x560A", 30),
        ("C_465", "x405C", "x465C", 50),
        ("C_560", "x405C", "x560C", 20),
    )
    for channel_key, control_stream, signal_stream, default_smooth in channel_specs:
        if signal_stream in session.streams:
            mapping[channel_key] = (
                control_stream if control_stream in session.streams else None,
                signal_stream,
                default_smooth,
            )
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
