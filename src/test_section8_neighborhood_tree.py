#!/usr/bin/env python3
"""Self-test for the Section 8 neighborhood + tree pipeline (pure-logic).

Geo/network stack (geopandas, requests, rasterio, shapely, rioxarray, xarray,
earthaccess) is stubbed; the risky pure logic is exercised on synthetic data:
census jam cleaning, %-people-of-colour, GEOID->parent-tract truncation,
functional typing, inventory-year parsing, quadkeys, ACS records, manifest row.
Runs with numpy + pandas:  python src/test_section8_neighborhood_tree.py
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

    # rasterio + submodules used at import time
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
    """Census jam-value cleaning."""
    print("\n[census jam-value cleaning]")
    check(sec8.clean_census_value("-666666666") is None, "-666666666 jam -> None")
    check(sec8.clean_census_value("-999999999") is None, "other large-neg jam -> None")
    check(sec8.clean_census_value("") is None, "blank -> None")
    check(sec8.clean_census_value(None) is None, "None -> None")
    check(sec8.clean_census_value("52345") == 52345.0, "'52345' -> 52345.0")
    check(sec8.clean_census_value("0") == 0.0, "'0' -> 0.0 valid zero")
    check(sec8.clean_census_value("-5") == -5.0, "small neg is not a jam value")


def test_pct_people_of_colour() -> None:
    """%POC = 100*(total - nhWhite)/total with zero/jam/clip handling."""
    print("\n[%-people-of-colour]")
    check(np.isclose(sec8.pct_people_of_colour("1000", "400"), 60.0),
          "total 1000, nhWhite 400 -> 60%")
    check(sec8.pct_people_of_colour("0", "0") is None, "zero total -> None")
    check(sec8.pct_people_of_colour("-666666666", "10") is None, "jam total -> None")
    check(sec8.pct_people_of_colour("100", None) is None, "missing white -> None")
    check(sec8.pct_people_of_colour("100", "120") == 0.0, "white>total clips to 0%")
    check(np.isclose(sec8.pct_people_of_colour("100", "0"), 100.0), "all POC -> 100%")


def test_geoid_and_tract() -> None:
    """BG GEOID composition + parent-tract truncation (SVI inheritance)."""
    print("\n[GEOID composition + parent-tract truncation]")
    g = sec8.block_group_geoid("04", "013", "010102", "1")
    check(g == "040130101021", f"BG GEOID = 12 digits (got {g})")
    check(sec8.tract_geoid_of(g) == "04013010102", "tract = first 11 digits of BG")
    check(len(sec8.tract_geoid_of(g)) == 11, "tract GEOID length 11")
    check(sec8.block_group_geoid("4", "13", "100", "2") == "040130001002",
          "components zero-padded to 2/3/6/1")


def test_functional_type() -> None:
    """Functional typing: water use + leaf habit."""
    print("\n[functional typing]")
    check(sec8.functional_type("Parkinsonia florida") == ("drought_tolerant", "deciduous"),
          "palo verde -> drought_tolerant/deciduous (genus)")
    check(sec8.functional_type("Prosopis velutina") == ("drought_tolerant", "deciduous"),
          "velvet mesquite -> drought_tolerant/deciduous")
    check(sec8.functional_type("Fraxinus velutina") == ("mesic", "deciduous"),
          "Arizona ash -> mesic/deciduous")
    check(sec8.functional_type("Quercus virginiana") == ("mesic", "evergreen"),
          "live oak -> mesic/evergreen (species override)")
    check(sec8.functional_type("Acacia farnesiana") == ("drought_tolerant", "deciduous"),
          "sweet acacia -> drought_tolerant/deciduous (species override)")
    check(sec8.functional_type("Washingtonia robusta") == ("drought_tolerant", "evergreen"),
          "fan palm -> drought_tolerant/evergreen")
    check(sec8.functional_type("Zzz unknownus") == ("unknown", "unknown"),
          "unknown genus -> unknown/unknown")
    check(sec8.functional_type("") == ("unknown", "unknown"), "blank -> unknown")
    check(sec8.functional_type("  PROSOPIS   CHILENSIS ") == ("drought_tolerant", "deciduous"),
          "case/space-insensitive normalization")


def test_inventory_year() -> None:
    """Inventory-year from ArcGIS epoch-ms."""
    print("\n[inventory-year from epoch-ms]")
    check(sec8.inventory_year_from_epoch_ms(1303257600000) == 2011, "1303257600000 ms -> 2011")
    check(sec8.inventory_year_from_epoch_ms(None) is None, "None -> None")
    check(sec8.inventory_year_from_epoch_ms(float("nan")) is None, "NaN -> None")


def test_quadkeys() -> None:
    """Bing quadkeys for the ms-buildings partitioned read."""
    print("\n[Bing quadkeys]")
    check(sec8.tile_xy_to_quadkey(0, 0, 1) == "0", "tile(0,0,z1) -> '0'")
    check(sec8.tile_xy_to_quadkey(1, 0, 1) == "1", "tile(1,0,z1) -> '1'")
    check(sec8.tile_xy_to_quadkey(0, 1, 1) == "2", "tile(0,1,z1) -> '2'")
    check(sec8.tile_xy_to_quadkey(1, 1, 1) == "3", "tile(1,1,z1) -> '3'")
    phx = (-112.55, 33.20, -111.55, 33.92)
    qks = sec8.bbox_quadkeys(phx, 9)
    expected = ["023013311", "023013313", "023102200", "023102201", "023102202", "023102203"]
    check(qks == expected, f"Phoenix bbox -> 6 level-9 quadkeys (got {qks})")
    check(all(len(q) == 9 for q in qks), "all quadkeys 9 digits")


def test_acs_records() -> None:
    """ACS table -> records keyed by header."""
    print("\n[ACS table -> records]")
    header = ["NAME", "B19013_001E", "state", "county", "tract", "block group"]
    rows = [["BG 1", "55000", "04", "013", "010102", "1"]]
    recs = sec8.acs_table_to_records(header, rows)
    check(recs[0]["B19013_001E"] == "55000" and recs[0]["block group"] == "1",
          "records keyed by header")


def test_vintage_contract() -> None:
    """Pinned release metadata, dynamic URLs, and ACS/TIGER mismatch guard."""
    print("\n[ACS5/TIGER vintage contract]")
    check(sec8.ACS5_VINTAGE == 2024 and sec8.TIGER_VINTAGE == 2024,
          "pilot pins matching 2024 ACS5 and TIGER/Line vintages")
    check(sec8.ACS5_PERIOD == "2020-2024", "ACS5 period is explicit (2020-2024)")
    check(sec8.ACS5_RELEASE_DATE == "2026-01-29",
          "ACS5 release date is explicit (2026-01-29)")
    check(sec8.TIGER_RELEASE_DATE == "2024-09-25",
          "TIGER/Line release date is explicit (2024-09-25)")
    check(sec8.TIGER_BOUNDARIES_AS_OF == "2024-01-01",
          "TIGER boundaries-as-of date is explicit (2024-01-01)")

    check(sec8.tiger_bg_filename(2023) == "tl_2023_04_bg.zip",
          "2023 TIGER filename is generated from the requested year")
    check(sec8.tiger_bg_url(2023) ==
          "https://www2.census.gov/geo/tiger/TIGER2023/BG/tl_2023_04_bg.zip",
          "2023 TIGER URL is generated from the requested year")
    check(sec8.tiger_bg_filename(2024) == "tl_2024_04_bg.zip",
          "2024 TIGER filename is generated from the requested year")
    check(sec8.tiger_bg_url(2024) ==
          "https://www2.census.gov/geo/tiger/TIGER2024/BG/tl_2024_04_bg.zip",
          "2024 TIGER URL is generated from the requested year")
    check("2024/acs/acs5" in sec8.acs_request_url(2024, "NAME,B19013_001E"),
          "ACS request URL identifies the 2024 ACS5 dataset")

    matched_ok = True
    try:
        sec8.validate_vintage_pair(2024, 2024, require_pinned=True)
    except ValueError:
        matched_ok = False
    check(matched_ok, "matching pinned vintages are accepted")

    mismatch_rejected = False
    try:
        sec8.validate_vintage_pair(2024, 2023)
    except ValueError as exc:
        mismatch_rejected = "cannot be joined" in str(exc)
    check(mismatch_rejected, "mismatched ACS5/TIGER vintages are rejected")

    unpinned_rejected = False
    try:
        sec8.validate_vintage_pair(2023, 2023, require_pinned=True)
    except ValueError as exc:
        unpinned_rejected = "pinned" in str(exc)
    check(unpinned_rejected, "production guard rejects a matching but unpinned pair")


def test_constants() -> None:
    """Other Section 8 constants."""
    print("\n[other Section 8 constants]")
    check(sec8.STATE_FIPS == "04" and sec8.COUNTY_FIPS == "013", "Maricopa = state 04 county 013")
    check(sec8.INCOME_VAR == "B19013_001E", "income variable B19013_001E")
    check(sec8.POC_TOTAL_VAR == "B03002_001E" and sec8.POC_NHWHITE_VAR == "B03002_003E",
          "POC from B03002_001E - B03002_003E")
    check(sec8.SVI_VALUE_COL == "RPL_THEMES", "SVI overall ranking column")
    check(sec8.TREE_LAYER_ID == 1, "tree FeatureServer layer 1")


def test_manifest_row() -> None:
    """Manifest row for a raw download (schema + checksum prefix)."""
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


def test_vintage_provenance() -> None:
    """Machine-readable provenance carries exact URLs, dates, and matched vintages."""
    print("\n[machine-readable vintage provenance]")
    import hashlib
    import tempfile
    import pandas as pd

    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        names = [
            f"acs5_2024_{sec8.INCOME_VAR}_maricopa_bg.json",
            "acs5_2024_B03002_maricopa_bg.json",
            "tl_2024_04_bg.zip",
        ]
        for name in names:
            (d / name).write_bytes(b"fixture")
        manifest = d / "manifest.csv"
        pd.DataFrame([
            {
                "source": f"fixture source {name}",
                "dataset": "fixture dataset",
                "filename": name,
                "download_date": "2026-06-12",
                "checksum": f"sha256:{hashlib.sha256(b'fixture').hexdigest()}",
            }
            for name in names
        ]).to_csv(manifest, index=False)

        provenance = sec8.build_vintage_provenance(
            raw_dir=d, manifest_csv=manifest)
        check(provenance["vintage_join_guard"]["status"] == "matched",
              "provenance records a matched ACS5/TIGER join")
        check(provenance["acs5"]["resources"][0]["access_date"] == "2026-06-12",
              "ACS access date comes from the manifest")
        check(provenance["tiger_line"]["exact_download_url"] == sec8.tiger_bg_url(2024),
              "provenance stores the exact TIGER download URL")
        check("key=" not in str(provenance).lower(),
              "provenance never serializes a Census API key")


def main() -> int:
    tests = [
        test_clean_census_value,
        test_pct_people_of_colour,
        test_geoid_and_tract,
        test_functional_type,
        test_inventory_year,
        test_quadkeys,
        test_acs_records,
        test_vintage_contract,
        test_constants,
        test_manifest_row,
        test_vintage_provenance,
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
