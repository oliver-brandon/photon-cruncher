from __future__ import annotations

import contextlib
import io
import os
import sys
import unittest
from unittest import mock

from photon_cruncher.aurora_main import main as aurora_main
from photon_cruncher.updates import (
    UpdateRelease,
    UpdateService,
    UpdateState,
    development_mode_enabled,
    is_newer_version,
    update_channel,
    velopack_runtime_available,
)
from photon_cruncher.version import UPDATE_PACKAGE_ID, update_target


class FakeBackend:
    def __init__(
        self,
        *,
        channel: str | None = None,
        release: UpdateRelease | None = None,
        check_error: Exception | None = None,
        download_error: Exception | None = None,
    ) -> None:
        self.channel = channel or update_channel()
        self.package_id = UPDATE_PACKAGE_ID
        self.release = release
        self.check_error = check_error
        self.download_error = download_error
        self.applied = False

    def check(self) -> UpdateRelease | None:
        if self.check_error:
            raise self.check_error
        return self.release

    def download(self, release, progress=None) -> None:
        if progress:
            progress(25)
            progress(100)
        if self.download_error:
            raise self.download_error

    def apply_and_restart(self, release) -> None:
        self.applied = True


class UpdateTests(unittest.TestCase):
    def test_development_mode_disables_velopack_runtime(self) -> None:
        with (
            mock.patch.dict(os.environ, {"PHOTON_CRUNCHER_DEV": "1"}, clear=True),
            mock.patch.object(sys, "frozen", True, create=True),
        ):
            self.assertTrue(development_mode_enabled())
            self.assertFalse(velopack_runtime_available())

    def test_packaged_non_development_runtime_remains_enabled(self) -> None:
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(sys, "frozen", True, create=True),
        ):
            self.assertFalse(development_mode_enabled())
            self.assertTrue(velopack_runtime_available())

    def test_developer_entry_skips_velopack_startup(self) -> None:
        with (
            mock.patch.dict(os.environ, {"PHOTON_CRUNCHER_DEV": "1"}, clear=True),
            mock.patch("photon_cruncher.aurora_main.run_velopack_startup") as startup,
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaises(SystemExit) as raised,
        ):
            aurora_main(["--version"])
        self.assertEqual(raised.exception.code, 0)
        startup.assert_not_called()

    def test_non_development_entry_runs_velopack_startup(self) -> None:
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch("photon_cruncher.aurora_main.run_velopack_startup") as startup,
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaises(SystemExit) as raised,
        ):
            aurora_main(["--version"])
        self.assertEqual(raised.exception.code, 0)
        startup.assert_called_once_with()

    def test_version_comparison_uses_numeric_components(self) -> None:
        self.assertTrue(is_newer_version("2.0.10", "2.0.9"))
        self.assertTrue(is_newer_version("v2.1.0", "2.0.99"))
        self.assertFalse(is_newer_version("2.0.0", "2.0.0"))
        self.assertFalse(is_newer_version("1.9.9", "2.0.0"))
        with self.assertRaises(ValueError):
            is_newer_version("not-a-version", "2.0.0")

    def test_channels_are_isolated_by_dev_platform_and_architecture(self) -> None:
        self.assertEqual(
            update_target("Windows", "AMD64"),
            ("aurora-dev-win-x64", "win-x64"),
        )
        self.assertEqual(
            update_target("Darwin", "arm64"),
            ("aurora-dev-osx-arm64", "osx-arm64"),
        )

        backend = FakeBackend(channel="stable-win-x64")
        service = UpdateService(lambda: backend, channel=update_channel())
        snapshot = service.check()
        self.assertEqual(snapshot.state, UpdateState.DISABLED)
        self.assertIn("non-dev update channel", snapshot.message)

    def test_unavailable_network_does_not_interrupt_the_app(self) -> None:
        backend = FakeBackend(check_error=ConnectionError("offline"))
        service = UpdateService(lambda: backend, channel=update_channel())

        with self.assertLogs("photon_cruncher.updates", level="WARNING"):
            snapshot = service.check()

        self.assertEqual(snapshot.state, UpdateState.UNAVAILABLE)
        self.assertIn("continue offline", snapshot.message)
        self.assertFalse(snapshot.update_visible)

    def test_failed_download_keeps_current_installation(self) -> None:
        release = UpdateRelease("2.0.1", "A small update.")
        backend = FakeBackend(
            release=release,
            download_error=RuntimeError("download interrupted"),
        )
        service = UpdateService(
            lambda: backend,
            current_version="2.0.0",
            channel=update_channel(),
        )

        available = service.check()
        with self.assertLogs("photon_cruncher.updates", level="WARNING"):
            failed = service.download()

        self.assertEqual(available.state, UpdateState.AVAILABLE)
        self.assertEqual(failed.state, UpdateState.DOWNLOAD_FAILED)
        self.assertEqual(failed.release, release)
        self.assertFalse(backend.applied)
        self.assertIn("not changed", failed.message)


if __name__ == "__main__":
    unittest.main()
