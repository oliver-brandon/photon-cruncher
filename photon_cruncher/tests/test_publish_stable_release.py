"""Stable release publication refuses incomplete payloads and unsafe retries."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from contextlib import chdir
from pathlib import Path
from unittest import mock

from scripts import publish_stable_release as publisher


class StableReleasePublicationTests(unittest.TestCase):
    def test_both_platforms_are_verified_before_publishing(self):
        with tempfile.TemporaryDirectory() as temporary, chdir(temporary):
            root = Path(temporary)
            for channel, folder, ext in (
                ("stable-win-x64", "release-windows", "exe"),
                ("stable-osx-arm64", "release-macos", "pkg"),
            ):
                directory = root / folder
                directory.mkdir()
                entries = []
                for kind in ("Full", "Delta"):
                    name = f"com.photoncruncher.app-2.1.0-{channel}-{kind.lower()}.nupkg"
                    content = f"{channel}-{kind}".encode()
                    (directory / name).write_bytes(content)
                    entries.append({
                        "Version": "2.1.0", "Type": kind,
                        "PackageId": "com.photoncruncher.app",
                        "FileName": name, "Size": len(content),
                        "SHA256": hashlib.sha256(content).hexdigest(),
                    })
                (directory / f"releases.{channel}.json").write_text(json.dumps({"Assets": entries}))
                (directory / f"candidate-Setup.{ext}").write_bytes(b"installer")
                (directory / f"com.photoncruncher.app-{channel}-Portable.zip").write_bytes(b"portable")

            env = {"RELEASE_VERSION": "2.1.0", "RELEASE_TAG": "v2.1.0",
                   "GITHUB_REPOSITORY": "owner/repo", "INSTALLER_STEM": "Photon-v2.1.0"}
            # A public release is never replaced, even with valid local payloads.
            with (mock.patch.dict(os.environ, env),
                  mock.patch.object(publisher.subprocess, "run") as run,
                  mock.patch.object(publisher, "gh") as gh):
                run.return_value.returncode = 0
                run.return_value.stdout = '{"isDraft":false}'
                with self.assertRaisesRegex(ValueError, "published release already exists"):
                    publisher.main()
                gh.assert_not_called()
            # A corrupt package must fail before any remote calls.
            (root / "release-macos" / entries[0]["FileName"]).write_bytes(b"corrupt")
            with (mock.patch.dict(os.environ, env),
                  mock.patch.object(publisher.subprocess, "run") as run):
                with self.assertRaisesRegex(ValueError, "hash or size mismatch"):
                    publisher.main()
                run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
