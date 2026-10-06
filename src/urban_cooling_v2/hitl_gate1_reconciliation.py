"""Build the nonthermal Gate-1 observation reconciliation package.

The package is deliberately outcome blind.  It reads catalogue metadata,
geometry/cloud quality counts, HRRR metadata, and Step-1 condition axes; it
never opens an ECOSTRESS LST or other thermal value layer.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .step02_catalog import condition_cell, local_solar_dates


CATALOGUE_REL = Path(
    "data/processed/v2/task1/step2_definitive_l1b_geo_D0047_archive_available/"
    "tables/step2_scene_catalogue.csv"
)
RAW_CATALOGUE_REL = Path("data/raw/v2/ecostress/catalogue_tiles_2018_2025.csv")
HRRR_MANIFEST_REL = Path(
    "data/raw/v2/weather/"
    "hrrr_exact_acquisition_l1b_geo_D0047_archive_available_manifest.csv"
)
HRRR_SUMMARY_REL = Path(
    "data/raw/v2/weather/"
    "hrrr_exact_acquisition_l1b_geo_D0047_archive_available/"
    "hrrr_hourly_domain_summary.csv"
)
STEP1_REL = Path("data/processed/v2/step1_condition_axes.csv")
C3_AUDIT_REL = Path(
    "docs/v2/hitl/G1_OBSERVATION_RECONCILIATION/source_evidence/"
    "collection3_cmr_audit.json"
)
C3_2020_RAW_REL = Path(
    "docs/v2/hitl/G1_OBSERVATION_RECONCILIATION/source_evidence/"
    "cmr_collection3_historical_summer_2020.json"
)
C3_2024_RAW_REL = Path(
    "docs/v2/hitl/G1_OBSERVATION_RECONCILIATION/source_evidence/"
    "cmr_collection3_historical_summer_2024.json"
)
D0060_REL = Path("docs/v2/D0060_G1_2026_METADATA_QUERY_DEVIATION.md")
D0061_REL = Path("docs/v2/D0061_G1_UNBOUNDED_CMR_PATTERN_DEVIATION.md")
QUARANTINED_2026_CMR_REL = Path(
    "docs/v2/hitl/G1_OBSERVATION_RECONCILIATION/source_evidence/"
    "protocol_deviation_quarantine/"
    "DO_NOT_USE_unbounded_pattern_11645_returned_2026_metadata.json"
)
OUTPUT_REL = Path("docs/v2/hitl/G1_OBSERVATION_RECONCILIATION")
GENERATOR_REL = Path("src/urban_cooling_v2/hitl_gate1_reconciliation.py")
RUNNER_REL = Path("src/run_v2_hitl_gate1.py")

PRIMARY_TIME_STRATA = ("10-12", "16-18")
VIEW_P95_THRESHOLD_DEG = 20.0
MINIMUM_VIEW_COVERAGE = 0.95


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    frame.to_csv(temporary, index=False, float_format="%.15g")
    temporary.replace(path)


def _atomic_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _atomic_json(value: Any, path: Path) -> None:
    _atomic_text(json.dumps(value, indent=2, sort_keys=True) + "\n", path)


def _utc(values: Iterable[Any]) -> pd.Series:
    try:
        converted = pd.to_datetime(values, utc=True, errors="raise", format="mixed")
    except TypeError:  # pragma: no cover - older pandas compatibility
        converted = pd.to_datetime(values, utc=True, errors="raise")
    return pd.Series(converted)


def _utc_text(values: Iterable[Any]) -> pd.Series:
    return _utc(values).dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _bool(frame: pd.DataFrame, column: str) -> pd.Series:
    return frame[column].eq(True)  # noqa: E712 - explicit nullable-boolean rule


def _split_count(values: pd.Series) -> pd.Series:
    return values.fillna("").astype(str).map(
        lambda value: 0 if not value else len(value.split("|"))
    )


def _observation_ids(frame: pd.DataFrame) -> pd.Series:
    """Build an explicit city-orbit-scene-group identifier."""

    def normalized_scenes(value: Any) -> str:
        parts = str(value).split("|")
        normalized = [f"{int(part):03d}" if part.isdigit() else part for part in parts]
        return "-".join(normalized)

    cities = frame["city"].astype(str)
    orbits = pd.to_numeric(frame["orbit"], errors="raise").astype(int).map(
        lambda value: f"{value:05d}"
    )
    scenes = frame["scene"].map(normalized_scenes)
    return cities + "|orbit_" + orbits + "|scenes_" + scenes


def _levels(values: pd.Series) -> tuple[pd.Series, pd.Series]:
    parts = values.str.extract(r"demand_(low|middle|high)__antecedent_(wet|middle|dry)")
    return parts[0], parts[1]


def classify_final_status(frame: pd.DataFrame) -> pd.Series:
    """Assign one mutually exclusive Gate-1 status to each observation."""

    day = _bool(frame, "daytime")
    geolocation = _bool(frame, "geolocation_usable")
    metadata = _bool(frame, "metadata_candidate")
    archive = _bool(frame, "d0047_profile_included")
    geometry = _bool(frame, "quality_candidate_pre_cloud_l1b")
    early_late = geometry & frame["time_stratum"].isin(PRIMARY_TIME_STRATA)
    status = pd.Series(pd.NA, index=frame.index, dtype="string")
    status.loc[~day] = "outside_daytime_10_18"
    status.loc[day & ~geolocation] = "daytime_geolocation_excluded"
    status.loc[day & geolocation & ~metadata] = (
        "daytime_metadata_or_obstruction_excluded"
    )
    status.loc[metadata & ~archive] = "archive_unavailable_pre_geometry"
    for geometry_status in (
        "coverage_and_angle_fail",
        "angle_fail",
        "coverage_fail",
    ):
        mask = archive & frame["l1b_geometry_status"].eq(geometry_status)
        status.loc[mask] = f"geometry_{geometry_status}"
    status.loc[geometry & ~early_late] = "retained_midday_not_early_late"
    status.loc[early_late] = "retained_early_late_stratum_eligible"
    return status


def expand_hrrr_brackets(passes: pd.DataFrame) -> pd.DataFrame:
    """Expand acquisitions to unique floor/ceiling HRRR pass-hour links."""

    required = {"observation_id", "city", "acquisition"}
    missing = required - set(passes.columns)
    if missing:
        raise ValueError(f"passes lacks {sorted(missing)}")
    work = passes[["observation_id", "city", "acquisition"]].copy()
    work["acquisition"] = _utc(work["acquisition"]).to_numpy()
    floor = work.copy()
    floor["analysis_utc"] = floor["acquisition"].dt.floor("h")
    floor["bracket_role"] = "floor"
    ceiling = work.copy()
    ceiling["analysis_utc"] = ceiling["acquisition"].dt.ceil("h")
    ceiling["bracket_role"] = "ceiling"
    links = pd.concat([floor, ceiling], ignore_index=True)
    exact = links["analysis_utc"].eq(links["acquisition"])
    links.loc[exact, "bracket_role"] = "exact"
    return links.drop_duplicates(["observation_id", "analysis_utc"]).reset_index(
        drop=True
    )


def validated_clear_domain_weights(frame: pd.DataFrame) -> pd.Series:
    """Validate and return the frozen per-pass clear-domain weights."""

    numerator = pd.to_numeric(
        frame["n_clear_pixels_independent_of_view"], errors="raise"
    )
    denominator = pd.to_numeric(frame["n_domain_pixels_cloud"], errors="raise")
    weights = pd.to_numeric(frame["clear_domain_fraction"], errors="raise")
    if (denominator <= 0).any() or not np.allclose(
        weights.to_numpy(dtype=float),
        (numerator / denominator).to_numpy(dtype=float),
        rtol=0,
        atol=5e-15,
    ):
        raise ValueError("clear-domain weights do not equal clear/domain pixel counts")
    return weights


def build_observation_ledger(
    catalogue: pd.DataFrame, raw_catalogue: pd.DataFrame
) -> pd.DataFrame:
    """Return one row per physical city-orbit observation.

    Adjacent ECOSTRESS scenes and MGRS tiles are kept as provenance fields but
    do not create additional observational units.
    """

    if len(catalogue) != 2968:
        raise ValueError(f"expected 2,968 catalogue observations, found {len(catalogue)}")
    if catalogue["scene_key"].isna().any() or catalogue["scene_key"].duplicated().any():
        raise ValueError("scene_key must be complete and unique")
    if catalogue.duplicated(["city", "orbit"]).any():
        raise ValueError("catalogue contains duplicate city-orbit observations")

    raw_counts = (
        raw_catalogue.groupby(["city", "orbit"], sort=False)
        .size()
        .rename("n_granule_products_before_revision_selection")
        .reset_index()
    )
    work = catalogue.merge(
        raw_counts, how="left", on=["city", "orbit"], validate="one_to_one"
    )
    if work["n_granule_products_before_revision_selection"].isna().any():
        raise ValueError("raw catalogue is missing a city-orbit group")

    acquisition = _utc(work["acquisition_utc"])
    local_dates = local_solar_dates(
        acquisition, pd.to_numeric(work["centroid_longitude"], errors="raise")
    )
    day = _bool(work, "daytime")
    geolocation = _bool(work, "geolocation_usable")
    metadata = _bool(work, "metadata_candidate")
    archive = _bool(work, "d0047_profile_included")
    geometry = _bool(work, "quality_candidate_pre_cloud_l1b")
    cloud = _bool(work, "cloud_asset_complete") & _bool(work, "provenance_complete")
    early_late = geometry & work["time_stratum"].isin(PRIMARY_TIME_STRATA)

    status = classify_final_status(work)
    if status.isna().any():
        unresolved = work.loc[status.isna(), ["scene_key", "l1b_geometry_status"]]
        raise ValueError(f"unclassified observations: {unresolved.head().to_dict('records')}")

    observation_ids = _observation_ids(work)
    if observation_ids.duplicated().any():
        raise ValueError("city-orbit-scene-group identifiers must be unique")
    ledger = pd.DataFrame(
        {
            "observation_id": observation_ids,
            "source_scene_key": work["scene_key"].astype(str),
            "observation_unit": "physical_city_orbit_observation",
            "city": work["city"].astype(str),
            "orbit": pd.to_numeric(work["orbit"], errors="raise").astype(int),
            "scene_labels": work["scene"].astype(str),
            "official_orbit_scene_key": work["official_orbit_scene_key"],
            "acquisition_utc": _utc_text(acquisition),
            "local_solar_date": pd.Series(local_dates).astype(str),
            "acquisition_year": acquisition.dt.year.astype(int),
            "acquisition_month": acquisition.dt.month.astype(int),
            "local_solar_time_hours": work["local_solar_time_hours"],
            "time_stratum": work["time_stratum"],
            "n_granule_products_before_revision_selection": work[
                "n_granule_products_before_revision_selection"
            ].astype(int),
            "n_granule_products_selected": _split_count(work["granule_id"]).astype(int),
            "n_intersecting_scenes": pd.to_numeric(
                work["n_intersecting_scenes"], errors="raise"
            ).astype(int),
            "n_intersecting_tiles": pd.to_numeric(
                work["n_intersecting_tiles"], errors="raise"
            ).astype(int),
            "selected_granule_ids": work["granule_id"].astype(str),
            "is_daytime_10_18": day,
            "geolocation_usable": geolocation,
            "metadata_candidate": metadata,
            "archive_available_for_l1b_geometry": archive,
            "l1b_geometry_status": work["l1b_geometry_status"],
            "geometry_pass": geometry,
            "cloud_and_provenance_complete": cloud,
            "early_late_stratum_eligible": early_late,
            "final_reconciliation_status": status,
            "clear_domain_fraction": pd.to_numeric(
                work["clear_domain_fraction"], errors="coerce"
            ),
        }
    )
    if ledger["n_granule_products_selected"].sum() != 13575:
        raise ValueError("selected tiled-product identity does not equal 13,575")
    return ledger


def build_deduplication_summary(
    raw_catalogue: pd.DataFrame, ledger: pd.DataFrame
) -> pd.DataFrame:
    selected_ids = {
        item
        for value in ledger["selected_granule_ids"]
        for item in str(value).split("|")
    }
    selected = raw_catalogue["granule_id"].isin(selected_ids)
    rows: list[dict[str, Any]] = []
    for city in ["ALL_CITIES", *sorted(raw_catalogue["city"].unique())]:
        raw_mask = pd.Series(True, index=raw_catalogue.index)
        ledger_mask = pd.Series(True, index=ledger.index)
        if city != "ALL_CITIES":
            raw_mask = raw_catalogue["city"].eq(city)
            ledger_mask = ledger["city"].eq(city)
        rows.append(
            {
                "city": city,
                "raw_domain_intersecting_tiled_products": int(raw_mask.sum()),
                "selected_latest_revision_tiled_products": int(
                    (raw_mask & selected).sum()
                ),
                "superseded_tiled_products_removed": int(
                    (raw_mask & ~selected).sum()
                ),
                "physical_city_orbit_observations": int(ledger_mask.sum()),
                "unit_rule": (
                    "latest revision per scene/tile, then group all adjacent scenes and "
                    "tiles sharing city and orbit into one physical observation"
                ),
            }
        )
    result = pd.DataFrame(rows)
    overall = result.loc[result["city"].eq("ALL_CITIES")].iloc[0]
    if (
        int(overall["raw_domain_intersecting_tiled_products"]) != 13577
        or int(overall["selected_latest_revision_tiled_products"]) != 13575
        or int(overall["physical_city_orbit_observations"]) != 2968
    ):
        raise ValueError("deduplication census does not match the frozen catalogue")
    return result


def _stage_masks(ledger: pd.DataFrame) -> list[tuple[str, pd.Series]]:
    return [
        ("physical_city_orbit_observations", pd.Series(True, index=ledger.index)),
        ("daytime_10_18_local_solar", ledger["is_daytime_10_18"]),
        ("geolocation_usable", ledger["geolocation_usable"]),
        ("metadata_and_obstruction_screen", ledger["metadata_candidate"]),
        (
            "archive_available_pre_geometry",
            ledger["archive_available_for_l1b_geometry"],
        ),
        ("geometry_pass_p95_le_20_and_coverage_ge_0_95", ledger["geometry_pass"]),
        ("cloud_and_provenance_complete_physical", ledger["cloud_and_provenance_complete"]),
        (
            "early_late_stratum_eligible_10_12_or_16_18_prior_to_matching",
            ledger["early_late_stratum_eligible"],
        ),
    ]


def build_attrition_summary(
    raw_catalogue: pd.DataFrame, ledger: pd.DataFrame
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = [
        {
            "stage_order": 0,
            "stage": "raw_domain_intersecting_tiled_products",
            "physical_count": len(raw_catalogue),
            "count_unit": "tiled_granule_product",
            "pass_equivalent_sum": np.nan,
            "pass_equivalent_role": "not_defined",
        },
        {
            "stage_order": 1,
            "stage": "selected_latest_revision_tiled_products",
            "physical_count": int(ledger["n_granule_products_selected"].sum()),
            "count_unit": "tiled_granule_product",
            "pass_equivalent_sum": np.nan,
            "pass_equivalent_role": "not_defined",
        },
    ]
    for offset, (stage, mask) in enumerate(_stage_masks(ledger), start=2):
        weights = pd.to_numeric(
            ledger.loc[mask, "clear_domain_fraction"], errors="coerce"
        )
        weight_defined = stage in {
            "geometry_pass_p95_le_20_and_coverage_ge_0_95",
            "cloud_and_provenance_complete_physical",
            "early_late_stratum_eligible_10_12_or_16_18_prior_to_matching",
        }
        rows.append(
            {
                "stage_order": offset,
                "stage": stage,
                "physical_count": int(mask.sum()),
                "count_unit": "physical_city_orbit_observation",
                "pass_equivalent_sum": (
                    float(weights.sum()) if weight_defined else np.nan
                ),
                "pass_equivalent_role": (
                    "secondary_clear_domain_exposure_diagnostic"
                    if weight_defined
                    else "not_defined"
                ),
            }
        )
    result = pd.DataFrame(rows)
    result["retention_from_previous_physical_pct"] = np.nan
    physical = result["physical_count"].astype(float)
    for index in range(1, len(result)):
        previous = physical.iloc[index - 1]
        if result.loc[index, "count_unit"] == result.loc[index - 1, "count_unit"]:
            result.loc[index, "retention_from_previous_physical_pct"] = (
                100.0 * physical.iloc[index] / previous
            )
    return result


def build_attrition_breakdown(ledger: pd.DataFrame) -> pd.DataFrame:
    dimensions = {
        "city": ledger["city"].astype(str),
        "acquisition_year": ledger["acquisition_year"].astype(str),
        "acquisition_month": ledger["acquisition_month"].astype(str).str.zfill(2),
        "time_stratum": ledger["time_stratum"].fillna("outside_10_18").astype(str),
    }
    rows: list[dict[str, Any]] = []
    for dimension, values in dimensions.items():
        for stratum in sorted(values.unique()):
            group = values.eq(stratum)
            for stage_order, (stage, stage_mask) in enumerate(_stage_masks(ledger), start=1):
                combined = group & stage_mask
                weight_defined = stage in {
                    "geometry_pass_p95_le_20_and_coverage_ge_0_95",
                    "cloud_and_provenance_complete_physical",
                    "early_late_stratum_eligible_10_12_or_16_18_prior_to_matching",
                }
                rows.append(
                    {
                        "dimension": dimension,
                        "stratum": stratum,
                        "stage_order": stage_order,
                        "stage": stage,
                        "physical_observation_count": int(combined.sum()),
                        "pass_equivalent_sum": (
                            float(
                                pd.to_numeric(
                                    ledger.loc[combined, "clear_domain_fraction"],
                                    errors="coerce",
                                ).sum()
                            )
                            if weight_defined
                            else np.nan
                        ),
                    }
                )
    return pd.DataFrame(rows)


def build_hrrr_crosswalk(
    catalogue: pd.DataFrame,
    manifest: pd.DataFrame,
    hourly_summary: pd.DataFrame,
) -> pd.DataFrame:
    retained = catalogue.loc[_bool(catalogue, "quality_candidate_pre_cloud_l1b")].copy()
    retained["observation_id"] = _observation_ids(retained)
    retained["acquisition"] = _utc(retained["acquisition_utc"]).to_numpy()

    links = expand_hrrr_brackets(
        retained[["observation_id", "city", "acquisition"]]
    )

    request = manifest.copy()
    request["analysis_utc"] = _utc(request["analysis_utc"]).to_numpy()
    request = request.rename(
        columns={
            "item_id": "hrrr_item_id",
            "cities": "manifest_cities",
            "n_target_passes": "manifest_n_target_passes",
        }
    )
    links = links.merge(
        request[
            [
                "analysis_utc",
                "hrrr_item_id",
                "manifest_cities",
                "manifest_n_target_passes",
                "model",
                "product",
                "product_resolution",
                "object_key",
            ]
        ],
        how="left",
        on="analysis_utc",
        validate="many_to_one",
    )
    if links["hrrr_item_id"].isna().any():
        raise ValueError("HRRR crosswalk has an unmatched analysis hour")
    city_listed = [
        city in str(cities).split("|")
        for city, cities in zip(
            links["city"], links["manifest_cities"], strict=True
        )
    ]
    if not all(city_listed):
        raise ValueError("HRRR manifest does not list every linked city")

    link_count = links.groupby("analysis_utc")["observation_id"].transform("nunique")
    city_count = links.groupby("analysis_utc")["city"].transform("nunique")
    links["pass_links_at_analysis_hour"] = link_count.astype(int)
    links["cities_at_analysis_hour"] = city_count.astype(int)
    links["shared_across_cities"] = city_count.gt(1)
    if not np.array_equal(
        link_count.to_numpy(dtype=int),
        pd.to_numeric(links["manifest_n_target_passes"], errors="raise").to_numpy(dtype=int),
    ):
        raise ValueError("HRRR target-pass counts do not match the crosswalk")

    summary = hourly_summary.copy()
    summary["analysis_utc"] = _utc(summary["timestamp_utc"]).to_numpy()
    expected_pairs = links[["city", "analysis_utc"]].drop_duplicates()
    actual_pairs = summary[["city", "analysis_utc"]].drop_duplicates()
    pair_audit = expected_pairs.merge(
        actual_pairs, how="outer", on=["city", "analysis_utc"], indicator=True
    )
    if not pair_audit["_merge"].eq("both").all():
        raise ValueError("HRRR hourly city summaries do not match the crosswalk")

    result = links[
        [
            "observation_id",
            "city",
            "acquisition",
            "bracket_role",
            "analysis_utc",
            "hrrr_item_id",
            "model",
            "product",
            "product_resolution",
            "object_key",
            "manifest_n_target_passes",
            "pass_links_at_analysis_hour",
            "cities_at_analysis_hour",
            "shared_across_cities",
        ]
    ].copy()
    result["acquisition_utc"] = _utc_text(result.pop("acquisition"))
    result["analysis_utc"] = _utc_text(result["analysis_utc"])
    result["mapping_role"] = (
        "hourly_weather_asset_bracketing_physical_observation_not_an_observation"
    )
    result = result.sort_values(
        ["analysis_utc", "city", "observation_id", "bracket_role"]
    ).reset_index(drop=True)
    if len(result) != 438 or result["hrrr_item_id"].nunique() != 413:
        raise ValueError("expected 438 pass-hour links and 413 unique HRRR assets")
    if result.loc[result["shared_across_cities"], "hrrr_item_id"].nunique() != 25:
        raise ValueError("expected exactly 25 shared cross-city analysis hours")
    return result


def build_pass_quality(
    catalogue: pd.DataFrame, hrrr_crosswalk: pd.DataFrame
) -> pd.DataFrame:
    work = catalogue.loc[_bool(catalogue, "quality_candidate_pre_cloud_l1b")].copy()
    work["observation_id"] = _observation_ids(work)
    numerator = pd.to_numeric(work["n_clear_pixels_independent_of_view"], errors="raise")
    denominator = pd.to_numeric(work["n_domain_pixels_cloud"], errors="raise")
    weights = validated_clear_domain_weights(work)
    work["condition_cell"] = condition_cell(
        work["demand_percentile"], work["antecedent_dryness_percentile"]
    ).to_numpy()
    demand_level, dryness_level = _levels(work["condition_cell"])

    bracket = hrrr_crosswalk.pivot(
        index="observation_id", columns="bracket_role", values="hrrr_item_id"
    ).reset_index()
    if set(bracket.columns) != {"observation_id", "floor", "ceiling"}:
        raise ValueError("every retained pass must have floor and ceiling HRRR assets")

    result = pd.DataFrame(
        {
            "observation_id": work["observation_id"],
            "city": work["city"].astype(str),
            "orbit": pd.to_numeric(work["orbit"], errors="raise").astype(int),
            "official_orbit_scene_key": work["official_orbit_scene_key"],
            "acquisition_utc": _utc_text(work["acquisition_utc"]),
            "year": pd.to_numeric(work["year"], errors="raise").astype(int),
            "month": pd.to_numeric(work["month"], errors="raise").astype(int),
            "time_stratum": work["time_stratum"].astype(str),
            "early_late_stratum_eligible": work["time_stratum"].isin(
                PRIMARY_TIME_STRATA
            ),
            "l1b_geometry_coverage_fraction": work[
                "l1b_geometry_coverage_fraction"
            ],
            "l1b_view_zenith_abs_p95_deg": work[
                "l1b_view_zenith_abs_p95_deg"
            ],
            "applied_view_p95_threshold_deg": VIEW_P95_THRESHOLD_DEG,
            "applied_minimum_view_coverage": MINIMUM_VIEW_COVERAGE,
            "n_domain_pixels_cloud": denominator.astype(int),
            "n_cloud_observed_pixels_independent_of_view": pd.to_numeric(
                work["n_cloud_observed_pixels_independent_of_view"], errors="raise"
            ).astype(int),
            "n_clear_pixels_independent_of_view": numerator.astype(int),
            "n_cloud_pixels_independent_of_view": pd.to_numeric(
                work["n_cloud_pixels_independent_of_view"], errors="raise"
            ).astype(int),
            "n_cloud_invalid_or_fill_pixels_independent_of_view": pd.to_numeric(
                work["n_cloud_invalid_or_fill_pixels_independent_of_view"],
                errors="raise",
            ).astype(int),
            "clear_domain_fraction": weights,
            "pass_equivalent_weight_formula": (
                "n_clear_pixels_independent_of_view / n_domain_pixels_cloud"
            ),
            "pass_equivalent_role": (
                "secondary_clear_domain_exposure_diagnostic_not_independent_sample_size"
            ),
            "usable_tree_pixels": pd.array([pd.NA] * len(work), dtype="Int64"),
            "usable_reference_pixels": pd.array([pd.NA] * len(work), dtype="Int64"),
            "tree_reference_count_status": (
                "DEFERRED_TO_G3A_NONTHERMAL_TREE_REFERENCE_YIELD_CHECKPOINT"
            ),
            "vpd_kpa_at_acquisition": work["vpd_kpa_at_acquisition"],
            "demand_percentile": work["demand_percentile"],
            "antecedent_dryness_percentile": work[
                "antecedent_dryness_percentile"
            ],
            "demand_level": demand_level,
            "dryness_level": dryness_level,
            "condition_cell": work["condition_cell"],
            "cloud_asset_complete": _bool(work, "cloud_asset_complete"),
            "provenance_complete": _bool(work, "provenance_complete"),
        }
    )
    result = result.merge(bracket, how="left", on="observation_id", validate="one_to_one")
    return result.sort_values(["city", "acquisition_utc", "orbit"]).reset_index(drop=True)


def build_within_city_support(pass_quality: pd.DataFrame) -> pd.DataFrame:
    levels = ("low", "middle", "high")
    rows: list[dict[str, Any]] = []
    for city in ["ALL_CITIES", *sorted(pass_quality["city"].unique())]:
        city_data = pass_quality if city == "ALL_CITIES" else pass_quality.loc[
            pass_quality["city"].eq(city)
        ]
        for demand in levels:
            for dryness in ("wet", "middle", "dry"):
                cell = city_data.loc[
                    city_data["demand_level"].eq(demand)
                    & city_data["dryness_level"].eq(dryness)
                ]
                early_late = cell.loc[cell["early_late_stratum_eligible"]]
                rows.append(
                    {
                        "city": city,
                        "demand_level": demand,
                        "dryness_level": dryness,
                        "condition_cell": f"demand_{demand}__antecedent_{dryness}",
                        "retained_physical_passes": len(cell),
                        "retained_pass_equivalent_sum": float(
                            cell["clear_domain_fraction"].sum()
                        ),
                        "early_late_stratum_eligible_physical_passes": len(early_late),
                        "early_late_stratum_eligible_pass_equivalent_sum": float(
                            early_late["clear_domain_fraction"].sum()
                        ),
                    }
                )
    return pd.DataFrame(rows)


def build_missing_archive_audit(
    catalogue: pd.DataFrame, step1_conditions: pd.DataFrame
) -> pd.DataFrame:
    missing = catalogue.loc[catalogue["d0047_profile_included"].eq(False)].copy()
    if len(missing) != 31:
        raise ValueError(f"expected 31 archive-unavailable candidates, found {len(missing)}")
    missing["proxy_local_solar_date"] = local_solar_dates(
        _utc(missing["acquisition_utc"]),
        pd.to_numeric(missing["centroid_longitude"], errors="raise"),
    ).to_numpy()
    daily = step1_conditions.copy()
    daily["date"] = pd.to_datetime(daily["date"], errors="raise").dt.date
    proxy = missing.merge(
        daily[
            [
                "city",
                "date",
                "vpd_kpa",
                "demand_pct",
                "antecedent_dryness_30d_pct",
                "balance_30d_mm",
            ]
        ],
        how="left",
        left_on=["city", "proxy_local_solar_date"],
        right_on=["city", "date"],
        validate="many_to_one",
    )
    required = ["vpd_kpa", "demand_pct", "antecedent_dryness_30d_pct"]
    if proxy[required].isna().any().any():
        raise ValueError("daily Step-1 proxy is incomplete for missing candidates")
    proxy["proxy_condition_cell"] = condition_cell(
        proxy["demand_pct"], proxy["antecedent_dryness_30d_pct"]
    ).to_numpy()
    result = pd.DataFrame(
        {
            "observation_id": _observation_ids(proxy),
            "source_scene_key": proxy["scene_key"].astype(str),
            "city": proxy["city"].astype(str),
            "orbit": pd.to_numeric(proxy["orbit"], errors="raise").astype(int),
            "scene_labels": proxy["scene"].astype(str),
            "acquisition_utc": _utc_text(proxy["acquisition_utc"]),
            "year": _utc(proxy["acquisition_utc"]).dt.year.astype(int),
            "month": _utc(proxy["acquisition_utc"]).dt.month.astype(int),
            "time_stratum": proxy["time_stratum"].astype(str),
            "archive_exclusion_reason": proxy["d0047_exclusion_reason"].astype(str),
            "required_l1b_scene_count": proxy["d0047_required_scene_count"],
            "unavailable_l1b_scene_count": proxy["d0047_unavailable_scene_count"],
            "unavailable_l1b_scene_keys": proxy["d0047_unavailable_scene_keys"],
            "proxy_local_solar_date": proxy["proxy_local_solar_date"].astype(str),
            "proxy_daily_vpd_kpa": proxy["vpd_kpa"],
            "proxy_demand_percentile": proxy["demand_pct"],
            "proxy_antecedent_dryness_30d_percentile": proxy[
                "antecedent_dryness_30d_pct"
            ],
            "proxy_balance_30d_mm": proxy["balance_30d_mm"],
            "proxy_condition_cell": proxy["proxy_condition_cell"],
            "audit_item_status": "OPEN_WITH_PROXY_EVIDENCE",
            "proxy_only_not_acquisition_time_support": True,
            "definitive_acquisition_time_condition_cell_known": False,
            "geometry_outcome_known": False,
            "cloud_weight_known": False,
            "collection3_current_recovery_status": (
                "NO_HISTORICAL_CMR_GRANULE_RECHECK_AT_G3"
            ),
        }
    )
    return result.sort_values(["city", "acquisition_utc", "orbit"]).reset_index(drop=True)


def _input_bindings(root: Path) -> dict[str, dict[str, str]]:
    roles = {
        CATALOGUE_REL: "canonical 2,968-observation nonthermal catalogue",
        RAW_CATALOGUE_REL: "raw tiled-granule metadata census",
        HRRR_MANIFEST_REL: "unique HRRR hourly-asset request manifest",
        HRRR_SUMMARY_REL: "completed city-hour weather summaries",
        STEP1_REL: "daily condition axes used for the missing-31 proxy",
        C3_AUDIT_REL: "revised metadata-only Collection 3 audit",
        C3_2020_RAW_REL: "raw date-bounded CMR response body for summer 2020",
        C3_2024_RAW_REL: "raw date-bounded CMR response body for summer 2024",
        D0060_REL: "first 2026 metadata-query protocol-deviation record",
        D0061_REL: "second unbounded-query protocol-deviation record",
        GENERATOR_REL: "Gate-1 reconciliation implementation",
        RUNNER_REL: "Gate-1 reproducible runner",
    }
    return {
        path.as_posix(): {"sha256": sha256_file(root / path), "role": role}
        for path, role in roles.items()
    }


def _method_notes() -> str:
    return """# Gate 1 methods and count definitions

## Unit of observation and deduplication

The independent census unit in this checkpoint is one **physical city–orbit
observation**. A pass can intersect multiple adjacent ECOSTRESS scenes and MGRS tiles.
Those tiled products remain listed in the ledger for provenance, but they do not become
additional atmospheric situations. The raw metadata census contains 13,577 tiled product
records. Latest-revision selection removes two superseded records, leaving 13,575 selected
products grouped into 2,968 unique city–orbit observations.

The `observation_id` explicitly encodes city, zero-padded orbit, and the full adjacent-scene
group. The ledger also carries the upstream `scene_key`, official orbit–scene key where
enriched metadata exists, source-granule list, and counts before and after revision
selection.

## Attrition and applied view rule

All stage counts through 219 are physical observations. The definitive geometry rule was
applied on `ECO_L1B_GEO.002`: at least 0.95 valid domain coverage and pass-level p95 absolute
view zenith no greater than 20 degrees. The 31 candidates whose required L1B scene evidence
was unavailable were excluded before geometry; they were not assigned zero coverage and no
adjacent scene was substituted.

The 102 final records are **individual early/late-stratum-eligible physical passes** in the
10–12 or 16–18 local-solar-time strata. They are not 102 matched morning–afternoon pairs,
and Gate 1 establishes no empirical morning–afternoon comparability. The other 117 retained
passes are in the 12–14 or 14–16 midday strata.

## Pass-equivalent formula

For retained physical pass *i*:

`w_i = n_clear_pixels_independent_of_view_i / n_domain_pixels_cloud_i`

and the reported pass-equivalent exposure is `PE = sum_i(w_i)`. This produces 159.087084
for all 219 retained physical passes and 72.689029 for the 102 early/late-stratum-eligible
passes. It is a **secondary clear-domain exposure diagnostic**. Without usable
tree/reference counts and matching yields, it cannot quantify the reliability of a
within-pass cooling contrast. It is also not an independent observation count, an effective
sample size, or proof of 159 distinct atmospheric situations.

The per-pass table reports the clear-domain numerator, denominator, cloud/fill partition,
and fraction. Usable tree and reference pixel counts are explicitly unavailable at this
checkpoint; blank values are paired with a machine-readable status rather than treated as
zeros. They are assigned to the mandatory named `G3A_NONTHERMAL_TREE_REFERENCE_YIELD`
checkpoint. G3A will compute pre-outcome eligible tree/reference pixels and nonthermal
matching yields without reading a temperature/LST value, after G3 freezes the design and
before G4, G5, or G7 may proceed.

## Why 413 weather timestamps correspond to 219 passes

All 219 acquisition times fall between integer UTC hours. Linear interpolation therefore
uses a floor-hour and a ceiling-hour input for each pass: 438 pass–hour links. Twenty-five
analysis hours are shared by two cities, so deduplication yields 413 unique HRRR assets.
There are no same-city duplicate pass-hour links. HRRR timestamps count weather assets,
not satellite observations.

## Missing-31 audit

The missing-candidate table joins each candidate to the already frozen Step-1 daily
condition axes on local-solar date. The demand value is therefore a **daily proxy**, not
the acquisition-time HRRR value that would have been computed only after geometry passed.
The proxy can identify possible concentration but cannot reveal the definitive
acquisition-time condition cell, whether a missing candidate would pass geometry, its cloud
weight, or its eventual tree/reference support. The audit item therefore remains
`OPEN_WITH_PROXY_EVIDENCE`.

## Collection 3 semantics and current availability

The official Collection 3 tiled product documents separate `view_zenith.tif` and
`cloud.tif` assets. View-zenith NaN and cloud value 255 are fill/missing support and must
not be converted to a physical angle or cloud class. Two date-bounded CMR probes returned
no Collection 3 granules for the 2020 or 2024 study summers. Both raw response bodies and
their SHA-256 hashes are preserved. Thus Collection 3 is a technically valid future
recovery route, but it does not recover the 31 candidates now. Recheck at G3; do not
interpret the current zero as permanent absence.

## Protocol deviations

The first Gate-1 draft queried 2026 public granule metadata as a positive control, violating
the approved no-query boundary. During revision, an unbounded wildcard query separately
matched text inside ten 2026 acquisition timestamps. D0060 and D0061 record both events.
The responses are excluded from all counts and conclusions; one retained raw response is
quarantined solely as deviation evidence. No science-data link, temperature/LST value,
thermal outcome, holdout result, or 2026 science value was opened. Gate 1 therefore does
not claim clean protocol compliance.
"""


def _g3a_checkpoint_contract() -> str:
    return """# Mandatory later checkpoint — G3A nonthermal tree/reference yield

**Status:** `PLANNED_NOT_AUTHORIZED`  
**Placement:** after G3 freezes the sampling design and before G4, G5, or G7

## Purpose

Resolve the tree/reference evidence gap without inspecting temperature values. For every
G3-selected physical pass, compute pre-outcome eligible tree pixels, reference pixels, and
nonthermal matching yield.

## Permitted inputs

- the G3-frozen city, season, and view-angle design;
- checksum-bound tree/canopy, imperviousness, land-cover, water, building/buffer, and
  neighborhood masks;
- frozen geometry and cloud/fill masks; and
- a separately named retrieval-validity/QA layer only if the temperature/LST value band is
  technically blocked and never opened.

## Required outputs

- raw candidate tree and reference pixel counts per physical pass;
- counts after every nonthermal eligibility rule;
- eligible neighborhood and matched-set counts per pass;
- zero-yield and low-yield pass flags;
- physical pass counts beside all exposure summaries; and
- hashes proving that no temperature/LST value layer was accessed.

## Guardrails

No temperature/LST value, thermal outcome, 2026 record, or holdout outcome may be opened.
The checkpoint must stop for human approval. Its counts are pre-outcome eligibility/yield
counts, not cooling-contrast reliability estimates and not independent weather sample sizes.
"""


def _revision_response() -> str:
    return """# Gate 1 revision response

1. **2026 freeze:** D0060 and D0061 disclose two metadata-query deviations. The revised
   packet separates metadata exposure from unopened science data and does not claim full
   protocol compliance.
2. **Tree/reference counts:** the blank fields remain honest, and the mandatory named
   `G3A_NONTHERMAL_TREE_REFERENCE_YIELD` checkpoint now owns their nonthermal computation.
3. **The 102 count:** every headline now says 102 early/late-stratum-eligible individual
   passes prior to empirical matching, never 102 AM–PM pairs.
4. **Missing 31:** the item is `OPEN_WITH_PROXY_EVIDENCE`; daily Step-1 VPD cannot establish
   the definitive acquisition-time cell.
5. **Weight terminology:** pass-equivalents are a secondary clear-domain exposure
   diagnostic, not an outcome-reliability weight.
6. **Collection 3 preservation:** the date-bounded 2020 and 2024 raw CMR response bodies and
   SHA-256 hashes are source-bound. All 2026 responses are excluded; the unbounded false
   match is quarantined only as deviation evidence.
"""


def _review_markdown(
    missing: pd.DataFrame, support: pd.DataFrame, c3_audit: dict[str, Any]
) -> str:
    low_dry = support.loc[
        support["city"].eq("ALL_CITIES")
        & support["condition_cell"].eq("demand_low__antecedent_dry")
    ].iloc[0]
    missing_low_dry = int(
        missing["proxy_condition_cell"].eq("demand_low__antecedent_dry").sum()
    )
    return f"""# Gate 1 review — Revised complete observation reconciliation

**Gate status:** `REVISED_AWAITING_HUMAN_APPROVAL_WITH_RECORDED_PROTOCOL_DEVIATIONS`  
**Authorized by:** `D0059`; deviations recorded by `D0060` and `D0061`  
**Next gate remains locked:** `G2`

## Important protocol disclosure

Gate 1 does **not** claim clean compliance with the approved 2026 freeze. Two public CMR
metadata exposures occurred: the original 2026 positive-control query and a later unbounded
wildcard query that matched text inside 2026 timestamps. No science-data link or
temperature/LST value was opened, and neither response contributes to any count or
conclusion. The events and containment are preserved in D0060 and D0061.

## Bottom line

The complete nonthermal chain now reconciles without changing the frozen data rules:

`13,577 tiled records → 13,575 selected revisions → 2,968 physical city–orbit observations
→ 1,055 daytime → 1,017 geolocation-usable → 942 metadata candidates → 911 archive-available
→ 219 geometry/cloud-complete physical passes → 102 early/late-stratum-eligible individual
physical passes prior to empirical matching`.

The 219 retained physical passes carry **159.087084 pass-equivalents**, and the 102
early/late-stratum-eligible passes carry **72.689029**. Those weighted values are secondary
clear-domain exposure diagnostics, not outcome-reliability weights or independent sample
sizes. The
102 are not 102 matched morning–afternoon pairs.

## Four requested review items

1. **Attrition:** every one of the 2,968 observations has a mutually exclusive final status;
   the long breakdown covers city, year, month, and time stratum.
2. **Formula:** `w_i = clear domain pixels / domain pixels`; physical counts are reported
   next to every weighted sum.
3. **Applied view rule:** L1B-GEO valid-domain coverage ≥ 0.95 and pass-level p95 absolute
   view zenith ≤ 20°.
4. **Within-city wet/dry support:** all nine demand × dryness cells are present as explicit
   rows for each city and overall, including zeros and both full-retained and early/late
   eligibility counts prior to matching.

## What the reconciliation changes in our understanding

- The **413** HRRR number is fully explained: 438 floor/ceiling pass–hour links for 219
  fractional-hour acquisitions collapse to 413 unique assets because 25 hours are shared
  across two cities. It is not a pass count.
- The retained low-demand/dry corner has **{int(low_dry['retained_physical_passes'])} physical passes** but only
  **{float(low_dry['retained_pass_equivalent_sum']):.6f} pass-equivalents**. Cloud weighting therefore describes
  poor usable exposure; it must not erase the distinction between eight atmospheric events
  and roughly half a clear-domain equivalent.
- Of the 31 archive-unavailable candidates, **{missing_low_dry}** fall in that same corner
  under a clearly labelled daily Step-1 proxy. The item remains
  **`OPEN_WITH_PROXY_EVIDENCE`**: definitive acquisition-time membership, geometry, and
  cloud outcomes are unknown. If both eventually passed geometry, the physical candidate
  ceiling would rise from 8 to {8 + missing_low_dry}, but recovery is not demonstrated to
  restore support.
- Collection 3 has the correct tiled view/cloud variables and fill semantics in principle,
  but current CMR results contain no historical 2020 or 2024 granules for these candidates.
  Reprocessing should be checked again at G3. Current recovered count: **{c3_audit['gate1_conclusion']['missing_31_recovered']}**.

## Explicit limitations

- `usable_tree_pixels` and `usable_reference_pixels` are not available yet. They remain
  blank with an explicit status, never zero-filled. The mandatory named
  `G3A_NONTHERMAL_TREE_REFERENCE_YIELD` checkpoint will compute pre-outcome eligible counts
  without opening a temperature/LST value after G3 freezes the design and before G4/G5/G7.
- The missing-31 condition classification uses a daily proxy, not exact-acquisition HRRR.
- The Collection 3 finding is a timestamped current-availability audit, not a permanent
  archive claim.

## Data-access state

No ECOSTRESS temperature/LST value, thermal outcome, holdout result, or 2026 science value
was opened. However, 2026 **metadata were queried**, as disclosed above; the packet does not
label the 2026 record wholly unopened. R0015 and R0016 remain STOP, Task 2 remains disabled,
and the holdout remains `UNSELECTED`.

## Files to review

1. `attrition_summary.csv` — compact complete chain and count units.
2. `observation_ledger.csv` — all 2,968 physical observations and final statuses.
3. `within_city_wet_dry_support.csv` — raw and weighted support for every city/cell.
4. `pass_quality_219.csv` — per-pass geometry, cloud counts, weights, and support cells.
5. `hrrr_pass_hour_crosswalk.csv` — the 438-to-413 weather reconciliation.
6. `archive_missing_31_audit.csv` — candidate-level proxy audit and unknown-outcome flags.
7. `G3A_nonthermal_tree_reference_yield_checkpoint.md` — mandatory later count checkpoint.
8. `source_evidence/cmr_collection3_historical_summer_2020.json` and the corresponding 2024
   file — preserved raw historical CMR response bodies.
9. `revision_response.md`, `method_notes.md`, and `checks.json` — revisions, definitions,
   limitations, hashes, and assertions.

## Your decision

- `APPROVE G1` — bind this reconciliation and authorize G2 nonthermal hydroclimatic support only.
- `REVISE G1: <change>` — revise this package; do not begin G2.
- `STOP` — preserve all current locks and do not continue.
"""


def write_gate1_package(root: str | Path) -> dict[str, Any]:
    root_path = Path(root).resolve()
    output = root_path / OUTPUT_REL
    output.mkdir(parents=True, exist_ok=True)

    catalogue = pd.read_csv(root_path / CATALOGUE_REL, low_memory=False)
    raw_catalogue = pd.read_csv(root_path / RAW_CATALOGUE_REL, low_memory=False)
    manifest = pd.read_csv(root_path / HRRR_MANIFEST_REL)
    hourly_summary = pd.read_csv(root_path / HRRR_SUMMARY_REL)
    step1 = pd.read_csv(root_path / STEP1_REL)
    c3_audit = json.loads((root_path / C3_AUDIT_REL).read_text(encoding="utf-8"))

    ledger = build_observation_ledger(catalogue, raw_catalogue)
    dedup = build_deduplication_summary(raw_catalogue, ledger)
    attrition = build_attrition_summary(raw_catalogue, ledger)
    breakdown = build_attrition_breakdown(ledger)
    hrrr = build_hrrr_crosswalk(catalogue, manifest, hourly_summary)
    quality = build_pass_quality(catalogue, hrrr)
    support = build_within_city_support(quality)
    missing = build_missing_archive_audit(catalogue, step1)

    outputs = {
        "observation_ledger.csv": ledger,
        "deduplication_summary.csv": dedup,
        "attrition_summary.csv": attrition,
        "attrition_breakdown.csv": breakdown,
        "hrrr_pass_hour_crosswalk.csv": hrrr,
        "pass_quality_219.csv": quality,
        "within_city_wet_dry_support.csv": support,
        "archive_missing_31_audit.csv": missing,
    }
    for name, frame in outputs.items():
        _atomic_csv(frame, output / name)

    _atomic_text(_method_notes(), output / "method_notes.md")
    _atomic_text(
        _g3a_checkpoint_contract(),
        output / "G3A_nonthermal_tree_reference_yield_checkpoint.md",
    )
    _atomic_text(_revision_response(), output / "revision_response.md")
    bindings = {
        "schema_version": 2,
        "gate": "G1",
        "authorized_by": "D0059",
        "revision_decision_ids": ["D0060", "D0061"],
        "inputs": _input_bindings(root_path),
    }
    _atomic_json(bindings, output / "source_bindings.json")

    status_counts = ledger["final_reconciliation_status"].value_counts().to_dict()
    missing_cells = missing["proxy_condition_cell"].value_counts().to_dict()
    all_low_dry = support.loc[
        support["city"].eq("ALL_CITIES")
        & support["condition_cell"].eq("demand_low__antecedent_dry")
    ].iloc[0]
    product_counts = manifest["product"].value_counts().to_dict()
    checks = [
        {
            "check_id": "G1-C01",
            "name": "complete_revision_and_tile_to_observation_reconciliation",
            "status": "PASS",
            "evidence": (
                "13,577 raw tiled products; 13,575 latest-revision products; "
                "2,968 unique physical city-orbit observations."
            ),
        },
        {
            "check_id": "G1-C02",
            "name": "complete_mutually_exclusive_attrition_identity",
            "status": "PASS",
            "evidence": {
                "final_status_counts": status_counts,
                "sum": int(sum(status_counts.values())),
                "early_late_stratum_eligible_physical_passes": int(
                    ledger["early_late_stratum_eligible"].sum()
                ),
                "count_interpretation": (
                    "individual physical passes prior to empirical matching; "
                    "not morning-afternoon pairs"
                ),
            },
        },
        {
            "check_id": "G1-C03",
            "name": "applied_view_rule_and_geometry_resolution",
            "status": "PASS",
            "evidence": (
                "911/911 archive-available candidates have definitive L1B-GEO geometry; "
                "219 pass coverage>=0.95 and p95(abs(view zenith))<=20 degrees; the 31 "
                "pre-geometry archive exclusions were not assigned zero coverage."
            ),
        },
        {
            "check_id": "G1-C04",
            "name": "physical_and_weighted_pass_counts_separated",
            "status": "PASS",
            "evidence": {
                "retained_physical_passes": len(quality),
                "retained_pass_equivalent_sum": float(
                    quality["clear_domain_fraction"].sum()
                ),
                "early_late_stratum_eligible_physical_passes": int(
                    quality["early_late_stratum_eligible"].sum()
                ),
                "early_late_stratum_eligible_pass_equivalent_sum": float(
                    quality.loc[
                        quality["early_late_stratum_eligible"],
                        "clear_domain_fraction",
                    ].sum()
                ),
                "formula": (
                    "sum(n_clear_pixels_independent_of_view / "
                    "n_domain_pixels_cloud)"
                ),
                "role": "secondary_clear_domain_exposure_diagnostic",
            },
        },
        {
            "check_id": "G1-C05",
            "name": "per_pass_nonthermal_quality_counts_complete",
            "status": "PASS_WITH_MANDATORY_LATER_CHECKPOINT",
            "evidence": (
                "All 219 retained passes have clear/cloud/fill pixel partitions, clear "
                "fractions, geometry metrics, and complete asset provenance. Usable tree "
                "and reference counts are explicitly unavailable. The mandatory "
                "G3A_NONTHERMAL_TREE_REFERENCE_YIELD checkpoint will compute tree/reference "
                "counts and nonthermal matching yield after G3 and before G4/G5/G7, without "
                "opening a temperature/LST value."
            ),
        },
        {
            "check_id": "G1-C06",
            "name": "hrrr_413_to_219_reconciled",
            "status": "PASS",
            "evidence": {
                "physical_passes": 219,
                "pass_hour_links": len(hrrr),
                "unique_hourly_assets": int(hrrr["hrrr_item_id"].nunique()),
                "shared_cross_city_hours": int(
                    hrrr.loc[hrrr["shared_across_cities"], "hrrr_item_id"].nunique()
                ),
                "manifest_product_counts": product_counts,
            },
        },
        {
            "check_id": "G1-C07",
            "name": "within_city_wet_dry_support_complete",
            "status": "PASS_RECONCILIATION_SUPPORT_REMAINS_SPARSE",
            "evidence": {
                "explicit_city_by_cell_rows": len(support),
                "low_demand_dry_physical_passes": int(
                    all_low_dry["retained_physical_passes"]
                ),
                "low_demand_dry_pass_equivalents": float(
                    all_low_dry["retained_pass_equivalent_sum"]
                ),
            },
        },
        {
            "check_id": "G1-C08",
            "name": "archive_missing_31_sparse_corner_audit",
            "status": "OPEN_WITH_PROXY_EVIDENCE",
            "evidence": {
                "missing_candidates": len(missing),
                "by_year": {
                    str(key): int(value)
                    for key, value in missing["year"].value_counts().sort_index().items()
                },
                "daily_proxy_condition_cells": {
                    str(key): int(value) for key, value in missing_cells.items()
                },
                "low_demand_dry_daily_proxy_candidates": int(
                    missing["proxy_condition_cell"]
                    .eq("demand_low__antecedent_dry")
                    .sum()
                ),
                "proxy_scope": "daily_step1_condition_axes_only",
                "definitive_acquisition_time_condition_cell_known": False,
                "geometry_and_cloud_outcomes_known": False,
            },
        },
        {
            "check_id": "G1-C09",
            "name": "collection3_recovery_and_fill_semantics_audited",
            "status": "PASS_RECOVERY_NOT_CURRENTLY_AVAILABLE_RAW_RESPONSES_PRESERVED",
            "evidence": {
                "gate1_conclusion": c3_audit["gate1_conclusion"],
                "date_bounded_raw_responses": [
                    {
                        "query_id": item["query_id"],
                        "date_boundary": item["date_boundary"],
                        "response_entry_count": item["response_entry_count"],
                        "raw_response_body": item["raw_response_body"],
                        "raw_response_bytes": item["raw_response_bytes"],
                        "raw_response_sha256": item["raw_response_sha256"],
                    }
                    for item in c3_audit["cmr_queries_used_as_gate1_evidence"]
                ],
            },
        },
        {
            "check_id": "G1-C10",
            "name": "data_access_and_protocol_deviation_state",
            "status": "PASS_WITH_RECORDED_PROTOCOL_DEVIATIONS_NOT_FULL_COMPLIANCE",
            "evidence": {
                "protocol_deviation_records": ["D0060", "D0061"],
                "record_2026_metadata_query_status": (
                    "PROTOCOL_DEVIATION_OCCURRED_D0060_D0061"
                ),
                "record_2026_science_data_status": "UNOPENED",
                "temperature_or_lst_layers_opened_during_gate1": 0,
                "metadata_records_excluded_from_gate1_evidence": True,
                "task1_run_records_remain_stop": ["R0015", "R0016"],
                "holdout_status": "UNSELECTED",
            },
        },
        {
            "check_id": "G1-C11",
            "name": "tree_reference_yield_checkpoint_scheduled",
            "status": "PLANNED_NOT_AUTHORIZED",
            "evidence": {
                "checkpoint": "G3A_NONTHERMAL_TREE_REFERENCE_YIELD",
                "placement": "after_G3_before_G4_G5_or_G7",
                "temperature_or_lst_value_access_permitted": False,
                "human_approval_required_at_checkpoint": True,
            },
        },
    ]
    _atomic_text(
        _review_markdown(missing, support, c3_audit),
        output / "review.md",
    )
    artifact_paths = [
        *(output / name for name in outputs),
        output / "method_notes.md",
        output / "G3A_nonthermal_tree_reference_yield_checkpoint.md",
        output / "revision_response.md",
        output / "review.md",
        output / "source_bindings.json",
        root_path / C3_AUDIT_REL,
        root_path / C3_2020_RAW_REL,
        root_path / C3_2024_RAW_REL,
        root_path / D0060_REL,
        root_path / D0061_REL,
        root_path / QUARANTINED_2026_CMR_REL,
    ]
    checks_json = {
        "schema_version": 2,
        "gate": "G1",
        "gate_name": "complete_observation_reconciliation",
        "prepared_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "authorized_by": "D0059",
        "gate_status": (
            "REVISED_AWAITING_HUMAN_APPROVAL_WITH_RECORDED_PROTOCOL_DEVIATIONS"
        ),
        "technical_checks_pass": True,
        "protocol_compliance_pass": False,
        "protocol_compliance_status": (
            "D0060_D0061_RECORDED_NOT_CLEAN_COMPLIANCE"
        ),
        "protocol_deviation_records": ["D0060", "D0061"],
        "approval_received": False,
        "next_gate_authorized": False,
        "next_gate_if_approved": "G2",
        "sealed_state": {
            "task1_interaction_status": "STOP",
            "task1_time_of_day_status": "STOP_TIME_OF_DAY_ONLY_STEP3",
            "task2_result_bearing_actions_enabled": False,
            "holdout_status": "UNSELECTED",
            "heldout_thermal_status": "UNOPENED",
            "record_2026_metadata_query_status": (
                "PROTOCOL_DEVIATION_OCCURRED_D0060_D0061"
            ),
            "record_2026_science_data_status": "UNOPENED",
            "record_2026_metadata_records_excluded_from_gate1_evidence": True,
            "thermal_or_lst_layers_opened_during_gate1": 0,
        },
        "artifact_sha256": {
            path.relative_to(root_path).as_posix(): sha256_file(path)
            for path in artifact_paths
        },
        "checks": checks,
        "user_action_required": "APPROVE_G1_REVISE_G1_OR_STOP",
    }
    _atomic_json(checks_json, output / "checks.json")
    return {
        "gate_status": checks_json["gate_status"],
        "output_directory": output.as_posix(),
        "physical_observations": len(ledger),
        "retained_physical_passes": len(quality),
        "early_late_stratum_eligible_physical_passes": int(
            quality["early_late_stratum_eligible"].sum()
        ),
        "retained_pass_equivalents": float(quality["clear_domain_fraction"].sum()),
        "hrrr_unique_assets": int(hrrr["hrrr_item_id"].nunique()),
        "archive_missing_candidates": len(missing),
    }
