#!/usr/bin/env bash
# Apply a locally staged stable full package to the real v1.2.1 install on a disposable runner.
# This checks UpdateMac's apply/relaunch path, not GitHub feed discovery or the in-app dialog.
set -euo pipefail

if [[ "${GITHUB_ACTIONS:-}" != "true" || "${RUNNER_OS:-}" != "macOS" || -z "${RUNNER_TEMP:-}" ]]; then
  echo "This test must run on an isolated GitHub-hosted macOS runner." >&2
  exit 1
fi
if [[ "$#" -ne 1 || ! -f "$1" ]]; then
  echo "Usage: $0 candidate-full.nupkg" >&2
  exit 2
fi

candidate="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
target_version="$(python3 - "$candidate" <<'PYCODE'
import sys, zipfile, xml.etree.ElementTree as ET
with zipfile.ZipFile(sys.argv[1]) as archive:
    names = [name for name in archive.namelist() if name.endswith(".nuspec") and "/" not in name]
    if len(names) != 1:
        raise SystemExit("Expected one package manifest")
    root = ET.fromstring(archive.read(names[0]))
    metadata = next(node for node in root if node.tag.split("}")[-1] == "metadata")
    fields = {node.tag.split("}")[-1]: node.text for node in metadata}
    if (
        fields.get("id") != "com.photoncruncher.app"
        or fields.get("channel") != "stable-osx-arm64"
        or fields.get("rid") != "osx-arm64"
        or not fields.get("version")
        or fields["version"] == "1.2.1"
    ):
        raise SystemExit("Candidate has an unexpected package identity, channel, runtime or version")
    print(fields["version"])
PYCODE
)"
work="${RUNNER_TEMP}/photon-stable-upgrade"
mkdir -p "$work/packages"
# The updater deletes a corrupt package. Stage a copy so the build artifact is
# preserved for diagnostics and later publication.
cp -p "$candidate" "$work/packages/$(basename "$candidate")"
candidate="$work/packages/$(basename "$candidate")"
old_pkg="$work/Photon-Cruncher-v1.2.1-macOS.pkg"
curl --fail --location --retry 3 --max-time 300 \
  -o "$old_pkg" \
  https://github.com/oliver-brandon/photon-cruncher/releases/download/v1.2.1/Photon-Cruncher-v1.2.1-macOS.pkg
pkgutil --check-signature "$old_pkg"
sudo installer -pkg "$old_pkg" -target /

installed="/Applications/Photon Cruncher.app"
if [[ ! -d "$installed" ]]; then
  echo "The v1.2.1 package did not install the expected application." >&2
  exit 1
fi
# Exercise the actual PKG payload at a user-writable location with the same
# app name. This avoids unattended admin prompts and avoids launching as root.
mkdir -p "$work/Applications"
app="$work/Applications/Photon Cruncher.app"
ditto "$installed" "$app"
binary="$app/Contents/MacOS/Photon Cruncher"
updater="$app/Contents/MacOS/UpdateMac"
if [[ ! -x "$binary" || ! -x "$updater" ]]; then
  echo "The v1.2.1 installer did not create the expected stable app and updater." >&2
  exit 1
fi
test "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$app/Contents/Info.plist")" = "com.photoncruncher.app"
test "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$app/Contents/Info.plist")" = "1.2.1"
codesign --verify --deep --strict "$app"
open -n "$app"
old_pid=""
new_pid=""
cleanup() {
  [[ -z "$old_pid" ]] || kill -TERM "$old_pid" 2>/dev/null || true
  [[ -z "$new_pid" ]] || kill -TERM "$new_pid" 2>/dev/null || true
}
trap cleanup EXIT
for _ in {1..60}; do
  old_pid="$(pgrep -f "^$binary" | head -1 || true)"
  [[ -n "$old_pid" ]] && break
  sleep 1
done
if [[ -z "$old_pid" ]]; then
  echo "The v1.2.1 app did not start." >&2
  exit 1
fi

# Run the installed updater as the desktop user. UpdateMac will replace the
# user-owned bundle and relaunch without an elevation prompt.
"$updater" --verbose --rootDir "$app" --packageDir "$work/packages" \
  apply --waitPid "$old_pid" --package "$candidate" > "$work/update.log" 2>&1 &
update_pid=$!
kill -TERM "$old_pid"
wait "$update_pid" || { cat "$work/update.log" >&2; exit 1; }

# UpdateMac must relaunch the installed app itself, not merely replace files.
for _ in {1..120}; do
  version="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$app/Contents/Info.plist" 2>/dev/null || true)"
  executable="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' "$app/Contents/Info.plist" 2>/dev/null || true)"
  new_pid="$(pgrep -f "^$app/Contents/MacOS/$executable" | head -1 || true)"
  [[ "$version" = "$target_version" && -n "$new_pid" && "$new_pid" != "$old_pid" ]] && break
  sleep 1
done
if [[ "${version:-}" != "$target_version" || -z "${new_pid:-}" || "$new_pid" = "$old_pid" ]]; then
  cat "$work/update.log" >&2
  echo "UpdateMac did not replace and relaunch the stable app as $target_version." >&2
  exit 1
fi
test "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$app/Contents/Info.plist")" = "com.photoncruncher.app"
codesign --verify --deep --strict "$app"
echo "v1.2.1 installer, UpdateMac apply and automatic $target_version relaunch passed."
# Close the automatically relaunched instance before the GUI exercise opens
# this same installed bundle with its isolated diagnostics connection.
kill -TERM "$new_pid"
for _ in {1..30}; do
  kill -0 "$new_pid" 2>/dev/null || exit 0
  sleep 1
done
echo "The restarted application did not exit." >&2
exit 1
