"""Shared analysis service used by lab GUI, Aurora, and CLI.

GUI layers must call this module (or thin wrappers around it) instead of
re-implementing load/process/export loops. Backend fixes land here once.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np

from photon_cruncher.analysis.trial_classifier import (
    ClassifiedTrialSource,
    classified_trial_sources,
)
from photon_cruncher.export.exporter import export_channel, save_result_figure
from photon_cruncher.io.loader import load_session
from photon_cruncher.model import Epoc, PhotometrySession
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


def list_channels(session: PhotometrySession) -> list[ChannelInfo]:
    mapping = available_channels(session)
    return [
        ChannelInfo(
            key=key,
            iso_stream=iso,
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
                stream_store=(iso_stream, signal_stream),
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
    paths: dict[str, str] = {"csv": "", "figure": ""}
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
    return paths


def session_summary(session: PhotometrySession) -> dict[str, Any]:
    sources = classified_trial_sources(session)
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
        "channels": [channel.key for channel in list_channels(session)],
        "classified_sources": [
            {
                "key": source.key,
                "label": source.label,
                "events": len(source.trials),
                "warnings": list(source.warnings),
            }
            for source in sources
        ],
    }


def result_plot_payload(result: AnalysisResult) -> dict[str, Any]:
    """JSON-friendly plot payload for Aurora / web clients."""
    processed = result.processed
    use_smooth = result.settings.plot_smooth
    z = processed.zall_smooth if use_smooth else processed.zall
    mean = processed.mean_z_smooth if use_smooth else processed.mean_z
    sem = processed.sem_z_smooth if use_smooth else processed.sem_z
    return {
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
        "settings": {
            "trange": list(result.settings.trange),
            "baseline_per": list(result.settings.baseline_per),
            "base_adjust": float(result.settings.base_adjust),
            "downsample_factor": int(result.settings.downsample_factor),
            "smooth_factor": int(result.settings.smooth_factor),
            "plot_smooth": bool(result.settings.plot_smooth),
            "set_baseline": bool(result.settings.set_baseline),
        },
        "times": _json_safe(processed.ts),
        "mean": _json_safe(mean),
        "sem": _json_safe(sem),
        "z": _json_safe(z),
    }


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
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value
