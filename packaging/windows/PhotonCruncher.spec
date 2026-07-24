# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Photon Cruncher Aurora (Windows)."""

from pathlib import Path


project_root = Path(SPECPATH).parents[1]
package_root = project_root / "photon_cruncher"
icon_path = package_root / "assets" / "icons" / "photon-cruncher-aurora.ico"
if not icon_path.exists():
    icon_path = package_root / "assets" / "icons" / "photon-cruncher.ico"
app_name = "Photon Cruncher Aurora v2.0"

a = Analysis(
    [str(package_root / "aurora_main.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        (str(package_root / "assets"), "photon_cruncher/assets"),
        (str(package_root / "gui_aurora" / "static"), "photon_cruncher/gui_aurora/static"),
    ],
    hiddenimports=[
        "tdt",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebChannel",
        "photon_cruncher.gui_aurora.shell",
        "photon_cruncher.gui_aurora.server",
        "photon_cruncher.gui_aurora.session_store",
        "photon_cruncher.service",
        "photon_cruncher.product",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "AppKit",
        "Foundation",
        "objc",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=app_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_path),
)

cli_a = Analysis(
    [str(package_root / "cli.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        (str(package_root / "assets"), "photon_cruncher/assets"),
    ],
    hiddenimports=["tdt", "photon_cruncher.service"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "AppKit",
        "Foundation",
        "objc",
    ],
    noarchive=False,
    optimize=0,
)
cli_pyz = PYZ(cli_a.pure)
cli_exe = EXE(
    cli_pyz,
    cli_a.scripts,
    cli_a.binaries,
    cli_a.datas,
    [],
    name="photon-cruncher-cli",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_path),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=app_name,
)
