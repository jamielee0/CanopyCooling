#!/usr/bin/env python3
"""Execute the frozen D0035 L1B GEO geometry and exhaustive-cloud remedy."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import threading
import time
from typing import Any, Mapping

import netCDF4
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in os.sys.path:
    os.sys.path.insert(0, str(ROOT / "src"))

from urban_cooling_v2.config import load_config
from urban_cooling_v2.domains import geometry_bbox, load_domain_features
from urban_cooling_v2.step02_cloud_exhaustive import (
    _summarize_cloud_without_view_mask,
    build_exhaustive_cloud_manifest,
    load_cached_l2t_results,
)
from urban_cooling_v2.step02_enrich import load_checkpoint, write_checkpoint
from urban_cooling_v2.step02_enrich_fetch import (
    CLOUD_COG,
    download_target_manifest_concurrent,
)
from urban_cooling_v2.step02_l1b_geometry import (
    BOUNDARY_GUARD_DISTANCE_M,
    DECISION_ID,
    EXPECTED_CITY_SCENE_LINKS,
    EXPECTED_METADATA_CANDIDATES,
    EXPECTED_UNIQUE_SCENES,
    GEOMETRY_VARIABLES,
    LOCATOR_INFLUENCE_M,
    LOCATOR_MARGIN_PIXELS,
    LOCATOR_STRIDE,
    MINIMUM_VIEW_COVERAGE,
    NEAR_NADIR_MAX_DEG,
    NO_OVERLAP_LOCATOR_EXPECTED_CELLS,
    NO_OVERLAP_LOCATOR_SHAPE,
    NO_OVERLAP_LOCATOR_UNCERTAINTY_M,
    NO_OVERLAP_MAX_UNSAMPLED_PATH_PIXELS,
    MAX_ADJACENT_SOURCE_DISPLACEMENT_M,
    RADIUS_OF_INFLUENCE_M,
    boundary_expansion_neighbors,
    build_canonical_target_grids,
    build_geometry_validation,
    decode_selected_chunks,
    frozen_geometry_targets,
    finalize_initial_selection_proof,
    initial_chunk_selection,
    initial_chunk_selection_with_proof,
    map_decoded_chunks_to_targets,
    normalize_geo_records,
    parse_dmrpp_chunks,
    resolve_latest_geo_scenes,
    sha256_file,
    sha256_strings,
)
from urban_cooling_v2.step02_live_manifest import cached_cmr_query
from urban_cooling_v2.step02_raster import partition_domain_for_mgrs_tile


PRE_CLOUD = ROOT / "data/processed/v2/task1/step2_quality_screening/passes_quality_screened_pre_cloud.csv"
VIEW_MANIFEST = ROOT / "data/raw/v2/ecostress/view_candidate_manifest_latest.csv"
L2T_CACHE = ROOT / "data/raw/v2/ecostress/enrichment_cmr_cache/l2t"
DOMAIN_FILE = ROOT / "data/raw/v2/domains/census_urban_areas.geojson"
DENOMINATORS = ROOT / "data/processed/v2/task1/step2_quality_screening/domain_pixel_denominators.csv"
ASSET_ROOT = ROOT / "data/raw/v2/ecostress/enrichment_assets"

RAW_ROOT = ROOT / "data/raw/v2/ecostress/l1b_geo_geometry_D0035"
CMR_CACHE = RAW_ROOT / "cmr"
DMRPP_DIR = RAW_ROOT / "dmrpp"
LOCATOR_DIR = RAW_ROOT / "locator_stride32"
PASS_EVIDENCE_DIR = RAW_ROOT / "pass_evidence"
SCENE_MANIFEST = RAW_ROOT / "l1b_geo_scene_manifest.csv"
ASSET_CHECKPOINT = RAW_ROOT / "locator_dmrpp_checkpoint.json"
GEOMETRY_CHECKPOINT = RAW_ROOT / "geometry_scene_checkpoint.json"
OLD_DMRPP_DIR = ASSET_ROOT / "l1b_geo_dmrpp"

CLOUD_MANIFEST = ROOT / "data/raw/v2/ecostress/enrichment_manifest_cloud_l1b_geo_D0035.csv"
CLOUD_CHECKPOINT = ASSET_ROOT / "cloud_l1b_geo_D0035_checkpoint.json"
SHARED_CLOUD_CHECKPOINTS = (
    ASSET_ROOT / "cloud_exhaustive_checkpoint.json",
    ASSET_ROOT / "enrichment_checkpoint.json",
)

OUTPUT_DIR = ROOT / "data/processed/v2/task1/step2_quality_screening_l1b_geo"
GEOMETRY_SUMMARY = OUTPUT_DIR / "geometry_pass_summary.csv"
PRE_CLOUD_L1B = OUTPUT_DIR / "passes_quality_screened_pre_cloud_geometry_only.csv"
GEOMETRY_VALIDATION_JSON = OUTPUT_DIR / "geometry_validation.json"
GEOMETRY_VALIDATION_CSV = OUTPUT_DIR / "geometry_validation.csv"
CLOUD_SUMMARY = OUTPUT_DIR / "cloud_pass_summary.csv"
FINAL_TABLE = OUTPUT_DIR / "passes_quality_screened_l1b_geo.csv"
COMBINED_VALIDATION_JSON = OUTPUT_DIR / "combined_validation.json"
COMBINED_VALIDATION_CSV = OUTPUT_DIR / "combined_validation.csv"
RUN_RECORD = OUTPUT_DIR / "run_record.json"

MAX_SELECTED_CHUNKS_PER_SCENE = 512
MAX_RANGE_BYTES_PER_SCENE = 256 * 1024 * 1024
MIN_FREE_DISK_RESERVE_BYTES = 5 * 1024 * 1024 * 1024
LOCATOR_VARIABLES = ("latitude", "longitude")
D0035_ALGORITHM_VERSION = "d0035-l1b-dmrpp-pass-stream-v4"
IMPLEMENTATION_DECISION_ID = "D0036"
COLLECTION_CONCEPT_ID = "C2076087338-LPCLOUD"

# The netCDF-C/HDF5 stack used by netCDF4 is not reliably thread-safe in this
# environment.  Geometry workers may still overlap authenticated range reads
# and numerical mapping, but locator-file opens are serialized to prevent a
# native-process crash when several cached NetCDF files are inspected at once.
_NETCDF4_IO_LOCK = threading.Lock()


def _require_free_disk(label: str, projected_new_bytes: int) -> None:
    free = int(shutil.disk_usage(RAW_ROOT.parent).free)
    required = int(projected_new_bytes) + MIN_FREE_DISK_RESERVE_BYTES
    if free < required:
        raise RuntimeError(
            f"Insufficient disk for {label}: free={free:,}, required={required:,}"
        )
    print(
        f"D0035 disk preflight ({label}): free {free:,}; projected new "
        f"{int(projected_new_bytes):,}; reserve {MIN_FREE_DISK_RESERVE_BYTES:,}",
        flush=True,
    )


def _target_grid_fingerprint(grids: Mapping[str, Any]) -> str:
    digest = hashlib.sha256()
    for tile, grid in sorted(grids.items()):
        digest.update(str(tile).encode())
        digest.update(grid.crs.to_wkt().encode())
        digest.update(np.asarray(grid.x, dtype="<f8").tobytes())
        digest.update(np.asarray(grid.y, dtype="<f8").tobytes())
        geometry = grid.domain_geometry_projected
        digest.update(geometry.wkb if geometry is not None else b"no-domain-geometry")
    return digest.hexdigest()


def _d0048_geometry_binding_fields() -> dict[str, Any]:
    """Return the exact D0048 mechanics sealed into every pass binding."""

    return {
        "implementation_decision_id": "D0048",
        "verified_no_overlap_locator_shape": list(NO_OVERLAP_LOCATOR_SHAPE),
        "verified_no_overlap_locator_expected_cells": (
            NO_OVERLAP_LOCATOR_EXPECTED_CELLS
        ),
        "verified_no_overlap_locator_stride": LOCATOR_STRIDE,
        "verified_no_overlap_locator_stride_minus_one_pixels": LOCATOR_STRIDE - 1,
        "verified_no_overlap_locator_influence_m": LOCATOR_INFLUENCE_M,
        "verified_no_overlap_max_unsampled_path_pixels": (
            NO_OVERLAP_MAX_UNSAMPLED_PATH_PIXELS
        ),
        "verified_no_overlap_maximum_adjacent_source_displacement_m": (
            MAX_ADJACENT_SOURCE_DISPLACEMENT_M
        ),
        "verified_no_overlap_locator_uncertainty_m": (
            NO_OVERLAP_LOCATOR_UNCERTAINTY_M
        ),
        "verified_no_overlap_boundary_guard_m": BOUNDARY_GUARD_DISTANCE_M,
        "verified_no_overlap_source_margin_pixels": LOCATOR_MARGIN_PIXELS,
        "verified_no_overlap_tie_break_rule": "row_major_lowest_flat_index",
    }


def _validate_config_seal(config: Any) -> None:
    frozen = {
        "geometry_remediation_decision_id": DECISION_ID,
        "geometry_remediation_collection_concept_id": COLLECTION_CONCEPT_ID,
        "geometry_remediation_expected_metadata_candidates": EXPECTED_METADATA_CANDIDATES,
        "geometry_remediation_expected_city_scene_references": EXPECTED_CITY_SCENE_LINKS,
        "geometry_remediation_expected_unique_l1b_scene_assets": EXPECTED_UNIQUE_SCENES,
        "geometry_remediation_locator_stride": LOCATOR_STRIDE,
        "geometry_remediation_locator_margin_pixels": LOCATOR_MARGIN_PIXELS,
        "geometry_remediation_minimum_view_coverage_fraction": MINIMUM_VIEW_COVERAGE,
        "geometry_remediation_max_view_zenith_p95_deg": NEAR_NADIR_MAX_DEG,
    }
    observed = config.ecostress
    mismatches = [
        key for key, expected in frozen.items() if observed.get(key) != expected
    ]
    if mismatches:
        raise ValueError(
            "D0035 execution/config seal mismatch: " + ", ".join(sorted(mismatches))
        )


def _atomic_json(value: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, indent=2, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


def _atomic_csv(table: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    table.to_csv(temporary, index=False)
    temporary.replace(path)


def _load_dotenv_without_overwrite(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _earthaccess() -> tuple[Any, Any]:
    _load_dotenv_without_overwrite(ROOT / ".env")
    import earthaccess

    has_environment = bool(
        os.environ.get("EARTHDATA_TOKEN")
        or (os.environ.get("EARTHDATA_USERNAME") and os.environ.get("EARTHDATA_PASSWORD"))
    )
    strategy = "environment" if has_environment else "netrc"
    auth = earthaccess.login(strategy=strategy)
    if not getattr(auth, "authenticated", False):
        raise RuntimeError("Earthdata authentication was not established")
    return earthaccess, auth


def _mapping(result: Any) -> dict[str, Any]:
    if isinstance(result, Mapping):
        return dict(result)
    data = getattr(result, "data", None)
    if isinstance(data, Mapping):
        return dict(data)
    raise TypeError("CMR result must be mapping-like")


def _read_cache_results(paths: list[Path]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for path in paths:
        document = json.loads(path.read_text(encoding="utf-8"))
        results = document.get("results")
        if not isinstance(results, list):
            raise ValueError(f"Malformed CMR cache {path}")
        output.extend(dict(record) for record in results)
    return output


def _exact_scene_query(orbit: int, scene: int) -> dict[str, Any]:
    return {
        "short_name": "ECO_L1B_GEO",
        "version": "002",
        "provider": "LPCLOUD",
        "granule_name": f"ECOv002_L1B_GEO_{int(orbit):05d}_{int(scene):03d}_*",
        "count": -1,
    }


def _decorate_scene_manifest(
    links: pd.DataFrame,
    results: list[dict[str, Any]],
    *,
    query_failures: Mapping[tuple[int, int], str] | None = None,
) -> pd.DataFrame:
    records = normalize_geo_records(results)
    manifest = resolve_latest_geo_scenes(links, records)
    failures = dict(query_failures or {})
    manifest["cmr_query_error_type"] = [
        failures.get((int(orbit), int(scene)), "")
        for orbit, scene in manifest[["orbit", "scene"]].itertuples(index=False)
    ]
    city_sets = (
        links.groupby(["orbit", "scene"], sort=True)["city"]
        .agg(lambda values: ";".join(sorted(set(map(str, values)))))
        .rename("cities")
        .reset_index()
    )
    manifest = manifest.merge(city_sets, on=["orbit", "scene"], validate="one_to_one")
    manifest["decision_id"] = DECISION_ID
    manifest["collection_short_name"] = "ECO_L1B_GEO"
    manifest["collection_version"] = "002"
    manifest["target_scope"] = "all_942_metadata_candidates_2018_2025"
    manifest["lst_opened"] = False
    manifest["record_2026_opened"] = False
    if len(manifest) != EXPECTED_UNIQUE_SCENES:
        raise ValueError("D0035 scene manifest does not have exactly 1,370 rows")
    _atomic_csv(manifest, SCENE_MANIFEST)
    return manifest


def _rebuild_scene_manifest_from_exact_cache(links: pd.DataFrame) -> pd.DataFrame:
    """Re-resolve latest GEO identities from every immutable exact-query cache."""

    keys = sorted(
        set(map(tuple, links[["orbit", "scene"]].drop_duplicates().to_records(index=False)))
    )
    results: list[dict[str, Any]] = []
    failures: dict[tuple[int, int], str] = {}
    for raw_orbit, raw_scene in keys:
        orbit, scene = int(raw_orbit), int(raw_scene)
        path = CMR_CACHE / "by_scene" / f"{orbit:05d}_{scene:03d}.json"
        if not path.is_file():
            failures[(orbit, scene)] = "MissingExactQueryCache"
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            if document.get("query") != _exact_scene_query(orbit, scene):
                raise ValueError("exact query mismatch")
            cached_results = document.get("results")
            if not isinstance(cached_results, list):
                raise ValueError("malformed result list")
            results.extend(dict(record) for record in cached_results)
        except Exception as exc:
            failures[(orbit, scene)] = type(exc).__name__
    return _decorate_scene_manifest(links, results, query_failures=failures)


def _prepare_scene_manifest(
    candidates: pd.DataFrame,
    links: pd.DataFrame,
    *,
    search_data: Any,
    domain_geometries: Mapping[str, Mapping[str, Any]],
    max_workers: int,
) -> pd.DataFrame:
    """Resolve the 1,370 exact latest GEO.002 scene identities via CMR.

    Every query is keyed by an already-sealed L2T orbit/scene reference.  A
    spatial L1B search is intentionally prohibited because a tiled footprint
    can intersect a domain even when the L1B catalogue footprint does not.
    """

    expected = sorted(
        set(map(tuple, links[["orbit", "scene"]].drop_duplicates().to_records(index=False)))
    )
    if len(expected) != EXPECTED_UNIQUE_SCENES:
        raise ValueError("Exact L2T-derived scene reference count changed")

    def query_scene(key: tuple[int, int]) -> list[dict[str, Any]]:
        orbit, scene = map(int, key)
        query = _exact_scene_query(orbit, scene)
        return cached_cmr_query(
            CMR_CACHE / "by_scene" / f"{orbit:05d}_{scene:03d}.json",
            search_data=search_data,
            query=query,
        )

    results: list[dict[str, Any]] = []
    failures: list[tuple[tuple[int, int], str]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(query_scene, key): key for key in expected}
        for future in as_completed(futures):
            key = futures[future]
            try:
                results.extend(future.result())
            except Exception as exc:
                failures.append((key, type(exc).__name__))
    query_failures = {
        (int(orbit), int(scene)): kind for (orbit, scene), kind in failures
    }
    manifest = _decorate_scene_manifest(
        links, results, query_failures=query_failures
    )
    if failures:
        preview = ", ".join(f"{key}:{kind}" for key, kind in failures[:8])
        print(
            f"D0035 exact CMR census retained {len(failures)} failed queries as "
            f"explicit missing rows ({preview})",
            flush=True,
        )
    return manifest


def _validate_scene_manifest_identity(
    manifest: pd.DataFrame, links: pd.DataFrame
) -> None:
    required = {
        "orbit",
        "scene",
        "status",
        "decision_id",
        "collection_short_name",
        "collection_version",
        "collection_concept_id",
    }
    missing = sorted(required.difference(manifest.columns))
    if missing:
        raise ValueError(f"D0035 scene manifest lacks columns: {missing}")
    expected = set(
        map(
            tuple,
            links[["orbit", "scene"]]
            .drop_duplicates()
            .astype({"orbit": int, "scene": int})
            .to_records(index=False),
        )
    )
    observed = set(
        map(
            tuple,
            manifest[["orbit", "scene"]]
            .astype({"orbit": int, "scene": int})
            .to_records(index=False),
        )
    )
    valid = bool(
        len(manifest) == EXPECTED_UNIQUE_SCENES
        and not manifest.duplicated(["orbit", "scene"]).any()
        and observed == expected
        and manifest["decision_id"].astype(str).eq(DECISION_ID).all()
        and manifest["collection_short_name"].astype(str).eq("ECO_L1B_GEO").all()
        and manifest["collection_version"].astype(str).str.zfill(3).eq("002").all()
        and manifest["status"]
        .astype(str)
        .isin(["available", "missing", "missing_required_endpoint"])
        .all()
    )
    if not valid:
        raise ValueError("Cached D0035 scene manifest identity seal failed")
    available = manifest["status"].astype(str).eq("available")
    if available.any():
        if not manifest.loc[available, "collection_concept_id"].astype(str).eq(
            COLLECTION_CONCEPT_ID
        ).all():
            raise ValueError("D0035 scene is not bound to the frozen collection concept")
        for column in (
            "granule_id",
            "opendap_url",
            "hdf_url",
            "dmrpp_url",
            "cmr_record_sha256",
        ):
            if column not in manifest or manifest.loc[available, column].isna().any():
                raise ValueError(f"Available D0035 scene lacks {column}")
        if not manifest.loc[available, "cmr_record_sha256"].astype(str).str.fullmatch(
            r"[0-9a-f]{64}"
        ).all():
            raise ValueError("Available D0035 scene has an invalid CMR digest")


def _validate_geometry_identity(
    summary: pd.DataFrame, candidates: pd.DataFrame
) -> None:
    required = {"city", "orbit", "acquisition_utc"}
    missing = sorted(required.difference(summary.columns))
    if missing:
        raise ValueError(f"D0035 geometry summary lacks identity columns: {missing}")

    def identities(table: pd.DataFrame) -> set[tuple[str, int, str]]:
        stamps = pd.to_datetime(
            table["acquisition_utc"], errors="raise", utc=True, format="mixed"
        ).map(lambda value: value.isoformat())
        return set(
            zip(
                table["city"].astype(str),
                pd.to_numeric(table["orbit"], errors="raise").astype(int),
                stamps,
                strict=True,
            )
        )

    if (
        len(summary) != EXPECTED_METADATA_CANDIDATES
        or summary.duplicated(["city", "orbit"]).any()
        or identities(summary) != identities(candidates)
    ):
        raise ValueError("D0035 geometry summary does not exactly equal frozen pass keys")


def _get_file(
    session: Any,
    url: str,
    destination: Path,
    *,
    item_id: str,
    max_bytes: int,
    params: Mapping[str, Any] | None = None,
    timeout: tuple[float, float] = (30, 240),
) -> tuple[int, str]:
    if destination.is_file():
        return destination.stat().st_size, sha256_file(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.part")
    last_kind = "unknown"
    for attempt in range(5):
        response = None
        try:
            response = session.get(url, params=params, stream=True, timeout=timeout)
            status = int(response.status_code)
            if status != 200:
                last_kind = f"HTTP_{status}"
                if status in {429, 500, 502, 503, 504}:
                    time.sleep(min(2**attempt, 16))
                    continue
                raise RuntimeError(f"HTTP status {status} for {item_id}")
            total = 0
            with temporary.open("wb") as handle:
                for block in response.iter_content(chunk_size=1024 * 1024):
                    if not block:
                        continue
                    total += len(block)
                    if total > max_bytes:
                        raise RuntimeError(f"Response exceeds byte limit for {item_id}")
                    handle.write(block)
            if total == 0:
                raise RuntimeError(f"Empty response for {item_id}")
            temporary.replace(destination)
            return total, sha256_file(destination)
        except RuntimeError:
            raise
        except Exception as exc:
            last_kind = type(exc).__name__
            if attempt == 4:
                break
            time.sleep(min(2**attempt, 16))
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
    raise RuntimeError(f"Download failed for {item_id}: {last_kind}")


def _locator_constraint() -> str:
    slices = "[0:32:5631][0:32:5399]"
    return ";".join(
        f"/Geolocation/{name}{slices}" for name in LOCATOR_VARIABLES
    )


def _validate_locator(path: Path) -> None:
    with _NETCDF4_IO_LOCK:
        with netCDF4.Dataset(path) as dataset:
            if set(dataset.groups) != {"Geolocation"}:
                raise ValueError("Locator NetCDF contains an unexpected group set")
            group = dataset.groups["Geolocation"]
            if set(group.variables) != set(LOCATOR_VARIABLES):
                raise ValueError(
                    "Locator NetCDF contains a forbidden or missing variable"
                )
            expected = (176, 169)
            for name in LOCATOR_VARIABLES:
                if tuple(group.variables[name].shape) != expected:
                    raise ValueError(f"Unexpected locator shape for {name}")


def _seed_old_dmrpp(granule_id: str, destination: Path) -> bool:
    source = OLD_DMRPP_DIR / f"{granule_id}.h5.dmrpp"
    if not source.is_file() or destination.exists():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)
    return True


def _fetch_metadata_assets(
    manifest: pd.DataFrame,
    *,
    session_factory: Any,
    max_workers: int,
) -> None:
    target_granules = set(manifest["granule_id"].astype(str))
    checkpoint = {
        key: value
        for key, value in load_checkpoint(ASSET_CHECKPOINT).items()
        if key in target_granules
    }
    lock = threading.Lock()
    local = threading.local()

    def worker(row: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        granule = str(row["granule_id"])
        dmrpp = DMRPP_DIR / f"{granule}.h5.dmrpp"
        locator = LOCATOR_DIR / f"{granule}_stride32.nc4"
        existing = checkpoint.get(granule, {})
        cmr_bound = bool(
            existing.get("status") == "complete"
            and existing.get("cmr_record_sha256") == str(row["cmr_record_sha256"])
            and existing.get("collection_concept_id") == COLLECTION_CONCEPT_ID
        )
        if (
            cmr_bound
            and existing.get("algorithm_version") == D0035_ALGORITHM_VERSION
            and tuple(existing.get("locator_variables", ())) == LOCATOR_VARIABLES
            and dmrpp.is_file()
            and locator.is_file()
            and existing.get("dmrpp_sha256") == sha256_file(dmrpp)
            and existing.get("locator_sha256") == sha256_file(locator)
        ):
            _validate_locator(locator)
            return granule, dict(existing)
        if dmrpp.is_file() and (
            not cmr_bound or existing.get("dmrpp_sha256") != sha256_file(dmrpp)
        ):
            dmrpp.unlink()
        if locator.is_file():
            try:
                _validate_locator(locator)
            except (OSError, ValueError):
                # A pre-v4 locator contains stride-32 view_zenith and is not
                # authorized by D0035.  Replace only that cache object.
                locator.unlink()
            else:
                if (
                    not cmr_bound
                    or existing.get("locator_sha256") != sha256_file(locator)
                ):
                    locator.unlink()
        if not hasattr(local, "session"):
            local.session = session_factory()
        _seed_old_dmrpp(granule, dmrpp)
        dmrpp_bytes, dmrpp_hash = _get_file(
            local.session,
            str(row["dmrpp_url"]),
            dmrpp,
            item_id=f"{granule}:dmrpp",
            max_bytes=16 * 1024 * 1024,
        )
        parse_dmrpp_chunks(dmrpp)
        locator_bytes, locator_hash = _get_file(
            local.session,
            str(row["opendap_url"]) + ".dap.nc4",
            locator,
            item_id=f"{granule}:locator",
            max_bytes=8 * 1024 * 1024,
            params={"dap4.ce": _locator_constraint()},
        )
        _validate_locator(locator)
        return granule, {
            "status": "complete",
            "dmrpp_path": str(dmrpp),
            "dmrpp_size_bytes": dmrpp_bytes,
            "dmrpp_sha256": dmrpp_hash,
            "locator_path": str(locator),
            "locator_size_bytes": locator_bytes,
            "locator_sha256": locator_hash,
            "variables": list(GEOMETRY_VARIABLES),
            "locator_variables": list(LOCATOR_VARIABLES),
            "decision_id": DECISION_ID,
            "cmr_record_sha256": str(row["cmr_record_sha256"]),
            "collection_concept_id": COLLECTION_CONCEPT_ID,
            "algorithm_version": D0035_ALGORITHM_VERSION,
        }

    rows = manifest.sort_values(["orbit", "scene"]).to_dict("records")
    completed = 0
    for start in range(0, len(rows), 50):
        failures: list[tuple[str, str]] = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(worker, row): row for row in rows[start : start + 50]}
            for future in as_completed(futures):
                row = futures[future]
                try:
                    granule, record = future.result()
                    with lock:
                        checkpoint[granule] = record
                    completed += 1
                except Exception as exc:
                    failures.append((str(row["granule_id"]), type(exc).__name__))
        write_checkpoint(ASSET_CHECKPOINT, checkpoint)
        print(
            f"D0035 locator/DMR++ assets: {completed}/{len(rows)} processed",
            flush=True,
        )
        if failures:
            preview = ", ".join(f"{item}:{kind}" for item, kind in failures[:8])
            raise RuntimeError(f"{len(failures)} locator/DMR++ fetches failed: {preview}")


def _validated_asset_bindings(
    manifest: pd.DataFrame,
) -> dict[str, dict[str, Any]]:
    """Re-hash every local locator/DMR++ file before checkpoint reuse."""

    checkpoint = load_checkpoint(ASSET_CHECKPOINT)
    expected_granules = set(manifest["granule_id"].astype(str))
    if set(checkpoint) != expected_granules:
        raise RuntimeError("D0035 metadata-asset checkpoint key census is not exact")
    output: dict[str, dict[str, Any]] = {}
    for row in manifest.to_dict("records"):
        granule = str(row["granule_id"])
        record = checkpoint.get(granule, {})
        dmrpp = DMRPP_DIR / f"{granule}.h5.dmrpp"
        locator = LOCATOR_DIR / f"{granule}_stride32.nc4"
        dmrpp_hash = sha256_file(dmrpp) if dmrpp.is_file() else ""
        locator_hash = sha256_file(locator) if locator.is_file() else ""
        valid = bool(
            record.get("status") == "complete"
            and record.get("algorithm_version") == D0035_ALGORITHM_VERSION
            and record.get("cmr_record_sha256") == str(row["cmr_record_sha256"])
            and record.get("collection_concept_id") == COLLECTION_CONCEPT_ID
            and tuple(record.get("locator_variables", ())) == LOCATOR_VARIABLES
            and record.get("dmrpp_sha256") == dmrpp_hash
            and record.get("locator_sha256") == locator_hash
            and len(dmrpp_hash) == 64
            and len(locator_hash) == 64
        )
        if not valid:
            raise RuntimeError(f"D0035 metadata-asset binding is stale for {granule}")
        _validate_locator(locator)
        output[granule] = {
            "cmr_record_sha256": str(row["cmr_record_sha256"]),
            "collection_concept_id": COLLECTION_CONCEPT_ID,
            "dmrpp_sha256": dmrpp_hash,
            "locator_sha256": locator_hash,
            "dmrpp_size_bytes": dmrpp.stat().st_size,
            "locator_size_bytes": locator.stat().st_size,
            "locator_variables": list(LOCATOR_VARIABLES),
            "algorithm_version": D0035_ALGORITHM_VERSION,
        }
    if len(output) != EXPECTED_UNIQUE_SCENES:
        raise RuntimeError("D0035 metadata-asset binding census is incomplete")
    return output


class _RangeFetcher:
    def __init__(
        self,
        session: Any,
        hdf_url: str,
        scene_id: str,
        *,
        max_total_bytes: int = MAX_RANGE_BYTES_PER_SCENE,
        refresh_session: Any | None = None,
    ):
        self.session = session
        self.hdf_url = hdf_url
        self.scene_id = scene_id
        self.n_requests = 0
        self.n_bytes = 0
        self.range_evidence: list[str] = []
        self.object_size_bytes: int | None = None
        self.object_validator: str | None = None
        self.max_total_bytes = int(max_total_bytes)
        self._refresh_session = refresh_session
        self.session_refresh_count = 0

    def __call__(self, start: int, end: int) -> bytes:
        expected = end - start + 1
        if expected <= 0 or expected > 16 * 1024 * 1024:
            raise RuntimeError(f"Unsafe range size for {self.scene_id}")
        if self.n_bytes + expected > self.max_total_bytes:
            raise RuntimeError(f"Scene range-byte guard exceeded for {self.scene_id}")
        request_headers = {
            "Range": f"bytes={start}-{end}",
            "Accept-Encoding": "identity",
        }
        last_kind = "unknown"
        for attempt in range(6):
            response = None
            try:
                response = self.session.get(
                    self.hdf_url,
                    headers=request_headers,
                    timeout=(30, 240),
                )
                status = int(response.status_code)
                if status in {401, 403}:
                    if self._refresh_session is None or self.session_refresh_count:
                        raise RuntimeError(
                            f"Range status {status} for {self.scene_id}"
                        )
                    close = getattr(response, "close", None)
                    if callable(close):
                        close()
                    response = None
                    # The callback is attempted at most once for this scene,
                    # even when session creation itself fails.  Retrying here
                    # keeps authentication repair separate from the existing
                    # transient-transport retry budget and repeats the exact
                    # URL, byte range, encoding request, and timeout.
                    self.session_refresh_count = 1
                    try:
                        refreshed = self._refresh_session()
                    except Exception as exc:
                        raise RuntimeError(
                            f"Authenticated session refresh failed for {self.scene_id}"
                        ) from exc
                    if refreshed is None:
                        raise RuntimeError(
                            f"Authenticated session refresh failed for {self.scene_id}"
                        )
                    self.session = refreshed
                    response = self.session.get(
                        self.hdf_url,
                        headers=request_headers,
                        timeout=(30, 240),
                    )
                    status = int(response.status_code)
                if status != 206:
                    last_kind = f"HTTP_{status}"
                    if status in {429, 500, 502, 503, 504}:
                        time.sleep(min(2**attempt, 20))
                        continue
                    raise RuntimeError(f"Range status {status} for {self.scene_id}")
                encoding = str(response.headers.get("Content-Encoding", "")).strip().casefold()
                if encoding not in {"", "identity"}:
                    raise RuntimeError(f"Encoded range response for {self.scene_id}")
                payload = bytes(response.content)
                content_range = str(response.headers.get("Content-Range", ""))
                match = re.fullmatch(
                    rf"bytes {start}-{end}/(?P<total>[1-9][0-9]*)",
                    content_range.strip(),
                    flags=re.IGNORECASE,
                )
                if len(payload) != expected or match is None:
                    raise RuntimeError(f"Invalid range response for {self.scene_id}")
                total = int(match.group("total"))
                if total <= end:
                    raise RuntimeError(f"Invalid HDF object size for {self.scene_id}")
                version_id = str(response.headers.get("x-amz-version-id", "")).strip()
                etag = str(response.headers.get("ETag", "")).strip()
                validator = f"version:{version_id}" if version_id else f"etag:{etag}"
                if validator in {"version:", "etag:"}:
                    raise RuntimeError(f"HDF object lacks an immutable validator for {self.scene_id}")
                if self.object_size_bytes is None:
                    self.object_size_bytes = total
                    self.object_validator = validator
                elif total != self.object_size_bytes or validator != self.object_validator:
                    raise RuntimeError(f"HDF object changed during range reads for {self.scene_id}")
                self.n_requests += 1
                self.n_bytes += len(payload)
                self.range_evidence.append(
                    f"{start}:{end}:{hashlib.sha256(payload).hexdigest()}"
                )
                return payload
            except RuntimeError:
                raise
            except Exception as exc:
                last_kind = type(exc).__name__
                if attempt == 5:
                    break
                time.sleep(min(2**attempt, 20))
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
        raise RuntimeError(f"Range fetch failed for {self.scene_id}: {last_kind}")


def _read_locator(path: Path) -> tuple[np.ndarray, np.ndarray]:
    with _NETCDF4_IO_LOCK:
        with netCDF4.Dataset(path) as dataset:
            group = dataset.groups["Geolocation"]
            latitude = np.asarray(
                np.ma.asarray(group.variables["latitude"][:]).filled(np.nan),
                dtype=float,
            )
            longitude = np.asarray(
                np.ma.asarray(group.variables["longitude"][:]).filled(np.nan),
                dtype=float,
            )
    return latitude, longitude


def _scene_boundary_evidence_valid(item: Mapping[str, Any]) -> bool:
    """Validate one completed scene proof, including D0048 empty mappings."""

    if item.get("boundary_verified") is not True:
        return False
    # D0049 is transport-only and therefore is not part of the scientific
    # binding.  Newly written evidence records the optional refresh count,
    # while completed pre-D0049 evidence remains valid when the field is
    # absent.
    if "session_refresh_count" in item:
        refresh_count = item["session_refresh_count"]
        if (
            isinstance(refresh_count, bool)
            or not isinstance(refresh_count, (int, np.integer))
            or int(refresh_count) not in {0, 1}
        ):
            return False
    if IMPLEMENTATION_DECISION_ID != "D0048":
        return True
    try:
        common = bool(
            item.get("full_resolution_boundary_verified") is True
            and item.get("locator_shape") == list(NO_OVERLAP_LOCATOR_SHAPE)
            and int(item.get("locator_expected_count", -1))
            == NO_OVERLAP_LOCATOR_EXPECTED_CELLS
            and 0 <= int(item.get("locator_valid_count", -1))
            <= NO_OVERLAP_LOCATOR_EXPECTED_CELLS
            and int(item.get("locator_stride", -1)) == LOCATOR_STRIDE
            and int(item.get("locator_stride_minus_one_pixels", -1))
            == LOCATOR_STRIDE - 1
            and float(item.get("locator_influence_m", math.nan))
            == LOCATOR_INFLUENCE_M
            and int(item.get("locator_max_unsampled_path_pixels", -1))
            == NO_OVERLAP_MAX_UNSAMPLED_PATH_PIXELS
            and float(item.get("maximum_adjacent_source_displacement_m", math.nan))
            == MAX_ADJACENT_SOURCE_DISPLACEMENT_M
            and float(item.get("locator_uncertainty_bound_m", math.nan))
            == NO_OVERLAP_LOCATOR_UNCERTAINTY_M
            and float(item.get("boundary_guard_distance_m", math.nan))
            == BOUNDARY_GUARD_DISTANCE_M
            and int(item.get("seed_source_margin_pixels", -1))
            == LOCATOR_MARGIN_PIXELS
            and item.get("row_major_tie_breaking") is True
            and item.get("verified_no_overlap_zero_imputed") is False
            and item.get("missing_scene_zero_coverage_assigned") is False
            and item.get("missing_scene_substitution_used") is False
        )
    except (TypeError, ValueError):
        return False
    if not common:
        return False
    mode = item.get("proof_mode")
    if mode == "locator_near_domain":
        try:
            return bool(
                item.get("proof_status") == "near_domain_full_resolution_verified"
                and item.get("proof_acceptance_status")
                == "ordinary_near_domain_mapping"
                and item.get("geometry_observation_status")
                == "mapped_near_domain_geometry"
                and isinstance(item.get("seeded_chunk_coords"), list)
                and int(item.get("seeded_chunk_count", -1))
                == len(item.get("seeded_chunk_coords", []))
                and int(item.get("mapped_target_cell_count", -1)) >= 0
            )
        except (TypeError, ValueError):
            return False
    if mode != "verified_no_overlap":
        return False
    try:
        minimum = float(item["locator_minimum_domain_distance_m"])
        lower = float(item["locator_no_overlap_lower_bound_m"])
        seeded_points = item["seeded_locator_points"]
        seeded_chunks = item["seeded_chunk_coords"]
        return bool(
            item.get("proof_status") == "verified_no_domain_overlap"
            and item.get("proof_acceptance_status")
            == "verified_no_overlap_mapped_zero"
            and item.get("geometry_observation_status")
            == "verified_no_domain_overlap"
            and int(item.get("locator_valid_count", -1))
            == NO_OVERLAP_LOCATOR_EXPECTED_CELLS
            and math.isfinite(minimum)
            and math.isfinite(lower)
            and math.isclose(
                lower,
                minimum - NO_OVERLAP_LOCATOR_UNCERTAINTY_M,
                rel_tol=0,
                abs_tol=1e-9,
            )
            and lower > BOUNDARY_GUARD_DISTANCE_M
            and isinstance(seeded_points, list)
            and bool(seeded_points)
            and all(
                isinstance(point, Mapping)
                and int(point.get("locator_flat_index", -1))
                == int(point.get("locator_row", -1))
                * NO_OVERLAP_LOCATOR_SHAPE[1]
                + int(point.get("locator_col", -1))
                for point in seeded_points
            )
            and isinstance(seeded_chunks, list)
            and bool(seeded_chunks)
            and int(item.get("seeded_chunk_count", -1)) == len(seeded_chunks)
            and int(item.get("mapped_target_cell_count", -1)) == 0
            and item.get("verified_no_overlap_mapped_zero") is True
        )
    except (KeyError, TypeError, ValueError):
        return False


def _pass_evidence_valid(
    record: Mapping[str, Any],
    binding_sha256: str,
    *,
    binding_payload: Mapping[str, Any],
) -> bool:
    if record.get("status") != "complete" or not record.get("boundary_verified"):
        return False
    path = Path(str(record.get("evidence_path", "")))
    if not (
        path.is_file()
        and record.get("binding_sha256") == binding_sha256
        and len(str(record.get("evidence_sha256", ""))) == 64
        and sha256_file(path) == record.get("evidence_sha256")
    ):
        return False
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        summary = document["summary"]
        city = str(binding_payload["city"])
        orbit = int(binding_payload["orbit"])
        acquisition = pd.Timestamp(binding_payload["acquisition_utc"]).isoformat()
        scenes = document["scene_evidence"]
        return bool(
            path.resolve()
            == (PASS_EVIDENCE_DIR / city / f"{orbit:05d}.json").resolve()
            and
            document.get("status") == "complete"
            and document.get("decision_id") == DECISION_ID
            and document.get("algorithm_version") == D0035_ALGORITHM_VERSION
            and (
                IMPLEMENTATION_DECISION_ID != "D0048"
                or document.get("implementation_decision_id") == "D0048"
            )
            and document.get("binding_sha256") == binding_sha256
            and document.get("binding") == dict(binding_payload)
            and document.get("boundary_verified") is True
            and isinstance(scenes, list)
            and scenes
            and all(_scene_boundary_evidence_valid(item) for item in scenes)
            and str(document.get("city")) == city
            and int(document.get("orbit")) == orbit
            and str(summary.get("city")) == city
            and int(summary.get("orbit")) == orbit
            and pd.Timestamp(summary.get("acquisition_utc")).isoformat() == acquisition
            and summary.get("l1b_geometry_complete") is True
            and summary.get("decision_id") == DECISION_ID
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False


def _bool_value(value: Any) -> bool:
    if isinstance(value, str):
        lowered = value.strip().casefold()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no", "", "nan"}:
            return False
        raise ValueError(f"Cannot parse boolean value {value!r}")
    return bool(value)


def _run_geometry_passes(
    candidates: pd.DataFrame,
    manifest: pd.DataFrame,
    links: pd.DataFrame,
    target_grids: Mapping[str, Mapping[str, Any]],
    asset_bindings: Mapping[str, Mapping[str, Any]],
    *,
    session_factory: Any,
    max_workers: int,
) -> pd.DataFrame:
    """Stream 1--3 scenes per pass and persist only metric/evidence JSON.

    This avoids multi-gigabyte scene-map intermediates.  Thirty-four scenes
    referenced by two cities are deliberately re-read for the second city;
    that small overhead keeps every pass checkpoint independent and auditable.
    """

    target_checkpoint_keys = {
        f"{row.city}:{int(row.orbit):05d}"
        for row in candidates[["city", "orbit"]].itertuples(index=False)
    }
    checkpoint = {
        key: value
        for key, value in load_checkpoint(GEOMETRY_CHECKPOINT).items()
        if key in target_checkpoint_keys
    }
    local = threading.local()
    manifest_by_key = {
        (int(row.orbit), int(row.scene)): row._asdict()
        for row in manifest.itertuples(index=False)
    }
    link_groups = {
        (str(city), int(orbit)): group.sort_values("scene")
        for (city, orbit), group in links.groupby(["city", "orbit"], sort=True)
    }
    grid_fingerprints = {
        city: _target_grid_fingerprint(grids) for city, grids in target_grids.items()
    }

    def process_scene(
        row: Mapping[str, Any], city: str
    ) -> tuple[dict[str, dict[str, np.ndarray]], dict[str, Any]]:
        granule = str(row["granule_id"])
        dmrpp = DMRPP_DIR / f"{granule}.h5.dmrpp"
        locator = LOCATOR_DIR / f"{granule}_stride32.nc4"
        if not dmrpp.is_file() or not locator.is_file():
            raise FileNotFoundError(f"D0035 metadata asset missing for {granule}")
        descriptors = parse_dmrpp_chunks(dmrpp)
        chunk_shape = next(iter(descriptors["latitude"].values())).chunk_shape
        locator_lat, locator_lon = _read_locator(locator)
        selection_proof: dict[str, Any] | None = None
        if IMPLEMENTATION_DECISION_ID == "D0048":
            selected, selection_proof = initial_chunk_selection_with_proof(
                locator_lat,
                locator_lon,
                target_grids[city],
                chunk_shape=chunk_shape,
            )
        else:
            selected = initial_chunk_selection(
                locator_lat,
                locator_lon,
                target_grids[city],
                chunk_shape=chunk_shape,
            )
        if len(selected) > MAX_SELECTED_CHUNKS_PER_SCENE:
            raise RuntimeError(f"Initial chunk guard exceeded for {granule}")
        initial_selected = set(selected)

        def refresh_session() -> Any:
            # Replacing the worker's thread-local session makes the refreshed
            # authentication available both to this fetcher and to subsequent
            # scenes processed by the same worker thread.
            local.session = session_factory()
            return local.session

        fetcher = _RangeFetcher(
            local.session,
            str(row["hdf_url"]),
            granule,
            refresh_session=refresh_session,
        )
        decoded: dict[str, dict[tuple[int, int], np.ndarray]] = {
            name: {} for name in GEOMETRY_VARIABLES
        }
        chunk_hashes: dict[str, str] = {}
        iterations = 0
        edges_tested = 0
        final_minimum = math.inf
        while True:
            decoded, chunk_hashes, _ = decode_selected_chunks(
                descriptors,
                selected,
                ("latitude", "longitude"),
                fetch_range=fetcher,
                decoded=decoded,
                chunk_hashes=chunk_hashes,
            )
            additions, minimum, n_edges = boundary_expansion_neighbors(
                selected,
                decoded["latitude"],
                decoded["longitude"],
                target_grids[city],
                chunk_shape=chunk_shape,
            )
            iterations += 1
            edges_tested += n_edges
            final_minimum = minimum
            if not additions:
                break
            selected.update(additions)
            if len(selected) > MAX_SELECTED_CHUNKS_PER_SCENE:
                raise RuntimeError(f"Boundary chunk guard exceeded for {granule}")
            if iterations >= 64:
                raise RuntimeError(f"Boundary expansion did not converge for {granule}")
        decoded, chunk_hashes, _ = decode_selected_chunks(
            descriptors,
            selected,
            ("view_zenith",),
            fetch_range=fetcher,
            decoded=decoded,
            chunk_hashes=chunk_hashes,
        )
        mapped = map_decoded_chunks_to_targets(
            selected,
            decoded,
            target_grids[city],
            chunk_shape=chunk_shape,
        )
        distances = [
            np.asarray(values["source_distance_m"], dtype=float)
            for values in mapped.values()
            if len(values["source_distance_m"])
        ]
        all_distances = np.concatenate(distances) if distances else np.array([], dtype=float)
        mapped_target_cell_count = int(
            sum(len(values["target_index"]) for values in mapped.values())
        )
        if selection_proof is not None:
            selection_proof = finalize_initial_selection_proof(
                selection_proof,
                full_resolution_boundary_verified=True,
                mapped_target_cell_count=mapped_target_cell_count,
            )
        if len(all_distances) and (
            not np.isfinite(all_distances).all()
            or float(np.max(all_distances)) > RADIUS_OF_INFLUENCE_M
        ):
            raise ValueError(f"Nearest-neighbour radius violation for {granule}")
        evidence = {
            "granule_id": granule,
            "orbit": int(row["orbit"]),
            "scene": int(row["scene"]),
            "city": city,
            "cmr_record_sha256": str(row["cmr_record_sha256"]),
            "dmrpp_size_bytes": dmrpp.stat().st_size,
            "dmrpp_sha256": sha256_file(dmrpp),
            "locator_size_bytes": locator.stat().st_size,
            "locator_sha256": sha256_file(locator),
            "initial_chunk_count": len(initial_selected),
            "final_chunk_count": len(selected),
            "selected_chunk_coords_sha256": sha256_strings(
                f"{r}:{c}" for r, c in selected
            ),
            "selected_compressed_chunks_sha256": sha256_strings(
                f"{key}:{value}" for key, value in chunk_hashes.items()
            ),
            "range_request_count": fetcher.n_requests,
            "range_bytes_transferred": fetcher.n_bytes,
            "range_evidence_sha256": sha256_strings(fetcher.range_evidence),
            "session_refresh_count": fetcher.session_refresh_count,
            "hdf_object_size_bytes": fetcher.object_size_bytes,
            "hdf_object_validator": fetcher.object_validator,
            "boundary_expansion_iterations": iterations,
            "boundary_edges_tested": edges_tested,
            "boundary_minimum_domain_distance_m": (
                None if not math.isfinite(final_minimum) else final_minimum
            ),
            "boundary_verified": True,
            "mapped_target_cell_count": mapped_target_cell_count,
            "mapped_source_distance_min_m": (
                float(np.min(all_distances)) if len(all_distances) else None
            ),
            "mapped_source_distance_max_m": (
                float(np.max(all_distances)) if len(all_distances) else None
            ),
        }
        if selection_proof is not None:
            evidence.update(selection_proof)
        return mapped, evidence

    def worker(candidate: Mapping[str, Any]) -> tuple[str, dict[str, Any], dict[str, Any]]:
        city = str(candidate["city"])
        orbit = int(candidate["orbit"])
        item_id = f"{city}:{orbit:05d}"
        pass_links = link_groups[(city, orbit)]
        scene_bindings: list[dict[str, Any]] = []
        for link in pass_links.itertuples(index=False):
            scene_row = manifest_by_key[(orbit, int(link.scene))]
            granule = str(scene_row["granule_id"])
            if granule not in asset_bindings:
                raise RuntimeError(f"Missing current asset binding for {granule}")
            scene_bindings.append(
                {
                    "orbit": orbit,
                    "scene": int(link.scene),
                    "granule_id": granule,
                    **dict(asset_bindings[granule]),
                }
            )
        binding_payload = {
            "algorithm_version": D0035_ALGORITHM_VERSION,
            "decision_id": DECISION_ID,
            "city": city,
            "orbit": orbit,
            "acquisition_utc": pd.Timestamp(candidate["acquisition_utc"]).isoformat(),
            "target_grid_sha256": grid_fingerprints[city],
            "locator_stride": LOCATOR_STRIDE,
            "source_margin_pixels": 64,
            "radius_m": RADIUS_OF_INFLUENCE_M,
            "boundary_guard_m": BOUNDARY_GUARD_DISTANCE_M,
            "max_selected_chunks": MAX_SELECTED_CHUNKS_PER_SCENE,
            "max_range_bytes_per_scene": MAX_RANGE_BYTES_PER_SCENE,
            "scene_bindings": scene_bindings,
        }
        if IMPLEMENTATION_DECISION_ID == "D0048":
            binding_payload.update(_d0048_geometry_binding_fields())
        binding_sha256 = hashlib.sha256(
            json.dumps(binding_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        cached = checkpoint.get(item_id, {})
        if _pass_evidence_valid(
            cached, binding_sha256, binding_payload=binding_payload
        ):
            document = json.loads(Path(str(cached["evidence_path"])).read_text())
            return item_id, dict(cached), dict(document["summary"])
        if not hasattr(local, "session"):
            local.session = session_factory()
        combined = {
            tile: np.full(grid.size, np.nan, dtype=np.float32)
            for tile, grid in target_grids[city].items()
        }
        n_overlap = 0
        scene_evidence: list[dict[str, Any]] = []
        for link in pass_links.itertuples(index=False):
            scene_row = manifest_by_key[(orbit, int(link.scene))]
            mapped, evidence = process_scene(scene_row, city)
            scene_evidence.append(evidence)
            for tile, values in mapped.items():
                indices = np.asarray(values["target_index"], dtype=np.int64)
                angles = np.asarray(values["view_zenith_abs_deg"], dtype=np.float32)
                existing = np.isfinite(combined[tile][indices])
                n_overlap += int(existing.sum())
                if len(indices):
                    previous = combined[tile][indices]
                    combined[tile][indices] = np.where(
                        existing, np.maximum(previous, angles), angles
                    )
        value_parts = [values[np.isfinite(values)] for values in combined.values()]
        all_values = np.concatenate(value_parts) if value_parts else np.array([], dtype=float)
        n_domain = int(sum(len(values) for values in combined.values()))
        n_valid = int(len(all_values))
        coverage = n_valid / n_domain
        p95 = float(np.quantile(all_values, 0.95)) if n_valid else math.nan
        coverage_ok = bool(coverage >= 0.95)
        angle_ok = bool(n_valid and p95 <= 20.0)
        if coverage_ok and angle_ok:
            status = "geometry_pass"
        elif not coverage_ok and not angle_ok:
            status = "coverage_and_angle_fail"
        elif not coverage_ok:
            status = "coverage_fail"
        else:
            status = "angle_fail"
        passed = bool(coverage_ok and angle_ok)
        acquisition = pd.Timestamp(candidate["acquisition_utc"])
        summary = {
            "city": city,
            "orbit": orbit,
            "acquisition_utc": acquisition.isoformat(),
            "year": int(acquisition.year),
            "metadata_candidate": True,
            "n_l1b_geo_scenes": int(len(pass_links)),
            "n_domain_pixels": n_domain,
            "n_view_valid_pixels": n_valid,
            "view_valid_fraction": coverage,
            "view_zenith_abs_min_deg": float(np.min(all_values)) if n_valid else math.nan,
            "view_zenith_abs_median_deg": float(np.median(all_values)) if n_valid else math.nan,
            "view_zenith_abs_mean_deg": float(np.mean(all_values)) if n_valid else math.nan,
            "view_zenith_abs_p95_deg": p95,
            "view_zenith_abs_max_deg": float(np.max(all_values)) if n_valid else math.nan,
            "near_nadir_threshold_deg": 20.0,
            "minimum_view_coverage": 0.95,
            "near_nadir": passed,
            "n_overlapping_valid_pixels": n_overlap,
            "overlap_rule": "retain largest absolute finite L1B view zenith across scenes",
            "geometry_source": "ECO_L1B_GEO.002",
            "l1b_geometry_covered_cells": n_valid,
            "l1b_geometry_domain_cells": n_domain,
            "l1b_geometry_coverage_fraction": coverage,
            "l1b_view_zenith_abs_p95_deg": p95,
            "l1b_geometry_complete": True,
            "l1b_geometry_status": status,
            "quality_candidate_pre_cloud_l1b": passed,
            "quality_candidate_pre_cloud": passed,
            "quality_candidate_pre_cloud_l2t_invalid": _bool_value(
                candidate.get("quality_candidate_pre_cloud", False)
            ),
            "geometry_resolution_status": status,
            "geometry_definitive": True,
            "quality_candidate_pre_cloud_geometry_only": passed,
            "scene_source_evidence_sha256": hashlib.sha256(
                json.dumps(scene_evidence, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            # build_geometry_validation requires this generic evidence field.
            "scene_map_set_sha256": hashlib.sha256(
                json.dumps(scene_evidence, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "decision_id": DECISION_ID,
        }
        evidence = {
            "decision_id": DECISION_ID,
            "implementation_decision_id": IMPLEMENTATION_DECISION_ID,
            "status": "complete",
            "city": city,
            "orbit": orbit,
            "collection_short_name": "ECO_L1B_GEO",
            "collection_version": "002",
            "variables": list(GEOMETRY_VARIABLES),
            "locator_variables": list(LOCATOR_VARIABLES),
            "full_resolution": True,
            "locator_stride": LOCATOR_STRIDE,
            "source_margin_pixels_minimum": 64,
            "radius_of_influence_m": RADIUS_OF_INFLUENCE_M,
            "boundary_guard_distance_m": BOUNDARY_GUARD_DISTANCE_M,
            "boundary_rule": (
                "literal projected frozen-domain distance; invalid edges expand; "
                "210 m radius plus 100 m adjacent-source-pixel guard"
            ),
            "boundary_verified": all(item["boundary_verified"] for item in scene_evidence),
            "algorithm_version": D0035_ALGORITHM_VERSION,
            "binding": binding_payload,
            "binding_sha256": binding_sha256,
            "scene_evidence": scene_evidence,
            "summary": summary,
            "lst_opened": False,
            "thermal_opened": False,
            "record_2026_opened": False,
            "holdout_status": "UNSELECTED",
        }
        evidence_path = PASS_EVIDENCE_DIR / city / f"{orbit:05d}.json"
        _atomic_json(evidence, evidence_path)
        record = {
            "status": "complete",
            "boundary_verified": True,
            "evidence_path": str(evidence_path),
            "evidence_sha256": sha256_file(evidence_path),
            "binding_sha256": binding_sha256,
            "range_bytes_transferred": int(
                sum(item["range_bytes_transferred"] for item in scene_evidence)
            ),
            "range_request_count": int(
                sum(item["range_request_count"] for item in scene_evidence)
            ),
        }
        return item_id, record, summary

    records = candidates.sort_values(["city", "acquisition_utc", "orbit"]).to_dict("records")
    summaries: list[dict[str, Any]] = []
    processed = 0
    unresolved_total = 0

    def unresolved_summary(candidate: Mapping[str, Any], error_type: str) -> dict[str, Any]:
        city = str(candidate["city"])
        orbit = int(candidate["orbit"])
        acquisition = pd.Timestamp(candidate["acquisition_utc"])
        n_domain = int(sum(grid.size for grid in target_grids[city].values()))
        evidence_hash = hashlib.sha256(
            f"unresolved:{D0035_ALGORITHM_VERSION}:{city}:{orbit}:{error_type}".encode()
        ).hexdigest()
        return {
            "city": city,
            "orbit": orbit,
            "acquisition_utc": acquisition.isoformat(),
            "year": int(acquisition.year),
            "metadata_candidate": True,
            "n_l1b_geo_scenes": int(len(link_groups[(city, orbit)])),
            "n_domain_pixels": n_domain,
            "n_view_valid_pixels": np.nan,
            "view_valid_fraction": np.nan,
            "view_zenith_abs_min_deg": np.nan,
            "view_zenith_abs_median_deg": np.nan,
            "view_zenith_abs_mean_deg": np.nan,
            "view_zenith_abs_p95_deg": np.nan,
            "view_zenith_abs_max_deg": np.nan,
            "near_nadir_threshold_deg": 20.0,
            "minimum_view_coverage": 0.95,
            "near_nadir": False,
            "n_overlapping_valid_pixels": np.nan,
            "overlap_rule": "unresolved; no geometry inference permitted",
            "geometry_source": "ECO_L1B_GEO.002",
            "l1b_geometry_covered_cells": np.nan,
            "l1b_geometry_domain_cells": n_domain,
            "l1b_geometry_coverage_fraction": np.nan,
            "l1b_view_zenith_abs_p95_deg": np.nan,
            "l1b_geometry_complete": False,
            "l1b_geometry_status": "unresolved",
            "quality_candidate_pre_cloud_l1b": False,
            "quality_candidate_pre_cloud": False,
            "quality_candidate_pre_cloud_l2t_invalid": _bool_value(
                candidate.get("quality_candidate_pre_cloud", False)
            ),
            "geometry_resolution_status": "unresolved",
            "geometry_definitive": False,
            "quality_candidate_pre_cloud_geometry_only": False,
            "geometry_error_type": error_type,
            "scene_source_evidence_sha256": evidence_hash,
            "scene_map_set_sha256": evidence_hash,
            "decision_id": DECISION_ID,
        }

    for start in range(0, len(records), 10):
        failures: list[tuple[str, str]] = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(worker, row): row for row in records[start : start + 10]}
            for future in as_completed(futures):
                row = futures[future]
                item_id = f"{row['city']}:{int(row['orbit']):05d}"
                try:
                    key, record, summary = future.result()
                    checkpoint[key] = record
                    summaries.append(summary)
                    processed += 1
                except Exception as exc:
                    error_message = str(exc).strip().replace("\n", " ")[:500]
                    checkpoint[item_id] = {
                        "status": "unresolved",
                        "error_type": type(exc).__name__,
                        "error_message": error_message,
                        "boundary_verified": False,
                    }
                    failures.append(
                        (
                            item_id,
                            (
                                f"{type(exc).__name__}: {error_message}"
                                if error_message
                                else type(exc).__name__
                            ),
                        )
                    )
                    summaries.append(unresolved_summary(row, type(exc).__name__))
                    processed += 1
                    unresolved_total += 1
        write_checkpoint(GEOMETRY_CHECKPOINT, checkpoint)
        total_bytes = sum(
            int(value.get("range_bytes_transferred", 0))
            for value in checkpoint.values()
        )
        print(
            f"D0035 full-resolution pass geometry: {processed}/{len(records)}; "
            f"unresolved {unresolved_total}; "
            f"range bytes {total_bytes:,}",
            flush=True,
        )
        if failures:
            preview = ", ".join(f"{item}:{kind}" for item, kind in failures[:8])
            print(
                f"D0035 fail-closed unresolved batch: {len(failures)} ({preview})",
                flush=True,
            )
    summary = pd.DataFrame(summaries).sort_values(
        ["city", "acquisition_utc", "orbit"], kind="stable"
    ).reset_index(drop=True)
    if len(summary) != EXPECTED_METADATA_CANDIDATES:
        raise RuntimeError("D0035 pass evidence census is not exactly 942")
    return summary


def _canonical_pre_cloud_table(
    candidates: pd.DataFrame, geometry_summary: pd.DataFrame
) -> pd.DataFrame:
    table = candidates.copy()
    if "quality_candidate_pre_cloud" in table.columns:
        table = table.rename(
            columns={"quality_candidate_pre_cloud": "quality_candidate_pre_cloud_l2t_invalid"}
        )
    else:
        table["quality_candidate_pre_cloud_l2t_invalid"] = False
    # Preserve every superseded L2T geometry diagnostic under an explicit
    # invalid suffix, then let the canonical generic columns come from L1B.
    generic_geometry = [
        "n_domain_pixels",
        "n_view_valid_pixels",
        "view_valid_fraction",
        "view_zenith_abs_min_deg",
        "view_zenith_abs_median_deg",
        "view_zenith_abs_mean_deg",
        "view_zenith_abs_p95_deg",
        "view_zenith_abs_max_deg",
        "near_nadir_threshold_deg",
        "minimum_view_coverage",
        "near_nadir",
        "n_overlapping_valid_pixels",
        "overlap_rule",
    ]
    table = table.rename(
        columns={
            column: f"{column}_l2t_invalid"
            for column in generic_geometry
            if column in table.columns
        }
    )
    metrics = geometry_summary.drop(
        columns=[column for column in ("metadata_candidate", "year") if column in geometry_summary],
        errors="ignore",
    ).copy()
    table["acquisition_utc"] = pd.to_datetime(
        table["acquisition_utc"], utc=True, format="mixed"
    ).map(
        lambda value: value.isoformat()
    )
    metrics["acquisition_utc"] = pd.to_datetime(
        metrics["acquisition_utc"], utc=True, format="mixed"
    ).map(
        lambda value: value.isoformat()
    )
    # Old L2T-derived view metrics remain as explicitly invalid historical
    # diagnostics.  L1B metrics use their own unambiguous names.
    duplicate = [
        column
        for column in metrics.columns
        if column in table.columns and column not in {"city", "orbit", "acquisition_utc"}
    ]
    metrics = metrics.drop(columns=duplicate)
    table = table.merge(
        metrics,
        on=["city", "orbit", "acquisition_utc"],
        how="left",
        validate="one_to_one",
    )
    if table["quality_candidate_pre_cloud_l1b"].isna().any():
        raise ValueError("Canonical L1B table lost a geometry result")
    table["quality_candidate_pre_cloud"] = table[
        "quality_candidate_pre_cloud_l1b"
    ].astype(bool)
    if not table["quality_candidate_pre_cloud"].equals(
        table["quality_candidate_pre_cloud_l1b"].astype(bool)
    ):
        raise ValueError("Canonical pre-cloud flag does not equal the L1B flag")
    return table.sort_values(["city", "acquisition_utc", "orbit"], kind="stable").reset_index(
        drop=True
    )


def _seed_cloud_checkpoint(manifest: pd.DataFrame) -> None:
    target_ids = set(manifest["item_id"].astype(str))
    dedicated = load_checkpoint(CLOUD_CHECKPOINT)
    for shared_path in SHARED_CLOUD_CHECKPOINTS:
        if not shared_path.is_file():
            continue
        shared = load_checkpoint(shared_path)
        for item_id in target_ids:
            if item_id not in dedicated and item_id in shared:
                dedicated[item_id] = shared[item_id]
    write_checkpoint(CLOUD_CHECKPOINT, dedicated)


def _cloud_evidence(
    rows: pd.DataFrame, checkpoint: Mapping[str, Mapping[str, Any]]
) -> tuple[bool, int, str]:
    evidence: list[str] = []
    total = 0
    for row in rows.to_dict("records"):
        item_id = str(row["item_id"])
        record = checkpoint.get(item_id)
        if not record or record.get("status") != "complete":
            return False, total, ""
        path = Path(str(record.get("local_path", "")))
        digest = str(record.get("sha256", ""))
        size = int(record.get("size_bytes", -1))
        file_name = Path(str(row.get("file_name", ""))).name
        granule_id = str(row.get("granule_id", ""))
        product_id = str(row.get("selected_product_id", ""))
        city = str(row.get("city", ""))
        expected_item = (
            f"{CLOUD_COG}-"
            + hashlib.sha256(
                f"{city}|{granule_id}|{CLOUD_COG}".encode("utf-8")
            ).hexdigest()[:20]
        )
        identity_valid = bool(
            str(row.get("asset_type", "")) == CLOUD_COG
            and str(row.get("status", "")).casefold() == "available"
            and item_id == expected_item
            and product_id == granule_id
            and Path(file_name).stem == f"{product_id}_cloud"
            and path.resolve() == (ASSET_ROOT / CLOUD_COG / file_name).resolve()
        )
        if (
            not identity_valid
            or not path.is_file()
            or path.stat().st_size != size
            or len(digest) != 64
            or sha256_file(path) != digest
        ):
            return False, total, ""
        total += size
        evidence.append(
            f"{item_id}:{product_id}:{file_name}:{digest}:{size}"
        )
    return True, total, sha256_strings(evidence)


def _empty_cloud_validation(
    expected: int,
    *,
    complete: bool = False,
    error_type: str | None = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "expected_cloud_candidates": int(expected),
        "resolved_cloud_candidate_count": 0,
        "finite_cloud_fraction_count": 0,
        "cloud_complete": bool(complete),
        "cloud_extrapolation_used": False,
        "planning_pass_equivalent_sum": 0.0 if complete and expected == 0 else None,
        "planning_pass_equivalent_floor": 0 if complete and expected == 0 else None,
    }
    if error_type:
        value["cloud_error_type"] = str(error_type)
    return value


def _validate_cloud_summary(
    summary: pd.DataFrame,
    passing: pd.DataFrame,
    *,
    download_error_type: str | None = None,
) -> dict[str, Any]:
    expected = int(len(passing))
    if expected == 0:
        return _empty_cloud_validation(0, complete=True)
    finite = np.isfinite(pd.to_numeric(summary["clear_domain_fraction"], errors="coerce"))
    resolved_status = summary["cloud_resolution_status"].astype(str).eq(
        "observed_exhaustive_complete_independent_of_view"
    )
    exact_keys = set(
        map(tuple, summary[["city", "orbit"]].to_records(index=False))
    ) == set(map(tuple, passing[["city", "orbit"]].to_records(index=False)))
    domain = pd.to_numeric(summary["n_domain_pixels"], errors="coerce")
    clear = pd.to_numeric(
        summary["n_clear_pixels_independent_of_view"], errors="coerce"
    )
    cloudy = pd.to_numeric(
        summary["n_cloud_pixels_independent_of_view"], errors="coerce"
    )
    invalid = pd.to_numeric(
        summary["n_cloud_invalid_or_fill_pixels_independent_of_view"], errors="coerce"
    )
    observed = pd.to_numeric(
        summary["n_cloud_observed_pixels_independent_of_view"], errors="coerce"
    )
    expected_assets = pd.to_numeric(summary["n_expected_scene_tiles"], errors="coerce")
    resolved_assets = pd.to_numeric(summary["n_resolved_cloud_assets"], errors="coerce")
    verified_assets = pd.to_numeric(summary["n_verified_cloud_assets"], errors="coerce")
    digests = summary["cloud_asset_set_sha256"].astype(str).str.fullmatch(
        r"[0-9a-f]{64}"
    )
    partition = (clear + cloudy + invalid).eq(domain) & (clear + cloudy).eq(observed)
    ratio = clear / domain
    fractions_equal = np.isclose(
        pd.to_numeric(summary["clear_domain_fraction"], errors="coerce"),
        ratio,
        rtol=0,
        atol=1e-15,
        equal_nan=False,
    )
    asset_census = (
        expected_assets.gt(0)
        & expected_assets.eq(resolved_assets)
        & expected_assets.eq(verified_assets)
    )
    complete = bool(
        len(summary) == expected
        and not summary.duplicated(["city", "orbit"]).any()
        and exact_keys
        and finite.all()
        and resolved_status.all()
        and summary["cloud_asset_complete"].fillna(False).astype(bool).all()
        and summary["provenance_complete"].fillna(False).astype(bool).all()
        and digests.all()
        and domain.gt(0).all()
        and partition.all()
        and np.asarray(fractions_equal).all()
        and asset_census.all()
    )
    total = float(summary["clear_domain_fraction"].sum()) if complete else None
    output = {
        "expected_cloud_candidates": expected,
        "resolved_cloud_candidate_count": int(resolved_status.sum()),
        "finite_cloud_fraction_count": int(finite.sum()),
        "cloud_complete": complete,
        "cloud_extrapolation_used": False,
        "planning_pass_equivalent_sum": total,
        "planning_pass_equivalent_floor": math.floor(total) if total is not None else None,
        "cloud_pixel_partition_identity_count": int(partition.sum()),
        "cloud_asset_census_identity_count": int(asset_census.sum()),
        "cloud_asset_digest_valid_count": int(digests.sum()),
    }
    if download_error_type:
        output["cloud_download_error_type"] = download_error_type
    return output


def _unresolved_cloud_row(
    candidate: Mapping[str, Any],
    *,
    expected_assets: int,
    error_type: str,
) -> dict[str, Any]:
    acquisition = pd.Timestamp(candidate["acquisition_utc"])
    denominator = int(candidate["l1b_geometry_domain_cells"])
    return {
        "city": str(candidate["city"]),
        "orbit": int(candidate["orbit"]),
        "acquisition_utc": acquisition.isoformat(),
        "year": int(acquisition.year),
        "n_domain_pixels": denominator,
        "n_domain_pixels_in_present_tiles": np.nan,
        "n_cloud_observed_pixels_independent_of_view": np.nan,
        "n_clear_pixels_independent_of_view": np.nan,
        "n_cloud_pixels_independent_of_view": np.nan,
        "n_cloud_invalid_or_fill_pixels_independent_of_view": np.nan,
        "cloud_survival_fraction_of_domain_independent_of_view": np.nan,
        "cloud_fraction_of_domain_independent_of_view": np.nan,
        "n_unique_mgrs_tiles": np.nan,
        "n_overlapping_cloud_observations": np.nan,
        "independent_cloud_overlap_rule": "unresolved; no cloud inference permitted",
        "clear_domain_fraction": np.nan,
        "n_expected_scene_tiles": int(expected_assets),
        "n_resolved_cloud_assets": 0,
        "n_verified_cloud_assets": 0,
        "cloud_asset_complete": False,
        "provenance_complete": False,
        "cloud_asset_bytes": 0,
        "cloud_asset_set_sha256": "",
        "cloud_resolution_status": "unresolved",
        "cloud_error_type": str(error_type),
        "decision_id": DECISION_ID,
    }


def _run_cloud(
    pre_cloud_l1b: pd.DataFrame,
    latest_views: pd.DataFrame,
    domain_geometries: Mapping[str, Mapping[str, Any]],
    *,
    session_factory: Any,
    max_workers: int,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    passing = pre_cloud_l1b.loc[
        pre_cloud_l1b["quality_candidate_pre_cloud_l1b"].fillna(False).astype(bool)
    ].copy()
    expected = int(len(passing))
    if expected == 0:
        columns = list(
            _unresolved_cloud_row(
                {
                    "city": "",
                    "orbit": 0,
                    "acquisition_utc": "2018-01-01T00:00:00Z",
                    "l1b_geometry_domain_cells": 1,
                },
                expected_assets=0,
                error_type="empty_target_set",
            )
        )
        return pd.DataFrame(columns=columns), _empty_cloud_validation(0, complete=True)
    l2t_results = load_cached_l2t_results(L2T_CACHE)
    manifest = build_exhaustive_cloud_manifest(
        pre_cloud_l1b,
        latest_views,
        l2t_results=l2t_results,
        expected_candidate_passes=expected,
    )
    manifest["decision_id"] = DECISION_ID
    manifest["target_scope"] = "all_D0035_L1B_geometry_passing_candidates"
    manifest["cloud_target_selected_before_outcome"] = True
    if set(manifest["asset_type"].astype(str)) != {CLOUD_COG}:
        raise ValueError("D0035 cloud manifest contains a forbidden non-cloud asset")
    _atomic_csv(manifest, CLOUD_MANIFEST)
    _seed_cloud_checkpoint(manifest)
    download_error_type: str | None = None
    try:
        download_target_manifest_concurrent(
            manifest,
            destination_root=ASSET_ROOT,
            checkpoint_path=CLOUD_CHECKPOINT,
            session_factory=session_factory,
            max_workers=max_workers,
            checkpoint_batch_size=100,
            timeout_seconds=180,
        )
    except Exception as exc:
        # Continue to a row-complete audit from the checkpoint.  Any affected
        # pass becomes explicitly unresolved and forces the combined STOP.
        download_error_type = type(exc).__name__
    checkpoint = load_checkpoint(CLOUD_CHECKPOINT)
    tile_domains = {
        city: {
            tile: partition_domain_for_mgrs_tile(domain_geometries[city], tile)
            for tile in sorted(group["tile"].astype(str).unique())
        }
        for city, group in manifest.groupby("city", sort=True)
    }
    cloud_groups = {
        (str(city), int(orbit)): group
        for (city, orbit), group in manifest.groupby(["city", "orbit"], sort=True)
    }
    rows: list[dict[str, Any]] = []
    for candidate in passing.to_dict("records"):
        key = (str(candidate["city"]), int(candidate["orbit"]))
        cloud_rows = cloud_groups.get(key)
        if cloud_rows is None:
            rows.append(
                _unresolved_cloud_row(
                    candidate, expected_assets=0, error_type="MissingCloudManifestPass"
                )
            )
            continue
        try:
            complete, nbytes, digest = _cloud_evidence(cloud_rows, checkpoint)
            if not complete:
                raise ValueError(f"D0035 cloud evidence is incomplete for pass {key}")
            denominator = int(candidate["l1b_geometry_domain_cells"])
            result = _summarize_cloud_without_view_mask(
                cloud_rows,
                asset_root=ASSET_ROOT,
                domain_pixel_denominator=denominator,
                tile_domain_geometries_wgs84=tile_domains[key[0]],
            )
            clear_fraction = float(
                result["cloud_survival_fraction_of_domain_independent_of_view"]
            )
            if not math.isfinite(clear_fraction):
                raise ValueError(f"D0035 cloud fraction is not finite for pass {key}")
            acquisition = pd.Timestamp(candidate["acquisition_utc"])
            rows.append(
                {
                    "city": key[0],
                    "orbit": key[1],
                    "acquisition_utc": acquisition.isoformat(),
                    "year": int(acquisition.year),
                    **result,
                    "clear_domain_fraction": clear_fraction,
                    "n_expected_scene_tiles": int(len(cloud_rows)),
                    "n_resolved_cloud_assets": int(len(cloud_rows)),
                    "n_verified_cloud_assets": int(len(cloud_rows)),
                    "cloud_asset_complete": True,
                    "provenance_complete": True,
                    "cloud_asset_bytes": nbytes,
                    "cloud_asset_set_sha256": digest,
                    "cloud_resolution_status": "observed_exhaustive_complete_independent_of_view",
                    "decision_id": DECISION_ID,
                }
            )
        except Exception as exc:
            rows.append(
                _unresolved_cloud_row(
                    candidate,
                    expected_assets=int(len(cloud_rows)),
                    error_type=type(exc).__name__,
                )
            )
    summary = pd.DataFrame(rows).sort_values(
        ["city", "acquisition_utc", "orbit"], kind="stable"
    ).reset_index(drop=True)
    validation = _validate_cloud_summary(
        summary, passing, download_error_type=download_error_type
    )
    return summary, validation


def _combined_validation(
    geometry: Mapping[str, Any], cloud: Mapping[str, Any]
) -> dict[str, Any]:
    combined_complete = bool(geometry["geometry_complete"] and cloud["cloud_complete"])
    no_geometry_passers = bool(
        geometry["geometry_complete"]
        and int(geometry.get("geometry_passing_candidate_count", 0)) == 0
    )
    scientific_gate_eligible = bool(combined_complete and not no_geometry_passers)
    if not geometry["geometry_complete"]:
        status = "STOP_D0035_INCOMPLETE_GEOMETRY"
    elif not cloud["cloud_complete"]:
        status = "STOP_D0035_INCOMPLETE_EXHAUSTIVE_CLOUD"
    elif no_geometry_passers:
        status = "STOP_D0035_NO_GEOMETRY_PASSERS"
    else:
        status = "PASS_D0035_GEOMETRY_AND_EXHAUSTIVE_CLOUD"
    output = {
        **geometry,
        **cloud,
        "decision_id": DECISION_ID,
        "combined_complete": combined_complete,
        "scientific_gate_eligible": scientific_gate_eligible,
        "candidate_view_mask_cloud_independent": bool(geometry["geometry_complete"]),
        "view_gate_cloud_conditioned": False,
        "cloud_extrapolation_used": False,
        "lst_opened": False,
        "thermal_opened": False,
        "record_2026_opened": False,
        "holdout_status": "UNSELECTED",
        "frozen_years": "2018-2025",
        "gate_status": status,
        "canonical_status": status,
    }
    return output


def _unavailable_geometry_validation(
    *, stage: str, error_type: str
) -> dict[str, Any]:
    return {
        "decision_id": DECISION_ID,
        "expected_metadata_candidates": EXPECTED_METADATA_CANDIDATES,
        "resolved_geometry_candidate_count": 0,
        "definitive_geometry_status_count": 0,
        "unresolved_geometry_candidate_count": EXPECTED_METADATA_CANDIDATES,
        "geometry_source": "ECO_L1B_GEO.002",
        "geometry_complete": False,
        "candidate_seal_geometry_only": False,
        "candidate_view_mask_cloud_independent": False,
        "view_gate_cloud_conditioned": False,
        "geometry_passing_candidate_count": 0,
        "scientific_gate_eligible": False,
        "geometry_failure_stage": str(stage),
        "geometry_error_type": str(error_type),
        "gate_status": "STOP_D0035_INCOMPLETE_GEOMETRY",
        "canonical_status": "STOP_D0035_INCOMPLETE_GEOMETRY",
        "lst_opened": False,
        "thermal_opened": False,
        "record_2026_opened": False,
        "holdout_status": "UNSELECTED",
        "frozen_years": "2018-2025",
    }


def _write_geometry_validation(validation: Mapping[str, Any]) -> None:
    _atomic_json(dict(validation), GEOMETRY_VALIDATION_JSON)
    _atomic_csv(pd.DataFrame([dict(validation)]), GEOMETRY_VALIDATION_CSV)


def _write_combined_validation(validation: Mapping[str, Any]) -> None:
    _atomic_json(dict(validation), COMBINED_VALIDATION_JSON)
    _atomic_csv(pd.DataFrame([dict(validation)]), COMBINED_VALIDATION_CSV)


def _write_run_record(
    combined: Mapping[str, Any],
    artifacts: list[Path],
    *,
    profile: str,
) -> None:
    geometry_items = (
        load_checkpoint(GEOMETRY_CHECKPOINT) if GEOMETRY_CHECKPOINT.is_file() else {}
    )
    pass_files = sorted(
        {
            Path(str(record["evidence_path"]))
            for record in geometry_items.values()
            if record.get("status") == "complete"
            and record.get("evidence_path")
            and Path(str(record["evidence_path"])).is_file()
            and Path(str(record["evidence_path"])).resolve().is_relative_to(
                PASS_EVIDENCE_DIR.resolve()
            )
        }
    )
    pass_evidence_set = sha256_strings(
        f"{path.relative_to(PASS_EVIDENCE_DIR)}:{sha256_file(path)}"
        for path in pass_files
    )
    asset_items = load_checkpoint(ASSET_CHECKPOINT) if ASSET_CHECKPOINT.is_file() else {}

    def digest(path: Path) -> str:
        return sha256_file(path) if path.is_file() else ""

    run_record = {
        "schema_version": 2,
        "run_id": "R0004_D0035",
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "decision_id": DECISION_ID,
        "implementation_decision_id": IMPLEMENTATION_DECISION_ID,
        "collection_concept_id": COLLECTION_CONCEPT_ID,
        "algorithm_version": D0035_ALGORITHM_VERSION,
        "profile": profile,
        "provenance_counts": {
            "metadata_candidates": EXPECTED_METADATA_CANDIDATES,
            "city_scene_links": EXPECTED_CITY_SCENE_LINKS,
            "unique_scenes": EXPECTED_UNIQUE_SCENES,
            "asset_checkpoint_items": len(asset_items),
            "geometry_checkpoint_items": len(geometry_items),
            "pass_evidence_files": len(pass_files),
        },
        "provenance_sha256": {
            "scene_manifest": digest(SCENE_MANIFEST),
            "asset_checkpoint": digest(ASSET_CHECKPOINT),
            "geometry_checkpoint": digest(GEOMETRY_CHECKPOINT),
            "pass_evidence_set": pass_evidence_set,
            "geometry_summary": digest(GEOMETRY_SUMMARY),
            "cloud_checkpoint": digest(CLOUD_CHECKPOINT),
            "cloud_summary": digest(CLOUD_SUMMARY),
            "combined_validation": digest(COMBINED_VALIDATION_JSON),
        },
        "artifact_sha256": {
            str(path.relative_to(ROOT)): sha256_file(path)
            for path in artifacts
            if path.is_file()
        },
        "combined_validation": dict(combined),
        "lst_opened": False,
        "thermal_opened": False,
        "record_2026_opened": False,
        "holdout_status": "UNSELECTED",
    }
    _atomic_json(run_record, RUN_RECORD)


def _record_pre_geometry_stop(stage: str, error_type: str) -> int:
    geometry = _unavailable_geometry_validation(stage=stage, error_type=error_type)
    cloud = _empty_cloud_validation(0, error_type="NotRunGeometryIncomplete")
    combined = _combined_validation(geometry, cloud)
    _write_geometry_validation(geometry)
    _write_combined_validation(combined)
    artifacts = [SCENE_MANIFEST, ASSET_CHECKPOINT, GEOMETRY_VALIDATION_JSON, COMBINED_VALIDATION_JSON]
    _write_run_record(
        combined,
        artifacts,
        profile=f"D0035 fail-closed before geometry ({stage}: {error_type})",
    )
    print(f"D0035 combined gate: {combined['canonical_status']}", flush=True)
    return 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage",
        choices=("manifest", "assets", "geometry", "cloud", "all"),
        default="all",
    )
    parser.add_argument("--max-workers", type=int, default=10)
    parser.add_argument("--geometry-workers", type=int, default=4)
    args = parser.parse_args()
    if args.max_workers < 1 or args.geometry_workers < 1:
        raise ValueError("Worker counts must be positive")

    config = load_config(ROOT / "configs/v2_cities.toml")
    _validate_config_seal(config)
    if config.study.get("holdout_status") != "UNSELECTED":
        raise ValueError("D0035 requires the holdout to remain UNSELECTED")
    features = load_domain_features(DOMAIN_FILE, config)
    domain_geometries = {city: feature["geometry"] for city, feature in features.items()}
    screened = pd.read_csv(PRE_CLOUD)
    views = pd.read_csv(VIEW_MANIFEST)
    candidates, links = frozen_geometry_targets(screened, views)
    try:
        earthaccess, _ = _earthaccess()
    except Exception as exc:
        return _record_pre_geometry_stop("earthdata_authentication", type(exc).__name__)

    try:
        if args.stage == "manifest" or not SCENE_MANIFEST.is_file():
            manifest = _prepare_scene_manifest(
                candidates,
                links,
                search_data=earthaccess.search_data,
                domain_geometries=domain_geometries,
                max_workers=args.max_workers,
            )
        else:
            # Never trust a saved CSV's selected build/revision.  Re-resolve
            # from all 1,370 exact-query CMR caches and replace the CSV with
            # the canonical latest identity census.
            manifest = _rebuild_scene_manifest_from_exact_cache(links)
        _validate_scene_manifest_identity(manifest, links)
    except Exception as exc:
        return _record_pre_geometry_stop("scene_manifest", type(exc).__name__)
    unresolved_scenes = int((~manifest["status"].astype(str).eq("available")).sum())
    print(
        f"D0035 scene manifest: {len(candidates)} passes, {len(links)} city-scenes, "
        f"{len(manifest)} unique L1B GEO assets; unresolved {unresolved_scenes}",
        flush=True,
    )
    if unresolved_scenes:
        return _record_pre_geometry_stop(
            "scene_manifest", f"{unresolved_scenes}_unresolved_scene_identities"
        )
    if args.stage == "manifest":
        return 0

    try:
        if args.stage in {"assets", "all"} or not ASSET_CHECKPOINT.is_file():
            _require_free_disk(
                "DMR++ plus latitude/longitude stride-32 locator cache",
                len(manifest) * (2_000_000 + 500_000),
            )
            _fetch_metadata_assets(
                manifest,
                session_factory=earthaccess.get_requests_https_session,
                max_workers=args.max_workers,
            )
        asset_bindings = _validated_asset_bindings(manifest)
    except Exception as exc:
        return _record_pre_geometry_stop("metadata_assets", type(exc).__name__)
    if args.stage == "assets":
        return 0

    try:
        denominators = pd.read_csv(DENOMINATORS)
        target_grids = build_canonical_target_grids(
            views,
            domain_geometries_wgs84=domain_geometries,
            asset_root=ASSET_ROOT,
            denominator_table=denominators,
        )
        # Always walk the 942 pass checkpoints.  Valid cached evidence is
        # re-hashed and binding-checked inside this function; stale evidence is
        # recomputed rather than trusting saved summary/validation files.
        _require_free_disk("streamed pass evidence", 1024 * 1024 * 1024)
        geometry_summary = _run_geometry_passes(
            candidates,
            manifest,
            links,
            target_grids,
            asset_bindings,
            session_factory=earthaccess.get_requests_https_session,
            max_workers=args.geometry_workers,
        )
        _atomic_csv(geometry_summary, GEOMETRY_SUMMARY)
        _validate_geometry_identity(geometry_summary, candidates)
        geometry_validation = build_geometry_validation(geometry_summary)
        canonical = _canonical_pre_cloud_table(candidates, geometry_summary)
        _atomic_csv(canonical, PRE_CLOUD_L1B)
        _write_geometry_validation(geometry_validation)
    except Exception as exc:
        return _record_pre_geometry_stop("geometry_execution", type(exc).__name__)

    print(
        f"D0035 geometry seal: {geometry_validation['resolved_geometry_candidate_count']}/"
        f"{geometry_validation['expected_metadata_candidates']} definitive; "
        f"{geometry_validation['geometry_passing_candidate_count']} pass",
        flush=True,
    )
    geometry_artifacts = [
        SCENE_MANIFEST,
        ASSET_CHECKPOINT,
        GEOMETRY_CHECKPOINT,
        GEOMETRY_SUMMARY,
        PRE_CLOUD_L1B,
        GEOMETRY_VALIDATION_JSON,
    ]
    if not geometry_validation["geometry_complete"]:
        cloud_validation = _empty_cloud_validation(
            int(geometry_validation["geometry_passing_candidate_count"]),
            error_type="NotRunGeometryIncomplete",
        )
        combined = _combined_validation(geometry_validation, cloud_validation)
        empty_cloud = pd.DataFrame(
            columns=["city", "orbit", "acquisition_utc", "clear_domain_fraction"]
        )
        _atomic_csv(empty_cloud, CLOUD_SUMMARY)
        _atomic_csv(canonical, FINAL_TABLE)
        _write_combined_validation(combined)
        _write_run_record(
            combined,
            geometry_artifacts + [CLOUD_SUMMARY, FINAL_TABLE, COMBINED_VALIDATION_JSON],
            profile="all 942 metadata candidates; fail-closed incomplete L1B GEO geometry",
        )
        print(f"D0035 combined gate: {combined['canonical_status']}", flush=True)
        return 2

    if args.stage == "geometry":
        pass_count = int(geometry_validation["geometry_passing_candidate_count"])
        cloud_validation = _empty_cloud_validation(
            pass_count, complete=(pass_count == 0), error_type=None if pass_count == 0 else "NotRunStageGeometry"
        )
        combined = _combined_validation(geometry_validation, cloud_validation)
        _write_combined_validation(combined)
        _write_run_record(
            combined,
            geometry_artifacts + [COMBINED_VALIDATION_JSON],
            profile="all 942 metadata candidates; geometry stage complete",
        )
        return 0

    passing = canonical.loc[
        canonical["quality_candidate_pre_cloud_l1b"].fillna(False).astype(bool)
    ].copy()
    try:
        cloud_summary, cloud_validation = _run_cloud(
            canonical,
            views,
            domain_geometries,
            session_factory=earthaccess.get_requests_https_session,
            max_workers=args.max_workers,
        )
    except Exception as exc:
        cloud_summary = pd.DataFrame(
            [
                _unresolved_cloud_row(
                    row, expected_assets=0, error_type=type(exc).__name__
                )
                for row in passing.to_dict("records")
            ]
        )
        if cloud_summary.empty:
            cloud_summary = pd.DataFrame(
                columns=["city", "orbit", "acquisition_utc", "clear_domain_fraction"]
            )
            cloud_validation = _empty_cloud_validation(0, complete=True)
        else:
            cloud_validation = _validate_cloud_summary(cloud_summary, passing)
            cloud_validation["cloud_error_type"] = type(exc).__name__

    combined = _combined_validation(geometry_validation, cloud_validation)
    final = canonical.merge(
        cloud_summary.drop(columns=["year"], errors="ignore"),
        on=["city", "orbit", "acquisition_utc"],
        how="left",
        validate="one_to_one",
        suffixes=("", "_cloud"),
    )
    _atomic_csv(cloud_summary, CLOUD_SUMMARY)
    _atomic_csv(final, FINAL_TABLE)
    _write_combined_validation(combined)
    artifacts = geometry_artifacts + [
        CLOUD_MANIFEST,
        CLOUD_CHECKPOINT,
        CLOUD_SUMMARY,
        FINAL_TABLE,
        COMBINED_VALIDATION_JSON,
    ]
    _write_run_record(
        combined,
        artifacts,
        profile="all 942 metadata candidates; full-resolution L1B GEO DMR++ chunks; exhaustive cloud",
    )
    print(
        f"D0035 combined gate: {combined['canonical_status']}; planning floor "
        f"{combined['planning_pass_equivalent_floor']}",
        flush=True,
    )
    return 0 if combined["scientific_gate_eligible"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
