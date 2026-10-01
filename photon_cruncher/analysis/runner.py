from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from photon_cruncher.export.exporter import (
    batch_output_directories,
    export_batch_summary,
    export_channel,
)
from photon_cruncher.io.loader import load_session
from photon_cruncher.model import Epoc, PhotometrySession
from photon_cruncher.processing.pipeline import (
    ProcessedSignal,
    ProcessingSettings,
    available_channels,
    default_settings_for_channel,
    process_channel,
)


BatchEpocSelection = tuple[str, tuple[str, ...]] | tuple[str, tuple[str, ...], str]


def _epoc_suffix_side(epoc_name: str) -> str | None:
    if epoc_name.endswith("1_") or epoc_name.endswith("A"):
        return "left"
    if epoc_name.endswith("2_") or epoc_name.endswith("C"):
        return "right"
    return None


def epoc_names_for_selection(
    session: PhotometrySession,
    selection: BatchEpocSelection,
) -> list[str]:
    _, epoc_members, *mode_parts = selection
    mode = mode_parts[0] if mode_parts else "all"
    present_members = [
        epoc_name for epoc_name in epoc_members if epoc_name in session.epocs
    ]
    if mode == "prefer_left":
        preferred = [
            epoc_name
            for epoc_name in present_members
            if _epoc_suffix_side(epoc_name) == "left"
        ]
        return preferred or [
            epoc_name
            for epoc_name in present_members
            if _epoc_suffix_side(epoc_name) == "right"
        ]
    if mode == "prefer_right":
        preferred = [
            epoc_name
            for epoc_name in present_members
            if _epoc_suffix_side(epoc_name) == "right"
        ]
        return preferred or [
            epoc_name
            for epoc_name in present_members
            if _epoc_suffix_side(epoc_name) == "left"
        ]
    return present_members


@dataclass
class AnalysisResult:
    session: PhotometrySession
    epoc: Epoc
    channel_key: str
    processed: ProcessedSignal
    settings: ProcessingSettings
    stream_store: tuple[str, str]


@dataclass
class BatchExportedResult:
    output_dir: Path
    input_path: Path
    epoc: str
    channel: str
    num_trials: int
    csv_path: Path | None = None
    figure_path: Path | None = None


@dataclass(frozen=True)
class BatchOutcome:
    status: str
    input_path: Path
    epoc: str
    reason: str


def run_session(
    session: PhotometrySession,
    epoc_name: str,
    channel_keys: list[str] | None = None,
) -> list[AnalysisResult]:
    if epoc_name not in session.epocs:
        raise ValueError(f"Epoc '{epoc_name}' not found.")
    epoc = session.epocs[epoc_name]
    channel_map = available_channels(session)
    if channel_keys is None:
        channel_keys = list(channel_map.keys())

    results: list[AnalysisResult] = []
    for channel_key in channel_keys:
        if channel_key not in channel_map:
            continue
        iso_stream, signal_stream, smooth_factor = channel_map[channel_key]
        settings = default_settings_for_channel(channel_key)
        settings.smooth_factor = smooth_factor
        processed = process_channel(session, iso_stream, signal_stream, epoc, settings)
        results.append(
            AnalysisResult(
                session=session,
                epoc=epoc,
                channel_key=channel_key,
                processed=processed,
                settings=settings,
                stream_store=(iso_stream, signal_stream),
            )
        )
    return results


def run_session_with_settings(
    session: PhotometrySession,
    epoc_name: str,
    channel_keys: list[str] | None,
    settings_factory: Callable[[str], ProcessingSettings],
) -> list[AnalysisResult]:
    if epoc_name not in session.epocs:
        raise ValueError(f"Epoc '{epoc_name}' not found.")
    epoc = session.epocs[epoc_name]
    channel_map = available_channels(session)
    if channel_keys is None:
        channel_keys = list(channel_map.keys())

    results: list[AnalysisResult] = []
    for channel_key in channel_keys:
        if channel_key not in channel_map:
            continue
        iso_stream, signal_stream, _ = channel_map[channel_key]
        settings = settings_factory(channel_key)
        processed = process_channel(session, iso_stream, signal_stream, epoc, settings)
        results.append(
            AnalysisResult(
                session=session,
                epoc=epoc,
                channel_key=channel_key,
                processed=processed,
                settings=settings,
                stream_store=(iso_stream, signal_stream),
            )
        )
    return results


def run_batch(
    input_paths: list[Path],
    epoc_name: str,
    output_dir: Path,
) -> None:
    summary_rows: list[dict[str, Any]] = []
    destinations = batch_output_directories(input_paths, output_dir, per_session_subdir=False)
    for path in input_paths:
        session = load_session(path)
        results = run_session(session, epoc_name)
        for result in results:
            export_channel(
                output_dir=destinations[Path(path).expanduser().resolve()],
                session_name=session.source_path.stem,
                epoc_name=epoc_name,
                channel_key=result.channel_key,
                processed=result.processed,
                settings=result.settings,
                dropped_trials=[],
                stream_store=result.stream_store,
                metadata={
                    **session.info,
                    "source_path": str(session.source_path),
                },
                export_smoothed=result.settings.plot_smooth,
            )
            summary_rows.append(
                {
                    "session": session.source_path.stem,
                    "epoc": epoc_name,
                    "channel": result.channel_key,
                    "num_trials": result.processed.zall.shape[0],
                    "num_artifacts": result.processed.num_artifacts,
                }
            )
    export_batch_summary(output_dir, summary_rows)


def run_batch_custom(
    input_paths: list[Path],
    epoc_selections: list[BatchEpocSelection],
    output_dir: Path,
    channel_keys: list[str] | None,
    settings_factory: Callable[[str], ProcessingSettings],
    export_summary: bool = False,
    per_session_subdir: bool = False,
    export_csv: bool = True,
    figure_exporter: Callable[[Path, AnalysisResult], Path] | None = None,
    outcomes: list[BatchOutcome] | None = None,
) -> list[BatchExportedResult]:
    summary_rows: list[dict[str, Any]] = []
    exported_results: list[BatchExportedResult] = []
    destinations = batch_output_directories(
        input_paths, output_dir, per_session_subdir=per_session_subdir
    )

    def report(status: str, path: Path, epoc: str, reason: str) -> None:
        if outcomes is not None:
            outcomes.append(BatchOutcome(status, path, epoc, reason))

    for path in input_paths:
        try:
            session = load_session(path)
        except Exception as exc:
            report("error", path, "", f"Could not load recording: {exc}")
            continue
        session_output = destinations[Path(path).expanduser().resolve()]
        for selection in epoc_selections:
            epoc_names = epoc_names_for_selection(session, selection)
            if not epoc_names:
                report("skipped", path, selection[0], "No matching epoc.")
            for epoc_name in epoc_names:
                if session.epocs[epoc_name].onset.size == 0:
                    report("skipped", path, epoc_name, "The epoc has no events.")
                    continue
                try:
                    results = run_session_with_settings(
                        session=session,
                        epoc_name=epoc_name,
                        channel_keys=channel_keys,
                        settings_factory=settings_factory,
                    )
                except Exception as exc:
                    report("error", path, epoc_name, f"Analysis failed: {exc}")
                    continue
                for result in results:
                    csv_path = None
                    figure_path = None
                    if export_csv:
                        try:
                            csv_path = export_channel(
                                output_dir=session_output,
                                session_name=session.source_path.stem,
                                epoc_name=epoc_name,
                                channel_key=result.channel_key,
                                processed=result.processed,
                                settings=result.settings,
                                dropped_trials=result.processed.dropped_edge_trials,
                                stream_store=result.stream_store,
                                metadata={
                                    **session.info,
                                    "source_path": str(session.source_path),
                                },
                                export_smoothed=result.settings.plot_smooth,
                            )
                        except Exception as exc:
                            report("error", path, epoc_name, f"{result.channel_key} CSV export failed: {exc}")
                    if figure_exporter is not None:
                        try:
                            figure_path = figure_exporter(session_output, result)
                        except Exception as exc:
                            report("error", path, epoc_name, f"{result.channel_key} figure export failed: {exc}")
                    exported_results.append(
                        BatchExportedResult(
                            session_output, session.source_path, epoc_name,
                            result.channel_key, int(result.processed.zall.shape[0]),
                            csv_path, figure_path,
                        )
                    )
                    if export_summary:
                        summary_rows.append(
                            {
                                "session": session.source_path.stem,
                                "epoc": epoc_name,
                                "channel": result.channel_key,
                                "num_trials": result.processed.zall.shape[0],
                                "num_artifacts": result.processed.num_artifacts,
                            }
                        )
    if export_summary:
        export_batch_summary(output_dir, summary_rows)
    return exported_results
