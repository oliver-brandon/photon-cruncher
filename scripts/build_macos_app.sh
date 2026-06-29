#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd "${script_dir}/.." && pwd)"
python_bin="${PYTHON_BIN:-python3}"
venv_dir="${project_root}/.build-venv"
spec_file="${project_root}/packaging/macos/PhotonCruncher.spec"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This build script creates a macOS .app bundle and must be run on macOS." >&2
  exit 1
fi

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

echo
echo "Built app:"
echo "  ${project_root}/dist/Photon Cruncher Dev v1.1.3.app"
echo
echo "You can move 'Photon Cruncher Dev v1.1.3.app' anywhere on this Mac, including /Applications."
