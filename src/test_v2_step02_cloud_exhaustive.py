#!/usr/bin/env python3
"""Network-free tests for the D0033 exhaustive Step-2 cloud audit."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box, mapping

from urban_cooling_v2.step02_cloud_exhaustive import (
    DECISION_ID,
    TARGET_SCOPE,
    build_exhaustive_cloud_manifest,
    build_exhaustive_validation,
    frozen_candidate_passes,
    load_cached_l2t_results,
    run_cloud_view_dependency_audit,
)


OFFICIAL_ROOT = "https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected"
FIRST = "ECOv002_L2T_LSTE_28527_009_13TDE_20230718T081442_0710_01"
SECOND = "ECOv002_L2T_LSTE_28528_010_13TDE_20230719T081442_0710_01"
EXTRA = "ECOv002_L2T_LSTE_28529_011_13TDE_20230720T081442_0710_01"


def _url(product: str, suffix: str) -> str:
    return f"{OFFICIAL_ROOT}/ECO_L2T_LSTE.002/{product}/{product}{suffix}"


def _cmr_result(product: str, *, include_cloud: bool = True) -> dict:
    urls = [_url(product, "_view_zenith.tif")]
    if include_cloud:
        urls.append(_url(product, "_cloud.tif"))
    return {"umm": {"RelatedUrls": [{"URL": value} for value in urls]}}


def _screened() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "city": "phoenix",
                "orbit": 28527,
                "acquisition_utc": "2023-07-18T08:14:42Z",
                "quality_candidate_pre_cloud": True,
                "n_domain_pixels": 100,
                "n_view_valid_pixels": 99,
            },
            {
                "city": "miami",
                "orbit": 28528,
                "acquisition_utc": "2023-07-19T08:14:42Z",
                "quality_candidate_pre_cloud": True,
                "n_domain_pixels": 200,
                "n_view_valid_pixels": 196,
            },
            {
                "city": "atlanta",
                "orbit": 28529,
                "acquisition_utc": "2023-07-20T08:14:42Z",
                "quality_candidate_pre_cloud": False,
                "n_domain_pixels": 150,
                "n_view_valid_pixels": 149,
            },
        ]
    )


def _view_row(city: str, orbit: int, scene: int, product: str) -> dict:
    return {
        "city": city,
        "granule_id": product,
        "orbit": orbit,
        "scene": scene,
        "tile": "13TDE",
        "item_id": f"view-{city}",
        "asset_type": "view_zenith_cog",
        "status": "available",
        "selection_rule": "exact_l2t_granule",
        "selected_product_id": product,
        "selected_build": 710,
        "selected_revision": 1,
        "file_name": f"{product}_view_zenith.tif",
        "source_url": _url(product, "_view_zenith.tif"),
        "year": 2023,
        "month": 7,
        "acquisition_utc": product.split("_")[6],
    }


def _views() -> pd.DataFrame:
    return pd.DataFrame(
        [
            _view_row("phoenix", 28527, 9, FIRST),
            _view_row("miami", 28528, 10, SECOND),
            _view_row("atlanta", 28529, 11, EXTRA),
        ]
    )


def _summary() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "city": "phoenix",
                "orbit": 28527,
                "n_domain_pixels": 100,
                "n_view_valid_pixels": 99,
                "n_clear_pixels": 40,
                "cloud_survival_fraction_of_domain": 0.4,
                "cloud_asset_complete": True,
                "view_asset_complete": True,
                "provenance_complete": True,
            },
            {
                "city": "miami",
                "orbit": 28528,
                "n_domain_pixels": 200,
                "n_view_valid_pixels": 196,
                "n_clear_pixels": 140,
                "cloud_survival_fraction_of_domain": 0.7,
                "cloud_asset_complete": True,
                "view_asset_complete": True,
                "provenance_complete": True,
            },
        ]
    )


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


class ExhaustiveCloudTests(unittest.TestCase):
    def test_manifest_targets_every_pre_cloud_candidate_and_only_cloud(self) -> None:
        manifest = build_exhaustive_cloud_manifest(
            _screened(),
            _views(),
            l2t_results=[_cmr_result(FIRST), _cmr_result(SECOND), _cmr_result(EXTRA)],
            expected_candidate_passes=2,
        )
        self.assertEqual(len(manifest), 2)
        self.assertEqual(set(manifest["city"]), {"phoenix", "miami"})
        self.assertEqual(set(manifest["asset_type"]), {"cloud_cog"})
        self.assertTrue(manifest["status"].eq("available").all())
        self.assertTrue(manifest["cloud_target_selected_before_outcome"].all())
        self.assertEqual(set(manifest["decision_id"]), {DECISION_ID})
        self.assertEqual(set(manifest["target_scope"]), {TARGET_SCOPE})
        self.assertTrue(manifest["file_name"].str.endswith("_cloud.tif").all())
        self.assertTrue(
            manifest["selected_build"].eq(manifest["view_selected_build"]).all()
        )
        self.assertNotIn("atlanta", set(manifest["city"]))

    def test_missing_official_cloud_asset_fails_closed_with_exact_count(self) -> None:
        with self.assertRaisesRegex(ValueError, "1 exhaustive cloud assets are unresolved"):
            build_exhaustive_cloud_manifest(
                _screened(),
                _views(),
                l2t_results=[
                    _cmr_result(FIRST),
                    _cmr_result(SECOND, include_cloud=False),
                ],
                expected_candidate_passes=2,
            )

    def test_unavailable_candidate_view_granule_fails_closed(self) -> None:
        views = _views()
        unavailable = views.iloc[0].copy()
        unavailable["scene"] = 10
        unavailable["granule_id"] = "candidate-second-granule"
        unavailable["item_id"] = "view-unavailable"
        unavailable["status"] = "missing"
        views = pd.concat([views, unavailable.to_frame().T], ignore_index=True)
        with self.assertRaisesRegex(ValueError, "1 candidate view assets are not available"):
            build_exhaustive_cloud_manifest(
                _screened(),
                views,
                l2t_results=[_cmr_result(FIRST), _cmr_result(SECOND)],
                expected_candidate_passes=2,
            )

    def test_candidate_seal_rejects_2026_before_cloud_values(self) -> None:
        screened = _screened()
        screened.loc[0, "acquisition_utc"] = "2026-07-18T08:14:42Z"
        with self.assertRaisesRegex(ValueError, "frozen 2018-2025"):
            frozen_candidate_passes(screened, expected_candidate_passes=2)

    def test_complete_validation_reports_sum_and_conservative_floor(self) -> None:
        validation = build_exhaustive_validation(
            _summary(), screened_passes=_screened(), expected_candidate_passes=2
        )
        self.assertEqual(validation["decision_id"], DECISION_ID)
        self.assertEqual(validation["expected_candidate_passes"], 2)
        self.assertEqual(validation["resolved_candidate_passes"], 2)
        self.assertEqual(validation["finite_survival_passes"], 2)
        self.assertTrue(validation["complete"])
        self.assertAlmostEqual(
            validation["sum_cloud_survival_fraction_of_domain"], 1.1
        )
        self.assertEqual(validation["conservative_planning_floor"], 1)
        self.assertFalse(validation["cloud_extrapolation_used"])
        self.assertFalse(validation["lst_opened"])
        self.assertEqual(validation["holdout_status"], "UNSELECTED")
        self.assertFalse(validation["scientific_gate_eligible"])

    def test_missing_candidate_makes_validation_incomplete(self) -> None:
        validation = build_exhaustive_validation(
            _summary().iloc[:1],
            screened_passes=_screened(),
            expected_candidate_passes=2,
        )
        self.assertEqual(validation["resolved_candidate_passes"], 1)
        self.assertEqual(validation["finite_survival_passes"], 1)
        self.assertFalse(validation["candidate_keys_exact"])
        self.assertFalse(validation["complete"])

    def test_cache_reader_rejects_any_2026_query(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cloud-cache-seal-") as temporary:
            path = Path(temporary) / "phoenix" / "2026.json"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(
                    {
                        "query": {
                            "temporal": [
                                "2026-06-01T00:00:00Z",
                                "2026-09-30T23:59:59Z",
                            ]
                        },
                        "results": [],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "Out-of-window"):
                load_cached_l2t_results(Path(temporary))

    def test_dependency_diagnostic_finds_cloud_conditioned_view_mask(self) -> None:
        screened = pd.DataFrame(
            [
                {
                    "city": "test_city",
                    "orbit": 30001,
                    "acquisition_utc": "2023-07-18T08:14:42Z",
                    "quality_candidate_pre_cloud": True,
                    "n_domain_pixels": 16,
                    "n_view_valid_pixels": 12,
                }
            ]
        )
        identity = {
            "city": "test_city",
            "orbit": 30001,
            "scene": 1,
            "tile": "31NAA",
            "granule_id": "g1",
            "selected_build": 700,
            "selected_revision": 1,
            "status": "available",
        }
        cloud_manifest = pd.DataFrame(
            [
                {
                    **identity,
                    "item_id": "cloud-g1",
                    "asset_type": "cloud_cog",
                    "file_name": "g1_cloud.tif",
                }
            ]
        )
        view_manifest = pd.DataFrame(
            [
                {
                    **identity,
                    "item_id": "view-g1",
                    "asset_type": "view_zenith_cog",
                    "file_name": "g1_view_zenith.tif",
                }
            ]
        )
        with tempfile.TemporaryDirectory(prefix="cloud-view-dependency-") as temporary:
            root = Path(temporary)
            cloud = np.zeros((4, 4), dtype=np.uint8)
            cloud[0, :] = 1
            view = np.full((4, 4), 10.0, dtype=np.float32)
            view[0, :] = np.nan
            _write_layer(root / "cloud_cog/g1_cloud.tif", cloud, nodata=None)
            _write_layer(
                root / "view_zenith_cog/g1_view_zenith.tif",
                view,
                nodata=np.nan,
            )
            pair, independent = run_cloud_view_dependency_audit(
                screened,
                cloud_manifest,
                view_manifest,
                domain_geometries_wgs84={"test_city": mapping(box(0, 0, 4, 4))},
                asset_root=root,
                expected_candidate_passes=1,
            )
        self.assertEqual(len(pair), 1)
        self.assertEqual(pair.loc[0, "n_cloud_pixels_independent_of_view"], 4)
        self.assertEqual(pair.loc[0, "n_view_valid_and_cloud_pixels"], 0)
        self.assertTrue(pair.loc[0, "cloudy_and_view_valid_are_disjoint"])
        self.assertEqual(
            independent.loc[0, "n_clear_pixels_independent_of_view"], 12
        )
        self.assertEqual(
            independent.loc[0, "n_cloud_pixels_independent_of_view"], 4
        )

        mechanical = pd.DataFrame(
            [
                {
                    "city": "test_city",
                    "orbit": 30001,
                    "n_domain_pixels": 16,
                    "n_view_valid_pixels": 12,
                    "n_clear_pixels": 12,
                    "cloud_survival_fraction_of_domain": 0.75,
                    "cloud_asset_complete": True,
                    "view_asset_complete": True,
                    "provenance_complete": True,
                }
            ]
        )
        validation = build_exhaustive_validation(
            mechanical,
            screened_passes=screened,
            cloud_view_dependency_diagnostic=pair,
            independent_cloud_pass_summary=independent,
            expected_cloud_view_layer_pairs=1,
            expected_candidate_passes=1,
        )
        self.assertTrue(validation["complete"])
        self.assertTrue(validation["view_gate_cloud_conditioned"])
        self.assertFalse(validation["candidate_seal_geometry_only"])
        self.assertFalse(validation["scientific_gate_eligible"])
        self.assertEqual(
            validation["gate_status"], "STOP_CLOUD_CONDITIONED_VIEW_GATE"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
