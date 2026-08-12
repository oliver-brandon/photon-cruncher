from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from photon_cruncher.export.exporter import (
    export_batch_summary,
    export_channel,
    save_result_figure,
)
from photon_cruncher.io.loader import load_session
from photon_cruncher.model import PhotometrySession
from photon_cruncher.processing.pipeline import ProcessingSettings
from photon_cruncher.service import (
    AnalysisResult,
    analyze as service_analyze,
    write_result_manifest,
)

# Re-export for existing imports (gui, cli, tests).
__all__ = [
    "AnalysisResult",
    "BatchEpocSelection",
    "BatchExportedResult",
    "BatchOutcome",
    "epoc_names_for_selection",
    "run_batch",
    "run_batch_custom",
    "run_session",
    "run_session_with_settings",
]


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
class BatchExportedResult:
    output_dir: Path
    result: AnalysisResult
    csv_path: Path | None = None
    figure_path: Path | None = None
    manifest_path: Path | None = None


@dataclass(frozen=True)
class BatchOutcome:
    """A non-export outcome recorded while processing one batch source.

    ``run_batch_custom`` retains its list-of-exports return value for existing
    callers.  A caller that needs user-facing diagnostics can pass a mutable
    ``outcomes`` list and receive these records without loading the source a
    second time.
    """

    status: str
    input_path: Path
    session: str
    epoc: str
    channels: tuple[str, ...]
    reason: str


def _record_batch_outcome(
    outcomes: list[BatchOutcome] | None,
    *,
    status: str,
    path: Path,
    session: str,
    epoc: str,
    channel_keys: list[str] | None,
    reason: str,
) -> None:
    if outcomes is None:
        return
    outcomes.append(
        BatchOutcome(
            status=status,
            input_path=path,
            session=session,
            epoc=epoc,
            channels=tuple(channel_keys or ()),
            reason=reason,
        )
    )


def run_session(
    session: PhotometrySession,
    epoc_name: str,
    channel_keys: list[str] | None = None,
) -> list[AnalysisResult]:
    return service_analyze(
        session,
        epoc_name,
        channel_keys=channel_keys,
        settings_factory=None,
    )


def run_session_with_settings(
    session: PhotometrySession,
    epoc_name: str,
    channel_keys: list[str] | None,
    settings_factory: Callable[[str], ProcessingSettings],
) -> list[AnalysisResult]:
    return service_analyze(
        session,
        epoc_name,
        channel_keys=channel_keys,
        settings_factory=settings_factory,
    )


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
            csv_path = export_channel(
                output_dir=output_dir,
                session_name=session.source_path.stem,
                epoc_name=epoc_name,
                channel_key=result.channel_key,
                processed=result.processed,
                settings=result.settings,
                dropped_trials=result.processed.dropped_edge_trials,
                stream_store=result.stream_store,
                metadata={
                    "source_path": str(session.source_path),
                    **session.info,
                },
                export_smoothed=result.settings.plot_smooth,
            )
            write_result_manifest(result, output_dir, {"csv": str(csv_path)})
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
    outcomes: list[BatchOutcome] | None = None,
    export_figure: bool = False,
    figure_format: str = "png",
    cancel_requested: Callable[[], bool] | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
    session_loader: Callable[[Path], PhotometrySession] | None = None,
) -> list[BatchExportedResult]:
    summary_rows: list[dict[str, Any]] = []
    exported_results: list[BatchExportedResult] = []
    total_steps = max(1, len(input_paths) * len(epoc_selections))
    completed_steps = 0
    load = session_loader or load_session

    def cancelled() -> bool:
        return bool(cancel_requested and cancel_requested())

    def report(detail: str) -> None:
        if progress_callback is not None:
            progress_callback(completed_steps, total_steps, detail)

    report("Preparing batch export")
    for path in input_paths:
        if cancelled():
            break
        source_path = Path(path)
        session_name = source_path.stem
        report(f"Loading {session_name}")
        try:
            session = load(source_path)
        except Exception as exc:  # noqa: BLE001 - retain other batch exports
            _record_batch_outcome(
                outcomes,
                status="error",
                path=source_path,
                session=session_name,
                epoc="",
                channel_keys=channel_keys,
                reason=f"Could not load source: {exc}",
            )
            completed_steps += len(epoc_selections)
            report(f"Could not load {session_name}")
            continue
        session_name = session.source_path.stem
        session_output = (
            output_dir / session.source_path.stem if per_session_subdir else output_dir
        )
        for selection in epoc_selections:
            if cancelled():
                break
            report(f"Analyzing {session_name} · {selection[0]}")
            epoc_names = epoc_names_for_selection(session, selection)
            if not epoc_names:
                _record_batch_outcome(
                    outcomes,
                    status="skipped",
                    path=source_path,
                    session=session_name,
                    epoc=selection[0],
                    channel_keys=channel_keys,
                    reason="No matching epoc was found in this source.",
                )
                completed_steps += 1
                report(f"Skipped {session_name} · {selection[0]}")
                continue
            for epoc_name in epoc_names:
                if cancelled():
                    break
                if session.epocs[epoc_name].onset.size == 0:
                    _record_batch_outcome(
                        outcomes,
                        status="skipped",
                        path=source_path,
                        session=session_name,
                        epoc=epoc_name,
                        channel_keys=channel_keys,
                        reason="The epoc has no events.",
                    )
                    continue
                try:
                    results = service_analyze(
                        session,
                        epoc_name,
                        channel_keys=channel_keys,
                        settings_factory=settings_factory,
                        cancel_requested=cancel_requested,
                    )
                except Exception as exc:  # noqa: BLE001 - retain other batch exports
                    _record_batch_outcome(
                        outcomes,
                        status="error",
                        path=source_path,
                        session=session_name,
                        epoc=epoc_name,
                        channel_keys=channel_keys,
                        reason=f"Analysis failed: {exc}",
                    )
                    continue
                if cancelled():
                    break
                if channel_keys is not None:
                    result_channels = {result.channel_key for result in results}
                    missing_channels = [
                        channel_key
                        for channel_key in channel_keys
                        if channel_key not in result_channels
                    ]
                    if missing_channels:
                        _record_batch_outcome(
                            outcomes,
                            status="skipped",
                            path=source_path,
                            session=session_name,
                            epoc=epoc_name,
                            channel_keys=missing_channels,
                            reason="Requested channel(s) are not available.",
                        )
                if not results and channel_keys is None:
                    _record_batch_outcome(
                        outcomes,
                        status="skipped",
                        path=source_path,
                        session=session_name,
                        epoc=epoc_name,
                        channel_keys=channel_keys,
                        reason="No compatible channels are available.",
                    )
                    continue
                for result in results:
                    if cancelled():
                        break
                    csv_path: Path | None = None
                    figure_path: Path | None = None
                    manifest_path: Path | None = None
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
                                    "source_path": str(session.source_path),
                                    **session.info,
                                },
                                export_smoothed=result.settings.plot_smooth,
                            )
                        except Exception as exc:  # noqa: BLE001 - retain batch work
                            _record_batch_outcome(
                                outcomes,
                                status="error",
                                path=source_path,
                                session=session_name,
                                epoc=epoc_name,
                                channel_keys=[result.channel_key],
                                reason=f"CSV export failed: {exc}",
                            )
                    if export_figure:
                        try:
                            figure_path = save_result_figure(
                                session_output,
                                result,
                                figure_format=figure_format,
                            )
                        except Exception as exc:  # noqa: BLE001 - retain batch work
                            _record_batch_outcome(
                                outcomes,
                                status="error",
                                path=source_path,
                                session=session_name,
                                epoc=epoc_name,
                                channel_keys=[result.channel_key],
                                reason=f"Figure export failed: {exc}",
                            )
                    if csv_path or figure_path:
                        try:
                            manifest_path = write_result_manifest(
                                result,
                                session_output,
                                {
                                    "csv": str(csv_path or ""),
                                    "figure": str(figure_path or ""),
                                },
                            )
                        except Exception as exc:  # noqa: BLE001 - retain batch work
                            _record_batch_outcome(
                                outcomes,
                                status="error",
                                path=source_path,
                                session=session_name,
                                epoc=epoc_name,
                                channel_keys=[result.channel_key],
                                reason=f"Analysis manifest export failed: {exc}",
                            )
                    exported_results.append(
                        BatchExportedResult(
                            output_dir=session_output,
                            result=result,
                            csv_path=csv_path,
                            figure_path=figure_path,
                            manifest_path=manifest_path,
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
            completed_steps += 1
            report(f"Finished {session_name} · {selection[0]}")
    if export_summary:
        export_batch_summary(output_dir, summary_rows)
    if cancelled():
        report("Batch export cancelled")
    else:
        completed_steps = total_steps
        report("Batch export complete")
    return exported_results
