from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from photon_cruncher.export.exporter import export_batch_summary, export_channel
from photon_cruncher.io.loader import load_session
from photon_cruncher.model import Epoc, PhotometrySession
from photon_cruncher.processing.pipeline import (
    ProcessedSignal,
    ProcessingSettings,
    available_channels,
    default_settings_for_channel,
    process_channel,
)


@dataclass
class AnalysisResult:
    session: PhotometrySession
    epoc: Epoc
    channel_key: str
    processed: ProcessedSignal
    settings: ProcessingSettings
    stream_store: tuple[str, str]


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
    for path in input_paths:
        session = load_session(path)
        results = run_session(session, epoc_name)
        for result in results:
            export_channel(
                output_dir=output_dir,
                session_name=session.source_path.stem,
                epoc_name=epoc_name,
                channel_key=result.channel_key,
                processed=result.processed,
                settings=result.settings,
                dropped_trials=[],
                stream_store=result.stream_store,
                metadata={
                    "source_path": str(session.source_path),
                    **session.info,
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
    epoc_names: list[str],
    output_dir: Path,
    channel_keys: list[str] | None,
    settings_factory: Callable[[str], ProcessingSettings],
    export_summary: bool = False,
    per_session_subdir: bool = False,
) -> None:
    summary_rows: list[dict[str, Any]] = []
    for path in input_paths:
        session = load_session(path)
        session_output = output_dir / session.source_path.stem if per_session_subdir else output_dir
        for epoc_name in epoc_names:
            if epoc_name not in session.epocs:
                continue
            if session.epocs[epoc_name].onset.size == 0:
                continue
            try:
                results = run_session_with_settings(
                    session=session,
                    epoc_name=epoc_name,
                    channel_keys=channel_keys,
                    settings_factory=settings_factory,
                )
            except ValueError:
                continue
            for result in results:
                export_channel(
                    output_dir=session_output,
                    session_name=session.source_path.stem,
                    epoc_name=epoc_name,
                    channel_key=result.channel_key,
                    processed=result.processed,
                    settings=result.settings,
                    dropped_trials=[],
                    stream_store=result.stream_store,
                    metadata={
                        "source_path": str(session.source_path),
                        **session.info,
                    },
                    export_smoothed=result.settings.plot_smooth,
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
