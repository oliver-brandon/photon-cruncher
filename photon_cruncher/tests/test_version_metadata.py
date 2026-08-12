from __future__ import annotations

import subprocess
import sys
import tomllib
import unittest
from pathlib import Path

from photon_cruncher import __version__
from photon_cruncher.product import AURORA_UI_VERSION, bundle_app_name
from photon_cruncher.version import (
    APP_NAME,
    ARCHIVE_STEM,
    UPDATE_CHANNEL_PREFIX,
    UPDATE_PACKAGE_ID,
    UPDATE_RELEASE_TAG,
    update_target,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class VersionMetadataTests(unittest.TestCase):
    def test_runtime_names_derive_from_canonical_version(self) -> None:
        self.assertEqual(AURORA_UI_VERSION, __version__)
        self.assertEqual(bundle_app_name(), f"{APP_NAME} v{__version__}")
        self.assertEqual(ARCHIVE_STEM, f"Photon-Cruncher-Aurora-v{__version__}")

    def test_pyproject_uses_dynamic_package_version(self) -> None:
        pyproject = tomllib.loads(
            (PROJECT_ROOT / "photon_cruncher" / "pyproject.toml").read_text(
                encoding="utf-8"
            )
        )
        self.assertNotIn("version", pyproject["project"])
        self.assertIn("version", pyproject["project"]["dynamic"])
        self.assertEqual(
            pyproject["tool"]["setuptools"]["dynamic"]["version"]["attr"],
            "photon_cruncher.version.__version__",
        )
        self.assertIn("velopack==1.2.0", pyproject["project"]["dependencies"])

    def test_dev_update_identity_derives_from_canonical_version(self) -> None:
        channel, runtime = update_target("Darwin", "arm64")
        self.assertEqual(channel, f"{UPDATE_CHANNEL_PREFIX}-{runtime}")
        self.assertEqual(UPDATE_PACKAGE_ID, "com.photoncruncher.aurora.dev")
        self.assertEqual(UPDATE_RELEASE_TAG, f"aurora-dev-v{__version__}")

    def test_repository_version_metadata_is_consistent(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "scripts" / "version_metadata.py"),
                "--check",
            ],
            cwd=PROJECT_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn(__version__, completed.stdout)


if __name__ == "__main__":
    unittest.main()
