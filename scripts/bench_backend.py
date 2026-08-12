#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import platform
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from photon_cruncher import __version__
from photon_cruncher.export.exporter import export_channel, save_result_figure
from photon_cruncher.io.loader import load_session
from photon_cruncher.processing.pipeline import (
    available_channels,
    default_settings_for_channel,
    process_channel,
)
from photon_cruncher.service import AnalysisResult, result_plot_payload


def _pick_epoc(session, preferred: str | None):
    if preferred and preferred in session.epocs:
        return preferred, session.epocs[preferred]
    for name, epoc in session.epocs.items():
        if epoc.onset.size >= 5:
            return name, epoc
    name = next(iter(session.epocs))
    return name, session.epocs[name]


def _median_call(call: Callable[[], Any], repeats: int) -> tuple[float, Any]:
    timings: list[float] = []
    result: Any = None
    for _ in range(repeats):
        started = time.perf_counter()
        result = call()
        timings.append(time.perf_counter() - started)
    return statistics.median(timings), result


def bench_path(
    path: Path,
    *,
    export_figure: bool,
    epoc_name: str | None,
    repeats: int,
    measure_transport: bool,
) -> None:
    print(f"\n== {path}")
    t_load, session = _median_call(lambda: load_session(path), repeats)
    print(f"load_session                 {t_load:8.3f}s  median n={repeats}")

    channels = available_channels(session)
    if not channels:
        print("no channels available")
        return

    chosen_epoc_name, epoc = _pick_epoc(session, epoc_name)
    print(
        f"epoc={chosen_epoc_name!r} events={epoc.onset.size} channels={list(channels)}"
    )

    def process_all_channels():
        results = []
        for channel_key, (iso, signal, smooth) in channels.items():
            settings = default_settings_for_channel(channel_key)
            settings.smooth_factor = smooth
            try:
                processed = process_channel(session, iso, signal, epoc, settings)
            except ValueError as exc:
                print(f"  {channel_key}: skipped ({exc})")
                continue
            results.append((channel_key, iso, signal, settings, processed))
        return results

    t_process, results = _median_call(process_all_channels, repeats)
    print(
        f"process all channels         {t_process:8.3f}s  "
        f"median n={repeats} channels={len(results)}"
    )

    if not results:
        return

    analysis_results = [
        AnalysisResult(
            session=session,
            epoc=epoc,
            channel_key=channel_key,
            processed=processed,
            settings=settings,
            stream_store=(iso or "", signal),
        )
        for channel_key, iso, signal, settings, processed in results
    ]

    if measure_transport:
        def serialize_legacy() -> bytes:
            return json.dumps(
                {
                    "results": [
                        result_plot_payload(result)
                        for result in analysis_results
                    ]
                },
                separators=(",", ":"),
            ).encode("utf-8")

        def serialize_compact() -> bytes:
            return json.dumps(
                {
                    "results": [
                        result_plot_payload(result, include_matrix=False)
                        for result in analysis_results
                    ]
                },
                separators=(",", ":"),
            ).encode("utf-8")

        first_result = analysis_results[0]
        first_matrix = (
            first_result.processed.zall_smooth
            if first_result.settings.plot_smooth
            else first_result.processed.zall
        )

        def pack_displayed_matrix() -> bytes:
            return first_matrix.astype("<f4", copy=False).tobytes(order="C")

        t_legacy, legacy = _median_call(serialize_legacy, repeats)
        t_compact, compact = _median_call(serialize_compact, repeats)
        t_matrix, matrix = _median_call(pack_displayed_matrix, repeats)
        print(
            f"legacy all-channel JSON       {t_legacy:8.3f}s  "
            f"{len(legacy) / (1024 * 1024):8.3f} MiB"
        )
        print(
            f"compact summary JSON          {t_compact:8.3f}s  "
            f"{len(compact) / (1024 * 1024):8.3f} MiB"
        )
        print(
            f"displayed float32 matrix      {t_matrix:8.3f}s  "
            f"{len(matrix) / (1024 * 1024):8.3f} MiB"
        )

    channel_key, iso, signal, settings, processed = results[0]
    print(f"first channel matrix         {processed.zall.shape}")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)

        def export_csv():
            return export_channel(
                output_dir=out,
                session_name=path.stem,
                epoc_name=chosen_epoc_name,
                channel_key=channel_key,
                processed=processed,
                settings=settings,
                dropped_trials=[],
                stream_store=(iso, signal),
                metadata={},
            )

        t_csv, _ = _median_call(export_csv, repeats)
        print(f"export_channel CSV           {t_csv:8.3f}s  median n={repeats}")

        if export_figure:
            result = AnalysisResult(
                session=session,
                epoc=epoc,
                channel_key=channel_key,
                processed=processed,
                settings=settings,
                stream_store=(iso, signal),
            )
            # Exclude Matplotlib/font initialization from steady-state export timing.
            save_result_figure(out, result)
            t_fig, _ = _median_call(lambda: save_result_figure(out, result), repeats)
            print(f"save_result_figure           {t_fig:8.3f}s  median n={repeats}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark Photon Cruncher backend hot paths.")
    parser.add_argument("inputs", nargs="+", help="MAT files or TDT block folders")
    parser.add_argument("--epoc", default=None, help="Preferred epoc name")
    parser.add_argument("--figure", action="store_true", help="Also time figure export")
    parser.add_argument(
        "--transport",
        action="store_true",
        help="Measure legacy JSON versus Aurora compact plot transport.",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=3,
        help="Number of timed repetitions per stage (default: 3).",
    )
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be at least 1")

    print(
        f"Photon Cruncher {__version__} | Python {platform.python_version()} | "
        f"{platform.system()} {platform.release()} {platform.machine()}"
    )

    for raw in args.inputs:
        path = Path(raw).expanduser().resolve()
        if not path.exists():
            print(f"missing: {path}")
            continue
        bench_path(
            path,
            export_figure=args.figure,
            epoc_name=args.epoc,
            repeats=args.repeat,
            measure_transport=args.transport,
        )


if __name__ == "__main__":
    main()
