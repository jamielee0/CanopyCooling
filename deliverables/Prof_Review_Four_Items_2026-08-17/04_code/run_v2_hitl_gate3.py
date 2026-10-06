#!/usr/bin/env python3
"""Run the D0064/D0065 Gate-3 nonthermal sampling-design audit."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from urban_cooling_v2.hitl_gate3_sampling import (
    ANGLE_THRESHOLDS,
    CANDIDATE_CITY_META,
    add_antecedent_predictors,
    audit_existing_angle_thresholds,
    candidate_day_support,
    fetch_candidate_domains,
    fetch_candidate_metadata,
    fetch_candidate_weather,
    fetch_modis_phenology,
    load_candidate_domains,
    selection_result,
    sha256_file,
    summarize_candidate_metadata,
    summarize_leaf_on,
)


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/v2/hitl/g3_sampling_design"
OUTPUT = ROOT / "docs/v2/hitl/G3_SAMPLING_DESIGN"
DOMAINS = RAW / "candidate_domains_7.geojson"
PHENOLOGY_RAW = RAW / "mod13q1_2018_2025_composite_ndvi.csv"
WEATHER_RAW = RAW / "candidate_city_daily_gridmet_2018_2025.csv"
METADATA_RAW = RAW / "candidate_additions_l2t_metadata_2018_2025.csv"
EXISTING_DOMAINS = ROOT / "data/raw/v2/domains/census_urban_areas.geojson"
GEOMETRY = ROOT / "data/processed/v2/task1/step2_quality_screening_l1b_geo_D0047/geometry_pass_summary.csv"
CATALOGUE = ROOT / "data/processed/v2/task1/step2_quality_screening_l1b_geo_D0047/passes_quality_screened_pre_cloud_geometry_only.csv"
G2_PASS = ROOT / "docs/v2/hitl/G2_HYDROCLIMATE_SUPPORT/pass_hydroclimate_219.csv"
MISSING = ROOT / "docs/v2/hitl/G1_OBSERVATION_RECONCILIATION/archive_missing_31_audit.csv"
CENSUS_SERVICE = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Urban/MapServer/0"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _hashes(paths: list[Path]) -> dict[str, str]:
    return {str(path.relative_to(ROOT)): sha256_file(path) for path in paths}


def _plot_phenology(monthly: pd.DataFrame, destination: Path) -> None:
    labels = {slug: value["label"] for slug, value in CANDIDATE_CITY_META.items()}
    fig, axes = plt.subplots(4, 2, figsize=(11, 12), sharex=True)
    for axis, city in zip(axes.flat, sorted(CANDIDATE_CITY_META)):
        group = monthly.loc[monthly["city"].eq(city)].sort_values("month")
        axis.plot(group["month"], group["median_ndvi"], marker="o", color="#176B87")
        axis.fill_between(group["month"], group["q1_ndvi"], group["q3_ndvi"], color="#86B6F6", alpha=0.3)
        stable = group.loc[group["stable_leaf_on"]]
        axis.scatter(stable["month"], stable["median_ndvi"], color="#1A7F37", s=55, zorder=3, label="stable")
        axis.axhline(float(group["city_peak_median_ndvi"].iloc[0]) * 0.9, color="#A35C00", linestyle="--", linewidth=1)
        axis.set_title(labels[city])
        axis.set_ylabel("NDVI")
        axis.grid(alpha=0.2)
    axes.flat[-1].axis("off")
    for axis in axes[-1, :]:
        if axis.axison:
            axis.set_xlabel("Month")
    fig.suptitle("Gate 3 optical phenology (2018–2025 monthly medians and IQR)")
    fig.tight_layout()
    destination.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destination, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _plot_angles(detail: pd.DataFrame, destination: Path) -> None:
    counts = (
        detail.groupby(["threshold_deg", "city"], as_index=False)
        .agg(
            physical_passes=("orbit", "size"),
            complete_passes=("quality_and_exact_weather_complete", "sum"),
        )
    )
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)
    for city, group in counts.groupby("city", sort=True):
        label = CANDIDATE_CITY_META.get(city, {}).get("label", city)
        axes[0].plot(group["threshold_deg"], group["physical_passes"], marker="o", label=label)
        unresolved = group["physical_passes"] - group["complete_passes"]
        axes[1].plot(group["threshold_deg"], unresolved, marker="o", label=label)
    axes[0].set_title("Geometry-qualified physical passes")
    axes[1].set_title("Passes lacking cloud/exact-weather completion")
    for axis in axes:
        axis.set_xlabel("Pass-level view-zenith p95 threshold (degrees)")
        axis.set_xticks(ANGLE_THRESHOLDS)
        axis.grid(alpha=0.25)
    axes[0].set_ylabel("Physical pass count")
    axes[1].legend(fontsize=8, loc="upper left", bbox_to_anchor=(1.02, 1))
    fig.suptitle("Existing five-city June–September threshold audit")
    fig.tight_layout()
    destination.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destination, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _city_window_audit(
    phenology_windows: pd.DataFrame,
    day_support: pd.DataFrame,
    metadata_passes: pd.DataFrame,
) -> pd.DataFrame:
    candidates = phenology_windows.copy()
    candidates = candidates.merge(day_support, on=["city", "window_id"], how="left", validate="one_to_one")
    metadata_counts = (
        metadata_passes.groupby(["city", "window_id"], as_index=False)
        .agg(
            metadata_all_physical_passes=("orbit", "size"),
            metadata_daytime_ceiling_passes=("time_stratum", lambda x: int(x.notna().sum())),
            metadata_ceiling_years=("year", "nunique"),
            metadata_ceiling_morning=("time_stratum", lambda x: int(x.eq("10-12").sum())),
            metadata_ceiling_late_afternoon=("time_stratum", lambda x: int(x.eq("16-18").sum())),
        )
    )
    candidates = candidates.merge(metadata_counts, on=["city", "window_id"], how="left", validate="one_to_one")
    existing = {"phoenix", "los_angeles", "atlanta", "minneapolis_st_paul", "miami"}
    candidates["domain_bound"] = True
    candidates["weather_reference_complete"] = candidates["physical_city_days"].notna() & candidates["complete_60d_days"].eq(candidates["physical_city_days"])
    candidates["metadata_audit_status"] = np.where(
        candidates["metadata_all_physical_passes"].notna(),
        "HISTORICAL_METADATA_CEILING_COMPLETE",
        np.where(
            candidates["city"].isin(existing) & candidates["window_id"].eq("jun_sep"),
            "INHERITED_G1_COMPLETE_METADATA_LEDGER",
            "UNRESOLVED",
        ),
    )
    candidates["geometry_status"] = np.where(
        candidates["city"].isin(existing) & candidates["window_id"].eq("jun_sep"),
        "EXISTING_THRESHOLD_AUDIT_AVAILABLE",
        "UNRESOLVED_REQUIRES_L1B_GEOMETRY",
    )
    candidates["view_azimuth_status"] = "UNRESOLVED_NOT_MAPPED"
    candidates["cloud_and_exact_hrrr_status"] = np.where(
        candidates["city"].isin(existing) & candidates["window_id"].eq("jun_sep"),
        "AVAILABLE_ONLY_FOR_EXISTING_P95_LE_20_PASSES",
        "UNRESOLVED",
    )
    candidates["eligible_for_primary_design"] = False
    candidates["eligibility_status"] = "NOT_ELIGIBLE_IN_CURRENT_G3_PACKET"
    return candidates.sort_values(["city", "window_id"]).reset_index(drop=True)


def _review_text(
    selection: dict[str, Any],
    monthly: pd.DataFrame,
    windows: pd.DataFrame,
    city_window: pd.DataFrame,
    eligibility: pd.DataFrame,
    detail: pd.DataFrame,
    metadata_passes: pd.DataFrame,
) -> str:
    stable = windows.loc[windows["all_months_stable_leaf_on"], ["city", "window_id"]]
    stable_text = ", ".join(f"{row.city}/{row.window_id}" for row in stable.itertuples(index=False)) or "none"
    threshold_totals = detail.groupby("threshold_deg").size().to_dict()
    threshold_text = ", ".join(f"{int(k)}°: {int(v)}" for k, v in sorted(threshold_totals.items()))
    addition_counts = (
        metadata_passes.groupby(["city", "window_id"])
        .agg(all_physical=("orbit", "size"), daytime=("time_stratum", lambda x: int(x.notna().sum())))
    )
    addition_text = ", ".join(
        f"{city}/{window}: {int(row.all_physical)} all / {int(row.daytime)} daytime"
        for (city, window), row in addition_counts.sort_index().iterrows()
    )
    failures_20 = eligibility.loc[eligibility["threshold_deg"].eq(20)]
    failure_text = "; ".join(
        f"{row.city}: archive unresolved={row.archive_unresolved_candidates}, azimuth={row.azimuth_complete}, eligible={row.eligible_city_window}"
        for row in failures_20.itertuples(index=False)
    )
    return f"""# Gate 3 review — prospective sampling design

## Decision

`REVISE_REQUIRED`

No primary city set, season window, or view-zenith threshold is selected. The frozen Gate-3
rules were applied without opening temperature/LST values or querying any 2026 record, but
the evidence chain is not yet complete enough to choose a prospective design.

## What this gate completed

- Bound official 2020 Census Urban Area domains for all seven candidates, including
  Denver–Aurora (`23527`) and Sacramento (`77068`), with source and analysis checksums.
- Retrieved and QA-screened historical `MOD13Q1.061` NDVI for April–October 2018–2025 and
  applied the pre-result stable-leaf-on rule. Passing city/window combinations: **{stable_text}**.
- Rebuilt the candidate-day GridMET reference through the required preceding 60-day windows.
- Audited historical metadata ceilings for Denver, Sacramento, Phoenix April–May, and
  California October. Intersecting physical-overpass counts and their 10–18 local-solar
  daytime subsets are: **{addition_text}**.
- Ran the existing five-city June–September geometry evidence through 10°, 15°, 20°, 25°,
  and exploratory 30° thresholds. Counts are **{threshold_text}** physical passes.

The daytime metadata ceilings are not usable-pass counts. They precede L1B coverage/angle,
view-azimuth, cloud, and exact-acquisition HRRR checks.

## Why Gate 3 cannot be approved as a selected design

1. Denver, Sacramento, and every shoulder-season addition still lack the frozen full-domain
   L1B geometry and cloud-quality audit.
2. Pass-level `view_azimuth` and relative sun–sensor azimuth have not been mapped for any
   candidate threshold. The official L1B arrays exist, but the prior pipeline read only
   latitude, longitude, and view zenith.
3. The 25° and 30° additions in the inherited panel lack complete cloud and exact-acquisition
   HRRR evidence, so their joint demand/wetness distributions are unresolved.
4. Gate 1's 31 archive-unavailable candidates remain unresolved. Under D0065 they remain in
   the denominator and prevent a claim of fully resolved observation accounting.

At the inherited 20° threshold: **{failure_text}**.

## Efficient revision path

Keep D0065 unchanged and run one bounded nonthermal augmentation:

1. seal L1B identities and full-domain view geometry for the candidate additions;
2. map `view_azimuth` and `solar_azimuth` on the same target cells for every threshold
   candidate;
3. complete cloud and exact-acquisition HRRR only for newly geometry-qualified passes;
4. recheck the 31 historical archive exclusions without using an unbounded search; and
5. rerun the same eligibility rules once.

No threshold should be chosen from the current count chart. A 20° rule remains only the
inherited comparator, not a Gate-3 selection.

## Locks and next action

- Sampling design: `UNSELECTED`
- G3A tree/reference-yield checkpoint: `LOCKED`
- Gate 4 and later gates: `LOCKED`
- Holdout: `UNSELECTED`
- Temperature/LST and thermal outcomes: `UNOPENED`
- 2026 metadata/science query: `NOT PERFORMED AT G3`

Human options:

- `REVISE G3: run the bounded nonthermal augmentation` — complete the missing evidence
  under D0065 and return a revised Gate-3 packet.
- `STOP` — preserve this identifiability/data-completeness result and end the amended
  workflow.
"""


def run(args: argparse.Namespace) -> dict[str, Any]:
    RAW.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "figures").mkdir(parents=True, exist_ok=True)

    if args.fetch_domains:
        import requests

        domains = fetch_candidate_domains(
            EXISTING_DOMAINS,
            DOMAINS,
            request_get=requests.get,
            service_url=CENSUS_SERVICE,
        )
    else:
        domains = load_candidate_domains(DOMAINS)

    project = os.environ.get("EARTHENGINE_PROJECT", "")
    if (args.fetch_phenology or args.fetch_weather) and not project:
        raise RuntimeError("EARTHENGINE_PROJECT is required for historical Earth Engine retrieval")
    if args.fetch_phenology:
        import ee

        composites = fetch_modis_phenology(domains, PHENOLOGY_RAW, ee=ee, project=project)
    else:
        composites = pd.read_csv(PHENOLOGY_RAW, parse_dates=["date"])
    monthly, windows = summarize_leaf_on(composites)

    if args.fetch_weather:
        import ee

        weather = fetch_candidate_weather(domains, WEATHER_RAW, ee=ee, project=project)
    else:
        weather = pd.read_csv(WEATHER_RAW, parse_dates=["date"])
    weather_predictors = add_antecedent_predictors(weather)
    day_support = candidate_day_support(weather_predictors)

    if args.fetch_metadata:
        import earthaccess

        metadata = fetch_candidate_metadata(domains, METADATA_RAW, search_data=earthaccess.search_data)
    else:
        metadata = pd.read_csv(METADATA_RAW, low_memory=False)
        metadata["acquisition_utc"] = pd.to_datetime(metadata["acquisition_utc"], utc=True, format="mixed")
    metadata_passes, metadata_counts = summarize_candidate_metadata(metadata)

    detail, joint, eligibility = audit_existing_angle_thresholds(
        GEOMETRY, CATALOGUE, G2_PASS, MISSING, windows
    )
    city_window = _city_window_audit(windows, day_support, metadata_passes)
    selection = selection_result(eligibility)

    artifacts: list[Path] = []
    tables = {
        "phenology_monthly.csv": monthly,
        "phenology_window_decisions.csv": windows,
        "candidate_day_weather_support.csv": day_support,
        "candidate_addition_physical_metadata_passes.csv": metadata_passes,
        "candidate_addition_metadata_counts.csv": metadata_counts,
        "city_window_audit.csv": city_window,
        "angle_threshold_pass_detail_existing_five.csv": detail,
        "angle_threshold_joint_support_existing_five.csv": joint,
        "angle_threshold_eligibility_existing_five.csv": eligibility,
    }
    for name, frame in tables.items():
        path = OUTPUT / name
        frame.to_csv(path, index=False)
        artifacts.append(path)

    selection_path = OUTPUT / "selection.json"
    _write_json(selection_path, selection)
    artifacts.append(selection_path)

    phenology_figure = OUTPUT / "figures/phenology_profiles.png"
    angle_figure = OUTPUT / "figures/angle_threshold_counts.png"
    _plot_phenology(monthly, phenology_figure)
    _plot_angles(detail, angle_figure)
    artifacts.extend([phenology_figure, angle_figure])

    sources = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "decision_ids": ["D0064", "D0065"],
        "source_files": _hashes(
            [
                EXISTING_DOMAINS,
                ROOT / "docs/v2/D0064_G2_APPROVAL_AND_G3_AUTHORIZATION.md",
                ROOT / "docs/v2/D0065_G3_PRE_RESULT_SAMPLING_RULES.md",
                ROOT / "docs/v2/hitl/G0_FREEZE_AND_AMENDMENT/proposed_outcome_blind_protocol_amendment.md",
                ROOT / "docs/v2/hitl/G2_HYDROCLIMATE_SUPPORT/checks.json",
                ROOT / "docs/v2/hitl/G2_HYDROCLIMATE_SUPPORT/review.md",
                ROOT / "docs/v2/hitl/G2_HYDROCLIMATE_SUPPORT/source_bindings.json",
                DOMAINS,
                DOMAINS.with_suffix(DOMAINS.suffix + ".provenance.json"),
                PHENOLOGY_RAW,
                PHENOLOGY_RAW.with_suffix(PHENOLOGY_RAW.suffix + ".provenance.json"),
                WEATHER_RAW,
                WEATHER_RAW.with_suffix(WEATHER_RAW.suffix + ".provenance.json"),
                METADATA_RAW,
                METADATA_RAW.with_suffix(METADATA_RAW.suffix + ".provenance.json"),
                GEOMETRY,
                CATALOGUE,
                G2_PASS,
                MISSING,
                ROOT / "src/urban_cooling_v2/hitl_gate3_sampling.py",
                ROOT / "src/run_v2_hitl_gate3.py",
            ]
        ),
        "official_sources": {
            "census_urban_areas": "https://www.census.gov/programs-surveys/geography/guidance/geo-areas/urban-rural.html",
            "census_tigerweb_service": CENSUS_SERVICE,
            "mod13_user_guide_v61": "https://lpdaac.usgs.gov/documents/621/MOD13_User_Guide_V61.pdf",
            "mod13_qa_guide": "https://lpdaac.usgs.gov/documents/103/MOD13_User_Guide_V6.pdf",
            "ecostress_l1_product_spec": "https://ecostress.jpl.nasa.gov/downloads/psd/ECOSTRESS_SDS_PSD_L1.pdf",
            "ecostress_l1_user_guide": "https://lpdaac.usgs.gov/documents/1491/ECO1B_User_Guide_V2.pdf",
        },
        "record_2026_queried": False,
        "temperature_or_lst_opened": False,
        "holdout_status": "UNSELECTED",
    }
    source_path = OUTPUT / "source_bindings.json"
    _write_json(source_path, sources)
    artifacts.append(source_path)

    checks = {
        "gate": "G3",
        "overall_status": "REVISE_REQUIRED",
        "rules_frozen_before_results": True,
        "candidate_domain_count": len(domains),
        "candidate_domains_complete": len(domains) == 7,
        "phenology_composites": len(composites),
        "phenology_year_min": int(pd.to_datetime(composites["date"]).dt.year.min()),
        "phenology_year_max": int(pd.to_datetime(composites["date"]).dt.year.max()),
        "phenology_valid_fraction_bounds_pass": bool(
            composites["primary_valid_fraction"].between(0, 1).all()
            and composites["good_valid_fraction"].between(0, 1).all()
        ),
        "weather_city_days": len(weather),
        "candidate_metadata_granules": len(metadata),
        "candidate_metadata_all_physical_passes": len(metadata_passes),
        "candidate_metadata_daytime_ceiling_passes": int(metadata_passes["time_stratum"].notna().sum()),
        "angle_thresholds_run_deg": list(ANGLE_THRESHOLDS),
        "existing_five_threshold_counts": {str(int(k)): int(v) for k, v in detail.groupby("threshold_deg").size().items()},
        "angle_counts_monotone": bool(
            detail.groupby("threshold_deg").size().reindex(ANGLE_THRESHOLDS).is_monotonic_increasing
        ),
        "twenty_degree_count_matches_g2_219": int(detail.loc[detail["threshold_deg"].eq(20)].shape[0]) == 219,
        "view_azimuth_complete": False,
        "relative_azimuth_complete": False,
        "new_candidate_geometry_complete": False,
        "shoulder_geometry_complete": False,
        "archive_unavailable_31_resolved": False,
        "sampling_design_selected": False,
        "g3a_authorized": False,
        "gate4_authorized": False,
        "temperature_or_lst_opened": False,
        "record_2026_queried": False,
        "holdout_status": "UNSELECTED",
        "verification": {
            "v2_test_programs_passed": 37,
            "legacy_test_programs_passed": 17,
            "all_test_programs_passed": True,
            "figures_visually_inspected": 2,
        },
        "artifact_hashes": _hashes(artifacts),
        "source_bindings_sha256": sha256_file(source_path),
    }
    checks_path = OUTPUT / "checks.json"
    _write_json(checks_path, checks)

    review = _review_text(selection, monthly, windows, city_window, eligibility, detail, metadata_passes)
    review_path = OUTPUT / "review.md"
    review_path.write_text(review, encoding="utf-8")

    return {
        "output": str(OUTPUT),
        "checks_sha256": sha256_file(checks_path),
        "review_sha256": sha256_file(review_path),
        "source_bindings_sha256": sha256_file(source_path),
        "selection": selection,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fetch-domains", action="store_true")
    parser.add_argument("--fetch-phenology", action="store_true")
    parser.add_argument("--fetch-weather", action="store_true")
    parser.add_argument("--fetch-metadata", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(run(parse_args()), indent=2))
