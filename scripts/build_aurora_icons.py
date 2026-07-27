#!/usr/bin/env python3
"""Build transparent Aurora PNG, ICNS, and ICO application icons.

The original generated artwork was composited onto white, so packaging that
RGB image preserved white pixels outside the rounded tile. This script restores
an alpha-backed rounded mask and derives every packaged size from one 1024px
source.
"""

from __future__ import annotations

import argparse
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

from PySide6 import QtCore, QtGui


PNG_SIZES = (16, 24, 32, 48, 64, 128, 256, 512, 1024)
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def _transparent_rounded_tile(source: Path) -> QtGui.QImage:
    image = QtGui.QImage(str(source))
    if image.isNull():
        raise ValueError(f"Could not read icon source: {source}")
    if image.width() != image.height():
        raise ValueError("Aurora icon source must be square")
    image = image.convertToFormat(QtGui.QImage.Format.Format_RGBA8888)

    size = image.width()
    mask = QtGui.QImage(
        size,
        size,
        QtGui.QImage.Format.Format_Grayscale8,
    )
    mask.fill(0)
    painter = QtGui.QPainter(mask)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
    painter.setPen(QtCore.Qt.PenStyle.NoPen)
    painter.setBrush(QtCore.Qt.GlobalColor.white)
    inset = max(1.0, size / 1024.0)
    radius = size * (250.0 / 1024.0)
    painter.drawRoundedRect(
        QtCore.QRectF(inset, inset, size - 2 * inset, size - 2 * inset),
        radius,
        radius,
    )
    painter.end()

    pixels = image.bits()
    alpha = mask.constBits()
    stride = image.bytesPerLine()
    mask_stride = mask.bytesPerLine()
    for y in range(size):
        row = y * stride
        mask_row = y * mask_stride
        for x in range(size):
            offset = row + x * 4
            coverage = alpha[mask_row + x]
            pixels[offset + 3] = coverage
            if coverage == 0:
                pixels[offset] = 0
                pixels[offset + 1] = 0
                pixels[offset + 2] = 0
            elif coverage < 255:
                # Undo the source artwork's white matte at the antialiased edge.
                for channel in range(3):
                    composited = pixels[offset + channel]
                    restored = (
                        composited * 255 - (255 - coverage) * 255
                    ) // coverage
                    pixels[offset + channel] = max(0, min(255, restored))
    return image


def _save_pngs(image: QtGui.QImage, png_dir: Path) -> dict[int, Path]:
    png_dir.mkdir(parents=True, exist_ok=True)
    written: dict[int, Path] = {}
    for size in PNG_SIZES:
        resized = image.scaled(
            size,
            size,
            QtCore.Qt.AspectRatioMode.IgnoreAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )
        path = png_dir / f"photon-cruncher-aurora-{size}.png"
        if not resized.save(str(path), "PNG"):
            raise RuntimeError(f"Could not write {path}")
        written[size] = path
    canonical = png_dir / "photon-cruncher-aurora.png"
    if not image.save(str(canonical), "PNG"):
        raise RuntimeError(f"Could not write {canonical}")
    return written


def _build_icns(pngs: dict[int, Path], output: Path) -> None:
    names = {
        "icon_16x16.png": 16,
        "icon_16x16@2x.png": 32,
        "icon_32x32.png": 32,
        "icon_32x32@2x.png": 64,
        "icon_128x128.png": 128,
        "icon_128x128@2x.png": 256,
        "icon_256x256.png": 256,
        "icon_256x256@2x.png": 512,
        "icon_512x512.png": 512,
        "icon_512x512@2x.png": 1024,
    }
    with tempfile.TemporaryDirectory(prefix="aurora-icon-") as tmp:
        iconset = Path(tmp) / "Aurora.iconset"
        iconset.mkdir()
        for name, size in names.items():
            (iconset / name).write_bytes(pngs[size].read_bytes())
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(output)],
            check=True,
        )


def _build_ico(pngs: dict[int, Path], output: Path) -> None:
    blobs = [(size, pngs[size].read_bytes()) for size in ICO_SIZES]
    header_size = 6 + 16 * len(blobs)
    offset = header_size
    entries: list[bytes] = []
    payloads: list[bytes] = []
    for size, blob in blobs:
        dimension = 0 if size == 256 else size
        entries.append(
            struct.pack(
                "<BBBBHHII",
                dimension,
                dimension,
                0,
                0,
                1,
                32,
                len(blob),
                offset,
            )
        )
        payloads.append(blob)
        offset += len(blob)
    output.write_bytes(
        struct.pack("<HHH", 0, 1, len(blobs)) + b"".join(entries + payloads)
    )


def build(repo_root: Path) -> None:
    icons_dir = repo_root / "photon_cruncher" / "assets" / "icons"
    source = icons_dir / "aurora-options" / "option-c-p-monogram.png"
    png_dir = icons_dir / "png"
    image = _transparent_rounded_tile(source)
    pngs = _save_pngs(image, png_dir)
    if shutil.which("iconutil"):
        _build_icns(pngs, icons_dir / "photon-cruncher-aurora.icns")
    _build_ico(pngs, icons_dir / "photon-cruncher-aurora.ico")

    web_mark = (
        repo_root
        / "photon_cruncher"
        / "gui_aurora"
        / "static"
        / "img"
        / "aurora-mark.png"
    )
    mark = image.scaled(
        256,
        256,
        QtCore.Qt.AspectRatioMode.IgnoreAspectRatio,
        QtCore.Qt.TransformationMode.SmoothTransformation,
    )
    if not mark.save(str(web_mark), "PNG"):
        raise RuntimeError(f"Could not write {web_mark}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    args = parser.parse_args()
    build(args.repo_root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
