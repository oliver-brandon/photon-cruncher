# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import runpy

from PyInstaller.utils.hooks import collect_all


project_root = Path(SPECPATH).parents[1]
package_root = project_root / "photon_cruncher"
version_meta = runpy.run_path(str(package_root / "version.py"))
icon_path = package_root / "assets" / "icons" / "photon-cruncher.icns"
app_name = version_meta["BUNDLE_APP_NAME"]
velopack_datas, velopack_binaries, velopack_hiddenimports = collect_all("velopack")


a = Analysis(
    [str(package_root / "main.py")],
    pathex=[str(project_root)],
    binaries=velopack_binaries,
    datas=[
        (str(package_root / "assets"), "photon_cruncher/assets"),
    ] + velopack_datas,
    hiddenimports=[
        "tdt",
        "photon_cruncher.gui.updater",
        "photon_cruncher.updates",
        "velopack",
    ] + velopack_hiddenimports,
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
    argv_emulation=False,
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
app = BUNDLE(
    coll,
    name=f"{app_name}.app",
    icon=str(icon_path),
    bundle_identifier=version_meta["BUNDLE_IDENTIFIER"],
    info_plist={
        "CFBundleDisplayName": version_meta["APP_NAME"],
        "CFBundleName": version_meta["APP_NAME"],
        "CFBundleShortVersionString": version_meta["__version__"],
        "CFBundleVersion": version_meta["__version__"],
        "LSApplicationCategoryType": "public.app-category.science",
        "NSHighResolutionCapable": True,
    },
)
