#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd "${script_dir}/.." && pwd)"
python_bin="${PYTHON_BIN:-}"
venv_dir="${project_root}/.build-venv"
spec_file="${project_root}/packaging/macos/PhotonCruncher.spec"
version_script="${project_root}/scripts/version_metadata.py"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This build script creates a macOS .app bundle and must be run on macOS." >&2
  exit 1
fi

# Prefer an isolated Python 3.11 build env (WebEngine wheels / Addons are reliable there).
if [[ -z "${python_bin}" ]]; then
  if command -v python3.11 >/dev/null 2>&1; then
    python_bin="$(command -v python3.11)"
  elif [[ -x /Users/brandon/miniconda/bin/conda ]]; then
    # Ensure conda env exists at .build-venv if missing.
    if [[ ! -x "${venv_dir}/bin/python" ]]; then
      /Users/brandon/miniconda/bin/conda create -y -p "${venv_dir}" python=3.11 pip setuptools wheel
    fi
    python_bin="${venv_dir}/bin/python"
  else
    python_bin="python3"
  fi
fi

app_name="$("${python_bin}" "${version_script}" --field bundle_app_name)"
archive_stem="$("${python_bin}" "${version_script}" --field archive_stem)"
zip_stem="${archive_stem}-macOS"

if [[ ! -x "${venv_dir}/bin/python" ]]; then
  "${python_bin}" -m venv "${venv_dir}"
fi

"${venv_dir}/bin/python" -m pip install --upgrade pip setuptools wheel
"${venv_dir}/bin/python" -m pip install -e "${project_root}/photon_cruncher[build]"

# WebEngine lives in PySide6 Addons (bundled with modern PySide6). Verify present.
if ! "${venv_dir}/bin/python" -c "from PySide6.QtWebEngineWidgets import QWebEngineView" >/dev/null 2>&1; then
  echo "PySide6 QtWebEngineWidgets is missing. Installing PySide6 + Addons..." >&2
  "${venv_dir}/bin/python" -m pip install --upgrade "PySide6>=6.6"
  if ! "${venv_dir}/bin/python" -c "from PySide6.QtWebEngineWidgets import QWebEngineView" >/dev/null 2>&1; then
    echo "ERROR: Qt WebEngine is required for Aurora and could not be imported." >&2
    exit 1
  fi
fi

"${venv_dir}/bin/python" -m PyInstaller \
  --clean \
  --noconfirm \
  --distpath "${project_root}/dist" \
  --workpath "${project_root}/build" \
  "${spec_file}"

mkdir -p "${project_root}/dist/${zip_stem}"
rm -rf "${project_root}/dist/${zip_stem:?}/"*
ditto \
  "${project_root}/dist/${app_name}.app" \
  "${project_root}/dist/${zip_stem}/${app_name}.app"
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
