#!/usr/bin/env python3
from __future__ import annotations

import argparse
import tempfile
import time
from pathlib import Path

from photon_cruncher.export.exporter import export_channel, save_result_figure
from photon_cruncher.io.loader import load_session
from photon_cruncher.processing.pipeline import (
    available_channels,
    default_settings_for_channel,
    process_channel,
)


def _pick_epoc(session, preferred: str | None):
    if preferred and preferred in session.epocs:
        return preferred, session.epocs[preferred]
    for name, epoc in session.epocs.items():
        if epoc.onset.size >= 5:
            return name, epoc
    name = next(iter(session.epocs))
    return name, session.epocs[name]


def bench_path(path: Path, *, export_figure: bool, epoc_name: str | None) -> None:
    print(f"\n== {path}")
    t0 = time.perf_counter()
    session = load_session(path)
    t_load = time.perf_counter() - t0
    print(f"load_session                 {t_load:8.3f}s")

    channels = available_channels(session)
    if not channels:
        print("no channels available")
        return

    chosen_epoc_name, epoc = _pick_epoc(session, epoc_name)
    print(
        f"epoc={chosen_epoc_name!r} events={epoc.onset.size} channels={list(channels)}"
    )

    results = []
    t0 = time.perf_counter()
    for channel_key, (iso, signal, smooth) in channels.items():
        settings = default_settings_for_channel(channel_key)
        settings.smooth_factor = smooth
        try:
            processed = process_channel(session, iso, signal, epoc, settings)
        except ValueError as exc:
            print(f"  {channel_key}: skipped ({exc})")
            continue
        results.append((channel_key, iso, signal, settings, processed))
    t_process = time.perf_counter() - t0
    print(f"process all channels         {t_process:8.3f}s  n={len(results)}")

    if not results:
        return

    channel_key, iso, signal, settings, processed = results[0]
    print(f"first channel matrix         {processed.zall.shape}")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        t0 = time.perf_counter()
        export_channel(
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
        t_csv = time.perf_counter() - t0
        print(f"export_channel CSV           {t_csv:8.3f}s")

        if export_figure:
            result = type(
                "BenchResult",
                (),
                {
                    "session": session,
                    "epoc": epoc,
                    "channel_key": channel_key,
                    "processed": processed,
                    "settings": settings,
                },
            )()
            t0 = time.perf_counter()
            save_result_figure(out, result)
            t_fig = time.perf_counter() - t0
            print(f"save_result_figure           {t_fig:8.3f}s")


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark Photon Cruncher backend hot paths.")
    parser.add_argument("inputs", nargs="+", help="MAT files or TDT block folders")
    parser.add_argument("--epoc", default=None, help="Preferred epoc name")
    parser.add_argument("--figure", action="store_true", help="Also time figure export")
    args = parser.parse_args()

    for raw in args.inputs:
        path = Path(raw).expanduser().resolve()
        if not path.exists():
            print(f"missing: {path}")
            continue
        bench_path(path, export_figure=args.figure, epoc_name=args.epoc)


if __name__ == "__main__":
    main()
