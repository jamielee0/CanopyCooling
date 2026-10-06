#!/usr/bin/env python3
"""Fail-closed exhaustive cloud audit for the frozen Step-2 candidates.

Decision D0033 replaces the failed reference-month extrapolation with an
observed cloud-layer audit of every pass that had already passed metadata and
view-angle screening.  Candidate selection is therefore read only from the
pre-cloud table; cloud values can never change which passes are audited.

This module accepts only ECOSTRESS ``cloud`` and ``view_zenith`` COGs.  It does
not construct, download, or open an LST path.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import rasterio

from .step02_enrich_fetch import CLOUD_COG, VIEW_ZENITH_COG, create_target_manifest
from .step02_raster import (
    _check_same_grid,
    _domain_window,
    partition_domain_for_mgrs_tile,
    select_latest_tile_revisions,
    summarize_cloud_pass,
)


DECISION_ID = "D0033"
EXPECTED_CANDIDATE_PASSES = 107
TARGET_SCOPE = "exhaustive_near_nadir_candidates_pre_outcome_D0033"
FROZEN_FIRST_YEAR = 2018
FROZEN_LAST_YEAR = 2025


def _bool_series(series: pd.Series, *, name: str) -> pd.Series:
    """Parse an explicit boolean column without truthy-string surprises."""

    if pd.api.types.is_bool_dtype(series.dtype):
        return series.astype(bool)
    lowered = series.astype("string").str.strip().str.casefold()
    unknown = ~lowered.isin(["true", "false"])
    if unknown.any():
        raise ValueError(f"{name} contains non-boolean values")
    return lowered.eq("true")


def frozen_candidate_passes(
    screened_passes: pd.DataFrame,
    *,
    expected_candidate_passes: int = EXPECTED_CANDIDATE_PASSES,
) -> pd.DataFrame:
    """Return the immutable pre-cloud candidate set and validate its seal."""

    required = {"city", "orbit", "acquisition_utc", "quality_candidate_pre_cloud"}
    missing = sorted(required.difference(screened_passes.columns))
    if missing:
        raise ValueError(f"Pre-cloud pass table lacks columns: {missing}")
    candidates = screened_passes.loc[
        _bool_series(
            screened_passes["quality_candidate_pre_cloud"],
            name="quality_candidate_pre_cloud",
        )
    ].copy()
    candidates["city"] = candidates["city"].astype(str)
    candidates["orbit"] = pd.to_numeric(candidates["orbit"], errors="raise").astype(int)
    candidates["acquisition_utc"] = pd.to_datetime(
        candidates["acquisition_utc"], errors="raise", utc=True, format="mixed"
    )
    if candidates.duplicated(["city", "orbit"]).any():
        raise ValueError("Pre-cloud candidates are not unique by city/orbit")
    if len(candidates) != int(expected_candidate_passes):
        raise ValueError(
            "Frozen pre-cloud candidate count mismatch: "
            f"expected {expected_candidate_passes}, found {len(candidates)}"
        )
    years = candidates["acquisition_utc"].dt.year
    if not years.between(FROZEN_FIRST_YEAR, FROZEN_LAST_YEAR).all():
        raise ValueError("Exhaustive cloud targets must stay inside frozen 2018-2025")
    return candidates.sort_values(["city", "acquisition_utc", "orbit"]).reset_index(
        drop=True
    )


def load_cached_l2t_results(cache_root: str | Path) -> list[dict[str, Any]]:
    """Read the already-frozen 2018-2025 L2T CMR result cache.

    The year in every cache filename and its stored temporal query is checked
    before results are returned.  This prevents an accidental 2026/holdout
    query from entering the remediation manifest.
    """

    root = Path(cache_root)
    paths = sorted(root.glob("*/*.json"))
    if not paths:
        raise FileNotFoundError(f"No cached L2T CMR results beneath {root}")
    results: list[dict[str, Any]] = []
    for path in paths:
        try:
            year = int(path.stem)
        except ValueError as exc:
            raise ValueError(f"Unexpected L2T cache filename: {path.name}") from exc
        if not FROZEN_FIRST_YEAR <= year <= FROZEN_LAST_YEAR:
            raise ValueError(f"Out-of-window L2T cache file: {path}")
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict) or not isinstance(document.get("results"), list):
            raise ValueError(f"Malformed L2T cache document: {path}")
        query = document.get("query", {})
        temporal = query.get("temporal") if isinstance(query, dict) else None
        if not isinstance(temporal, list) or len(temporal) != 2:
            raise ValueError(f"L2T cache lacks a frozen temporal query: {path}")
        query_years = {int(str(value)[:4]) for value in temporal}
        if query_years != {year}:
            raise ValueError(f"L2T cache year/query mismatch: {path}")
        results.extend(dict(record) for record in document["results"])
    return results


def _candidate_view_rows(
    candidates: pd.DataFrame, latest_view_manifest: pd.DataFrame
) -> pd.DataFrame:
    required = {
        "city",
        "orbit",
        "scene",
        "tile",
        "granule_id",
        "item_id",
        "asset_type",
        "status",
        "selected_build",
        "selected_revision",
        "file_name",
    }
    missing = sorted(required.difference(latest_view_manifest.columns))
    if missing:
        raise ValueError(f"Latest view manifest lacks columns: {missing}")
    views = latest_view_manifest.loc[
        latest_view_manifest["asset_type"].astype(str).eq(VIEW_ZENITH_COG)
    ].copy()
    views["orbit"] = pd.to_numeric(views["orbit"], errors="raise").astype(int)
    keys = candidates[["city", "orbit"]]
    selected = views.merge(
        keys, on=["city", "orbit"], how="inner", validate="many_to_one"
    )
    unavailable = ~selected["status"].astype(str).str.casefold().eq("available")
    if unavailable.any():
        raise ValueError(
            f"{int(unavailable.sum())} candidate view assets are not available"
        )
    selected = select_latest_tile_revisions(selected)
    expected_keys = set(map(tuple, keys.to_records(index=False)))
    observed_keys = set(
        map(tuple, selected[["city", "orbit"]].drop_duplicates().to_records(index=False))
    )
    if observed_keys != expected_keys:
        missing_keys = len(expected_keys.difference(observed_keys))
        extra_keys = len(observed_keys.difference(expected_keys))
        raise ValueError(
            f"Candidate view coverage mismatch: {missing_keys} missing, {extra_keys} extra"
        )
    identity = ["city", "orbit", "scene", "tile", "granule_id"]
    if selected.duplicated(identity).any():
        raise ValueError("Candidate latest-view rows are not unique by scene/tile identity")
    return selected.sort_values(identity).reset_index(drop=True)


def build_exhaustive_cloud_manifest(
    screened_passes: pd.DataFrame,
    latest_view_manifest: pd.DataFrame,
    *,
    l2t_results: Iterable[Any],
    expected_candidate_passes: int = EXPECTED_CANDIDATE_PASSES,
) -> pd.DataFrame:
    """Resolve the official cloud asset for every selected candidate granule."""

    candidates = frozen_candidate_passes(
        screened_passes, expected_candidate_passes=expected_candidate_passes
    )
    views = _candidate_view_rows(candidates, latest_view_manifest)
    target_columns = ["city", "granule_id", "orbit", "scene", "tile"]
    manifest = create_target_manifest(
        views[target_columns], l2t_results=l2t_results, l1b_geo_results=[]
    )
    clouds = manifest.loc[manifest["asset_type"].eq(CLOUD_COG)].copy()
    identity = ["city", "orbit", "scene", "tile", "granule_id"]
    if len(clouds) != len(views) or clouds.duplicated(identity).any():
        raise ValueError("Cloud manifest is not one-to-one with selected view granules")
    if not clouds["status"].astype(str).str.casefold().eq("available").all():
        missing_assets = int(
            (~clouds["status"].astype(str).str.casefold().eq("available")).sum()
        )
        raise ValueError(f"{missing_assets} exhaustive cloud assets are unresolved")

    view_provenance = views[
        identity
        + [
            "item_id",
            "selected_build",
            "selected_revision",
            "file_name",
        ]
        + [
            column
            for column in ("acquisition_utc", "year", "month")
            if column in views.columns
        ]
    ].rename(
        columns={
            "item_id": "view_item_id",
            "selected_build": "view_selected_build",
            "selected_revision": "view_selected_revision",
            "file_name": "view_file_name",
            "acquisition_utc": "granule_acquisition_utc",
        }
    )
    clouds = clouds.merge(
        view_provenance, on=identity, how="inner", validate="one_to_one"
    )
    build_equal = pd.to_numeric(clouds["selected_build"], errors="coerce").eq(
        pd.to_numeric(clouds["view_selected_build"], errors="coerce")
    )
    revision_equal = pd.to_numeric(
        clouds["selected_revision"], errors="coerce"
    ).eq(pd.to_numeric(clouds["view_selected_revision"], errors="coerce"))
    product_equal = clouds["selected_product_id"].astype(str).str.casefold().eq(
        clouds["granule_id"].astype(str).str.casefold()
    )
    if not (build_equal & revision_equal & product_equal).all():
        raise ValueError("Cloud/view product identity, build, or revision mismatch")

    pass_meta = candidates[["city", "orbit", "acquisition_utc"]].rename(
        columns={"acquisition_utc": "pass_acquisition_utc"}
    )
    clouds = clouds.merge(
        pass_meta, on=["city", "orbit"], how="left", validate="many_to_one"
    )
    clouds["pass_acquisition_utc"] = clouds["pass_acquisition_utc"].map(
        lambda value: value.isoformat()
    )
    clouds["target_scope"] = TARGET_SCOPE
    clouds["decision_id"] = DECISION_ID
    clouds["cloud_target_selected_before_outcome"] = True
    if set(clouds["asset_type"].astype(str)) != {CLOUD_COG}:
        raise ValueError("Exhaustive manifest contains a forbidden non-cloud asset")
    return clouds.sort_values(identity, kind="stable").reset_index(drop=True)


def _sha256_strings(values: Iterable[Any]) -> str:
    payload = "\n".join(sorted(str(value) for value in values)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _checkpoint_asset_evidence(
    rows: pd.DataFrame,
    checkpoint_items: Mapping[str, Mapping[str, Any]],
) -> tuple[bool, int, str]:
    evidence: list[str] = []
    total_bytes = 0
    for row in rows.to_dict("records"):
        item_id = str(row["item_id"])
        record = checkpoint_items.get(item_id)
        if not record or record.get("status") != "complete":
            return False, total_bytes, ""
        path_value = record.get("local_path")
        digest = str(record.get("sha256", ""))
        if not path_value or len(digest) != 64:
            return False, total_bytes, ""
        path = Path(str(path_value))
        expected_name = Path(str(row["file_name"])).name
        expected_size = record.get("size_bytes")
        if (
            not path.is_file()
            or path.name != expected_name
            or expected_size is None
            or path.stat().st_size != int(expected_size)
        ):
            return False, total_bytes, ""
        total_bytes += int(expected_size)
        evidence.append(f"{item_id}:{digest}:{int(expected_size)}")
    return True, total_bytes, _sha256_strings(evidence)


def run_exhaustive_cloud_audit(
    screened_passes: pd.DataFrame,
    cloud_manifest: pd.DataFrame,
    latest_view_manifest: pd.DataFrame,
    *,
    domain_geometries_wgs84: Mapping[str, Mapping[str, Any]],
    asset_root: str | Path,
    cloud_checkpoint_items: Mapping[str, Mapping[str, Any]],
    view_checkpoint_items: Mapping[str, Mapping[str, Any]],
    expected_candidate_passes: int = EXPECTED_CANDIDATE_PASSES,
) -> pd.DataFrame:
    """Compute one observed cloud-survival fraction for every frozen pass."""

    candidates = frozen_candidate_passes(
        screened_passes, expected_candidate_passes=expected_candidate_passes
    )
    clouds = cloud_manifest.copy()
    clouds["orbit"] = pd.to_numeric(clouds["orbit"], errors="raise").astype(int)
    if set(clouds["asset_type"].astype(str)) != {CLOUD_COG}:
        raise ValueError("Cloud audit manifest must contain cloud COG rows only")
    views = _candidate_view_rows(candidates, latest_view_manifest)
    target_granules = clouds[["city", "orbit", "scene", "tile", "granule_id"]]
    views = views.merge(
        target_granules,
        on=["city", "orbit", "scene", "tile", "granule_id"],
        how="inner",
        validate="one_to_one",
    )
    if len(views) != len(clouds):
        raise ValueError("Every exhaustive cloud row must retain its matching view row")

    tile_domains = {
        str(city): {
            str(tile): partition_domain_for_mgrs_tile(
                domain_geometries_wgs84[str(city)], str(tile)
            )
            for tile in sorted(group["tile"].astype(str).unique())
        }
        for city, group in views.groupby("city", sort=True)
    }
    cloud_groups = {
        (str(city), int(orbit)): group
        for (city, orbit), group in clouds.groupby(["city", "orbit"], sort=True)
    }
    view_groups = {
        (str(city), int(orbit)): group
        for (city, orbit), group in views.groupby(["city", "orbit"], sort=True)
    }
    candidate_keys = set(
        map(tuple, candidates[["city", "orbit"]].to_records(index=False))
    )
    if set(cloud_groups) != candidate_keys or set(view_groups) != candidate_keys:
        raise ValueError("Cloud/view pass keys do not exactly equal frozen candidates")

    rows: list[dict[str, Any]] = []
    for candidate in candidates.to_dict("records"):
        key = (str(candidate["city"]), int(candidate["orbit"]))
        cloud_rows = cloud_groups[key]
        view_rows = view_groups[key]
        cloud_complete, cloud_bytes, cloud_digest = _checkpoint_asset_evidence(
            cloud_rows, cloud_checkpoint_items
        )
        view_complete, view_bytes, view_digest = _checkpoint_asset_evidence(
            view_rows, view_checkpoint_items
        )
        identity = ["city", "orbit", "scene", "tile", "granule_id"]
        identity_equal = set(
            map(tuple, cloud_rows[identity].to_records(index=False))
        ) == set(map(tuple, view_rows[identity].to_records(index=False)))
        provenance_complete = bool(cloud_complete and view_complete and identity_equal)
        if not provenance_complete:
            raise ValueError(f"Incomplete asset/provenance evidence for pass {key}")
        denominator = int(candidate["n_domain_pixels"])
        result = summarize_cloud_pass(
            cloud_rows,
            view_rows,
            domain_geometry_wgs84=domain_geometries_wgs84[key[0]],
            asset_root=asset_root,
            domain_pixel_denominator=denominator,
            tile_domain_geometries_wgs84=tile_domains[key[0]],
        )
        if int(result["n_domain_pixels"]) != denominator:
            raise ValueError(f"Cloud denominator changed for pass {key}")
        if int(result["n_view_valid_pixels"]) != int(candidate["n_view_valid_pixels"]):
            raise ValueError(f"Cloud/view valid-pixel identity changed for pass {key}")
        acquisition = pd.Timestamp(candidate["acquisition_utc"])
        result.update(
            {
                "city": key[0],
                "orbit": key[1],
                "acquisition_utc": acquisition.isoformat(),
                "year": int(acquisition.year),
                "n_expected_scene_tiles": int(len(cloud_rows)),
                "n_resolved_cloud_assets": int(len(cloud_rows)),
                "n_verified_cloud_assets": int(len(cloud_rows)),
                "n_verified_view_assets": int(len(view_rows)),
                "cloud_asset_complete": cloud_complete,
                "view_asset_complete": view_complete,
                "provenance_complete": provenance_complete,
                "cloud_asset_bytes": cloud_bytes,
                "view_asset_bytes_reused": view_bytes,
                "cloud_asset_set_sha256": cloud_digest,
                "view_asset_set_sha256": view_digest,
                "source_granule_ids_sha256": _sha256_strings(
                    cloud_rows["granule_id"]
                ),
                "cloud_resolution_status": "observed_exhaustive_complete",
                "target_selection_rule": TARGET_SCOPE,
                "decision_id": DECISION_ID,
            }
        )
        rows.append(result)
    summary = pd.DataFrame(rows).sort_values(
        ["city", "acquisition_utc", "orbit"], kind="stable"
    )
    return summary.reset_index(drop=True)


def _summarize_cloud_without_view_mask(
    cloud_rows: pd.DataFrame,
    *,
    asset_root: str | Path,
    domain_pixel_denominator: int,
    tile_domain_geometries_wgs84: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Mosaic cloud codes without conditioning on L2T float-layer validity."""

    clouds = select_latest_tile_revisions(cloud_rows)
    if set(clouds["asset_type"].astype(str)) != {CLOUD_COG}:
        raise ValueError("Independent cloud summary accepts cloud COGs only")
    root = Path(asset_root)
    n_domain_present = 0
    n_clear = 0
    n_cloud = 0
    n_invalid = 0
    n_overlap = 0
    n_tiles = 0
    for tile, tile_rows in clouds.groupby("tile", sort=True):
        records = tile_rows.sort_values(
            ["scene", "selected_build", "selected_revision", "granule_id"],
            kind="stable",
        ).to_dict("records")
        first_path = root / CLOUD_COG / Path(str(records[0]["file_name"])).name
        with rasterio.open(first_path) as reference:
            clipped = _domain_window(
                reference, tile_domain_geometries_wgs84[str(tile)]
            )
            if clipped is None:
                continue
            window, domain = clipped
            observed_any = np.zeros(domain.shape, dtype=bool)
            clear_any = np.zeros(domain.shape, dtype=bool)
            cloudy_any = np.zeros(domain.shape, dtype=bool)
            unexpected_any = np.zeros(domain.shape, dtype=bool)
            for record in records:
                path = root / CLOUD_COG / Path(str(record["file_name"])).name
                if not path.is_file():
                    raise FileNotFoundError(path)
                with rasterio.open(path) as dataset:
                    _check_same_grid(reference, dataset)
                    layer = dataset.read(1, window=window, masked=True)
                data = np.asarray(layer.filled(255))
                unmasked = domain & ~np.ma.getmaskarray(layer)
                observed = unmasked & np.isin(data, (0, 1))
                n_overlap += int((observed & observed_any).sum())
                observed_any |= observed
                clear_any |= observed & (data == 0)
                cloudy_any |= observed & (data == 1)
                unexpected_any |= unmasked & ~np.isin(data, (0, 1, 255))
            invalid = domain & (~observed_any | unexpected_any)
            cloudy = domain & ~invalid & cloudy_any
            clear = domain & ~invalid & ~cloudy_any & clear_any
            if int(clear.sum() + cloudy.sum() + invalid.sum()) != int(domain.sum()):
                raise ValueError("Independent cloud classes do not partition the domain")
            n_domain_present += int(domain.sum())
            n_clear += int(clear.sum())
            n_cloud += int(cloudy.sum())
            n_invalid += int(invalid.sum())
            n_tiles += 1
    if int(domain_pixel_denominator) < n_domain_present:
        raise ValueError("Independent cloud denominator is smaller than present-tile pixels")
    n_invalid += int(domain_pixel_denominator) - n_domain_present
    return {
        "n_domain_pixels": int(domain_pixel_denominator),
        "n_domain_pixels_in_present_tiles": n_domain_present,
        "n_cloud_observed_pixels_independent_of_view": n_clear + n_cloud,
        "n_clear_pixels_independent_of_view": n_clear,
        "n_cloud_pixels_independent_of_view": n_cloud,
        "n_cloud_invalid_or_fill_pixels_independent_of_view": n_invalid,
        "cloud_survival_fraction_of_domain_independent_of_view": (
            n_clear / int(domain_pixel_denominator)
        ),
        "cloud_fraction_of_domain_independent_of_view": (
            n_cloud / int(domain_pixel_denominator)
        ),
        "n_unique_mgrs_tiles": n_tiles,
        "n_overlapping_cloud_observations": n_overlap,
        "independent_cloud_overlap_rule": "cloudy wins; invalid/unexpected does not survive",
    }


def run_cloud_view_dependency_audit(
    screened_passes: pd.DataFrame,
    cloud_manifest: pd.DataFrame,
    latest_view_manifest: pd.DataFrame,
    *,
    domain_geometries_wgs84: Mapping[str, Mapping[str, Any]],
    asset_root: str | Path,
    expected_candidate_passes: int = EXPECTED_CANDIDATE_PASSES,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Quantify whether L2T view validity is independent of cloud outcome.

    The pair table audits every selected scene/tile layer without mosaicking, so
    cloud/view missingness can be tested directly.  The pass table separately
    mosaics cloud codes without intersecting the float ``view_zenith`` mask.
    """

    candidates = frozen_candidate_passes(
        screened_passes, expected_candidate_passes=expected_candidate_passes
    )
    clouds = cloud_manifest.copy()
    clouds["orbit"] = pd.to_numeric(clouds["orbit"], errors="raise").astype(int)
    views = _candidate_view_rows(candidates, latest_view_manifest)
    identity = ["city", "orbit", "scene", "tile", "granule_id"]
    pairs = clouds.merge(
        views,
        on=identity,
        how="inner",
        suffixes=("_cloud", "_view"),
        validate="one_to_one",
    )
    if len(pairs) != len(clouds):
        raise ValueError("Cloud/view dependency audit is missing selected layer pairs")
    root = Path(asset_root)
    tile_domains = {
        str(city): {
            str(tile): partition_domain_for_mgrs_tile(
                domain_geometries_wgs84[str(city)], str(tile)
            )
            for tile in sorted(group["tile"].astype(str).unique())
        }
        for city, group in pairs.groupby("city", sort=True)
    }

    pair_rows: list[dict[str, Any]] = []
    for record in pairs.sort_values(identity, kind="stable").to_dict("records"):
        city = str(record["city"])
        tile = str(record["tile"])
        cloud_path = root / CLOUD_COG / Path(str(record["file_name_cloud"])).name
        view_path = root / VIEW_ZENITH_COG / Path(
            str(record["file_name_view"])
        ).name
        if not cloud_path.is_file() or not view_path.is_file():
            raise FileNotFoundError(cloud_path if not cloud_path.is_file() else view_path)
        counts = {
            "n_domain_pixels_in_pair_window": 0,
            "n_view_valid_pixels": 0,
            "n_view_invalid_pixels": 0,
            "n_cloud_code_observed_pixels": 0,
            "n_clear_pixels_independent_of_view": 0,
            "n_cloud_pixels_independent_of_view": 0,
            "n_cloud_invalid_or_fill_pixels_independent_of_view": 0,
            "n_view_valid_and_clear_pixels": 0,
            "n_view_valid_and_cloud_pixels": 0,
            "n_view_valid_and_cloud_invalid_pixels": 0,
            "n_view_invalid_and_clear_pixels": 0,
            "n_view_invalid_and_cloud_pixels": 0,
        }
        with rasterio.open(view_path) as view_ds, rasterio.open(cloud_path) as cloud_ds:
            _check_same_grid(view_ds, cloud_ds)
            clipped = _domain_window(view_ds, tile_domains[city][tile])
            if clipped is not None:
                window, domain = clipped
                view = view_ds.read(1, window=window, masked=True)
                cloud = cloud_ds.read(1, window=window, masked=True)
                view_data = np.asarray(view.filled(np.nan), dtype=float)
                cloud_data = np.asarray(cloud.filled(255))
                view_valid = (
                    domain
                    & ~np.ma.getmaskarray(view)
                    & np.isfinite(view_data)
                    & (np.abs(view_data) <= 90.0)
                )
                cloud_unmasked = domain & ~np.ma.getmaskarray(cloud)
                cloud_observed = cloud_unmasked & np.isin(cloud_data, (0, 1))
                clear = cloud_observed & (cloud_data == 0)
                cloudy = cloud_observed & (cloud_data == 1)
                cloud_invalid = domain & ~cloud_observed
                counts = {
                    "n_domain_pixels_in_pair_window": int(domain.sum()),
                    "n_view_valid_pixels": int(view_valid.sum()),
                    "n_view_invalid_pixels": int((domain & ~view_valid).sum()),
                    "n_cloud_code_observed_pixels": int(cloud_observed.sum()),
                    "n_clear_pixels_independent_of_view": int(clear.sum()),
                    "n_cloud_pixels_independent_of_view": int(cloudy.sum()),
                    "n_cloud_invalid_or_fill_pixels_independent_of_view": int(
                        cloud_invalid.sum()
                    ),
                    "n_view_valid_and_clear_pixels": int((view_valid & clear).sum()),
                    "n_view_valid_and_cloud_pixels": int((view_valid & cloudy).sum()),
                    "n_view_valid_and_cloud_invalid_pixels": int(
                        (view_valid & cloud_invalid).sum()
                    ),
                    "n_view_invalid_and_clear_pixels": int(
                        (domain & ~view_valid & clear).sum()
                    ),
                    "n_view_invalid_and_cloud_pixels": int(
                        (domain & ~view_valid & cloudy).sum()
                    ),
                }
        n_cloudy = counts["n_cloud_pixels_independent_of_view"]
        n_view = counts["n_view_valid_pixels"]
        n_overlap = counts["n_view_valid_and_cloud_pixels"]
        pair_rows.append(
            {
                **{column: record[column] for column in identity},
                "cloud_item_id": record["item_id_cloud"],
                "view_item_id": record["item_id_view"],
                **counts,
                "fraction_cloudy_pixels_with_valid_view": (
                    n_overlap / n_cloudy if n_cloudy else np.nan
                ),
                "fraction_view_valid_pixels_classified_cloud": (
                    n_overlap / n_view if n_view else np.nan
                ),
                "cloudy_and_view_valid_are_disjoint": bool(
                    n_cloudy > 0 and n_overlap == 0
                ),
                "tile_intersects_frozen_domain": bool(
                    counts["n_domain_pixels_in_pair_window"] > 0
                ),
                "decision_id": DECISION_ID,
            }
        )
    pair_summary = pd.DataFrame(pair_rows).sort_values(identity, kind="stable")

    cloud_groups = {
        (str(city), int(orbit)): group
        for (city, orbit), group in clouds.groupby(["city", "orbit"], sort=True)
    }
    pass_rows: list[dict[str, Any]] = []
    for candidate in candidates.to_dict("records"):
        key = (str(candidate["city"]), int(candidate["orbit"]))
        result = _summarize_cloud_without_view_mask(
            cloud_groups[key],
            asset_root=root,
            domain_pixel_denominator=int(candidate["n_domain_pixels"]),
            tile_domain_geometries_wgs84=tile_domains[key[0]],
        )
        acquisition = pd.Timestamp(candidate["acquisition_utc"])
        result.update(
            {
                "city": key[0],
                "orbit": key[1],
                "acquisition_utc": acquisition.isoformat(),
                "year": int(acquisition.year),
                "decision_id": DECISION_ID,
            }
        )
        pass_rows.append(result)
    independent_pass_summary = pd.DataFrame(pass_rows).sort_values(
        ["city", "acquisition_utc", "orbit"], kind="stable"
    )
    return pair_summary.reset_index(drop=True), independent_pass_summary.reset_index(
        drop=True
    )


def build_exhaustive_validation(
    cloud_pass_summary: pd.DataFrame,
    *,
    screened_passes: pd.DataFrame | None = None,
    cloud_view_dependency_diagnostic: pd.DataFrame | None = None,
    independent_cloud_pass_summary: pd.DataFrame | None = None,
    diagnostic_artifacts: Mapping[str, Any] | None = None,
    expected_cloud_view_layer_pairs: int | None = None,
    expected_candidate_passes: int = EXPECTED_CANDIDATE_PASSES,
) -> dict[str, Any]:
    """Build the D0033 one-row completeness and scientific-validity record."""

    required = {
        "city",
        "orbit",
        "n_domain_pixels",
        "n_view_valid_pixels",
        "n_clear_pixels",
        "cloud_survival_fraction_of_domain",
        "cloud_asset_complete",
        "view_asset_complete",
        "provenance_complete",
    }
    missing = sorted(required.difference(cloud_pass_summary.columns))
    if missing:
        raise ValueError(f"Cloud pass summary lacks columns: {missing}")
    summary = cloud_pass_summary.copy()
    summary["orbit"] = pd.to_numeric(summary["orbit"], errors="raise").astype(int)
    unique = not summary.duplicated(["city", "orbit"]).any()
    fractions = pd.to_numeric(
        summary["cloud_survival_fraction_of_domain"], errors="coerce"
    )
    finite = np.isfinite(fractions.to_numpy(dtype=float))
    counts_valid = (
        pd.to_numeric(summary["n_domain_pixels"], errors="coerce").gt(0)
        & pd.to_numeric(summary["n_view_valid_pixels"], errors="coerce").ge(0)
        & pd.to_numeric(summary["n_clear_pixels"], errors="coerce").ge(0)
        & pd.to_numeric(summary["n_clear_pixels"], errors="coerce").le(
            pd.to_numeric(summary["n_view_valid_pixels"], errors="coerce")
        )
        & pd.to_numeric(summary["n_view_valid_pixels"], errors="coerce").le(
            pd.to_numeric(summary["n_domain_pixels"], errors="coerce")
        )
    )
    ratio = pd.to_numeric(summary["n_clear_pixels"], errors="coerce") / pd.to_numeric(
        summary["n_domain_pixels"], errors="coerce"
    )
    fraction_identity = np.isclose(
        fractions.to_numpy(dtype=float), ratio.to_numpy(dtype=float), rtol=0, atol=1e-15
    )
    flags_complete = (
        _bool_series(summary["cloud_asset_complete"], name="cloud_asset_complete")
        & _bool_series(summary["view_asset_complete"], name="view_asset_complete")
        & _bool_series(summary["provenance_complete"], name="provenance_complete")
    )
    keys_equal = True
    if screened_passes is not None:
        candidates = frozen_candidate_passes(
            screened_passes, expected_candidate_passes=expected_candidate_passes
        )
        expected_keys = set(
            map(tuple, candidates[["city", "orbit"]].to_records(index=False))
        )
        observed_keys = set(
            map(tuple, summary[["city", "orbit"]].to_records(index=False))
        )
        keys_equal = observed_keys == expected_keys
    resolved = int(len(summary))
    finite_count = int(finite.sum())
    all_finite = finite_count == resolved
    sum_fraction = float(fractions.sum()) if all_finite else None
    floor_value = math.floor(sum_fraction) if sum_fraction is not None else None
    complete = bool(
        resolved == int(expected_candidate_passes)
        and finite_count == int(expected_candidate_passes)
        and unique
        and keys_equal
        and counts_valid.all()
        and fraction_identity.all()
        and flags_complete.all()
    )

    pair_count = 0
    pairs_with_cloud = 0
    pairs_with_cloud_and_zero_view_overlap = 0
    pairwise_cloud_pixels = 0
    pairwise_cloud_view_overlap = 0
    pairwise_clear_pixels = 0
    pairwise_view_valid_pixels = 0
    pairwise_view_valid_clear_pixels = 0
    pairwise_view_valid_cloud_invalid_pixels = 0
    pairs_with_view_valid_subset_of_clear = 0
    pair_diagnostic_complete = False
    if cloud_view_dependency_diagnostic is not None:
        diagnostic_required = {
            "city",
            "orbit",
            "scene",
            "tile",
            "granule_id",
            "n_view_valid_pixels",
            "n_clear_pixels_independent_of_view",
            "n_cloud_pixels_independent_of_view",
            "n_view_valid_and_clear_pixels",
            "n_view_valid_and_cloud_pixels",
            "n_view_valid_and_cloud_invalid_pixels",
        }
        diagnostic_missing = sorted(
            diagnostic_required.difference(cloud_view_dependency_diagnostic.columns)
        )
        if diagnostic_missing:
            raise ValueError(
                f"Cloud/view dependency diagnostic lacks columns: {diagnostic_missing}"
            )
        diagnostic = cloud_view_dependency_diagnostic.copy()
        diagnostic_identity = ["city", "orbit", "scene", "tile", "granule_id"]
        pair_count = int(len(diagnostic))
        pair_diagnostic_complete = bool(
            pair_count > 0
            and not diagnostic.duplicated(diagnostic_identity).any()
            and (
                expected_cloud_view_layer_pairs is None
                or pair_count == int(expected_cloud_view_layer_pairs)
            )
        )
        clear = pd.to_numeric(
            diagnostic["n_clear_pixels_independent_of_view"], errors="raise"
        )
        cloudy = pd.to_numeric(
            diagnostic["n_cloud_pixels_independent_of_view"], errors="raise"
        )
        overlap = pd.to_numeric(
            diagnostic["n_view_valid_and_cloud_pixels"], errors="raise"
        )
        view_valid = pd.to_numeric(
            diagnostic["n_view_valid_pixels"], errors="raise"
        )
        view_clear = pd.to_numeric(
            diagnostic["n_view_valid_and_clear_pixels"], errors="raise"
        )
        view_cloud_invalid = pd.to_numeric(
            diagnostic["n_view_valid_and_cloud_invalid_pixels"], errors="raise"
        )
        pairs_with_cloud = int(cloudy.gt(0).sum())
        pairs_with_cloud_and_zero_view_overlap = int(
            (cloudy.gt(0) & overlap.eq(0)).sum()
        )
        pairwise_cloud_pixels = int(cloudy.sum())
        pairwise_cloud_view_overlap = int(overlap.sum())
        pairwise_clear_pixels = int(clear.sum())
        pairwise_view_valid_pixels = int(view_valid.sum())
        pairwise_view_valid_clear_pixels = int(view_clear.sum())
        pairwise_view_valid_cloud_invalid_pixels = int(view_cloud_invalid.sum())
        pairs_with_view_valid_subset_of_clear = int(
            (
                view_valid.gt(0)
                & view_clear.eq(view_valid)
                & overlap.eq(0)
                & view_cloud_invalid.eq(0)
            ).sum()
        )

    independent_sum = None
    independent_floor = None
    independent_passes_finite = 0
    independent_pass_diagnostic_complete = False
    if independent_cloud_pass_summary is not None:
        independent_required = {
            "city",
            "orbit",
            "n_domain_pixels",
            "n_clear_pixels_independent_of_view",
            "n_cloud_pixels_independent_of_view",
            "n_cloud_invalid_or_fill_pixels_independent_of_view",
            "cloud_survival_fraction_of_domain_independent_of_view",
        }
        independent_missing = sorted(
            independent_required.difference(independent_cloud_pass_summary.columns)
        )
        if independent_missing:
            raise ValueError(
                f"Independent cloud pass summary lacks columns: {independent_missing}"
            )
        independent = independent_cloud_pass_summary.copy()
        independent["orbit"] = pd.to_numeric(
            independent["orbit"], errors="raise"
        ).astype(int)
        independent_fractions = pd.to_numeric(
            independent["cloud_survival_fraction_of_domain_independent_of_view"],
            errors="coerce",
        )
        independent_finite = np.isfinite(
            independent_fractions.to_numpy(dtype=float)
        )
        independent_passes_finite = int(independent_finite.sum())
        independent_partition = (
            pd.to_numeric(
                independent["n_clear_pixels_independent_of_view"], errors="raise"
            )
            + pd.to_numeric(
                independent["n_cloud_pixels_independent_of_view"], errors="raise"
            )
            + pd.to_numeric(
                independent["n_cloud_invalid_or_fill_pixels_independent_of_view"],
                errors="raise",
            )
        ).eq(pd.to_numeric(independent["n_domain_pixels"], errors="raise"))
        independent_keys = set(
            map(tuple, independent[["city", "orbit"]].to_records(index=False))
        )
        summary_keys = set(
            map(tuple, summary[["city", "orbit"]].to_records(index=False))
        )
        independent_pass_diagnostic_complete = bool(
            len(independent) == int(expected_candidate_passes)
            and not independent.duplicated(["city", "orbit"]).any()
            and independent_passes_finite == int(expected_candidate_passes)
            and independent_partition.all()
            and independent_keys == summary_keys
        )
        if independent_pass_diagnostic_complete:
            independent_sum = float(independent_fractions.sum())
            independent_floor = math.floor(independent_sum)

    # Exact zero overlap across a nonzero set of cloudy pixels demonstrates
    # that the float view-angle layer's valid mask is cloud-conditioned.  The
    # official tiled-product guide independently explains that float32 layers
    # use NaN where retrieval is unavailable and that cloud/water layers explain
    # those missing values.
    view_gate_cloud_conditioned = bool(
        pair_diagnostic_complete
        and pairwise_cloud_pixels > 0
        and pairwise_cloud_view_overlap == 0
    )
    candidate_seal_geometry_only = bool(
        pair_diagnostic_complete and not view_gate_cloud_conditioned
    )
    scientific_gate_eligible = bool(
        complete
        and independent_pass_diagnostic_complete
        and candidate_seal_geometry_only
    )
    gate_status = (
        "ELIGIBLE_EXHAUSTIVE_CLOUD_AUDIT"
        if scientific_gate_eligible
        else "STOP_CLOUD_CONDITIONED_VIEW_GATE"
    )
    record = {
        "decision_id": DECISION_ID,
        "expected_candidate_passes": int(expected_candidate_passes),
        "resolved_candidate_passes": resolved,
        "finite_survival_passes": finite_count,
        "candidate_keys_exact": bool(keys_equal and unique),
        "asset_and_provenance_complete": bool(flags_complete.all()),
        "count_identities_complete": bool(counts_valid.all() and fraction_identity.all()),
        "complete": complete,
        "complete_scope": "asset_census_and_observed_fraction_completeness_only",
        "sum_cloud_survival_fraction_of_domain": sum_fraction,
        "conservative_planning_floor": floor_value,
        "planning_floor_status": (
            "GATE_ELIGIBLE"
            if scientific_gate_eligible
            else "PROVISIONAL_NOT_GATE_ELIGIBLE"
        ),
        "planning_rule": (
            "floor of the sum of observed pass-specific clear/domain fractions"
        ),
        "candidate_selection_rule": TARGET_SCOPE,
        "cloud_estimation_method": "observed_exhaustive_no_extrapolation",
        "cloud_extrapolation_used": False,
        "n_cloud_view_layer_pairs_audited": pair_count,
        "expected_cloud_view_layer_pairs": (
            int(expected_cloud_view_layer_pairs)
            if expected_cloud_view_layer_pairs is not None
            else None
        ),
        "cloud_view_pair_diagnostic_complete": pair_diagnostic_complete,
        "n_pairs_with_cloud_pixels": pairs_with_cloud,
        "n_pairs_with_cloud_and_zero_valid_view_overlap": (
            pairs_with_cloud_and_zero_view_overlap
        ),
        "n_pairwise_cloud_pixels_independent_of_view": pairwise_cloud_pixels,
        "n_pairwise_clear_pixels_independent_of_view": pairwise_clear_pixels,
        "n_pairwise_cloud_pixels_with_valid_view": pairwise_cloud_view_overlap,
        "fraction_pairwise_cloud_pixels_with_valid_view": (
            pairwise_cloud_view_overlap / pairwise_cloud_pixels
            if pairwise_cloud_pixels
            else None
        ),
        "n_pairwise_view_valid_pixels": pairwise_view_valid_pixels,
        "n_pairwise_view_valid_and_clear_pixels": pairwise_view_valid_clear_pixels,
        "n_pairwise_view_valid_and_cloud_invalid_pixels": (
            pairwise_view_valid_cloud_invalid_pixels
        ),
        "n_pairs_where_view_valid_is_subset_of_clear": (
            pairs_with_view_valid_subset_of_clear
        ),
        "fraction_pairwise_view_valid_pixels_classified_clear": (
            pairwise_view_valid_clear_pixels / pairwise_view_valid_pixels
            if pairwise_view_valid_pixels
            else None
        ),
        "fraction_pairwise_view_valid_pixels_classified_cloud": (
            pairwise_cloud_view_overlap / pairwise_view_valid_pixels
            if pairwise_view_valid_pixels
            else None
        ),
        "independent_cloud_pass_diagnostic_complete": (
            independent_pass_diagnostic_complete
        ),
        "independent_cloud_finite_passes": independent_passes_finite,
        "sum_cloud_survival_fraction_independent_of_view": independent_sum,
        "conservative_planning_floor_independent_of_view": independent_floor,
        "view_gate_cloud_conditioned": view_gate_cloud_conditioned,
        "candidate_seal_geometry_only": candidate_seal_geometry_only,
        "candidate_view_mask_cloud_independent": candidate_seal_geometry_only,
        "scientific_gate_eligible": scientific_gate_eligible,
        "gate_status": gate_status,
        "canonical_status": gate_status,
        "requires_new_pre_outcome_decision": not scientific_gate_eligible,
        "recommended_remediation": (
            "repeat view screening for every metadata candidate with an unmasked "
            "geometry source such as L1B GEO before applying cloud outcomes"
        ),
        "official_tiled_product_semantics_source": (
            "https://lpdaac.usgs.gov/documents/1566/"
            "ECOL2-4_Grid_Tile_User_Guide_V2.pdf"
        ),
        "official_semantics_note": (
            "L2T float32 layers use NaN where retrieval is unavailable; the cloud "
            "and water masks explain missing values, so view_zenith valid coverage "
            "is not a geometry-only coverage measure"
        ),
        "lst_opened": False,
        "frozen_years": f"{FROZEN_FIRST_YEAR}-{FROZEN_LAST_YEAR}",
        "holdout_status": "UNSELECTED",
    }
    if diagnostic_artifacts:
        record.update({str(key): value for key, value in diagnostic_artifacts.items()})
    return record


__all__ = [
    "DECISION_ID",
    "EXPECTED_CANDIDATE_PASSES",
    "TARGET_SCOPE",
    "build_exhaustive_cloud_manifest",
    "build_exhaustive_validation",
    "frozen_candidate_passes",
    "load_cached_l2t_results",
    "run_cloud_view_dependency_audit",
    "run_exhaustive_cloud_audit",
]
