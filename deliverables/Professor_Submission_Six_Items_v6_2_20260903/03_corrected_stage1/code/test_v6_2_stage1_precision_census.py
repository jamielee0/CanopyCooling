#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import numpy as np

from urban_cooling_v2.stage1_precision_census import (
    build_power_rows,
    build_quality_mask,
    discover_latest_complete_bundles,
    fit_block_pass,
    free_check_ruling,
    merge_scene_arrays,
    required_count,
)


def test_quality_and_cloudy_wins() -> None:
    lst = np.array([[300.0, 301.0], [302.0, np.nan]])
    qc = np.array([[0, 1], [2, 0]], dtype=np.uint16)
    cloud = np.array([[0, 0], [0, 0]], dtype=np.uint8)
    water = np.zeros((2, 2), dtype=np.uint8)
    assert build_quality_mask(lst, qc, cloud, water).tolist() == [
        [True, True],
        [False, False],
    ]

    first = {"LST": lst, "QC": qc, "cloud": cloud, "water": water, "height": np.ones((2, 2))}
    second = {
        "LST": np.array([[303.0, 304.0], [305.0, 306.0]]),
        "QC": np.zeros((2, 2), dtype=np.uint16),
        "cloud": np.array([[1, 0], [0, 0]], dtype=np.uint8),
        "water": np.zeros((2, 2), dtype=np.uint8),
        "height": np.ones((2, 2)) * 2,
    }
    merged, height, valid = merge_scene_arrays([first, second])
    assert not valid[0, 0]
    assert np.isnan(merged[0, 0])
    assert merged[0, 1] == 304.0
    assert height[0, 1] == 2.0


def test_latest_complete_bundle_selection() -> None:
    with tempfile.TemporaryDirectory() as directory:
        tmp_path = Path(directory)
        base = "ECOv002_L2T_LSTE_27963_013_12SUB_20230611T233953"
        for build, revision in ((710, 1), (712, 2)):
            for layer in ("LST", "QC", "cloud", "water", "height"):
                (tmp_path / f"{base}_{build:04d}_{revision:02d}_{layer}.tif").touch()
        incomplete = "ECOv002_L2T_LSTE_27963_013_12SUC_20230611T233953_0713_01"
        for layer in ("LST", "QC", "cloud", "water"):
            (tmp_path / f"{incomplete}_{layer}.tif").touch()
        bundles = discover_latest_complete_bundles(tmp_path, [27963])
        assert len(bundles) == 1
        assert bundles[0].build == 712
        assert bundles[0].revision == 2


def test_one_slope_per_block_pass_and_spatial_jackknife() -> None:
    rng = np.random.default_rng(6202)
    axis = np.arange(35.0, 1000.0, 70.0)
    xs, ys = np.meshgrid(axis, axis)
    x = xs.ravel()
    y = ys.ravel()
    canopy = np.clip((x - x.min()) / (x.max() - x.min()), 0, 1)
    impervious = np.clip(1 - canopy + rng.normal(0, 0.05, len(x)), 0, 1)
    lowveg = np.clip(0.4 * canopy + rng.normal(0, 0.05, len(x)), 0, 1)
    bare = np.clip(0.3 * impervious + rng.normal(0, 0.04, len(x)), 0, 1)
    building = np.clip(0.2 * impervious + rng.normal(0, 0.03, len(x)), 0, 1)
    elevation = 300 + 0.01 * x + 0.005 * y
    distance = np.sqrt((x - 500) ** 2 + (y - 500) ** 2)
    noise = rng.normal(0, 0.25, len(x))
    lst = 315 - 2.0 * canopy + 0.7 * impervious + 0.2 * lowveg + noise
    row, slope = fit_block_pass(
        city="Phoenix",
        block_id="phoenix_r0000_c0000",
        pass_id="phoenix:synthetic",
        lst_k=lst,
        canopy_fraction=canopy,
        context={
            "impervious_fraction": impervious,
            "low_vegetation_fraction": lowveg,
            "bare_fraction": bare,
            "building_fraction": building,
            "elevation": elevation,
            "distance_to_water": distance,
        },
        x_coord=x,
        y_coord=y,
        block_origin_x=0,
        block_origin_y=0,
    )
    assert slope is not None
    assert row["convergence_flag"] is True
    assert row["spatial_replicates_successful"] == 4
    assert float(row["spatially_robust_se_K_per_10pp"]) > 0
    assert "slope" not in row
    assert "coefficient" not in row


def test_span_fails_closed_without_coefficient() -> None:
    n = 80
    row, slope = fit_block_pass(
        city="Phoenix",
        block_id="b",
        pass_id="p",
        lst_k=np.linspace(300, 301, n),
        canopy_fraction=np.linspace(0.10, 0.20, n),
        context={"impervious": np.linspace(0, 1, n)},
        x_coord=np.arange(n) * 70.0,
        y_coord=np.zeros(n),
        block_origin_x=0,
        block_origin_y=0,
    )
    assert slope is None
    assert row["failure_reason"] == "canopy_span_below_0_20"
    assert row["convergence_flag"] is False


def test_square_root_attenuation_counts_and_ruling() -> None:
    assert required_count(0.4, 0.5, "detection") == 628
    assert required_count(0.4, 0.5, "equivalence") == 1978
    d1b = [
        {
            "city": "Phoenix",
            "season_window": "sensitivity",
            "view_zenith_set_deg": 15,
            "block_passes": 3000,
            "largest_connected_component_share": 1.0,
        },
        {
            "city": "Los Angeles",
            "season_window": "provisional_primary",
            "view_zenith_set_deg": 15,
            "block_passes": 4000,
            "largest_connected_component_share": 0.9,
        },
    ]
    rows, summaries = build_power_rows([0.3, 0.4, 0.5], d1b)
    assert summaries["median"] == 0.4
    assert len(rows) == 2 * 3 * 3 * 2
    ruling = free_check_ruling(rows)
    assert ruling["gate_A_authorized"] is False
    assert ruling["stop_before_gate_A"] is False


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            suite.addTest(unittest.FunctionTestCase(value))
    return suite


if __name__ == "__main__":
    unittest.main()
