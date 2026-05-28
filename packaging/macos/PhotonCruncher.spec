# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


project_root = Path(SPECPATH).parents[1]
package_root = project_root / "photon_cruncher"
icon_path = package_root / "assets" / "icons" / "photon-cruncher.icns"


a = Analysis(
    [str(package_root / "main.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        (str(package_root / "assets"), "photon_cruncher/assets"),
    ],
    hiddenimports=["tdt"],
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
    name="Photon Cruncher Dev v1.1.1",
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
    name="Photon Cruncher Dev v1.1.1",
)
app = BUNDLE(
    coll,
    name="Photon Cruncher Dev v1.1.1.app",
    icon=str(icon_path),
    bundle_identifier="com.photoncruncher.dev",
    info_plist={
        "CFBundleDisplayName": "Photon Cruncher Dev v1.1.1",
        "CFBundleName": "Photon Cruncher Dev v1.1.1",
        "CFBundleShortVersionString": "1.1.1",
        "CFBundleVersion": "1.1.1",
        "LSApplicationCategoryType": "public.app-category.science",
        "NSHighResolutionCapable": True,
    },
)
