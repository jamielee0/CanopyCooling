#!/usr/bin/env python3
"""Run the real ECOSTRESS Step-2 view-angle and cloud quality audit.

This driver reads the frozen catalogue, exact Census geometries, and already
downloaded quality-layer COGs.  It never opens LST.  Outputs are written beneath
``data/processed/v2/task1/step2_quality_screening``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any

import numpy as np
import pandas as pd

from urban_cooling_v2.config import load_config
from urban_cooling_v2.domains import load_domain_features
from urban_cooling_v2.step02_raster import (
    CLOUD_ASSET_TYPE,
    VIEW_ASSET_TYPE,
    domain_pixel_counts_by_tile,
    partition_domain_for_mgrs_tile,
    select_latest_tile_revisions,
    summarize_cloud_pass,
    summarize_view_pass,
)
from urban_cooling_v2.step02_cloud import evaluate_cloud_stability


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/v2/ecostress"
PROCESSED = ROOT / "data/processed/v2/task1"
ASSETS = RAW / "enrichment_assets"
OUTPUT = PROCESSED / "step2_quality_screening"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_files(frame: pd.DataFrame, asset_root: Path) -> None:
    missing: list[str] = []
    for row in frame.to_dict("records"):
        path = asset_root / str(row["asset_type"]) / Path(str(row["file_name"])).name
        if not path.is_file():
            missing.append(path.name)
    if missing:
        preview = ", ".join(missing[:8])
        raise FileNotFoundError(
            f"{len(missing)} selected quality files are not downloaded; first: {preview}"
        )


def _domains() -> dict[str, dict[str, Any]]:
    config = load_config(ROOT / "configs/v2_cities.toml")
    features = load_domain_features(
        ROOT / "data/raw/v2/domains/census_urban_areas.geojson", config
    )
    return {city: feature["geometry"] for city, feature in features.items()}


def run_view_screening(
    *,
    view_manifest_path: Path,
    output_dir: Path,
    asset_root: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    manifest = pd.read_csv(view_manifest_path)
    manifest = manifest.loc[
        manifest["status"].astype(str).str.casefold().eq("available")
        & manifest["asset_type"].eq(VIEW_ASSET_TYPE)
    ].copy()
    manifest = select_latest_tile_revisions(manifest)
    _require_files(manifest, asset_root)
    domains = _domains()
    tile_domains = {
        str(city): {
            str(tile): partition_domain_for_mgrs_tile(domains[str(city)], str(tile))
            for tile in sorted(city_rows["tile"].astype(str).unique())
        }
        for city, city_rows in manifest.groupby("city", sort=True)
    }
    denominator_rows: list[dict[str, Any]] = []
    denominators: dict[str, int] = {}
    for city, city_rows in manifest.groupby("city", sort=True):
        counts = domain_pixel_counts_by_tile(
            city_rows,
            domain_geometry_wgs84=domains[str(city)],
            asset_root=asset_root,
            tile_domain_geometries_wgs84=tile_domains[str(city)],
        )
        denominators[str(city)] = int(sum(counts.values()))
        denominator_rows.extend(
            {
                "city": city,
                "tile": tile,
                "n_domain_pixel_centers": count,
                "city_domain_pixel_denominator": denominators[str(city)],
                "pixel_inclusion_rule": "70 m native-grid pixel center inside frozen Census geometry",
            }
            for tile, count in counts.items()
        )
    groups = list(manifest.groupby(["city", "orbit"], sort=True))
    rows: list[dict[str, Any]] = []
    for index, ((city, orbit), group) in enumerate(groups, start=1):
        result = summarize_view_pass(
            group,
            domain_geometry_wgs84=domains[str(city)],
            asset_root=asset_root,
            domain_pixel_denominator=denominators[str(city)],
            tile_domain_geometries_wgs84=tile_domains[str(city)],
        )
        result.update(
            {
                "city": city,
                "orbit": int(orbit),
                "n_manifest_rows_before_revision_selection": int(len(group)),
            }
        )
        rows.append(result)
        if index % 50 == 0 or index == len(groups):
            print(f"view passes {index}/{len(groups)}", flush=True)
    summaries = pd.DataFrame(rows).sort_values(["city", "orbit"])

    pass_path = PROCESSED / "step2_enrichment/daytime_passes_enriched_pre_view.csv"
    passes = pd.read_csv(pass_path)
    passes["orbit"] = pd.to_numeric(passes["orbit"], errors="raise").astype(int)
    if passes.duplicated(["city", "orbit"]).any():
        raise ValueError("Enriched pass table is not unique by city/orbit")
    screened = passes.merge(
        summaries,
        on=["city", "orbit"],
        how="left",
        validate="one_to_one",
        suffixes=("", "_raster"),
    )
    candidate = screened["metadata_candidate"].eq(True)  # noqa: E712
    missing_candidate = candidate & screened["near_nadir_raster"].isna()
    if missing_candidate.any():
        raise ValueError(
            f"{int(missing_candidate.sum())} metadata candidates lack a view summary"
        )
    screened["near_nadir"] = (
        candidate
        & screened["near_nadir_raster"].astype("boolean").fillna(False).astype(bool)
    )
    screened["view_screen_status"] = np.where(
        ~candidate,
        "not_evaluated_metadata_excluded",
        np.where(screened["near_nadir"], "near_nadir_pass", "view_excluded"),
    )
    screened["quality_candidate_pre_cloud"] = screened["near_nadir"]
    screened = screened.drop(columns="near_nadir_raster")

    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(denominator_rows).to_csv(
        output_dir / "domain_pixel_denominators.csv", index=False
    )
    summaries.to_csv(output_dir / "view_pass_summary.csv", index=False)
    screened.to_csv(output_dir / "passes_quality_screened_pre_cloud.csv", index=False)
    return summaries, screened


def run_cloud_calibration(
    *,
    full_manifest_path: Path,
    view_manifest_path: Path,
    screened_passes: pd.DataFrame,
    output_dir: Path,
    asset_root: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    full = pd.read_csv(full_manifest_path)
    clouds = full.loc[
        full["status"].astype(str).str.casefold().eq("available")
        & full["asset_type"].eq(CLOUD_ASSET_TYPE)
    ].copy()
    attempted_cloud_years = set(clouds["year"].dropna().astype(int).unique())
    for scope in clouds.get("target_scope", pd.Series(dtype=str)).dropna().astype(str):
        match = re.search(r"frozen_cloud_calibration_july_years_([0-9_]+)$", scope)
        if match:
            attempted_cloud_years.update(
                int(value) for value in match.group(1).split("_") if value
            )
    attempted_cloud_years = sorted(attempted_cloud_years)
    views = pd.read_csv(view_manifest_path)
    views = views.loc[
        views["status"].astype(str).str.casefold().eq("available")
        & views["asset_type"].eq(VIEW_ASSET_TYPE)
    ].copy()
    views = select_latest_tile_revisions(views)
    clouds = select_latest_tile_revisions(clouds)
    eligible_keys = screened_passes.loc[
        screened_passes["quality_candidate_pre_cloud"], ["city", "orbit"]
    ].drop_duplicates()
    clouds = clouds.merge(
        eligible_keys, on=["city", "orbit"], how="inner", validate="many_to_one"
    )
    views = views.merge(
        eligible_keys, on=["city", "orbit"], how="inner", validate="many_to_one"
    )
    cloud_granules = set(clouds["granule_id"].astype(str))
    views = views.loc[views["granule_id"].astype(str).isin(cloud_granules)].copy()
    _require_files(clouds, asset_root)
    _require_files(views, asset_root)
    domains = _domains()
    tile_domains = {
        str(city): {
            str(tile): partition_domain_for_mgrs_tile(domains[str(city)], str(tile))
            for tile in sorted(city_rows["tile"].astype(str).unique())
        }
        for city, city_rows in views.groupby("city", sort=True)
    }
    view_groups = {
        (str(city), int(orbit)): group
        for (city, orbit), group in views.groupby(["city", "orbit"], sort=True)
    }
    rows: list[dict[str, Any]] = []
    denominators = {
        str(city): int(group["n_domain_pixels"].dropna().iloc[0])
        for city, group in screened_passes.loc[
            screened_passes["metadata_candidate"],
            ["city", "n_domain_pixels"],
        ].groupby("city", sort=True)
    }
    cloud_groups = list(clouds.groupby(["city", "orbit"], sort=True))
    for index, ((city, orbit), group) in enumerate(cloud_groups, start=1):
        key = (str(city), int(orbit))
        if key not in view_groups:
            continue
        result = summarize_cloud_pass(
            group,
            view_groups[key],
            domain_geometry_wgs84=domains[str(city)],
            asset_root=asset_root,
            domain_pixel_denominator=denominators[str(city)],
            tile_domain_geometries_wgs84=tile_domains[str(city)],
        )
        acquisition = pd.to_datetime(group["acquisition_utc"], utc=True)
        stamp = acquisition.sort_values().iloc[len(acquisition) // 2]
        result.update(
            {
                "city": city,
                "orbit": int(orbit),
                "acquisition_utc": stamp.isoformat(),
                "year": int(stamp.year),
                "month": int(stamp.month),
                "month_key": f"{stamp.year:04d}-{stamp.month:02d}",
            }
        )
        rows.append(result)
        if index % 10 == 0 or index == len(cloud_groups):
            print(f"cloud passes {index}/{len(cloud_groups)}", flush=True)
    pass_summary = pd.DataFrame(rows)
    if pass_summary.empty:
        raise ValueError("No near-nadir cloud-calibration pass survived the metadata gate")
    pass_summary = pass_summary.sort_values(["city", "acquisition_utc", "orbit"])

    month_rows: list[dict[str, Any]] = []
    for (city, month_key), group in pass_summary.groupby(
        ["city", "month_key"], sort=True
    ):
        n_domain = int(group["n_domain_pixels"].sum())
        n_view = int(group["n_view_valid_pixels"].sum())
        n_clear = int(group["n_clear_pixels"].sum())
        month_rows.append(
            {
                "city": city,
                "month_key": month_key,
                "n_near_nadir_passes": int(len(group)),
                "n_domain_pixels": n_domain,
                "n_view_valid_pixels": n_view,
                "n_clear_pixels": n_clear,
                "pass_mean_survival_fraction": float(
                    group["cloud_survival_fraction_of_domain"].mean()
                ),
                "pass_median_survival_fraction": float(
                    group["cloud_survival_fraction_of_domain"].median()
                ),
                "pixel_pooled_survival_fraction": n_clear / n_domain,
                "pixel_pooled_clear_fraction_of_valid_view": n_clear / n_view
                if n_view
                else np.nan,
            }
        )
    month_summary = pd.DataFrame(month_rows).sort_values(["city", "month_key"])

    validation, stage_audit = evaluate_cloud_stability(
        month_summary,
        attempted_years=attempted_cloud_years,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    pass_summary.to_csv(output_dir / "cloud_pass_summary.csv", index=False)
    month_summary.to_csv(output_dir / "cloud_month_summary.csv", index=False)
    validation.to_csv(output_dir / "cloud_validation.csv", index=False)
    stage_audit.to_csv(output_dir / "cloud_stability_stage_audit.csv", index=False)
    return pass_summary, month_summary, validation


def write_attrition(
    *,
    screened: pd.DataFrame,
    month_summary: pd.DataFrame,
    validation: pd.DataFrame,
    output_dir: Path,
) -> pd.DataFrame:
    catalogue = pd.read_csv(
        PROCESSED
        / "step2_catalogue_audit/tables/step2_scene_catalogue_metadata_only.csv"
    )
    reference_by_city = {
        "phoenix": "phoenix",
        "los_angeles": "phoenix",
        "atlanta": "miami",
        "minneapolis_st_paul": "miami",
        "miami": "miami",
    }
    all_stable = bool(validation["representative_within_tolerance"].all())
    primary_survival = {
        row.reference_city: float(row.cloud_survival_fraction)
        for row in validation.itertuples()
    }
    rows: list[dict[str, Any]] = []
    for city in sorted(screened["city"].unique()):
        city_passes = screened.loc[screened["city"].eq(city)]
        counts: list[tuple[str, float]] = [
            (
                "catalogue_physical_passes_all_local_solar_times",
                float(catalogue.loc[catalogue["city"].eq(city), "orbit"].nunique()),
            ),
            ("daytime_10_to_18_local_solar", float(len(city_passes))),
            (
                "geolocation_best_or_good",
                float(city_passes["geolocation_usable"].eq(True).sum()),  # noqa: E712
            ),
            (
                "no_obstruction_after_geolocation",
                float(
                    (
                        city_passes["geolocation_usable"].eq(True)  # noqa: E712
                        & city_passes["obstruction_flag"].eq(False)  # noqa: E712
                    ).sum()
                ),
            ),
            (
                "near_nadir_and_95pct_domain_coverage",
                float(city_passes["quality_candidate_pre_cloud"].sum()),
            ),
        ]
        reference = reference_by_city[city]
        if all_stable and reference in primary_survival:
            expected = counts[-1][1] * primary_survival[reference]
        else:
            expected = np.nan
        counts.append(("expected_cloud_surviving_pass_equivalents", expected))
        catalogue_count = counts[0][1]
        previous = np.nan
        for stage, count in counts:
            rows.append(
                {
                    "city": city,
                    "stage": stage,
                    "surviving_passes_or_equivalents": count,
                    "fraction_of_catalogue": count / catalogue_count
                    if np.isfinite(count) and catalogue_count
                    else np.nan,
                    "fraction_of_previous_stage": count / previous
                    if np.isfinite(count) and np.isfinite(previous) and previous
                    else np.nan,
                    "count_type": "expected_equivalent"
                    if stage.startswith("expected_cloud")
                    else "integer_physical_passes",
                    "cloud_reference_city": reference
                    if stage.startswith("expected_cloud")
                    else "",
                    "cloud_extrapolation_status": (
                        "allowed_after_validation"
                        if all_stable
                        else "withheld_pending_frozen_month_expansion"
                    )
                    if stage.startswith("expected_cloud")
                    else "not_applicable",
                }
            )
            previous = count
    attrition = pd.DataFrame(rows)
    attrition.to_csv(output_dir / "T2.2_quality_attrition.csv", index=False)
    return attrition


def write_run_record(
    *,
    output_dir: Path,
    view_manifest_path: Path,
    full_manifest_path: Path,
    screened: pd.DataFrame,
    validation: pd.DataFrame,
) -> None:
    config = load_config(ROOT / "configs/v2_cities.toml")
    domain_features = load_domain_features(
        ROOT / "data/raw/v2/domains/census_urban_areas.geojson", config
    )
    record = {
        "schema_version": 1,
        "scope": "ECOSTRESS quality layers only; no LST opened",
        "view_manifest": str(view_manifest_path.resolve().relative_to(ROOT)),
        "view_manifest_sha256": _sha256(view_manifest_path),
        "full_enrichment_manifest": str(
            full_manifest_path.resolve().relative_to(ROOT)
        ),
        "full_enrichment_manifest_sha256": _sha256(full_manifest_path),
        "frozen_domain_geojson_sha256": _sha256(
            ROOT / "data/raw/v2/domains/census_urban_areas.geojson"
        ),
        "analysis_geometry_sha256_by_city": {
            city: feature["properties"]["analysis_geometry_sha256"]
            for city, feature in sorted(domain_features.items())
        },
        "n_daytime_passes": int(len(screened)),
        "n_metadata_candidates": int(screened["metadata_candidate"].sum()),
        "n_near_nadir_candidates": int(
            screened["quality_candidate_pre_cloud"].sum()
        ),
        "cloud_validation_all_stable": bool(
            validation["representative_within_tolerance"].all()
        ),
        "near_nadir_rule": (
            "valid view coverage >=0.95 and p95 absolute view zenith <=20 degrees"
        ),
        "revision_rule": "latest build/revision per city/orbit/scene/MGRS tile",
        "overlap_rule": "larger absolute view angle; cloudy wins over clear",
        "domain_topology_rule": config.study["domain_analysis_topology_rule"],
        "mgrs_partition_rule": config.study["ecostress_mgrs_partition_rule"],
    }
    (output_dir / "run_record.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--view-manifest",
        type=Path,
        default=RAW / "view_candidate_manifest_latest.csv",
    )
    parser.add_argument(
        "--full-manifest", type=Path, default=RAW / "enrichment_manifest.csv"
    )
    parser.add_argument("--asset-root", type=Path, default=ASSETS)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    _, screened = run_view_screening(
        view_manifest_path=args.view_manifest,
        output_dir=args.output,
        asset_root=args.asset_root,
    )
    _, month_summary, validation = run_cloud_calibration(
        full_manifest_path=args.full_manifest,
        view_manifest_path=args.view_manifest,
        screened_passes=screened,
        output_dir=args.output,
        asset_root=args.asset_root,
    )
    write_attrition(
        screened=screened,
        month_summary=month_summary,
        validation=validation,
        output_dir=args.output,
    )
    write_run_record(
        output_dir=args.output,
        view_manifest_path=args.view_manifest,
        full_manifest_path=args.full_manifest,
        screened=screened,
        validation=validation,
    )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
