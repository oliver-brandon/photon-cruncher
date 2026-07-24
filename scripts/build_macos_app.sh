#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd "${script_dir}/.." && pwd)"
python_bin="${PYTHON_BIN:-python3}"
venv_dir="${project_root}/.build-venv"
spec_file="${project_root}/packaging/macos/PhotonCruncher.spec"
app_name="Photon Cruncher Aurora v2.0"
zip_stem="Photon-Cruncher-Aurora-v2.0-macOS"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This build script creates a macOS .app bundle and must be run on macOS." >&2
  exit 1
fi

if [[ ! -x "${venv_dir}/bin/python" ]]; then
  "${python_bin}" -m venv "${venv_dir}"
fi

"${venv_dir}/bin/python" -m pip install --upgrade pip setuptools wheel
"${venv_dir}/bin/python" -m pip install -e "${project_root}/photon_cruncher[build]"
# WebEngine is required for the Aurora shell.
"${venv_dir}/bin/python" -m pip install "PySide6-WebEngine>=6.6"
"${venv_dir}/bin/python" -m PyInstaller \
  --clean \
  --noconfirm \
  --distpath "${project_root}/dist" \
  --workpath "${project_root}/build" \
  "${spec_file}"

mkdir -p "${project_root}/dist/${zip_stem}"
rm -rf "${project_root}/dist/${zip_stem:?}/"*
cp -R "${project_root}/dist/${app_name}.app" "${project_root}/dist/${zip_stem}/"
if [[ -f "${project_root}/dist/photon-cruncher-cli" ]]; then
  cp "${project_root}/dist/photon-cruncher-cli" "${project_root}/dist/${zip_stem}/"
fi
ditto -c -k --keepParent "${project_root}/dist/${zip_stem}" "${project_root}/dist/${zip_stem}.zip"

echo
echo "Built Aurora app:"
echo "  ${project_root}/dist/${app_name}.app"
echo
echo "Built command-line access point:"
echo "  ${project_root}/dist/photon-cruncher-cli"
echo
echo "Built zip:"
echo "  ${project_root}/dist/${zip_stem}.zip"
echo
echo "Launch:"
echo "  open \"${project_root}/dist/${app_name}.app\""
echo "or during development:"
echo "  .build-venv/bin/python -m photon_cruncher.aurora_main"
