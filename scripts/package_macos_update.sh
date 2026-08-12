#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd "${script_dir}/.." && pwd)"
version_script="${project_root}/scripts/version_metadata.py"
build_script="${project_root}/scripts/build_macos_app.sh"
python_bin="${PYTHON_BIN:-python3}"
vpk_bin="${VPK_BIN:-vpk}"
output_dir="${VELOPACK_OUTPUT_DIR:-${project_root}/dist/velopack-releases}"
stage_root="${project_root}/build/velopack/macos"
release_notes="${project_root}/packaging/velopack/release-notes.md"
entitlements="${project_root}/packaging/macos/aurora.entitlements"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Velopack macOS releases must be built on macOS." >&2
  exit 1
fi

if [[ "${VELOPACK_SKIP_BUILD:-0}" != "1" ]]; then
  "${build_script}"
fi

metadata_python="${project_root}/.build-venv/bin/python"
if [[ ! -x "${metadata_python}" ]]; then
  metadata_python="${python_bin}"
fi

version="$("${metadata_python}" "${version_script}" --field version)"
app_name="$("${metadata_python}" "${version_script}" --field app_name)"
bundle_app_name="$("${metadata_python}" "${version_script}" --field bundle_app_name)"
package_id="$("${metadata_python}" "${version_script}" --field update_package_id)"
channel="$("${metadata_python}" "${version_script}" --field update_channel)"
runtime="$("${metadata_python}" "${version_script}" --field update_runtime)"
expected_channel="aurora-dev-${runtime}"

if [[ "${channel}" != "${expected_channel}" ]]; then
  echo "Refusing unexpected update channel: ${channel}" >&2
  exit 1
fi

for variable in \
  MACOS_DEVELOPER_ID_APPLICATION \
  MACOS_DEVELOPER_ID_INSTALLER \
  MACOS_NOTARY_PROFILE \
  MACOS_SIGNING_KEYCHAIN; do
  if [[ -z "${!variable:-}" ]]; then
    echo "Required signing variable ${variable} is missing." >&2
    exit 1
  fi
done

source_app="${project_root}/dist/${bundle_app_name}.app"
staged_app="${stage_root}/${app_name}.app"
if [[ ! -d "${source_app}" ]]; then
  echo "PyInstaller app not found: ${source_app}" >&2
  exit 1
fi

rm -rf "${stage_root}"
mkdir -p "${stage_root}" "${output_dir}"
ditto "${source_app}" "${staged_app}"
staged_versioned_executable="${staged_app}/Contents/MacOS/${bundle_app_name}"
staged_main_executable="${staged_app}/Contents/MacOS/${app_name}"
if [[ ! -f "${staged_versioned_executable}" ]]; then
  echo "Staged macOS executable not found: ${staged_versioned_executable}" >&2
  exit 1
fi
mv "${staged_versioned_executable}" "${staged_main_executable}"
/usr/libexec/PlistBuddy \
  -c "Set :CFBundleExecutable ${app_name}" \
  "${staged_app}/Contents/Info.plist"
if [[ -f "${project_root}/dist/photon-cruncher-cli" ]]; then
  mkdir -p "${staged_app}/Contents/Resources/bin"
  staged_cli="${staged_app}/Contents/Resources/bin/photon-cruncher-cli"
  cp \
    "${project_root}/dist/photon-cruncher-cli" \
    "${staged_cli}"
  chmod +x "${staged_cli}"
  codesign \
    --force \
    --options runtime \
    --timestamp \
    --sign "${MACOS_DEVELOPER_ID_APPLICATION}" \
    --keychain "${MACOS_SIGNING_KEYCHAIN}" \
    "${staged_cli}"
fi

set +e
"${vpk_bin}" pack \
  --outputDir "${output_dir}" \
  --channel "${channel}" \
  --runtime "${runtime}" \
  --packId "${package_id}" \
  --packVersion "${version}" \
  --packDir "${staged_app}" \
  --mainExe "${app_name}" \
  --packTitle "${app_name} Dev" \
  --packAuthors "Brandon Oliver" \
  --releaseNotes "${release_notes}" \
  --signAppIdentity "${MACOS_DEVELOPER_ID_APPLICATION}" \
  --signInstallIdentity "${MACOS_DEVELOPER_ID_INSTALLER}" \
  --notaryProfile "${MACOS_NOTARY_PROFILE}" \
  --keychain "${MACOS_SIGNING_KEYCHAIN}" \
  --signEntitlements "${entitlements}"
vpk_status=$?
set -e

if [[ "${vpk_status}" -ne 0 ]]; then
  notary_history="$(mktemp)"
  if xcrun notarytool history \
    --keychain-profile "${MACOS_NOTARY_PROFILE}" \
    --keychain "${MACOS_SIGNING_KEYCHAIN}" \
    --output-format json > "${notary_history}"; then
    notary_job_id="$("${metadata_python}" -c '
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    history = json.load(handle).get("history", [])
if history:
    print(max(history, key=lambda item: item.get("createdDate", ""))["id"])
' "${notary_history}")"
    if [[ -n "${notary_job_id}" ]]; then
      echo "Latest Apple notarization log (${notary_job_id}):" >&2
      xcrun notarytool log \
        "${notary_job_id}" \
        --keychain-profile "${MACOS_NOTARY_PROFILE}" \
        --keychain "${MACOS_SIGNING_KEYCHAIN}" >&2 || true
    fi
  fi
  rm -f "${notary_history}"
  exit "${vpk_status}"
fi

feed="${output_dir}/releases.${channel}.json"
if [[ ! -f "${feed}" ]]; then
  echo "Velopack feed was not created: ${feed}" >&2
  exit 1
fi

pkg_path="$(find "${output_dir}" -maxdepth 1 -name '*.pkg' -print -quit)"
full_package="$(find "${output_dir}" -maxdepth 1 -name '*-full.nupkg' -print -quit)"
if [[ -z "${pkg_path}" || -z "${full_package}" ]]; then
  echo "Velopack did not create the macOS installer and full update package." >&2
  exit 1
fi

pkgutil --check-signature "${pkg_path}"
spctl --assess --verbose=2 --type install "${pkg_path}"

echo "Built signed Aurora dev update channel ${channel}:"
echo "  Installer: ${pkg_path}"
echo "  Full package: ${full_package}"
echo "  Feed: ${feed}"
