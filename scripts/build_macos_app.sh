#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd "${script_dir}/.." && pwd)"
python_bin="${PYTHON_BIN:-python3}"
venv_dir="${project_root}/.build-venv"
spec_file="${project_root}/packaging/macos/PhotonCruncher.spec"
version_script="${project_root}/scripts/version_metadata.py"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This build script creates a macOS .app bundle and must be run on macOS." >&2
  exit 1
fi

app_name="$("${python_bin}" "${version_script}" --field bundle_app_name)"
archive_stem="$("${python_bin}" "${version_script}" --field archive_stem)"
zip_path="${project_root}/dist/${archive_stem}-macOS.zip"

if [[ ! -x "${venv_dir}/bin/python" ]]; then
  "${python_bin}" -m venv "${venv_dir}"
fi

"${venv_dir}/bin/python" -m pip install --upgrade pip setuptools wheel
"${venv_dir}/bin/python" -m pip install -e "${project_root}/photon_cruncher[build]"
"${venv_dir}/bin/python" -m PyInstaller \
  --clean \
  --noconfirm \
  --distpath "${project_root}/dist" \
  --workpath "${project_root}/build" \
  "${spec_file}"

rm -f "${zip_path}"
ditto -c -k --keepParent \
  "${project_root}/dist/${app_name}.app" \
  "${zip_path}"

echo
echo "Built app:"
echo "  ${project_root}/dist/${app_name}.app"
echo
echo "Built zip for manual sharing:"
echo "  ${zip_path}"
