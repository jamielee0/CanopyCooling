#!/usr/bin/env python3
"""Run D0069's bounded, nonthermal Gate-3 geometry/cloud/weather augmentation."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import threading
from typing import Any, Mapping
from urllib.parse import urlsplit

import numpy as np
import pandas as pd
from pyproj import Transformer
from scipy.spatial import cKDTree


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in os.sys.path:
    os.sys.path.insert(0, str(ROOT / "src"))

import run_v2_step02_l1b_geometry as legacy_geometry

from urban_cooling_v2.domains import (
    geometry_bbox,
    sha256_json,
    valid_analysis_geometry,
)
from urban_cooling_v2.hitl_gate3_sampling import (
    PRIMARY_ANGLE_THRESHOLDS,
    add_antecedent_predictors,
    circular_mean_concentration,
    relative_azimuth_deg,
)
from urban_cooling_v2.step02_cloud_exhaustive import (
    _summarize_cloud_without_view_mask,
    build_exhaustive_cloud_manifest,
    load_cached_l2t_results,
)
from urban_cooling_v2.step02_enrich import load_checkpoint, write_checkpoint
from urban_cooling_v2.step02_enrich_fetch import (
    CLOUD_COG,
    VIEW_ZENITH_COG,
    create_target_manifest,
    download_target_manifest_concurrent,
)
from urban_cooling_v2.step02_hrrr_fetch import (
    HRRR_FORECAST_HOUR,
    HRRR_MODEL,
    HRRR_SEARCH_STRING,
    HRRR_SOURCE_LABEL,
    HrrrDependencyError,
    HrrrFetchError,
    _dataset_variable,
    _grid_coordinates,
    _two_dimensional,
    build_hrrr_request_manifest,
    dependency_status,
    estimate_hrrr_subset_downloads,
    extract_domain_cells,
    official_hrrr_product,
    summarize_domain_cells,
)
from urban_cooling_v2.step02_catalog import local_solar_dates
from urban_cooling_v2.step02_l1b_geometry import (
    BOUNDARY_GUARD_DISTANCE_M,
    FULL_SWATH_SHAPE,
    GEOMETRY_VARIABLES,
    G3_AZIMUTH_VARIABLES,
    LOCATOR_MARGIN_PIXELS,
    MAX_ADJACENT_SOURCE_DISPLACEMENT_M,
    RADIUS_OF_INFLUENCE_M,
    boundary_expansion_neighbors,
    build_canonical_target_grids,
    decode_selected_chunks,
    finalize_initial_selection_proof,
    initial_chunk_selection_with_proof,
    normalize_geo_records,
    parse_dmrpp_chunks_for_variables,
    resolve_latest_geo_scenes,
    sha256_file,
    sha256_strings,
)
from urban_cooling_v2.step02_live_manifest import cached_cmr_query
from urban_cooling_v2.step02_raster import partition_domain_for_mgrs_tile, _domain_window


DECISION_ID = "D0069"
ALGORITHM_VERSION = "d0069-g3-five-field-geometry-v2"
ZERO_MAP_PROOF_SCHEMA_VERSION = "d0079-generated-zero-map-proof-v1"
COLLECTION_CONCEPT_ID = "C2076087338-LPCLOUD"
COLLECTION_SHORT_NAME = "ECO_L1B_GEO"
COLLECTION_VERSION = "002"
COLLECTION_PROVIDER = "LPCLOUD"
D0047_ALGORITHM_VERSION = "d0047-archive-available-l1b-dmrpp-pass-stream-v2"
ALL_GEOMETRY_VARIABLES = GEOMETRY_VARIABLES + G3_AZIMUTH_VARIABLES
TEMPERATURE_SEARCH = r":(?:TMP|DPT):2 m"
WIND_SEARCH = r":(?:UGRD|VGRD):10 m above ground"
COMBINED_WEATHER_SEARCH = f"{TEMPERATURE_SEARCH}|{WIND_SEARCH}"
HRRR_SOURCE = (
    "NOAA HRRR public AWS archive; exact analysis f00 2-m TMP/DPT and "
    "10-m UGRD/VGRD; sfc with frozen prs fallback"
)
WEATHER_ALGORITHM_VERSION = "d0069-hrrr-exact-four-field-repaired-domains-v1"
HRRR_MIN_FREE_SPACE_RESERVE_BYTES = 5 * 1024**3
_L2T_ID_RE = re.compile(
    r"^ECOv002_L2T_LSTE_(?P<orbit>[0-9]{5})_(?P<scene>[0-9]{3})_"
    r"[^_]+_(?P<stamp>[0-9]{8}T[0-9]{6})_[0-9]+_[0-9]+$"
)
_GEO_ID_RE = re.compile(
    r"^ECOv002_L1B_GEO_(?P<orbit>[0-9]{5})_(?P<scene>[0-9]{3})_"
    r"(?P<stamp>[0-9]{8}T[0-9]{6})_[0-9]+_[0-9]+$"
)
PRIMARY_WINDOWS = {
    "atlanta": "jun_sep",
    "denver_aurora": "jun_sep",
    "minneapolis_st_paul": "jun_sep",
    "phoenix": "phoenix_apr_may",
}

DOMAINS_FILE = ROOT / "data/raw/v2/hitl/g3_sampling_design/candidate_domains_7.geojson"
NEW_METADATA = ROOT / "data/raw/v2/hitl/g3_sampling_design/candidate_additions_l2t_metadata_2018_2025.csv"
NEW_PASSES = ROOT / "docs/v2/hitl/G3_SAMPLING_DESIGN/candidate_addition_physical_metadata_passes.csv"
DAILY_GRIDMET = ROOT / "data/raw/v2/hitl/g3_sampling_design/candidate_city_daily_gridmet_2018_2025.csv"

EXISTING_GEOMETRY = ROOT / "data/processed/v2/task1/step2_quality_screening_l1b_geo_D0047/geometry_pass_summary.csv"
EXISTING_LINKS = ROOT / "data/processed/v2/task1/step2_quality_screening_l1b_geo_D0047/retained_city_scene_links.csv"
EXISTING_SCENE_MANIFEST = ROOT / "data/raw/v2/ecostress/l1b_geo_geometry_D0047_archive_available/l1b_geo_scene_manifest.csv"
EXISTING_DMRPP = ROOT / "data/raw/v2/ecostress/l1b_geo_geometry_D0047_archive_available/dmrpp"
EXISTING_LOCATOR = ROOT / "data/raw/v2/ecostress/l1b_geo_geometry_D0047_archive_available/locator_stride32"
EXISTING_ASSET_CHECKPOINT = ROOT / "data/raw/v2/ecostress/l1b_geo_geometry_D0047_archive_available/locator_dmrpp_checkpoint.json"
EXISTING_PASS_EVIDENCE = ROOT / "data/raw/v2/ecostress/l1b_geo_geometry_D0047_archive_available/pass_evidence"
EXISTING_VIEW_MANIFEST = ROOT / "data/raw/v2/ecostress/view_candidate_manifest_latest.csv"
EXISTING_DENOMINATORS = ROOT / "data/processed/v2/task1/step2_quality_screening/domain_pixel_denominators.csv"
EXISTING_L2T_CACHE = ROOT / "data/raw/v2/ecostress/enrichment_cmr_cache/l2t"
EXISTING_HRRR_SHARDS = ROOT / "data/raw/v2/weather/hrrr_exact_acquisition_l1b_geo_D0047_archive_available/hourly_domain_cells"

RAW = ROOT / "data/raw/v2/hitl/g3_sampling_design_revision2"
PROCESSED = ROOT / "data/processed/v2/hitl/g3_sampling_design_revision2"
NEW_GEO_ROOT = RAW / "new_l1b_geo"
NEW_GEO_CMR = NEW_GEO_ROOT / "cmr/by_scene"
NEW_DMRPP = NEW_GEO_ROOT / "dmrpp"
NEW_LOCATOR = NEW_GEO_ROOT / "locator_stride32"
NEW_ASSET_CHECKPOINT = NEW_GEO_ROOT / "locator_dmrpp_checkpoint.json"
NEW_SCENE_MANIFEST = NEW_GEO_ROOT / "l1b_geo_scene_manifest.csv"
NEW_L2T_CACHE = RAW / "new_l2t_cmr"
NEW_L2T_MANIFEST = RAW / "new_l2t_asset_manifest.csv"
ASSET_ROOT = ROOT / "data/raw/v2/ecostress/enrichment_assets"
G3_ASSET_CHECKPOINT = RAW / "l2t_asset_checkpoint.json"
PASS_EVIDENCE = RAW / "geometry_azimuth_pass_evidence"
GEOMETRY_RECONSTRUCTION = RAW / "geometry_azimuth_reconstruction"
GEOMETRY_RECONSTRUCTION_PREFLIGHT = RAW / "geometry_reconstruction_storage_preflight.json"
PASS_CHECKPOINT = RAW / "geometry_azimuth_checkpoint.json"
GEOMETRY_SUMMARY = PROCESSED / "geometry_azimuth_pass_summary.csv"
CLOUD_MANIFEST = RAW / "cloud_manifest.csv"
CLOUD_CHECKPOINT = RAW / "cloud_checkpoint.json"
CLOUD_SUMMARY = PROCESSED / "cloud_pass_summary.csv"
HRRR_ROOT = RAW / "hrrr_exact_acquisition"
HRRR_MANIFEST = RAW / "hrrr_exact_acquisition_manifest.csv"
HRRR_HOURLY_SUMMARY = HRRR_ROOT / "hrrr_hourly_domain_summary.csv"
HRRR_STORAGE_ESTIMATE = HRRR_ROOT / "hrrr_storage_estimate.csv"
HRRR_STORAGE_PREFLIGHT = HRRR_ROOT / "hrrr_storage_preflight.json"
WEATHER_PASS_SUMMARY = PROCESSED / "exact_weather_and_condition_pass_summary.csv"
UNAVAILABLE_CONDITION_PASS_SUMMARY = (
    PROCESSED / "new_unavailable_condition_pass_summary.csv"
)
AUGMENTATION_SUMMARY = PROCESSED / "augmentation_summary.json"
RUN_LOCK = RAW / ".augmentation.lock"

MAX_SELECTED_CHUNKS_PER_SCENE = 512
MAX_RANGE_BYTES_PER_SCENE = 320 * 1024 * 1024
EXPECTED_NEW_PASS_COUNT = 300
GEOMETRY_RECONSTRUCTION_FORMAT = "d0069-mapped-domain-cells-v1"
GEOMETRY_RECONSTRUCTION_MAX_BYTES = 8 * 1024**3
GEOMETRY_RECONSTRUCTION_RESERVE_BYTES = 5 * 1024**3
GEOMETRY_RECONSTRUCTION_CONTAINER_OVERHEAD_BYTES_PER_PASS = 1024**2
_NETCDF_LOCK = threading.Lock()


@contextmanager
def _exclusive_run_lock(*, stage: str, path: Path = RUN_LOCK):
    """Prevent concurrent augmentation writers from regressing checkpoints."""

    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(
                "Another Gate-3 augmentation process holds the exclusive run lock; "
                "refusing concurrent checkpoint writes"
            ) from exc
        handle.seek(0)
        handle.truncate()
        handle.write(
            f"pid={os.getpid()} stage={stage} acquired_utc="
            f"{datetime.now(timezone.utc).isoformat()}\n"
        )
        handle.flush()
        yield
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def _canonical_sha256(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _l2t_scene_acquisition_utc(granule_id: Any, orbit: Any, scene: Any) -> pd.Timestamp:
    """Return the exact L1B scene second encoded in a sealed L2T identity."""

    match = _L2T_ID_RE.fullmatch(str(granule_id))
    if match is None:
        raise ValueError(f"Invalid ECO_L2T_LSTE.002 granule identity: {granule_id!r}")
    if int(match.group("orbit")) != int(orbit) or int(match.group("scene")) != int(scene):
        raise ValueError("L2T granule orbit/scene fields disagree with the catalogue row")
    return pd.to_datetime(match.group("stamp"), format="%Y%m%dT%H%M%S", utc=True)


def _official_endpoint(value: Any, *, host: str) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    parsed = urlsplit(value.strip())
    return bool(
        parsed.scheme.casefold() == "https"
        and parsed.hostname == host
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
    )


def _validate_geo_manifest(
    manifest: pd.DataFrame,
    links: pd.DataFrame,
    *,
    require_provider_column: bool,
) -> None:
    """Fail closed unless every available scene has the frozen v002 identity."""

    required = {
        "orbit", "scene", "scene_acquisition_utc", "granule_id", "geo_acquisition_utc",
        "concept_id", "collection_concept_id", "opendap_url", "hdf_url", "dmrpp_url",
        "required_endpoints_complete", "cmr_record_sha256", "status", "collection_short_name",
        "collection_version",
    }
    missing = sorted(required.difference(manifest.columns))
    if missing:
        raise ValueError(f"G3 GEO manifest lacks sealed columns: {missing}")
    expected = links[["orbit", "scene", "scene_acquisition_utc"]].drop_duplicates().copy()
    if expected.duplicated(["orbit", "scene"]).any():
        raise ValueError("G3 scene links contain conflicting scene identities")
    observed = manifest[["orbit", "scene"]].copy()
    if (
        len(manifest) != len(expected)
        or observed.duplicated().any()
        or set(map(tuple, observed.astype(int).to_records(index=False)))
        != set(map(tuple, expected[["orbit", "scene"]].astype(int).to_records(index=False)))
    ):
        raise ValueError("G3 GEO manifest does not equal the required scene census")
    if not manifest["collection_short_name"].astype(str).eq(COLLECTION_SHORT_NAME).all():
        raise ValueError("G3 GEO manifest short-name seal failed")
    if not manifest["collection_version"].astype(str).str.zfill(3).eq(COLLECTION_VERSION).all():
        raise ValueError("G3 GEO manifest version seal failed")
    if require_provider_column and (
        "provider" not in manifest
        or not manifest["provider"].astype(str).eq(COLLECTION_PROVIDER).all()
    ):
        raise ValueError("G3 GEO manifest provider seal failed")
    allowed_status = {"available", "missing", "missing_required_endpoint"}
    if not manifest["status"].astype(str).isin(allowed_status).all():
        raise ValueError("G3 GEO manifest contains an unsealed status")

    expected_time = expected.assign(
        expected_second=pd.to_datetime(
            expected["scene_acquisition_utc"], utc=True, errors="raise", format="mixed"
        ).dt.floor("s")
    )[["orbit", "scene", "expected_second"]]
    available = manifest.loc[manifest["status"].astype(str).eq("available")].merge(
        expected_time, on=["orbit", "scene"], how="left", validate="one_to_one"
    )
    for row in available.to_dict("records"):
        geo_time = pd.Timestamp(row["geo_acquisition_utc"])
        geo_time = geo_time.tz_localize("UTC") if geo_time.tzinfo is None else geo_time.tz_convert("UTC")
        if geo_time.floor("s") != pd.Timestamp(row["expected_second"]):
            raise ValueError("Available G3 GEO scene is not an exact acquisition match")
        granule = str(row["granule_id"])
        identity = _GEO_ID_RE.fullmatch(granule)
        if (
            identity is None
            or int(identity.group("orbit")) != int(row["orbit"])
            or int(identity.group("scene")) != int(row["scene"])
            or pd.to_datetime(identity.group("stamp"), format="%Y%m%dT%H%M%S", utc=True)
            != geo_time.floor("s")
            or str(row["collection_concept_id"]) != COLLECTION_CONCEPT_ID
            or not str(row["concept_id"]).endswith("-LPCLOUD")
            or not bool(row["required_endpoints_complete"])
            or not re.fullmatch(r"[0-9a-f]{64}", str(row["cmr_record_sha256"]))
            or not _official_endpoint(row["opendap_url"], host="opendap.earthdata.nasa.gov")
            or not _official_endpoint(row["hdf_url"], host="data.lpdaac.earthdatacloud.nasa.gov")
            or str(row["dmrpp_url"]) != str(row["hdf_url"]) + ".dmrpp"
            or not str(row["hdf_url"]).endswith(f"/{granule}.h5")
            or f"/{COLLECTION_SHORT_NAME}.{COLLECTION_VERSION}/" not in str(row["hdf_url"])
        ):
            raise ValueError(f"Available G3 GEO scene failed source/endpoint seal: {granule}")


def _average_tie_reference_percentile(reference: Any, values: Any) -> np.ndarray:
    """Map values to Gate-2 average-tie empirical percentiles on [0, 1]."""

    reference_array = np.asarray(reference, dtype=float)
    reference_array = reference_array[np.isfinite(reference_array)]
    if not len(reference_array):
        raise ValueError("Percentile reference distribution is empty")
    targets = np.asarray(values, dtype=float)
    result = np.full(targets.shape, np.nan, dtype=float)
    finite = np.isfinite(targets)
    if len(reference_array) == 1:
        result[finite] = 0.5
        return result
    ordered = np.sort(reference_array)
    unique = np.unique(ordered)
    percentiles = []
    for value in unique:
        left = int(np.searchsorted(ordered, value, side="left"))
        right = int(np.searchsorted(ordered, value, side="right"))
        average_rank = (left + 1 + right) / 2.0
        percentiles.append((average_rank - 1.0) / (len(ordered) - 1.0))
    result[finite] = np.interp(targets[finite], unique, percentiles, left=0.0, right=1.0)
    return result


def _right_open_tercile(percentiles: Any, labels: tuple[str, str, str]) -> np.ndarray:
    values = np.asarray(percentiles, dtype=float)
    output = np.full(values.shape, "", dtype=object)
    finite = np.isfinite(values)
    output[finite] = np.select(
        [values[finite] < 1 / 3, values[finite] < 2 / 3],
        [labels[0], labels[1]],
        default=labels[2],
    )
    return output


def _atomic_json(payload: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


def _atomic_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    frame.to_csv(temporary, index=False)
    temporary.replace(path)


def _pass_identities(frame: pd.DataFrame) -> set[tuple[str, str, int, str]]:
    required = {"city", "window_id", "orbit", "acquisition_utc"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"Pass table lacks identity columns: {missing}")
    stamps = pd.to_datetime(
        frame["acquisition_utc"], utc=True, errors="raise", format="mixed"
    ).map(lambda value: value.isoformat())
    return set(
        zip(
            frame["city"].astype(str),
            frame["window_id"].astype(str),
            pd.to_numeric(frame["orbit"], errors="raise").astype(int),
            stamps,
            strict=True,
        )
    )


def _domains() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    document = json.loads(DOMAINS_FILE.read_text(encoding="utf-8"))
    provenance = json.loads(
        DOMAINS_FILE.with_suffix(DOMAINS_FILE.suffix + ".provenance.json").read_text(
            encoding="utf-8"
        )
    )
    expected = {
        str(record["city"]): record for record in provenance["records"]
    }
    features = {
        str(feature["properties"]["city"]): feature for feature in document["features"]
    }
    selected = {}
    geometries = {}
    for city in PRIMARY_WINDOWS:
        source = dict(features[city]["geometry"])
        analysis = valid_analysis_geometry(source)
        if (
            sha256_json(source) != str(expected[city]["source_geometry_sha256"])
            or sha256_json(analysis) != str(expected[city]["analysis_geometry_sha256"])
        ):
            raise ValueError(f"{city}: frozen source/analysis geometry hash mismatch")
        feature = json.loads(json.dumps(features[city]))
        feature["geometry"] = analysis
        feature["properties"]["source_geometry_sha256"] = sha256_json(source)
        feature["properties"]["analysis_geometry_sha256"] = sha256_json(analysis)
        feature["properties"]["topology_repair_applied"] = source != analysis
        selected[city] = feature
        geometries[city] = analysis
    return selected, geometries


def _new_passes_and_targets() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    passes = pd.read_csv(NEW_PASSES)
    mask = passes["time_stratum"].notna() & (
        (passes["city"].eq("denver_aurora") & passes["window_id"].eq("jun_sep"))
        | (passes["city"].eq("phoenix") & passes["window_id"].eq("phoenix_apr_may"))
    )
    passes = passes.loc[mask].copy()
    passes["orbit"] = pd.to_numeric(passes["orbit"], errors="raise").astype(int)
    passes["acquisition_utc"] = pd.to_datetime(
        passes["acquisition_utc"], utc=True, errors="raise", format="mixed"
    )
    if len(passes) != 300 or passes.duplicated(["city", "orbit"]).any():
        raise ValueError("D0069 new daytime pass seal changed")
    metadata = pd.read_csv(NEW_METADATA)
    metadata["orbit"] = pd.to_numeric(metadata["orbit"], errors="raise").astype(int)
    metadata["scene"] = pd.to_numeric(metadata["scene"], errors="raise").astype(int)
    targets = metadata.merge(
        passes[["city", "window_id", "orbit"]],
        on=["city", "window_id", "orbit"],
        how="inner",
        validate="many_to_one",
    )
    targets["acquisition_utc"] = pd.to_datetime(
        targets["acquisition_utc"], utc=True, errors="raise", format="mixed"
    )
    revisions = targets["granule_id"].astype(str).str.extract(r"_(?P<build>[0-9]+)_(?P<revision>[0-9]+)$")
    if revisions.isna().any().any():
        raise ValueError("A new L2T identity lacks build/revision fields")
    targets["_build"] = revisions["build"].astype(int)
    targets["_revision"] = revisions["revision"].astype(int)
    targets = (
        targets.sort_values(
            ["city", "orbit", "scene", "tile", "_build", "_revision", "granule_id"],
            kind="stable",
        )
        .drop_duplicates(["city", "orbit", "scene", "tile"], keep="last")
        .drop(columns=["_build", "_revision"])
    )
    targets["scene_acquisition_utc"] = [
        _l2t_scene_acquisition_utc(granule, orbit, scene)
        for granule, orbit, scene in targets[
            ["granule_id", "orbit", "scene"]
        ].itertuples(index=False)
    ]
    scene_time_counts = targets.groupby(["city", "orbit", "scene"])[
        "scene_acquisition_utc"
    ].nunique()
    if scene_time_counts.ne(1).any():
        raise ValueError("Tiled L2T records disagree on their encoded scene timestamp")
    links = (
        targets.groupby(["city", "orbit", "scene"], as_index=False)
        .agg(scene_acquisition_utc=("scene_acquisition_utc", "first"))
    )
    if len(links) != 488 or links.duplicated(["orbit", "scene"]).any():
        raise ValueError("D0069 new L1B scene-link seal changed")
    return passes.reset_index(drop=True), targets.reset_index(drop=True), links.reset_index(drop=True)


def _l2t_query(city: str, year: int, feature: Mapping[str, Any]) -> dict[str, Any]:
    window = PRIMARY_WINDOWS[city]
    start_md, end_md = (("04-01", "05-31") if window == "phoenix_apr_may" else ("06-01", "09-30"))
    return {
        "short_name": "ECO_L2T_LSTE",
        "version": "002",
        "provider": "LPCLOUD",
        "bounding_box": geometry_bbox(feature["geometry"]),
        "temporal": (f"{year}-{start_md}T00:00:00Z", f"{year}-{end_md}T23:59:59Z"),
        "count": -1,
    }


def _prepare_new_l2t_assets(earthaccess: Any, features: Mapping[str, Any]) -> pd.DataFrame:
    _, targets, _ = _new_passes_and_targets()
    results: list[dict[str, Any]] = []
    for city in ("denver_aurora", "phoenix"):
        for year in range(2018, 2026):
            query = _l2t_query(city, year, features[city])
            path = NEW_L2T_CACHE / city / f"{year}.json"
            results.extend(
                cached_cmr_query(path, search_data=earthaccess.search_data, query=query)
            )
    manifest = create_target_manifest(
        targets[["city", "granule_id", "orbit", "scene"]],
        l2t_results=results,
        l1b_geo_results=[],
    )
    l2t = manifest.loc[manifest["asset_type"].isin([VIEW_ZENITH_COG, CLOUD_COG])].copy()
    if not l2t["status"].astype(str).eq("available").all():
        raise RuntimeError("A required nonthermal L2T view/cloud asset is unresolved")
    _atomic_csv(l2t, NEW_L2T_MANIFEST)
    views = l2t.loc[l2t["asset_type"].eq(VIEW_ZENITH_COG)].copy()
    references = (
        views.sort_values(
            ["city", "tile", "scene", "selected_build", "selected_revision", "granule_id"],
            kind="stable",
        )
        .drop_duplicates(["city", "tile"], keep="first")
    )
    download_target_manifest_concurrent(
        references,
        destination_root=ASSET_ROOT,
        checkpoint_path=G3_ASSET_CHECKPOINT,
        session_factory=earthaccess.get_requests_https_session,
        max_workers=8,
    )
    return l2t


def _new_denominators(l2t_manifest: pd.DataFrame, geometries: Mapping[str, Any]) -> pd.DataFrame:
    views = l2t_manifest.loc[l2t_manifest["asset_type"].eq(VIEW_ZENITH_COG)].copy()
    references = (
        views.sort_values(
            ["city", "tile", "scene", "selected_build", "selected_revision", "granule_id"],
            kind="stable",
        )
        .drop_duplicates(["city", "tile"], keep="first")
    )
    rows = []
    for record in references.to_dict("records"):
        import rasterio

        city, tile = str(record["city"]), str(record["tile"])
        path = ASSET_ROOT / VIEW_ZENITH_COG / Path(str(record["file_name"])).name
        tile_domain = partition_domain_for_mgrs_tile(geometries[city], tile)
        with rasterio.open(path) as dataset:
            clipped = _domain_window(dataset, tile_domain)
            count = int(clipped[1].sum()) if clipped is not None else 0
        rows.append({"city": city, "tile": tile, "n_domain_pixel_centers": count})
    table = pd.DataFrame(rows)
    totals = table.groupby("city")["n_domain_pixel_centers"].transform("sum")
    table["city_domain_pixel_denominator"] = totals.astype(int)
    if table["n_domain_pixel_centers"].le(0).any():
        raise ValueError("A new city/tile target denominator is empty")
    _atomic_csv(table, PROCESSED / "new_city_domain_pixel_denominators.csv")
    return table


def _exact_scene_query(orbit: int, scene: int) -> dict[str, Any]:
    return {
        "short_name": "ECO_L1B_GEO",
        "version": "002",
        "provider": "LPCLOUD",
        "granule_name": f"ECOv002_L1B_GEO_{orbit:05d}_{scene:03d}_*",
        "count": -1,
    }


def _prepare_new_scene_manifest(earthaccess: Any, links: pd.DataFrame, workers: int) -> pd.DataFrame:
    keys = [tuple(map(int, value)) for value in links[["orbit", "scene"]].to_records(index=False)]
    results: list[dict[str, Any]] = []
    failures: dict[tuple[int, int], str] = {}

    def query(key: tuple[int, int]) -> list[dict[str, Any]]:
        orbit, scene = key
        return cached_cmr_query(
            NEW_GEO_CMR / f"{orbit:05d}_{scene:03d}.json",
            search_data=earthaccess.search_data,
            query=_exact_scene_query(orbit, scene),
        )

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(query, key): key for key in keys}
        for future in as_completed(futures):
            key = futures[future]
            try:
                results.extend(future.result())
            except Exception as exc:
                failures[key] = type(exc).__name__
    records = normalize_geo_records(results)
    manifest = resolve_latest_geo_scenes(
        links, records, expected_unique_scenes=len(links)
    )
    manifest["cmr_query_error_type"] = [
        failures.get((int(row.orbit), int(row.scene)), "")
        for row in manifest.itertuples(index=False)
    ]
    manifest["cities"] = manifest["orbit"].map(
        links.groupby("orbit")["city"].first().to_dict()
    )
    manifest["decision_id"] = DECISION_ID
    manifest["collection_short_name"] = COLLECTION_SHORT_NAME
    manifest["collection_version"] = COLLECTION_VERSION
    manifest["provider"] = COLLECTION_PROVIDER
    manifest["record_2026_opened"] = False
    manifest["temperature_or_lst_opened"] = False
    _validate_geo_manifest(manifest, links, require_provider_column=True)
    _atomic_csv(manifest, NEW_SCENE_MANIFEST)
    return manifest


def _metadata_asset_cache_valid(
    source: Mapping[str, Any],
    cached: Mapping[str, Any],
    dmrpp: Path,
    locator: Path,
) -> bool:
    """Validate the complete source/file binding before reusing metadata assets."""

    if not dmrpp.is_file() or not locator.is_file():
        return False
    expected = {
        "status": "complete",
        "algorithm_version": ALGORITHM_VERSION,
        "decision_id": DECISION_ID,
        "collection_short_name": COLLECTION_SHORT_NAME,
        "collection_version": COLLECTION_VERSION,
        "provider": COLLECTION_PROVIDER,
        "collection_concept_id": COLLECTION_CONCEPT_ID,
        "concept_id": str(source["concept_id"]),
        "granule_id": str(source["granule_id"]),
        "cmr_record_sha256": str(source["cmr_record_sha256"]),
        "hdf_url": str(source["hdf_url"]),
        "dmrpp_url": str(source["dmrpp_url"]),
        "opendap_url": str(source["opendap_url"]),
    }
    if any(str(cached.get(key, "")) != str(value) for key, value in expected.items()):
        return False
    return bool(
        tuple(cached.get("variables", ())) == tuple(ALL_GEOMETRY_VARIABLES)
        and int(cached.get("dmrpp_size_bytes", -1)) == dmrpp.stat().st_size
        and int(cached.get("locator_size_bytes", -1)) == locator.stat().st_size
        and cached.get("dmrpp_sha256") == sha256_file(dmrpp)
        and cached.get("locator_sha256") == sha256_file(locator)
    )


def _bound_metadata_asset_record(
    source: Mapping[str, Any], dmrpp: Path, locator: Path
) -> dict[str, Any]:
    return {
        "status": "complete",
        "algorithm_version": ALGORITHM_VERSION,
        "granule_id": str(source["granule_id"]),
        "cmr_record_sha256": str(source["cmr_record_sha256"]),
        "concept_id": str(source["concept_id"]),
        "collection_concept_id": COLLECTION_CONCEPT_ID,
        "collection_short_name": COLLECTION_SHORT_NAME,
        "collection_version": COLLECTION_VERSION,
        "provider": COLLECTION_PROVIDER,
        "hdf_url": str(source["hdf_url"]),
        "dmrpp_url": str(source["dmrpp_url"]),
        "opendap_url": str(source["opendap_url"]),
        "dmrpp_sha256": sha256_file(dmrpp),
        "locator_sha256": sha256_file(locator),
        "dmrpp_size_bytes": dmrpp.stat().st_size,
        "locator_size_bytes": locator.stat().st_size,
        "variables": list(ALL_GEOMETRY_VARIABLES),
        "decision_id": DECISION_ID,
    }


def _fetch_new_metadata_assets(
    earthaccess: Any, manifest: pd.DataFrame, workers: int
) -> None:
    available = manifest.loc[manifest["status"].astype(str).eq("available")].copy()
    checkpoint = load_checkpoint(NEW_ASSET_CHECKPOINT)
    local = threading.local()
    lock = threading.Lock()

    def worker(record: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        granule = str(record["granule_id"])
        dmrpp = NEW_DMRPP / f"{granule}.h5.dmrpp"
        locator = NEW_LOCATOR / f"{granule}_stride32.nc4"
        previous = checkpoint.get(granule, {})
        if _metadata_asset_cache_valid(record, previous, dmrpp, locator):
            parse_dmrpp_chunks_for_variables(dmrpp, ALL_GEOMETRY_VARIABLES)
            legacy_geometry._validate_locator(locator)
            return granule, dict(previous)
        # Upgrade a pre-seal D0069 checkpoint without another download only
        # when its CMR digest and both byte-level file hashes already agree.
        if (
            dmrpp.is_file()
            and locator.is_file()
            and previous.get("status") == "complete"
            and previous.get("cmr_record_sha256") == str(record["cmr_record_sha256"])
            and previous.get("dmrpp_sha256") == sha256_file(dmrpp)
            and previous.get("locator_sha256") == sha256_file(locator)
            and tuple(previous.get("variables", ())) == tuple(ALL_GEOMETRY_VARIABLES)
        ):
            parse_dmrpp_chunks_for_variables(dmrpp, ALL_GEOMETRY_VARIABLES)
            legacy_geometry._validate_locator(locator)
            upgraded = _bound_metadata_asset_record(record, dmrpp, locator)
            if not _metadata_asset_cache_valid(record, upgraded, dmrpp, locator):
                raise RuntimeError(f"Metadata asset checkpoint upgrade failed: {granule}")
            return granule, upgraded
        # An unbound local object cannot be treated as evidence for this CMR identity.
        for stale in (dmrpp, locator):
            if stale.is_file():
                stale.unlink()
        if not hasattr(local, "session"):
            local.session = earthaccess.get_requests_https_session()
        dmrpp_bytes, dmrpp_hash = legacy_geometry._get_file(
            local.session,
            str(record["dmrpp_url"]),
            dmrpp,
            item_id=f"{granule}:dmrpp",
            max_bytes=16 * 1024 * 1024,
        )
        parse_dmrpp_chunks_for_variables(dmrpp, ALL_GEOMETRY_VARIABLES)
        locator_bytes, locator_hash = legacy_geometry._get_file(
            local.session,
            str(record["opendap_url"]) + ".dap.nc4",
            locator,
            item_id=f"{granule}:locator",
            max_bytes=8 * 1024 * 1024,
            params={"dap4.ce": legacy_geometry._locator_constraint()},
        )
        legacy_geometry._validate_locator(locator)
        evidence = _bound_metadata_asset_record(record, dmrpp, locator)
        if (
            evidence["dmrpp_sha256"] != dmrpp_hash
            or evidence["locator_sha256"] != locator_hash
            or int(evidence["dmrpp_size_bytes"]) != dmrpp_bytes
            or int(evidence["locator_size_bytes"]) != locator_bytes
        ):
            raise RuntimeError(f"Downloaded metadata asset changed before binding: {granule}")
        return granule, evidence

    records = available.sort_values(["orbit", "scene"]).to_dict("records")
    for start in range(0, len(records), 50):
        failures = []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(worker, row): row for row in records[start : start + 50]}
            for future in as_completed(futures):
                row = futures[future]
                try:
                    granule, evidence = future.result()
                    with lock:
                        checkpoint[granule] = evidence
                except Exception as exc:
                    failures.append((str(row["granule_id"]), type(exc).__name__))
        write_checkpoint(NEW_ASSET_CHECKPOINT, checkpoint)
        print(f"D0069 new locator/DMR++ assets: {min(start + 50, len(records))}/{len(records)}", flush=True)
        if failures:
            raise RuntimeError(f"New locator/DMR++ failures: {failures[:5]}")


def prepare(workers: int) -> None:
    features, geometries = _domains()
    passes, _, links = _new_passes_and_targets()
    earthaccess, _ = legacy_geometry._earthaccess()
    l2t = _prepare_new_l2t_assets(earthaccess, features)
    denominators = _new_denominators(l2t, geometries)
    build_canonical_target_grids(
        l2t,
        domain_geometries_wgs84=geometries,
        asset_root=ASSET_ROOT,
        denominator_table=denominators,
    )
    manifest = _prepare_new_scene_manifest(earthaccess, links, workers)
    _fetch_new_metadata_assets(earthaccess, manifest, workers)
    passes = _derive_new_pass_archive_status(passes, links, manifest)
    _atomic_csv(passes, PROCESSED / "new_pass_archive_status.csv")
    print(
        "D0069 prepare complete: "
        + json.dumps(passes["archive_status"].value_counts().to_dict(), sort_keys=True),
        flush=True,
    )
    # Persist the full outcome before stopping so the unresolved identity is
    # auditable and a later retry cannot silently change the denominator.
    _validated_new_archive_status(
        passes,
        expected_unavailable=None,
        fail_on_unresolved=True,
    )


def _derive_new_pass_archive_status(
    passes: pd.DataFrame,
    links: pd.DataFrame,
    scene_manifest: pd.DataFrame,
) -> pd.DataFrame:
    """Deterministically derive every pass status from its exact required scenes."""

    required_passes = {"city", "orbit"}
    required_links = {"city", "orbit", "scene"}
    required_manifest = {"orbit", "scene", "status", "cmr_query_error_type"}
    if required_passes.difference(passes.columns):
        raise ValueError("D0069 pass census lacks city/orbit identity fields")
    if required_links.difference(links.columns):
        raise ValueError("D0069 scene links lack city/orbit/scene identity fields")
    if required_manifest.difference(scene_manifest.columns):
        raise ValueError("D0069 scene manifest lacks status/error provenance fields")
    rows = passes.copy()
    rows["orbit"] = pd.to_numeric(rows["orbit"], errors="raise").astype(int)
    exact_links = links.copy()
    exact_links["orbit"] = pd.to_numeric(exact_links["orbit"], errors="raise").astype(int)
    exact_links["scene"] = pd.to_numeric(exact_links["scene"], errors="raise").astype(int)
    scene = scene_manifest.copy()
    scene["orbit"] = pd.to_numeric(scene["orbit"], errors="raise").astype(int)
    scene["scene"] = pd.to_numeric(scene["scene"], errors="raise").astype(int)
    pass_keys = set(rows[["city", "orbit"]].itertuples(index=False, name=None))
    link_pass_keys = set(exact_links[["city", "orbit"]].itertuples(index=False, name=None))
    scene_keys = set(scene[["orbit", "scene"]].itertuples(index=False, name=None))
    link_scene_keys = set(exact_links[["orbit", "scene"]].itertuples(index=False, name=None))
    if (
        len(rows) != EXPECTED_NEW_PASS_COUNT
        or rows.duplicated(["city", "orbit"]).any()
        or len(scene) != 488
        or scene.duplicated(["orbit", "scene"]).any()
        or len(exact_links) != 488
        or exact_links.duplicated(["orbit", "scene"]).any()
        or link_pass_keys != pass_keys
        or scene_keys != link_scene_keys
    ):
        raise ValueError("D0069 exact scene manifest/link census changed")
    allowed_scene_statuses = {"available", "missing", "missing_required_endpoint"}
    if not set(scene["status"].astype(str)).issubset(allowed_scene_statuses):
        raise ValueError("D0069 scene manifest contains an unsealed archive status")
    scene_lookup = scene.set_index(["orbit", "scene"])
    derived = []
    for record in rows.to_dict("records"):
        required = exact_links.loc[
            exact_links["city"].eq(record["city"])
            & exact_links["orbit"].eq(record["orbit"]),
            ["orbit", "scene"],
        ]
        if required.empty:
            raise ValueError("A D0069 pass has no exact required orbit/scene links")
        keys = [tuple(map(int, value)) for value in required.to_records(index=False)]
        records = scene_lookup.loc[keys]
        has_error = records["cmr_query_error_type"].fillna("").astype(str).str.strip().ne("").any()
        all_available = records["status"].astype(str).eq("available").all()
        derived.append(
            "UNRESOLVED_ERROR" if has_error else ("ACCESSIBLE" if all_available else "RESOLVED_UNAVAILABLE")
        )
    rows["archive_status"] = derived
    return rows


def _target_grids(geometries: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    existing_views = pd.read_csv(EXISTING_VIEW_MANIFEST)
    existing_denominators = pd.read_csv(EXISTING_DENOMINATORS)
    existing = build_canonical_target_grids(
        existing_views,
        domain_geometries_wgs84=geometries,
        asset_root=ASSET_ROOT,
        denominator_table=existing_denominators.loc[
            existing_denominators["city"].isin(["atlanta", "minneapolis_st_paul"])
        ],
    )
    new_l2t = pd.read_csv(NEW_L2T_MANIFEST)
    new_denominators = pd.read_csv(PROCESSED / "new_city_domain_pixel_denominators.csv")
    new = build_canonical_target_grids(
        new_l2t,
        domain_geometries_wgs84=geometries,
        asset_root=ASSET_ROOT,
        denominator_table=new_denominators,
    )
    return {**existing, **new}


def _validated_new_archive_status(
    frame: pd.DataFrame,
    *,
    expected_unavailable: int | None = None,
    fail_on_unresolved: bool,
) -> pd.DataFrame:
    """Validate and freeze the new-pass archive census before downstream use."""

    required = {"city", "window_id", "orbit", "acquisition_utc", "archive_status"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"D0069 new archive census lacks columns: {missing}")
    work = frame.copy()
    work["orbit"] = pd.to_numeric(work["orbit"], errors="raise").astype(int)
    work["acquisition_utc"] = pd.to_datetime(
        work["acquisition_utc"], utc=True, errors="raise", format="mixed"
    )
    allowed = {"ACCESSIBLE", "RESOLVED_UNAVAILABLE", "UNRESOLVED_ERROR"}
    if (
        len(work) != EXPECTED_NEW_PASS_COUNT
        or work.duplicated(["city", "orbit"]).any()
        or not set(work["archive_status"].astype(str)).issubset(allowed)
        or set(work["city"].astype(str)) != {"denver_aurora", "phoenix"}
        or any(
            PRIMARY_WINDOWS.get(str(city)) != str(window)
            for city, window in work[["city", "window_id"]].itertuples(index=False)
        )
    ):
        raise ValueError("D0069 new archive census identity/status seal failed")
    original, _, _ = _new_passes_and_targets()
    if _pass_identities(work) != _pass_identities(original):
        raise ValueError("D0069 new archive census does not equal the frozen 300 passes")
    _, _, links = _new_passes_and_targets()
    manifest = pd.read_csv(NEW_SCENE_MANIFEST)
    expected = _derive_new_pass_archive_status(original, links, manifest)
    comparison = work[["city", "orbit", "archive_status"]].merge(
        expected[["city", "orbit", "archive_status"]],
        on=["city", "orbit"],
        suffixes=("_observed", "_derived"),
        validate="one_to_one",
    )
    if not comparison["archive_status_observed"].astype(str).eq(
        comparison["archive_status_derived"].astype(str)
    ).all():
        raise ValueError("D0069 new pass archive statuses do not match exact scene provenance")
    unresolved = work["archive_status"].astype(str).eq("UNRESOLVED_ERROR")
    if fail_on_unresolved and unresolved.any():
        raise RuntimeError(
            f"D0069 archive census retains {int(unresolved.sum())} UNRESOLVED_ERROR passes"
        )
    unavailable = work["archive_status"].astype(str).eq("RESOLVED_UNAVAILABLE")
    if expected_unavailable is not None and int(unavailable.sum()) != int(expected_unavailable):
        raise ValueError(
            "D0069 resolved-unavailable new-pass census changed: "
            f"expected {expected_unavailable}, found {int(unavailable.sum())}"
        )
    return work


def _new_unavailable_weather_population() -> pd.DataFrame:
    archive = _validated_new_archive_status(
        pd.read_csv(PROCESSED / "new_pass_archive_status.csv"),
        fail_on_unresolved=True,
    )
    unavailable = archive.loc[
        archive["archive_status"].astype(str).eq("RESOLVED_UNAVAILABLE")
    ].copy()
    unavailable["source_population"] = "new_d0069"
    return unavailable


def _require_resolved_new_archive() -> pd.DataFrame:
    return _validated_new_archive_status(
        pd.read_csv(PROCESSED / "new_pass_archive_status.csv"),
        fail_on_unresolved=True,
    )


def _geometry_population() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    existing_all = pd.read_csv(EXISTING_GEOMETRY)
    existing_all = existing_all.loc[
        existing_all["city"].isin(["atlanta", "minneapolis_st_paul"])
    ].copy()
    existing_all["window_id"] = "jun_sep"
    existing_all["source_population"] = "existing_d0047"
    included = existing_all["d0047_profile_included"].astype("string").str.casefold().eq("true")
    existing_all["archive_status"] = np.where(
        included, "ACCESSIBLE", "RESOLVED_UNAVAILABLE"
    )
    existing_candidates = existing_all.loc[included].copy()
    existing_candidates["acquisition_utc"] = pd.to_datetime(
        existing_candidates["acquisition_utc"], utc=True, errors="raise", format="mixed"
    )
    existing_links = pd.read_csv(EXISTING_LINKS)
    existing_links = existing_links.loc[
        existing_links["city"].isin(["atlanta", "minneapolis_st_paul"])
    ].copy()

    new_all = _require_resolved_new_archive()
    new_all["source_population"] = "new_d0069"
    new_candidates = new_all.loc[new_all["archive_status"].eq("ACCESSIBLE")].copy()
    new_candidates["acquisition_utc"] = pd.to_datetime(
        new_candidates["acquisition_utc"], utc=True, errors="raise", format="mixed"
    )
    _, _, new_links = _new_passes_and_targets()
    accessible_keys = new_candidates[["city", "orbit"]]
    new_links = new_links.merge(
        accessible_keys, on=["city", "orbit"], how="inner", validate="many_to_one"
    )
    candidates = pd.concat(
        [
            existing_candidates[["city", "window_id", "orbit", "acquisition_utc", "source_population"]],
            new_candidates[["city", "window_id", "orbit", "acquisition_utc", "source_population"]],
        ],
        ignore_index=True,
    )
    links = pd.concat(
        [
            existing_links[["city", "orbit", "scene", "scene_acquisition_utc"]],
            new_links[["city", "orbit", "scene", "scene_acquisition_utc"]],
        ],
        ignore_index=True,
    )
    ledger = pd.concat(
        [
            existing_all[["city", "window_id", "orbit", "acquisition_utc", "source_population", "archive_status"]],
            new_all[["city", "window_id", "orbit", "acquisition_utc", "source_population", "archive_status"]],
        ],
        ignore_index=True,
    )
    if candidates.duplicated(["city", "orbit"]).any() or len(ledger) != 762:
        raise ValueError("D0069 four-window observation ledger changed")
    return candidates, links, ledger


def _scene_sources(links: pd.DataFrame) -> dict[tuple[int, int], dict[str, Any]]:
    old = pd.read_csv(EXISTING_SCENE_MANIFEST)
    new = pd.read_csv(NEW_SCENE_MANIFEST)
    required = set(map(tuple, links[["orbit", "scene"]].astype(int).to_records(index=False)))
    rows = []
    for root_id, manifest in (("existing_d0047", old), ("new_d0069", new)):
        selected = manifest.loc[
            [
                (int(orbit), int(scene)) in required
                for orbit, scene in manifest[["orbit", "scene"]].itertuples(index=False)
            ]
        ].copy()
        selected_links = links.loc[
            [
                (int(orbit), int(scene))
                in set(map(tuple, selected[["orbit", "scene"]].astype(int).to_records(index=False)))
                for orbit, scene in links[["orbit", "scene"]].itertuples(index=False)
            ]
        ]
        _validate_geo_manifest(
            selected,
            selected_links,
            require_provider_column=(root_id == "new_d0069"),
        )
        selected["source_population"] = root_id
        rows.append(selected)
    combined = pd.concat(rows, ignore_index=True)
    combined = combined.loc[combined["status"].astype(str).eq("available")].copy()
    if combined.duplicated(["orbit", "scene"]).any():
        raise ValueError("A D0069 scene has multiple available source records")
    output = {
        (int(row.orbit), int(row.scene)): row._asdict()
        for row in combined.itertuples(index=False)
    }
    if set(output) != required:
        raise ValueError("Available D0069 scene-source census is incomplete")
    old_checkpoint = load_checkpoint(EXISTING_ASSET_CHECKPOINT)
    new_checkpoint = load_checkpoint(NEW_ASSET_CHECKPOINT)
    for source in output.values():
        granule = str(source["granule_id"])
        dmrpp, locator = _paths_for_scene(source)
        cached = (
            old_checkpoint.get(granule, {})
            if str(source["source_population"]) == "existing_d0047"
            else new_checkpoint.get(granule, {})
        )
        if str(source["source_population"]) == "new_d0069":
            valid = _metadata_asset_cache_valid(source, cached, dmrpp, locator)
        else:
            valid = bool(
                dmrpp.is_file()
                and locator.is_file()
                and cached.get("status") == "complete"
                and cached.get("decision_id") == "D0047"
                and cached.get("cmr_record_sha256") == str(source["cmr_record_sha256"])
                and cached.get("collection_concept_id") == COLLECTION_CONCEPT_ID
                and tuple(cached.get("variables", ())) == tuple(GEOMETRY_VARIABLES)
                and tuple(cached.get("locator_variables", ())) == ("latitude", "longitude")
                and cached.get("dmrpp_sha256") == sha256_file(dmrpp)
                and cached.get("locator_sha256") == sha256_file(locator)
                and int(cached.get("dmrpp_size_bytes", -1)) == dmrpp.stat().st_size
                and int(cached.get("locator_size_bytes", -1)) == locator.stat().st_size
            )
        if not valid:
            raise ValueError(f"G3 scene asset cache binding failed for {granule}")
    return output


def _paths_for_scene(record: Mapping[str, Any]) -> tuple[Path, Path]:
    root_id = str(record["source_population"])
    dmrpp_root = EXISTING_DMRPP if root_id == "existing_d0047" else NEW_DMRPP
    locator_root = EXISTING_LOCATOR if root_id == "existing_d0047" else NEW_LOCATOR
    granule = str(record["granule_id"])
    return dmrpp_root / f"{granule}.h5.dmrpp", locator_root / f"{granule}_stride32.nc4"


def _validated_raw_azimuth(values: Any) -> np.ndarray:
    """Preserve only physical ECO_L1B_GEO raw azimuth values before wrapping."""

    array = np.asarray(values, dtype=float).copy()
    array[~np.isfinite(array) | (array < -180.0) | (array > 180.0)] = np.nan
    return array


def _map_five_fields(
    selected: set[tuple[int, int]],
    decoded: Mapping[str, Mapping[tuple[int, int], np.ndarray]],
    grids: Mapping[str, Any],
    *,
    chunk_shape: tuple[int, int],
) -> dict[str, dict[str, np.ndarray]]:
    pieces: dict[str, list[np.ndarray]] = {name: [] for name in ALL_GEOMETRY_VARIABLES}
    for coord in sorted(selected):
        if any(coord not in decoded[name] for name in ALL_GEOMETRY_VARIABLES):
            raise ValueError(f"Selected chunk {coord} lacks a required geometry field")
        row_origin = coord[0] * chunk_shape[0]
        col_origin = coord[1] * chunk_shape[1]
        rows = min(chunk_shape[0], FULL_SWATH_SHAPE[0] - row_origin)
        cols = min(chunk_shape[1], FULL_SWATH_SHAPE[1] - col_origin)
        values = {
            name: np.asarray(decoded[name][coord][:rows, :cols], dtype=float)
            for name in ALL_GEOMETRY_VARIABLES
        }
        shapes = {value.shape for value in values.values()}
        if len(shapes) != 1:
            raise ValueError(f"Selected chunk {coord} has misaligned geometry fields")
        values["view_azimuth"] = _validated_raw_azimuth(values["view_azimuth"])
        values["solar_azimuth"] = _validated_raw_azimuth(values["solar_azimuth"])
        valid = (
            np.isfinite(values["latitude"])
            & np.isfinite(values["longitude"])
            & (values["latitude"] >= -90)
            & (values["latitude"] <= 90)
            & (values["longitude"] >= -180)
            & (values["longitude"] <= 180)
            & ~((values["latitude"] == 0) & (values["longitude"] == 0))
            & np.isfinite(values["view_zenith"])
            & (np.abs(values["view_zenith"]) <= 90)
        )
        if valid.any():
            for name in ALL_GEOMETRY_VARIABLES:
                pieces[name].append(values[name][valid])
    if not pieces["latitude"]:
        raise ValueError("Selected chunks contain no valid five-field geometry")
    source = {name: np.concatenate(parts) for name, parts in pieces.items()}
    output = {}
    for tile, grid in grids.items():
        transformer = Transformer.from_crs("EPSG:4326", grid.crs, always_xy=True)
        x, y = transformer.transform(source["longitude"], source["latitude"])
        xy = np.column_stack((x, y))
        finite = np.isfinite(xy).all(axis=1)
        if not finite.any():
            raise ValueError("A selected scene has no projectable source geometry")
        tree = cKDTree(xy[finite])
        distance, index = tree.query(
            np.column_stack((grid.x, grid.y)),
            k=1,
            distance_upper_bound=RADIUS_OF_INFLUENCE_M,
        )
        valid = np.isfinite(distance) & (index < int(finite.sum()))
        source_indices = np.flatnonzero(finite)[index[valid]]
        output[str(tile)] = {
            "target_index": np.flatnonzero(valid).astype(np.int32),
            "view_zenith_abs_deg": np.abs(source["view_zenith"][source_indices]).astype(np.float32),
            "view_azimuth_deg": np.mod(source["view_azimuth"][source_indices], 360.0).astype(np.float32),
            "solar_azimuth_deg": np.mod(source["solar_azimuth"][source_indices], 360.0).astype(np.float32),
            "source_distance_m": distance[valid].astype(np.float32),
        }
    return output


def _accepted_zero_mapped_scene_proof(scene: Mapping[str, Any]) -> bool:
    """Accept only an exact no-overlap or boundary-verified zero-map proof."""

    try:
        mapped_count = int(scene.get("mapped_target_cell_count", -1))
    except (TypeError, ValueError):
        return False
    if mapped_count != 0:
        return False
    status = str(scene.get("proof_status", ""))
    if status not in {
        "verified_no_domain_overlap",
        "near_domain_full_resolution_verified",
    }:
        return False
    try:
        boundary_distance = float(scene.get("boundary_minimum_domain_distance_m"))
        selected_chunks = int(scene.get("final_chunk_count", 0))
        range_requests = int(scene.get("range_request_count", 0))
    except (TypeError, ValueError):
        return False
    common = bool(
        scene.get("full_resolution_boundary_verified") is True
        and scene.get("boundary_verified") is True
        and math.isfinite(boundary_distance)
        and boundary_distance > float(BOUNDARY_GUARD_DISTANCE_M)
        and selected_chunks > 0
        and range_requests > 0
        and re.fullmatch(
            r"[0-9a-f]{64}", str(scene.get("selected_compressed_chunks_sha256", ""))
        )
        is not None
        and re.fullmatch(r"[0-9a-f]{64}", str(scene.get("range_evidence_sha256", "")))
        is not None
        and scene.get("missing_scene_substitution_used") is False
        and scene.get("missing_scene_zero_coverage_assigned") is False
        and scene.get("verified_no_overlap_zero_imputed") is False
    )
    if status == "verified_no_domain_overlap":
        return bool(
            common
            and scene.get("proof_mode") == "verified_no_overlap"
            and scene.get("proof_acceptance_status") == "verified_no_overlap_mapped_zero"
            and scene.get("verified_no_overlap_mapped_zero") is True
        )
    return bool(
        common
        and scene.get("proof_mode") == "locator_near_domain"
        and scene.get("proof_acceptance_status") == "ordinary_near_domain_mapping"
        and math.isfinite(boundary_distance)
        and boundary_distance > float(BOUNDARY_GUARD_DISTANCE_M)
    )


def _zero_mapped_scene_proof_failure(scene: Mapping[str, Any]) -> str:
    granule = str(scene.get("granule_id", "UNKNOWN_GRANULE"))
    status = str(scene.get("proof_status", ""))
    try:
        count = int(scene.get("mapped_target_cell_count", -1))
    except (TypeError, ValueError):
        count = -1
    if count != 0:
        return f"{granule}: mapped_target_cell_count={count}, expected 0"
    if status not in {
        "verified_no_domain_overlap",
        "near_domain_full_resolution_verified",
    }:
        return f"{granule}: unsupported proof_status={status!r}"
    if status == "verified_no_domain_overlap":
        return f"{granule}: exact no-overlap proof did not satisfy the sealed predicate"
    if scene.get("full_resolution_boundary_verified") is not True:
        return f"{granule}: full_resolution_boundary_verified is not true"
    if scene.get("boundary_verified") is not True:
        return f"{granule}: boundary_verified is not true"
    if scene.get("proof_mode") != "locator_near_domain":
        return f"{granule}: proof_mode is not locator_near_domain"
    if scene.get("proof_acceptance_status") != "ordinary_near_domain_mapping":
        return f"{granule}: proof_acceptance_status is not ordinary_near_domain_mapping"
    try:
        distance = float(scene.get("boundary_minimum_domain_distance_m"))
    except (TypeError, ValueError):
        distance = math.nan
    if not math.isfinite(distance) or distance <= float(BOUNDARY_GUARD_DISTANCE_M):
        return f"{granule}: boundary minimum distance does not exceed the guard"
    for field in ("final_chunk_count", "range_request_count"):
        try:
            positive = int(scene.get(field, 0)) > 0
        except (TypeError, ValueError):
            positive = False
        if not positive:
            return f"{granule}: {field} is not positive"
    for field in ("selected_compressed_chunks_sha256", "range_evidence_sha256"):
        if re.fullmatch(r"[0-9a-f]{64}", str(scene.get(field, ""))) is None:
            return f"{granule}: {field} is not a SHA-256 digest"
    for field in (
        "missing_scene_substitution_used",
        "missing_scene_zero_coverage_assigned",
        "verified_no_overlap_zero_imputed",
    ):
        if scene.get(field) is not False:
            return f"{granule}: {field} is not explicitly false"
    return f"{granule}: zero-mapped proof failed for an unclassified reason"


def _validated_no_overlap_reuse(
    candidate: Mapping[str, Any],
    document: Mapping[str, Any],
    *,
    target_grid_sha256: str,
    n_domain_pixels: int,
    expected_scene_census: set[tuple[int, int, str]] | None = None,
) -> None:
    """Validate every identity behind a D0047 verified zero-mapped proof."""

    binding = document.get("binding")
    summary = document.get("summary")
    scenes = document.get("scene_evidence")
    if not isinstance(binding, Mapping) or not isinstance(summary, Mapping) or not isinstance(scenes, list):
        raise ValueError("D0047 zero-mapped evidence is structurally incomplete")
    candidate_time = pd.Timestamp(candidate["acquisition_utc"])
    candidate_time = candidate_time.tz_localize("UTC") if candidate_time.tzinfo is None else candidate_time.tz_convert("UTC")
    source_time = pd.Timestamp(binding.get("acquisition_utc"))
    source_time = source_time.tz_localize("UTC") if source_time.tzinfo is None else source_time.tz_convert("UTC")
    if (
        document.get("status") != "complete"
        or document.get("full_resolution") is not True
        or document.get("decision_id") != "D0047"
        or document.get("collection_short_name") != COLLECTION_SHORT_NAME
        or str(document.get("collection_version", "")).zfill(3) != COLLECTION_VERSION
        or document.get("algorithm_version") != D0047_ALGORITHM_VERSION
        or tuple(document.get("variables", ())) != tuple(GEOMETRY_VARIABLES)
        or document.get("boundary_verified") is not True
        or document.get("binding_sha256") != _canonical_sha256(binding)
        or str(binding.get("city")) != str(candidate["city"])
        or binding.get("algorithm_version") != D0047_ALGORITHM_VERSION
        or int(binding.get("orbit", -1)) != int(candidate["orbit"])
        or source_time != candidate_time
        or str(binding.get("target_grid_sha256")) != target_grid_sha256
        or float(binding.get("radius_m", math.nan)) != float(RADIUS_OF_INFLUENCE_M)
        or float(binding.get("boundary_guard_m", math.nan)) != float(BOUNDARY_GUARD_DISTANCE_M)
        or str(summary.get("city")) != str(candidate["city"])
        or int(summary.get("orbit", -1)) != int(candidate["orbit"])
        or int(summary.get("n_domain_pixels", -1)) != int(n_domain_pixels)
        or int(summary.get("n_view_valid_pixels", -1)) != 0
        or float(summary.get("l1b_geometry_coverage_fraction", math.nan)) != 0.0
        or summary.get("l1b_geometry_complete") is not True
        or summary.get("geometry_definitive") is not True
        or bool(summary.get("quality_candidate_pre_cloud_geometry_only"))
        or int(summary.get("n_l1b_geo_scenes", -1)) != len(scenes)
        or not scenes
    ):
        raise ValueError("D0047 zero-mapped evidence failed its pass/grid/status binding")
    rejected = [
        _zero_mapped_scene_proof_failure(item)
        for item in scenes
        if not _accepted_zero_mapped_scene_proof(item)
    ]
    if rejected:
        raise ValueError("D0047 zero-mapped scene proof rejected: " + "; ".join(rejected))
    scene_bindings = binding.get("scene_bindings", [])
    if not isinstance(scene_bindings, list) or len(scene_bindings) != len(scenes):
        raise ValueError("D0047 zero-mapped scene binding census is incomplete")
    observed_scene_census = {
        (int(source.get("orbit", -1)), int(source.get("scene", -1)), str(source.get("granule_id", "")))
        for source in scene_bindings
    }
    if (
        len(observed_scene_census) != len(scene_bindings)
        or expected_scene_census is not None
        and observed_scene_census != expected_scene_census
    ):
        raise ValueError("D0047 zero-mapped scene census differs from frozen pass links")
    evidence_by_granule = {str(item.get("granule_id")): item for item in scenes}
    for source in scene_bindings:
        granule = str(source.get("granule_id"))
        evidence = evidence_by_granule.get(granule)
        dmrpp = EXISTING_DMRPP / f"{granule}.h5.dmrpp"
        locator = EXISTING_LOCATOR / f"{granule}_stride32.nc4"
        if (
            evidence is None
            or source.get("collection_concept_id") != COLLECTION_CONCEPT_ID
            or source.get("cmr_record_sha256") != evidence.get("cmr_record_sha256")
            or source.get("dmrpp_sha256") != evidence.get("dmrpp_sha256")
            or source.get("locator_sha256") != evidence.get("locator_sha256")
            or not dmrpp.is_file()
            or not locator.is_file()
            or source.get("dmrpp_sha256") != sha256_file(dmrpp)
            or source.get("locator_sha256") != sha256_file(locator)
            or int(source.get("dmrpp_size_bytes", -1)) != dmrpp.stat().st_size
            or int(source.get("locator_size_bytes", -1)) != locator.stat().st_size
        ):
            raise ValueError(f"D0047 zero-mapped source binding failed for {granule}")


def _no_overlap_reuse(
    candidate: Mapping[str, Any],
    *,
    target_grid_sha256: str,
    n_domain_pixels: int,
    expected_scene_census: set[tuple[int, int, str]],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    if str(candidate["source_population"]) != "existing_d0047":
        return None
    path = EXISTING_PASS_EVIDENCE / str(candidate["city"]) / f"{int(candidate['orbit']):05d}.json"
    if not path.is_file():
        return None
    document = json.loads(path.read_text(encoding="utf-8"))
    if int(document.get("summary", {}).get("n_view_valid_pixels", -1)) != 0:
        return None
    _validated_no_overlap_reuse(
        candidate,
        document,
        target_grid_sha256=target_grid_sha256,
        n_domain_pixels=n_domain_pixels,
        expected_scene_census=expected_scene_census,
    )
    summary = document.get("summary", {})
    scenes = document.get("scene_evidence", [])
    output = {
        "city": str(candidate["city"]),
        "window_id": str(candidate["window_id"]),
        "orbit": int(candidate["orbit"]),
        "acquisition_utc": pd.Timestamp(candidate["acquisition_utc"]).isoformat(),
        "year": int(pd.Timestamp(candidate["acquisition_utc"]).year),
        "source_population": str(candidate["source_population"]),
        "n_l1b_geo_scenes": int(summary["n_l1b_geo_scenes"]),
        "n_domain_pixels": int(summary["n_domain_pixels"]),
        "n_view_valid_pixels": 0,
        "l1b_geometry_coverage_fraction": 0.0,
        "l1b_view_zenith_abs_min_deg": math.nan,
        "l1b_view_zenith_abs_median_deg": math.nan,
        "l1b_view_zenith_abs_mean_deg": math.nan,
        "l1b_view_zenith_abs_p95_deg": math.nan,
        "l1b_view_zenith_abs_max_deg": math.nan,
        "view_azimuth_circular_mean_deg": math.nan,
        "view_azimuth_circular_concentration": math.nan,
        "solar_azimuth_circular_mean_deg": math.nan,
        "solar_azimuth_circular_concentration": math.nan,
        "relative_azimuth_median_deg": math.nan,
        "relative_azimuth_q1_deg": math.nan,
        "relative_azimuth_q3_deg": math.nan,
        "relative_azimuth_iqr_deg": math.nan,
        "azimuth_valid_fraction_of_view_cells": math.nan,
        "geometry_azimuth_complete": True,
        "geometry_azimuth_status": "RESOLVED_VERIFIED_ZERO_MAPPED_CELLS",
        "source_geometry_evidence_sha256": sha256_file(path),
        "decision_id": DECISION_ID,
        "temperature_or_lst_opened": False,
        "record_2026_opened": False,
    }
    evidence = {
        "status": "complete",
        "reuse_rule": "checksum-verified D0047 full-resolution zero-mapped scene proof",
        "source_path": str(path),
        "source_sha256": sha256_file(path),
        "summary": output,
    }
    return output, evidence


def _reconstruction_path(city: str, orbit: int) -> Path:
    return GEOMETRY_RECONSTRUCTION / str(city) / f"{int(orbit):05d}.npz"


def _geometry_reconstruction_storage_preflight(
    city_domain_cells: Mapping[str, int],
    candidate_cities: Iterable[Any],
    *,
    completed_candidate_cities: Iterable[Any] = (),
    completed_validation_digests: Mapping[str, str] | None = None,
    storage_root: Path = GEOMETRY_RECONSTRUCTION,
    reserve_bytes: int = GEOMETRY_RECONSTRUCTION_RESERVE_BYTES,
    evidence_path: Path | None = GEOMETRY_RECONSTRUCTION_PREFLIGHT,
    disk_usage: Any = shutil.disk_usage,
) -> dict[str, Any]:
    """Guard uncompressed sparse-array worst case plus container overhead and reserve."""

    cities = [str(city) for city in candidate_cities]
    completed_cities = [str(city) for city in completed_candidate_cities]
    validation_digests = dict(completed_validation_digests or {})
    missing = sorted(set(cities).difference(city_domain_cells))
    if missing:
        raise ValueError(f"Geometry reconstruction estimate lacks city cells: {missing}")
    if len(completed_cities) != len(validation_digests):
        raise ValueError("Geometry resume credits lack one validation digest per completed pass")
    full_counts = pd.Series(cities, dtype="string").value_counts().to_dict()
    completed_counts = pd.Series(completed_cities, dtype="string").value_counts().to_dict()
    if any(completed_counts.get(city, 0) > full_counts.get(city, 0) for city in completed_counts):
        raise ValueError("Geometry resume credits escape the full candidate city census")
    if any(
        re.fullmatch(r"[0-9a-f]{64}", str(digest)) is None
        for digest in validation_digests.values()
    ):
        raise ValueError("Geometry resume credit has a malformed validation digest")
    remaining_cities = list(cities)
    for city in completed_cities:
        remaining_cities.remove(city)
    # uint32 target index + three float32 geometry values = 16 bytes/cell.
    raw_array_bytes = int(sum(int(city_domain_cells[city]) * 16 for city in cities))
    container_overhead = len(cities) * GEOMETRY_RECONSTRUCTION_CONTAINER_OVERHEAD_BYTES_PER_PASS
    conservative = raw_array_bytes + container_overhead
    completed_raw = int(
        sum(int(city_domain_cells[city]) * 16 for city in completed_cities)
    )
    completed_overhead = (
        len(completed_cities) * GEOMETRY_RECONSTRUCTION_CONTAINER_OVERHEAD_BYTES_PER_PASS
    )
    completed_conservative = completed_raw + completed_overhead
    remaining_raw = int(
        sum(int(city_domain_cells[city]) * 16 for city in remaining_cities)
    )
    remaining_overhead = (
        len(remaining_cities) * GEOMETRY_RECONSTRUCTION_CONTAINER_OVERHEAD_BYTES_PER_PASS
    )
    remaining_conservative = remaining_raw + remaining_overhead
    if (
        completed_raw + remaining_raw != raw_array_bytes
        or completed_overhead + remaining_overhead != container_overhead
        or completed_conservative + remaining_conservative != conservative
    ):
        raise ValueError("Geometry resume storage partition does not reconcile")
    # The 8 GiB ceiling governs the reconstruction arrays/artifacts themselves.
    # Per-pass container overhead is still included in the live-space preflight,
    # but must not make an otherwise compliant raw-array estimate fail the
    # artifact ceiling before compression is attempted.
    if raw_array_bytes > GEOMETRY_RECONSTRUCTION_MAX_BYTES:
        raise RuntimeError(
            "D0069 geometry reconstruction raw-array estimate exceeds the absolute 8 GiB guard: "
            f"{raw_array_bytes}"
        )
    storage_root.mkdir(parents=True, exist_ok=True)
    try:
        free = int(disk_usage(storage_root).free)
    except Exception:
        raise RuntimeError(
            "D0069 could not measure live free space; geometry reconstruction is locked"
        ) from None
    required = remaining_conservative + int(reserve_bytes)
    payload = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "decision_id": DECISION_ID,
        "format_version": GEOMETRY_RECONSTRUCTION_FORMAT,
        "candidate_passes": len(cities),
        "bytes_per_fully_valid_domain_cell": 16,
        "raw_array_worst_case_bytes": raw_array_bytes,
        "container_overhead_bytes_per_pass": GEOMETRY_RECONSTRUCTION_CONTAINER_OVERHEAD_BYTES_PER_PASS,
        "container_overhead_bytes": container_overhead,
        "conservative_new_data_bytes": conservative,
        "completed_passes": len(completed_cities),
        "completed_raw_array_worst_case_bytes": completed_raw,
        "completed_container_overhead_bytes": completed_overhead,
        "completed_conservative_bytes": completed_conservative,
        "remaining_passes": len(remaining_cities),
        "remaining_raw_array_worst_case_bytes": remaining_raw,
        "remaining_container_overhead_bytes": remaining_overhead,
        "remaining_conservative_new_data_bytes": remaining_conservative,
        "credited_completed_item_ids": sorted(validation_digests),
        "credited_completed_validation_sha256_by_item_id": {
            item_id: validation_digests[item_id] for item_id in sorted(validation_digests)
        },
        "absolute_maximum_bytes": GEOMETRY_RECONSTRUCTION_MAX_BYTES,
        "explicit_reserve_bytes": int(reserve_bytes),
        "required_free_bytes": required,
        "observed_free_bytes": free,
        "status": "PASS" if free >= required else "FAIL_INSUFFICIENT_FREE_SPACE",
    }
    if evidence_path is not None:
        _atomic_json(payload, evidence_path)
    if free < required:
        raise RuntimeError(
            "D0069 geometry reconstruction live storage preflight failed: "
            f"free={free}, remaining_estimate={remaining_conservative}, "
            f"reserve={reserve_bytes}, required={required}"
        )
    return payload


def _write_geometry_reconstruction(
    path: Path,
    *,
    city: str,
    window_id: str,
    orbit: int,
    target_grid_sha256: str,
    grids: Mapping[str, Any],
    combined: Mapping[str, Mapping[str, np.ndarray]] | None,
) -> dict[str, Any]:
    """Persist sparse mapped-domain cells needed for independent G6 replay."""

    tiles = sorted(grids)
    sizes = np.asarray([grids[tile].size for tile in tiles], dtype=np.int64)
    offsets = np.concatenate(([0], np.cumsum(sizes[:-1], dtype=np.int64)))
    n_domain = int(sizes.sum())
    if combined is None:
        global_index = np.asarray([], dtype=np.int32)
        view = np.asarray([], dtype=np.float32)
        view_azimuth = np.asarray([], dtype=np.float32)
        solar_azimuth = np.asarray([], dtype=np.float32)
    else:
        indices: list[np.ndarray] = []
        view_parts: list[np.ndarray] = []
        view_azimuth_parts: list[np.ndarray] = []
        solar_azimuth_parts: list[np.ndarray] = []
        for tile, offset in zip(tiles, offsets, strict=True):
            tile_view = np.asarray(combined[tile]["view"], dtype=np.float32)
            valid = np.flatnonzero(np.isfinite(tile_view)).astype(np.int64)
            indices.append((valid + offset).astype(np.int32))
            view_parts.append(tile_view[valid])
            view_azimuth_parts.append(
                np.asarray(combined[tile]["view_azimuth"], dtype=np.float32)[valid]
            )
            solar_azimuth_parts.append(
                np.asarray(combined[tile]["solar_azimuth"], dtype=np.float32)[valid]
            )
        global_index = np.concatenate(indices) if indices else np.asarray([], dtype=np.int32)
        view = np.concatenate(view_parts) if view_parts else np.asarray([], dtype=np.float32)
        view_azimuth = (
            np.concatenate(view_azimuth_parts)
            if view_azimuth_parts
            else np.asarray([], dtype=np.float32)
        )
        solar_azimuth = (
            np.concatenate(solar_azimuth_parts)
            if solar_azimuth_parts
            else np.asarray([], dtype=np.float32)
        )
    if len(global_index) and (
        np.any(global_index < 0)
        or np.any(global_index >= n_domain)
        or len(np.unique(global_index)) != len(global_index)
    ):
        raise ValueError("Mapped geometry reconstruction indices are invalid")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.stem}.tmp.npz")
    with temporary.open("wb") as handle:
        np.savez_compressed(
            handle,
            format_version=np.asarray(GEOMETRY_RECONSTRUCTION_FORMAT),
            city=np.asarray(str(city)),
            window_id=np.asarray(str(window_id)),
            orbit=np.asarray(int(orbit), dtype=np.int64),
            target_grid_sha256=np.asarray(str(target_grid_sha256)),
            tile_names=np.asarray(tiles),
            tile_offsets=offsets,
            tile_sizes=sizes,
            n_domain_pixels=np.asarray(n_domain, dtype=np.int64),
            valid_target_index=global_index,
            view_zenith_abs_deg=view,
            view_azimuth_deg=view_azimuth,
            solar_azimuth_deg=solar_azimuth,
        )
    temporary.replace(path)
    if path.stat().st_size > GEOMETRY_RECONSTRUCTION_MAX_BYTES:
        raise RuntimeError("A geometry reconstruction artifact exceeded the global byte guard")
    return {
        "format_version": GEOMETRY_RECONSTRUCTION_FORMAT,
        "path": str(path),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
        "n_domain_pixels": n_domain,
        "n_valid_target_cells": int(len(global_index)),
        "target_grid_sha256": target_grid_sha256,
    }


def _reconstruction_cache_valid(
    document: Mapping[str, Any],
    *,
    expected_city: str | None = None,
    expected_window_id: str | None = None,
    expected_orbit: int | None = None,
    expected_target_grid_sha256: str | None = None,
    expected_n_domain_pixels: int | None = None,
    expected_path: Path | None = None,
) -> bool:
    record = document.get("reconstruction_artifact", {})
    path = Path(str(record.get("path", "")))
    if not (
        record.get("format_version") == GEOMETRY_RECONSTRUCTION_FORMAT
        and path.is_file()
        and record.get("sha256") == sha256_file(path)
        and int(record.get("size_bytes", -1)) == path.stat().st_size
        and (expected_path is None or path == expected_path)
        and (
            expected_target_grid_sha256 is None
            or str(record.get("target_grid_sha256")) == expected_target_grid_sha256
        )
        and (
            expected_n_domain_pixels is None
            or int(record.get("n_domain_pixels", -1)) == expected_n_domain_pixels
        )
    ):
        return False
    try:
        with np.load(path, allow_pickle=False) as mapped:
            required = {
                "format_version", "city", "window_id", "orbit", "target_grid_sha256",
                "n_domain_pixels", "valid_target_index", "view_zenith_abs_deg",
                "view_azimuth_deg", "solar_azimuth_deg",
            }
            if required.difference(mapped.files):
                return False
            indices = mapped["valid_target_index"]
            values = (
                mapped["view_zenith_abs_deg"], mapped["view_azimuth_deg"],
                mapped["solar_azimuth_deg"],
            )
            return bool(
                str(mapped["format_version"]) == GEOMETRY_RECONSTRUCTION_FORMAT
                and (expected_city is None or str(mapped["city"]) == expected_city)
                and (
                    expected_window_id is None
                    or str(mapped["window_id"]) == expected_window_id
                )
                and (expected_orbit is None or int(mapped["orbit"]) == expected_orbit)
                and (
                    expected_target_grid_sha256 is None
                    or str(mapped["target_grid_sha256"])
                    == expected_target_grid_sha256
                )
                and (
                    expected_n_domain_pixels is None
                    or int(mapped["n_domain_pixels"]) == expected_n_domain_pixels
                )
                and len(indices) == int(record.get("n_valid_target_cells", -1))
                and all(len(value) == len(indices) for value in values)
                and len(np.unique(indices)) == len(indices)
                and (
                    not len(indices)
                    or (
                        int(indices.min()) >= 0
                        and int(indices.max()) < int(mapped["n_domain_pixels"])
                    )
                )
            )
    except (OSError, ValueError, KeyError):
        return False


def _validated_pass_cache(
    cached: Mapping[str, Any],
    evidence_path: Path,
    binding_payload: Mapping[str, Any],
    *,
    expected_window_id: str | None = None,
    expected_n_domain_pixels: int | None = None,
    expected_reconstruction_path: Path | None = None,
) -> dict[str, Any] | None:
    binding_sha256 = _canonical_sha256(binding_payload)
    if not evidence_path.is_file() or not (
        cached.get("status") == "complete"
        and cached.get("binding_sha256") == binding_sha256
        and cached.get("evidence_path") == str(evidence_path)
        and cached.get("evidence_sha256") == sha256_file(evidence_path)
    ):
        return None
    try:
        document = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not (
        document.get("status") == "complete"
        and document.get("binding") == binding_payload
        and document.get("binding_sha256") == binding_sha256
        and isinstance(document.get("scene_evidence"), list)
        and isinstance(document.get("summary"), Mapping)
        and _reconstruction_cache_valid(
            document,
            expected_city=str(binding_payload["city"]),
            expected_window_id=expected_window_id,
            expected_orbit=int(binding_payload["orbit"]),
            expected_target_grid_sha256=str(binding_payload["target_grid_sha256"]),
            expected_n_domain_pixels=expected_n_domain_pixels,
            expected_path=expected_reconstruction_path,
        )
    ):
        return None
    summary = dict(document["summary"])
    if (
        str(summary.get("city")) != str(binding_payload["city"])
        or int(summary.get("orbit", -1)) != int(binding_payload["orbit"])
        or str(summary.get("decision_id")) != DECISION_ID
        or (
            expected_window_id is not None
            and str(summary.get("window_id")) != expected_window_id
        )
        or (
            expected_n_domain_pixels is not None
            and int(summary.get("n_domain_pixels", -1)) != expected_n_domain_pixels
        )
        or int(summary.get("n_view_valid_pixels", -1))
        != int(document["reconstruction_artifact"].get("n_valid_target_cells", -2))
        or summary.get("geometry_reconstruction_artifact_sha256")
        != document["reconstruction_artifact"].get("sha256")
        or int(summary.get("geometry_reconstruction_artifact_size_bytes", -1))
        != int(document["reconstruction_artifact"].get("size_bytes", -2))
    ):
        return None
    if (
        int(summary.get("n_view_valid_pixels", -1)) == 0
        and str(summary.get("source_population")) == "new_d0069"
        and not (
            document.get("zero_map_proof_schema_version")
            == ZERO_MAP_PROOF_SCHEMA_VERSION
            and summary.get("geometry_azimuth_status")
            == "RESOLVED_VERIFIED_ZERO_MAPPED_CELLS"
            and summary.get("geometry_azimuth_complete") is True
            and bool(document["scene_evidence"])
            and all(
                _accepted_zero_mapped_scene_proof(scene)
                for scene in document["scene_evidence"]
            )
        )
    ):
        return None
    return summary


def _geometry_binding_payload(
    candidate: Mapping[str, Any],
    link_groups: Mapping[tuple[str, int], pd.DataFrame],
    sources: Mapping[tuple[int, int], Mapping[str, Any]],
    fingerprints: Mapping[str, str],
) -> dict[str, Any]:
    """Build the one current binding used by both worker cache and resume credit."""

    city, orbit = str(candidate["city"]), int(candidate["orbit"])
    scene_bindings = []
    for link in link_groups[(city, orbit)].itertuples(index=False):
        source = sources[(orbit, int(link.scene))]
        dmrpp, locator = _paths_for_scene(source)
        if not dmrpp.is_file() or not locator.is_file():
            raise RuntimeError(f"Missing sealed scene metadata assets: {source['granule_id']}")
        scene_bindings.append(
            {
                "orbit": orbit,
                "scene": int(link.scene),
                "granule_id": str(source["granule_id"]),
                "cmr_record_sha256": str(source["cmr_record_sha256"]),
                "collection_concept_id": str(source["collection_concept_id"]),
                "concept_id": str(source["concept_id"]),
                "hdf_url": str(source["hdf_url"]),
                "dmrpp_url": str(source["dmrpp_url"]),
                "opendap_url": str(source["opendap_url"]),
                "dmrpp_sha256": sha256_file(dmrpp),
                "locator_sha256": sha256_file(locator),
                "dmrpp_size_bytes": dmrpp.stat().st_size,
                "locator_size_bytes": locator.stat().st_size,
            }
        )
    return {
        "algorithm_version": ALGORITHM_VERSION,
        "decision_id": DECISION_ID,
        "city": city,
        "orbit": orbit,
        "acquisition_utc": pd.Timestamp(candidate["acquisition_utc"]).isoformat(),
        "target_grid_sha256": fingerprints[city],
        "variables": list(ALL_GEOMETRY_VARIABLES),
        "radius_m": RADIUS_OF_INFLUENCE_M,
        "boundary_guard_m": BOUNDARY_GUARD_DISTANCE_M,
        "scene_bindings": scene_bindings,
    }


def _geometry_resume_validation_payload(
    item_id: str,
    cached: Mapping[str, Any],
    evidence_path: Path,
    document: Mapping[str, Any],
) -> dict[str, Any]:
    reconstruction = document["reconstruction_artifact"]
    reconstruction_path = Path(str(reconstruction["path"]))
    return {
        "item_id": item_id,
        "checkpoint_status": str(cached.get("status")),
        "binding_sha256": str(cached.get("binding_sha256")),
        "evidence_path": str(evidence_path),
        "evidence_sha256": sha256_file(evidence_path),
        "reconstruction_path": str(reconstruction_path),
        "reconstruction_sha256": sha256_file(reconstruction_path),
        "reconstruction_size_bytes": reconstruction_path.stat().st_size,
        "format_version": str(reconstruction["format_version"]),
        "city": str(document["binding"]["city"]),
        "window_id": str(document["summary"]["window_id"]),
        "orbit": int(document["binding"]["orbit"]),
        "target_grid_sha256": str(reconstruction["target_grid_sha256"]),
        "n_domain_pixels": int(reconstruction["n_domain_pixels"]),
        "n_valid_target_cells": int(reconstruction["n_valid_target_cells"]),
    }


def _enforce_credited_cache_at_use(
    item_id: str,
    expected_digest: str | None,
    cached_summary: Mapping[str, Any] | None,
    cached: Mapping[str, Any],
    evidence_path: Path,
) -> None:
    """Stop if a credited cache changes after storage preflight."""

    if expected_digest is None:
        return
    if cached_summary is None or not evidence_path.is_file():
        raise RuntimeError(
            f"Credited geometry cache changed after storage preflight: {item_id}; rerun preflight"
        )
    try:
        document = json.loads(evidence_path.read_text(encoding="utf-8"))
        reconstruction = document["reconstruction_artifact"]
        reconstruction_path = Path(str(reconstruction["path"]))
        if not _reconstruction_cache_valid(
            document,
            expected_city=str(document["binding"]["city"]),
            expected_window_id=str(document["summary"]["window_id"]),
            expected_orbit=int(document["binding"]["orbit"]),
            expected_target_grid_sha256=str(reconstruction["target_grid_sha256"]),
            expected_n_domain_pixels=int(reconstruction["n_domain_pixels"]),
            expected_path=reconstruction_path,
        ):
            raise ValueError("current reconstruction no longer validates")
        current = _canonical_sha256(
            _geometry_resume_validation_payload(item_id, cached, evidence_path, document)
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        current = "INVALID"
    if current != expected_digest:
        raise RuntimeError(
            f"Credited geometry cache changed after storage preflight: {item_id}; rerun preflight"
        )


def _validated_geometry_resume_credits(
    candidates: pd.DataFrame,
    checkpoint: Mapping[str, Mapping[str, Any]],
    link_groups: Mapping[tuple[str, int], pd.DataFrame],
    sources: Mapping[tuple[int, int], Mapping[str, Any]],
    fingerprints: Mapping[str, str],
    city_domain_cells: Mapping[str, int],
) -> tuple[list[str], dict[str, str]]:
    """Credit only ordinary artifacts the current worker will return unchanged."""

    completed_cities: list[str] = []
    digests: dict[str, str] = {}
    for candidate in candidates.to_dict("records"):
        city, orbit = str(candidate["city"]), int(candidate["orbit"])
        item_id = f"{city}:{orbit:05d}"
        cached = checkpoint.get(item_id, {})
        # Zero-mapped reuse is evaluated before the ordinary cache and currently
        # rewrites its reconstruction, so an existing zero NPZ receives no credit.
        old_path = EXISTING_PASS_EVIDENCE / city / f"{orbit:05d}.json"
        if str(candidate.get("source_population")) == "existing_d0047" and old_path.is_file():
            try:
                if int(json.loads(old_path.read_text(encoding="utf-8")).get(
                    "summary", {}
                ).get("n_view_valid_pixels", -1)) == 0:
                    continue
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                continue
        binding = _geometry_binding_payload(candidate, link_groups, sources, fingerprints)
        evidence_path = PASS_EVIDENCE / city / f"{orbit:05d}.json"
        summary = _validated_pass_cache(
            cached,
            evidence_path,
            binding,
            expected_window_id=str(candidate["window_id"]),
            expected_n_domain_pixels=int(city_domain_cells[city]),
            expected_reconstruction_path=_reconstruction_path(city, orbit),
        )
        if summary is None:
            continue
        document = json.loads(evidence_path.read_text(encoding="utf-8"))
        completed_cities.append(city)
        digests[item_id] = _canonical_sha256(
            _geometry_resume_validation_payload(item_id, cached, evidence_path, document)
        )
    return completed_cities, digests


def _validate_geometry_resume_preflight_payload(
    preflight: Mapping[str, Any],
    candidates: pd.DataFrame,
    checkpoint: Mapping[str, Mapping[str, Any]],
    link_groups: Mapping[tuple[str, int], pd.DataFrame],
    sources: Mapping[tuple[int, int], Mapping[str, Any]],
    fingerprints: Mapping[str, str],
    city_domain_cells: Mapping[str, int],
) -> dict[str, Any]:
    """Recompute the sealed full/resume partition and every credited digest."""

    all_cities = candidates["city"].astype(str).tolist()
    candidate_by_id = {
        f"{row.city}:{int(row.orbit):05d}": row
        for row in candidates.itertuples(index=False)
    }
    credited = [str(value) for value in preflight.get("credited_completed_item_ids", [])]
    sealed_digests = preflight.get("credited_completed_validation_sha256_by_item_id", {})
    if (
        len(credited) != len(set(credited))
        or set(credited) != set(sealed_digests)
        or not set(credited).issubset(candidate_by_id)
    ):
        raise ValueError("Geometry resume preflight credited identity census is invalid")
    valid_cities, current_digests = _validated_geometry_resume_credits(
        candidates,
        checkpoint,
        link_groups,
        sources,
        fingerprints,
        city_domain_cells,
    )
    del valid_cities
    if any(current_digests.get(item_id) != sealed_digests[item_id] for item_id in credited):
        raise ValueError("Geometry resume preflight credited artifact validation changed")
    completed_cities = [str(candidate_by_id[item_id].city) for item_id in credited]
    remaining_cities = list(all_cities)
    for city in completed_cities:
        remaining_cities.remove(city)
    overhead_per_pass = GEOMETRY_RECONSTRUCTION_CONTAINER_OVERHEAD_BYTES_PER_PASS
    full_raw = int(sum(city_domain_cells[city] * 16 for city in all_cities))
    full_overhead = len(all_cities) * overhead_per_pass
    completed_raw = int(sum(city_domain_cells[city] * 16 for city in completed_cities))
    completed_overhead = len(completed_cities) * overhead_per_pass
    remaining_raw = int(sum(city_domain_cells[city] * 16 for city in remaining_cities))
    remaining_overhead = len(remaining_cities) * overhead_per_pass
    expected = {
        "candidate_passes": len(all_cities),
        "raw_array_worst_case_bytes": full_raw,
        "container_overhead_bytes": full_overhead,
        "conservative_new_data_bytes": full_raw + full_overhead,
        "completed_passes": len(completed_cities),
        "completed_raw_array_worst_case_bytes": completed_raw,
        "completed_container_overhead_bytes": completed_overhead,
        "completed_conservative_bytes": completed_raw + completed_overhead,
        "remaining_passes": len(remaining_cities),
        "remaining_raw_array_worst_case_bytes": remaining_raw,
        "remaining_container_overhead_bytes": remaining_overhead,
        "remaining_conservative_new_data_bytes": remaining_raw + remaining_overhead,
    }
    if any(int(preflight.get(key, -1)) != value for key, value in expected.items()):
        raise ValueError("Geometry resume preflight full/completed/remaining totals changed")
    if (
        preflight.get("status") != "PASS"
        or preflight.get("format_version") != GEOMETRY_RECONSTRUCTION_FORMAT
        or int(preflight.get("absolute_maximum_bytes", -1))
        != GEOMETRY_RECONSTRUCTION_MAX_BYTES
        or full_raw > GEOMETRY_RECONSTRUCTION_MAX_BYTES
        or int(preflight.get("required_free_bytes", -1))
        != expected["remaining_conservative_new_data_bytes"]
        + int(preflight.get("explicit_reserve_bytes", -2))
        or int(preflight.get("observed_free_bytes", -1))
        < int(preflight.get("required_free_bytes", 0))
    ):
        raise ValueError("Geometry resume preflight guard or reserve binding failed")
    return expected


def run_geometry(workers: int) -> None:
    _require_resolved_new_archive()
    _, geometries = _domains()
    grids = _target_grids(geometries)
    candidates, links, ledger = _geometry_population()
    sources = _scene_sources(links)
    link_groups = {
        (str(city), int(orbit)): group.sort_values("scene")
        for (city, orbit), group in links.groupby(["city", "orbit"], sort=True)
    }
    fingerprints = {
        city: legacy_geometry._target_grid_fingerprint(city_grids)
        for city, city_grids in grids.items()
    }
    city_domain_cells = {
        city: int(sum(grid.size for grid in city_grids.values()))
        for city, city_grids in grids.items()
    }
    checkpoint = load_checkpoint(PASS_CHECKPOINT)
    completed_cities, completion_digests = _validated_geometry_resume_credits(
        candidates,
        checkpoint,
        link_groups,
        sources,
        fingerprints,
        city_domain_cells,
    )
    _geometry_reconstruction_storage_preflight(
        city_domain_cells,
        candidates["city"],
        completed_candidate_cities=completed_cities,
        completed_validation_digests=completion_digests,
    )
    earthaccess, _ = legacy_geometry._earthaccess()
    local = threading.local()

    def worker(candidate: Mapping[str, Any]) -> tuple[str, dict[str, Any], dict[str, Any]]:
        item_id = f"{candidate['city']}:{int(candidate['orbit']):05d}"
        candidate_city = str(candidate["city"])
        candidate_orbit = int(candidate["orbit"])
        expected_completion_digest = completion_digests.get(item_id)
        # A pass credited by the live-space preflight may only take the exact
        # ordinary-cache no-write path.  It must return or fail before any
        # zero-map reuse or reconstruction branch can write an artifact.
        if expected_completion_digest is not None:
            credited_binding_payload = _geometry_binding_payload(
                candidate, link_groups, sources, fingerprints
            )
            credited_cached = checkpoint.get(item_id, {})
            credited_evidence_path = (
                PASS_EVIDENCE / candidate_city / f"{candidate_orbit:05d}.json"
            )
            credited_summary = _validated_pass_cache(
                credited_cached,
                credited_evidence_path,
                credited_binding_payload,
                expected_window_id=str(candidate["window_id"]),
                expected_n_domain_pixels=city_domain_cells[candidate_city],
                expected_reconstruction_path=_reconstruction_path(
                    candidate_city, candidate_orbit
                ),
            )
            _enforce_credited_cache_at_use(
                item_id,
                expected_completion_digest,
                credited_summary,
                credited_cached,
                credited_evidence_path,
            )
            return item_id, dict(credited_cached), dict(credited_summary)
        expected_zero_scene_census = {
            (
                candidate_orbit,
                int(link.scene),
                str(sources[(candidate_orbit, int(link.scene))]["granule_id"]),
            )
            for link in link_groups[(candidate_city, candidate_orbit)].itertuples(index=False)
        }
        reused = _no_overlap_reuse(
            candidate,
            target_grid_sha256=fingerprints[candidate_city],
            n_domain_pixels=sum(grid.size for grid in grids[candidate_city].values()),
            expected_scene_census=expected_zero_scene_census,
        )
        if reused is not None:
            summary, evidence = reused
            reconstruction = _write_geometry_reconstruction(
                _reconstruction_path(candidate_city, int(candidate["orbit"])),
                city=candidate_city,
                window_id=str(candidate["window_id"]),
                orbit=int(candidate["orbit"]),
                target_grid_sha256=fingerprints[candidate_city],
                grids=grids[candidate_city],
                combined=None,
            )
            evidence["reconstruction_artifact"] = reconstruction
            summary["geometry_reconstruction_artifact_sha256"] = reconstruction["sha256"]
            summary["geometry_reconstruction_artifact_size_bytes"] = reconstruction["size_bytes"]
            summary["geometry_reconstruction_evidence_complete"] = True
            binding = hashlib.sha256(
                json.dumps(evidence, sort_keys=True, default=str).encode()
            ).hexdigest()
            evidence["binding_sha256"] = binding
            return item_id, evidence, summary
        city, orbit = str(candidate["city"]), int(candidate["orbit"])
        pass_links = link_groups[(city, orbit)]
        binding_payload = _geometry_binding_payload(
            candidate, link_groups, sources, fingerprints
        )
        binding = _canonical_sha256(binding_payload)
        cached = checkpoint.get(item_id, {})
        evidence_path = PASS_EVIDENCE / city / f"{orbit:05d}.json"
        cached_summary = _validated_pass_cache(
            cached,
            evidence_path,
            binding_payload,
            expected_window_id=str(candidate["window_id"]),
            expected_n_domain_pixels=city_domain_cells[city],
            expected_reconstruction_path=_reconstruction_path(city, orbit),
        )
        _enforce_credited_cache_at_use(
            item_id,
            None,
            cached_summary,
            cached,
            evidence_path,
        )
        if cached_summary is not None:
            return item_id, dict(cached), cached_summary
        if not hasattr(local, "session"):
            local.session = earthaccess.get_requests_https_session()

        combined = {
            tile: {
                "view": np.full(grid.size, np.nan, dtype=np.float32),
                "view_azimuth": np.full(grid.size, np.nan, dtype=np.float32),
                "solar_azimuth": np.full(grid.size, np.nan, dtype=np.float32),
            }
            for tile, grid in grids[city].items()
        }
        scene_evidence = []
        overlaps = 0
        for link in pass_links.itertuples(index=False):
            source = sources[(orbit, int(link.scene))]
            granule = str(source["granule_id"])
            dmrpp, locator = _paths_for_scene(source)
            descriptors = parse_dmrpp_chunks_for_variables(dmrpp, ALL_GEOMETRY_VARIABLES)
            chunk_shape = next(iter(descriptors["latitude"].values())).chunk_shape
            locator_lat, locator_lon = legacy_geometry._read_locator(locator)
            selected, proof = initial_chunk_selection_with_proof(
                locator_lat, locator_lon, grids[city], chunk_shape=chunk_shape
            )
            initial = set(selected)

            def refresh_session() -> Any:
                local.session = earthaccess.get_requests_https_session()
                return local.session

            fetcher = legacy_geometry._RangeFetcher(
                local.session,
                str(source["hdf_url"]),
                granule,
                max_total_bytes=MAX_RANGE_BYTES_PER_SCENE,
                refresh_session=refresh_session,
            )
            decoded = {name: {} for name in ALL_GEOMETRY_VARIABLES}
            chunk_hashes: dict[str, str] = {}
            iterations = 0
            while True:
                decoded, chunk_hashes, _ = decode_selected_chunks(
                    descriptors,
                    selected,
                    ("latitude", "longitude"),
                    fetch_range=fetcher,
                    decoded=decoded,
                    chunk_hashes=chunk_hashes,
                )
                additions, minimum, edges = boundary_expansion_neighbors(
                    selected,
                    decoded["latitude"],
                    decoded["longitude"],
                    grids[city],
                    chunk_shape=chunk_shape,
                )
                iterations += 1
                if not additions:
                    break
                selected.update(additions)
                if len(selected) > MAX_SELECTED_CHUNKS_PER_SCENE or iterations >= 64:
                    raise RuntimeError(f"Geometry chunk expansion guard exceeded for {granule}")
            decoded, chunk_hashes, _ = decode_selected_chunks(
                descriptors,
                selected,
                ("view_zenith", "view_azimuth", "solar_azimuth"),
                fetch_range=fetcher,
                decoded=decoded,
                chunk_hashes=chunk_hashes,
            )
            mapped = _map_five_fields(selected, decoded, grids[city], chunk_shape=chunk_shape)
            mapped_count = int(sum(len(value["target_index"]) for value in mapped.values()))
            proof = finalize_initial_selection_proof(
                proof,
                full_resolution_boundary_verified=True,
                mapped_target_cell_count=mapped_count,
            )
            for tile, values in mapped.items():
                indices = values["target_index"]
                previous = combined[tile]["view"][indices]
                incoming = values["view_zenith_abs_deg"]
                replace = ~np.isfinite(previous) | (incoming > previous)
                overlaps += int(np.isfinite(previous).sum())
                chosen = indices[replace]
                combined[tile]["view"][chosen] = incoming[replace]
                combined[tile]["view_azimuth"][chosen] = values["view_azimuth_deg"][replace]
                combined[tile]["solar_azimuth"][chosen] = values["solar_azimuth_deg"][replace]
            scene_evidence.append(
                {
                    **proof,
                    "granule_id": granule,
                    "orbit": orbit,
                    "scene": int(link.scene),
                    "initial_chunk_count": len(initial),
                    "final_chunk_count": len(selected),
                    "selected_chunk_coords_sha256": sha256_strings(
                        f"{row}:{column}" for row, column in selected
                    ),
                    "selected_compressed_chunks_sha256": sha256_strings(
                        f"{key}:{value}" for key, value in chunk_hashes.items()
                    ),
                    "selected_compressed_chunk_hash_inventory": [
                        {"chunk_key": str(key), "sha256": str(value)}
                        for key, value in sorted(chunk_hashes.items())
                    ],
                    "range_request_count": fetcher.n_requests,
                    "range_bytes_transferred": fetcher.n_bytes,
                    "range_evidence_sha256": sha256_strings(fetcher.range_evidence),
                    "boundary_expansion_iterations": iterations,
                    "boundary_minimum_domain_distance_m": None
                    if not math.isfinite(minimum)
                    else minimum,
                    "boundary_edges_tested_final_iteration": edges,
                }
            )
        view = np.concatenate([item["view"] for item in combined.values()])
        view_azimuth = np.concatenate([item["view_azimuth"] for item in combined.values()])
        solar_azimuth = np.concatenate([item["solar_azimuth"] for item in combined.values()])
        valid_view = np.isfinite(view)
        valid_azimuth = valid_view & np.isfinite(view_azimuth) & np.isfinite(solar_azimuth)
        view_values = view[valid_view]
        azimuth_complete = bool(np.array_equal(valid_view, valid_azimuth))
        relative = relative_azimuth_deg(
            view_azimuth[valid_azimuth], solar_azimuth[valid_azimuth]
        )
        view_mean, view_concentration = circular_mean_concentration(view_azimuth[valid_azimuth])
        solar_mean, solar_concentration = circular_mean_concentration(solar_azimuth[valid_azimuth])
        n_domain = int(len(view))
        n_valid = int(valid_view.sum())
        coverage = n_valid / n_domain
        verified_zero_mapped = bool(
            n_valid == 0
            and scene_evidence
            and all(_accepted_zero_mapped_scene_proof(item) for item in scene_evidence)
        )
        geometry_complete = bool(
            verified_zero_mapped or (azimuth_complete and n_valid > 0)
        )
        summary = {
            "city": city,
            "window_id": str(candidate["window_id"]),
            "orbit": orbit,
            "acquisition_utc": pd.Timestamp(candidate["acquisition_utc"]).isoformat(),
            "year": int(pd.Timestamp(candidate["acquisition_utc"]).year),
            "source_population": str(candidate["source_population"]),
            "n_l1b_geo_scenes": int(len(pass_links)),
            "n_domain_pixels": n_domain,
            "n_view_valid_pixels": n_valid,
            "l1b_geometry_coverage_fraction": coverage,
            "l1b_view_zenith_abs_min_deg": float(np.min(view_values)) if n_valid else math.nan,
            "l1b_view_zenith_abs_median_deg": float(np.median(view_values)) if n_valid else math.nan,
            "l1b_view_zenith_abs_mean_deg": float(np.mean(view_values)) if n_valid else math.nan,
            "l1b_view_zenith_abs_p95_deg": float(np.quantile(view_values, 0.95)) if n_valid else math.nan,
            "l1b_view_zenith_abs_max_deg": float(np.max(view_values)) if n_valid else math.nan,
            "view_azimuth_circular_mean_deg": view_mean,
            "view_azimuth_circular_concentration": view_concentration,
            "solar_azimuth_circular_mean_deg": solar_mean,
            "solar_azimuth_circular_concentration": solar_concentration,
            "relative_azimuth_median_deg": float(np.median(relative)) if len(relative) else math.nan,
            "relative_azimuth_q1_deg": float(np.quantile(relative, 0.25)) if len(relative) else math.nan,
            "relative_azimuth_q3_deg": float(np.quantile(relative, 0.75)) if len(relative) else math.nan,
            "relative_azimuth_iqr_deg": float(np.quantile(relative, 0.75) - np.quantile(relative, 0.25)) if len(relative) else math.nan,
            "azimuth_valid_fraction_of_view_cells": float(valid_azimuth.sum() / n_valid) if n_valid else math.nan,
            "n_overlapping_valid_pixels": overlaps,
            "geometry_azimuth_complete": geometry_complete,
            "geometry_azimuth_status": (
                "RESOLVED_VERIFIED_ZERO_MAPPED_CELLS"
                if verified_zero_mapped
                else ("COMPLETE" if geometry_complete else "AZIMUTH_INCOMPLETE")
            ),
            "source_geometry_evidence_sha256": sha256_strings(
                item["selected_compressed_chunks_sha256"] for item in scene_evidence
            ),
            "decision_id": DECISION_ID,
            "temperature_or_lst_opened": False,
            "record_2026_opened": False,
        }
        reconstruction = _write_geometry_reconstruction(
            _reconstruction_path(city, orbit),
            city=city,
            window_id=str(candidate["window_id"]),
            orbit=orbit,
            target_grid_sha256=fingerprints[city],
            grids=grids[city],
            combined=combined,
        )
        if (
            reconstruction["n_domain_pixels"] != n_domain
            or reconstruction["n_valid_target_cells"] != n_valid
        ):
            raise ValueError("Geometry reconstruction census differs from the pass summary")
        summary["geometry_reconstruction_artifact_sha256"] = reconstruction["sha256"]
        summary["geometry_reconstruction_artifact_size_bytes"] = reconstruction["size_bytes"]
        summary["geometry_reconstruction_evidence_complete"] = True
        document = {
            "status": "complete",
            "binding": binding_payload,
            "binding_sha256": binding,
            "zero_map_proof_schema_version": ZERO_MAP_PROOF_SCHEMA_VERSION,
            "scene_evidence": scene_evidence,
            "reconstruction_artifact": reconstruction,
            "summary": summary,
            "temperature_or_lst_opened": False,
            "record_2026_opened": False,
        }
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_json(document, evidence_path)
        record = {
            "status": "complete",
            "binding_sha256": binding,
            "evidence_path": str(evidence_path),
            "evidence_sha256": sha256_file(evidence_path),
        }
        return item_id, record, summary

    summaries = []
    records = candidates.sort_values(["city", "acquisition_utc", "orbit"]).to_dict("records")
    for start in range(0, len(records), 20):
        failures = []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(worker, row): row for row in records[start : start + 20]}
            for future in as_completed(futures):
                row = futures[future]
                try:
                    item_id, evidence, summary = future.result()
                    checkpoint[item_id] = evidence
                    summaries.append(summary)
                except Exception as exc:
                    failures.append(
                        (
                            f"{row['city']}:{int(row['orbit'])}",
                            type(exc).__name__,
                            str(exc)[:500],
                        )
                    )
        write_checkpoint(PASS_CHECKPOINT, checkpoint)
        print(f"D0069 five-field passes: {min(start + 20, len(records))}/{len(records)}", flush=True)
        if failures:
            raise RuntimeError(f"Five-field geometry failures: {failures[:5]}")
    resolved = pd.DataFrame(summaries)
    inaccessible = ledger.loc[~ledger["archive_status"].eq("ACCESSIBLE")].copy()
    inaccessible_rows = pd.DataFrame(
        {
            "city": inaccessible["city"],
            "window_id": inaccessible["window_id"],
            "orbit": inaccessible["orbit"].astype(int),
            "acquisition_utc": inaccessible["acquisition_utc"],
            "year": pd.to_datetime(inaccessible["acquisition_utc"], utc=True).dt.year,
            "source_population": inaccessible["source_population"],
            "geometry_azimuth_complete": False,
            "geometry_azimuth_status": inaccessible["archive_status"],
            "decision_id": DECISION_ID,
            "temperature_or_lst_opened": False,
            "record_2026_opened": False,
        }
    )
    final = pd.concat([resolved, inaccessible_rows], ignore_index=True, sort=False).sort_values(
        ["city", "acquisition_utc", "orbit"], kind="stable"
    )
    if (
        len(final) != len(ledger)
        or final.duplicated(["city", "orbit"]).any()
        or _pass_identities(final) != _pass_identities(ledger)
    ):
        raise ValueError("Five-field geometry output is not ledger-complete")
    reconstruction_rows = final.loc[
        final["geometry_azimuth_status"].astype(str).ne("RESOLVED_UNAVAILABLE")
    ]
    if not reconstruction_rows["geometry_reconstruction_evidence_complete"].astype(
        "string"
    ).str.casefold().eq("true").all():
        raise ValueError("A resolved geometry pass lacks mapped-cell reconstruction evidence")
    actual_reconstruction_bytes = int(
        pd.to_numeric(
            reconstruction_rows["geometry_reconstruction_artifact_size_bytes"], errors="raise"
        ).sum()
    )
    if actual_reconstruction_bytes > GEOMETRY_RECONSTRUCTION_MAX_BYTES:
        raise RuntimeError("D0069 mapped-cell reconstruction artifacts exceeded the 8 GiB guard")
    _atomic_csv(final, GEOMETRY_SUMMARY)
    print(
        f"D0069 geometry complete: {int(final['geometry_azimuth_complete'].fillna(False).sum())}/{len(final)} resolved five-field rows",
        flush=True,
    )


def _geometry_qualifiers() -> pd.DataFrame:
    geometry = pd.read_csv(GEOMETRY_SUMMARY)
    complete = geometry["geometry_azimuth_complete"].astype("string").str.casefold().eq("true")
    qualifiers = geometry.loc[
        complete
        & pd.to_numeric(geometry["l1b_geometry_coverage_fraction"], errors="coerce").ge(0.95)
        & pd.to_numeric(geometry["l1b_view_zenith_abs_p95_deg"], errors="coerce").le(25.0)
    ].copy()
    qualifiers["orbit"] = pd.to_numeric(qualifiers["orbit"], errors="raise").astype(int)
    qualifiers["acquisition_utc"] = pd.to_datetime(
        qualifiers["acquisition_utc"], utc=True, errors="raise", format="mixed"
    )
    if qualifiers.empty or qualifiers.duplicated(["city", "orbit"]).any():
        raise ValueError("D0069 primary-threshold geometry qualifiers are empty or duplicated")
    return qualifiers


def _cloud_target_manifest(qualifiers: pd.DataFrame) -> pd.DataFrame:
    existing_keys = qualifiers.loc[
        qualifiers["source_population"].eq("existing_d0047"),
        ["city", "orbit", "acquisition_utc"],
    ].copy()
    existing_keys["quality_candidate_pre_cloud"] = True
    existing_clouds = pd.DataFrame()
    if len(existing_keys):
        existing_clouds = build_exhaustive_cloud_manifest(
            existing_keys,
            pd.read_csv(EXISTING_VIEW_MANIFEST),
            l2t_results=load_cached_l2t_results(EXISTING_L2T_CACHE),
            expected_candidate_passes=len(existing_keys),
        )
    new_manifest = pd.read_csv(NEW_L2T_MANIFEST)
    new_keys = qualifiers.loc[
        qualifiers["source_population"].eq("new_d0069"), ["city", "orbit"]
    ]
    new_clouds = (
        new_manifest.loc[new_manifest["asset_type"].eq(CLOUD_COG)]
        .merge(new_keys, on=["city", "orbit"], how="inner", validate="many_to_one")
        .copy()
    )
    clouds = pd.concat([existing_clouds, new_clouds], ignore_index=True, sort=False)
    if not clouds["status"].astype(str).eq("available").all():
        raise RuntimeError("A D0069 cloud target is unresolved")
    expected = set(map(tuple, qualifiers[["city", "orbit"]].to_records(index=False)))
    observed = set(map(tuple, clouds[["city", "orbit"]].drop_duplicates().to_records(index=False)))
    if observed != expected:
        raise ValueError("D0069 cloud manifest does not cover every geometry qualifier")
    _atomic_csv(clouds, CLOUD_MANIFEST)
    return clouds


def _seed_asset_checkpoint(targets: pd.DataFrame, destination: Path) -> None:
    target_ids = set(targets["item_id"].astype(str))
    seeded: dict[str, Any] = {}
    sources = (
        ROOT / "data/raw/v2/ecostress/enrichment_assets/cloud_l1b_geo_D0047_checkpoint.json",
        ROOT / "data/raw/v2/ecostress/enrichment_assets/cloud_exhaustive_checkpoint.json",
        ROOT / "data/raw/v2/ecostress/enrichment_assets/enrichment_checkpoint.json",
        G3_ASSET_CHECKPOINT,
        destination,
    )
    for path in sources:
        for item_id, record in load_checkpoint(path).items():
            if item_id not in target_ids or record.get("status") != "complete":
                continue
            local_path = Path(str(record.get("local_path", "")))
            digest = str(record.get("sha256", ""))
            if (
                local_path.is_file()
                and len(digest) == 64
                and local_path.stat().st_size == int(record.get("size_bytes", -1))
                and sha256_file(local_path) == digest
            ):
                seeded[item_id] = dict(record)
    write_checkpoint(destination, seeded)


def run_cloud(workers: int) -> None:
    _require_resolved_new_archive()
    _, geometries = _domains()
    qualifiers = _geometry_qualifiers()
    clouds = _cloud_target_manifest(qualifiers)
    _seed_asset_checkpoint(clouds, CLOUD_CHECKPOINT)
    earthaccess, _ = legacy_geometry._earthaccess()
    download_target_manifest_concurrent(
        clouds,
        destination_root=ASSET_ROOT,
        checkpoint_path=CLOUD_CHECKPOINT,
        session_factory=earthaccess.get_requests_https_session,
        max_workers=workers,
    )
    checkpoint = load_checkpoint(CLOUD_CHECKPOINT)
    cloud_groups = {
        (str(city), int(orbit)): group
        for (city, orbit), group in clouds.groupby(["city", "orbit"], sort=True)
    }
    tile_domains = {
        city: {
            tile: partition_domain_for_mgrs_tile(geometries[city], tile)
            for tile in sorted(clouds.loc[clouds["city"].eq(city), "tile"].astype(str).unique())
        }
        for city in sorted(qualifiers["city"].unique())
    }
    rows = []
    for pass_row in qualifiers.sort_values(["city", "acquisition_utc", "orbit"]).to_dict("records"):
        key = (str(pass_row["city"]), int(pass_row["orbit"]))
        group = cloud_groups[key]
        evidence = []
        for record in group.to_dict("records"):
            item = checkpoint.get(str(record["item_id"]), {})
            path = Path(str(item.get("local_path", "")))
            if not (
                item.get("status") == "complete"
                and path.is_file()
                and item.get("sha256") == sha256_file(path)
                and path.name == Path(str(record["file_name"])).name
            ):
                raise RuntimeError(f"Cloud provenance is incomplete for {key}")
            evidence.append(f"{record['item_id']}:{item['sha256']}:{item['size_bytes']}")
        result = _summarize_cloud_without_view_mask(
            group,
            asset_root=ASSET_ROOT,
            domain_pixel_denominator=int(pass_row["n_domain_pixels"]),
            tile_domain_geometries_wgs84=tile_domains[key[0]],
        )
        result.update(
            {
                "city": key[0],
                "window_id": pass_row["window_id"],
                "orbit": key[1],
                "acquisition_utc": pd.Timestamp(pass_row["acquisition_utc"]).isoformat(),
                "clear_domain_fraction": result["cloud_survival_fraction_of_domain_independent_of_view"],
                "n_cloud_assets": int(len(group)),
                "cloud_asset_set_sha256": sha256_strings(evidence),
                "cloud_complete": True,
                "decision_id": DECISION_ID,
                "temperature_or_lst_opened": False,
                "record_2026_opened": False,
            }
        )
        rows.append(result)
    summary = pd.DataFrame(rows)
    if (
        len(summary) != len(qualifiers)
        or summary.duplicated(["city", "orbit"]).any()
        or _pass_identities(summary) != _pass_identities(qualifiers)
        or not summary["cloud_complete"].all()
        or not summary["cloud_asset_set_sha256"].astype(str).str.fullmatch(r"[0-9a-f]{64}").all()
    ):
        raise ValueError("D0069 cloud summary is incomplete")
    _atomic_csv(summary, CLOUD_SUMMARY)
    print(f"D0069 cloud complete: {len(summary)}/{len(qualifiers)} passes", flush=True)


def _weather_geometry_binding(record: Mapping[str, Any]) -> dict[str, str]:
    """Return the exact repaired-domain digests sealed into one HRRR request."""

    cities = sorted(filter(None, str(record["cities"]).split("|")))
    raw = record.get("analysis_geometry_sha256_by_city")
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        raise ValueError("HRRR request has an invalid analysis-geometry binding") from None
    binding = {str(city): str(digest) for city, digest in parsed.items()}
    if (
        sorted(binding) != cities
        or not all(re.fullmatch(r"[0-9a-f]{64}", digest) for digest in binding.values())
        or str(record.get("analysis_geometry_set_sha256")) != _canonical_sha256(binding)
        or str(record.get("weather_algorithm_version")) != WEATHER_ALGORITHM_VERSION
    ):
        raise ValueError("HRRR request analysis-geometry/algorithm seal failed")
    return dict(sorted(binding.items()))


def _weather_request_binding(record: Mapping[str, Any]) -> dict[str, Any]:
    timestamp = pd.Timestamp(record["analysis_utc"])
    timestamp = timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")
    geometry_binding = _weather_geometry_binding(record)
    return {
        "item_id": str(record["item_id"]),
        "analysis_utc": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "cities": "|".join(sorted(filter(None, str(record["cities"]).split("|")))),
        "n_target_passes": int(record["n_target_passes"]),
        "model": str(record["model"]),
        "product": str(record["product"]),
        "forecast_hour": int(record["forecast_hour"]),
        "temperature_dewpoint_variable_search": TEMPERATURE_SEARCH,
        "wind_variable_search": WIND_SEARCH,
        "source": HRRR_SOURCE,
        "object_key": str(record["object_key"]),
        "product_resolution": str(record["product_resolution"]),
        "weather_algorithm_version": WEATHER_ALGORITHM_VERSION,
        "analysis_geometry_sha256_by_city": geometry_binding,
        "analysis_geometry_set_sha256": _canonical_sha256(geometry_binding),
    }


def _valid_weather_shard(
    path: Path,
    record: Mapping[str, Any],
    checkpoint_record: Mapping[str, Any],
) -> pd.DataFrame | None:
    if not path.is_file():
        return None
    try:
        frame = pd.read_csv(path, parse_dates=["timestamp_utc"])
    except Exception:
        return None
    required = {
        "city",
        "timestamp_utc",
        "grid_y_index",
        "grid_x_index",
        "latitude",
        "longitude",
        "t2m_k",
        "d2m_k",
        "vpd_kpa",
        "u10_m_s",
        "v10_m_s",
        "wind_speed_m_s",
        "weather_algorithm_version",
        "analysis_geometry_sha256",
    }
    cities = sorted(filter(None, str(record["cities"]).split("|")))
    try:
        binding = _weather_request_binding(record)
    except (KeyError, TypeError, ValueError):
        return None
    geometry_binding = binding["analysis_geometry_sha256_by_city"]
    digest = sha256_file(path)
    if (
        required.difference(frame.columns)
        or checkpoint_record.get("status") != "complete"
        or checkpoint_record.get("request_binding") != binding
        or checkpoint_record.get("request_binding_sha256") != _canonical_sha256(binding)
        or checkpoint_record.get("sha256") != digest
        or int(checkpoint_record.get("size_bytes", -1)) != path.stat().st_size
        or sorted(checkpoint_record.get("cities", [])) != cities
        or checkpoint_record.get("weather_algorithm_version") != WEATHER_ALGORITHM_VERSION
        or checkpoint_record.get("analysis_geometry_sha256_by_city") != geometry_binding
        or checkpoint_record.get("analysis_geometry_set_sha256")
        != binding["analysis_geometry_set_sha256"]
    ):
        return None
    frame["timestamp_utc"] = pd.to_datetime(
        frame["timestamp_utc"], utc=True, errors="coerce", format="mixed"
    )
    expected_time = pd.Timestamp(record["analysis_utc"])
    expected_time = expected_time.tz_localize("UTC") if expected_time.tzinfo is None else expected_time.tz_convert("UTC")
    numeric_columns = sorted(
        required.difference(
            {
                "city",
                "timestamp_utc",
                "weather_algorithm_version",
                "analysis_geometry_sha256",
            }
        )
    )
    for column in numeric_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if (
        frame.empty
        or set(frame["city"].astype(str)) != set(cities)
        or frame["timestamp_utc"].isna().any()
        or not frame["timestamp_utc"].eq(expected_time).all()
        or expected_time.year not in range(2018, 2026)
        or frame[numeric_columns].isna().any().any()
        or frame.duplicated(["city", "grid_y_index", "grid_x_index"]).any()
        or any(len(group) < 2 for _, group in frame.groupby("city"))
        or not frame["weather_algorithm_version"].astype(str).eq(
            WEATHER_ALGORITHM_VERSION
        ).all()
        or any(
            not group["analysis_geometry_sha256"].astype(str).eq(
                geometry_binding[city]
            ).all()
            for city, group in frame.groupby("city", sort=False)
        )
    ):
        return None
    plausible = bool(
        frame["latitude"].between(-90, 90).all()
        and frame["longitude"].between(-180, 180).all()
        and frame["t2m_k"].between(180, 350).all()
        and frame["d2m_k"].between(170, 340).all()
        and frame["vpd_kpa"].between(0, 30).all()
        and frame["u10_m_s"].between(-150, 150).all()
        and frame["v10_m_s"].between(-150, 150).all()
        and frame["wind_speed_m_s"].between(0, 150).all()
        and np.allclose(
            frame["wind_speed_m_s"],
            np.hypot(frame["u10_m_s"], frame["v10_m_s"]),
            rtol=1e-6,
            atol=1e-6,
        )
    )
    if not plausible:
        return None
    return frame


class _D0069HrrrLoader:
    """AWS-only exact-hour loader for the four frozen weather components."""

    def __init__(self, cache_dir: Path, herbie_factory: Any | None = None) -> None:
        self.cache_dir = cache_dir
        self.herbie_factory = herbie_factory

    def __call__(self, analysis_utc: Any) -> tuple[Any, Any]:
        factory = self.herbie_factory
        if factory is None:
            status = dependency_status()
            if not status["live_ready"]:
                missing = [name for name in ("herbie", "cfgrib", "eccodes", "xarray") if not status[name]]
                raise HrrrDependencyError(f"Live HRRR wind decoding dependencies missing: {', '.join(missing)}")
            from herbie import Herbie

            factory = Herbie
        timestamp = pd.Timestamp(analysis_utc)
        timestamp = timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            request = factory(
                timestamp.tz_localize(None).to_pydatetime(),
                model=HRRR_MODEL,
                product=official_hrrr_product(timestamp),
                fxx=HRRR_FORECAST_HOUR,
                priority=["aws"],
                save_dir=self.cache_dir,
                overwrite=False,
                verbose=False,
            )
            temperature = request.xarray(TEMPERATURE_SEARCH, remove_grib=True, verbose=False)
            wind = request.xarray(WIND_SEARCH, remove_grib=True, verbose=False)
            if isinstance(temperature, (list, tuple)):
                import xarray as xr

                temperature = xr.merge(list(temperature), compat="override", join="exact")
            if isinstance(wind, (list, tuple)):
                import xarray as xr

                wind = xr.merge(list(wind), compat="override", join="exact")
            return temperature, wind
        except HrrrDependencyError:
            raise
        except Exception:
            raise HrrrFetchError(f"D0069 HRRR load failed for {timestamp.isoformat()}") from None


def _extract_domain_cells_with_wind(
    temperature_dataset: Any,
    wind_dataset: Any,
    domains: Mapping[str, Any],
    *,
    analysis_utc: Any,
) -> pd.DataFrame:
    cells = extract_domain_cells(
        temperature_dataset,
        domains,
        analysis_utc=analysis_utc,
        minimum_domain_cells=2,
    )
    temp_latitude, temp_longitude = _grid_coordinates(temperature_dataset)
    wind_latitude, wind_longitude = _grid_coordinates(wind_dataset)
    u10 = _two_dimensional(_dataset_variable(wind_dataset, "u10", "10u"), "u10")
    v10 = _two_dimensional(_dataset_variable(wind_dataset, "v10", "10v"), "v10")
    if not (
        temp_latitude.shape == wind_latitude.shape == u10.shape == v10.shape
        and np.allclose(temp_latitude, wind_latitude, rtol=0, atol=1e-8, equal_nan=True)
        and np.allclose(temp_longitude, wind_longitude, rtol=0, atol=1e-8, equal_nan=True)
    ):
        raise ValueError("HRRR 2-m and 10-m fields do not share the exact frozen grid")
    y = cells["grid_y_index"].to_numpy(dtype=int)
    x = cells["grid_x_index"].to_numpy(dtype=int)
    cells["u10_m_s"] = u10[y, x]
    cells["v10_m_s"] = v10[y, x]
    cells["wind_speed_m_s"] = np.hypot(cells["u10_m_s"], cells["v10_m_s"])
    if not (
        cells[["u10_m_s", "v10_m_s", "wind_speed_m_s"]].notna().all().all()
        and cells["u10_m_s"].between(-150, 150).all()
        and cells["v10_m_s"].between(-150, 150).all()
        and cells["wind_speed_m_s"].between(0, 150).all()
    ):
        raise ValueError("HRRR 10-m wind fields are incomplete or physically implausible")
    return cells


def _summarize_domain_cells_with_wind(cells: pd.DataFrame) -> pd.DataFrame:
    summary = summarize_domain_cells(cells)
    wind = (
        cells.groupby(["city", "timestamp_utc"], sort=True, observed=True)
        .agg(
            u10_m_s=("u10_m_s", "mean"),
            v10_m_s=("v10_m_s", "mean"),
            wind_speed_m_s=("wind_speed_m_s", "mean"),
            wind_speed_m_s_std=("wind_speed_m_s", "std"),
        )
        .reset_index()
    )
    return summary.merge(wind, on=["city", "timestamp_utc"], how="inner", validate="one_to_one")


def _live_hrrr_storage_preflight(
    conservative_new_data_bytes: int,
    *,
    storage_root: Path = HRRR_ROOT,
    reserve_bytes: int = HRRR_MIN_FREE_SPACE_RESERVE_BYTES,
    evidence_path: Path | None = HRRR_STORAGE_PREFLIGHT,
    disk_usage: Any = shutil.disk_usage,
    estimate_sha256: str | None = None,
) -> dict[str, Any]:
    """Fail closed unless live free space covers the full estimate plus reserve."""

    estimate = int(conservative_new_data_bytes)
    reserve = int(reserve_bytes)
    if estimate < 0 or reserve < 0:
        raise ValueError("D0069 HRRR storage estimate and reserve must be nonnegative")
    storage_root.mkdir(parents=True, exist_ok=True)
    try:
        free_bytes = int(disk_usage(storage_root).free)
    except Exception:
        raise RuntimeError("D0069 could not measure live free space; weather fetch is locked") from None
    required = estimate + reserve
    passed = free_bytes >= required
    payload = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "decision_id": DECISION_ID,
        "weather_algorithm_version": WEATHER_ALGORITHM_VERSION,
        "storage_root": str(storage_root.resolve()),
        "conservative_new_data_bytes": estimate,
        "explicit_reserve_bytes": reserve,
        "required_free_bytes": required,
        "observed_free_bytes": free_bytes,
        "estimate_sha256": estimate_sha256,
        "status": "PASS" if passed else "FAIL_INSUFFICIENT_FREE_SPACE",
    }
    if evidence_path is not None:
        _atomic_json(payload, evidence_path)
    if not passed:
        raise RuntimeError(
            "D0069 HRRR live storage preflight failed: "
            f"free={free_bytes}, estimate={estimate}, reserve={reserve}, required={required}"
        )
    return payload


def _weather_manifest_for_population(
    population: pd.DataFrame,
    geometries: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    if population.duplicated(["city", "orbit"]).any():
        raise ValueError("D0069 exact-weather population double-counts a physical pass")
    if geometries is None:
        _, geometries = _domains()
    manifest = build_hrrr_request_manifest(population)
    manifest["temperature_dewpoint_variable_search"] = TEMPERATURE_SEARCH
    manifest["wind_variable_search"] = WIND_SEARCH
    manifest["variable_search"] = COMBINED_WEATHER_SEARCH
    manifest["source"] = HRRR_SOURCE
    manifest["weather_algorithm_version"] = WEATHER_ALGORITHM_VERSION
    geometry_bindings: list[str] = []
    geometry_set_digests: list[str] = []
    for value in manifest["cities"].astype(str):
        cities = sorted(filter(None, value.split("|")))
        unknown = sorted(set(cities).difference(geometries))
        if unknown:
            raise ValueError(f"D0069 HRRR request lacks repaired domains for {unknown}")
        binding = {city: sha256_json(geometries[city]) for city in cities}
        if not all(re.fullmatch(r"[0-9a-f]{64}", digest) for digest in binding.values()):
            raise ValueError("D0069 repaired analysis-geometry digest is invalid")
        geometry_bindings.append(
            json.dumps(binding, sort_keys=True, separators=(",", ":"))
        )
        geometry_set_digests.append(_canonical_sha256(binding))
    manifest["analysis_geometry_sha256_by_city"] = geometry_bindings
    manifest["analysis_geometry_set_sha256"] = geometry_set_digests
    for record in manifest.to_dict("records"):
        _weather_request_binding(record)
    return manifest


def _fetch_exact_weather(
    weather_population: pd.DataFrame,
    geometries: Mapping[str, Any],
    workers: int,
) -> pd.DataFrame:
    manifest = _weather_manifest_for_population(weather_population, geometries)
    _atomic_csv(manifest, HRRR_MANIFEST)
    shards = HRRR_ROOT / "hourly_domain_cells"
    shards.mkdir(parents=True, exist_ok=True)
    checkpoint_path = HRRR_ROOT / "hrrr_checkpoint_d0069.json"
    manifest_items = set(manifest["item_id"].astype(str))
    checkpoint = {
        item_id: record
        for item_id, record in load_checkpoint(checkpoint_path).items()
        if item_id in manifest_items
    }
    pending = []
    rows_by_item: dict[str, pd.DataFrame] = {}
    for record in manifest.to_dict("records"):
        item_id = str(record["item_id"])
        destination = shards / f"{item_id}.csv.gz"
        item = checkpoint.get(item_id, {})
        current = _valid_weather_shard(destination, record, item)
        if current is not None:
            rows_by_item[item_id] = current
            continue
        pending.append(record)
    write_checkpoint(checkpoint_path, checkpoint)
    if pending:
        pending_manifest = pd.DataFrame(pending)
        estimate_manifest = pending_manifest.copy()
        estimate_manifest["variable_search"] = HRRR_SEARCH_STRING
        estimate_manifest["source"] = HRRR_SOURCE_LABEL
        estimates = estimate_hrrr_subset_downloads(
            estimate_manifest, max_workers=min(workers, 8)
        )
        # The base estimator covers TMP/DPT. Double its conservative byte bound
        # for the similarly narrow UGRD/VGRD subset requested by D0069.
        estimates["conservative_new_data_bytes"] = (
            pd.to_numeric(estimates["conservative_new_data_bytes"], errors="raise") * 2
        ).astype(int)
        _atomic_csv(estimates, HRRR_STORAGE_ESTIMATE)
        total = int(estimates["conservative_new_data_bytes"].sum())
        _live_hrrr_storage_preflight(
            total,
            estimate_sha256=sha256_file(HRRR_STORAGE_ESTIMATE),
        )
        thread_local = threading.local()

        def fetch(record: Mapping[str, Any]) -> tuple[str, pd.DataFrame]:
            if not hasattr(thread_local, "loader"):
                thread_local.loader = _D0069HrrrLoader(HRRR_ROOT / "grib_cache")
            timestamp = pd.Timestamp(record["analysis_utc"])
            cities = sorted(filter(None, str(record["cities"]).split("|")))
            temperature_dataset, wind_dataset = thread_local.loader(timestamp)
            try:
                cells = _extract_domain_cells_with_wind(
                    temperature_dataset,
                    wind_dataset,
                    {city: geometries[city] for city in cities},
                    analysis_utc=timestamp,
                )
                geometry_binding = _weather_geometry_binding(record)
                cells["weather_algorithm_version"] = WEATHER_ALGORITHM_VERSION
                cells["analysis_geometry_sha256"] = cells["city"].map(
                    geometry_binding
                )
                if cells["analysis_geometry_sha256"].isna().any():
                    raise ValueError("D0069 extracted HRRR cells lack a repaired-domain binding")
            finally:
                for dataset in (temperature_dataset, wind_dataset):
                    close = getattr(dataset, "close", None)
                    if callable(close):
                        close()
            return str(record["item_id"]), cells

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(fetch, record): record for record in pending}
            completed = 0
            failures: list[tuple[str, str]] = []
            for future in as_completed(futures):
                record = futures[future]
                try:
                    item_id, cells = future.result()
                except Exception as exc:
                    failures.append((str(record["item_id"]), type(exc).__name__))
                    continue
                destination = shards / f"{item_id}.csv.gz"
                temporary = destination.with_name(f".{destination.name}.tmp")
                cells.to_csv(temporary, index=False, compression="gzip")
                temporary.replace(destination)
                cities = sorted(filter(None, str(record["cities"]).split("|")))
                binding = _weather_request_binding(record)
                evidence = {
                    "status": "complete",
                    "source": HRRR_SOURCE,
                    "weather_algorithm_version": WEATHER_ALGORITHM_VERSION,
                    "analysis_geometry_sha256_by_city": binding[
                        "analysis_geometry_sha256_by_city"
                    ],
                    "analysis_geometry_set_sha256": binding[
                        "analysis_geometry_set_sha256"
                    ],
                    "request_binding": binding,
                    "request_binding_sha256": _canonical_sha256(binding),
                    "sha256": sha256_file(destination),
                    "size_bytes": destination.stat().st_size,
                    "cities": cities,
                }
                validated = _valid_weather_shard(destination, record, evidence)
                if validated is None:
                    failures.append((item_id, "PersistedShardValidationError"))
                    continue
                checkpoint[item_id] = evidence
                rows_by_item[item_id] = validated
                completed += 1
                write_checkpoint(checkpoint_path, checkpoint)
                if completed % 20 == 0:
                    print(f"D0069 exact HRRR pending hours: {completed}/{len(pending)}", flush=True)
        write_checkpoint(checkpoint_path, checkpoint)
        if failures:
            raise RuntimeError(f"D0069 exact HRRR failures after preserving successes: {failures[:8]}")
    ordered = [rows_by_item[str(item)] for item in manifest["item_id"]]
    all_cells = pd.concat(ordered, ignore_index=True)
    summary = _summarize_domain_cells_with_wind(all_cells)
    _atomic_csv(summary, HRRR_HOURLY_SUMMARY)
    return summary


def _interpolate_weather_to_passes(
    passes: pd.DataFrame,
    hourly: pd.DataFrame,
) -> pd.DataFrame:
    output = passes.copy()
    output["acquisition_utc"] = pd.to_datetime(
        output["acquisition_utc"], utc=True, errors="raise", format="mixed"
    )
    weather = hourly.copy()
    weather["timestamp_utc"] = pd.to_datetime(
        weather["timestamp_utc"], utc=True, errors="raise", format="mixed"
    )
    for target_column, source_column in (
        ("vpd_kpa_at_acquisition", "vpd_kpa"),
        ("air_temperature_k_at_acquisition", "t2m_k"),
        ("wind_speed_m_s_at_acquisition", "wind_speed_m_s"),
    ):
        output[target_column] = np.nan
        for city, indices in output.groupby("city").indices.items():
            source = weather.loc[weather["city"].eq(city)].sort_values("timestamp_utc")
            source_time = source["timestamp_utc"].astype("int64").to_numpy(dtype=float)
            source_values = pd.to_numeric(source[source_column], errors="coerce").to_numpy(float)
            target_time = output.iloc[indices]["acquisition_utc"].astype("int64").to_numpy(dtype=float)
            values = np.interp(target_time, source_time, source_values, left=np.nan, right=np.nan)
            output.iloc[indices, output.columns.get_loc(target_column)] = values
    return output


def _condition_labels(passes: pd.DataFrame, features: Mapping[str, Any]) -> pd.DataFrame:
    daily = add_antecedent_predictors(pd.read_csv(DAILY_GRIDMET, parse_dates=["date"]))
    daily = daily.loc[daily["city"].isin(PRIMARY_WINDOWS)].copy()
    daily["window_id"] = np.where(
        daily["city"].eq("phoenix") & daily["date"].dt.month.isin([4, 5]),
        "phoenix_apr_may",
        np.where(daily["date"].dt.month.isin([6, 7, 8, 9]), "jun_sep", None),
    )
    daily = daily.loc[
        [PRIMARY_WINDOWS.get(city) == window for city, window in daily[["city", "window_id"]].itertuples(index=False)]
    ].copy()
    daily["local_solar_date"] = daily["date"].dt.date
    output = passes.copy()
    longitudes = output["city"].map(
        {city: float(feature["properties"]["CENTLON"]) for city, feature in features.items()}
    )
    output["local_solar_date"] = local_solar_dates(
        output["acquisition_utc"], longitudes
    ).to_numpy()
    daily_lookup = daily[
        ["city", "window_id", "local_solar_date", "antecedent_precipitation_30d_mm"]
    ].drop_duplicates(["city", "window_id", "local_solar_date"])
    output = output.merge(
        daily_lookup,
        on=["city", "window_id", "local_solar_date"],
        how="left",
        validate="many_to_one",
    )
    output["demand_percentile"] = np.nan
    output["antecedent_precipitation_30d_wetness_percentile"] = np.nan
    for (city, window_id), indices in output.groupby(["city", "window_id"]).indices.items():
        reference = daily.loc[daily["city"].eq(city) & daily["window_id"].eq(window_id)]
        for target, reference_column in (
            ("demand_percentile", "vpd_kpa"),
            (
                "antecedent_precipitation_30d_wetness_percentile",
                "antecedent_precipitation_30d_mm",
            ),
        ):
            ordered = pd.to_numeric(reference[reference_column], errors="coerce").dropna().to_numpy(float)
            value_column = (
                "vpd_kpa_at_acquisition" if target == "demand_percentile" else reference_column
            )
            values = pd.to_numeric(output.iloc[indices][value_column], errors="coerce").to_numpy(float)
            percentiles = _average_tie_reference_percentile(ordered, values)
            output.iloc[indices, output.columns.get_loc(target)] = percentiles
    dates = pd.to_datetime(output["local_solar_date"])
    starts = pd.to_datetime(
        [f"{date.year}-04-01" if window == "phoenix_apr_may" else f"{date.year}-06-01" for date, window in zip(dates, output["window_id"], strict=True)]
    )
    output["day_of_window"] = (dates - starts).dt.days + 1
    output["demand_level"] = _right_open_tercile(
        output["demand_percentile"], ("low", "middle", "high")
    )
    wetness = output["antecedent_precipitation_30d_wetness_percentile"]
    output["wetness_level"] = _right_open_tercile(
        wetness, ("dry", "middle", "wet")
    )
    output["time_stratum"] = output["city"].astype(str)
    new_time = pd.read_csv(NEW_PASSES)[["city", "orbit", "time_stratum"]]
    existing_time = pd.read_csv(
        ROOT / "data/processed/v2/task1/step2_definitive_l1b_geo_D0047_archive_available/tables/step2_scene_catalogue.csv",
        low_memory=False,
    )[["city", "orbit", "time_stratum"]]
    time = pd.concat([existing_time, new_time], ignore_index=True).drop_duplicates(["city", "orbit"])
    output = output.drop(columns=["time_stratum"]).merge(
        time, on=["city", "orbit"], how="left", validate="one_to_one"
    )
    required = [
        "vpd_kpa_at_acquisition",
        "air_temperature_k_at_acquisition",
        "wind_speed_m_s_at_acquisition",
        "antecedent_precipitation_30d_mm",
        "demand_percentile",
        "antecedent_precipitation_30d_wetness_percentile",
        "time_stratum",
    ]
    if output[required].isna().any().any():
        raise ValueError(f"D0069 exact-weather/condition join is incomplete: {output[required].isna().sum().to_dict()}")
    output["exact_weather_complete"] = True
    output["decision_id"] = DECISION_ID
    output["temperature_or_lst_opened"] = False
    output["record_2026_opened"] = False
    return output


def _split_weather_outputs(
    labelled: pd.DataFrame,
    qualifiers: pd.DataFrame,
    unavailable: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split one weather fetch into observed and optimistic archive-bound tables."""

    if (
        qualifiers.duplicated(["city", "orbit"]).any()
        or unavailable.duplicated(["city", "orbit"]).any()
        or set(map(tuple, qualifiers[["city", "orbit"]].to_records(index=False)))
        & set(map(tuple, unavailable[["city", "orbit"]].to_records(index=False)))
    ):
        raise ValueError("D0069 weather populations overlap or contain duplicate passes")
    expected = pd.concat(
        [
            qualifiers[["city", "window_id", "orbit", "acquisition_utc"]],
            unavailable[["city", "window_id", "orbit", "acquisition_utc"]],
        ],
        ignore_index=True,
    )
    if len(labelled) != len(expected) or _pass_identities(labelled) != _pass_identities(expected):
        raise ValueError("D0069 labelled weather census does not equal its union population")
    key = ["city", "orbit"]
    qualifier_keys = qualifiers[key].assign(_qualifier=True)
    unavailable_keys = unavailable[key].assign(_unavailable=True)
    marked = (
        labelled.merge(qualifier_keys, on=key, how="left", validate="one_to_one")
        .merge(unavailable_keys, on=key, how="left", validate="one_to_one")
    )
    qualifier_mask = marked["_qualifier"].eq(True)
    unavailable_mask = marked["_unavailable"].eq(True)
    if (qualifier_mask == unavailable_mask).any():
        raise ValueError("A D0069 weather row has zero or two output memberships")
    observed = marked.loc[qualifier_mask].drop(columns=["_qualifier", "_unavailable"])
    upper = marked.loc[unavailable_mask].drop(columns=["_qualifier", "_unavailable"])
    observed["archive_bound_role"] = "OBSERVED_GEOMETRY_QUALIFIER"
    upper["archive_bound_role"] = "UPPER_BOUND_ONLY_RESOLVED_UNAVAILABLE"
    upper["archive_status"] = "RESOLVED_UNAVAILABLE"
    upper["geometry_observed"] = False
    upper["cloud_observed"] = False
    upper["selection_eligible_observation"] = False
    upper["upper_bound_only"] = True
    upper_columns = [
        "city",
        "window_id",
        "orbit",
        "acquisition_utc",
        "year",
        "source_population",
        "archive_status",
        "local_solar_date",
        "day_of_window",
        "time_stratum",
        "vpd_kpa_at_acquisition",
        "air_temperature_k_at_acquisition",
        "wind_speed_m_s_at_acquisition",
        "antecedent_precipitation_30d_mm",
        "demand_percentile",
        "demand_level",
        "antecedent_precipitation_30d_wetness_percentile",
        "wetness_level",
        "exact_weather_complete",
        "archive_bound_role",
        "geometry_observed",
        "cloud_observed",
        "selection_eligible_observation",
        "upper_bound_only",
        "decision_id",
        "temperature_or_lst_opened",
        "record_2026_opened",
    ]
    missing_upper = sorted(set(upper_columns).difference(upper.columns))
    if missing_upper:
        raise ValueError(f"D0069 upper-bound table lacks fields: {missing_upper}")
    upper = upper[upper_columns].copy()
    if (
        len(observed) != len(qualifiers)
        or _pass_identities(observed) != _pass_identities(qualifiers)
        or len(upper) != len(unavailable)
        or _pass_identities(upper) != _pass_identities(unavailable)
    ):
        raise ValueError("D0069 weather output split changed a pass identity")
    return observed.reset_index(drop=True), upper.reset_index(drop=True)


def run_weather(workers: int) -> None:
    _require_resolved_new_archive()
    features, geometries = _domains()
    qualifiers = _geometry_qualifiers()
    unavailable = _new_unavailable_weather_population()
    weather_population = pd.concat(
        [qualifiers, unavailable], ignore_index=True, sort=False
    )
    hourly = _fetch_exact_weather(weather_population, geometries, workers)
    joined = _interpolate_weather_to_passes(weather_population, hourly)
    joined = _condition_labels(joined, features)
    observed, upper = _split_weather_outputs(joined, qualifiers, unavailable)
    if (
        observed.duplicated(["city", "orbit"]).any()
        or upper.duplicated(["city", "orbit"]).any()
        or not observed["exact_weather_complete"].all()
        or not upper["exact_weather_complete"].all()
    ):
        raise ValueError("D0069 split weather outputs are incomplete or duplicated")
    _atomic_csv(observed, WEATHER_PASS_SUMMARY)
    _atomic_csv(upper, UNAVAILABLE_CONDITION_PASS_SUMMARY)
    print(
        f"D0069 exact weather complete: {len(observed)} observed qualifiers + "
        f"{len(upper)} upper-bound-only unavailable passes",
        flush=True,
    )


def _final_geometry_reconstruction_inventory(geometry: pd.DataFrame) -> dict[str, Any]:
    checkpoint = load_checkpoint(PASS_CHECKPOINT)
    rows = []
    total_bytes = 0
    resolved = geometry.loc[
        geometry["geometry_azimuth_status"].astype(str).ne("RESOLVED_UNAVAILABLE")
    ]
    for summary in resolved.to_dict("records"):
        city, orbit = str(summary["city"]), int(summary["orbit"])
        item_id = f"{city}:{orbit:05d}"
        record = checkpoint.get(item_id, {})
        path = _reconstruction_path(city, orbit)
        if (
            not path.is_file()
            or summary.get("geometry_reconstruction_artifact_sha256") != sha256_file(path)
            or int(summary.get("geometry_reconstruction_artifact_size_bytes", -1))
            != path.stat().st_size
        ):
            raise ValueError(f"Geometry reconstruction artifact binding failed: {item_id}")
        if record.get("reuse_rule"):
            evidence_path = Path(str(record.get("source_path", "")))
            evidence_sha = str(record.get("source_sha256", ""))
        else:
            evidence_path = Path(str(record.get("evidence_path", "")))
            evidence_sha = str(record.get("evidence_sha256", ""))
        if not evidence_path.is_file() or evidence_sha != sha256_file(evidence_path):
            raise ValueError(f"Geometry pass evidence binding failed: {item_id}")
        document = json.loads(evidence_path.read_text(encoding="utf-8"))
        source_assets = []
        selected_chunk_inventory = []
        for scene in document.get("scene_evidence", []):
            inventory = scene.get("selected_compressed_chunk_hash_inventory", [])
            for item in inventory:
                selected_chunk_inventory.append(
                    {
                        "granule_id": str(scene.get("granule_id", "")),
                        "chunk_key": str(item.get("chunk_key", "")),
                        "sha256": str(item.get("sha256", "")),
                    }
                )
        binding = document.get("binding", {})
        for source in binding.get("scene_bindings", []):
            granule = str(source["granule_id"])
            dmrpp = (EXISTING_DMRPP / f"{granule}.h5.dmrpp")
            locator = (EXISTING_LOCATOR / f"{granule}_stride32.nc4")
            if not dmrpp.is_file():
                dmrpp = NEW_DMRPP / f"{granule}.h5.dmrpp"
                locator = NEW_LOCATOR / f"{granule}_stride32.nc4"
            if (
                not dmrpp.is_file()
                or not locator.is_file()
                or source.get("dmrpp_sha256") != sha256_file(dmrpp)
                or source.get("locator_sha256") != sha256_file(locator)
            ):
                raise ValueError(f"Geometry local scene metadata binding failed: {granule}")
            source_assets.append(
                {
                    "granule_id": granule,
                    "dmrpp_path": str(dmrpp.relative_to(ROOT)),
                    "dmrpp_sha256": sha256_file(dmrpp),
                    "locator_path": str(locator.relative_to(ROOT)),
                    "locator_sha256": sha256_file(locator),
                }
            )
        total_bytes += path.stat().st_size
        rows.append(
            {
                "city": city,
                "orbit": orbit,
                "path": str(path.relative_to(ROOT)),
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
                "n_domain_pixels": int(summary["n_domain_pixels"]),
                "n_valid_target_cells": int(summary["n_view_valid_pixels"]),
                "pass_evidence_path": str(evidence_path.relative_to(ROOT)),
                "pass_evidence_sha256": evidence_sha,
                "source_assets": source_assets,
                "selected_compressed_chunk_count": len(selected_chunk_inventory),
                "selected_compressed_chunk_hash_inventory": selected_chunk_inventory,
            }
        )
    if total_bytes > GEOMETRY_RECONSTRUCTION_MAX_BYTES:
        raise RuntimeError("Final geometry reconstruction inventory exceeds the 8 GiB guard")
    return {
        "format_version": GEOMETRY_RECONSTRUCTION_FORMAT,
        "pass_count": len(rows),
        "total_bytes": total_bytes,
        "maximum_bytes": GEOMETRY_RECONSTRUCTION_MAX_BYTES,
        "storage_guard_pass": total_bytes <= GEOMETRY_RECONSTRUCTION_MAX_BYTES,
        "raw_mapped_per_pixel_reconstruction_supported": True,
        "passes": rows,
    }


def finalize_summary() -> None:
    required_paths = (
        GEOMETRY_SUMMARY,
        CLOUD_MANIFEST,
        CLOUD_SUMMARY,
        HRRR_MANIFEST,
        HRRR_HOURLY_SUMMARY,
        HRRR_STORAGE_ESTIMATE,
        HRRR_STORAGE_PREFLIGHT,
        GEOMETRY_RECONSTRUCTION_PREFLIGHT,
        PASS_CHECKPOINT,
        WEATHER_PASS_SUMMARY,
        UNAVAILABLE_CONDITION_PASS_SUMMARY,
        DOMAINS_FILE,
        DOMAINS_FILE.with_suffix(DOMAINS_FILE.suffix + ".provenance.json"),
        NEW_SCENE_MANIFEST,
        NEW_L2T_MANIFEST,
        PROCESSED / "new_pass_archive_status.csv",
    )
    missing = [str(path) for path in required_paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"D0069 finalization lacks required artifacts: {missing}")
    _, repaired_geometries = _domains()
    _, _, links = _new_passes_and_targets()
    _validate_geo_manifest(
        pd.read_csv(NEW_SCENE_MANIFEST), links, require_provider_column=True
    )
    geometry = pd.read_csv(GEOMETRY_SUMMARY)
    cloud = pd.read_csv(CLOUD_SUMMARY)
    weather = pd.read_csv(WEATHER_PASS_SUMMARY)
    unavailable_weather = pd.read_csv(UNAVAILABLE_CONDITION_PASS_SUMMARY)
    cloud_manifest = pd.read_csv(CLOUD_MANIFEST)
    hrrr_manifest = pd.read_csv(HRRR_MANIFEST)
    hrrr_hourly = pd.read_csv(HRRR_HOURLY_SUMMARY)
    hrrr_estimate = pd.read_csv(HRRR_STORAGE_ESTIMATE)
    hrrr_preflight = json.loads(HRRR_STORAGE_PREFLIGHT.read_text(encoding="utf-8"))
    candidates, geometry_links, ledger = _geometry_population()
    geometry_sources = _scene_sources(geometry_links)
    geometry_link_groups = {
        (str(city), int(orbit)): group.sort_values("scene")
        for (city, orbit), group in geometry_links.groupby(["city", "orbit"], sort=True)
    }
    geometry_grids = _target_grids(repaired_geometries)
    geometry_fingerprints = {
        city: legacy_geometry._target_grid_fingerprint(city_grids)
        for city, city_grids in geometry_grids.items()
    }
    geometry_city_cells = {
        city: int(sum(grid.size for grid in city_grids.values()))
        for city, city_grids in geometry_grids.items()
    }
    geometry_resume_preflight = _validate_geometry_resume_preflight_payload(
        json.loads(GEOMETRY_RECONSTRUCTION_PREFLIGHT.read_text(encoding="utf-8")),
        candidates,
        load_checkpoint(PASS_CHECKPOINT),
        geometry_link_groups,
        geometry_sources,
        geometry_fingerprints,
        geometry_city_cells,
    )
    qualifiers = _geometry_qualifiers()
    unavailable = _new_unavailable_weather_population()
    weather_population = pd.concat([qualifiers, unavailable], ignore_index=True, sort=False)
    geometry_reconstruction_inventory = _final_geometry_reconstruction_inventory(geometry)
    expected_hrrr_manifest = _weather_manifest_for_population(
        weather_population, repaired_geometries
    )
    expected_bindings = {
        _canonical_sha256(_weather_request_binding(record))
        for record in expected_hrrr_manifest.to_dict("records")
    }
    observed_bindings = {
        _canonical_sha256(_weather_request_binding(record))
        for record in hrrr_manifest.to_dict("records")
    }
    expected_hour_city = {
        (city, pd.Timestamp(record["analysis_utc"]).isoformat())
        for record in hrrr_manifest.to_dict("records")
        for city in str(record["cities"]).split("|")
    }
    observed_hour_city = set(
        zip(
            hrrr_hourly["city"].astype(str),
            pd.to_datetime(
                hrrr_hourly["timestamp_utc"], utc=True, errors="raise", format="mixed"
            ).map(lambda value: value.isoformat()),
            strict=True,
        )
    )
    estimated_new_bytes = int(
        pd.to_numeric(
            hrrr_estimate["conservative_new_data_bytes"], errors="raise"
        ).sum()
    )
    if (
        len(geometry) != len(ledger)
        or _pass_identities(geometry) != _pass_identities(ledger)
        or _pass_identities(cloud) != _pass_identities(qualifiers)
        or _pass_identities(weather) != _pass_identities(qualifiers)
        or _pass_identities(unavailable_weather) != _pass_identities(unavailable)
        or cloud.duplicated(["city", "orbit"]).any()
        or weather.duplicated(["city", "orbit"]).any()
        or unavailable_weather.duplicated(["city", "orbit"]).any()
        or set(map(tuple, weather[["city", "orbit"]].to_records(index=False)))
        & set(map(tuple, unavailable_weather[["city", "orbit"]].to_records(index=False)))
        or observed_bindings != expected_bindings
        or observed_hour_city != expected_hour_city
        or hrrr_preflight.get("status") != "PASS"
        or hrrr_preflight.get("decision_id") != DECISION_ID
        or hrrr_preflight.get("weather_algorithm_version")
        != WEATHER_ALGORITHM_VERSION
        or int(hrrr_preflight.get("conservative_new_data_bytes", -1))
        != estimated_new_bytes
        or int(hrrr_preflight.get("explicit_reserve_bytes", -1))
        != HRRR_MIN_FREE_SPACE_RESERVE_BYTES
        or int(hrrr_preflight.get("required_free_bytes", -1))
        != estimated_new_bytes + HRRR_MIN_FREE_SPACE_RESERVE_BYTES
        or int(hrrr_preflight.get("observed_free_bytes", -1))
        < int(hrrr_preflight.get("required_free_bytes", 0))
        or hrrr_preflight.get("estimate_sha256") != sha256_file(HRRR_STORAGE_ESTIMATE)
    ):
        raise ValueError("D0069 final table/pass identity reconciliation failed")
    expected_cloud_keys = set(map(tuple, qualifiers[["city", "orbit"]].to_records(index=False)))
    observed_cloud_keys = set(
        map(tuple, cloud_manifest[["city", "orbit"]].drop_duplicates().to_records(index=False))
    )
    cloud_items = set(cloud_manifest["item_id"].astype(str))
    cloud_checkpoint = load_checkpoint(CLOUD_CHECKPOINT)
    if observed_cloud_keys != expected_cloud_keys or set(cloud_checkpoint) != cloud_items:
        raise ValueError("D0069 final cloud manifest/checkpoint census failed")
    for record in cloud_manifest.to_dict("records"):
        evidence = cloud_checkpoint.get(str(record["item_id"]), {})
        path = Path(str(evidence.get("local_path", "")))
        if not (
            evidence.get("status") == "complete"
            and path.is_file()
            and path.name == Path(str(record["file_name"])).name
            and evidence.get("sha256") == sha256_file(path)
            and int(evidence.get("size_bytes", -1)) == path.stat().st_size
        ):
            raise ValueError(f"D0069 final cloud source binding failed: {record['item_id']}")
    weather_checkpoint = load_checkpoint(HRRR_ROOT / "hrrr_checkpoint_d0069.json")
    if set(weather_checkpoint) != set(hrrr_manifest["item_id"].astype(str)):
        raise ValueError("D0069 final HRRR checkpoint census failed")
    for record in hrrr_manifest.to_dict("records"):
        item_id = str(record["item_id"])
        shard = HRRR_ROOT / "hourly_domain_cells" / f"{item_id}.csv.gz"
        if _valid_weather_shard(shard, record, weather_checkpoint[item_id]) is None:
            raise ValueError(f"D0069 final HRRR shard binding failed: {item_id}")
    forbidden_opened = False
    for frame in (geometry, cloud, weather, unavailable_weather):
        for column in ("temperature_or_lst_opened", "record_2026_opened"):
            if column not in frame:
                forbidden_opened = True
            else:
                forbidden_opened = forbidden_opened or frame[column].astype(
                    "string"
                ).str.casefold().ne("false").any()
    if (
        not geometry["decision_id"].astype(str).eq(DECISION_ID).all()
        or not cloud["decision_id"].astype(str).eq(DECISION_ID).all()
        or not weather["decision_id"].astype(str).eq(DECISION_ID).all()
        or not cloud["cloud_complete"].astype("string").str.casefold().eq("true").all()
        or not weather["exact_weather_complete"].astype("string").str.casefold().eq("true").all()
        or not unavailable_weather["exact_weather_complete"].astype("string").str.casefold().eq("true").all()
        or not unavailable_weather["archive_bound_role"].astype(str).eq(
            "UPPER_BOUND_ONLY_RESOLVED_UNAVAILABLE"
        ).all()
        or not unavailable_weather["archive_status"].astype(str).eq("RESOLVED_UNAVAILABLE").all()
        or not unavailable_weather["upper_bound_only"].astype("string").str.casefold().eq("true").all()
        or not unavailable_weather["geometry_observed"].astype("string").str.casefold().eq("false").all()
        or not unavailable_weather["cloud_observed"].astype("string").str.casefold().eq("false").all()
        or not unavailable_weather["selection_eligible_observation"].astype("string").str.casefold().eq("false").all()
        or weather[[
            "vpd_kpa_at_acquisition",
            "air_temperature_k_at_acquisition",
            "wind_speed_m_s_at_acquisition",
        ]].apply(pd.to_numeric, errors="coerce").isna().any().any()
        or unavailable_weather[[
            "vpd_kpa_at_acquisition",
            "air_temperature_k_at_acquisition",
            "wind_speed_m_s_at_acquisition",
            "demand_percentile",
            "antecedent_precipitation_30d_wetness_percentile",
        ]].apply(pd.to_numeric, errors="coerce").isna().any().any()
        or pd.to_datetime(geometry["acquisition_utc"], utc=True, errors="raise", format="mixed").dt.year.gt(2025).any()
        or pd.to_datetime(weather["acquisition_utc"], utc=True, errors="raise", format="mixed").dt.year.gt(2025).any()
        or pd.to_datetime(unavailable_weather["acquisition_utc"], utc=True, errors="raise", format="mixed").dt.year.gt(2025).any()
        or forbidden_opened
    ):
        raise ValueError("D0069 final status/year/nonthermal completeness seal failed")

    def identity_digest(frame: pd.DataFrame) -> str:
        return sha256_strings("|".join(map(str, identity)) for identity in sorted(_pass_identities(frame)))

    payload = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "decision_ids": [
            "D0065", "D0067", "D0069", "D0070", "D0071", "D0072", "D0075",
            "D0076", "D0077", "D0078", "D0079"
        ],
        "geometry_ledger_rows": len(geometry),
        "geometry_azimuth_complete_rows": int(
            geometry["geometry_azimuth_complete"].astype("string").str.casefold().eq("true").sum()
        ),
        "primary_threshold_geometry_qualifiers": len(weather),
        "cloud_complete_rows": int(cloud["cloud_complete"].astype("string").str.casefold().eq("true").sum()),
        "exact_weather_complete_rows": int(
            weather["exact_weather_complete"].astype("string").str.casefold().eq("true").sum()
        ),
        "upper_bound_only_condition_rows": len(unavailable_weather),
        "pass_identity_sha256": {
            "ledger": identity_digest(ledger),
            "geometry": identity_digest(geometry),
            "qualifiers": identity_digest(qualifiers),
            "cloud": identity_digest(cloud),
            "weather": identity_digest(weather),
            "unavailable_population": identity_digest(unavailable),
            "unavailable_weather": identity_digest(unavailable_weather),
            "weather_union": identity_digest(weather_population),
        },
        "source_bindings": {
            "collection_short_name": COLLECTION_SHORT_NAME,
            "collection_version": COLLECTION_VERSION,
            "collection_concept_id": COLLECTION_CONCEPT_ID,
            "provider": COLLECTION_PROVIDER,
            "hrrr_source": HRRR_SOURCE,
            "hrrr_temperature_dewpoint_search": TEMPERATURE_SEARCH,
            "hrrr_wind_search": WIND_SEARCH,
            "weather_algorithm_version": WEATHER_ALGORITHM_VERSION,
            "analysis_geometry_sha256_by_city": {
                city: sha256_json(repaired_geometries[city])
                for city in sorted(repaired_geometries)
            },
            "hrrr_storage_reserve_bytes": HRRR_MIN_FREE_SPACE_RESERVE_BYTES,
        },
        "geometry_reconstruction_inventory": geometry_reconstruction_inventory,
        "geometry_resume_preflight": geometry_resume_preflight,
        "artifacts": {
            str(path.relative_to(ROOT)): sha256_file(path)
            for path in required_paths
        },
        "temperature_or_lst_opened": False,
        "holdout_opened": False,
        "record_2026_opened": False,
        "record_2026_metadata_exposures_preserved": [
            "D0060", "D0061", "D0073", "D0074"
        ],
        "g3a_authorized": False,
        "gate4_authorized": False,
    }
    _atomic_json(payload, AUGMENTATION_SUMMARY)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage",
        choices=("prepare", "geometry", "cloud", "weather", "all", "finalize"),
        default="all",
    )
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.workers < 1:
        raise ValueError("workers must be positive")
    with _exclusive_run_lock(stage=args.stage):
        if args.stage in {"prepare", "all"}:
            prepare(args.workers)
        if args.stage in {"geometry", "all"}:
            run_geometry(args.workers)
        if args.stage in {"cloud", "all"}:
            run_cloud(args.workers)
        if args.stage in {"weather", "all"}:
            run_weather(args.workers)
        if args.stage in {"finalize", "all"}:
            finalize_summary()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
