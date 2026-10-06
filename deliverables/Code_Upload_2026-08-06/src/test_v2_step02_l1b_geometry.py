#!/usr/bin/env python3
"""Focused tests for the D0035 cloud-independent L1B GEO screen."""

from __future__ import annotations

from pathlib import Path
import tempfile
import zlib

import netCDF4
import numpy as np
import pandas as pd
from pyproj import CRS, Transformer
from scipy.spatial import cKDTree

from urban_cooling_v2.step02_l1b_geometry import (
    ChunkDescriptor,
    TargetGrid,
    boundary_expansion_neighbors,
    build_geometry_validation,
    coalesce_chunk_ranges,
    decode_chunk,
    frozen_geometry_targets,
    initial_chunk_selection,
    map_decoded_chunks_to_targets,
    normalize_geo_records,
    resolve_latest_geo_scenes,
    summarize_geometry_passes,
    write_scene_map_npz,
)
from urban_cooling_v2.step02_cloud_exhaustive import frozen_candidate_passes
from run_v2_step02_l1b_geometry import _locator_constraint, _validate_locator


def _grid(*, city: str = "phoenix", tile: str = "12SVC") -> TargetGrid:
    crs = CRS.from_epsg(32612)
    x, y = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform(
        [-112.0, -111.9995], [33.0, 33.0005]
    )
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    return TargetGrid(city=city, tile=tile, crs=crs, x=x, y=y, tree=cKDTree(np.c_[x, y]))


def test_frozen_targets_use_every_scene_in_a_pass() -> None:
    screened = pd.DataFrame(
        {
            "city": ["a", "a"],
            "orbit": [1, 2],
            "acquisition_utc": ["2020-07-01T00:00:00Z", "2020-07-02T00:00:00Z"],
            "metadata_candidate": [True, True],
        }
    )
    rows = []
    for orbit, scenes in [(1, (3, 4)), (2, (5,))]:
        for scene in scenes:
            stamp = f"2020070{orbit}T000{scene:02d}0"
            granule = f"ECOv002_L2T_LSTE_{orbit:05d}_{scene:03d}_12SVC_{stamp}_0712_01"
            rows.append(
                {
                    "city": "a",
                    "orbit": orbit,
                    "scene": scene,
                    "tile": "12SVC",
                    "granule_id": granule,
                    "asset_type": "view_zenith_cog",
                    "status": "available",
                    "selected_build": 712,
                    "selected_revision": 1,
                    "acquisition_utc": pd.to_datetime(
                        stamp, format="%Y%m%dT%H%M%S", utc=True
                    ),
                }
            )
    candidates, links = frozen_geometry_targets(
        screened,
        pd.DataFrame(rows),
        expected_candidates=2,
        expected_city_scene_links=3,
        expected_unique_scenes=3,
    )
    assert len(candidates) == 2
    assert links.groupby(["city", "orbit"]).size().to_dict() == {("a", 1): 2, ("a", 2): 1}


def test_mixed_iso_timestamps_are_accepted_by_both_frozen_censuses() -> None:
    rows = pd.DataFrame(
        {
            "city": ["a", "a"],
            "orbit": [1, 2],
            "acquisition_utc": [
                "2020-07-01T00:00:00Z",
                "2020-07-02T00:00:00.123456Z",
            ],
            "quality_candidate_pre_cloud": [True, True],
        }
    )
    result = frozen_candidate_passes(rows, expected_candidate_passes=2)
    assert len(result) == 2


def test_latest_geo_identity_never_falls_back_when_latest_lacks_endpoint() -> None:
    def record(build: int, *, complete: bool) -> dict[str, object]:
        granule = f"ECOv002_L1B_GEO_00001_001_20200701T000000_{build:04d}_01"
        urls: list[dict[str, str]] = [
            {
                "Type": "GET DATA",
                "URL": f"https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/x/{granule}.h5",
            }
        ]
        if complete:
            urls.append(
                {
                    "Subtype": "OPENDAP DATA",
                    "URL": f"https://opendap.earthdata.nasa.gov/collections/x/granules/{granule}",
                }
            )
        return {
            "meta": {"revision-id": 1, "concept-id": f"G{build}"},
            "umm": {"GranuleUR": granule, "RelatedUrls": urls},
        }

    records = normalize_geo_records([record(700, complete=True), record(800, complete=False)])
    links = pd.DataFrame(
        {
            "orbit": [1],
            "scene": [1],
            "scene_acquisition_utc": ["2020-07-01T00:00:00Z"],
        }
    )
    resolved = resolve_latest_geo_scenes(links, records, expected_unique_scenes=1)
    assert int(resolved.loc[0, "selected_build"]) == 800
    assert resolved.loc[0, "status"] == "missing_required_endpoint"


def test_stride32_locator_contains_latitude_longitude_only() -> None:
    constraint = _locator_constraint()
    assert "/Geolocation/latitude" in constraint
    assert "/Geolocation/longitude" in constraint
    assert "view_zenith" not in constraint
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "locator.nc4"
        with netCDF4.Dataset(path, "w") as dataset:
            group = dataset.createGroup("Geolocation")
            group.createDimension("rows", 176)
            group.createDimension("cols", 169)
            for name in ("latitude", "longitude"):
                group.createVariable(name, "f8", ("rows", "cols"))
        _validate_locator(path)
        with netCDF4.Dataset(path, "a") as dataset:
            dataset.groups["Geolocation"].createVariable(
                "view_zenith", "f4", ("rows", "cols")
            )
        try:
            _validate_locator(path)
        except ValueError:
            pass
        else:
            raise AssertionError("Locator validation accepted forbidden view_zenith")


def test_chunk_decode_and_range_coalescing() -> None:
    array = np.arange(12, dtype="<f8").reshape(3, 4)
    compressed = zlib.compress(array.tobytes())
    descriptor = ChunkDescriptor(
        variable="latitude",
        dtype=np.dtype("f8"),
        array_shape=(3, 4),
        chunk_shape=(3, 4),
        origin=(0, 0),
        offset=100,
        nbytes=len(compressed),
        compression="deflate",
        byte_order="LE",
        fill_value="0",
    )
    assert np.array_equal(decode_chunk(compressed, descriptor), array)
    second = ChunkDescriptor(**{**descriptor.__dict__, "origin": (0, 4), "offset": 100 + len(compressed)})
    groups = coalesce_chunk_ranges([second, descriptor], max_span_bytes=1_000, max_gap_bytes=0)
    assert len(groups) == 1
    assert groups[0][0] == 100


def test_locator_margin_and_full_resolution_boundary_expansion() -> None:
    grid = _grid()
    locator_lat = np.zeros((4, 4), dtype=float)
    locator_lon = np.zeros((4, 4), dtype=float)
    locator_lat[1, 1] = 33.0
    locator_lon[1, 1] = -112.0
    selected = initial_chunk_selection(
        locator_lat,
        locator_lon,
        {grid.tile: grid},
        chunk_shape=(64, 64),
        array_shape=(128, 128),
        source_margin_pixels=64,
    )
    assert selected == {(0, 0), (0, 1), (1, 0), (1, 1)}

    selected = {(0, 0)}
    lat = np.full((4, 4), 20.0)
    lon = np.full((4, 4), -100.0)
    lat[:, -1] = 33.0
    lon[:, -1] = -112.0
    additions, distance, edges = boundary_expansion_neighbors(
        selected,
        {(0, 0): lat},
        {(0, 0): lon},
        {grid.tile: grid},
        chunk_shape=(4, 4),
        array_shape=(4, 8),
    )
    assert additions == {(0, 1)}
    assert distance <= 210
    assert edges == 1

    # An all-fill edge is never accepted as proof that omitted geometry cannot
    # re-enter the domain in the neighbouring chunk.
    fill_lat = np.full((4, 4), 20.0)
    fill_lon = np.full((4, 4), -100.0)
    fill_lat[:, -1] = 0.0
    fill_lon[:, -1] = 0.0
    additions, _, _ = boundary_expansion_neighbors(
        {(0, 0)},
        {(0, 0): fill_lat},
        {(0, 0): fill_lon},
        {grid.tile: grid},
        chunk_shape=(4, 4),
        array_shape=(4, 8),
    )
    assert additions == {(0, 1)}

    # A current edge at 250 m must expand because an adjacent ~70-90 m source
    # pixel can re-enter the frozen 210 m radius.
    one_grid = TargetGrid(
        city=grid.city,
        tile=grid.tile,
        crs=grid.crs,
        x=grid.x[:1],
        y=grid.y[:1],
        tree=cKDTree(np.c_[grid.x[:1], grid.y[:1]]),
    )
    inverse = Transformer.from_crs(one_grid.crs, "EPSG:4326", always_xy=True)
    lon250, lat250 = inverse.transform(one_grid.x[0] + 250.0, one_grid.y[0])
    guard_lat = np.full((4, 4), 20.0)
    guard_lon = np.full((4, 4), -100.0)
    guard_lat[:, -1] = lat250
    guard_lon[:, -1] = lon250
    additions, distance, _ = boundary_expansion_neighbors(
        {(0, 0)},
        {(0, 0): guard_lat},
        {(0, 0): guard_lon},
        {one_grid.tile: one_grid},
        chunk_shape=(4, 4),
        array_shape=(4, 8),
    )
    assert 240 < distance < 260
    assert additions == {(0, 1)}


def test_full_resolution_mapping_and_pass_overlap_rule() -> None:
    grid = _grid()
    latitude = np.full((2, 2), 33.0)
    longitude = np.array([[-112.0, -111.9995], [-112.0, -111.9995]])
    view = np.array([[10.0, 15.0], [12.0, 18.0]], dtype=np.float32)
    decoded = {
        "latitude": {(0, 0): latitude},
        "longitude": {(0, 0): longitude},
        "view_zenith": {(0, 0): view},
    }
    mapped = map_decoded_chunks_to_targets(
        {(0, 0)},
        decoded,
        {grid.tile: grid},
        chunk_shape=(2, 2),
        array_shape=(2, 2),
    )
    assert len(mapped[grid.tile]["target_index"]) == 2

    with tempfile.TemporaryDirectory() as tmp:
        p1 = Path(tmp) / "scene1.npz"
        p2 = Path(tmp) / "scene2.npz"
        write_scene_map_npz(p1, mapped)
        second = {
            grid.tile: {
                "target_index": np.array([0, 1]),
                "view_zenith_abs_deg": np.array([19.0, 25.0]),
                "source_distance_m": np.array([10.0, 10.0]),
            }
        }
        write_scene_map_npz(p2, second)
        candidates = pd.DataFrame(
            {"city": [grid.city], "orbit": [1], "acquisition_utc": ["2020-07-01T00:00:00Z"]}
        )
        links = pd.DataFrame(
            {
                "city": [grid.city, grid.city],
                "orbit": [1, 1],
                "scene": [1, 2],
                "scene_acquisition_utc": ["2020-07-01T00:00:00Z", "2020-07-01T00:00:52Z"],
            }
        )
        summary = summarize_geometry_passes(
            candidates,
            links,
            {(grid.city, 1, 1): p1, (grid.city, 1, 2): p2},
            {grid.city: {grid.tile: grid}},
            expected_candidates=1,
        )
    row = summary.iloc[0]
    assert row["n_overlapping_valid_pixels"] == 2
    assert row["l1b_view_zenith_abs_p95_deg"] > 20
    assert row["l1b_geometry_status"] == "angle_fail"
    assert not bool(row["quality_candidate_pre_cloud_l1b"])
    validation = build_geometry_validation(summary, expected_candidates=1)
    assert validation["geometry_complete"] is True
    assert validation["geometry_passing_candidate_count"] == 0


def main() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
    print(f"{len(tests)} D0035 L1B geometry tests passed")


if __name__ == "__main__":
    main()
