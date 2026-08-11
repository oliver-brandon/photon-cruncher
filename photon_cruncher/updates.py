"""Dev-only Velopack update service shared by the Aurora desktop shell."""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from enum import Enum
from threading import RLock
from typing import Any, Callable, Protocol

from packaging.version import InvalidVersion, Version

from photon_cruncher.version import (
    UPDATE_CHANNEL_PREFIX,
    UPDATE_PACKAGE_ID,
    UPDATE_REPOSITORY_URL,
    __version__,
    update_target,
)


LOG = logging.getLogger(__name__)


class UpdateState(str, Enum):
    IDLE = "idle"
    CHECKING = "checking"
    CURRENT = "current"
    AVAILABLE = "available"
    DOWNLOADING = "downloading"
    READY = "ready"
    INSTALLING = "installing"
    UNAVAILABLE = "unavailable"
    DOWNLOAD_FAILED = "download_failed"
    INSTALL_FAILED = "install_failed"
    DISABLED = "disabled"


class UpdateConfigurationError(RuntimeError):
    """Raised when an updater could escape the Aurora dev release boundary."""


@dataclass(frozen=True)
class UpdateRelease:
    version: str
    notes_markdown: str = ""
    package_id: str = UPDATE_PACKAGE_ID
    native: Any = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class UpdateSnapshot:
    state: UpdateState
    current_version: str
    channel: str
    release: UpdateRelease | None = None
    progress: int | None = None
    message: str = ""

    @property
    def update_visible(self) -> bool:
        return self.state in {
            UpdateState.AVAILABLE,
            UpdateState.DOWNLOADING,
            UpdateState.READY,
            UpdateState.DOWNLOAD_FAILED,
            UpdateState.INSTALL_FAILED,
        }


class UpdateBackend(Protocol):
    channel: str
    package_id: str

    def check(self) -> UpdateRelease | None: ...

    def download(
        self,
        release: UpdateRelease,
        progress: Callable[[int], None] | None = None,
    ) -> None: ...

    def apply_and_restart(self, release: UpdateRelease) -> None: ...


def update_channel() -> str:
    return update_target()[0]


def validate_dev_channel(channel: str, expected: str | None = None) -> str:
    expected_channel = expected or update_channel()
    if not channel.startswith(f"{UPDATE_CHANNEL_PREFIX}-"):
        raise UpdateConfigurationError(
            f"Refusing non-dev update channel {channel!r}"
        )
    if channel != expected_channel:
        raise UpdateConfigurationError(
            f"Update channel {channel!r} does not match this build "
            f"({expected_channel!r})"
        )
    return channel


def is_newer_version(candidate: str, current: str = __version__) -> bool:
    """Compare release versions without lexical ordering mistakes."""
    try:
        return Version(candidate.removeprefix("v")) > Version(
            current.removeprefix("v")
        )
    except InvalidVersion as exc:
        raise ValueError(f"Invalid update version: {exc}") from exc


def run_velopack_startup() -> bool:
    """Run Velopack lifecycle hooks before the packaged desktop app starts."""
    if not velopack_runtime_available():
        return False
    try:
        import velopack

        velopack.App().set_auto_apply_on_startup(False).run()
        return True
    except Exception:  # noqa: BLE001
        LOG.exception("Velopack startup hooks failed")
        return False


def velopack_runtime_available() -> bool:
    """Return whether this process can be managed by a Velopack installation."""
    return bool(
        getattr(sys, "frozen", False)
        or os.environ.get("PHOTON_CRUNCHER_FORCE_VELOPACK")
    )


class VelopackBackend:
    """Thin adapter around the Velopack Python SDK."""

    def __init__(
        self,
        *,
        channel: str | None = None,
        package_id: str = UPDATE_PACKAGE_ID,
        repository_url: str = UPDATE_REPOSITORY_URL,
    ) -> None:
        import velopack

        self.channel = validate_dev_channel(channel or update_channel())
        self.package_id = package_id
        source = velopack.GithubSource(repository_url, None, True)
        options = velopack.UpdateOptions(False, 10, self.channel)
        self._manager = velopack.UpdateManager(source, options)

        installed_id = str(self._manager.get_app_id() or "")
        if installed_id and installed_id != self.package_id:
            raise UpdateConfigurationError(
                f"Installed package {installed_id!r} is not {self.package_id!r}"
            )

    def check(self) -> UpdateRelease | None:
        info = self._manager.check_for_updates()
        if info is None:
            return None
        asset = info.TargetFullRelease
        package_id = str(asset.PackageId or "")
        if package_id and package_id != self.package_id:
            raise UpdateConfigurationError(
                f"Feed package {package_id!r} is not {self.package_id!r}"
            )
        return UpdateRelease(
            version=str(asset.Version),
            notes_markdown=str(asset.NotesMarkdown or ""),
            package_id=package_id or self.package_id,
            native=info,
        )

    def download(
        self,
        release: UpdateRelease,
        progress: Callable[[int], None] | None = None,
    ) -> None:
        self._manager.download_updates(release.native, progress)

    def apply_and_restart(self, release: UpdateRelease) -> None:
        self._manager.apply_updates_and_restart(release.native)


class UpdateService:
    """Stateful, UI-independent update coordinator."""

    def __init__(
        self,
        backend_factory: Callable[[], UpdateBackend],
        *,
        current_version: str = __version__,
        channel: str | None = None,
    ) -> None:
        self.current_version = current_version
        self.channel = validate_dev_channel(channel or update_channel())
        self._backend_factory = backend_factory
        self._backend: UpdateBackend | None = None
        self._lock = RLock()
        self._snapshot = UpdateSnapshot(
            UpdateState.IDLE,
            current_version,
            self.channel,
        )

    @property
    def snapshot(self) -> UpdateSnapshot:
        with self._lock:
            return self._snapshot

    def _set(self, snapshot: UpdateSnapshot) -> UpdateSnapshot:
        with self._lock:
            self._snapshot = snapshot
        return snapshot

    def _get_backend(self) -> UpdateBackend:
        if self._backend is None:
            backend = self._backend_factory()
            validate_dev_channel(backend.channel, self.channel)
            if backend.package_id != UPDATE_PACKAGE_ID:
                raise UpdateConfigurationError(
                    f"Updater package {backend.package_id!r} is not "
                    f"{UPDATE_PACKAGE_ID!r}"
                )
            self._backend = backend
        return self._backend

    def check(self) -> UpdateSnapshot:
        self._set(
            UpdateSnapshot(
                UpdateState.CHECKING,
                self.current_version,
                self.channel,
                message="Checking for Aurora dev updates...",
            )
        )
        try:
            release = self._get_backend().check()
            if release is None or not is_newer_version(
                release.version, self.current_version
            ):
                return self._set(
                    UpdateSnapshot(
                        UpdateState.CURRENT,
                        self.current_version,
                        self.channel,
                        message="Photon Cruncher Aurora is up to date.",
                    )
                )
            return self._set(
                UpdateSnapshot(
                    UpdateState.AVAILABLE,
                    self.current_version,
                    self.channel,
                    release=release,
                    message=f"Aurora v{release.version} is available.",
                )
            )
        except UpdateConfigurationError as exc:
            return self._set(
                UpdateSnapshot(
                    UpdateState.DISABLED,
                    self.current_version,
                    self.channel,
                    message=str(exc),
                )
            )
        except Exception:  # noqa: BLE001
            LOG.warning("Update check unavailable", exc_info=True)
            return self._set(
                UpdateSnapshot(
                    UpdateState.UNAVAILABLE,
                    self.current_version,
                    self.channel,
                    message=(
                        "Could not reach the Aurora dev update service. "
                        "The app can continue offline."
                    ),
                )
            )

    def download(
        self,
        progress: Callable[[int], None] | None = None,
    ) -> UpdateSnapshot:
        release = self.snapshot.release
        if release is None:
            raise RuntimeError("No update is available to download")
        self._set(
            UpdateSnapshot(
                UpdateState.DOWNLOADING,
                self.current_version,
                self.channel,
                release=release,
                progress=0,
                message=f"Downloading Aurora v{release.version}...",
            )
        )
        try:
            self._get_backend().download(release, progress)
            return self._set(
                UpdateSnapshot(
                    UpdateState.READY,
                    self.current_version,
                    self.channel,
                    release=release,
                    progress=100,
                    message="Update downloaded. Ready to restart.",
                )
            )
        except Exception:  # noqa: BLE001
            LOG.warning("Update download failed", exc_info=True)
            return self._set(
                UpdateSnapshot(
                    UpdateState.DOWNLOAD_FAILED,
                    self.current_version,
                    self.channel,
                    release=release,
                    message=(
                        "The update download failed. Your current installation "
                        "was not changed."
                    ),
                )
            )

    def install_and_restart(self) -> UpdateSnapshot:
        release = self.snapshot.release
        if release is None:
            raise RuntimeError("No downloaded update is ready to install")
        installing = self._set(
            UpdateSnapshot(
                UpdateState.INSTALLING,
                self.current_version,
                self.channel,
                release=release,
                progress=100,
                message="Installing update and restarting...",
            )
        )
        try:
            self._get_backend().apply_and_restart(release)
            return installing
        except Exception:  # noqa: BLE001
            LOG.warning("Update installation failed", exc_info=True)
            return self._set(
                UpdateSnapshot(
                    UpdateState.INSTALL_FAILED,
                    self.current_version,
                    self.channel,
                    release=release,
                    message=(
                        "The update could not be installed. Your current "
                        "installation was not changed."
                    ),
                )
            )


def create_update_service() -> UpdateService:
    channel = update_channel()
    return UpdateService(
        lambda: VelopackBackend(channel=channel),
        channel=channel,
    )
