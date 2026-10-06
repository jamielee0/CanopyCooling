#!/usr/bin/env python3
"""Network-free tests for domain-exact Step-2 quality-layer summaries."""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.coords import BoundingBox
from rasterio.transform import from_origin
from shapely.geometry import box, mapping, shape

from urban_cooling_v2 import step02_raster as quality


def _write_layer(path: Path, values: np.ndarray, *, nodata: float | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=values.shape[0],
        width=values.shape[1],
        count=1,
        dtype=values.dtype,
        crs="EPSG:4326",
        transform=from_origin(0, 4, 1, 1),
        nodata=nodata,
    ) as dataset:
        dataset.write(values, 1)


def _row(
    *,
    granule: str,
    scene: int,
    asset_type: str,
    file_name: str,
    revision: int = 1,
) -> dict[str, object]:
    return {
        "city": "test_city",
        "orbit": 30001,
        "scene": scene,
        "tile": "31NAA",
        "granule_id": granule,
        "asset_type": asset_type,
        "file_name": file_name,
        "selected_build": 700,
        "selected_revision": revision,
    }


def test_latest_product_revision_is_selected_per_scene_tile() -> None:
    rows = pd.DataFrame(
        [
            _row(
                granule="old",
                scene=1,
                asset_type=quality.VIEW_ASSET_TYPE,
                file_name="old.tif",
                revision=1,
            ),
            _row(
                granule="new",
                scene=1,
                asset_type=quality.VIEW_ASSET_TYPE,
                file_name="new.tif",
                revision=2,
            ),
        ]
    )
    selected = quality.select_latest_tile_revisions(rows)
    assert selected["granule_id"].tolist() == ["new"]


def test_adjacent_mgrs_zones_partition_without_area_overlap() -> None:
    domain = mapping(box(-85, 33, -83, 35))
    zone16 = shape(quality.partition_domain_for_mgrs_tile(domain, "16SFB"))
    zone17 = shape(quality.partition_domain_for_mgrs_tile(domain, "17SKS"))
    assert np.isclose(zone16.area + zone17.area, shape(domain).area)
    assert zone16.intersection(zone17).area == 0


def test_buffered_cog_bounds_reduce_to_nonoverlapping_mgrs_core() -> None:
    assert quality.canonical_mgrs_core_bounds(
        BoundingBox(300000, 3590260, 409760, 3700020)
    ) == (300000.0, 3600000.0, 400000.0, 3700000.0)
    assert quality.canonical_mgrs_core_bounds(
        BoundingBox(699960, 3790240, 809720, 3900000)
    ) == (700000.0, 3800000.0, 800000.0, 3900000.0)


def test_view_and_cloud_passes_use_exact_domain_and_conservative_overlap() -> None:
    with tempfile.TemporaryDirectory(prefix="step02-raster-") as temporary:
        root = Path(temporary)
        view1 = np.full((4, 4), 10.0, dtype=np.float32)
        view2 = np.full((4, 4), np.nan, dtype=np.float32)
        view2[0, :] = 30.0
        cloud1 = np.zeros((4, 4), dtype=np.uint8)
        cloud2 = np.full((4, 4), 255, dtype=np.uint8)
        cloud2[0, :] = 1

        files = {
            "g1_view_zenith.tif": view1,
            "g2_view_zenith.tif": view2,
            "g1_cloud.tif": cloud1,
            "g2_cloud.tif": cloud2,
        }
        for name, values in files.items():
            asset_type = (
                quality.VIEW_ASSET_TYPE if "view_zenith" in name else quality.CLOUD_ASSET_TYPE
            )
            _write_layer(
                root / asset_type / name,
                values,
                nodata=np.nan if asset_type == quality.VIEW_ASSET_TYPE else None,
            )

        view_rows = pd.DataFrame(
            [
                _row(
                    granule="g1",
                    scene=1,
                    asset_type=quality.VIEW_ASSET_TYPE,
                    file_name="g1_view_zenith.tif",
                ),
                _row(
                    granule="g2",
                    scene=2,
                    asset_type=quality.VIEW_ASSET_TYPE,
                    file_name="g2_view_zenith.tif",
                ),
            ]
        )
        cloud_rows = pd.DataFrame(
            [
                _row(
                    granule="g1",
                    scene=1,
                    asset_type=quality.CLOUD_ASSET_TYPE,
                    file_name="g1_cloud.tif",
                ),
                _row(
                    granule="g2",
                    scene=2,
                    asset_type=quality.CLOUD_ASSET_TYPE,
                    file_name="g2_cloud.tif",
                ),
            ]
        )
        domain = mapping(box(0, 0, 4, 4))

        view = quality.summarize_view_pass(
            view_rows,
            domain_geometry_wgs84=domain,
            asset_root=root,
        )
        assert view["n_domain_pixels"] == 16
        assert view["n_view_valid_pixels"] == 16
        assert view["n_overlapping_valid_pixels"] == 4
        assert view["view_zenith_abs_p95_deg"] == 30.0
        assert view["near_nadir"] is False

        global_denominator = quality.summarize_view_pass(
            view_rows,
            domain_geometry_wgs84=domain,
            asset_root=root,
            domain_pixel_denominator=32,
        )
        assert global_denominator["n_domain_pixels_in_present_tiles"] == 16
        assert np.isclose(global_denominator["view_valid_fraction"], 0.5)

        cloud = quality.summarize_cloud_pass(
            cloud_rows,
            view_rows,
            domain_geometry_wgs84=domain,
            asset_root=root,
        )
        assert cloud["n_domain_pixels"] == 16
        assert cloud["n_view_valid_pixels"] == 16
        assert cloud["n_clear_pixels"] == 12
        assert cloud["n_cloud_pixels"] == 4
        assert np.isclose(cloud["cloud_survival_fraction_of_domain"], 0.75)


if __name__ == "__main__":
    test_latest_product_revision_is_selected_per_scene_tile()
    test_adjacent_mgrs_zones_partition_without_area_overlap()
    test_buffered_cog_bounds_reduce_to_nonoverlapping_mgrs_core()
    test_view_and_cloud_passes_use_exact_domain_and_conservative_overlap()
    print("v2 Step 2 raster tests passed")
