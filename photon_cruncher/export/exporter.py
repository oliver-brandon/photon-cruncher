from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from photon_cruncher.processing.pipeline import ProcessedSignal, ProcessingSettings
from photon_cruncher.version import APP_NAME, __version__


def batch_output_directories(
    input_paths: list[Path], output_dir: Path, *, per_session_subdir: bool
) -> dict[Path, Path]:
    paths = list(dict.fromkeys(Path(path).expanduser().resolve() for path in input_paths))
    counts = Counter(path.stem.casefold() for path in paths)
    destinations: dict[Path, Path] = {}
    for path in paths:
        if counts[path.stem.casefold()] > 1:
            identity = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:12]
            destinations[path] = output_dir / f"{path.stem}--{identity}"
        else:
            destinations[path] = output_dir / path.stem if per_session_subdir else output_dir
    return destinations


def check_export_source(output_dir: Path, prefix: str, source_path: str | Path) -> None:
    manifest = output_dir / f"{prefix}_analysis.json"
    if not manifest.exists():
        return
    previous = json.loads(manifest.read_text(encoding="utf-8")).get("source", {}).get("path")
    if (
        not previous
        or Path(previous).expanduser().resolve() != Path(source_path).expanduser().resolve()
    ):
        raise ValueError(
            f"Existing exports belong to another recording: {manifest}. "
            "Choose a different output folder."
        )


def write_analysis_manifest(
    output_dir: Path,
    prefix: str,
    source_path: str | Path,
    epoc_name: str,
    channel_key: str,
    processed: ProcessedSignal,
    settings: ProcessingSettings,
) -> Path:
    check_export_source(output_dir, prefix, source_path)
    source = Path(source_path).expanduser().resolve()
    setting_values = {
        key: None if isinstance(value, float) and not math.isfinite(value) else value
        for key, value in asdict(settings).items()
    }
    payload = {
        "schema_version": 1,
        "created_utc": datetime.now(UTC).isoformat(),
        "application": {"name": APP_NAME, "version": __version__},
        "source": {"path": str(source), "name": source.name},
        "analysis": {
            "epoc": epoc_name,
            "channel": channel_key,
            "pipeline": "control_to_signal_linear_v1",
            "settings": setting_values,
        },
        "trials": {
            "kept": int(processed.zall.shape[0]),
            "numbers": processed.trial_numbers,
            "labels": processed.trial_labels,
            "dropped_incomplete": processed.dropped_edge_trials,
            "artifact_removals": processed.num_artifacts,
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{prefix}_analysis.json"
    path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return path


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
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"{session_name}_{epoc_name}_{channel_key}{filename_suffix}"
    source_path = metadata.get("source_path")
    if source_path:
        check_export_source(output_dir, prefix, source_path)

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
    if source_path:
        write_analysis_manifest(
            output_dir, prefix, source_path, epoc_name, channel_key, processed, settings
        )
    return heatmap_path


def export_batch_summary(output_dir: Path, rows: list[dict[str, Any]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "batch_summary.csv"
    pd.DataFrame(rows).to_csv(summary_path, index=False)


def _label_slug(label: str) -> str:
    return "_".join(label.strip().lower().split())
