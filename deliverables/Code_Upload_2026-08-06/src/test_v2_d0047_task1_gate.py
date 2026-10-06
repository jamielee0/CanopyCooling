#!/usr/bin/env python3
"""Network-free adversarial tests for the D0047 Task-1/Task-2 boundary."""

from __future__ import annotations

from copy import deepcopy
import csv
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_v2_task2_guardrails import (  # noqa: E402
    BoundFixture,
    HRRR_SEARCH,
    HRRR_SOURCE,
    _json_hash,
    _ready_config,
    _write_csv,
    _write_json,
)
from urban_cooling_v2.task1_pass_gate import (  # noqa: E402
    D0047_CERTIFIED_COUNT_STATUS,
    D0047_HRRR_PASS_STATUS,
    D0047_PASS_STATUS,
    Task1GateError,
    sha256_file,
    validate_canonical_task1_pass,
    write_d0047_canonical_task1_pass,
)
from urban_cooling_v2.task2_guardrails import evaluate_preflight  # noqa: E402


ANALYSIS_PROFILE = "D0047_archive_available"
SCIENTIFIC_SCOPE = "archive_available_only"
PROFILE_SCOPE = "archive_available_after_pre_geometry_exclusion_D0047"
ALGORITHM = "d0047-archive-available-l1b-dmrpp-pass-stream-v1"
RETAINED_STATUS = "retained_archive_available"
EXCLUDED_STATUS = "archive_unavailable_pre_geometry"
D0053_HRRR_SOURCE = (
    "NOAA HRRR public AWS archive; exact analysis f00 2-m fields; "
    "sfc with frozen prs fallback"
)
D0053_FALLBACK_HOURS = frozenset(
    {
        "20180728T23Z",
        "20180802T23Z",
        "20180807T19Z",
        "20180815T23Z",
    }
)
D0053_MANIFEST_FIELDS = [
    "item_id",
    "analysis_utc",
    "cities",
    "n_target_passes",
    "model",
    "product",
    "forecast_hour",
    "variable_search",
    "source",
    "object_key",
    "product_resolution",
]

ORIGINAL_BY_CITY = {
    "atlanta": 196,
    "los_angeles": 196,
    "miami": 91,
    "minneapolis_st_paul": 266,
    "phoenix": 193,
}
EXCLUDED_BY_CITY = {
    "atlanta": 8,
    "los_angeles": 8,
    "miami": 1,
    "minneapolis_st_paul": 8,
    "phoenix": 6,
}
RETAINED_BY_CITY = {
    city: ORIGINAL_BY_CITY[city] - EXCLUDED_BY_CITY[city]
    for city in ORIGINAL_BY_CITY
}


class D0047BoundFixture(BoundFixture):
    """Compact local fixture with every D0047 hash and count relationship."""

    def __init__(self, root: Path, *, diagnostic_status: str = "PASS") -> None:
        self.root = root.resolve()
        self.paths: dict[str, Path] = {}
        self._build_preserved_d0035_stop()
        self._build_d0046()
        self._build_d0047_quality()
        self._build_d0053_hrrr()
        self._scope_hrrr_to_d0047()
        self._build_d0047_step2()
        self._build_d0047_step3(diagnostic_status=diagnostic_status)

    def _build_d0053_hrrr(self) -> None:
        root = self.root / "weather/exact_hrrr"
        manifest_path = self.root / "weather/hrrr_manifest.csv"
        index_path = root / "hrrr_hourly_shard_index.csv"
        summary_path = root / "hrrr_hourly_domain_summary.csv"
        checkpoint_path = root / "hrrr_checkpoint.json"
        seal_path = root / "hrrr_run_seal.json"
        fallback_hours = [
            datetime.strptime(value, "%Y%m%dT%HZ").replace(tzinfo=timezone.utc)
            for value in sorted(D0053_FALLBACK_HOURS)
        ]
        primary_start = datetime(2019, 1, 1, tzinfo=timezone.utc)
        primary_hours = [primary_start + timedelta(hours=index) for index in range(409)]
        analysis_hours = sorted([*fallback_hours, *primary_hours])
        domain_sha = "8" * 64
        manifest_rows: list[dict] = []
        bindings: list[dict] = []
        checkpoint_items: dict[str, dict] = {}
        index_rows: list[dict] = []
        summary_rows: list[dict] = []
        shard_set: list[dict] = []

        for timestamp in analysis_hours:
            timestamp_key = timestamp.strftime("%Y%m%dT%HZ")
            fallback = timestamp_key in D0053_FALLBACK_HOURS
            product = "prs" if fallback else "sfc"
            object_stem = "wrfprs" if fallback else "wrfsfc"
            resolution = (
                "frozen_prs_fallback_for_missing_official_sfc_object"
                if fallback
                else "primary_sfc"
            )
            item_id = f"hrrr-{product}-f00-{timestamp:%Y%m%dT%H}Z"
            object_key = (
                f"hrrr.{timestamp:%Y%m%d}/conus/"
                f"hrrr.t{timestamp:%H}z.{object_stem}f00.grib2"
            )
            grib_url = (
                "https://noaa-hrrr-bdp-pds.s3.amazonaws.com/" + object_key
            )
            manifest_rows.append(
                {
                    "item_id": item_id,
                    "analysis_utc": timestamp.isoformat(sep=" "),
                    "cities": "phoenix",
                    "n_target_passes": 1,
                    "model": "hrrr",
                    "product": product,
                    "forecast_hour": 0,
                    "variable_search": HRRR_SEARCH,
                    "source": D0053_HRRR_SOURCE,
                    "object_key": object_key,
                    "grib_url": grib_url,
                    "index_url": grib_url + ".idx",
                    "product_resolution": resolution,
                }
            )
            binding = {
                "item_id": item_id,
                "analysis_utc": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "cities": "phoenix",
                "n_target_passes": 1,
                "model": "hrrr",
                "product": product,
                "forecast_hour": 0,
                "variable_search": HRRR_SEARCH,
                "source": D0053_HRRR_SOURCE,
                "object_key": object_key,
                "product_resolution": resolution,
            }
            bindings.append(binding)
            request_sha = _json_hash(binding)
            shard_path = root / "hourly_domain_cells" / f"{item_id}.csv.gz"
            shard_path.parent.mkdir(parents=True, exist_ok=True)
            shard_path.write_bytes(b"sealed test shard\n")
            shard_sha = sha256_file(shard_path)
            city_counts = {"phoenix": 2}
            checkpoint_items[item_id] = {
                "schema_version": 3,
                "shard_schema_version": 1,
                "status": "complete",
                "frozen_domain_sha256": domain_sha,
                "request_binding": binding,
                "request_sha256": request_sha,
                "shard_columns": ["city", "timestamp_utc"],
                "local_path": str(shard_path),
                "size_bytes": shard_path.stat().st_size,
                "sha256": shard_sha,
                "n_rows": 2,
                "city_row_counts": city_counts,
            }
            index_rows.append(
                {
                    "schema_version": 3,
                    "shard_schema_version": 1,
                    "item_id": item_id,
                    "analysis_utc": timestamp.isoformat(sep=" "),
                    "cities": "phoenix",
                    "n_target_passes": 1,
                    "model": "hrrr",
                    "product": product,
                    "product_resolution": resolution,
                    "forecast_hour": 0,
                    "variable_search": HRRR_SEARCH,
                    "object_key": object_key,
                    "request_sha256": request_sha,
                    "frozen_domain_sha256": domain_sha,
                    "local_path": str(shard_path),
                    "size_bytes": shard_path.stat().st_size,
                    "sha256": shard_sha,
                    "n_rows": 2,
                    "city_row_counts": json.dumps(city_counts, separators=(",", ":")),
                    "source": D0053_HRRR_SOURCE,
                }
            )
            summary_rows.append(
                {
                    "city": "phoenix",
                    "timestamp_utc": timestamp.isoformat(sep=" "),
                    "vpd_kpa": 1.5,
                    "vpd_kpa_median": 1.5,
                    "vpd_kpa_std": 0.1,
                    "vpd_kpa_p10": 1.4,
                    "vpd_kpa_p90": 1.6,
                    "vpd_kpa_min": 1.4,
                    "vpd_kpa_max": 1.6,
                    "t2m_k": 305.0,
                    "d2m_k": 290.0,
                    "n_domain_cells": 2,
                    "source": D0053_HRRR_SOURCE,
                    "domain_cell_rule": (
                        "HRRR grid-cell center covered by frozen Census Urban Area"
                    ),
                }
            )
            shard_set.append(
                {
                    "item_id": item_id,
                    "request_sha256": request_sha,
                    "sha256": shard_sha,
                    "n_rows": 2,
                    "city_row_counts": city_counts,
                }
            )

        _write_csv(manifest_path, manifest_rows)
        _write_csv(index_path, index_rows)
        _write_csv(summary_path, summary_rows)
        manifest_sha = _json_hash(bindings)
        checkpoint = {
            "schema_version": 3,
            "checkpoint_kind": "hrrr_exact_acquisition_domain_shards",
            "manifest_sha256": manifest_sha,
            "frozen_domain_sha256": domain_sha,
            "shard_schema_version": 1,
            "minimum_domain_cells": 2,
            "items": checkpoint_items,
        }
        _write_json(checkpoint_path, checkpoint)
        seal = {
            "schema_version": 2,
            "status": "PASS_EXACT_HRRR_RUN_SEAL",
            "manifest_path": str(manifest_path),
            "manifest_file_sha256": sha256_file(manifest_path),
            "manifest_canonical_sha256": manifest_sha,
            "manifest_fields": D0053_MANIFEST_FIELDS,
            "frozen_domain_sha256": domain_sha,
            "domain_names": ["phoenix"],
            "minimum_domain_cells": 2,
            "checkpoint_path": str(checkpoint_path),
            "checkpoint_sha256": sha256_file(checkpoint_path),
            "shard_index_path": str(index_path),
            "shard_index_sha256": sha256_file(index_path),
            "summary_path": str(summary_path),
            "summary_sha256": sha256_file(summary_path),
            "shard_set_sha256": _json_hash(shard_set),
            "counts": {
                "manifest_items": 413,
                "checkpoint_items": 413,
                "shard_index_rows": 413,
                "summary_rows": 413,
                "shard_cell_rows": 826,
                "requested_city_hours": 413,
            },
            "checkpoint_schema_version": 3,
            "shard_schema_version": 1,
            "lst_opened": False,
            "thermal_opened": False,
            "record_2026_opened": False,
            "holdout_status": "UNSELECTED",
        }
        _write_json(seal_path, seal)
        self.hrrr_seal = seal
        self.paths.update(
            {
                "hrrr_run_seal": seal_path,
                "hrrr_manifest": manifest_path,
                "hrrr_shard_index": index_path,
                "hrrr_summary": summary_path,
            }
        )

    def _build_preserved_d0035_stop(self) -> None:
        combined_path = self.root / "evidence/d0035_stop/combined_validation.json"
        run_path = self.root / "evidence/d0035_stop/run_record.json"
        combined = {
            "decision_id": "D0035",
            "expected_metadata_candidates": 942,
            "resolved_geometry_candidate_count": 0,
            "definitive_geometry_status_count": 0,
            "unresolved_geometry_candidate_count": 942,
            "geometry_source": "ECO_L1B_GEO.002",
            "geometry_complete": False,
            "candidate_seal_geometry_only": False,
            "candidate_view_mask_cloud_independent": False,
            "view_gate_cloud_conditioned": False,
            "geometry_passing_candidate_count": 0,
            "scientific_gate_eligible": False,
            "geometry_failure_stage": "scene_manifest",
            "geometry_error_type": "41_unresolved_scene_identities",
            "gate_status": "STOP_D0035_INCOMPLETE_GEOMETRY",
            "canonical_status": "STOP_D0035_INCOMPLETE_GEOMETRY",
            "lst_opened": False,
            "thermal_opened": False,
            "record_2026_opened": False,
            "holdout_status": "UNSELECTED",
            "frozen_years": "2018-2025",
            "expected_cloud_candidates": 0,
            "resolved_cloud_candidate_count": 0,
            "finite_cloud_fraction_count": 0,
            "cloud_complete": False,
            "cloud_extrapolation_used": False,
            "planning_pass_equivalent_sum": None,
            "planning_pass_equivalent_floor": None,
            "combined_complete": False,
        }
        _write_json(combined_path, combined)
        combined_sha = sha256_file(combined_path)
        run = {
            "schema_version": 2,
            "run_id": "R0004_D0035",
            "decision_id": "D0035",
            "implementation_decision_id": "D0036",
            "algorithm_version": "d0035-l1b-dmrpp-pass-stream-v4",
            "provenance_counts": {
                "metadata_candidates": 942,
                "city_scene_links": 1404,
                "unique_scenes": 1370,
                "asset_checkpoint_items": 0,
                "geometry_checkpoint_items": 0,
                "pass_evidence_files": 0,
            },
            "provenance_sha256": {"combined_validation": combined_sha},
            "artifact_sha256": {self.relative(combined_path): combined_sha},
            "combined_validation": combined,
            "lst_opened": False,
            "thermal_opened": False,
            "record_2026_opened": False,
            "holdout_status": "UNSELECTED",
        }
        _write_json(run_path, run)
        self.paths.update(
            {
                "d0035_exhaustive_stop_combined_validation": combined_path,
                "d0035_exhaustive_stop_run_record": run_path,
            }
        )

    def _build_d0046(self) -> None:
        root = self.root / "evidence/d0046"
        probe_path = root / "direct_download_probe.csv"
        controls_path = root / "direct_download_controls.json"
        validation_path = root / "direct_download_validation.json"
        run_path = root / "direct_download_run_record.json"
        resolution_path = root / "scene_identity_resolution.csv"
        identity_path = root / "identity_validation.json"
        # These 41 keys are also placed, unchanged, in the D0047 candidate ledger.
        self.missing_scene_keys = [(100 + index, index + 1) for index in range(41)]
        resolution_rows = [
            {
                "orbit": orbit,
                "scene": scene,
                "identity_resolution_status": "unresolved_missing",
            }
            for orbit, scene in self.missing_scene_keys
        ]
        _write_csv(resolution_path, resolution_rows)
        _write_json(
            identity_path,
            {
                "expected_missing_scene_count": 41,
                "unresolved_missing_count": 41,
                "identity_complete": False,
                "geometry_values_opened": False,
                "lst_opened": False,
                "thermal_opened": False,
                "record_2026_opened": False,
                "holdout_status": "UNSELECTED",
                "downstream_authorized": False,
            },
        )
        probe_rows = [
            {
                "probe_role": "target",
                "orbit": orbit,
                "scene": scene,
                "geo_granule_id": f"ECOv002_L1B_GEO_{orbit:05d}_{scene:03d}_TEST",
                "hdf_url": f"https://example.invalid/{orbit:05d}_{scene:03d}.h5",
                "range_header": "bytes=0-7",
                "http_status": 404,
                "host_chain_allowed": True,
                "prefix_bytes_read": 0,
                "hdf5_signature_verified": False,
                "download_probe_status": "not_downloadable_at_exact_url_now",
                "payload_bytes_retained": 0,
                "geometry_values_opened": False,
                "lst_opened": False,
                "record_2026_opened": False,
                "decision_id": "D0046",
                "control_bracket_valid": True,
            }
            for orbit, scene in self.missing_scene_keys
        ]
        _write_csv(probe_path, probe_rows)
        control_rows = []
        for role in ("control_before", "control_after"):
            control_rows.append(
                {
                    "probe_role": role,
                    "orbit": 99999,
                    "scene": 1,
                    "range_header": "bytes=0-7",
                    "http_status": 206,
                    "download_probe_status": "range_readable_now",
                    "prefix_bytes_read": 8,
                    "hdf5_signature_verified": True,
                    "payload_bytes_retained": 0,
                    "geometry_values_opened": False,
                    "lst_opened": False,
                    "record_2026_opened": False,
                    "decision_id": "D0046",
                }
            )
        _write_json(controls_path, {"decision_id": "D0046", "controls": control_rows})
        validation = {
            "decision_id": "D0046",
            "source_gate_decision_id": "D0045",
            "expected_scene_count": 41,
            "attempted_scene_count": 41,
            "control_bracket_valid": True,
            "control_statuses": ["range_readable_now", "range_readable_now"],
            "status_counts": {"not_downloadable_at_exact_url_now": 41},
            "range_readable_now_count": 0,
            "not_downloadable_at_exact_url_now_count": 41,
            "transient_or_transport_count": 0,
            "all_exact_hdf_downloads_available": False,
            "identity_gate_complete": False,
            "gate_status": "STOP_D0046_DIRECT_DOWNLOADS_INCOMPLETE",
            "maximum_payload_bytes_read_per_scene": 0,
            "payload_bytes_retained": 0,
            "geometry_values_opened": False,
            "lst_opened": False,
            "thermal_opened": False,
            "record_2026_opened": False,
            "holdout_status": "UNSELECTED",
            "downstream_authorized": False,
        }
        _write_json(validation_path, validation)
        run = {
            "schema_version": 1,
            "run_id": "R0010",
            "decision_id": "D0046",
            "input_resolution_path": self.relative(resolution_path),
            "input_resolution_sha256": sha256_file(resolution_path),
            "identity_validation_path": self.relative(identity_path),
            "identity_validation_sha256": sha256_file(identity_path),
            "artifact_sha256": {
                self.relative(path): sha256_file(path)
                for path in (probe_path, controls_path, validation_path)
            },
            "validation": validation,
        }
        _write_json(run_path, run)
        self.paths.update(
            {
                "d0046_direct_download_probe": probe_path,
                "d0046_direct_download_controls": controls_path,
                "d0046_direct_download_validation": validation_path,
                "d0046_direct_download_run_record": run_path,
            }
        )

    def _build_d0047_quality(self) -> None:
        root = self.root / "evidence/d0047_quality"
        ledger_path = root / "candidate_availability_ledger.csv"
        exclusion_path = root / "archive_unavailable_pre_geometry_exclusions.csv"
        attrition_path = root / "archive_available_attrition_summary.csv"
        links_path = root / "retained_city_scene_links.csv"
        profile_path = root / "profile_validation.json"
        combined_path = root / "combined_validation.json"
        run_path = root / "run_record.json"
        evidence_hash = "e" * 64
        excluded_years = [2020] * 24 + [2024] * 7
        excluded_months = [6] * 8 + [7] * 4 + [8] * 13 + [9] * 6
        excluded_strata = ["10-12"] * 9 + ["12-14"] * 9 + ["14-16"] * 8 + ["16-18"] * 5
        missing_cursor = 0
        excluded_cursor = 0
        ledger_rows: list[dict[str, object]] = []
        retained_candidates: list[tuple[str, int]] = []
        for city_position, (city, total) in enumerate(ORIGINAL_BY_CITY.items()):
            n_excluded = EXCLUDED_BY_CITY[city]
            for local_index in range(total):
                excluded = local_index < n_excluded
                orbit = (
                    50_000 + city_position * 100 + local_index
                    if excluded
                    else local_index + 1
                )
                if excluded:
                    n_missing = 2 if excluded_cursor < 10 else 1
                    keys = self.missing_scene_keys[
                        missing_cursor : missing_cursor + n_missing
                    ]
                    missing_cursor += n_missing
                    year = excluded_years[excluded_cursor]
                    month = excluded_months[excluded_cursor]
                    stratum = excluded_strata[excluded_cursor]
                    excluded_cursor += 1
                    missing_text = ";".join(
                        f"{key_orbit:05d}_{scene:03d}" for key_orbit, scene in keys
                    )
                else:
                    n_missing = 0
                    year = 2023
                    month = 7
                    stratum = "12-14"
                    missing_text = ""
                    retained_candidates.append((city, orbit))
                ledger_rows.append(
                    {
                        "city": city,
                        "orbit": orbit,
                        "acquisition_utc": f"{year:04d}-{month:02d}-01T12:00:00+00:00",
                        "year": year,
                        "month": month,
                        "time_stratum": stratum,
                        "d0047_candidate_status": (
                            EXCLUDED_STATUS if excluded else RETAINED_STATUS
                        ),
                        "d0047_profile_included": not excluded,
                        "d0047_exclusion_reason": (
                            "required_exact_ECO_L1B_GEO.002_scene_unavailable"
                            if excluded
                            else ""
                        ),
                        "d0047_required_scene_count": max(1, n_missing),
                        "d0047_available_scene_count": 0 if excluded else 1,
                        "d0047_unavailable_scene_count": n_missing,
                        "d0047_unavailable_scene_keys": missing_text,
                        "d0047_required_scene_keys": missing_text,
                        "d0047_profile_scope": PROFILE_SCOPE,
                        "d0047_missing_scene_evidence_sha256": evidence_hash,
                        "decision_id": "D0047",
                        "lst_opened": False,
                        "thermal_opened": False,
                        "record_2026_opened": False,
                        "holdout_status": "UNSELECTED",
                    }
                )
        if missing_cursor != 41 or excluded_cursor != 31:
            raise AssertionError("fixture construction drift")
        _write_csv(ledger_path, ledger_rows)
        exclusion_rows = [
            row for row in ledger_rows if row["d0047_candidate_status"] == EXCLUDED_STATUS
        ]
        _write_csv(exclusion_path, exclusion_rows)
        _write_csv(
            attrition_path,
            [
                {
                    "city": city,
                    "year": 2023,
                    "month": 7,
                    "time_stratum": "12-14",
                    "original_candidate_count": ORIGINAL_BY_CITY[city],
                    "excluded_pre_geometry_candidate_count": EXCLUDED_BY_CITY[city],
                    "retained_geometry_candidate_count": RETAINED_BY_CITY[city],
                    "decision_id": "D0047",
                    "target_scope": PROFILE_SCOPE,
                }
                for city in ORIGINAL_BY_CITY
            ],
        )

        city_index = {city: index for index, city in enumerate(ORIGINAL_BY_CITY)}
        link_rows: list[dict[str, object]] = []
        for city, orbit in retained_candidates:
            link_rows.append(
                {
                    "city": city,
                    "orbit": orbit,
                    "scene": city_index[city] * 1000 + 500,
                    "d0047_scene_archive_available": True,
                    "decision_id": "D0047",
                    "d0047_profile_scope": PROFILE_SCOPE,
                }
            )
        for index, (city, orbit) in enumerate(retained_candidates[:412]):
            link_rows.append(
                {
                    "city": city,
                    "orbit": orbit,
                    "scene": 10_000 + index,
                    "d0047_scene_archive_available": True,
                    "decision_id": "D0047",
                    "d0047_profile_scope": PROFILE_SCOPE,
                }
            )
        # Thirty-two cross-city links reuse an Atlanta orbit/scene identity.
        for orbit in range(20, 52):
            link_rows.append(
                {
                    "city": "los_angeles",
                    "orbit": orbit,
                    "scene": city_index["atlanta"] * 1000 + 500,
                    "d0047_scene_archive_available": True,
                    "decision_id": "D0047",
                    "d0047_profile_scope": PROFILE_SCOPE,
                }
            )
        _write_csv(links_path, link_rows)

        profile = {
            "schema_version": 1,
            "decision_id": "D0047",
            "implementation_decision_id": "D0047",
            "algorithm_version": ALGORITHM,
            "target_scope": PROFILE_SCOPE,
            "analysis_profile": ANALYSIS_PROFILE,
            "scientific_gate_scope": SCIENTIFIC_SCOPE,
            "original_metadata_candidate_count": 942,
            "excluded_pre_geometry_candidate_count": 31,
            "retained_geometry_candidate_count": 911,
            "original_city_scene_link_count": 1404,
            "retained_city_scene_link_count": 1355,
            "original_unique_scene_count": 1370,
            "sealed_unavailable_unique_scene_count": 41,
            "retained_unique_scene_count": 1323,
            "candidate_ledger_complete": True,
            "retained_candidate_keys_exact": True,
            "whole_candidate_exclusion_rule": True,
            "missing_scene_imputation_used": False,
            "missing_scene_zero_coverage_assigned": False,
            "adjacent_scene_substitution_used": False,
            "geometry_values_opened": False,
            "cloud_values_opened": False,
            "lst_opened": False,
            "thermal_opened": False,
            "record_2026_opened": False,
            "holdout_status": "UNSELECTED",
            "frozen_years": "2018-2025",
            "missing_scene_evidence_sha256": evidence_hash,
            "excluded_by_city": EXCLUDED_BY_CITY,
            "original_by_city": ORIGINAL_BY_CITY,
            "retained_by_city": RETAINED_BY_CITY,
            "excluded_by_year": {"2020": 24, "2024": 7},
            "excluded_by_utc_month": {"6": 8, "7": 4, "8": 13, "9": 6},
            "excluded_by_time_stratum": {
                "10-12": 9,
                "12-14": 9,
                "14-16": 8,
                "16-18": 5,
            },
            "profile_gate_status": "PASS_D0047_ARCHIVE_AVAILABLE_PROFILE_SEALED",
            "candidate_ledger_relative_path": self.relative(ledger_path),
            "exclusion_ledger_relative_path": self.relative(exclusion_path),
            "retained_links_relative_path": self.relative(links_path),
        }
        _write_json(profile_path, profile)
        combined = {
            "decision_id": "D0047",
            "implementation_decision_id": "D0047",
            "analysis_profile": ANALYSIS_PROFILE,
            "scientific_gate_scope": SCIENTIFIC_SCOPE,
            "original_metadata_candidate_count": 942,
            "excluded_pre_geometry_candidate_count": 31,
            "retained_geometry_candidate_count": 911,
            "retained_city_scene_link_count": 1355,
            "retained_unique_scene_count": 1323,
            "expected_metadata_candidates": 911,
            "resolved_geometry_candidate_count": 911,
            "definitive_geometry_status_count": 911,
            "unresolved_geometry_candidate_count": 0,
            "geometry_source": "ECO_L1B_GEO.002",
            "geometry_complete": True,
            "geometry_passing_candidate_count": 2,
            "expected_cloud_candidates": 2,
            "resolved_cloud_candidate_count": 2,
            "finite_cloud_fraction_count": 2,
            "cloud_complete": True,
            "combined_complete": True,
            "scientific_gate_eligible": True,
            "candidate_seal_geometry_only": True,
            "candidate_view_mask_cloud_independent": True,
            "view_gate_cloud_conditioned": False,
            "cloud_extrapolation_used": False,
            "missing_scene_imputation_used": False,
            "missing_scene_zero_coverage_assigned": False,
            "adjacent_scene_substitution_used": False,
            "planning_pass_equivalent_sum": 1.75,
            "planning_pass_equivalent_floor": 1,
            "gate_status": D0047_PASS_STATUS,
            "canonical_status": D0047_PASS_STATUS,
            "lst_opened": False,
            "thermal_opened": False,
            "record_2026_opened": False,
            "holdout_status": "UNSELECTED",
            "frozen_years": "2018-2025",
        }
        _write_json(combined_path, combined)
        quality_paths = {
            "candidate_availability_ledger": ledger_path,
            "archive_unavailable_pre_geometry_exclusions": exclusion_path,
            "archive_available_attrition_summary": attrition_path,
            "retained_city_scene_links": links_path,
            "profile_validation": profile_path,
            "combined_validation": combined_path,
        }
        provenance = {name: sha256_file(path) for name, path in quality_paths.items()}
        run = {
            "schema_version": 3,
            "run_id": "R0011_D0047",
            "decision_id": "D0047",
            "implementation_decision_id": "D0047",
            "algorithm_version": ALGORITHM,
            "analysis_profile": ANALYSIS_PROFILE,
            "scientific_gate_scope": SCIENTIFIC_SCOPE,
            "provenance_counts": {
                "original_metadata_candidate_count": 942,
                "excluded_pre_geometry_candidate_count": 31,
                "retained_geometry_candidate_count": 911,
                "retained_city_scene_link_count": 1355,
                "retained_unique_scene_count": 1323,
                "asset_checkpoint_items": 1323,
                "geometry_checkpoint_items": 911,
                "pass_evidence_files": 911,
            },
            "provenance_sha256": provenance,
            "artifact_sha256": {
                self.relative(path): sha256_file(path) for path in quality_paths.values()
            },
            "combined_validation": combined,
            "missing_scene_imputation_used": False,
            "missing_scene_zero_coverage_assigned": False,
            "adjacent_scene_substitution_used": False,
            "lst_opened": False,
            "thermal_opened": False,
            "record_2026_opened": False,
            "holdout_status": "UNSELECTED",
        }
        _write_json(run_path, run)
        self.d0047_combined = combined
        self.d0047_run = run
        self.paths.update(
            {
                "d0047_profile_validation": profile_path,
                "d0047_combined_validation": combined_path,
                "d0047_run_record": run_path,
                "candidate_availability_ledger": ledger_path,
                "archive_unavailable_pre_geometry_exclusions": exclusion_path,
                "archive_available_attrition_summary": attrition_path,
                "retained_city_scene_links": links_path,
            }
        )

    def _hrrr_profile_binding(self) -> dict[str, object]:
        return {
            "decision_id": "D0047",
            "analysis_profile": ANALYSIS_PROFILE,
            "scientific_gate_scope": SCIENTIFIC_SCOPE,
            "profile_scope_label": PROFILE_SCOPE,
            "geometry_passing_candidate_count": 2,
            "combined_validation_path": self.relative(
                self.paths["d0047_combined_validation"]
            ),
            "combined_validation_sha256": sha256_file(
                self.paths["d0047_combined_validation"]
            ),
            "upstream_run_record_path": self.relative(self.paths["d0047_run_record"]),
            "upstream_run_record_sha256": sha256_file(
                self.paths["d0047_run_record"]
            ),
            "candidate_availability_ledger_path": self.relative(
                self.paths["candidate_availability_ledger"]
            ),
            "candidate_availability_ledger_sha256": sha256_file(
                self.paths["candidate_availability_ledger"]
            ),
            "exclusion_summary_path": self.relative(
                self.paths["archive_unavailable_pre_geometry_exclusions"]
            ),
            "exclusion_summary_sha256": sha256_file(
                self.paths["archive_unavailable_pre_geometry_exclusions"]
            ),
        }

    def _scope_hrrr_to_d0047(self) -> None:
        seal_path = self.paths["hrrr_run_seal"]
        seal = json.loads(seal_path.read_text(encoding="utf-8"))
        binding = self._hrrr_profile_binding()
        seal["status"] = D0047_HRRR_PASS_STATUS
        seal["profile_binding"] = binding
        seal["profile_binding_sha256"] = _json_hash(binding)
        _write_json(seal_path, seal)
        self.hrrr_seal = seal

    def _build_d0047_step2(self) -> None:
        output = self.root / (
            "data/processed/v2/task1/"
            "step2_definitive_l1b_geo_D0047_archive_available"
        )
        checks_path = output / "tables/step2_checks.csv"
        f25_path = output / "figures/F2.5_definitive_conditions.png"
        f25_path.parent.mkdir(parents=True, exist_ok=True)
        f25_path.write_bytes(b"synthetic network-free F2.5 fixture\n")
        _write_csv(
            checks_path,
            [{"check": "sealed_fixture", "pass": True, "detail": "complete"}],
        )
        gate_path = output / "step2_gate_record.json"
        ledger_paths = [
            checks_path,
            f25_path,
            *[
                self.paths[name]
                for name in (
                    "d0047_profile_validation",
                    "d0047_combined_validation",
                    "d0047_run_record",
                    "candidate_availability_ledger",
                    "archive_unavailable_pre_geometry_exclusions",
                    "archive_available_attrition_summary",
                    "retained_city_scene_links",
                    "hrrr_run_seal",
                    "hrrr_manifest",
                    "hrrr_shard_index",
                    "hrrr_summary",
                )
            ],
        ]
        binding = self._hrrr_profile_binding()
        upstream = {
            "decision_id": "D0047",
            "status": D0047_PASS_STATUS,
            "scientific_gate_eligible": True,
            "analysis_profile": ANALYSIS_PROFILE,
            "scientific_gate_scope": SCIENTIFIC_SCOPE,
            "profile_scope_label": PROFILE_SCOPE,
            "algorithm_version": ALGORITHM,
            "run_record_path": self.relative(self.paths["d0047_run_record"]),
            "run_record_sha256": sha256_file(self.paths["d0047_run_record"]),
            "provenance_counts": self.d0047_run["provenance_counts"],
            "provenance_sha256": self.d0047_run["provenance_sha256"],
            "candidate_availability_ledger_path": self.relative(
                self.paths["candidate_availability_ledger"]
            ),
            "candidate_availability_ledger_sha256": sha256_file(
                self.paths["candidate_availability_ledger"]
            ),
            "exclusion_summary_path": self.relative(
                self.paths["archive_unavailable_pre_geometry_exclusions"]
            ),
            "exclusion_summary_sha256": sha256_file(
                self.paths["archive_unavailable_pre_geometry_exclusions"]
            ),
            "attrition_summary_path": self.relative(
                self.paths["archive_available_attrition_summary"]
            ),
            "attrition_summary_sha256": sha256_file(
                self.paths["archive_available_attrition_summary"]
            ),
            "retained_links_path": self.relative(self.paths["retained_city_scene_links"]),
            "retained_links_sha256": sha256_file(
                self.paths["retained_city_scene_links"]
            ),
            "original_exhaustive_gate_status": "STOP_D0035_INCOMPLETE_GEOMETRY",
            "restored_archive_sensitivity_required": True,
        }
        gate = {
            "schema_version": 1,
            "decision_id": "D0047",
            "implementation_decision_id": "D0047",
            "analysis_profile": ANALYSIS_PROFILE,
            "scientific_gate_scope": SCIENTIFIC_SCOPE,
            "profile_scope_label": PROFILE_SCOPE,
            "planning_count_status": D0047_CERTIFIED_COUNT_STATUS,
            "status": "PASS",
            "scientific_gate_eligible": True,
            "all_checks_pass": True,
            "checks_path": self.relative(checks_path),
            "checks_sha256": sha256_file(checks_path),
            "checks": [
                {"check": "sealed_fixture", "pass": True, "detail": "complete"}
            ],
            "upstream_quality_profile": upstream,
            "hrrr_run_seal": {
                "status": D0047_HRRR_PASS_STATUS,
                "path": self.relative(self.paths["hrrr_run_seal"]),
                "sha256": sha256_file(self.paths["hrrr_run_seal"]),
                "manifest_canonical_sha256": self.hrrr_seal[
                    "manifest_canonical_sha256"
                ],
                "frozen_domain_sha256": self.hrrr_seal["frozen_domain_sha256"],
                "counts": self.hrrr_seal["counts"],
                "profile_binding": binding,
                "profile_binding_sha256": _json_hash(binding),
            },
            "counts": {
                "original_metadata_candidates": 942,
                "excluded_pre_geometry_candidates": 31,
                "retained_geometry_candidates": 911,
                "near_nadir_physical_passes": 2,
                "expected_pass_equivalents_total": 1.75,
                "planning_pass_count_floor": 1,
                "step2_checks": 1,
                "step2_checks_passed": 1,
            },
            "artifact_sha256": {
                self.relative(path): sha256_file(path) for path in ledger_paths
            },
            "lst_opened": False,
            "thermal_opened": False,
            "record_2026_opened": False,
            "holdout_status": "UNSELECTED",
            "frozen_years": "2018-2025",
        }
        _write_json(gate_path, gate)
        self.paths["step2_gate"] = gate_path

    def _build_d0047_step3(self, *, diagnostic_status: str) -> None:
        root = self.root / "evidence/d0047_step3"
        diagnostic_path = root / "step3_diagnostic_gate.json"
        support_path = root / "tables/T3.1_model_support.csv"
        run_path = root / "run_record.json"
        diagnostic = {
            "decision_id": "D0027",
            "status": diagnostic_status,
            "scientific_gate_eligible": True,
            "actual_n_passes": 1,
            "passed_required_checks": 2 if diagnostic_status == "PASS" else 1,
            "total_required_checks": 2,
            "failed_check_ids": [] if diagnostic_status == "PASS" else ["power"],
            "thresholds": {"target": 0.8},
        }
        _write_json(diagnostic_path, diagnostic)
        _write_csv(
            support_path,
            [
                {
                    "model": model,
                    "effect_size_k": 1.5,
                    "planning_n_passes": 1,
                    "power_at_planning_n": 0.5,
                    "target_power": 0.8,
                    "statistically_supportable_at_planning_n": False,
                    "count_status": D0047_CERTIFIED_COUNT_STATUS,
                    "scientific_gate_eligible": True,
                    "smallest_detectable_effect_at_planning_n_k": 2.0,
                }
                for model in ("demand_by_dryness", "demand_by_dryness_by_time")
            ],
        )
        run = {
            "decision_ids": ["D0021", "D0027", "D0029", "D0047"],
            "analysis_profile": ANALYSIS_PROFILE,
            "scientific_gate_scope": SCIENTIFIC_SCOPE,
            "actual_n_passes": 1,
            "count_status": D0047_CERTIFIED_COUNT_STATUS,
            "step2_gate": "PASS",
            "status": "ready_for_frozen_full_profile",
            "step2_gate_record_sha256": sha256_file(self.paths["step2_gate"]),
            "hrrr_run_seal_sha256": sha256_file(self.paths["hrrr_run_seal"]),
            "hrrr_summary_sha256": sha256_file(self.paths["hrrr_summary"]),
            "planning_sha256": "9" * 64,
            "config_sha256": "a" * 64,
            "template_sha256": "b" * 64,
            "diagnostic_gate": diagnostic,
            "lst_opened": False,
            "thermal_opened": False,
            "record_2026_opened": False,
            "holdout_status": "UNSELECTED",
            "frozen_years": "2018-2025",
        }
        _write_json(run_path, run)
        self.paths.update(
            {
                "step3_run_record": run_path,
                "step3_diagnostic_gate": diagnostic_path,
                "t3_model_support": support_path,
            }
        )

    def write_gate(self) -> Path:
        gate_path = self.root / "data/processed/v2/task1/TASK1_GATE.json"
        return write_d0047_canonical_task1_pass(
            self.paths, gate_path=gate_path, repo_root=self.root
        )


class D0047Task1GateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _preflight(self, gate_path: Path, gate: dict | None = None):
        document = (
            json.loads(gate_path.read_text(encoding="utf-8")) if gate is None else gate
        )
        return evaluate_preflight(
            _ready_config(),
            document,
            task1_gate_path=str(gate_path),
            free_bytes=10_000,
            repo_root=self.root,
        )

    def test_exact_d0047_chain_passes_task2_preflight(self) -> None:
        fixture = D0047BoundFixture(self.root)
        gate_path = fixture.write_gate()
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        artifacts = validate_canonical_task1_pass(
            gate, gate_path=gate_path, repo_root=self.root
        )
        self.assertEqual(len(artifacts), 21)
        report = self._preflight(gate_path, gate)
        self.assertTrue(report.ready, report.as_dict())

    def test_ledger_hash_mutation_blocks_preflight(self) -> None:
        fixture = D0047BoundFixture(self.root)
        gate_path = fixture.write_gate()
        fixture.paths["candidate_availability_ledger"].write_text(
            "mutated\n", encoding="utf-8"
        )
        report = self._preflight(gate_path)
        self.assertFalse(report.ready)
        self.assertIn(
            "TASK1_CANONICAL_GATE_INVALID", {item.code for item in report.blockers}
        )

    def test_d0046_stop_mutation_blocks_writer(self) -> None:
        fixture = D0047BoundFixture(self.root)
        validation_path = fixture.paths["d0046_direct_download_validation"]
        validation = json.loads(validation_path.read_text(encoding="utf-8"))
        validation["gate_status"] = "PASS"
        _write_json(validation_path, validation)
        with self.assertRaisesRegex(Task1GateError, "D0046"):
            fixture.write_gate()

    def test_d0027_fail_blocks_writer(self) -> None:
        fixture = D0047BoundFixture(self.root, diagnostic_status="FAIL")
        with self.assertRaisesRegex(Task1GateError, "status is not PASS"):
            fixture.write_gate()

    def test_generic_pass_cannot_impersonate_d0047(self) -> None:
        fixture = D0047BoundFixture(self.root)
        gate_path = fixture.write_gate()
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        generic = deepcopy(gate)
        generic.pop("profile_gate")
        report = self._preflight(gate_path, generic)
        self.assertFalse(report.ready)
        self.assertIn(
            "TASK1_CANONICAL_GATE_INVALID", {item.code for item in report.blockers}
        )

    def test_scope_or_count_drift_blocks_preflight(self) -> None:
        fixture = D0047BoundFixture(self.root)
        gate_path = fixture.write_gate()
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        gate["retained_geometry_candidate_count"] = 912
        report = self._preflight(gate_path, gate)
        self.assertFalse(report.ready)
        self.assertIn(
            "TASK1_CANONICAL_GATE_INVALID", {item.code for item in report.blockers}
        )

    def test_step3_thermal_or_2026_safety_drift_blocks_writer(self) -> None:
        fixture = D0047BoundFixture(self.root)
        run_path = fixture.paths["step3_run_record"]
        run = json.loads(run_path.read_text(encoding="utf-8"))
        run["thermal_opened"] = True
        _write_json(run_path, run)
        with self.assertRaisesRegex(Task1GateError, "Step 3 run record"):
            fixture.write_gate()

    def test_f25_is_required_and_hash_bound(self) -> None:
        fixture = D0047BoundFixture(self.root)
        f25 = self.root / (
            "data/processed/v2/task1/"
            "step2_definitive_l1b_geo_D0047_archive_available/figures/"
            "F2.5_definitive_conditions.png"
        )
        f25.unlink()
        with self.assertRaisesRegex(Task1GateError, "artifact"):
            fixture.write_gate()

    def test_d0053_manifest_requires_exact_fallback_hours_and_census(self) -> None:
        fixture = D0047BoundFixture(self.root)
        manifest_path = fixture.paths["hrrr_manifest"]
        with manifest_path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        fallback = next(
            row
            for row in rows
            if row["analysis_utc"].startswith("2018-07-28 23:00:00")
        )
        fallback["product"] = "sfc"
        with manifest_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        with self.assertRaisesRegex(Task1GateError, "stale product"):
            fixture.write_gate()

        fixture = D0047BoundFixture(self.root)
        manifest_path = fixture.paths["hrrr_manifest"]
        with manifest_path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        _write_csv(manifest_path, rows[:-1])
        with self.assertRaisesRegex(Task1GateError, r"409 sfc \+ 4 prs census"):
            fixture.write_gate()

    def test_d0053_manifest_source_and_resolution_are_frozen(self) -> None:
        fixture = D0047BoundFixture(self.root)
        manifest_path = fixture.paths["hrrr_manifest"]
        with manifest_path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        rows[0]["product_resolution"] = "primary_sfc"
        _write_csv(manifest_path, rows)
        with self.assertRaisesRegex(Task1GateError, "stale product_resolution"):
            fixture.write_gate()

        fixture = D0047BoundFixture(self.root)
        manifest_path = fixture.paths["hrrr_manifest"]
        with manifest_path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        rows[0]["source"] = HRRR_SOURCE
        _write_csv(manifest_path, rows)
        with self.assertRaisesRegex(Task1GateError, "stale source"):
            fixture.write_gate()

    def test_d0053_requires_run_seal_v2_and_checkpoint_v3(self) -> None:
        fixture = D0047BoundFixture(self.root)
        seal_path = fixture.paths["hrrr_run_seal"]
        seal = json.loads(seal_path.read_text(encoding="utf-8"))
        seal["schema_version"] = 1
        _write_json(seal_path, seal)
        with self.assertRaisesRegex(Task1GateError, "run seal has stale schema_version"):
            fixture.write_gate()

        fixture = D0047BoundFixture(self.root)
        seal_path = fixture.paths["hrrr_run_seal"]
        seal = json.loads(seal_path.read_text(encoding="utf-8"))
        checkpoint_path = Path(seal["checkpoint_path"])
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        checkpoint["schema_version"] = 2
        _write_json(checkpoint_path, checkpoint)
        seal["checkpoint_sha256"] = sha256_file(checkpoint_path)
        _write_json(seal_path, seal)
        with self.assertRaisesRegex(Task1GateError, "checkpoint has stale schema_version"):
            fixture.write_gate()


if __name__ == "__main__":
    unittest.main(verbosity=2)
