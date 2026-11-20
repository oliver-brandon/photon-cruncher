"""Exercise the packaged CLI with generated MAT and TDT recordings."""

from __future__ import annotations

import csv
import json
import math
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from scipy.io import savemat

from photon_cruncher.version import __version__


def write_synthetic_recordings(root: Path) -> tuple[Path, Path]:
    """Generate a short, deterministic TDT block and an equivalent MAT export."""
    root.mkdir(parents=True, exist_ok=True)
    sample_rate, seconds, samples_per_record = 100, 60, 100
    time = np.arange(sample_rate * seconds) / sample_rate
    control = 5 + np.sin(time / 9)
    signal = 8 + np.sin(time / 9) + np.sin(time * 2)
    onsets = np.array([10.0, 20.0, 40.0])
    mat = root / "synthetic.mat"
    savemat(mat, {"data": {
        "streams": {
            "x405A": {"data": control, "fs": sample_rate},
            "x465A": {"data": signal, "fs": sample_rate},
        },
        "epocs": {"Cue_": {"onset": onsets}},
    }})

    # TDT TSQ event headers are 40-byte little-endian records, with stream
    # offsets pointing into the TEV and strobe values stored in the offset slot.
    header = struct.Struct("<IIIHHdQIf")

    def event(size, kind, code, channel, timestamp, offset=0, data_format=0, fs=0):
        if isinstance(code, bytes):
            code = int.from_bytes(code, "little")
        return header.pack(size, kind, code, channel, 0, timestamp, offset, data_format, fs)

    block = root / "Synthetic-240101-000000"
    block.mkdir()
    epoch = 1704067200.0
    data = bytearray(80)
    records = [event(20, 34817, 1, 0, epoch - 0.000001, 40)]
    for second in range(seconds):
        for name, stream in ((b"405A", control), (b"465A", signal)):
            first = second * samples_per_record
            samples = np.asarray(stream[first:first + samples_per_record], dtype="<f4").tobytes()
            offset = len(data)
            data.extend(samples)
            records.append(event(10 + samples_per_record, 33025, name, 1, epoch + second,
                                 offset, 0, sample_rate))
        if second in onsets:
            value = struct.unpack("<Q", struct.pack("<d", 1.0))[0]
            records.append(event(10, 257, b"Cue_", 0, epoch + second, value, 4))
    records.append(event(20, 34817, 2, 0, epoch + seconds, len(data)))
    (block / "Synthetic.tsq").write_bytes(
        event((len(records) + 1) * header.size, 0, 0, 0, 0) + b"".join(records)
    )
    (block / "Synthetic.tev").write_bytes(data)
    return mat, block


def run_cli(command: list[str], args: list[str], root: Path, name: str) -> dict:
    report = root / f"{name}.json"
    completed = subprocess.run(
        [*command, *args, "--summary-json", str(report)],
        capture_output=True, text=True, timeout=120,
    )
    if completed.returncode != 0 or not report.is_file():
        raise RuntimeError(f"{name} failed ({completed.returncode}): {completed.stderr}\n{completed.stdout}")
    return json.loads(report.read_text(encoding="utf-8"))


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python smoke_packaged_analysis.py CLI [CLI_ARGS ...]")
    command = sys.argv[1:]
    version = subprocess.run([*command, "--version"], capture_output=True, text=True, timeout=30)
    if version.returncode or version.stdout.strip() != __version__:
        raise RuntimeError(f"Unexpected packaged CLI version: {version.stdout!r} {version.stderr!r}")
    with tempfile.TemporaryDirectory(prefix="photon-packaged-smoke-") as temporary:
        root = Path(temporary)
        mat, block = write_synthetic_recordings(root)
        config = {
            "inputs": [str(mat), str(block)], "output_dir": str(root / "exports"),
            "epocs": ["Cue_"], "channels": ["A_465"],
            "trial_filter": {"trial_numbers": [1, 3]},
            "processing": {"baseline_start": -2, "baseline_end": -0.5},
            "exports": {"csv": True, "figures": True, "figure_format": "png"},
        }
        config_path = root / "config.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        inspected = run_cli(command, ["inspect", str(mat), str(block)], root, "inspect")
        if len(inspected["sessions"]) != 2:
            raise AssertionError(f"Expected two sessions: {inspected}")
        for session in inspected["sessions"]:
            if "A_465" not in session["channels"] or "Cue_" not in session["epocs"]:
                raise AssertionError(f"Missing expected channels or epoc: {session}")
        validated = run_cli(command, ["validate-config", str(config_path)], root, "validate")
        if not validated.get("valid"):
            raise AssertionError(f"Invalid configuration: {validated}")
        analyzed = run_cli(command, ["analyze", "--config", str(config_path)], root, "analysis")
        if len(analyzed["results"]) != 2 or analyzed.get("errors"):
            raise AssertionError(f"Expected two successful results: {analyzed}")
        seen_sources = set()
        for result in analyzed["results"]:
            assert result["channel"] == "A_465" and result["trial_numbers"] == [1, 3]
            for key in ("exported_csv", "exported_figure", "analysis_manifest"):
                path = Path(result[key])
                assert path.is_file() and path.stat().st_size > 0, (key, path)
            with Path(result["exported_csv"]).open(newline="", encoding="utf-8") as stream:
                rows = list(csv.reader(stream))
            assert len(rows) == 4 and [row[0] for row in rows] == [
                "TIME", "MEAN", "TRIAL_001", "TRIAL_003"
            ]
            assert len(rows[0]) > 10 and all(len(row) == len(rows[0]) for row in rows)
            assert all(math.isfinite(float(value)) for row in rows for value in row[1:])
            assert Path(result["exported_figure"]).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
            manifest = json.loads(Path(result["analysis_manifest"]).read_text(encoding="utf-8"))
            assert manifest["trials"]["numbers"] == [1, 3]
            assert manifest["analysis"]["channel"] == "A_465"
            source = Path(manifest["source"]["path"]).resolve()
            assert source == Path(result["source_path"]).resolve()
            seen_sources.add(source)
        assert seen_sources == {mat.resolve(), block.resolve()}
        print("Packaged CLI verified: MAT and TDT inspect, config validation, analysis, CSV, figures and provenance.")


if __name__ == "__main__":
    main()
