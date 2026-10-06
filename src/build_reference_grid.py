#!/usr/bin/env python3
"""Section 1 / build_reference_grid — materialise the fixed reference grid as a GeoTIFF.

Inputs : config.py grid literals (CRS, GRID_TRANSFORM, GRID_NROWS/NCOLS, GRID_ORIGIN_XY).
Outputs: data/processed/reference_grid.tif (single-band uint8, all zeros) — the
         geometric anchor every later layer is reprojected/resampled to match.
Key decisions (full rationale in docs/DESIGN_DECISIONS.md, Section 1):
  - Geometry is not recomputed; literals from config.py are only materialised + verified.
  - 70 m EPSG:32612 cells with a frozen origin/extent (asserted exactly square).
  - rasterio backend when available, else a dependency-free pure-Python TIFF writer.
Run: python src/build_reference_grid.py
"""

from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402


def _epsg_int(crs: str) -> int:
    return int(crs.split(":")[1])


def _derived_bounds() -> tuple[float, float, float, float]:
    """Re-derive bounds from origin + shape + cell size for cross-checking."""
    left, top = config.GRID_ORIGIN_XY
    right = left + config.GRID_NCOLS * config.CELL_SIZE_M
    bottom = top - config.GRID_NROWS * config.CELL_SIZE_M
    return (left, bottom, right, top)


def _write_geotiff_pure(path: str) -> None:
    """Dependency-free classic-TIFF (GeoTIFF) writer: single band, uint8, all zeros."""
    ncols, nrows = config.GRID_NCOLS, config.GRID_NROWS
    a, _b, c, _d, e, f = config.GRID_TRANSFORM  # (xres,0,left,0,-yres,top)
    xres, yres = a, -e
    left, top = c, f
    epsg = _epsg_int(config.CRS)

    # IFD geometry: 14 tags sorted ascending; offsets chained after the IFD block.
    n_tags = 14
    ifd_end = 8 + (2 + 12 * n_tags + 4)        # header + IFD block
    off_ps = ifd_end                            # ModelPixelScale (3 doubles)
    off_tp = off_ps + 24                        # ModelTiepoint  (6 doubles)
    off_gk = off_tp + 48                        # GeoKeyDirectory (20 shorts)
    image_off = off_gk + 40
    strip_bytes = ncols * nrows

    def short_inline(v: int) -> bytes:
        return struct.pack("<H", v) + b"\x00\x00"

    def long_inline(v: int) -> bytes:
        return struct.pack("<I", v)

    # (tag, type, count, value_field) — type: 2=ASCII,3=SHORT,4=LONG,12=DOUBLE
    entries = [
        (256, 4, 1, long_inline(ncols)),        # ImageWidth
        (257, 4, 1, long_inline(nrows)),        # ImageLength
        (258, 3, 1, short_inline(8)),           # BitsPerSample
        (259, 3, 1, short_inline(1)),           # Compression = none
        (262, 3, 1, short_inline(1)),           # Photometric = BlackIsZero
        (273, 4, 1, long_inline(image_off)),    # StripOffsets
        (277, 3, 1, short_inline(1)),           # SamplesPerPixel
        (278, 4, 1, long_inline(nrows)),        # RowsPerStrip (single strip)
        (279, 4, 1, long_inline(strip_bytes)),  # StripByteCounts
        (339, 3, 1, short_inline(1)),           # SampleFormat = uint
        (33550, 12, 3, long_inline(off_ps)),    # ModelPixelScaleTag
        (33922, 12, 6, long_inline(off_tp)),    # ModelTiepointTag
        (34735, 3, 20, long_inline(off_gk)),    # GeoKeyDirectoryTag
        (42113, 2, 2, b"0\x00\x00\x00"),        # GDAL_NODATA = "0"
    ]
    assert len(entries) == n_tags

    out = bytearray()
    out += b"II" + struct.pack("<H", 42) + struct.pack("<I", 8)   # header
    out += struct.pack("<H", n_tags)
    for tag, typ, count, val in entries:
        out += struct.pack("<HHI", tag, typ, count) + val
    out += struct.pack("<I", 0)                                   # next IFD = 0
    out += struct.pack("<3d", xres, yres, 0.0)                    # pixel scale
    out += struct.pack("<6d", 0.0, 0.0, 0.0, left, top, 0.0)      # tiepoint
    geokeys = [
        1, 1, 0, 4,            # dir version, key rev, minor rev, num keys
        1024, 0, 1, 1,         # GTModelType = Projected
        1025, 0, 1, 1,         # GTRasterType = PixelIsArea
        3072, 0, 1, epsg,      # ProjectedCSType = EPSG
        3076, 0, 1, 9001,      # ProjLinearUnits = metre
    ]
    out += struct.pack("<20H", *geokeys)
    out += b"\x00" * strip_bytes                                  # empty band

    with open(path, "wb") as fh:
        fh.write(out)


def _write_geotiff_rasterio(path: str) -> None:
    """Write the reference grid via rasterio (preferred when the library is present)."""
    import numpy as np
    import rasterio
    from rasterio.transform import Affine

    transform = Affine(*config.GRID_TRANSFORM)
    profile = dict(
        driver="GTiff",
        height=config.GRID_NROWS,
        width=config.GRID_NCOLS,
        count=1,
        dtype="uint8",
        crs=config.CRS,
        transform=transform,
        nodata=0,
        compress="deflate",
        tiled=False,
    )
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(np.zeros((config.GRID_NROWS, config.GRID_NCOLS), "uint8"), 1)


def build() -> str:
    """Write reference_grid.tif via rasterio, falling back to the pure-Python writer."""
    config.ensure_dirs()
    path = str(config.REFERENCE_GRID_TIF)
    try:
        import rasterio  # noqa: F401

        _write_geotiff_rasterio(path)
        backend = "rasterio"
    except Exception:
        _write_geotiff_pure(path)
        backend = "pure-python"
    print(f"Wrote reference grid via {backend}: {path}")
    return path


def _read_back(path: str) -> dict:
    """Re-read the written file's georeferencing straight from the raw TIFF bytes."""
    with open(path, "rb") as fh:
        data = fh.read()
    assert data[:2] == b"II" and struct.unpack("<H", data[2:4])[0] == 42
    ifd_off = struct.unpack("<I", data[4:8])[0]
    n = struct.unpack("<H", data[ifd_off:ifd_off + 2])[0]
    tags = {}
    for i in range(n):
        o = ifd_off + 2 + i * 12
        tag, typ, count = struct.unpack("<HHI", data[o:o + 8])
        tags[tag] = (typ, count, data[o + 8:o + 12])

    def deref_doubles(tag):
        _typ, count, val = tags[tag]
        off = struct.unpack("<I", val)[0]
        return struct.unpack("<%dd" % count, data[off:off + 8 * count])

    width = struct.unpack("<I", tags[256][2])[0]
    length = struct.unpack("<I", tags[257][2])[0]
    ps = deref_doubles(33550)
    tp = deref_doubles(33922)
    return {"width": width, "length": length, "pixel_scale": ps, "tiepoint": tp}


def main() -> int:
    """Build the grid, print its geometry, and assert cells are exactly 70 m square."""
    path = build()

    left, bottom, right, top = _derived_bounds()
    assert (left, bottom, right, top) == config.GRID_BOUNDS, (
        "origin/shape disagree with GRID_BOUNDS literal"
    )

    print("\n--- Reference grid geometry ---")
    print(f"CRS        : {config.CRS}")
    print(f"cell size  : {config.CELL_SIZE_M} m x {config.CELL_SIZE_M} m")
    print(f"shape      : {config.GRID_SHAPE}  (rows, cols)")
    print(f"origin (TL): {config.GRID_ORIGIN_XY}")
    print(f"bounds     : left={left:.1f} bottom={bottom:.1f} "
          f"right={right:.1f} top={top:.1f}")

    # Assert cells are EXACTLY 70 m square, from config and from the file bytes.
    a, _b, _c, _d, e, _f = config.GRID_TRANSFORM
    assert a == float(config.CELL_SIZE_M), "x cell size != 70 m"
    assert -e == float(config.CELL_SIZE_M), "y cell size != 70 m"
    assert a == -e, "cells are not square"

    rb = _read_back(path)
    assert rb["width"] == config.GRID_NCOLS, "written width mismatch"
    assert rb["length"] == config.GRID_NROWS, "written height mismatch"
    assert rb["pixel_scale"][0] == 70.0 and rb["pixel_scale"][1] == 70.0, (
        "written pixel scale is not 70 m square"
    )
    assert rb["tiepoint"][3] == left and rb["tiepoint"][4] == top, (
        "written tiepoint does not match grid origin"
    )
    size = os.path.getsize(path)
    print(f"verified   : file georeferencing OK ({size:,} bytes on disk)")
    print("ASSERT OK  : cells are exactly 70 m square.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
