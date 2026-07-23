from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from photon_cruncher.processing.pipeline import ProcessedSignal, ProcessingSettings

if TYPE_CHECKING:
    from matplotlib.figure import Figure


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
) -> Path:
    _ = (dropped_trials, stream_store, metadata, settings)
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"{session_name}_{epoc_name}_{channel_key}{filename_suffix}"

    z_data = processed.zall_smooth if export_smoothed else processed.zall
    heatmap_path = output_dir / f"{prefix}_heatmap.csv"

    if z_data.shape[0] > 0:
        mean_trace = z_data.mean(axis=0)
    else:
        mean_trace = np.full_like(processed.ts, np.nan, dtype=float)

    labels = _heatmap_row_labels(processed, z_data.shape[0])
    matrix = np.vstack([processed.ts, mean_trace, z_data])
    _write_labeled_numeric_csv(heatmap_path, labels, matrix)
    return heatmap_path


def export_batch_summary(output_dir: Path, rows: list[dict[str, Any]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "batch_summary.csv"
    pd.DataFrame(rows).to_csv(summary_path, index=False)


def heatmap_trial_ticks(
    processed: ProcessedSignal,
    num_rows: int,
    max_ticks: int = 12,
) -> tuple[list[int], list[str]]:
    if num_rows <= 0:
        return [], []
    trial_numbers = (
        processed.trial_numbers
        if len(processed.trial_numbers) == num_rows
        else list(range(1, num_rows + 1))
    )
    if num_rows <= max_ticks:
        tick_positions = list(range(1, num_rows + 1))
    else:
        tick_positions = sorted(
            {
                1 + round(index * (num_rows - 1) / (max_ticks - 1))
                for index in range(max_ticks)
            }
        )
    tick_labels = [str(int(trial_numbers[position - 1])) for position in tick_positions]
    return tick_positions, tick_labels


def result_figure_title(result: Any) -> str:
    file_name = result.session.source_path.name or "Untitled session"
    return f"{file_name} | Epoc: {result.epoc.name}"


def populate_result_figure(figure: "Figure", result: Any) -> None:
    grid = figure.add_gridspec(1, 2, width_ratios=[2, 1])
    ax_line = figure.add_subplot(grid[0, 0])
    ax_heatmap = figure.add_subplot(grid[0, 1])
    processed = result.processed
    ts = processed.ts
    if result.settings.plot_smooth:
        z_data = processed.zall_smooth
        mean = processed.mean_z_smooth
        sem = processed.sem_z_smooth
    else:
        z_data = processed.zall
        mean = processed.mean_z
        sem = processed.sem_z

    heatmap = ax_heatmap.imshow(
        z_data,
        aspect="auto",
        origin="lower",
        extent=[ts[0], ts[-1], 0.5, z_data.shape[0] + 0.5],
        cmap="viridis",
        interpolation="nearest",
    )
    ax_heatmap.set_title(f"{result.channel_key} z-score heatmap")
    ax_heatmap.set_xlabel("Time (s)")
    ax_heatmap.set_ylabel("Trial")
    trial_tick_positions, trial_tick_labels = heatmap_trial_ticks(
        processed, z_data.shape[0]
    )
    ax_heatmap.set_yticks(trial_tick_positions)
    ax_heatmap.set_yticklabels(trial_tick_labels)
    figure.colorbar(heatmap, ax=ax_heatmap, orientation="vertical")

    ax_line.plot(ts, mean, color="#1f77b4", linewidth=2, label="Mean z")
    ax_line.fill_between(
        ts, mean - sem, mean + sem, color="#1f77b4", alpha=0.2, label="SEM"
    )
    ax_line.axvline(0, color="#222222", linestyle="--", linewidth=1)
    ax_line.set_xlabel("Time (s)")
    ax_line.set_ylabel("Z-score")
    ax_line.set_title("Mean \u00b1 SEM")
    ax_line.legend(loc="upper right")

    figure.suptitle(result_figure_title(result), fontsize=12, fontweight="bold")
    figure.tight_layout(rect=(0, 0, 1, 0.94))


def save_result_figure(
    output_dir: Path,
    result: Any,
    filename_suffix: str = "",
    figure_format: str = "png",
) -> Path:
    from matplotlib.figure import Figure

    output_dir.mkdir(parents=True, exist_ok=True)
    figure = Figure(figsize=(10, 4.5))
    try:
        populate_result_figure(figure, result)
        prefix = (
            f"{result.session.source_path.stem}_{result.epoc.name}_"
            f"{result.channel_key}{filename_suffix}"
        )
        figure_path = output_dir / f"{prefix}_summary.{figure_format}"
        figure.savefig(figure_path, dpi=300, format=figure_format)
    finally:
        figure.clear()
        del figure
    return figure_path


def _heatmap_row_labels(processed: ProcessedSignal, num_trials: int) -> list[str]:
    trial_numbers = (
        processed.trial_numbers
        if len(processed.trial_numbers) == num_trials
        else list(range(1, num_trials + 1))
    )
    trial_labels = (
        processed.trial_labels
        if len(processed.trial_labels) == num_trials
        else [""] * num_trials
    )
    labels = ["TIME", "MEAN"]
    for trial_number, trial_label in zip(trial_numbers, trial_labels):
        row_label = f"TRIAL_{trial_number:03d}"
        if trial_label:
            row_label += f"_{_label_slug(trial_label)}"
        labels.append(row_label)
    return labels


def _write_labeled_numeric_csv(
    path: Path,
    labels: list[str],
    matrix: np.ndarray,
) -> None:
    if len(labels) != matrix.shape[0]:
        raise ValueError("CSV label count must match matrix rows.")
    with path.open("w", encoding="utf-8", newline="") as handle:
        for label, row in zip(labels, matrix):
            handle.write(label)
            handle.write(",")
            np.savetxt(
                handle,
                np.asarray(row, dtype=float).reshape(1, -1),
                delimiter=",",
                fmt="%.10g",
                newline="\n",
            )


def _label_slug(label: str) -> str:
    return "_".join(label.strip().lower().split())
