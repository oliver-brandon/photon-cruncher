#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd "${script_dir}/.." && pwd)"
python_bin="${PYTHON_BIN:-python3}"
venv_dir="${project_root}/.build-venv"
spec_file="${project_root}/packaging/macos/PhotonCruncherAurora.spec"

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
"${venv_dir}/bin/python" -m pip install "PySide6-WebEngine>=6.6" || true
"${venv_dir}/bin/python" -m PyInstaller \
  --clean \
  --noconfirm \
  --distpath "${project_root}/dist" \
  --workpath "${project_root}/build" \
  "${spec_file}"

echo
echo "Built Aurora app:"
echo "  ${project_root}/dist/Photon Cruncher Aurora v1.1.4.app"
echo
echo "Lab GUI is unchanged. Launch Aurora with:"
echo "  open \"${project_root}/dist/Photon Cruncher Aurora v1.1.4.app\""
echo "or during development:"
echo "  .build-venv/bin/python -m photon_cruncher.aurora_main"
