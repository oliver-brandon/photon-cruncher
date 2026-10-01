"""Reproductions from the October 2026 correctness and performance review."""

from __future__ import annotations

import contextlib
import gc
import io
import json
import tempfile
import unittest
import weakref
from dataclasses import replace
from pathlib import Path
from unittest import mock

import numpy as np
from scipy.io import savemat

from photon_cruncher import cli, service
from photon_cruncher.analysis.runner import run_batch_custom
from photon_cruncher.export.exporter import heatmap_trial_ticks
from photon_cruncher.gui_aurora import server
from photon_cruncher.gui_aurora.session_store import STORE, SessionStore
from photon_cruncher.model import Epoc, PhotometrySession, Stream
from photon_cruncher.processing.pipeline import _moving_mean


def synthetic_session(path: Path) -> PhotometrySession:
    fs = 100.0
    time = np.arange(6000) / fs
    control = 20 + 0.01 * time + np.sin(time * 0.2)
    signal = 1.1 * control + np.sin(time * 3) + 0.2 * np.sin(time * 13)
    return PhotometrySession(
        streams={
            "x405A": Stream("x405A", fs, control),
            "x465A": Stream("x465A", fs, signal),
        },
        epocs={"Cue": Epoc("Cue", np.array([10.0, 20.0, 40.0]))},
        info={},
        source_path=Path(path),
    )


def write_synthetic_mat(path: Path) -> Path:
    session = synthetic_session(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    savemat(path, {"data": {
        "streams": {key: {"data": value.data, "fs": value.fs}
                    for key, value in session.streams.items()},
        "epocs": {"Cue": {"onset": session.epocs["Cue"].onset}},
    }})
    return path


class ProcessingRegressionTests(unittest.TestCase):
    def test_benchmark_rejects_an_unavailable_explicit_epoc(self):
        from scripts.bench_backend import _pick_epoc

        with self.assertRaisesRegex(ValueError, "'Tick' is unavailable"):
            _pick_epoc(synthetic_session(Path("test.mat")), "Tick")

    def test_smoothing_matches_shrinking_windows_even_when_longer_than_trace(self):
        trace = np.array([2., 7., -1., 3., 6.])
        for window in (1, 2, 3, 5, 6, 7, 10, 100):
            with self.subTest(window=window):
                expected = [
                    trace[max(0, index - window // 2):
                          min(len(trace), index + (window - 1) // 2 + 1)].mean()
                    for index in range(len(trace))
                ]
                np.testing.assert_allclose(_moving_mean(trace, window), expected)

    def test_oversized_smoothing_runs_through_processing(self):
        result = service.analyze(
            synthetic_session(Path("test.mat")), "Cue", channel_keys=["A_465"],
            settings_overrides={"smooth_factor": 1000},
        )[0]
        self.assertEqual(result.processed.zall_smooth.shape, result.processed.zall.shape)
        self.assertTrue(np.isfinite(result.processed.zall_smooth).all())

    def test_baseline_requires_two_downsampled_samples(self):
        for baseline in ((-4, -3), (-2, -1.85)):
            with self.subTest(baseline=baseline), self.assertRaisesRegex(ValueError, "at least two"):
                service.analyze(
                    synthetic_session(Path("test.mat")), "Cue",
                    settings_overrides={"baseline_per": baseline},
                )

    def test_heatmap_ticks_stay_bounded_on_whole_trial_rows(self):
        for rows in (1, 15, 40, 670, 100000):
            positions, labels = heatmap_trial_ticks(None, rows)
            self.assertLessEqual(len(positions), 12)
            self.assertEqual(len(positions), len(set(positions)))
            self.assertTrue(all(1 <= n <= rows and n % 2 == 1 for n in positions))
            self.assertEqual(labels, [str(n) for n in positions])


class BatchRegressionTests(unittest.TestCase):
    def test_same_named_sources_have_distinct_exports_with_and_without_subfolders(self):
        for subfolders in (False, True):
            with self.subTest(subfolders=subfolders), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                paths = [root / "tank-a" / "Block-1.mat",
                         root / "tank-b" / "Block-1.mat", root / "tank-c" / "block-1"]
                exported = run_batch_custom(
                    paths, [("Cue", ("Cue",))], root / "exports", ["A_465"],
                    service.settings_for_channel, per_session_subdir=subfolders,
                    session_loader=synthetic_session,
                )
                self.assertEqual(len({item.csv_path for item in exported}), 3)
                for item, path in zip(exported, paths):
                    self.assertTrue(item.csv_path.exists())
                    manifest = json.loads(item.manifest_path.read_text())
                    self.assertEqual(manifest["source"]["path"], str(path))

    def test_separate_runs_cannot_overwrite_another_sources_manifest_or_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = service.analyze(synthetic_session(root / "a" / "same.mat"), "Cue")[0]
            second = service.analyze(synthetic_session(root / "b" / "same.mat"), "Cue")[0]
            paths = service.export_result(first, root / "exports")
            before = {key: Path(value).read_bytes() for key, value in paths.items() if value}
            with self.assertRaisesRegex(ValueError, "another source"):
                service.export_result(second, root / "exports")
            for key, content in before.items():
                self.assertEqual(Path(paths[key]).read_bytes(), content)
            # Re-exporting the same recording remains supported.
            service.export_result(first, root / "exports")

    def test_completed_batch_does_not_retain_evicted_sessions_or_matrices(self):
        refs = []
        processed_refs = []
        store = SessionStore(max_sessions=1)
        analyze = service.analyze

        def load(path):
            session = synthetic_session(Path(path))
            refs.append(weakref.ref(session))
            return session

        def track_results(*args, **kwargs):
            results = analyze(*args, **kwargs)
            processed_refs.extend(weakref.ref(result.processed) for result in results)
            return results

        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "photon_cruncher.gui_aurora.session_store.open_session", side_effect=load
        ), mock.patch(
            "photon_cruncher.analysis.runner.service_analyze", new=track_results
        ):
            root = Path(tmp)
            exported = run_batch_custom(
                [root / f"session-{i}.mat" for i in range(6)],
                [("Cue", ("Cue",))], root / "exports", ["A_465"],
                service.settings_for_channel,
                session_loader=lambda path: store.open(path, make_current=False).session,
            )
            gc.collect()
            self.assertEqual(len(exported), 6)
            self.assertEqual(sum(ref() is not None for ref in refs), 1)
            self.assertTrue(all(ref() is None for ref in processed_refs))
            self.assertTrue(all(item.quality["kept_trials"] == 3 for item in exported))


class TrialSelectionRegressionTests(unittest.TestCase):
    def setUp(self):
        STORE.clear()

    def tearDown(self):
        STORE.clear()

    def test_disjoint_channel_trials_produce_an_empty_selection(self):
        session = synthetic_session(Path("disjoint.mat"))
        for wavelength in (405, 465):
            stream = session.streams[f"x{wavelength}A"]
            session.streams[f"x{wavelength}A"] = replace(stream, data=stream.data[:3000])
            session.streams[f"x{wavelength}C"] = replace(
                stream, name=f"x{wavelength}C", data=stream.data[3000:], t0=30.0
            )
        with mock.patch("photon_cruncher.gui_aurora.session_store.open_session", return_value=session):
            payload = server._analyze_request({
                "path": str(session.source_path), "epoc": "Cue", "compact": True,
                "channels": ["A_465", "C_465"], "common_trials": True,
            })
        self.assertEqual(payload["results"], [])
        self.assertEqual([r["trial_numbers"] for r in payload["all_results"]], [[1, 2], [3]])

    def test_common_selection_matches_summary_matrix_and_export(self):
        session = synthetic_session(Path("unequal.mat"))
        for wavelength in (405, 465):
            stream = session.streams[f"x{wavelength}A"]
            session.streams[f"x{wavelength}C"] = replace(
                stream, name=f"x{wavelength}C", data=stream.data[:3000]
            )
        body = {
            "path": str(session.source_path), "epoc": "Cue",
            "channels": ["A_465", "C_465"], "compact": True,
            "common_trials": True,
        }
        with mock.patch("photon_cruncher.gui_aurora.session_store.open_session", return_value=session):
            for selected in (None, [2], [1, 2, 3], []):
                with self.subTest(selected=selected):
                    request = {**body, "trial_numbers": selected}
                    payload = server._analyze_request(request)
                    expected = [1, 2] if selected is None else [n for n in selected if n < 3]
                    self.assertEqual(len(payload["all_results"]), 2)
                    if not expected:
                        self.assertEqual(payload["results"], [])
                        continue
                    for result in payload["results"]:
                        self.assertEqual(result["trial_numbers"], expected)
                        with mock.patch.object(server, "_filtered_result", wraps=server._filtered_result) as filtered:
                            matrix, headers = server._plot_matrix_request({**request, "channel": result["channel"]})
                        self.assertLessEqual(filtered.call_count, 1)
                        values = np.frombuffer(matrix, dtype="<f4").reshape(result["matrix_shape"])
                        self.assertEqual(int(headers["X-Aurora-Rows"]), len(expected))
                        np.testing.assert_allclose(values.mean(axis=0), result["mean"], atol=1e-6)
                    with tempfile.TemporaryDirectory() as tmp:
                        export = server._export_request({
                            **body, "channels": ["A_465"], "trial_numbers": expected,
                            "selected_trials": True, "output_dir": tmp,
                        })
                        csv = np.loadtxt(export["exports"][0]["csv"], delimiter=",", dtype=str)
                        self.assertEqual(list(csv[2:, 0]), [f"TRIAL_{n:03d}" for n in expected])
                        np.testing.assert_allclose(csv[1, 1:].astype(float), payload["results"][0]["mean"], atol=1e-8)
            # Normal Align analysis continues to keep each channel's own trials.
            normal = server._analyze_request({**body, "common_trials": False})
            self.assertEqual(normal["results"][0]["trial_numbers"], [1, 2, 3])


class CliRegressionTests(unittest.TestCase):
    def invoke(self, inputs, output, *flags):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(["analyze", *map(str, inputs), "--epoc", "Cue", "--channel", "A_465",
                             "--output-dir", str(output), "--export", "csv", *flags])
        return code, json.loads(stdout.getvalue()), stderr.getvalue()

    def test_runtime_errors_remain_distinct_from_empty_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            broken = root / "broken.mat"
            broken.write_bytes(b"invalid MAT")
            good = write_synthetic_mat(root / "good.mat")
            code, summary, _ = self.invoke([broken], root / "out")
            self.assertEqual(code, 3)
            self.assertEqual(summary["errors"][0]["stage"], "load")
            code, summary, _ = self.invoke([good], root / "out", "--trange-start", "0")
            self.assertEqual(code, 3)
            self.assertIn("at least two", summary["errors"][0]["reason"])
            self.assertFalse(list((root / "out").rglob("*.csv")))
            code, summary, _ = self.invoke([good], root / "out", "--trial-number", "999")
            self.assertEqual(code, 1)
            self.assertEqual(summary["errors"], [])
            code, summary, _ = self.invoke([broken, good], root / "out")
            self.assertEqual(code, 0)
            self.assertEqual(len(summary["results"]), 1)
            self.assertEqual(len(summary["errors"]), 1)

    def test_csv_export_failures_are_reported_as_runtime_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            good = write_synthetic_mat(root / "good.mat")
            with mock.patch("photon_cruncher.cli.service_export_result", side_effect=OSError("disk full")):
                code, summary, _ = self.invoke([good], root / "out")
            self.assertEqual(code, 3)
            self.assertEqual(summary["errors"][0]["stage"], "export")
            self.assertIn("disk full", summary["errors"][0]["reason"])

    def test_cli_disambiguates_same_named_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs = [write_synthetic_mat(root / tank / "same.mat") for tank in ("a", "b")]
            code, summary, _ = self.invoke(inputs, root / "out", "--no-per-session-subdir")
            self.assertEqual(code, 0)
            self.assertEqual(len({item["exported_csv"] for item in summary["results"]}), 2)


if __name__ == "__main__":
    unittest.main()
