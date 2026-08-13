from __future__ import annotations

import os
import sys
import types
import unittest
from unittest import mock

from photon_cruncher.updates import (
    UpdateRelease,
    UpdateService,
    UpdateState,
    VelopackBackend,
    is_newer_version,
    validate_stable_channel,
    velopack_runtime_available,
)
from photon_cruncher.version import (
    UPDATE_PACKAGE_ID,
    UPDATE_REPOSITORY_URL,
    update_target,
)


STABLE_CHANNEL = "stable-win-x64"


class FakeBackend:
    def __init__(
        self,
        *,
        channel: str = STABLE_CHANNEL,
        package_id: str = UPDATE_PACKAGE_ID,
        release: UpdateRelease | None = None,
        check_error: Exception | None = None,
        download_error: Exception | None = None,
        install_error: Exception | None = None,
    ) -> None:
        self.channel = channel
        self.package_id = package_id
        self.release = release
        self.check_error = check_error
        self.download_error = download_error
        self.install_error = install_error
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
        if self.install_error:
            raise self.install_error
        self.applied = True


class UpdateTests(unittest.TestCase):
    def test_source_runtime_is_disabled_and_forced_runtime_is_enabled(self) -> None:
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(sys, "frozen", False, create=True),
        ):
            self.assertFalse(velopack_runtime_available())
        with (
            mock.patch.dict(
                os.environ,
                {"PHOTON_CRUNCHER_FORCE_VELOPACK": "1"},
                clear=True,
            ),
            mock.patch.object(sys, "frozen", False, create=True),
        ):
            self.assertTrue(velopack_runtime_available())

    def test_version_comparison_uses_numeric_components(self) -> None:
        self.assertTrue(is_newer_version("1.2.10", "1.2.9"))
        self.assertTrue(is_newer_version("v1.3.0", "1.2.99"))
        self.assertFalse(is_newer_version("1.2.0", "1.2.0"))
        self.assertFalse(is_newer_version("1.1.9", "1.2.0"))
        with self.assertRaises(ValueError):
            is_newer_version("not-a-version", "1.2.0")

    def test_channels_are_stable_and_platform_specific(self) -> None:
        self.assertEqual(
            update_target("Windows", "AMD64"),
            ("stable-win-x64", "win-x64"),
        )
        self.assertEqual(
            update_target("Darwin", "arm64"),
            ("stable-osx-arm64", "osx-arm64"),
        )
        self.assertEqual(
            validate_stable_channel(STABLE_CHANNEL, STABLE_CHANNEL),
            STABLE_CHANNEL,
        )
        with self.assertRaisesRegex(Exception, "non-stable update channel"):
            validate_stable_channel("aurora-dev-win-x64", STABLE_CHANNEL)

    def test_stable_github_source_excludes_prereleases(self) -> None:
        manager = mock.Mock()
        manager.get_app_id.return_value = UPDATE_PACKAGE_ID
        fake_velopack = types.SimpleNamespace(
            GithubSource=mock.Mock(return_value=object()),
            UpdateOptions=mock.Mock(return_value=object()),
            UpdateManager=mock.Mock(return_value=manager),
        )
        with (
            mock.patch.dict(sys.modules, {"velopack": fake_velopack}),
            mock.patch(
                "photon_cruncher.updates.update_channel",
                return_value=STABLE_CHANNEL,
            ),
        ):
            VelopackBackend(channel=STABLE_CHANNEL)

        fake_velopack.GithubSource.assert_called_once_with(
            UPDATE_REPOSITORY_URL, None, False
        )

    def test_unavailable_network_does_not_interrupt_the_app(self) -> None:
        backend = FakeBackend(check_error=ConnectionError("offline"))
        with mock.patch(
            "photon_cruncher.updates.update_channel",
            return_value=STABLE_CHANNEL,
        ):
            service = UpdateService(lambda: backend, channel=STABLE_CHANNEL)

        with self.assertLogs("photon_cruncher.updates", level="WARNING"):
            snapshot = service.check()

        self.assertEqual(snapshot.state, UpdateState.UNAVAILABLE)
        self.assertIn("continue offline", snapshot.message)
        self.assertFalse(snapshot.update_visible)

    def test_failed_download_keeps_current_installation(self) -> None:
        release = UpdateRelease("1.2.1", "A small update.")
        backend = FakeBackend(
            release=release,
            download_error=RuntimeError("download interrupted"),
        )
        with mock.patch(
            "photon_cruncher.updates.update_channel",
            return_value=STABLE_CHANNEL,
        ):
            service = UpdateService(
                lambda: backend,
                current_version="1.2.0",
                channel=STABLE_CHANNEL,
            )

        available = service.check()
        with self.assertLogs("photon_cruncher.updates", level="WARNING"):
            failed = service.download()

        self.assertEqual(available.state, UpdateState.AVAILABLE)
        self.assertEqual(failed.state, UpdateState.DOWNLOAD_FAILED)
        self.assertEqual(failed.release, release)
        self.assertFalse(backend.applied)
        self.assertIn("not changed", failed.message)

    def test_successful_update_reaches_installing_state(self) -> None:
        release = UpdateRelease("1.2.1", "A small update.")
        backend = FakeBackend(release=release)
        with mock.patch(
            "photon_cruncher.updates.update_channel",
            return_value=STABLE_CHANNEL,
        ):
            service = UpdateService(
                lambda: backend,
                current_version="1.2.0",
                channel=STABLE_CHANNEL,
            )
        progress: list[int] = []

        self.assertEqual(service.check().state, UpdateState.AVAILABLE)
        self.assertEqual(service.download(progress.append).state, UpdateState.READY)
        self.assertEqual(
            service.install_and_restart().state,
            UpdateState.INSTALLING,
        )
        self.assertEqual(progress, [25, 100])
        self.assertTrue(backend.applied)

    def test_wrong_package_identity_disables_updates(self) -> None:
        backend = FakeBackend(package_id="com.photoncruncher.aurora.dev")
        with mock.patch(
            "photon_cruncher.updates.update_channel",
            return_value=STABLE_CHANNEL,
        ):
            service = UpdateService(lambda: backend, channel=STABLE_CHANNEL)

        snapshot = service.check()

        self.assertEqual(snapshot.state, UpdateState.DISABLED)
        self.assertIn(UPDATE_PACKAGE_ID, snapshot.message)


if __name__ == "__main__":
    unittest.main()
