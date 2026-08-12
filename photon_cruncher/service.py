"""Shared analysis service used by Aurora desktop GUI and CLI.

GUI layers must call this module (or thin wrappers around it) instead of
re-implementing load/process/export loops. Backend fixes land here once.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np

from photon_cruncher.analysis.trial_classifier import (
    ClassifiedTrialSource,
    classified_trial_sources,
)
from photon_cruncher import __version__
from photon_cruncher.export.exporter import (
    analysis_manifest_path,
    export_channel,
    save_result_figure,
    write_analysis_manifest,
)
from photon_cruncher.io.loader import load_session
from photon_cruncher.io.loader import discover_tdt_block_paths
from photon_cruncher.model import Epoc, PhotometrySession
from photon_cruncher.product import AURORA_APP_NAME
from photon_cruncher.processing.pipeline import (
    ProcessedSignal,
    ProcessingSettings,
    available_channels,
    default_settings_for_channel,
    process_channel,
    subset_processed_signal,
)


SettingsFactory = Callable[[str], ProcessingSettings]


@dataclass
class AnalysisResult:
    session: PhotometrySession
    epoc: Epoc
    channel_key: str
    processed: ProcessedSignal
    settings: ProcessingSettings
    stream_store: tuple[str, str]


@dataclass(frozen=True)
class ChannelInfo:
    key: str
    iso_stream: str
    signal_stream: str
    default_smooth: int


def open_session(path: str | Path) -> PhotometrySession:
    """Load a MAT file or TDT block into a PhotometrySession."""
    return load_session(Path(path))


def discover_data_sources(folder: str | Path) -> list[Path]:
    """Find MAT exports and TDT blocks below ``folder``."""
    root = Path(folder).expanduser()
    if not root.is_dir():
        raise ValueError(f"Data folder not found: {root}")
    paths = sorted(
        path for path in root.rglob("*") if path.is_file() and path.suffix.lower() == ".mat"
    )
    paths.extend(discover_tdt_block_paths(root))
    return list(dict.fromkeys(path.resolve() for path in paths))


def list_channels(session: PhotometrySession) -> list[ChannelInfo]:
    mapping = available_channels(session)
    return [
        ChannelInfo(
            key=key,
            iso_stream=iso or "",
            signal_stream=signal,
            default_smooth=smooth,
        )
        for key, (iso, signal, smooth) in mapping.items()
    ]


def list_epoc_names(session: PhotometrySession) -> list[str]:
    return sorted(session.epocs)


def list_classified_sources(session: PhotometrySession) -> list[ClassifiedTrialSource]:
    return classified_trial_sources(session)


def resolve_epoc(
    session: PhotometrySession,
    epoc_name: str,
) -> tuple[Epoc, ClassifiedTrialSource | None]:
    """Resolve a raw epoc name or classified source key/label."""
    if epoc_name in session.epocs:
        return session.epocs[epoc_name], None
    sources = classified_trial_sources(session)
    for source in sources:
        if epoc_name in {source.key, source.label}:
            return source.epoc, source
    available = sorted(session.epocs) + [source.label for source in sources]
    raise ValueError(
        f"epoc or classified source '{epoc_name}' not found; "
        f"available: {', '.join(available)}"
    )


def settings_for_channel(
    channel_key: str,
    *,
    overrides: dict[str, Any] | None = None,
) -> ProcessingSettings:
    settings = default_settings_for_channel(channel_key)
    if not overrides:
        return settings
    if "trange" in overrides:
        start, end = overrides["trange"]
        settings.trange = (float(start), float(end))
    if "trange_start" in overrides or "trange_end" in overrides:
        start = float(overrides.get("trange_start", settings.trange[0]))
        end = float(overrides.get("trange_end", settings.trange[1]))
        settings.trange = (start, end)
    if "baseline_per" in overrides:
        start, end = overrides["baseline_per"]
        settings.baseline_per = (float(start), float(end))
    if "baseline_start" in overrides or "baseline_end" in overrides:
        start = float(overrides.get("baseline_start", settings.baseline_per[0]))
        end = float(overrides.get("baseline_end", settings.baseline_per[1]))
        settings.baseline_per = (start, end)
    if "base_adjust" in overrides:
        settings.base_adjust = float(overrides["base_adjust"])
    if "baseline_adjust" in overrides:
        settings.base_adjust = float(overrides["baseline_adjust"])
    if "downsample_factor" in overrides:
        settings.downsample_factor = int(overrides["downsample_factor"])
    if "smooth_factor" in overrides and overrides["smooth_factor"] is not None:
        settings.smooth_factor = int(overrides["smooth_factor"])
    if "artifact_405" in overrides:
        value = overrides["artifact_405"]
        settings.artifact_405 = float("inf") if value is None else float(value)
    if "artifact_465" in overrides:
        value = overrides["artifact_465"]
        settings.artifact_465 = float("inf") if value is None else float(value)
    if "use_isosbestic" in overrides:
        settings.use_isosbestic = bool(overrides["use_isosbestic"])
    if "polynomial_degree" in overrides:
        settings.polynomial_degree = int(overrides["polynomial_degree"])
        if settings.polynomial_degree < 1:
            raise ValueError("polynomial_degree must be at least 1")
    if "plot_smooth" in overrides:
        settings.plot_smooth = bool(overrides["plot_smooth"])
    if "plot_smoothed" in overrides:
        settings.plot_smooth = bool(overrides["plot_smoothed"])
    if "set_baseline" in overrides:
        settings.set_baseline = bool(overrides["set_baseline"])
    if "baseline_correction" in overrides:
        settings.set_baseline = bool(overrides["baseline_correction"])
    return settings


def analyze(
    session: PhotometrySession,
    epoc: str | Epoc,
    *,
    channel_keys: list[str] | None = None,
    settings_factory: SettingsFactory | None = None,
    settings_overrides: dict[str, Any] | None = None,
    source: ClassifiedTrialSource | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> list[AnalysisResult]:
    """Run the shared MATLAB-faithful pipeline for one epoc across channels.

    ``epoc`` may be a raw epoc name, classified source key/label, or an Epoc
    object (including synthetic classified-trial epocs built by the GUI).
    """
    resolved_source = source
    if isinstance(epoc, Epoc):
        epoc_obj = epoc
    else:
        epoc_obj, resolved_source = resolve_epoc(session, epoc)

    channel_map = available_channels(session)
    keys = channel_keys if channel_keys is not None else list(channel_map.keys())

    def factory(channel_key: str) -> ProcessingSettings:
        if settings_factory is not None:
            return settings_factory(channel_key)
        return settings_for_channel(channel_key, overrides=settings_overrides)

    results: list[AnalysisResult] = []
    for channel_key in keys:
        if cancel_requested is not None and cancel_requested():
            break
        if channel_key not in channel_map:
            continue
        iso_stream, signal_stream, _ = channel_map[channel_key]
        settings = factory(channel_key)
        processed = process_channel(
            session, iso_stream, signal_stream, epoc_obj, settings
        )
        annotate_trials(processed, epoc_obj, resolved_source)
        results.append(
            AnalysisResult(
                session=session,
                epoc=epoc_obj,
                channel_key=channel_key,
                processed=processed,
                settings=settings,
                stream_store=(iso_stream or "", signal_stream),
            )
        )
    return results


def annotate_trials(
    processed: ProcessedSignal,
    epoc: Epoc,
    source: ClassifiedTrialSource | None = None,
) -> None:
    if source is not None:
        trials_by_number = {trial.trial_number: trial for trial in source.trials}
        processed.trial_labels = [
            trials_by_number[number].trial_type if number in trials_by_number else ""
            for number in processed.trial_numbers
        ]
        processed.trial_times = [
            trials_by_number[number].onset
            if number in trials_by_number
            else float("nan")
            for number in processed.trial_numbers
        ]
        return

    processed.trial_labels = []
    processed.trial_times = [
        float(epoc.onset[number - 1]) if 0 < number <= epoc.onset.size else float("nan")
        for number in processed.trial_numbers
    ]


def filter_trials(
    processed: ProcessedSignal,
    *,
    trial_numbers: Iterable[int] | None = None,
    trial_types: Iterable[str] | None = None,
) -> ProcessedSignal:
    numbers = [int(n) for n in (trial_numbers or [])]
    types = set(trial_types or [])
    if not numbers and not types:
        return processed

    available_numbers = (
        processed.trial_numbers
        if processed.trial_numbers
        else list(range(1, processed.zall.shape[0] + 1))
    )
    available_labels = (
        processed.trial_labels
        if len(processed.trial_labels) == len(available_numbers)
        else [""] * len(available_numbers)
    )
    selected = set(numbers) if numbers else set(available_numbers)
    if types:
        selected = {
            number
            for number, label in zip(available_numbers, available_labels)
            if number in selected and label in types
        }
    return subset_processed_signal(processed, sorted(selected))


def export_result(
    result: AnalysisResult,
    output_dir: str | Path,
    *,
    export_csv: bool = True,
    export_figure: bool = False,
    figure_format: str = "png",
    filename_suffix: str = "",
) -> dict[str, str]:
    output = Path(output_dir)
    paths: dict[str, str] = {"csv": "", "figure": "", "manifest": ""}
    if export_csv:
        csv_path = export_channel(
            output_dir=output,
            session_name=result.session.source_path.stem,
            epoc_name=result.epoc.name,
            channel_key=result.channel_key,
            processed=result.processed,
            settings=result.settings,
            dropped_trials=result.processed.dropped_edge_trials,
            stream_store=result.stream_store,
            metadata={
                "source_path": str(result.session.source_path),
                **result.session.info,
            },
            export_smoothed=result.settings.plot_smooth,
            filename_suffix=filename_suffix,
        )
        paths["csv"] = str(csv_path)
    if export_figure:
        figure_path = save_result_figure(
            output,
            result,
            filename_suffix=filename_suffix,
            figure_format=figure_format,
        )
        paths["figure"] = str(figure_path)
    if export_csv or export_figure:
        manifest = write_result_manifest(
            result,
            output,
            paths,
            filename_suffix=filename_suffix,
        )
        paths["manifest"] = str(manifest)
    return paths


def write_result_manifest(
    result: AnalysisResult,
    output_dir: str | Path,
    paths: dict[str, str],
    *,
    filename_suffix: str = "",
) -> Path:
    output = Path(output_dir)
    manifest = analysis_manifest_path(
        output,
        result.session.source_path.stem,
        result.epoc.name,
        result.channel_key,
        filename_suffix,
    )
    manifest_outputs = {
        key: value for key, value in paths.items() if value
    }
    manifest_outputs["manifest"] = str(manifest)
    return write_analysis_manifest(
        manifest,
        _strict_json_safe(
            {
                "application": {
                    "name": AURORA_APP_NAME,
                    "version": __version__,
                },
                "source": {
                    "path": str(result.session.source_path),
                    "name": result.session.source_path.name,
                    "metadata": result.session.info,
                },
                "analysis": {
                    "epoc": result.epoc.name,
                    "channel": result.channel_key,
                    "iso_stream": result.stream_store[0] or None,
                    "signal_stream": result.stream_store[1],
                    "settings": analysis_settings_payload(result.settings),
                    "exported_trace": (
                        "smoothed" if result.settings.plot_smooth else "raw"
                    ),
                },
                "trials": {
                    "kept": int(result.processed.zall.shape[0]),
                    "numbers": list(result.processed.trial_numbers),
                    "labels": list(result.processed.trial_labels),
                    "onsets_seconds": list(result.processed.trial_times),
                    "baseline_standard_deviations": list(
                        result.processed.baseline_standard_deviations
                    ),
                    "dropped_incomplete": list(
                        result.processed.dropped_edge_trials
                    ),
                    "artifact_removals": int(result.processed.num_artifacts),
                },
                "quality": quality_summary(result),
                "outputs": manifest_outputs,
            }
        ),
    )


def analysis_settings_payload(settings: ProcessingSettings) -> dict[str, Any]:
    def finite_or_none(value: float) -> float | None:
        return float(value) if math.isfinite(float(value)) else None

    return {
        "trange_start": float(settings.trange[0]),
        "trange_end": float(settings.trange[1]),
        "baseline_start": float(settings.baseline_per[0]),
        "baseline_end": float(settings.baseline_per[1]),
        "baseline_adjust": float(settings.base_adjust),
        "downsample_factor": int(settings.downsample_factor),
        "smooth_factor": int(settings.smooth_factor),
        "artifact_405": finite_or_none(settings.artifact_405),
        "artifact_465": finite_or_none(settings.artifact_465),
        "plot_smoothed": bool(settings.plot_smooth),
        "baseline_correction": bool(settings.set_baseline),
        "use_isosbestic": bool(settings.use_isosbestic),
        "polynomial_degree": int(settings.polynomial_degree),
    }


def quality_summary(result: AnalysisResult) -> dict[str, Any]:
    processed = result.processed
    # Inspect unsmoothed values so smoothing cannot hide a large excursion.
    data = processed.zall
    kept = int(data.shape[0])
    removed_edges = int(processed.num_edge_trials)
    removed_artifacts = int(processed.num_artifacts)
    attempted = kept + removed_edges + removed_artifacts
    finite_mask = np.isfinite(data)
    nonfinite_values = int(data.size - int(finite_mask.sum()))
    finite_values = data[finite_mask]
    max_abs_z = (
        float(np.max(np.abs(finite_values))) if finite_values.size else None
    )
    warnings: list[dict[str, str]] = []
    baseline_sd = np.asarray(
        processed.baseline_standard_deviations,
        dtype=float,
    )
    invalid_baseline_trials = int(
        np.count_nonzero(
            ~np.isfinite(baseline_sd) | (baseline_sd <= np.finfo(float).eps)
        )
    )

    if removed_edges:
        fraction = removed_edges / attempted if attempted else 0.0
        warnings.append(
            {
                "code": "incomplete_edge_trials",
                "severity": "warning" if fraction >= 0.10 else "notice",
                "message": (
                    f"{removed_edges} incomplete edge trial(s) were dropped "
                    f"({fraction:.1%} of attempted trials)."
                ),
            }
        )
    if removed_artifacts:
        fraction = removed_artifacts / attempted if attempted else 0.0
        warnings.append(
            {
                "code": "artifact_removals",
                "severity": "warning" if fraction >= 0.10 else "notice",
                "message": (
                    f"{removed_artifacts} artifact trial(s) were removed "
                    f"({fraction:.1%} of attempted trials)."
                ),
            }
        )
    if not result.settings.use_isosbestic:
        missing_control = not bool(result.stream_store[0])
        warnings.append(
            {
                "code": "signal_only",
                "severity": "warning" if missing_control else "notice",
                "message": (
                    "No paired 405 control was available; signal-only analysis was used."
                    if missing_control
                    else "Signal-only analysis was selected; no 405 control fit was applied."
                ),
            }
        )
    if invalid_baseline_trials:
        warnings.append(
            {
                "code": "low_baseline_variance",
                "severity": "warning",
                "message": (
                    f"{invalid_baseline_trials} trial(s) have zero or undefined "
                    "baseline variance; their z-scores may be unstable."
                ),
            }
        )
    if nonfinite_values:
        warnings.append(
            {
                "code": "nonfinite_zscores",
                "severity": "warning",
                "message": (
                    f"The result contains {nonfinite_values} non-finite z-score value(s); "
                    "check baseline variance and input signal quality."
                ),
            }
        )
    if max_abs_z is not None and max_abs_z > 20:
        warnings.append(
            {
                "code": "extreme_zscores",
                "severity": "warning",
                "message": (
                    f"Extreme z-scores were detected (maximum absolute z = {max_abs_z:.2f}); "
                    "inspect baseline variance, artifacts, and edge trials."
                ),
            }
        )

    return {
        "attempted_trials": attempted,
        "kept_trials": kept,
        "dropped_incomplete_trials": removed_edges,
        "artifact_removals": removed_artifacts,
        "nonfinite_values": nonfinite_values,
        "invalid_baseline_trials": invalid_baseline_trials,
        "maximum_absolute_z": max_abs_z,
        "evaluated_trace": "raw_zscore",
        "warnings": warnings,
    }


def session_summary(session: PhotometrySession) -> dict[str, Any]:
    sources = classified_trial_sources(session)
    channels = list_channels(session)
    return {
        "source_path": str(session.source_path),
        "session_name": session.source_path.stem,
        "info": _json_safe(session.info),
        "streams": {
            name: {
                "fs": float(stream.fs),
                "samples": int(stream.data.size),
                "t0": float(stream.t0),
            }
            for name, stream in sorted(session.streams.items())
        },
        "epocs": {
            name: {
                "events": int(epoc.onset.size),
                "first_onset": (
                    float(epoc.onset[0]) if epoc.onset.size else None
                ),
                "last_onset": (
                    float(epoc.onset[-1]) if epoc.onset.size else None
                ),
            }
            for name, epoc in sorted(session.epocs.items())
        },
        "channels": [channel.key for channel in channels],
        "channel_details": [
            {
                "key": channel.key,
                "iso_stream": channel.iso_stream,
                "signal_stream": channel.signal_stream,
                "default_smooth": channel.default_smooth,
            }
            for channel in channels
        ],
        "classified_sources": [
            {
                "key": source.key,
                "label": source.label,
                "events": len(source.trials),
                "trial_type_counts": {
                    label: sum(
                        1 for trial in source.trials if trial.trial_type == label
                    )
                    for label in sorted(
                        {trial.trial_type for trial in source.trials}
                    )
                },
                "warnings": list(source.warnings),
            }
            for source in sources
        ],
    }


def result_plot_payload(
    result: AnalysisResult,
    *,
    include_matrix: bool = True,
) -> dict[str, Any]:
    """JSON-friendly plot payload for Aurora / web clients."""
    processed = result.processed
    use_smooth = result.settings.plot_smooth
    z = processed.zall_smooth if use_smooth else processed.zall
    mean = processed.mean_z_smooth if use_smooth else processed.mean_z
    sem = processed.sem_z_smooth if use_smooth else processed.sem_z
    payload = {
        "session_name": result.session.source_path.stem,
        "source_path": str(result.session.source_path),
        "epoc": result.epoc.name,
        "channel": result.channel_key,
        "iso_stream": result.stream_store[0],
        "signal_stream": result.stream_store[1],
        "num_trials": int(z.shape[0]),
        "num_artifacts": int(processed.num_artifacts),
        "num_edge_trials": int(processed.num_edge_trials),
        "dropped_edge_trials": list(processed.dropped_edge_trials),
        "trial_numbers": list(processed.trial_numbers),
        "trial_labels": list(processed.trial_labels),
        "trial_times": _json_safe(processed.trial_times),
        "settings": {
            "trange": list(result.settings.trange),
            "baseline_per": list(result.settings.baseline_per),
            "base_adjust": float(result.settings.base_adjust),
            "downsample_factor": int(result.settings.downsample_factor),
            "smooth_factor": int(result.settings.smooth_factor),
            "plot_smooth": bool(result.settings.plot_smooth),
            "set_baseline": bool(result.settings.set_baseline),
            "use_isosbestic": bool(result.settings.use_isosbestic),
            "polynomial_degree": int(result.settings.polynomial_degree),
        },
        "quality": quality_summary(result),
        "times": _json_safe(processed.ts),
        "mean": _json_safe(mean),
        "sem": _json_safe(sem),
        "matrix_shape": [int(z.shape[0]), int(z.shape[1])],
        "matrix_dtype": "float32",
    }
    if include_matrix:
        payload["z"] = _json_safe(z)
    return payload


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.ndarray):
        return _json_safe(value.tolist())
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        converted = float(value)
        return converted if math.isfinite(converted) else None
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _strict_json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    safe = _json_safe(value)
    if isinstance(safe, dict):
        return {str(key): _strict_json_safe(item) for key, item in safe.items()}
    if isinstance(safe, list | tuple):
        return [_strict_json_safe(item) for item in safe]
    if isinstance(safe, float) and not math.isfinite(safe):
        return None
    return safe
