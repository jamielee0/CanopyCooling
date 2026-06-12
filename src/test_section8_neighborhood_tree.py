#!/usr/bin/env python3
"""Self-test for the Section 8 neighborhood + tree pipeline (pure-logic).

Mirrors test_section2-7_*: the geo / network stack (geopandas, requests, rasterio,
shapely, rioxarray, xarray, earthaccess) is stubbed so the module imports without
it, then the algorithmically risky pure logic is exercised on synthetic data:

  * Census jam-value cleaning (-666666666 -> None; blanks -> None; valid floats)
  * %-people-of-colour = 100*(total - non-Hispanic-White)/total, with zero/jam/clip
  * block-group GEOID composition and the GEOID -> parent-tract (first 11) truncation
    that drives the tract-to-block-group SVI inheritance (step 43)
  * functional typing (species override, genus default, unknown) -- the PRIMARY
    descriptor for the tree inventory (step 44)
  * inventory-year parsing from ArcGIS epoch-milliseconds
  * the manifest row built for a raw download (schema + checksum prefix)

The HTTP downloads, ArcGIS paging, STAC/fallback footprints, geopandas joins,
rasterize and matplotlib glue are standard library usage exercised by the real CLI
in the canopy environment.

Runs with just numpy + pandas:  python src/test_section8_neighborhood_tree.py
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import numpy as np


def _install_stubs() -> None:
    """Stub heavy top-level imports so the module imports with only numpy+pandas."""
    for name in ("earthaccess", "rioxarray", "xarray", "geopandas", "requests"):
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
    if not hasattr(sys.modules["xarray"], "DataArray"):
        sys.modules["xarray"].DataArray = object  # type: ignore[attr-defined]
        sys.modules["xarray"].Dataset = object     # type: ignore[attr-defined]
    sys.modules["geopandas"].GeoDataFrame = object  # type: ignore[attr-defined]
    sys.modules["geopandas"].read_file = lambda *a, **k: None  # type: ignore[attr-defined]
    sys.modules["geopandas"].read_parquet = lambda *a, **k: None  # type: ignore[attr-defined]
    sys.modules["requests"].Session = object  # type: ignore[attr-defined]

    # rasterio + submodules used at import time (features, transform.Affine, enums)
    if "rasterio" not in sys.modules:
        sys.modules["rasterio"] = types.ModuleType("rasterio")
    feats = types.ModuleType("rasterio.features")
    feats.rasterize = lambda *a, **k: None
    sys.modules["rasterio.features"] = feats
    sys.modules["rasterio"].features = feats  # type: ignore[attr-defined]
    trans = types.ModuleType("rasterio.transform")
    trans.Affine = lambda *a, **k: a
    sys.modules["rasterio.transform"] = trans
    sys.modules["rasterio"].transform = trans  # type: ignore[attr-defined]
    if "rasterio.enums" not in sys.modules:
        enums = types.ModuleType("rasterio.enums")

        class _Resampling:
            bilinear = "bilinear"; nearest = "nearest"; average = "average"

        enums.Resampling = _Resampling
        sys.modules["rasterio.enums"] = enums
        sys.modules["rasterio"].enums = enums  # type: ignore[attr-defined]

    # shapely.geometry.box
    if "shapely" not in sys.modules:
        sys.modules["shapely"] = types.ModuleType("shapely")
    geom = types.ModuleType("shapely.geometry")
    geom.box = lambda *a, **k: None
    sys.modules["shapely.geometry"] = geom
    sys.modules["shapely"].geometry = geom  # type: ignore[attr-defined]


_install_stubs()

sys.path.insert(0, str(Path(__file__).resolve().parent))
sec8 = importlib.import_module("section8_neighborhood_tree")


_FAILURES: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        _FAILURES.append(msg)
        print(f"  FAIL: {msg}")
    else:
        print(f"  ok:   {msg}")


def test_clean_census_value() -> None:
    print("\n[census jam-value cleaning]")
    check(sec8.clean_census_value("-666666666") is None, "-666666666 jam value -> None")
    check(sec8.clean_census_value("-999999999") is None, "other large-negative jam -> None")
    check(sec8.clean_census_value("") is None, "blank -> None")
    check(sec8.clean_census_value(None) is None, "None -> None")
    check(sec8.clean_census_value("52345") == 52345.0, "'52345' -> 52345.0")
    check(sec8.clean_census_value("0") == 0.0, "'0' -> 0.0 (valid zero)")
    check(sec8.clean_census_value("-5") == -5.0, "small negative is NOT a jam value")


def test_pct_people_of_colour() -> None:
    print("\n[%-people-of-colour]")
    # total 1000, non-Hispanic White alone 400 -> 60% POC
    check(np.isclose(sec8.pct_people_of_colour("1000", "400"), 60.0),
          "total 1000, nhWhite 400 -> 60% POC")
    check(sec8.pct_people_of_colour("0", "0") is None, "zero total -> None")
    check(sec8.pct_people_of_colour("-666666666", "10") is None, "jam total -> None")
    check(sec8.pct_people_of_colour("100", None) is None, "missing white -> None")
    # white > total (shouldn't happen) clips to 0, not negative
    check(sec8.pct_people_of_colour("100", "120") == 0.0, "white>total clips to 0%")
    check(np.isclose(sec8.pct_people_of_colour("100", "0"), 100.0), "all POC -> 100%")


def test_geoid_and_tract() -> None:
    print("\n[GEOID composition + parent-tract truncation (SVI inheritance)]")
    g = sec8.block_group_geoid("04", "013", "010102", "1")
    check(g == "040130101021", f"BG GEOID = 12 digits (got {g})")
    check(sec8.tract_geoid_of(g) == "04013010102", "tract GEOID = first 11 digits of BG")
    check(len(sec8.tract_geoid_of(g)) == 11, "tract GEOID length 11")
    # leading-zero / short component padding
    check(sec8.block_group_geoid("4", "13", "100", "2") == "040130001002",
          "components zero-padded to 2/3/6/1")


def test_functional_type() -> None:
    print("\n[functional typing: water use + leaf habit]")
    check(sec8.functional_type("Parkinsonia florida") == ("drought_tolerant", "deciduous"),
          "palo verde -> drought_tolerant/deciduous (genus rule)")
    check(sec8.functional_type("Prosopis velutina") == ("drought_tolerant", "deciduous"),
          "velvet mesquite -> drought_tolerant/deciduous")
    check(sec8.functional_type("Fraxinus velutina") == ("mesic", "deciduous"),
          "Arizona ash -> mesic/deciduous")
    check(sec8.functional_type("Quercus virginiana") == ("mesic", "evergreen"),
          "southern live oak -> mesic/evergreen (species override)")
    check(sec8.functional_type("Acacia farnesiana") == ("drought_tolerant", "deciduous"),
          "sweet acacia -> drought_tolerant/deciduous (species override vs genus evergreen)")
    check(sec8.functional_type("Washingtonia robusta") == ("drought_tolerant", "evergreen"),
          "Mexican fan palm -> drought_tolerant/evergreen")
    check(sec8.functional_type("Zzz unknownus") == ("unknown", "unknown"),
          "unknown genus -> unknown/unknown")
    check(sec8.functional_type("") == ("unknown", "unknown"), "blank species -> unknown")
    check(sec8.functional_type("  PROSOPIS   CHILENSIS ") == ("drought_tolerant", "deciduous"),
          "case/space-insensitive normalization")


def test_inventory_year() -> None:
    print("\n[inventory-year from epoch-ms]")
    # 1303257600000 ms = 2011-04-20 UTC
    check(sec8.inventory_year_from_epoch_ms(1303257600000) == 2011, "1303257600000 ms -> 2011")
    check(sec8.inventory_year_from_epoch_ms(None) is None, "None -> None")
    check(sec8.inventory_year_from_epoch_ms(float("nan")) is None, "NaN -> None")


def test_quadkeys() -> None:
    print("\n[Bing quadkeys for the ms-buildings partitioned read]")
    # canonical single-tile quadkey digits at zoom 1
    check(sec8.tile_xy_to_quadkey(0, 0, 1) == "0", "tile(0,0,z1) -> '0'")
    check(sec8.tile_xy_to_quadkey(1, 0, 1) == "1", "tile(1,0,z1) -> '1'")
    check(sec8.tile_xy_to_quadkey(0, 1, 1) == "2", "tile(0,1,z1) -> '2'")
    check(sec8.tile_xy_to_quadkey(1, 1, 1) == "3", "tile(1,1,z1) -> '3'")
    # the study bbox -> the level-9 quadkeys verified live against the PC dataset
    phx = (-112.55, 33.20, -111.55, 33.92)
    qks = sec8.bbox_quadkeys(phx, 9)
    expected = ["023013311", "023013313", "023102200", "023102201", "023102202", "023102203"]
    check(qks == expected, f"Phoenix bbox -> 6 level-9 quadkeys (got {qks})")
    check(all(len(q) == 9 for q in qks), "all quadkeys are 9 digits (level 9)")


def test_acs_records() -> None:
    print("\n[ACS table -> records]")
    header = ["NAME", "B19013_001E", "state", "county", "tract", "block group"]
    rows = [["BG 1", "55000", "04", "013", "010102", "1"]]
    recs = sec8.acs_table_to_records(header, rows)
    check(recs[0]["B19013_001E"] == "55000" and recs[0]["block group"] == "1",
          "records keyed by header")


def test_constants() -> None:
    print("\n[Section 8 constants]")
    check(sec8.STATE_FIPS == "04" and sec8.COUNTY_FIPS == "013", "Maricopa = state 04 county 013")
    check(sec8.INCOME_VAR == "B19013_001E", "income variable B19013_001E")
    check(sec8.POC_TOTAL_VAR == "B03002_001E" and sec8.POC_NHWHITE_VAR == "B03002_003E",
          "POC from B03002_001E - B03002_003E")
    check(sec8.SVI_VALUE_COL == "RPL_THEMES", "SVI overall ranking column")
    check(sec8.TREE_LAYER_ID == 1, "tree FeatureServer layer 1 (master point layer)")


def test_manifest_row() -> None:
    print("\n[manifest row for a raw download]")
    import tempfile
    import pandas as pd
    import section2_ecostress_lst as sec2

    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        raw = d / "acs5_2024_B03002_maricopa_bg.json"
        raw.write_text('[["x"]]', encoding="utf-8")
        manifest = d / "manifest.csv"
        sec2.append_to_manifest([{
            "source": "US Census Bureau ACS 5-year 2024",
            "dataset": "acs/acs5/2024",
            "filename": raw.name,
            "download_date": "2026-06-12",
            "checksum": f"sha256:{sec2.sha256_file(raw)}",
        }], manifest_csv=manifest)
        df = pd.read_csv(manifest)
        check(list(df.columns) == ["source", "dataset", "filename", "download_date", "checksum"],
              "manifest schema matches Section 0")
        check(str(df.iloc[0]["checksum"]).startswith("sha256:"), "sha256 checksum prefix")


def main() -> int:
    tests = [
        test_clean_census_value,
        test_pct_people_of_colour,
        test_geoid_and_tract,
        test_functional_type,
        test_inventory_year,
        test_quadkeys,
        test_acs_records,
        test_constants,
        test_manifest_row,
    ]
    print("=" * 64)
    print("Section 8 pure-logic self-test")
    print("=" * 64)
    for t in tests:
        t()
    print("\n" + "=" * 64)
    if _FAILURES:
        print(f"{len(_FAILURES)} CHECK(S) FAILED:")
        for f in _FAILURES:
            print(f"  - {f}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
