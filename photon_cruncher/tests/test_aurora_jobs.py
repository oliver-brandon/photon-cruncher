from __future__ import annotations

import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

from photon_cruncher.gui_aurora.batch_jobs import BatchJobManager
from photon_cruncher.gui_aurora.session_store import SessionStore


class SessionStoreTests(unittest.TestCase):
    def test_analysis_cache_is_lru_bounded(self) -> None:
        store = SessionStore(max_sessions=2, max_analysis_bytes=100)
        session = SimpleNamespace(source_path=Path("session.mat"))
        with (
            mock.patch(
                "photon_cruncher.gui_aurora.session_store.open_session",
                return_value=session,
            ),
            mock.patch(
                "photon_cruncher.gui_aurora.session_store.session_summary",
                return_value={"session_name": "session"},
            ),
        ):
            cached = store.open("session.mat")

        first = [
            SimpleNamespace(
                processed=SimpleNamespace(values=np.ones(10, dtype=np.float64))
            )
        ]
        second = [
            SimpleNamespace(
                processed=SimpleNamespace(values=np.ones(10, dtype=np.float64))
            )
        ]
        store.put_analysis(cached.path, "first", first)
        store.put_analysis(cached.path, "second", second)

        self.assertIsNone(store.get_analysis(cached.path, "first"))
        self.assertIs(store.get_analysis(cached.path, "second"), second)
        self.assertLessEqual(store.stats()["analysis_entries"], 1)

    def test_analysis_larger_than_cache_budget_is_not_retained(self) -> None:
        store = SessionStore(max_sessions=1, max_analysis_bytes=32)
        session = SimpleNamespace(source_path=Path("large.mat"))
        with (
            mock.patch(
                "photon_cruncher.gui_aurora.session_store.open_session",
                return_value=session,
            ),
            mock.patch(
                "photon_cruncher.gui_aurora.session_store.session_summary",
                return_value={"session_name": "large"},
            ),
        ):
            cached = store.open("large.mat")

        oversized = [
            SimpleNamespace(
                processed=SimpleNamespace(values=np.ones(10, dtype=np.float64))
            )
        ]
        store.put_analysis(cached.path, "oversized", oversized)

        self.assertIsNone(store.get_analysis(cached.path, "oversized"))
        self.assertEqual(store.stats()["analysis_entries"], 0)
        self.assertEqual(store.stats()["analysis_bytes"], 0)

    def test_session_cache_evicts_old_noncurrent_sources(self) -> None:
        store = SessionStore(max_sessions=2, max_analysis_bytes=1024)

        def open_fake(path: str):
            return SimpleNamespace(source_path=Path(path))

        with (
            mock.patch(
                "photon_cruncher.gui_aurora.session_store.open_session",
                side_effect=open_fake,
            ),
            mock.patch(
                "photon_cruncher.gui_aurora.session_store.session_summary",
                return_value={},
            ),
        ):
            first = store.open("first.mat")
            store.open("second.mat", make_current=False)
            store.open("third.mat", make_current=False)

        self.assertEqual(store.current_path(), first.path)
        self.assertEqual(store.stats()["cached_sessions"], 2)
        with self.assertRaises(ValueError):
            store.get("second.mat")
        self.assertEqual(
            store.evict_paths(["third.mat"], keep_current=True),
            1,
        )

    def test_slower_older_open_cannot_replace_the_current_session(self) -> None:
        store = SessionStore(max_sessions=2, max_analysis_bytes=1024)
        first_started = threading.Event()
        release_first = threading.Event()

        def open_fake(path: str):
            if Path(path).name == "first.mat":
                first_started.set()
                release_first.wait(1)
            return SimpleNamespace(source_path=Path(path))

        with (
            mock.patch(
                "photon_cruncher.gui_aurora.session_store.open_session",
                side_effect=open_fake,
            ),
            mock.patch(
                "photon_cruncher.gui_aurora.session_store.session_summary",
                return_value={},
            ),
        ):
            older = threading.Thread(target=lambda: store.open("first.mat"))
            older.start()
            self.assertTrue(first_started.wait(1))
            newest = store.open("second.mat")
            release_first.set()
            older.join(1)

        self.assertFalse(older.is_alive())
        self.assertEqual(store.current_path(), newest.path)
        self.assertEqual(store.stats()["cached_sessions"], 1)


class BatchJobManagerTests(unittest.TestCase):
    def test_completed_job_reports_progress_and_result(self) -> None:
        manager = BatchJobManager()

        def operation(_cancelled, progress):
            progress(1, 2, "Halfway")
            progress(2, 2, "Finished work")
            return {"exports": [{"csv": "result.csv"}]}

        started = manager.start(operation)
        snapshot = manager.wait(started["id"], timeout=2)

        self.assertEqual(snapshot["status"], "completed")
        self.assertEqual(snapshot["progress"], 100)
        self.assertEqual(snapshot["result"]["exports"][0]["csv"], "result.csv")

    def test_running_job_can_be_cancelled(self) -> None:
        manager = BatchJobManager()
        operation_started = threading.Event()

        def operation(cancelled, progress):
            operation_started.set()
            while not cancelled():
                progress(0, 1, "Working")
                time.sleep(0.005)
            return {"exports": []}

        started = manager.start(operation)
        self.assertTrue(operation_started.wait(1))
        manager.cancel(started["id"])
        snapshot = manager.wait(started["id"], timeout=2)

        self.assertEqual(snapshot["status"], "cancelled")
        self.assertEqual(snapshot["result"], {"exports": []})

    def test_only_one_batch_job_runs_at_a_time(self) -> None:
        manager = BatchJobManager()
        operation_started = threading.Event()
        release = threading.Event()

        def operation(_cancelled, _progress):
            operation_started.set()
            release.wait(1)
            return {"exports": []}

        first = manager.start(operation)
        self.assertTrue(operation_started.wait(1))
        with self.assertRaisesRegex(RuntimeError, "already running"):
            manager.start(operation)
        release.set()
        self.assertEqual(manager.wait(first["id"], timeout=2)["status"], "completed")


if __name__ == "__main__":
    unittest.main()
