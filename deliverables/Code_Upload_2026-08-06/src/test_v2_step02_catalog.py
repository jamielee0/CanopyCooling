#!/usr/bin/env python3
"""Synthetic verification for v2 Guide Step 2.

Run directly (no pytest required):

    MPLCONFIGDIR=/private/tmp/mpl-step2-v2 \
      /Users/jmlee/miniforge3/envs/urbanv2/bin/python \
      src/test_v2_step02_catalog.py

The tests never contact Earthdata and never download satellite files.  A fake
CMR search function verifies the catalogue adapter contract.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from urban_cooling_v2 import step02_catalog as step2


def _umm_record(granule_id: str, timestamp: str) -> dict:
    return {
        "meta": {"native-id": granule_id},
        "umm": {
            "GranuleUR": granule_id,
            "TemporalExtent": {
                "RangeDateTime": {"BeginningDateTime": timestamp}
            },
            "OrbitCalculatedSpatialDomains": [{"OrbitNumber": 12345}],
            "AdditionalAttributes": [
                {"Name": "GEOLOCATION_QUALITY_SUMMARY", "Values": ["best"]},
                {"Name": "VIEW_ZENITH", "Values": ["8.5"]},
                {"Name": "RETRIEVAL_BAND_COUNT", "Values": ["5"]},
            ],
            "SpatialExtent": {
                "HorizontalSpatialDomain": {
                    "Geometry": {"BoundingRectangles": [{"WestBoundingCoordinate": -113}]}
                }
            },
        },
    }


def test_metadata_normalization_and_offline_search_adapter() -> None:
    calls: list[dict] = []

    def fake_search(**kwargs):
        calls.append(kwargs)
        return [
            _umm_record(
                "ECOv003_L2T_LSTE_12345_001_12SVC_20200710T193000_0001_01",
                "2020-07-10T19:30:00Z",
            )
        ]

    domain = step2.CityDomain("Phoenix", 33.45, -112.07, (-113, 32.8, -111.2, 34.1))
    table = step2.search_earthaccess_summers(
        [domain],
        years=[2020],
        short_name="ECO_L2T_LSTE",
        version="003",
        search_data=fake_search,
    )
    assert len(calls) == 1
    assert calls[0]["temporal"] == (
        "2020-06-01T00:00:00Z",
        "2020-09-30T23:59:59Z",
    )
    assert calls[0]["bounding_box"] == domain.bbox_wsen
    assert table.loc[0, "orbit"] == "12345"
    assert table.loc[0, "scene"] == "001"
    assert table.loc[0, "tile"] == "12SVC"
    assert table.loc[0, "geolocation_quality"] == "best"
    assert table.loc[0, "collection_version"] == "003"


def test_mixed_iso_timestamps_and_adjacent_scenes_are_one_pass() -> None:
    raw = pd.DataFrame(
        {
            "city": ["Atlanta"] * 3,
            "granule_id": [
                "ECOv002_L2T_LSTE_00344_005_16SFB_20180728T223656_0712_01",
                "ECOv002_L2T_LSTE_00344_006_16SFC_20180728T223748_0712_01",
                "ECOv002_L2T_LSTE_00344_006_16SGC_20180728T223748_0712_01",
            ],
            "acquisition_utc": [
                "2018-07-28 22:36:56.465000+00:00",
                "2018-07-28 22:37:48+00:00",
                "2018-07-28 22:37:48+00:00",
            ],
            "orbit": ["00344"] * 3,
            "tile": ["16SFB", "16SFC", "16SGC"],
            "centroid_latitude": [33.75] * 3,
            "centroid_longitude": [-84.39] * 3,
            "geolocation_quality": ["best"] * 3,
            "view_zenith_deg": [5.0] * 3,
        }
    )
    prepared = step2.prepare_catalogue(raw, solar_engine="fallback")
    passes = step2.deduplicate_passes(prepared)
    assert len(passes) == 1
    assert passes.loc[0, "scene"] == "005|006"
    assert passes.loc[0, "n_intersecting_scenes"] == 2
    assert passes.loc[0, "n_intersecting_tiles"] == 3
    assert passes.loc[0, "acquisition_utc"].isoformat().startswith(
        "2018-07-28T22:37:48"
    )


def test_solar_time_geometry_and_astronomical_night() -> None:
    timestamp = pd.DatetimeIndex(["2023-06-21T19:30:00Z"])
    local_hour = step2.local_solar_time_hours(timestamp, -112.07)[0]
    assert 11.8 < local_hour < 12.2
    position = step2.solar_position(timestamp, 33.45, -112.07, engine="fallback")
    assert float(position.iloc[0]["solar_elevation_deg"]) > 75
    assert 150 < float(position.iloc[0]["solar_azimuth_deg"]) < 220

    night_position = step2.solar_position(
        pd.DatetimeIndex(["2023-06-21T08:00:00Z"]),
        33.45,
        -112.07,
        engine="fallback",
    )
    assert float(night_position.iloc[0]["solar_elevation_deg"]) < -6

    cases = pd.DataFrame(
        {
            "case": ["Phoenix", "Atlanta", "Miami"],
            "date": ["2020-06-21", "2021-07-15", "2022-09-01"],
            "latitude": [33.45, 33.75, 25.76],
            "longitude": [-112.07, -84.39, -80.19],
        }
    )
    check = step2.validate_local_solar_noon(cases, engine="fallback")
    assert check["pass"].all()


def test_band_mode_assignment_is_date_safe() -> None:
    times = pd.Series(
        pd.to_datetime(
            [
                "2018-07-01T12:00Z",
                "2019-05-14T12:00Z",
                "2019-05-15T12:00Z",
                "2023-04-27T12:00Z",
                "2023-04-28T12:00Z",
                "2023-05-17T12:00Z",
                "2023-05-18T12:00Z",
                "2024-07-01T12:00Z",
            ],
            utc=True,
        )
    )
    modes = step2.assign_retrieval_band_mode(
        times,
        observed_mode=[None, None, "full", "full", "full", "reduced", "full", "full"],
    )
    assert modes.tolist() == [
        "full",
        "full",
        "reduced",
        "reduced",
        "full",
        "reduced",
        "full",
        "full",
    ]
    audit = pd.DataFrame({"acquisition_utc": times, "retrieval_band_mode": modes})
    passed, detail = step2.validate_band_mode_assignments(audit)
    assert passed, detail

    summer_all_full = pd.DataFrame(
        {
            "acquisition_utc": pd.to_datetime(
                ["2023-06-01T12:00Z", "2024-07-01T12:00Z"], utc=True
            ),
            "retrieval_band_mode": ["full", "full"],
        }
    )
    passed, detail = step2.validate_band_mode_assignments(summer_all_full)
    assert passed, detail

    invalid_late_reduced = summer_all_full.copy()
    invalid_late_reduced.loc[1, "retrieval_band_mode"] = "reduced"
    passed, detail = step2.validate_band_mode_assignments(invalid_late_reduced)
    assert not passed
    assert "five-band-only" in detail

    unknown_late = summer_all_full.copy()
    unknown_late.loc[1, "retrieval_band_mode"] = "post_fix_unknown"
    passed, detail = step2.validate_band_mode_assignments(unknown_late)
    assert not passed
    assert "unknown=1" in detail


def test_acquisition_time_weather_join_uses_solar_date() -> None:
    passes = pd.DataFrame(
        {
            "city": ["Los Angeles"],
            "acquisition_utc": pd.to_datetime(["2023-07-02T00:00:00Z"], utc=True),
            "centroid_longitude": [-120.0],
        }
    )
    hourly = pd.DataFrame(
        {
            "city": ["Los Angeles", "Los Angeles"],
            "timestamp_utc": pd.to_datetime(
                ["2023-07-01T23:00:00Z", "2023-07-02T01:00:00Z"], utc=True
            ),
            "vpd_kpa": [4.0, 6.0],
        }
    )
    daily = pd.DataFrame(
        {
            "city": ["Los Angeles"],
            "date": ["2023-07-01"],
            "antecedent_dryness_percentile": [0.2],
        }
    )
    reference = pd.DataFrame(
        {
            "city": ["Los Angeles"] * 6,
            "vpd_kpa": [1, 2, 3, 4, 5, 6],
        }
    )
    joined = step2.join_acquisition_time_conditions(
        passes, hourly, daily, reference
    )
    assert np.isclose(joined.loc[0, "vpd_kpa_at_acquisition"], 5.0)
    assert joined.loc[0, "local_solar_date"].isoformat() == "2023-07-01"
    assert np.isclose(joined.loc[0, "demand_percentile"], 5 / 6)
    assert np.isclose(joined.loc[0, "antecedent_dryness_percentile"], 0.2)


CITY_COORDINATES = {
    "Phoenix": (33.45, -112.07),
    "Los Angeles": (34.05, -118.24),
    "Atlanta": (33.75, -84.39),
    "Minneapolis-Saint Paul": (44.98, -93.27),
    "Miami": (25.76, -80.19),
}


def _synthetic_raw_catalogue() -> pd.DataFrame:
    rows: list[dict] = []
    orbit = 10000
    for city_index, (city, (latitude, longitude)) in enumerate(CITY_COORDINATES.items()):
        for year in range(2018, 2026):
            for stratum_index, solar_hour in enumerate((10.5, 12.5, 14.5, 16.5)):
                day = 5 + stratum_index * 6 + city_index
                # Longitude-only conversion is close enough; the equation of
                # time perturbation remains safely inside each two-hour bin.
                utc_hour = (solar_hour - longitude / 15) % 24
                hour = int(utc_hour)
                minute = int(round((utc_hour - hour) * 60))
                if minute == 60:
                    hour = (hour + 1) % 24
                    minute = 0
                acquisition = pd.Timestamp(
                    year=year,
                    month=7,
                    day=day,
                    hour=hour,
                    minute=minute,
                    tz="UTC",
                )
                if acquisition >= step2.FIVE_BAND_ONLY_START:
                    reported_mode = "full"
                    band_count = 5
                elif acquisition >= step2.FIRMWARE_FIX:
                    reported_mode = "full" if (stratum_index + year) % 2 else "reduced"
                    band_count = 5 if reported_mode == "full" else 3
                else:
                    reported_mode = None
                    band_count = np.nan
                demand = 0.86 if (stratum_index + year) % 2 == 0 else 0.14
                dryness = 0.14 if demand > 0.5 else 0.86
                # Two tiles per acquisition test the mandatory pass de-duplication.
                for tile_index, tile in enumerate(("12SVC", "12SVD")):
                    rows.append(
                        {
                            "city": city,
                            "granule_id": f"ECO_{orbit}_{tile}_{acquisition:%Y%m%dT%H%M%S}",
                            "acquisition_utc": acquisition,
                            "orbit": str(orbit),
                            "tile": tile,
                            "footprint_json": "{}",
                            "centroid_latitude": latitude,
                            "centroid_longitude": longitude,
                            "geolocation_quality": "best" if tile_index == 0 else "good",
                            "view_zenith_deg": 7 + tile_index,
                            "reported_band_mode": reported_mode,
                            "retrieval_band_count": band_count,
                            "demand_percentile": demand,
                            "antecedent_dryness_percentile": dryness,
                        }
                    )
                orbit += 1
    return pd.DataFrame(rows)


def _cloud_samples() -> tuple[pd.DataFrame, pd.DataFrame]:
    domain = np.ones((10, 10), dtype=bool)
    frames = []
    for city, primary_count, validation_count in (
        ("Phoenix", 80, 76),
        ("Miami", 65, 61),
    ):
        primary = np.zeros((10, 10), dtype=bool)
        primary.flat[:primary_count] = True
        validation = np.zeros((10, 10), dtype=bool)
        validation.flat[:validation_count] = True
        frames.append(
            step2.summarize_cloud_masks(
                city=city,
                month="2021-07",
                usable_masks=[primary],
                domain_mask=domain,
                is_primary=True,
                scene_ids=[f"{city}-primary"],
            )
        )
        frames.append(
            step2.summarize_cloud_masks(
                city=city,
                month="2022-07",
                usable_masks=[validation],
                domain_mask=domain,
                is_primary=False,
                scene_ids=[f"{city}-validation"],
            )
        )
    return step2.estimate_cloud_survival(pd.concat(frames, ignore_index=True))


def test_deduplication_cloud_attrition_counts_and_deliverables() -> None:
    raw = _synthetic_raw_catalogue()
    prepared = step2.prepare_catalogue(raw, solar_engine="fallback")
    assert len(prepared) == 320
    scenes = step2.deduplicate_passes(prepared)
    assert len(scenes) == 160
    assert set(scenes["n_intersecting_tiles"]) == {2}
    usable = step2.filter_usable_passes(scenes)
    assert len(usable) == 160
    assert usable.groupby("city")["time_stratum"].nunique().eq(4).all()

    month, cloud_summary = _cloud_samples()
    assert len(month) == 4
    assert cloud_summary["representative"].all()
    assert np.isclose(
        cloud_summary.set_index("measured_city").loc["Phoenix", "cloud_survival_fraction"],
        0.8,
    )

    cloud_reference = {
        "Phoenix": "Phoenix",
        "Los Angeles": "Phoenix",
        "Atlanta": "Miami",
        "Minneapolis-Saint Paul": "Miami",
        "Miami": "Miami",
    }
    resolved = step2.resolve_cloud_survival(CITY_COORDINATES, cloud_summary, cloud_reference)
    attrition = step2.build_attrition_table(scenes, resolved)
    assert len(attrition) == len(CITY_COORDINATES) * len(step2.ATTRITION_STAGES)
    assert (
        attrition.groupby("city")["count_or_expected_count"].apply(
            lambda values: np.all(np.diff(values.to_numpy()) <= 1e-12)
        )
    ).all()

    counts = step2.usable_pass_counts(usable)
    assert int(
        counts.loc[counts["count_scope"] == "grand_total", "n_usable_passes"].iloc[0]
    ) == 160
    conditions = step2.pass_condition_counts(usable)
    corner_total = int(conditions.loc[conditions["off_diagonal_corner"], "n_passes"].sum())
    assert corner_total == len(usable)

    cases = pd.DataFrame(
        {
            "case": ["Phoenix", "Atlanta", "Miami"],
            "date": ["2020-06-21", "2021-07-15", "2022-09-01"],
            "latitude": [33.45, 33.75, 25.76],
            "longitude": [-112.07, -84.39, -80.19],
        }
    )
    checks = step2.run_step2_checks(
        scenes, usable, counts, cloud_summary, cases, solar_engine="fallback"
    )
    assert len(checks) == 6
    assert checks["pass"].all(), checks.to_string(index=False)

    with tempfile.TemporaryDirectory(prefix="step2-v2-") as temporary:
        paths = step2.build_step2_deliverables(
            prepared,
            cloud_summary,
            cloud_reference,
            cases,
            temporary,
            step1_recommendation="Step 1 recommended proceeding with a pooled audit.",
            rules=step2.FeasibilityRules(
                minimum_expected_total=50,
                minimum_expected_per_city=5,
                minimum_expected_per_pooled_stratum=5,
                minimum_off_diagonal_per_corner=5,
            ),
            solar_check_engine="fallback",
        )
        assert paths["gate"] == "PASS"
        for deliverable_id in (
            "F2.1",
            "F2.2",
            "F2.3",
            "F2.4",
            "F2.5",
            "T2.1",
            "T2.2",
            "T2.3",
            "catalogue",
            "conditions",
            "checks",
            "memo",
        ):
            path = Path(paths[deliverable_id])
            assert path.exists() and path.stat().st_size > 0, deliverable_id

        partial = step2.write_catalogue_ceiling_audit(prepared, Path(temporary) / "partial")
        assert partial["gate"] == "STOP_REQUIRED_METADATA_ENRICHMENT"
        for deliverable_id in (
            "F2.1_partial",
            "F2.2_partial",
            "F2.4_partial",
            "T2.1_partial",
            "T2.2_partial",
            "T2.3",
            "catalogue",
            "checks",
            "memo",
        ):
            path = Path(partial[deliverable_id])
            assert path.exists() and path.stat().st_size > 0, deliverable_id
        assert "F2.3" not in partial and "F2.5" not in partial


def test_candidate_specific_cloud_weights_preserve_zero_clear_passes() -> None:
    scenes = step2.deduplicate_passes(
        step2.prepare_catalogue(_synthetic_raw_catalogue(), solar_engine="fallback")
    )
    scenes["cloud_survival_fraction_of_domain"] = np.tile(
        [0.0, 1.0], len(scenes) // 2
    )
    usable = step2.filter_usable_passes(scenes)
    usable["expected_cloud_weight"] = usable[
        "cloud_survival_fraction_of_domain"
    ]
    city_mean = usable.groupby("city")["expected_cloud_weight"].mean()
    resolved = pd.DataFrame(
        {
            "city": city_mean.index,
            "cloud_survival_fraction": city_mean.to_numpy(),
            "cloud_reference_city": "candidate_specific_observed",
        }
    )
    attrition = step2.build_attrition_table(
        scenes,
        resolved,
        pass_cloud_weight_column="cloud_survival_fraction_of_domain",
    )
    final = attrition.loc[
        attrition["stage"].eq("surviving_cloud_screening")
    ].set_index("city")
    expected = usable.groupby("city")["expected_cloud_weight"].sum()
    pd.testing.assert_series_equal(
        final["count_or_expected_count"].sort_index(),
        expected.sort_index(),
        check_names=False,
    )
    assert (usable["expected_cloud_weight"] == 0).any()
    counts = step2.usable_pass_counts(usable)
    grand = counts.loc[counts["count_scope"].eq("grand_total")].iloc[0]
    assert np.isclose(
        grand["expected_usable_pass_equivalents"],
        usable["expected_cloud_weight"].sum(),
    )
    conditions = step2.pass_condition_counts(usable)
    assert "expected_pass_equivalents" in conditions
    assert np.isclose(
        conditions["expected_pass_equivalents"].sum(),
        usable["expected_cloud_weight"].sum(),
    )
    independent_cloud = pd.DataFrame(
        {
            "cloud_survival_fraction_of_domain": [0.0, 0.5],
            "n_clear_pixels_independent_of_view": [0, 50],
            "cloud_asset_complete": [True, True],
            "provenance_complete": [True, True],
        }
    )
    cases = pd.DataFrame(
        {
            "case": ["Phoenix", "Atlanta", "Miami"],
            "date": ["2020-06-21", "2021-07-15", "2022-09-01"],
            "latitude": [33.45, 33.75, 25.76],
            "longitude": [-112.07, -84.39, -80.19],
        }
    )
    checks = step2.run_step2_checks(
        scenes,
        usable,
        counts,
        independent_cloud,
        cases,
        solar_engine="fallback",
        cloud_check_mode="candidate_census",
    )
    cloud_check = checks.loc[
        checks["check"].eq("candidate cloud census is complete")
    ].iloc[0]
    assert bool(cloud_check["pass"])
    assert "D0035" in str(cloud_check["detail"])

    gate_attrition = pd.DataFrame(
        {
            "city": ["Phoenix"],
            "stage": ["surviving_cloud_screening"],
            "count_or_expected_count": [10.0],
            "cloud_survival_fraction": [0.5],
        }
    )
    gate_usable = pd.DataFrame(
        {
            "city": ["Phoenix", "Phoenix"],
            "time_stratum": ["10-12", "12-14"],
            "expected_cloud_weight": [0.5, 0.5],
        }
    )
    gate_conditions = pd.DataFrame(
        {
            "condition_cell": [
                "demand_high__antecedent_wet",
                "demand_low__antecedent_dry",
            ],
            "n_passes": [10, 10],
            "expected_pass_equivalents": [0.5, 0.5],
            "off_diagonal_corner": [True, True],
        }
    )
    gate, reasons = step2.assess_feasibility(
        gate_attrition,
        gate_usable,
        gate_conditions,
        pd.DataFrame({"pass": [True]}),
        step2.FeasibilityRules(
            minimum_expected_total=0,
            minimum_expected_per_city=0,
            minimum_expected_per_pooled_stratum=0,
            minimum_off_diagonal_per_corner=5,
        ),
    )
    assert gate == "STOP"
    assert any("expected_pass_equivalents" in reason for reason in reasons)


def main() -> int:
    tests = [
        test_metadata_normalization_and_offline_search_adapter,
        test_mixed_iso_timestamps_and_adjacent_scenes_are_one_pass,
        test_solar_time_geometry_and_astronomical_night,
        test_band_mode_assignment_is_date_safe,
        test_acquisition_time_weather_join_uses_solar_date,
        test_deduplication_cloud_attrition_counts_and_deliverables,
        test_candidate_specific_cloud_weights_preserve_zero_clear_passes,
    ]
    failures = []
    for test in tests:
        try:
            test()
        except Exception as exc:  # pragma: no cover - direct-run reporting
            failures.append((test.__name__, exc))
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
        else:
            print(f"PASS {test.__name__}")
    if failures:
        print(f"\n{len(failures)} of {len(tests)} Step-2 tests failed")
        return 1
    print(f"\nAll {len(tests)} Step-2 tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
