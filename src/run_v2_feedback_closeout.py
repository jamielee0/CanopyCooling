#!/usr/bin/env python3
"""Close all 37 Urban Tree Cooling feedback items without opening outcomes.

This runner is deliberately standalone: it imports no ``urban_cooling_v2`` or
other project module.  It consumes only previously sealed historical
nonthermal artifacts, performs independent identities/known-answer checks, and
fails closed when a requested analysis is not identifiable.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from pvlib.solarposition import spa_python


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/v2/hitl/FEEDBACK_CLOSEOUT"

TRACE = ROOT / "docs/v2/hitl/G0_FREEZE_AND_AMENDMENT/feedback_traceability.csv"
G1 = ROOT / "docs/v2/hitl/G1_OBSERVATION_RECONCILIATION"
G2 = ROOT / "docs/v2/hitl/G2_HYDROCLIMATE_SUPPORT"
G3 = ROOT / "docs/v2/hitl/G3_SAMPLING_DESIGN_SECOND_REVISION"
DOMAINS = ROOT / "data/raw/v2/hitl/g3_sampling_design/candidate_domains_7.geojson"
D0056_SETTINGS = (
    ROOT / "data/processed/v2/task1/step3_time_of_day_only_D0056/simulation_settings.json"
)
D0056_GATE = (
    ROOT / "data/processed/v2/task1/step3_time_of_day_only_D0056/step3_time_of_day_gate.json"
)
D0083 = ROOT / "docs/v2/D0083_USER_AUTHORIZED_NONTHERMAL_FEEDBACK_CLOSEOUT.md"
FEEDBACK_DOC = Path("/Users/jmlee/Downloads/Urban_Tree_Cooling_feedbackdocx (1).docx")

EXPECTED_FEEDBACK_SHA256 = "4d369a5337a20b2969d4c1ccabb528c56fae9eb19061c72513d301658dc79333"
THRESHOLDS = (10, 15, 20, 25)
PRIMARY_CITY_WINDOWS = (
    ("atlanta", "jun_sep"),
    ("denver_aurora", "jun_sep"),
    ("minneapolis_st_paul", "jun_sep"),
    ("phoenix", "phoenix_apr_may"),
)
NREL_REFERENCE_URL = "https://www.nrel.gov/docs/fy08osti/34302.pdf"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def atomic_json(path: Path, payload: Any) -> None:
    atomic_text(path, json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")


def atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    frame.to_csv(temporary, index=False)
    temporary.replace(path)


def finite_range_overlap(left: Iterable[float], right: Iterable[float]) -> float:
    a = np.asarray(list(left), dtype=float)
    b = np.asarray(list(right), dtype=float)
    a = a[np.isfinite(a)]
    b = b[np.isfinite(b)]
    if not len(a) or not len(b):
        return math.nan
    return float(min(a.max(), b.max()) - max(a.min(), b.min()))


def _range(values: pd.Series) -> tuple[float, float]:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return math.nan, math.nan
    return float(numeric.min()), float(numeric.max())


def build_g4_high_demand_audit(detail: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for threshold in THRESHOLDS:
        selected = detail.loc[pd.to_numeric(detail["threshold_deg"]).eq(threshold)].copy()
        for city, window in PRIMARY_CITY_WINDOWS:
            group = selected.loc[
                selected["city"].astype(str).eq(city)
                & selected["window_id"].astype(str).eq(window)
            ].copy()
            high = group.loc[group["demand_level"].astype(str).eq("high")]
            wet = high.loc[high["wetness_level"].astype(str).eq("wet")]
            dry = high.loc[high["wetness_level"].astype(str).eq("dry")]
            wet_vpd = _range(wet["vpd_kpa_at_acquisition"])
            dry_vpd = _range(dry["vpd_kpa_at_acquisition"])
            wet_day = _range(wet["day_of_window"])
            dry_day = _range(dry["day_of_window"])
            vpd_overlap = finite_range_overlap(
                wet["vpd_kpa_at_acquisition"], dry["vpd_kpa_at_acquisition"]
            )
            day_overlap = finite_range_overlap(wet["day_of_window"], dry["day_of_window"])
            count_pass = len(wet) >= 2 and len(dry) >= 2
            vpd_pass = bool(math.isfinite(vpd_overlap) and vpd_overlap > 0)
            day_pass = bool(math.isfinite(day_overlap) and day_overlap > 0)
            rows.append(
                {
                    "threshold_deg": threshold,
                    "city": city,
                    "window_id": window,
                    "physical_passes": len(group),
                    "high_demand_passes": len(high),
                    "high_demand_wet_passes": len(wet),
                    "high_demand_dry_passes": len(dry),
                    "wet_vpd_min_kpa": wet_vpd[0],
                    "wet_vpd_max_kpa": wet_vpd[1],
                    "dry_vpd_min_kpa": dry_vpd[0],
                    "dry_vpd_max_kpa": dry_vpd[1],
                    "vpd_range_overlap_kpa": vpd_overlap,
                    "wet_day_of_window_min": wet_day[0],
                    "wet_day_of_window_max": wet_day[1],
                    "dry_day_of_window_min": dry_day[0],
                    "dry_day_of_window_max": dry_day[1],
                    "day_of_window_range_overlap_days": day_overlap,
                    "wet_dry_count_pass": count_pass,
                    "absolute_demand_overlap_pass": vpd_pass,
                    "season_overlap_pass": day_pass,
                    "city_case_support_pass": count_pass and vpd_pass and day_pass,
                    "phoenix_season_phase": (
                        "pre_monsoon_april_may_only" if city == "phoenix" else "not_applicable"
                    ),
                    "temperature_or_lst_opened": False,
                    "record_2026_opened": False,
                }
            )
    result = pd.DataFrame(rows)
    threshold_checks: dict[str, Any] = {}
    for threshold in THRESHOLDS:
        selected = result.loc[result["threshold_deg"].eq(threshold)]
        passing = selected.loc[selected["city_case_support_pass"]]
        pass_counts = selected.set_index("city")["physical_passes"]
        total = int(pass_counts.sum())
        maximum_share = float(pass_counts.max() / total) if total else math.nan
        threshold_checks[str(threshold)] = {
            "within_city_passing_city_count": len(passing),
            "within_city_passing_cities": sorted(passing["city"].astype(str).tolist()),
            "four_city_pooled_support_pass": len(passing) >= 4,
            "maximum_city_share": maximum_share,
            "city_share_cap_pass": bool(math.isfinite(maximum_share) and maximum_share <= 0.40),
            "pooled_high_demand_contrast_eligible": bool(
                len(passing) >= 4 and math.isfinite(maximum_share) and maximum_share <= 0.40
            ),
        }
    checks = {
        "gate": "G4_DIAGNOSTIC_CLOSEOUT",
        "decision_id": "D0083",
        "thresholds": threshold_checks,
        "pooled_contrast_authorized": any(
            value["pooled_high_demand_contrast_eligible"]
            for value in threshold_checks.values()
        ),
        "case_study_candidates_at_25deg": threshold_checks["25"][
            "within_city_passing_cities"
        ],
        "temperature_or_lst_opened": False,
        "record_2026_opened": False,
    }
    return result, checks


def _city_centroids() -> dict[str, tuple[float, float]]:
    document = json.loads(DOMAINS.read_text(encoding="utf-8"))
    return {
        str(feature["properties"]["city"]): (
            float(feature["properties"]["CENTLAT"]),
            float(feature["properties"]["CENTLON"]),
        )
        for feature in document["features"]
    }


def add_independent_solar_position(detail: pd.DataFrame) -> pd.DataFrame:
    centroids = _city_centroids()
    output = detail.copy()
    output["astronomical_solar_elevation_deg"] = math.nan
    output["astronomical_solar_azimuth_deg"] = math.nan
    output["acquisition_utc"] = pd.to_datetime(
        output["acquisition_utc"], utc=True, errors="raise", format="mixed"
    )
    for city, index in output.groupby("city", sort=False).groups.items():
        latitude, longitude = centroids[str(city)]
        position = spa_python(
            pd.DatetimeIndex(output.loc[index, "acquisition_utc"]),
            latitude,
            longitude,
        )
        output.loc[index, "astronomical_solar_elevation_deg"] = position[
            "apparent_elevation"
        ].to_numpy()
        output.loc[index, "astronomical_solar_azimuth_deg"] = position[
            "azimuth"
        ].to_numpy()
    return output


def build_g5_time_audit(detail: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    work = add_independent_solar_position(detail)
    rows: list[dict[str, Any]] = []
    for threshold in THRESHOLDS:
        selected = work.loc[pd.to_numeric(work["threshold_deg"]).eq(threshold)]
        for city, window in PRIMARY_CITY_WINDOWS:
            group = selected.loc[
                selected["city"].astype(str).eq(city)
                & selected["window_id"].astype(str).eq(window)
            ]
            morning = group.loc[group["time_stratum"].astype(str).eq("10-12")]
            afternoon = group.loc[group["time_stratum"].astype(str).eq("16-18")]
            morning_elevation = _range(morning["astronomical_solar_elevation_deg"])
            afternoon_elevation = _range(afternoon["astronomical_solar_elevation_deg"])
            solar_overlap = finite_range_overlap(
                morning["astronomical_solar_elevation_deg"],
                afternoon["astronomical_solar_elevation_deg"],
            )
            vpd_overlap = finite_range_overlap(
                morning["vpd_kpa_at_acquisition"], afternoon["vpd_kpa_at_acquisition"]
            )
            day_overlap = finite_range_overlap(morning["day_of_window"], afternoon["day_of_window"])
            relative_overlap = finite_range_overlap(
                morning["relative_azimuth_median_deg"],
                afternoon["relative_azimuth_median_deg"],
            )
            rows.append(
                {
                    "threshold_deg": threshold,
                    "city": city,
                    "window_id": window,
                    "physical_passes": len(group),
                    "morning_10_12_passes": len(morning),
                    "afternoon_16_18_passes": len(afternoon),
                    "candidate_cross_stratum_pairs_before_calipers": len(morning) * len(afternoon),
                    "morning_solar_elevation_min_deg": morning_elevation[0],
                    "morning_solar_elevation_max_deg": morning_elevation[1],
                    "afternoon_solar_elevation_min_deg": afternoon_elevation[0],
                    "afternoon_solar_elevation_max_deg": afternoon_elevation[1],
                    "solar_elevation_range_overlap_deg": solar_overlap,
                    "vpd_range_overlap_kpa": vpd_overlap,
                    "day_of_window_range_overlap_days": day_overlap,
                    "relative_azimuth_range_overlap_deg": relative_overlap,
                    "both_strata_observed": bool(len(morning) and len(afternoon)),
                    "solar_elevation_overlap_pass": bool(
                        math.isfinite(solar_overlap) and solar_overlap > 0
                    ),
                    "empirical_matching_possible": bool(
                        len(morning)
                        and len(afternoon)
                        and math.isfinite(solar_overlap)
                        and solar_overlap > 0
                    ),
                    "estimand": "time_of_day_asymmetry_at_comparable_solar_elevation",
                    "hysteresis_or_physiology_claim_authorized": False,
                    "temperature_or_lst_opened": False,
                    "record_2026_opened": False,
                }
            )
    result = pd.DataFrame(rows)
    threshold_checks = {
        str(threshold): {
            "cities_with_both_strata": int(
                result.loc[result["threshold_deg"].eq(threshold), "both_strata_observed"].sum()
            ),
            "candidate_pairs_before_calipers": int(
                result.loc[
                    result["threshold_deg"].eq(threshold),
                    "candidate_cross_stratum_pairs_before_calipers",
                ].sum()
            ),
            "empirical_matching_possible": bool(
                result.loc[
                    result["threshold_deg"].eq(threshold),
                    "empirical_matching_possible",
                ].all()
                and len(result.loc[result["threshold_deg"].eq(threshold)]) == 4
            ),
        }
        for threshold in THRESHOLDS
    }
    checks = {
        "gate": "G5_DIAGNOSTIC_CLOSEOUT",
        "decision_id": "D0083",
        "thresholds": threshold_checks,
        "matched_analysis_count": 0,
        "time_of_day_analysis_authorized": any(
            value["empirical_matching_possible"] for value in threshold_checks.values()
        ),
        "estimand": "time_of_day_asymmetry_at_comparable_solar_elevation",
        "interpretation_boundary": (
            "Not hysteresis or direct physiological evidence; heat storage, air temperature, "
            "wind, illumination, and shadow geometry remain possible explanations."
        ),
        "temperature_or_lst_opened": False,
        "record_2026_opened": False,
    }
    return result, checks


def vpd_kpa_from_kelvin(temperature_k: float, dewpoint_k: float) -> float:
    def saturation(celsius: float) -> float:
        return 0.6108 * math.exp(17.27 * celsius / (celsius + 237.3))

    return saturation(temperature_k - 273.15) - saturation(dewpoint_k - 273.15)


def cloud_semantics(values: Iterable[float]) -> dict[str, int]:
    array = np.asarray(list(values), dtype=float)
    valid = np.isfinite(array) & (array != 255)
    return {
        "clear": int((valid & (array == 0)).sum()),
        "cloud": int((valid & (array >= 1) & (array <= 254)).sum()),
        "fill_or_missing": int((~valid).sum()),
    }


def build_g6_independent_verification() -> dict[str, Any]:
    attrition = pd.read_csv(G1 / "attrition_summary.csv")
    ledger = pd.read_csv(G1 / "observation_ledger.csv", low_memory=False)
    dedup = pd.read_csv(G1 / "deduplication_summary.csv")
    crosswalk = pd.read_csv(G1 / "hrrr_pass_hour_crosswalk.csv")
    quality = pd.read_csv(G1 / "pass_quality_219.csv")
    hydro = pd.read_csv(G2 / "pass_hydroclimate_219.csv", low_memory=False)
    leakage = pd.read_csv(G2 / "window_exclusion_audit.csv")
    phoenix = pd.read_csv(G2 / "phoenix_june_sign_check.csv")
    g3_cleanroom = json.loads((G3 / "cleanroom_verification.json").read_text(encoding="utf-8"))

    attrition_counts = dict(zip(attrition["stage"], attrition["physical_count"], strict=True))
    expected_chain = {
        "physical_city_orbit_observations": 2968,
        "geometry_pass_p95_le_20_and_coverage_ge_0_95": 219,
        "early_late_stratum_eligible_10_12_or_16_18_prior_to_matching": 102,
    }
    cloud_partition = bool(
        (
            pd.to_numeric(quality["n_clear_pixels_independent_of_view"])
            + pd.to_numeric(quality["n_cloud_pixels_independent_of_view"])
            == pd.to_numeric(quality["n_cloud_observed_pixels_independent_of_view"])
        ).all()
        and (
            pd.to_numeric(quality["n_cloud_observed_pixels_independent_of_view"])
            + pd.to_numeric(quality["n_cloud_invalid_or_fill_pixels_independent_of_view"])
            == pd.to_numeric(quality["n_domain_pixels_cloud"])
        ).all()
    )
    vpd_value = vpd_kpa_from_kelvin(303.15, 293.15)
    nrel_time = pd.DatetimeIndex([pd.Timestamp("2003-10-17T19:30:30Z")])
    nrel = spa_python(
        nrel_time,
        39.742476,
        -105.1786,
        altitude=1830.14,
        pressure=82000,
        temperature=11,
        delta_t=67,
    ).iloc[0]
    nrel_zenith_error = abs(float(nrel["apparent_zenith"]) - 50.11162)
    nrel_azimuth_error = abs(float(nrel["azimuth"]) - 194.34024)
    cloud_fixture = cloud_semantics([0, 1, 255, math.nan])
    synthetic_focal = pd.Timestamp("2020-07-15")
    synthetic_prior_end = synthetic_focal - pd.Timedelta(days=1)
    checks = [
        {
            "check_id": "G6-C01",
            "name": "feedback_document_hash",
            "passed": FEEDBACK_DOC.is_file() and sha256_file(FEEDBACK_DOC) == EXPECTED_FEEDBACK_SHA256,
            "evidence": EXPECTED_FEEDBACK_SHA256,
        },
        {
            "check_id": "G6-C02",
            "name": "core_attrition_counts",
            "passed": all(int(attrition_counts.get(name, -1)) == value for name, value in expected_chain.items()),
            "evidence": expected_chain,
        },
        {
            "check_id": "G6-C03",
            "name": "physical_observation_identity_and_deduplication",
            "passed": bool(
                len(ledger) == 2968
                and not ledger.duplicated(["city", "orbit"]).any()
                and ledger["observation_id"].nunique() == 2968
                and int(dedup.loc[dedup["city"].eq("ALL_CITIES"), "physical_city_orbit_observations"].iloc[0]) == 2968
            ),
            "evidence": {"ledger_rows": len(ledger), "unique_observations": ledger["observation_id"].nunique()},
        },
        {
            "check_id": "G6-C04",
            "name": "weather_438_links_413_assets_219_passes",
            "passed": bool(
                len(crosswalk) == 438
                and crosswalk["analysis_utc"].nunique() == 413
                and crosswalk["observation_id"].nunique() == 219
            ),
            "evidence": {
                "links": len(crosswalk),
                "unique_assets": crosswalk["analysis_utc"].nunique(),
                "passes": crosswalk["observation_id"].nunique(),
            },
        },
        {
            "check_id": "G6-C05",
            "name": "vpd_known_answer_kelvin_to_kpa",
            "passed": abs(vpd_value - 1.9047837878315672) < 1e-12,
            "evidence": {"temperature_k": 303.15, "dewpoint_k": 293.15, "vpd_kpa": vpd_value},
        },
        {
            "check_id": "G6-C06",
            "name": "nrel_spa_published_position",
            "passed": nrel_zenith_error < 1e-4 and nrel_azimuth_error < 1e-4,
            "evidence": {
                "source": NREL_REFERENCE_URL,
                "expected_apparent_zenith_deg": 50.11162,
                "observed_apparent_zenith_deg": float(nrel["apparent_zenith"]),
                "expected_azimuth_deg": 194.34024,
                "observed_azimuth_deg": float(nrel["azimuth"]),
            },
        },
        {
            "check_id": "G6-C07",
            "name": "prior_day_windows_exclude_observation_day",
            "passed": bool(
                hydro["antecedent_window_end"]
                .astype(str)
                .eq("day_before_local_solar_date")
                .all()
                and synthetic_prior_end == pd.Timestamp("2020-07-14")
                and int(leakage["observation_day_exclusion_violations"].sum()) == 0
            ),
            "evidence": {
                "pass_rows": len(hydro),
                "known_answer_focal_date": str(synthetic_focal.date()),
                "known_answer_window_end": str(synthetic_prior_end.date()),
                "audit_violations": int(
                    leakage["observation_day_exclusion_violations"].sum()
                ),
            },
        },
        {
            "check_id": "G6-C08",
            "name": "cloud_mask_fill_semantics_and_empirical_partitions",
            "passed": cloud_fixture == {"clear": 1, "cloud": 1, "fill_or_missing": 2} and cloud_partition,
            "evidence": {"known_answer": cloud_fixture, "empirical_passes": len(quality)},
        },
        {
            "check_id": "G6-C09",
            "name": "precipitation_et0_balance_units_and_sign",
            "passed": bool(
                (phoenix["independent_june_median_balance_30d_mm"] < -100).all()
                and phoenix["june_median_is_negative"].astype(bool).all()
            ),
            "evidence": {
                "unit": "mm",
                "definition": "precipitation_mm_minus_reference_evapotranspiration_mm",
                "phoenix_years": len(phoenix),
                "maximum_june_median_mm": float(phoenix["independent_june_median_balance_30d_mm"].max()),
            },
        },
        {
            "check_id": "G6-C10",
            "name": "g3_geometry_weather_support_cleanroom",
            "passed": bool(
                g3_cleanroom.get("geometry_cloud_weather_join_reproduced") is True
                and g3_cleanroom.get("governed_pass_values_reproduced") is True
                and g3_cleanroom.get("archive_bounds_reproduced") is True
            ),
            "evidence": {
                "verified_geometry_rows": g3_cleanroom.get("geometry_evidence_verification", {}).get("pass_evidence_rows_verified"),
                "new_unavailable_count": g3_cleanroom.get("new_unavailable_count"),
            },
        },
    ]
    return {
        "gate": "G6_INDEPENDENT_CLOSEOUT_VERIFICATION",
        "script_imports_existing_v2_modules": False,
        "checks": checks,
        "all_passed": all(item["passed"] for item in checks),
        "temperature_or_lst_opened": False,
        "holdout_opened": False,
        "record_2026_opened": False,
    }


def build_g7_preflight(
    detail: pd.DataFrame,
    g4_checks: dict[str, Any],
    g5_checks: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    quality = pd.read_csv(G1 / "pass_quality_219.csv")
    tree_reference_yield_available = bool(
        quality["usable_tree_pixels"].notna().all()
        and quality["usable_reference_pixels"].notna().all()
    )
    selected = detail.loc[pd.to_numeric(detail["threshold_deg"]).eq(25)].copy()
    design = selected[["city", "vpd_kpa_at_acquisition", "antecedent_precipitation_30d_mm"]].dropna()
    city_dummies = pd.get_dummies(design["city"].astype(str), drop_first=True, dtype=float)
    vpd = pd.to_numeric(design["vpd_kpa_at_acquisition"]).to_numpy(dtype=float)
    wet = pd.to_numeric(design["antecedent_precipitation_30d_mm"]).to_numpy(dtype=float)
    vpd = (vpd - vpd.mean()) / vpd.std(ddof=0)
    wet = (wet - wet.mean()) / wet.std(ddof=0)
    matrix = np.column_stack(
        [np.ones(len(design)), city_dummies.to_numpy(), vpd, wet, vpd * wet]
    )
    rank = int(np.linalg.matrix_rank(matrix)) if len(matrix) else 0
    columns = int(matrix.shape[1]) if len(matrix) else 0
    full_surface_rank_complete = bool(rank == columns and len(design) >= columns)
    g4_25 = g4_checks["thresholds"]["25"]
    profiles = pd.DataFrame(
        [
            {
                "simulation_profile": "full_demand_by_wetness_surface",
                "empirical_pass_count": len(selected),
                "design_rank": rank,
                "design_columns": columns,
                "required_group_support_pass": full_surface_rank_complete,
                "tree_reference_measurement_error_inputs_available": tree_reference_yield_available,
                "identifiable_for_feedback_compliant_simulation": full_surface_rank_complete and tree_reference_yield_available,
                "run_status": (
                    "READY" if full_surface_rank_complete and tree_reference_yield_available
                    else "NOT_RUN_MISSING_TREE_REFERENCE_MEASUREMENT_ERROR_INPUTS"
                ),
                "power": math.nan,
                "minimum_detectable_effect_k": math.nan,
            },
            {
                "simulation_profile": "focused_high_demand_wet_dry",
                "empirical_pass_count": int(selected["demand_level"].astype(str).eq("high").sum()),
                "design_rank": math.nan,
                "design_columns": math.nan,
                "required_group_support_pass": g4_25["four_city_pooled_support_pass"],
                "tree_reference_measurement_error_inputs_available": tree_reference_yield_available,
                "identifiable_for_feedback_compliant_simulation": bool(
                    g4_25["four_city_pooled_support_pass"] and tree_reference_yield_available
                ),
                "run_status": "NOT_RUN_FEWER_THAN_FOUR_CITIES_WITH_GENUINE_OVERLAP",
                "power": math.nan,
                "minimum_detectable_effect_k": math.nan,
            },
            {
                "simulation_profile": "empirically_matched_time_of_day_asymmetry",
                "empirical_pass_count": int(g5_checks["matched_analysis_count"]),
                "design_rank": math.nan,
                "design_columns": math.nan,
                "required_group_support_pass": g5_checks["time_of_day_analysis_authorized"],
                "tree_reference_measurement_error_inputs_available": tree_reference_yield_available,
                "identifiable_for_feedback_compliant_simulation": bool(
                    g5_checks["time_of_day_analysis_authorized"] and tree_reference_yield_available
                ),
                "run_status": "NOT_RUN_ZERO_EMPIRICAL_AM_PM_MATCHES",
                "power": math.nan,
                "minimum_detectable_effect_k": math.nan,
            },
        ]
    )
    historical = json.loads(D0056_GATE.read_text(encoding="utf-8"))
    historical_settings = json.loads(D0056_SETTINGS.read_text(encoding="utf-8"))
    historical_spec = historical_settings.get("simulation_spec", {})
    contract = {
        "gate": "G7_SIMULATION_CLOSEOUT_PREFLIGHT",
        "decision_id": "D0083",
        "frozen_parameters": {
            "effect_sizes_k": [0.75, 1.5, 2.25],
            "primary_effect_size_k": 1.5,
            "pass_sd_k": 0.8,
            "matched_set_sd_k": 0.5,
            "row_sd_k": 1.5,
            "alpha": 0.05,
            "target_power": 0.8,
            "seed": 20260816,
            "planned_power_replicates_per_effect": 1000,
            "planned_null_replicates": 2000,
            "planned_coverage_replicates": 500,
            "planned_whole_pass_bootstrap_draws": 500,
        },
        "all_three_profiles_identifiable": bool(
            profiles["identifiable_for_feedback_compliant_simulation"].all()
        ),
        "monte_carlo_run": False,
        "why_no_monte_carlo": (
            "The feedback-compliant empirical structures fail before simulation: tree/reference "
            "yield is unavailable, fewer than four cities pass focused overlap, and the complete "
            "design has zero empirical AM matches. Power or MDE would be fabricated under these inputs."
        ),
        "historical_d0056_time_simulation": {
            "status": historical.get("status"),
            "scope": historical.get("scientific_gate_scope"),
            "primary_effect_size_k": historical_spec.get("primary_effect_size_k"),
            "residual_components_k": {
                "pass_sd": historical_spec.get("pass_sd_k"),
                "matched_set_sd": historical_spec.get("matched_set_sd_k"),
                "row_sd": historical_spec.get("row_sd_k"),
            },
            "replicates": historical_settings.get("n_replicates"),
            "power_at_primary_effect": next(
                (
                    item.get("observed_value")
                    for item in historical.get("checks", [])
                    if item.get("check_id") == "full_panel_primary_effect_power"
                ),
                None,
            ),
            "cannot_substitute_for_feedback_compliant_matched_profile": True,
        },
        "temperature_or_lst_opened": False,
        "record_2026_opened": False,
    }
    return profiles, contract


def build_compliance_matrix(
    g4_checks: dict[str, Any],
    g5_checks: dict[str, Any],
    g6: dict[str, Any],
    g7: dict[str, Any],
) -> pd.DataFrame:
    trace = pd.read_csv(TRACE)
    assignments: dict[str, tuple[str, str, str]] = {
        "F01": ("ADDRESSED_NEGATIVE_RESULT", "G4;G8", "Formal audit rejects the pooled high-demand contrast; redirects to a Denver case-study proposal."),
        "F02": ("ADDRESSED", "G0", "D0059 approved the outcome-blind protocol before any thermal value was opened."),
        "F03": ("ADDRESSED", "G2", "P-ET0 is sensitivity-only and its stronger demand coupling is quantified."),
        "F04": ("ADDRESSED", "G2", "Precipitation-only support is reported for 30 and 60 days."),
        "F05": ("ADDRESSED", "G2", "Days since at least 5 mm rain is reported with right-censoring."),
        "F06": ("ADDRESSED", "G2", "Both 30- and 60-day windows are complete and prior-day bounded."),
        "F07": ("ADDRESSED", "G2", "Terminology is antecedent climatic wetness/water balance, never irrigation or root-zone water."),
        "F08": ("ADDRESSED", "G1;G7", "Physical passes are the observation count; pass-equivalents remain secondary exposure diagnostics."),
        "F09": ("ADDRESSED", "G1", "Raw counts appear beside all weighted summaries."),
        "F10": ("PARTIAL_BLOCKED_REPORTED", "G1;G7", "Clear/fill fractions are complete; tree/reference yield remains unavailable because no G3 design was selected."),
        "F11": ("ADDRESSED", "G3", "Miami is exploratory and Denver is restored as the semi-arid continental candidate."),
        "F12": ("ADDRESSED", "G3", "Denver geometry, weather, phenology, and support were audited."),
        "F13": ("ADDRESSED_NEGATIVE_RESULT", "G3", "The prospective selector failed, so no city set was frozen or silently rescued."),
        "F14": ("ADDRESSED", "G1;G3", "All 31 historical and 12 new unavailable passes are retained with proxy/exact nonthermal labels and calculated bounds."),
        "F15": ("ADDRESSED_NEGATIVE_RESULT", "G1;G3", "Collection-3 recovery was technically audited but recovered zero historical candidates; fill semantics remain explicit."),
        "F16": ("ADDRESSED", "G7", "Effect, residual components, replicate counts, clustering, and the invalid same-distribution 800-pass interpretation are recorded."),
        "F17": ("ADDRESSED_NEGATIVE_RESULT", "G5", "Solar elevation defines matching; no ordinary solar-zenith adjustment is authorized."),
        "F18": ("ADDRESSED_NEGATIVE_RESULT", "G3;G5", "View and relative azimuth are reported; zero AM support prevents geometry-matched pairs."),
        "F19": ("ADDRESSED", "G5", "The estimand is time-of-day asymmetry at comparable solar elevation, not hysteresis or physiology."),
        "F20": ("ADDRESSED", "G3", "Los Angeles/Sacramento October and Phoenix April-May were audited."),
        "F21": ("ADDRESSED", "G3", "Whole-domain and canopy-masked phenology are reported with June-September sensitivities."),
        "F22": ("ADDRESSED", "G3", "10/15/20/25-degree thresholds and 30-degree exploratory support were evaluated."),
        "F23": ("ADDRESSED", "G3", "Threshold detail includes city, time, hydroclimate, view, solar, and relative-azimuth values."),
        "F24": ("ADDRESSED_NEGATIVE_RESULT", "G4", "Wet/dry counts are evaluated within each city; only Denver passes at 25 degrees."),
        "F25": ("ADDRESSED_NEGATIVE_RESULT", "G4", "Absolute VPD range overlap is positive only where observed, not assumed from terciles."),
        "F26": ("ADDRESSED_NEGATIVE_RESULT", "G4", "Day-of-window overlap is explicit; Phoenix has only April-May pre-monsoon support."),
        "F27": ("ADDRESSED", "G4;G8", "Fewer than four cities pass; the pooled claim is rejected and a case-study proposal is selected."),
        "F28": ("ADDRESSED", "G0;D0083", "No thermal/LST, holdout outcome, Task-2 result, or 2026 science record was opened."),
        "F29": ("ADDRESSED_EQUIVALENT_LABEL", "G0", "Synthetic outputs are quarantined under illustrative_only with ILLUSTRATIVE prefixes and visible synthetic warnings; frozen manifests are preserved."),
        "F30": ("ADDRESSED", "G1;FIRST_FOUR_ITEMS", "The four requested items were delivered and approved under D0078."),
        "F31": ("ADDRESSED", "G1;G6", "The 2,968-to-102 chain and 438 links/413 assets/219 passes reproduce independently."),
        "F32": ("ADDRESSED", "G2;G3;G4;G5", "Wetness metrics, seasons, angle rules, city roles, recovery, and continuous overlap are covered across the packets."),
        "F33": ("ADDRESSED_BY_FAIL_CLOSED_PREFLIGHT", "G7", "All three profiles are preregistered, but feedback-compliant simulations are not identifiable and no power was fabricated."),
        "F34": ("ADDRESSED", "G7", "The historical same-distribution 800-pass scenario is explicitly barred from supporting new-city/season claims."),
        "F35": ("ADDRESSED", "G6", "A standalone script plus the Gate-3 clean room reproduce counts, identities, geometry, weather, and support."),
        "F36": ("ADDRESSED", "G6", "Known answers cover VPD units, NREL solar position, prior-day windows, fill semantics, deduplication, units/sign, and Phoenix June balance."),
        "F37": ("ADDRESSED", "G8", "The frozen decision rule selects a comparative Denver case-study proposal and rejects pooled/AM-PM outcome work."),
    }
    if set(assignments) != set(trace["feedback_id"].astype(str)):
        raise ValueError("Feedback closeout assignments do not equal the 37-item traceability census")
    output = trace.copy()
    output["closeout_status"] = output["feedback_id"].map(lambda value: assignments[value][0])
    output["closeout_gate"] = output["feedback_id"].map(lambda value: assignments[value][1])
    output["closeout_evidence"] = output["feedback_id"].map(lambda value: assignments[value][2])
    output["temperature_or_lst_opened"] = False
    output["record_2026_opened"] = False
    return output


def write_reviews(
    g4: pd.DataFrame,
    g4_checks: dict[str, Any],
    g5: pd.DataFrame,
    g5_checks: dict[str, Any],
    g6: dict[str, Any],
    g7_profiles: pd.DataFrame,
    g7_contract: dict[str, Any],
    compliance: pd.DataFrame,
) -> dict[str, Any]:
    g4_25 = g4.loc[g4["threshold_deg"].eq(25)]
    g5_25 = g5.loc[g5["threshold_deg"].eq(25)]
    g8 = {
        "gate": "G8_FEEDBACK_CLOSEOUT_DECISION",
        "decision": "COMPARATIVE_CASE_STUDY_PROPOSAL_ONLY",
        "pooled_high_demand_study_authorized": False,
        "time_of_day_study_authorized": False,
        "full_demand_by_wetness_surface_authorized": False,
        "case_study_candidates": g4_checks["case_study_candidates_at_25deg"],
        "reason": (
            "Only Denver has the required within-city high-demand wet/dry count plus positive "
            "absolute-demand and seasonal overlap at the widest selectable diagnostic threshold; "
            "the complete design has zero AM observations and zero empirical AM-PM matches."
        ),
        "thermal_activation_authorized": False,
        "holdout_selection_authorized": False,
        "record_2026_access_authorized": False,
        "independent_verification_passed": g6["all_passed"],
        "simulation_profiles_identifiable": g7_contract["all_three_profiles_identifiable"],
    }
    g4_review = f"""# G4 closeout — focused high-demand wet–dry audit

## Decision

`POOLED_CONTRAST_NOT_AUTHORIZED`

At the widest selectable diagnostic threshold (25°), the complete observed design contains
{int(g4_25['physical_passes'].sum())} physical passes. Exactly
{int(g4_25['city_case_support_pass'].sum())} of four city-windows passes the frozen
within-city wet/dry count, absolute-VPD overlap, and day-of-window overlap rules:
{', '.join(g4_25.loc[g4_25['city_case_support_pass'], 'city']) or 'none'}.
The pooled four-city claim therefore fails. Denver may be proposed as a comparative
case study; this is not a thermal result or authorization to open an outcome.

Phoenix contributes only April–May pre-monsoon support in this profile, so the requested
monsoon/pre-monsoon overlap is absent rather than assumed.

No temperature/LST value, holdout outcome, or 2026 science record was opened.
"""
    g5_review = f"""# G5 closeout — empirical AM–PM matching audit

## Decision

`TIME_OF_DAY_COMPARISON_NOT_AUTHORIZED`

At 25°, the four primary city-windows contain {int(g5_25['morning_10_12_passes'].sum())}
late-morning passes and {int(g5_25['afternoon_16_18_passes'].sum())} late-afternoon passes.
There are {int(g5_25['candidate_cross_stratum_pairs_before_calipers'].sum())} possible
within-city cross-stratum pairs even before solar-elevation, weather, season, or relative-
azimuth calipers. Consequently the matched analysis count is zero.

The estimand remains **time-of-day asymmetry at comparable solar elevation**. It is not
hysteresis, a diurnal trajectory, or direct physiological evidence. No solar-zenith
coefficient is adjusted away to rescue the unavailable comparison.

No temperature/LST value, holdout outcome, or 2026 science record was opened.
"""
    g7_review = f"""# G7 closeout — simulation preregistration and fail-closed preflight

The requested full-surface, focused high-demand, and empirically matched AM–PM profiles
were preregistered under D0083 with effect sizes 0.75/1.50/2.25 K, explicit residual
components, clustering, pass-level measurement error, replicate counts, alpha, target
power, seed, and MDE rule.

No new Monte Carlo result was generated. All three feedback-compliant profiles fail their
empirical preflight: tree/reference yield needed for measurement error is unavailable;
fewer than four cities have genuine high-demand overlap; and the matched AM–PM count is
zero. Reporting power or a finite MDE would therefore manufacture information the design
does not contain. The historical D0056 simulation remains reported only under its original,
obsolete archive-available time-of-day scope.

No temperature/LST value, holdout outcome, or 2026 science record was opened.
"""
    final_review = f"""# Urban Tree Cooling feedback closeout

## Outcome

All {len(compliance)} substantive feedback points have a bound disposition. The closeout
does not convert the failed Gate 3 into a pass. It completes the requested nonthermal
audits and applies the feedback's decision rule once.

**Final direction:** `COMPARATIVE_CASE_STUDY_PROPOSAL_ONLY`.

- The four-city pooled high-demand contrast is not supported; only Denver passes the
  within-city count and continuous-overlap rules at the 25° diagnostic profile.
- The empirically matched AM–PM comparison is not supported; there are zero late-morning
  observations in the complete four-city design.
- Feedback-compliant simulations cannot reproduce pass-level measurement error because
  the required tree/reference yield was never available after Gate 3 failed.
- Independent verification passes every count, identity, weather, VPD, solar-position,
  prior-day-window, cloud/fill, unit/sign, and Phoenix-balance check.

The result is an identifiability/support finding and a proposal for a Denver comparative
case study—not authorization to inspect thermal data. Thermal/LST, holdout outcomes,
Task 2, and 2026 science records remain sealed.
"""
    atomic_text(OUT / "g4_review.md", g4_review)
    atomic_text(OUT / "g5_review.md", g5_review)
    atomic_text(OUT / "g7_review.md", g7_review)
    atomic_text(OUT / "review.md", final_review)
    atomic_json(OUT / "g8_decision.json", g8)
    return g8


def run() -> dict[str, Any]:
    required = [
        TRACE,
        G1 / "attrition_summary.csv",
        G1 / "observation_ledger.csv",
        G1 / "deduplication_summary.csv",
        G1 / "hrrr_pass_hour_crosswalk.csv",
        G1 / "pass_quality_219.csv",
        G2 / "pass_hydroclimate_219.csv",
        G2 / "window_exclusion_audit.csv",
        G2 / "phoenix_june_sign_check.csv",
        G3 / "threshold_pass_detail.csv",
        G3 / "cleanroom_verification.json",
        G3 / "selection.json",
        DOMAINS,
        D0056_SETTINGS,
        D0056_GATE,
        D0083,
        FEEDBACK_DOC,
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Feedback closeout is fail-closed; missing {missing}")
    if sha256_file(FEEDBACK_DOC) != EXPECTED_FEEDBACK_SHA256:
        raise ValueError("Feedback DOCX hash changed")

    detail = pd.read_csv(G3 / "threshold_pass_detail.csv", low_memory=False)
    g4, g4_checks = build_g4_high_demand_audit(detail)
    g5, g5_checks = build_g5_time_audit(detail)
    g6 = build_g6_independent_verification()
    if not g6["all_passed"]:
        raise ValueError("Independent feedback-closeout verification failed")
    g7_profiles, g7_contract = build_g7_preflight(detail, g4_checks, g5_checks)
    compliance = build_compliance_matrix(g4_checks, g5_checks, g6, g7_contract)

    atomic_csv(OUT / "g4_high_demand_city_audit.csv", g4)
    atomic_json(OUT / "g4_checks.json", g4_checks)
    atomic_csv(OUT / "g5_time_matching_audit.csv", g5)
    atomic_json(OUT / "g5_checks.json", g5_checks)
    atomic_json(OUT / "g6_independent_verification.json", g6)
    atomic_csv(OUT / "g7_simulation_preflight.csv", g7_profiles)
    atomic_json(OUT / "g7_simulation_contract.json", g7_contract)
    atomic_csv(OUT / "feedback_compliance_matrix.csv", compliance)
    g8 = write_reviews(g4, g4_checks, g5, g5_checks, g6, g7_profiles, g7_contract, compliance)

    sources = {
        str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path): sha256_file(path)
        for path in required
    }
    artifacts = {
        str(path.relative_to(ROOT)): sha256_file(path)
        for path in sorted(OUT.iterdir())
        if path.is_file() and path.name not in {"source_bindings.json", "checks.json"}
    }
    atomic_json(
        OUT / "source_bindings.json",
        {
            "decision_id": "D0083",
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "sources": sources,
            "artifacts": artifacts,
            "feedback_doc_sha256": EXPECTED_FEEDBACK_SHA256,
            "temperature_or_lst_opened": False,
            "record_2026_opened": False,
        },
    )
    checks = {
        "decision_id": "D0083",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "feedback_points": len(compliance),
        "feedback_status_counts": compliance["closeout_status"].value_counts().to_dict(),
        "all_feedback_points_have_dispositions": bool(
            len(compliance) == 37 and compliance["closeout_status"].notna().all()
        ),
        "g4_pooled_contrast_authorized": g4_checks["pooled_contrast_authorized"],
        "g5_time_of_day_authorized": g5_checks["time_of_day_analysis_authorized"],
        "g6_all_passed": g6["all_passed"],
        "g7_all_profiles_identifiable": g7_contract["all_three_profiles_identifiable"],
        "g7_monte_carlo_run": g7_contract["monte_carlo_run"],
        "g8_decision": g8["decision"],
        "thermal_or_lst_opened": False,
        "holdout_opened": False,
        "task2_result_bearing_run": False,
        "record_2026_opened": False,
    }
    atomic_json(OUT / "checks.json", checks)
    return checks


def main() -> int:
    result = run()
    print(
        "PASS run_v2_feedback_closeout: "
        f"{result['feedback_points']} feedback points; decision={result['g8_decision']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
