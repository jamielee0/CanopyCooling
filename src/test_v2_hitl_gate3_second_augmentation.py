#!/usr/bin/env python3
"""Network-free tamper tests for D0069's second Gate-3 augmentation."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile

import numpy as np
import pandas as pd
from shapely.geometry import box
import xarray as xr
import run_v2_hitl_gate3_second_augmentation as augmentation


class _raises:
    def __init__(self, kind: type[BaseException]) -> None:
        self.kind = kind

    def __enter__(self) -> None:
        return None

    def __exit__(self, kind, value, traceback) -> bool:
        assert kind is not None and issubclass(kind, self.kind)
        return True


def _geo_links() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "orbit": [345],
            "scene": [3],
            "scene_acquisition_utc": [pd.Timestamp("2018-07-29T00:12:14Z")],
        }
    )


def _geo_manifest() -> pd.DataFrame:
    granule = "ECOv002_L1B_GEO_00345_003_20180729T001214_0712_01"
    hdf = (
        "https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/"
        f"ECO_L1B_GEO.002/{granule}/{granule}.h5"
    )
    return pd.DataFrame(
        {
            "orbit": [345],
            "scene": [3],
            "scene_acquisition_utc": ["2018-07-29T00:12:14Z"],
            "granule_id": [granule],
            "geo_acquisition_utc": ["2018-07-29T00:12:14Z"],
            "concept_id": ["G123-LPCLOUD"],
            "collection_concept_id": [augmentation.COLLECTION_CONCEPT_ID],
            "opendap_url": [
                "https://opendap.earthdata.nasa.gov/collections/"
                f"{augmentation.COLLECTION_CONCEPT_ID}/granules/{granule}"
            ],
            "hdf_url": [hdf],
            "dmrpp_url": [hdf + ".dmrpp"],
            "required_endpoints_complete": [True],
            "cmr_record_sha256": ["a" * 64],
            "status": ["available"],
            "collection_short_name": [augmentation.COLLECTION_SHORT_NAME],
            "collection_version": [augmentation.COLLECTION_VERSION],
            "provider": [augmentation.COLLECTION_PROVIDER],
        }
    )


def test_l2t_scene_time_comes_from_identity_and_requires_exact_keys() -> None:
    value = augmentation._l2t_scene_acquisition_utc(
        "ECOv002_L2T_LSTE_00345_003_13SED_20180729T001214_0712_01",
        345,
        3,
    )
    assert value == pd.Timestamp("2018-07-29T00:12:14Z")
    with _raises(ValueError):
        augmentation._l2t_scene_acquisition_utc(
            "ECOv002_L2T_LSTE_00345_003_13SED_20180729T001214_0712_01",
            345,
            4,
        )


def test_augmentation_writer_lock_rejects_concurrent_processes() -> None:
    with tempfile.TemporaryDirectory() as directory:
        lock_path = Path(directory) / "augmentation.lock"
        with augmentation._exclusive_run_lock(stage="geometry", path=lock_path):
            with _raises(RuntimeError):
                with augmentation._exclusive_run_lock(
                    stage="geometry", path=lock_path
                ):
                    raise AssertionError("Concurrent run unexpectedly acquired the lock")


def test_geo_manifest_seals_collection_provider_time_and_endpoints() -> None:
    manifest = _geo_manifest()
    augmentation._validate_geo_manifest(
        manifest, _geo_links(), require_provider_column=True
    )
    bad = manifest.copy()
    bad.loc[0, "hdf_url"] = "https://example.com/not-official.h5"
    with _raises(ValueError):
        augmentation._validate_geo_manifest(
            bad, _geo_links(), require_provider_column=True
        )
    bad = manifest.copy()
    bad.loc[0, "geo_acquisition_utc"] = "2018-07-29T00:12:15Z"
    with _raises(ValueError):
        augmentation._validate_geo_manifest(
            bad, _geo_links(), require_provider_column=True
        )


def test_raw_azimuth_out_of_range_and_missing_fail_closed() -> None:
    result = augmentation._validated_raw_azimuth(
        [-180.0, 180.0, -180.01, 180.01, np.nan, np.inf]
    )
    assert np.array_equal(result[:2], np.array([-180.0, 180.0]))
    assert np.isnan(result[2:]).all()


def test_metadata_asset_cache_is_bound_to_source_and_hash() -> None:
    with tempfile.TemporaryDirectory() as directory:
        tmp_path = Path(directory)
        dmrpp = tmp_path / "scene.h5.dmrpp"
        locator = tmp_path / "scene.nc4"
        dmrpp.write_bytes(b"dmrpp")
        locator.write_bytes(b"locator")
        source = {
            "concept_id": "G1-LPCLOUD",
            "granule_id": "scene",
            "cmr_record_sha256": "b" * 64,
            "hdf_url": "https://data.lpdaac.earthdatacloud.nasa.gov/scene.h5",
            "dmrpp_url": "https://data.lpdaac.earthdatacloud.nasa.gov/scene.h5.dmrpp",
            "opendap_url": "https://opendap.earthdata.nasa.gov/scene",
        }
        cached = {
            "status": "complete",
            "algorithm_version": augmentation.ALGORITHM_VERSION,
            "decision_id": augmentation.DECISION_ID,
            "collection_short_name": augmentation.COLLECTION_SHORT_NAME,
            "collection_version": augmentation.COLLECTION_VERSION,
            "provider": augmentation.COLLECTION_PROVIDER,
            "collection_concept_id": augmentation.COLLECTION_CONCEPT_ID,
            **source,
            "variables": list(augmentation.ALL_GEOMETRY_VARIABLES),
            "dmrpp_size_bytes": dmrpp.stat().st_size,
            "locator_size_bytes": locator.stat().st_size,
            "dmrpp_sha256": augmentation.sha256_file(dmrpp),
            "locator_sha256": augmentation.sha256_file(locator),
        }
        assert augmentation._metadata_asset_cache_valid(source, cached, dmrpp, locator)
        cached["cmr_record_sha256"] = "c" * 64
        assert not augmentation._metadata_asset_cache_valid(source, cached, dmrpp, locator)


def _weather_record() -> dict[str, object]:
    geometry_binding = {"atlanta": "1" * 64}
    return {
        "item_id": "hrrr-sfc-f00-20200722T22Z",
        "analysis_utc": "2020-07-22T22:00:00Z",
        "cities": "atlanta",
        "n_target_passes": 1,
        "model": "hrrr",
        "product": "sfc",
        "forecast_hour": 0,
        "object_key": "hrrr.20200722/conus/hrrr.t22z.wrfsfcf00.grib2",
        "product_resolution": "primary_sfc",
        "weather_algorithm_version": augmentation.WEATHER_ALGORITHM_VERSION,
        "analysis_geometry_sha256_by_city": json.dumps(
            geometry_binding, sort_keys=True, separators=(",", ":")
        ),
        "analysis_geometry_set_sha256": augmentation._canonical_sha256(
            geometry_binding
        ),
    }


def test_weather_shard_rejects_hour_wind_and_checksum_tampering() -> None:
    with tempfile.TemporaryDirectory() as directory:
        record = _weather_record()
        path = Path(directory) / "hour.csv.gz"
        frame = pd.DataFrame(
            {
                "city": ["atlanta", "atlanta"],
                "timestamp_utc": [record["analysis_utc"], record["analysis_utc"]],
                "grid_y_index": [1, 1],
                "grid_x_index": [2, 3],
                "latitude": [33.7, 33.8],
                "longitude": [-84.4, -84.3],
                "t2m_k": [300.0, 301.0],
                "d2m_k": [290.0, 291.0],
                "vpd_kpa": [1.0, 1.1],
                "u10_m_s": [3.0, 0.0],
                "v10_m_s": [4.0, 5.0],
                "wind_speed_m_s": [5.0, 5.0],
                "weather_algorithm_version": [
                    augmentation.WEATHER_ALGORITHM_VERSION
                ] * 2,
                "analysis_geometry_sha256": ["1" * 64] * 2,
            }
        )
        frame.to_csv(path, index=False, compression="gzip")
        binding = augmentation._weather_request_binding(record)
        checkpoint = {
            "status": "complete",
            "request_binding": binding,
            "request_binding_sha256": augmentation._canonical_sha256(binding),
            "sha256": augmentation.sha256_file(path),
            "size_bytes": path.stat().st_size,
            "cities": ["atlanta"],
            "weather_algorithm_version": augmentation.WEATHER_ALGORITHM_VERSION,
            "analysis_geometry_sha256_by_city": {"atlanta": "1" * 64},
            "analysis_geometry_set_sha256": augmentation._canonical_sha256(
                {"atlanta": "1" * 64}
            ),
        }
        assert augmentation._valid_weather_shard(path, record, checkpoint) is not None
        bad = dict(checkpoint)
        bad["sha256"] = "0" * 64
        assert augmentation._valid_weather_shard(path, record, bad) is None
        bad = dict(checkpoint)
        bad["weather_algorithm_version"] = "tampered"
        assert augmentation._valid_weather_shard(path, record, bad) is None
        bad_record = dict(record)
        bad_record["analysis_geometry_sha256_by_city"] = json.dumps(
            {"atlanta": "2" * 64}
        )
        bad_record["analysis_geometry_set_sha256"] = augmentation._canonical_sha256(
            {"atlanta": "2" * 64}
        )
        assert augmentation._valid_weather_shard(path, bad_record, checkpoint) is None
        wrong_hour = frame.copy()
        wrong_hour["timestamp_utc"] = "2020-07-22T23:00:00Z"
        wrong_hour.to_csv(path, index=False, compression="gzip")
        bad = dict(checkpoint)
        bad["sha256"] = augmentation.sha256_file(path)
        bad["size_bytes"] = path.stat().st_size
        assert augmentation._valid_weather_shard(path, record, bad) is None
        bad_frame = frame.copy()
        bad_frame.loc[0, "wind_speed_m_s"] = 99.0
        bad_frame.to_csv(path, index=False, compression="gzip")
        bad = dict(checkpoint)
        bad["sha256"] = augmentation.sha256_file(path)
        bad["size_bytes"] = path.stat().st_size
        assert augmentation._valid_weather_shard(path, record, bad) is None
        bad_frame = frame.copy()
        bad_frame.loc[0, "analysis_geometry_sha256"] = "3" * 64
        bad_frame.to_csv(path, index=False, compression="gzip")
        bad = dict(checkpoint)
        bad["sha256"] = augmentation.sha256_file(path)
        bad["size_bytes"] = path.stat().st_size
        assert augmentation._valid_weather_shard(path, record, bad) is None
        bad_frame = frame.copy()
        bad_frame.loc[0, "weather_algorithm_version"] = "tampered"
        bad_frame.to_csv(path, index=False, compression="gzip")
        bad = dict(checkpoint)
        bad["sha256"] = augmentation.sha256_file(path)
        bad["size_bytes"] = path.stat().st_size
        assert augmentation._valid_weather_shard(path, record, bad) is None


def test_exact_weather_cell_extraction_adds_aligned_wind() -> None:
    latitude = np.array([[33.70, 33.70], [33.80, 33.80]])
    longitude = np.array([[-84.40, -84.30], [-84.40, -84.30]])
    coordinates = {
        "latitude": (("y", "x"), latitude),
        "longitude": (("y", "x"), longitude),
    }
    temperature = xr.Dataset(
        {
            "t2m": (("y", "x"), np.full((2, 2), 300.0)),
            "d2m": (("y", "x"), np.full((2, 2), 290.0)),
        },
        coords=coordinates,
    )
    wind = xr.Dataset(
        {
            "u10": (("y", "x"), np.full((2, 2), 3.0)),
            "v10": (("y", "x"), np.full((2, 2), 4.0)),
        },
        coords=coordinates,
    )
    cells = augmentation._extract_domain_cells_with_wind(
        temperature,
        wind,
        {"atlanta": box(-84.45, 33.65, -84.25, 33.85)},
        analysis_utc="2020-07-22T22:00:00Z",
    )
    assert len(cells) == 4
    assert np.allclose(cells["wind_speed_m_s"], 5.0)
    tampered = wind.assign_coords(longitude=(("y", "x"), longitude + 0.01))
    with _raises(ValueError):
        augmentation._extract_domain_cells_with_wind(
            temperature,
            tampered,
            {"atlanta": box(-84.45, 33.65, -84.25, 33.85)},
            analysis_utc="2020-07-22T22:00:00Z",
        )


def test_gate2_percentile_ties_and_right_open_boundaries() -> None:
    percentiles = augmentation._average_tie_reference_percentile(
        [0.0, 1.0, 1.0, 2.0], [0.0, 1.0, 2.0]
    )
    assert np.allclose(percentiles, [0.0, 0.5, 1.0])
    labels = augmentation._right_open_tercile(
        [0.0, 1 / 3, 2 / 3, 1.0], ("low", "middle", "high")
    )
    assert labels.tolist() == ["low", "middle", "high", "high"]


def test_pass_cache_rejects_document_tampering() -> None:
    binding = {
        "city": "atlanta",
        "orbit": 123,
        "decision_id": augmentation.DECISION_ID,
        "algorithm_version": augmentation.ALGORITHM_VERSION,
        "target_grid_sha256": "a" * 64,
    }
    document = {
        "status": "complete",
        "binding": binding,
        "binding_sha256": augmentation._canonical_sha256(binding),
        "scene_evidence": [],
        "summary": {
            "city": "atlanta",
            "orbit": 123,
            "decision_id": augmentation.DECISION_ID,
            "window_id": "jun_sep",
            "n_domain_pixels": 3,
            "n_view_valid_pixels": 0,
        },
    }
    with tempfile.TemporaryDirectory() as directory:
        reconstruction = Path(directory) / "reconstruction.npz"
        grid = type("Grid", (), {"size": 3})()
        document["reconstruction_artifact"] = augmentation._write_geometry_reconstruction(
            reconstruction,
            city="atlanta",
            window_id="jun_sep",
            orbit=123,
            target_grid_sha256="a" * 64,
            grids={"tile": grid},
            combined=None,
        )
        document["summary"]["geometry_reconstruction_artifact_sha256"] = document[
            "reconstruction_artifact"
        ]["sha256"]
        document["summary"]["geometry_reconstruction_artifact_size_bytes"] = document[
            "reconstruction_artifact"
        ]["size_bytes"]
        path = Path(directory) / "evidence.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        checkpoint = {
            "status": "complete",
            "binding_sha256": augmentation._canonical_sha256(binding),
            "evidence_path": str(path),
            "evidence_sha256": augmentation.sha256_file(path),
        }
        assert augmentation._validated_pass_cache(
            checkpoint,
            path,
            binding,
            expected_window_id="jun_sep",
            expected_n_domain_pixels=3,
            expected_reconstruction_path=reconstruction,
        ) is not None
        stale_binding = dict(binding, algorithm_version="stale")
        assert augmentation._validated_pass_cache(
            checkpoint, path, stale_binding,
            expected_window_id="jun_sep",
            expected_n_domain_pixels=3,
            expected_reconstruction_path=reconstruction,
        ) is None
        stale_checkpoint = dict(checkpoint, evidence_sha256="0" * 64)
        assert augmentation._validated_pass_cache(
            stale_checkpoint, path, binding,
            expected_window_id="jun_sep",
            expected_n_domain_pixels=3,
            expected_reconstruction_path=reconstruction,
        ) is None
        document["summary"]["orbit"] = 124
        path.write_text(json.dumps(document), encoding="utf-8")
        checkpoint["evidence_sha256"] = augmentation.sha256_file(path)
        assert augmentation._validated_pass_cache(
            checkpoint,
            path,
            binding,
            expected_window_id="jun_sep",
            expected_n_domain_pixels=3,
            expected_reconstruction_path=reconstruction,
        ) is None


def test_generated_zero_map_cache_requires_corrected_proof_schema() -> None:
    binding = {
        "city": "atlanta",
        "orbit": 123,
        "decision_id": augmentation.DECISION_ID,
        "algorithm_version": augmentation.ALGORITHM_VERSION,
        "target_grid_sha256": "a" * 64,
    }
    scene = augmentation.finalize_initial_selection_proof(
        {
            "granule_id": "ECOv002_L1B_GEO_00123_004_20200722T225220_0712_01",
            "proof_mode": "verified_no_overlap",
            "boundary_minimum_domain_distance_m": 311.0,
            "final_chunk_count": 1,
            "range_request_count": 1,
            "selected_compressed_chunks_sha256": "b" * 64,
            "range_evidence_sha256": "c" * 64,
            "missing_scene_substitution_used": False,
            "missing_scene_zero_coverage_assigned": False,
        },
        full_resolution_boundary_verified=True,
        mapped_target_cell_count=0,
    )
    with tempfile.TemporaryDirectory() as directory:
        reconstruction = Path(directory) / "reconstruction.npz"
        document = {
            "status": "complete",
            "binding": binding,
            "binding_sha256": augmentation._canonical_sha256(binding),
            "scene_evidence": [scene],
            "summary": {
                "city": "atlanta",
                "orbit": 123,
                "decision_id": augmentation.DECISION_ID,
                "window_id": "jun_sep",
                "source_population": "new_d0069",
                "n_domain_pixels": 3,
                "n_view_valid_pixels": 0,
                "geometry_azimuth_complete": True,
                "geometry_azimuth_status": "RESOLVED_VERIFIED_ZERO_MAPPED_CELLS",
            },
        }
        grid = type("Grid", (), {"size": 3})()
        document["reconstruction_artifact"] = augmentation._write_geometry_reconstruction(
            reconstruction,
            city="atlanta",
            window_id="jun_sep",
            orbit=123,
            target_grid_sha256="a" * 64,
            grids={"tile": grid},
            combined=None,
        )
        document["summary"]["geometry_reconstruction_artifact_sha256"] = document[
            "reconstruction_artifact"
        ]["sha256"]
        document["summary"]["geometry_reconstruction_artifact_size_bytes"] = document[
            "reconstruction_artifact"
        ]["size_bytes"]
        path = Path(directory) / "evidence.json"

        def checkpoint() -> dict[str, object]:
            path.write_text(json.dumps(document), encoding="utf-8")
            return {
                "status": "complete",
                "binding_sha256": augmentation._canonical_sha256(binding),
                "evidence_path": str(path),
                "evidence_sha256": augmentation.sha256_file(path),
            }

        assert augmentation._validated_pass_cache(
            checkpoint(), path, binding,
            expected_window_id="jun_sep",
            expected_n_domain_pixels=3,
            expected_reconstruction_path=reconstruction,
        ) is None
        document["zero_map_proof_schema_version"] = (
            augmentation.ZERO_MAP_PROOF_SCHEMA_VERSION
        )
        assert augmentation._validated_pass_cache(
            checkpoint(), path, binding,
            expected_window_id="jun_sep",
            expected_n_domain_pixels=3,
            expected_reconstruction_path=reconstruction,
        ) is not None


def test_zero_mapped_reuse_binds_grid_source_and_strict_scene_proof() -> None:
    with tempfile.TemporaryDirectory() as directory:
        tmp_path = Path(directory)
        dmrpp_root = tmp_path / "dmrpp"
        locator_root = tmp_path / "locator"
        dmrpp_root.mkdir()
        locator_root.mkdir()
        previous_dmrpp = augmentation.EXISTING_DMRPP
        previous_locator = augmentation.EXISTING_LOCATOR
        augmentation.EXISTING_DMRPP = dmrpp_root
        augmentation.EXISTING_LOCATOR = locator_root
        granule = "ECOv002_L1B_GEO_00123_004_20200722T225220_0712_01"
        dmrpp = dmrpp_root / f"{granule}.h5.dmrpp"
        locator = locator_root / f"{granule}_stride32.nc4"
        dmrpp.write_bytes(b"dmrpp")
        locator.write_bytes(b"locator")
        scene = {
            "granule_id": granule,
            "orbit": 123,
            "scene": 4,
            "cmr_record_sha256": "d" * 64,
            "collection_concept_id": augmentation.COLLECTION_CONCEPT_ID,
            "dmrpp_sha256": augmentation.sha256_file(dmrpp),
            "locator_sha256": augmentation.sha256_file(locator),
            "dmrpp_size_bytes": dmrpp.stat().st_size,
            "locator_size_bytes": locator.stat().st_size,
        }
        binding = {
            "algorithm_version": augmentation.D0047_ALGORITHM_VERSION,
            "city": "atlanta",
            "orbit": 123,
            "acquisition_utc": "2020-07-22T22:52:20Z",
            "target_grid_sha256": "e" * 64,
            "radius_m": augmentation.RADIUS_OF_INFLUENCE_M,
            "boundary_guard_m": augmentation.BOUNDARY_GUARD_DISTANCE_M,
            "scene_bindings": [scene],
        }
        document = {
            "status": "complete",
            "decision_id": "D0047",
            "collection_short_name": augmentation.COLLECTION_SHORT_NAME,
            "collection_version": augmentation.COLLECTION_VERSION,
            "algorithm_version": augmentation.D0047_ALGORITHM_VERSION,
            "variables": list(augmentation.GEOMETRY_VARIABLES),
            "full_resolution": True,
            "boundary_verified": True,
            "binding": binding,
            "binding_sha256": augmentation._canonical_sha256(binding),
            "summary": {
                "city": "atlanta",
                "orbit": 123,
                "n_domain_pixels": 10,
                "n_view_valid_pixels": 0,
                "n_l1b_geo_scenes": 1,
                "l1b_geometry_coverage_fraction": 0.0,
                "l1b_geometry_complete": True,
                "geometry_definitive": True,
                "quality_candidate_pre_cloud_geometry_only": False,
            },
            "scene_evidence": [{
                **scene,
                "proof_status": "verified_no_domain_overlap",
                "mapped_target_cell_count": 0,
                "full_resolution_boundary_verified": True,
                "boundary_verified": True,
                "boundary_minimum_domain_distance_m": 311.0,
                "proof_mode": "verified_no_overlap",
                "proof_acceptance_status": "verified_no_overlap_mapped_zero",
                "verified_no_overlap_mapped_zero": True,
                "verified_no_overlap_zero_imputed": False,
                "missing_scene_zero_coverage_assigned": False,
                "missing_scene_substitution_used": False,
                "final_chunk_count": 1,
                "range_request_count": 1,
                "selected_compressed_chunks_sha256": "a" * 64,
                "range_evidence_sha256": "b" * 64,
            }],
        }
        candidate = {
            "city": "atlanta",
            "orbit": 123,
            "acquisition_utc": "2020-07-22T22:52:20Z",
        }
        augmentation._validated_no_overlap_reuse(
            candidate,
            document,
            target_grid_sha256="e" * 64,
            n_domain_pixels=10,
            expected_scene_census={(123, 4, granule)},
        )
        with _raises(ValueError):
            augmentation._validated_no_overlap_reuse(
                candidate,
                document,
                target_grid_sha256="e" * 64,
                n_domain_pixels=10,
                expected_scene_census={(123, 5, granule)},
            )
        no_overlap_imputed = json.loads(json.dumps(document))
        no_overlap_imputed["scene_evidence"][0]["verified_no_overlap_zero_imputed"] = True
        with _raises(ValueError):
            augmentation._validated_no_overlap_reuse(
                candidate,
                no_overlap_imputed,
                target_grid_sha256="e" * 64,
                n_domain_pixels=10,
            )
        no_overlap_unverified = json.loads(json.dumps(document))
        no_overlap_unverified["scene_evidence"][0]["full_resolution_boundary_verified"] = False
        with _raises(ValueError):
            augmentation._validated_no_overlap_reuse(
                candidate,
                no_overlap_unverified,
                target_grid_sha256="e" * 64,
                n_domain_pixels=10,
            )
        near_domain = json.loads(json.dumps(document))
        near_domain["scene_evidence"][0]["proof_status"] = (
            "near_domain_full_resolution_verified"
        )
        near_domain["scene_evidence"][0].update(
            {
                "proof_mode": "locator_near_domain",
                "proof_acceptance_status": "ordinary_near_domain_mapping",
                "boundary_verified": True,
                "boundary_minimum_domain_distance_m": 311.0,
                "final_chunk_count": 1,
                "range_request_count": 1,
                "selected_compressed_chunks_sha256": "a" * 64,
                "range_evidence_sha256": "b" * 64,
                "missing_scene_substitution_used": False,
                "missing_scene_zero_coverage_assigned": False,
                "verified_no_overlap_zero_imputed": False,
                "verified_no_overlap_mapped_zero": False,
            }
        )
        augmentation._validated_no_overlap_reuse(
            candidate, near_domain, target_grid_sha256="e" * 64, n_domain_pixels=10
        )
        downgraded = json.loads(json.dumps(near_domain))
        downgraded["scene_evidence"][0]["proof_status"] = "verified_no_domain_overlap"
        with _raises(ValueError):
            augmentation._validated_no_overlap_reuse(
                candidate, downgraded, target_grid_sha256="e" * 64, n_domain_pixels=10
            )
        mapped = json.loads(json.dumps(near_domain))
        mapped["scene_evidence"][0]["mapped_target_cell_count"] = 1
        try:
            augmentation._validated_no_overlap_reuse(
                candidate, mapped, target_grid_sha256="e" * 64, n_domain_pixels=10
            )
        except ValueError as exc:
            assert "mapped_target_cell_count=1, expected 0" in str(exc)
        else:
            raise AssertionError("Positive mapped count was accepted as zero-mapped proof")
        unverified = json.loads(json.dumps(near_domain))
        unverified["scene_evidence"][0]["full_resolution_boundary_verified"] = False
        try:
            augmentation._validated_no_overlap_reuse(
                candidate, unverified, target_grid_sha256="e" * 64, n_domain_pixels=10
            )
        except ValueError as exc:
            assert "full_resolution_boundary_verified is not true" in str(exc)
        else:
            raise AssertionError("Unverified full-resolution boundary was accepted")
        inside_guard = json.loads(json.dumps(near_domain))
        inside_guard["scene_evidence"][0]["boundary_minimum_domain_distance_m"] = 310.0
        with _raises(ValueError):
            augmentation._validated_no_overlap_reuse(
                candidate, inside_guard, target_grid_sha256="e" * 64, n_domain_pixels=10
            )
        imputed = json.loads(json.dumps(near_domain))
        imputed["scene_evidence"][0]["verified_no_overlap_zero_imputed"] = True
        with _raises(ValueError):
            augmentation._validated_no_overlap_reuse(
                candidate, imputed, target_grid_sha256="e" * 64, n_domain_pixels=10
            )
        unhashed = json.loads(json.dumps(near_domain))
        unhashed["scene_evidence"][0]["range_evidence_sha256"] = ""
        with _raises(ValueError):
            augmentation._validated_no_overlap_reuse(
                candidate, unhashed, target_grid_sha256="e" * 64, n_domain_pixels=10
            )
        bad_status = json.loads(json.dumps(near_domain))
        bad_status["scene_evidence"][0]["proof_status"] = "ordinary_near_domain_mapping"
        try:
            augmentation._validated_no_overlap_reuse(
                candidate, bad_status, target_grid_sha256="e" * 64, n_domain_pixels=10
            )
        except ValueError as exc:
            assert "unsupported proof_status" in str(exc)
        else:
            raise AssertionError("Unsupported scene proof status was accepted")
        with _raises(ValueError):
            augmentation._validated_no_overlap_reuse(
                candidate, document, target_grid_sha256="f" * 64, n_domain_pixels=10
            )
        augmentation.EXISTING_DMRPP = previous_dmrpp
        augmentation.EXISTING_LOCATOR = previous_locator


def test_generated_zero_mapped_proof_carries_both_boundary_seals() -> None:
    proof = {
        "granule_id": "ECOv002_L1B_GEO_00123_004_20200722T225220_0712_01",
        "proof_mode": "verified_no_overlap",
        "boundary_minimum_domain_distance_m": 311.0,
        "final_chunk_count": 1,
        "range_request_count": 1,
        "selected_compressed_chunks_sha256": "a" * 64,
        "range_evidence_sha256": "b" * 64,
        "missing_scene_substitution_used": False,
        "missing_scene_zero_coverage_assigned": False,
    }
    finalized = augmentation.finalize_initial_selection_proof(
        proof,
        full_resolution_boundary_verified=True,
        mapped_target_cell_count=0,
    )
    assert finalized["full_resolution_boundary_verified"] is True
    assert finalized["boundary_verified"] is True
    assert augmentation._accepted_zero_mapped_scene_proof(finalized)


def test_atlanta_17605_is_a_real_boundary_verified_zero_mapped_pass() -> None:
    path = augmentation.EXISTING_PASS_EVIDENCE / "atlanta" / "17605.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    summary = document["summary"]
    binding = document["binding"]
    assert summary["n_view_valid_pixels"] == 0
    assert len(document["scene_evidence"]) == 1
    assert document["scene_evidence"][0]["proof_status"] == (
        "near_domain_full_resolution_verified"
    )
    assert augmentation._accepted_zero_mapped_scene_proof(
        document["scene_evidence"][0]
    )
    augmentation._validated_no_overlap_reuse(
        {
            "city": "atlanta",
            "orbit": 17605,
            "acquisition_utc": summary["acquisition_utc"],
        },
        document,
        target_grid_sha256=binding["target_grid_sha256"],
        n_domain_pixels=summary["n_domain_pixels"],
    )


def _pass_rows(start_orbit: int, count: int, *, status: str | None = None) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "city": ["denver_aurora"] * count,
            "window_id": ["jun_sep"] * count,
            "orbit": np.arange(start_orbit, start_orbit + count),
            "acquisition_utc": pd.date_range(
                "2020-06-01T12:30:00Z", periods=count, freq="D"
            ),
            "year": [2020] * count,
            "source_population": ["new_d0069"] * count,
        }
    )
    if status is not None:
        frame["archive_status"] = status
    return frame


def test_weather_manifest_binds_algorithm_and_exact_repaired_domains() -> None:
    geometry = {
        "type": "Polygon",
        "coordinates": [[[-84.5, 33.6], [-84.2, 33.6], [-84.2, 33.9], [-84.5, 33.6]]],
    }
    population = _pass_rows(1, 1)
    population["city"] = "atlanta"
    manifest = augmentation._weather_manifest_for_population(
        population, {"atlanta": geometry}
    )
    record = manifest.iloc[0].to_dict()
    binding = augmentation._weather_request_binding(record)
    assert binding["weather_algorithm_version"] == augmentation.WEATHER_ALGORITHM_VERSION
    assert binding["analysis_geometry_sha256_by_city"] == {
        "atlanta": augmentation.sha256_json(geometry)
    }
    tampered = dict(record)
    tampered["analysis_geometry_set_sha256"] = "0" * 64
    with _raises(ValueError):
        augmentation._weather_request_binding(tampered)
    tampered = dict(record)
    tampered["weather_algorithm_version"] = "old-algorithm"
    with _raises(ValueError):
        augmentation._weather_request_binding(tampered)


def test_live_storage_preflight_uses_free_space_estimate_and_reserve() -> None:
    class Usage:
        def __init__(self, free: int) -> None:
            self.free = free

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        evidence = root / "preflight.json"
        payload = augmentation._live_hrrr_storage_preflight(
            2_000,
            storage_root=root,
            reserve_bytes=1_000,
            evidence_path=evidence,
            disk_usage=lambda _: Usage(3_000),
            estimate_sha256="a" * 64,
        )
        assert payload["status"] == "PASS"
        assert payload["required_free_bytes"] == 3_000
        assert json.loads(evidence.read_text(encoding="utf-8"))["status"] == "PASS"
        with _raises(RuntimeError):
            augmentation._live_hrrr_storage_preflight(
                2_000,
                storage_root=root,
                reserve_bytes=1_001,
                evidence_path=evidence,
                disk_usage=lambda _: Usage(3_000),
            )
        failed = json.loads(evidence.read_text(encoding="utf-8"))
        assert failed["status"] == "FAIL_INSUFFICIENT_FREE_SPACE"
        with _raises(RuntimeError):
            augmentation._live_hrrr_storage_preflight(
                1,
                storage_root=root,
                reserve_bytes=0,
                evidence_path=None,
                disk_usage=lambda _: (_ for _ in ()).throw(OSError("unavailable")),
            )


def test_weather_split_preserves_disjoint_censuses_and_upper_labels() -> None:
    qualifiers = _pass_rows(1, 2)
    unavailable = _pass_rows(101, 2, status="RESOLVED_UNAVAILABLE")
    labelled = pd.concat([qualifiers, unavailable], ignore_index=True)
    labelled["local_solar_date"] = pd.to_datetime(labelled["acquisition_utc"]).dt.date
    labelled["day_of_window"] = [1, 2, 3, 4]
    labelled["time_stratum"] = "10-12"
    labelled["vpd_kpa_at_acquisition"] = 2.0
    labelled["air_temperature_k_at_acquisition"] = 300.0
    labelled["wind_speed_m_s_at_acquisition"] = 5.0
    labelled["antecedent_precipitation_30d_mm"] = 20.0
    labelled["demand_percentile"] = 0.8
    labelled["demand_level"] = "high"
    labelled["antecedent_precipitation_30d_wetness_percentile"] = 0.2
    labelled["wetness_level"] = "dry"
    labelled["exact_weather_complete"] = True
    labelled["decision_id"] = augmentation.DECISION_ID
    labelled["temperature_or_lst_opened"] = False
    labelled["record_2026_opened"] = False
    observed, upper = augmentation._split_weather_outputs(
        labelled, qualifiers, unavailable
    )
    assert len(observed) == 2 and len(upper) == 2
    assert set(observed["orbit"]) == {1, 2}
    assert set(upper["orbit"]) == {101, 102}
    assert upper["archive_bound_role"].eq(
        "UPPER_BOUND_ONLY_RESOLVED_UNAVAILABLE"
    ).all()
    assert upper["archive_status"].eq("RESOLVED_UNAVAILABLE").all()
    assert upper["demand_level"].eq("high").all()
    assert upper["wetness_level"].eq("dry").all()
    assert upper["upper_bound_only"].all()
    assert not upper["geometry_observed"].any()
    assert not upper["cloud_observed"].any()
    assert not upper["selection_eligible_observation"].any()


def test_weather_split_and_manifest_reject_double_count() -> None:
    qualifiers = _pass_rows(1, 2)
    unavailable = qualifiers.iloc[[0]].assign(archive_status="RESOLVED_UNAVAILABLE")
    labelled = qualifiers.copy()
    with _raises(ValueError):
        augmentation._split_weather_outputs(labelled, qualifiers, unavailable)
    duplicated = pd.concat([qualifiers, qualifiers.iloc[[0]]], ignore_index=True)
    with _raises(ValueError):
        augmentation._weather_manifest_for_population(duplicated)


def test_unresolved_archive_status_is_fatal() -> None:
    frame = _pass_rows(1, augmentation.EXPECTED_NEW_PASS_COUNT)
    frame["city"] = "denver_aurora"
    frame["window_id"] = "jun_sep"
    frame.loc[200:, "city"] = "phoenix"
    frame.loc[200:, "window_id"] = "phoenix_apr_may"
    frame["archive_status"] = "ACCESSIBLE"
    frame.loc[0, "archive_status"] = "UNRESOLVED_ERROR"
    original = augmentation._new_passes_and_targets
    original_derive = augmentation._derive_new_pass_archive_status
    augmentation._new_passes_and_targets = lambda: (frame.copy(), pd.DataFrame(), pd.DataFrame())
    augmentation._derive_new_pass_archive_status = (
        lambda passes, links, manifest: frame.copy()
    )
    try:
        with _raises(RuntimeError):
            augmentation._validated_new_archive_status(
                frame, expected_unavailable=None, fail_on_unresolved=True
            )
    finally:
        augmentation._new_passes_and_targets = original
        augmentation._derive_new_pass_archive_status = original_derive


def test_archive_status_known_answer_and_same_count_swap_rejected() -> None:
    passes, _, links = augmentation._new_passes_and_targets()
    manifest = pd.read_csv(augmentation.NEW_SCENE_MANIFEST)
    derived = augmentation._derive_new_pass_archive_status(passes, links, manifest)
    assert derived["archive_status"].value_counts().to_dict() == {
        "ACCESSIBLE": 288,
        "RESOLVED_UNAVAILABLE": 12,
    }
    assert derived.groupby(["city", "archive_status"]).size().to_dict() == {
        ("denver_aurora", "ACCESSIBLE"): 220,
        ("denver_aurora", "RESOLVED_UNAVAILABLE"): 9,
        ("phoenix", "ACCESSIBLE"): 68,
        ("phoenix", "RESOLVED_UNAVAILABLE"): 3,
    }
    statuses = derived.set_index(["city", "orbit"])["archive_status"]
    assert statuses.loc[("denver_aurora", 345)] == "ACCESSIBLE"
    assert statuses.loc[("denver_aurora", 11040)] == "RESOLVED_UNAVAILABLE"
    swapped = derived.copy()
    first = swapped["city"].eq("denver_aurora") & swapped["orbit"].eq(345)
    second = swapped["city"].eq("denver_aurora") & swapped["orbit"].eq(11040)
    swapped.loc[first, "archive_status"] = "RESOLVED_UNAVAILABLE"
    swapped.loc[second, "archive_status"] = "ACCESSIBLE"
    assert swapped["archive_status"].value_counts().to_dict() == derived[
        "archive_status"
    ].value_counts().to_dict()
    with _raises(ValueError):
        augmentation._validated_new_archive_status(
            swapped, expected_unavailable=None, fail_on_unresolved=True
        )


def test_archive_status_derivation_rejects_missing_scene_and_exposes_query_error() -> None:
    passes, _, links = augmentation._new_passes_and_targets()
    manifest = pd.read_csv(augmentation.NEW_SCENE_MANIFEST)
    with _raises(ValueError):
        augmentation._derive_new_pass_archive_status(
            passes, links, manifest.iloc[:-1].copy()
        )
    errored = manifest.copy()
    errored["cmr_query_error_type"] = errored["cmr_query_error_type"].astype("string")
    errored.loc[0, "cmr_query_error_type"] = "TimeoutError"
    derived = augmentation._derive_new_pass_archive_status(passes, links, errored)
    affected_orbit = int(links.loc[
        links["orbit"].eq(int(errored.loc[0, "orbit"]))
        & links["scene"].eq(int(errored.loc[0, "scene"])),
        "orbit",
    ].iloc[0])
    affected_city = str(links.loc[
        links["orbit"].eq(int(errored.loc[0, "orbit"]))
        & links["scene"].eq(int(errored.loc[0, "scene"])),
        "city",
    ].iloc[0])
    state = derived.loc[
        derived["city"].eq(affected_city) & derived["orbit"].eq(affected_orbit),
        "archive_status",
    ].item()
    assert state == "UNRESOLVED_ERROR"


def test_unavailable_pass_receives_canonical_demand_and_wet_labels() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        daily_path = root / "daily.csv"
        passes_path = root / "passes.csv"
        dates = pd.date_range("2020-05-01", "2020-09-30", freq="D")
        daily = pd.DataFrame(
            {
                "city": "denver_aurora",
                "date": dates,
                "pr_mm": np.arange(1, len(dates) + 1, dtype=float),
                "eto_mm": 1.0,
                "vpd_kpa": np.arange(1, len(dates) + 1, dtype=float),
                "tmmx_k": 300.0,
            }
        )
        daily.to_csv(daily_path, index=False)
        pd.DataFrame(
            {
                "city": ["denver_aurora"],
                "orbit": [90001],
                "time_stratum": ["10-12"],
            }
        ).to_csv(passes_path, index=False)
        previous_daily = augmentation.DAILY_GRIDMET
        previous_passes = augmentation.NEW_PASSES
        augmentation.DAILY_GRIDMET = daily_path
        augmentation.NEW_PASSES = passes_path
        try:
            unavailable = pd.DataFrame(
                {
                    "city": ["denver_aurora"],
                    "window_id": ["jun_sep"],
                    "orbit": [90001],
                    "acquisition_utc": ["2020-09-15T18:00:00Z"],
                    "year": [2020],
                    "source_population": ["new_d0069"],
                    "archive_status": ["RESOLVED_UNAVAILABLE"],
                    "vpd_kpa_at_acquisition": [float(len(dates))],
                    "air_temperature_k_at_acquisition": [300.0],
                    "wind_speed_m_s_at_acquisition": [5.0],
                }
            )
            features = {
                "denver_aurora": {"properties": {"CENTLON": -105.0}}
            }
            labelled = augmentation._condition_labels(unavailable, features)
        finally:
            augmentation.DAILY_GRIDMET = previous_daily
            augmentation.NEW_PASSES = previous_passes
        assert labelled.iloc[0]["demand_level"] == "high"
        assert labelled.iloc[0]["wetness_level"] == "wet"
        assert bool(labelled.iloc[0]["exact_weather_complete"])


def main() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
    print(f"PASS test_v2_hitl_gate3_second_augmentation ({len(tests)} tests)")


if __name__ == "__main__":
    main()
