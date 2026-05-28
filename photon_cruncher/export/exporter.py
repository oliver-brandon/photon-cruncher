from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from photon_cruncher.processing.pipeline import ProcessedSignal, ProcessingSettings


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
    filename_suffix: str = "",
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"{session_name}_{epoc_name}_{channel_key}{filename_suffix}"

    z_data = processed.zall_smooth if export_smoothed else processed.zall
    heatmap_path = output_dir / f"{prefix}_heatmap.csv"

    if z_data.shape[0] > 0:
        mean_trace = z_data.mean(axis=0)
    else:
        mean_trace = np.full_like(processed.ts, np.nan, dtype=float)

    rows: list[list[object]] = []
    rows.append(["TIME", *processed.ts.tolist()])
    rows.append(["MEAN", *mean_trace.tolist()])
    trial_numbers = (
        processed.trial_numbers
        if len(processed.trial_numbers) == z_data.shape[0]
        else list(range(1, z_data.shape[0] + 1))
    )
    trial_labels = (
        processed.trial_labels
        if len(processed.trial_labels) == z_data.shape[0]
        else [""] * z_data.shape[0]
    )
    for trial_number, trial_label, trial in zip(trial_numbers, trial_labels, z_data):
        row_label = f"TRIAL_{trial_number:03d}"
        if trial_label:
            row_label += f"_{_label_slug(trial_label)}"
        rows.append([row_label, *trial.tolist()])

    pd.DataFrame(rows).to_csv(heatmap_path, index=False, header=False)


def export_batch_summary(output_dir: Path, rows: list[dict[str, Any]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "batch_summary.csv"
    pd.DataFrame(rows).to_csv(summary_path, index=False)


def _label_slug(label: str) -> str:
    return "_".join(label.strip().lower().split())
