from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from photometry_app.processing.pipeline import ProcessedSignal, ProcessingSettings


def export_channel(
    output_dir: Path,
    session_name: str,
    epoc_name: str,
    channel_key: str,
    processed: ProcessedSignal,
    settings: ProcessingSettings,
    dropped_trials: list[int],
    stream_store: tuple[str, str],
    metadata: dict[str, Any],
    export_smoothed: bool = True,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"{session_name}_{epoc_name}_{channel_key}"

    z_data = processed.zall_smooth if export_smoothed else processed.zall
    mean_data = processed.mean_z_smooth if export_smoothed else processed.mean_z
    sem_data = processed.sem_z_smooth if export_smoothed else processed.sem_z

    heatmap_path = output_dir / f"{prefix}_heatmap.csv"
    time_path = output_dir / f"{prefix}_time.csv"
    mean_path = output_dir / f"{prefix}_mean.csv"
    sem_path = output_dir / f"{prefix}_sem.csv"

    pd.DataFrame(z_data).to_csv(heatmap_path, index=False, header=False)
    pd.DataFrame({"time": processed.ts}).to_csv(time_path, index=False)
    pd.DataFrame({"mean": mean_data}).to_csv(mean_path, index=False)
    pd.DataFrame({"sem": sem_data}).to_csv(sem_path, index=False)

    settings_payload = {
        "trange": settings.trange,
        "baseline_per": settings.baseline_per,
        "downsample_factor": settings.downsample_factor,
        "smoothing_window": settings.smooth_factor,
        "base_adjust": settings.base_adjust,
        "plot_smooth": settings.plot_smooth,
        "set_baseline": settings.set_baseline,
        "artifact_405": settings.artifact_405,
        "artifact_465": settings.artifact_465,
        "dropped_trials": dropped_trials,
        "stream_store": {
            "iso": stream_store[0],
            "signal": stream_store[1],
        },
        "input_metadata": metadata,
    }
    settings_path = output_dir / f"{prefix}_settings.json"
    settings_path.write_text(json.dumps(settings_payload, indent=2))


def export_batch_summary(output_dir: Path, rows: list[dict[str, Any]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "batch_summary.csv"
    pd.DataFrame(rows).to_csv(summary_path, index=False)
