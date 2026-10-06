#!/usr/bin/env python3
"""Build the narrow live asset manifest for the Task-1 ECOSTRESS audit.

The manifest contains JSON metadata and view-angle COGs for every daytime tile,
cloud COGs only for the four preregistered calibration city-months, and L1B GEO
DMR++ metadata only beyond the coverage of JPL's frozen Poor/Suspect flag table.
It never includes an LST asset.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .config import StudyConfig
from .domains import geometry_bbox, load_domain_features
from .step02_catalog import prepare_catalogue
from .step02_enrich_fetch import (
    CLOUD_COG,
    L1B_GEO_DMRPP,
    L2T_JSON,
    VIEW_ZENITH_COG,
    create_target_manifest,
)


GEOLOCATION_FLAG_TABLE_COVERAGE_END = pd.Timestamp("2024-11-29T23:59:59Z")


def _mapping(result: Any) -> dict[str, Any]:
    if isinstance(result, Mapping):
        return dict(result)
    data = getattr(result, "data", None)
    if isinstance(data, Mapping):
        return dict(data)
    raise TypeError("CMR result must be mapping-like")


def cached_cmr_query(
    cache_path: str | Path,
    *,
    search_data: Callable[..., Sequence[Any]],
    query: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Run or replay one immutable CMR query without persisting credentials."""

    destination = Path(cache_path)
    canonical_query = json.loads(json.dumps(dict(query), default=str))
    if destination.exists():
        payload = json.loads(destination.read_text(encoding="utf-8"))
        if payload.get("query") != canonical_query:
            raise ValueError(f"Cached CMR query mismatch: {destination}")
        return list(payload.get("results", []))
    results = [_mapping(result) for result in search_data(**dict(query))]
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_text(
        json.dumps({"query": canonical_query, "results": results}, indent=2, default=str)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)
    return results


def build_live_enrichment_manifest(
    config: StudyConfig,
    domains_geojson: str | Path,
    raw_catalogue_csv: str | Path,
    cache_dir: str | Path,
    output_csv: str | Path,
    *,
    search_data: Callable[..., Sequence[Any]],
    cloud_calibration_years: Sequence[int] = (2022, 2023),
) -> pd.DataFrame:
    """Query/replay CMR and write the predeclared target-scoped asset manifest."""

    cloud_years = tuple(sorted({int(year) for year in cloud_calibration_years}))
    if not cloud_years or any(year < 2018 or year > 2025 for year in cloud_years):
        raise ValueError("cloud_calibration_years must be within frozen 2018-2025")

    raw = pd.read_csv(raw_catalogue_csv)
    prepared = prepare_catalogue(raw, solar_engine="fallback")
    targets = prepared.loc[prepared["daytime"]].copy()
    targets["acquisition_utc"] = pd.to_datetime(targets["acquisition_utc"], utc=True)
    targets["year"] = targets["acquisition_utc"].dt.year
    targets["month"] = targets["acquisition_utc"].dt.month
    target_columns = ["city", "granule_id", "orbit", "scene"]
    if targets.duplicated(["city", "granule_id"]).any():
        raise ValueError("Daytime target granules must be unique within city")

    features = load_domain_features(domains_geojson, config)
    cache_root = Path(cache_dir)
    l2t_results: list[dict[str, Any]] = []
    geo_results: list[dict[str, Any]] = []
    for city in config.cities:
        bbox = geometry_bbox(features[city.slug]["geometry"])
        city_years = sorted(
            targets.loc[targets["city"] == city.slug, "year"].unique().astype(int)
        )
        for year in city_years:
            common = {
                "provider": "LPCLOUD",
                "bounding_box": bbox,
                "temporal": (
                    f"{year:04d}-06-01T00:00:00Z",
                    f"{year:04d}-09-30T23:59:59Z",
                ),
                "count": -1,
            }
            l2_query = {
                **common,
                "short_name": str(config.ecostress["short_name"]),
                "version": str(config.ecostress["catalogue_version"]),
            }
            l2t_results.extend(
                cached_cmr_query(
                    cache_root / "l2t" / city.slug / f"{year}.json",
                    search_data=search_data,
                    query=l2_query,
                )
            )
            year_end = pd.Timestamp(f"{year:04d}-09-30T23:59:59Z")
            if year_end > GEOLOCATION_FLAG_TABLE_COVERAGE_END:
                geo_query = {
                    **common,
                    "short_name": "ECO_L1B_GEO",
                    "version": "002",
                }
                geo_results.extend(
                    cached_cmr_query(
                        cache_root / "l1b_geo" / city.slug / f"{year}.json",
                        search_data=search_data,
                        query=geo_query,
                    )
                )

    full = create_target_manifest(
        targets[target_columns],
        l2t_results=l2t_results,
        l1b_geo_results=geo_results,
    )
    missing_geo = full.loc[
        full["asset_type"].eq(L1B_GEO_DMRPP) & full["status"].eq("missing"),
        ["orbit", "scene"],
    ].drop_duplicates()
    post_table_keys = targets.loc[
        targets["acquisition_utc"] > GEOLOCATION_FLAG_TABLE_COVERAGE_END,
        ["orbit", "scene"],
    ].drop_duplicates()
    for frame in (missing_geo, post_table_keys):
        frame["orbit"] = pd.to_numeric(frame["orbit"], errors="raise").astype(int)
        frame["scene"] = pd.to_numeric(frame["scene"], errors="raise").astype(int)
    missing_geo = missing_geo.merge(
        post_table_keys, on=["orbit", "scene"], how="inner", validate="one_to_one"
    )
    for row in missing_geo.itertuples(index=False):
        query = {
            "short_name": "ECO_L1B_GEO",
            "version": "002",
            "provider": "LPCLOUD",
            "granule_name": (
                f"ECOv002_L1B_GEO_{int(row.orbit):05d}_{int(row.scene):03d}_*"
            ),
            "count": -1,
        }
        geo_results.extend(
            cached_cmr_query(
                cache_root
                / "l1b_geo_by_scene"
                / f"{int(row.orbit):05d}_{int(row.scene):03d}.json",
                search_data=search_data,
                query=query,
            )
        )
    if len(missing_geo):
        full = create_target_manifest(
            targets[target_columns],
            l2t_results=l2t_results,
            l1b_geo_results=geo_results,
        )
    target_meta = targets[
        ["city", "granule_id", "year", "month", "acquisition_utc"]
    ].drop_duplicates(["city", "granule_id"])
    full = full.merge(
        target_meta,
        on=["city", "granule_id"],
        how="left",
        validate="many_to_one",
    )

    calibration = (
        full["city"].isin(
            [
                str(config.ecostress["cloud_dry_reference_city"]),
                str(config.ecostress["cloud_humid_reference_city"]),
            ]
        )
        & full["year"].isin(cloud_years)
        & full["month"].eq(7)
    )
    beyond_table = full["acquisition_utc"] > GEOLOCATION_FLAG_TABLE_COVERAGE_END
    keep = (
        full["asset_type"].isin([L2T_JSON, VIEW_ZENITH_COG])
        | (full["asset_type"].eq(CLOUD_COG) & calibration)
        | (full["asset_type"].eq(L1B_GEO_DMRPP) & beyond_table)
    )
    selected = full.loc[keep].copy()
    selected["target_scope"] = "all_daytime_tiles"
    selected.loc[selected["asset_type"].eq(CLOUD_COG), "target_scope"] = (
        "frozen_cloud_calibration_july_years_"
        + "_".join(str(year) for year in cloud_years)
    )
    selected.loc[selected["asset_type"].eq(L1B_GEO_DMRPP), "target_scope"] = (
        "post_flag_table_geolocation"
    )
    # L1B GEO is scene-level; the same official asset can appear through
    # several tiles or cities. Download it once and join by orbit/scene.
    is_geo = selected["asset_type"].eq(L1B_GEO_DMRPP)
    geo = selected.loc[is_geo].sort_values(
        ["orbit", "scene", "city", "granule_id"]
    ).drop_duplicates(["orbit", "scene", "asset_type"], keep="first")
    selected = pd.concat([selected.loc[~is_geo], geo], ignore_index=True)
    selected = selected.sort_values(
        ["asset_type", "city", "year", "granule_id"], kind="stable"
    ).reset_index(drop=True)
    destination = Path(output_csv)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    selected.to_csv(temporary, index=False)
    temporary.replace(destination)
    return selected


__all__ = [
    "GEOLOCATION_FLAG_TABLE_COVERAGE_END",
    "build_live_enrichment_manifest",
    "cached_cmr_query",
]
