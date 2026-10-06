#!/usr/bin/env python3
"""Network-free tests for the Gate-3 second-revision packet helpers."""

from __future__ import annotations

import ast
import hashlib
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from run_v2_hitl_gate3_second_revision import (
    PRIMARY_CITY_WINDOWS,
    average_tie_percentile,
    assemble_pass_evidence,
    build_eligibility,
    relabel_archive_wetness,
    unify_unavailable_ledger,
    validate_geometry_reconstruction_inventory,
    validate_hrrr_storage_binding,
    _packet_validate_zero_mapped_evidence,
)
from urban_cooling_v2.hitl_gate3_sampling import selection_result
from run_v2_hitl_gate3_cleanroom_check import (
    HRRR_SOURCE,
    TEMPERATURE_SEARCH,
    WEATHER_ALGORITHM_VERSION,
    WIND_SEARCH,
    _canonical_sha,
    _derive_new_unavailable_values,
    _independent_new_archive_provenance,
    _cleanroom_compare_zero_scene_census,
    _cleanroom_validate_zero_mapped_document,
    _replay_mapped_geometry_summary,
    _validate_hrrr_manifest_binding,
    _validate_governance_source_bindings,
)


ROOT = Path(__file__).resolve().parents[1]


def test_average_tie_percentile() -> None:
    actual = average_tie_percentile([0, 1, 1, 3], [0, 1, 2, 3])
    expected = np.array([0.0, 0.5, 0.75, 1.0])
    assert np.allclose(actual, expected)


def test_right_open_tercile_boundaries() -> None:
    values = pd.Series([1 / 3, 2 / 3])
    demand = np.select(
        [values.ge(2 / 3), values.lt(1 / 3)], ["high", "low"], default="middle"
    )
    wetness = np.select(
        [values.lt(1 / 3), values.ge(2 / 3)], ["dry", "wet"], default="middle"
    )
    assert demand.tolist() == ["middle", "high"]
    assert wetness.tolist() == ["middle", "wet"]


def test_cleanroom_requires_every_governance_source_binding() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        names = ("one.md", "two.md")
        for name in names:
            (root / name).write_text(name, encoding="utf-8")
        sources = {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in names
        }
        _validate_governance_source_bindings(
            {"sources": sources}, root=root, relative_paths=names
        )
        for bad_sources in (
            {"one.md": sources["one.md"]},
            {**sources, "two.md": "0" * 64},
        ):
            try:
                _validate_governance_source_bindings(
                    {"sources": bad_sources}, root=root, relative_paths=names
                )
            except ValueError as exc:
                assert "governance source bindings" in str(exc)
            else:
                raise AssertionError("Missing or tampered governance binding was accepted")


def test_cleanroom_archive_provenance_known_answer() -> None:
    derived, evidence = _independent_new_archive_provenance()
    assert evidence["pass_count"] == 300
    assert evidence["required_scene_link_count"] == 488
    assert len(evidence["required_scene_links_sha256"]) == 64
    assert evidence["status_counts"] == {
        "ACCESSIBLE": 288,
        "RESOLVED_UNAVAILABLE": 12,
    }
    assert derived.groupby(["city", "archive_status"]).size().to_dict() == {
        ("denver_aurora", "ACCESSIBLE"): 220,
        ("denver_aurora", "RESOLVED_UNAVAILABLE"): 9,
        ("phoenix", "ACCESSIBLE"): 68,
        ("phoenix", "RESOLVED_UNAVAILABLE"): 3,
    }


def test_archive_precipitation_relabel_uses_primary_scope_only() -> None:
    archive = pd.DataFrame(
        [
            {
                "observation_id": "a",
                "city": "atlanta",
                "acquisition_utc": "2020-07-01T12:00:00Z",
                "year": 2020,
                "month": 7,
                "time_stratum": "10-12",
                "proxy_local_solar_date": "2020-07-01",
                "proxy_demand_percentile": 0.9,
                "proxy_antecedent_dryness_30d_percentile": 0.99,
                "pass_recheck_classification": "RESOLVED_UNAVAILABLE",
            },
            {
                "observation_id": "b",
                "city": "los_angeles",
                "acquisition_utc": "2020-07-01T12:00:00Z",
                "year": 2020,
                "month": 7,
                "time_stratum": "10-12",
                "proxy_local_solar_date": "2020-07-01",
                "proxy_demand_percentile": 0.1,
                "proxy_antecedent_dryness_30d_percentile": 0.01,
                "pass_recheck_classification": "RESOLVED_UNAVAILABLE",
            },
        ]
        * 15
        + [
            {
                "observation_id": "c",
                "city": "phoenix",
                "acquisition_utc": "2020-07-01T12:00:00Z",
                "year": 2020,
                "month": 7,
                "time_stratum": "10-12",
                "proxy_local_solar_date": "2020-07-01",
                "proxy_demand_percentile": 0.5,
                "proxy_antecedent_dryness_30d_percentile": 0.5,
                "pass_recheck_classification": "RESOLVED_UNAVAILABLE",
            }
        ]
    )
    archive["observation_id"] = [f"id_{index}" for index in range(len(archive))]
    dates = pd.date_range("2020-01-01", "2020-12-31", freq="D")
    daily = pd.concat(
        [
            pd.DataFrame(
                {
                    "city": city,
                    "date": dates,
                    "pr_mm": np.arange(len(dates), dtype=float) % 7,
                    "eto_mm": 1.0,
                }
            )
            for city in ("atlanta", "los_angeles", "phoenix")
        ],
        ignore_index=True,
    )
    result = relabel_archive_wetness(archive, daily)
    assert len(result) == 31
    assert result.loc[result["city"].eq("atlanta"), "bound_scope_included"].all()
    assert not result.loc[result["city"].eq("los_angeles"), "bound_scope_included"].any()
    assert not result.loc[result["city"].eq("phoenix"), "bound_scope_included"].any()
    assert not result["old_proxy_p_minus_et0_used_for_bounds"].any()


def _safety_columns(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    output["temperature_or_lst_opened"] = False
    output["record_2026_opened"] = False
    return output


def test_pass_join_fails_closed_on_missing_wind() -> None:
    rows = []
    for city, window in sorted(PRIMARY_CITY_WINDOWS):
        rows.append(
            {
                "city": city,
                "window_id": window,
                "orbit": len(rows) + 1,
                "acquisition_utc": "2020-07-01T12:00:00Z",
                "year": 2020,
                "l1b_geometry_coverage_fraction": 1.0,
                "l1b_view_zenith_abs_p95_deg": 20.0,
                "view_azimuth_circular_mean_deg": 100.0,
                "solar_azimuth_circular_mean_deg": 150.0,
                "relative_azimuth_median_deg": 50.0,
                "geometry_azimuth_complete": True,
                "geometry_azimuth_status": "COMPLETE",
            }
        )
    geometry = _safety_columns(pd.DataFrame(rows * 190 + rows[:2]))
    geometry["orbit"] = np.arange(1, len(geometry) + 1)
    cloud = _safety_columns(
        geometry[["city", "window_id", "orbit"]].assign(
            clear_domain_fraction=0.9, cloud_complete=True
        )
    )
    weather = _safety_columns(
        geometry[["city", "window_id", "orbit"]].assign(
            time_stratum="10-12",
            demand_level="high",
            wetness_level="wet",
            vpd_kpa_at_acquisition=2.0,
            antecedent_precipitation_30d_mm=10.0,
            air_temperature_k_at_acquisition=300.0,
            day_of_window=10,
            exact_weather_complete=True,
        )
    )
    try:
        assemble_pass_evidence(geometry, cloud, weather)
    except ValueError as exc:
        assert "wind_speed_m_s_at_acquisition" in str(exc)
    else:
        raise AssertionError("Missing wind did not fail closed")


def test_cleanroom_has_no_forbidden_imports() -> None:
    path = ROOT / "src/run_v2_hitl_gate3_cleanroom_check.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    assert "urban_cooling_v2.hitl_gate3_sampling" not in imported
    assert "run_v2_hitl_gate3_second_augmentation" not in imported


def _new_unavailable_fixtures() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    historical = pd.DataFrame(
        [{"physical_pass_id": "old", "city": "atlanta", "window_id": "jun_sep"}]
    )
    status = pd.DataFrame(
        [
            {"city": "denver_aurora", "window_id": "jun_sep", "orbit": 10, "archive_status": "RESOLVED_UNAVAILABLE"},
            {"city": "phoenix", "window_id": "phoenix_apr_may", "orbit": 20, "archive_status": "RESOLVED_UNAVAILABLE"},
        ]
    )
    filler = pd.DataFrame(
        [
            {
                "city": "denver_aurora" if index < 150 else "phoenix",
                "window_id": "jun_sep" if index < 150 else "phoenix_apr_may",
                "orbit": 1000 + index,
                "archive_status": "ACCESSIBLE",
            }
            for index in range(298)
        ]
    )
    status = pd.concat([status, filler], ignore_index=True)
    labels = pd.DataFrame(
        [
            {
                "city": city, "window_id": window, "orbit": orbit, "year": 2020,
                "time_stratum": "10-12", "demand_level": "high", "wetness_level": wetness,
                "archive_status": "RESOLVED_UNAVAILABLE",
                "exact_weather_complete": True,
                "temperature_or_lst_opened": False, "record_2026_opened": False,
                "acquisition_utc": "2020-07-01T12:00:00Z",
            }
            for city, window, orbit, wetness in (
                ("denver_aurora", "jun_sep", 10, "wet"),
                ("phoenix", "phoenix_apr_may", 20, "dry"),
            )
        ]
    )
    return historical, status, labels


def test_unified_unavailable_includes_denver_and_phoenix() -> None:
    historical, status, labels = _new_unavailable_fixtures()
    result = unify_unavailable_ledger(historical, status, labels)
    assert set(result["city"]) == {"atlanta", "denver_aurora", "phoenix"}
    assert result["physical_pass_id"].is_unique
    assert result.loc[result["city"].isin(["denver_aurora", "phoenix"]), "bound_scope_included"].all()


def test_unified_unavailable_fails_on_new_unresolved_error() -> None:
    historical, status, labels = _new_unavailable_fixtures()
    status.loc[0, "archive_status"] = "UNRESOLVED_ERROR"
    try:
        unify_unavailable_ledger(historical, status, labels.iloc[1:])
    except ValueError as exc:
        assert "UNRESOLVED_ERROR" in str(exc)
    else:
        raise AssertionError("New UNRESOLVED_ERROR did not fail closed")


def test_accessible_azimuth_incomplete_is_carried_into_eligibility() -> None:
    detail = pd.DataFrame(
        [
            {
                "threshold_deg": 15, "physical_pass_id": f"{city}|{index}", "city": city,
                "window_id": window, "year": 2020, "time_stratum": "10-12",
                "demand_level": "high", "wetness_level": "wet",
                "vpd_kpa_at_acquisition": 2.0, "day_of_window": 10,
                "clear_domain_fraction": 1.0,
            }
            for index, (city, window) in enumerate(sorted(PRIMARY_CITY_WINDOWS))
        ]
    )
    phenology = pd.DataFrame(
        [
            {
                "city": city, "window_id": window, "primary_phenology_pass": True,
                "canopy_sensitivity_pass": True, "phenology_auto_eligible": True,
                "phenology_status": "PRIMARY_AND_CANOPY_CONFIRMED",
                "qa0_sensitivity_status": "QA0_CONFIRMS",
            }
            for city, window in sorted(PRIMARY_CITY_WINDOWS)
        ]
    )
    bounds = pd.DataFrame(
        [{"threshold_deg": threshold, "archive_bounds_invariant": True} for threshold in (10, 15, 20, 25)]
    )
    unresolved = pd.DataFrame(
        [{"city": "atlanta", "window_id": "jun_sep", "geometry_azimuth_status": "AZIMUTH_INCOMPLETE"}]
    )
    result = build_eligibility(detail, phenology, bounds, unresolved)
    atlanta = result.loc[result["threshold_deg"].eq(15) & result["city"].eq("atlanta")].iloc[0]
    assert atlanta["accessible_unresolved_pass_count"] == 1
    assert not atlanta["accessible_observation_accounting_complete"]
    assert "accessible_observation_accounting_complete" in atlanta["ineligibility_reasons"]
    assert len(result.loc[result["threshold_deg"].eq(15)]) == 4


def test_sparse_10_does_not_abort_valid_15_selection() -> None:
    rows = []
    balance_rows = []
    for threshold in (10, 15, 20, 25):
        pass_ids = [f"{city}|{threshold}" for city, _ in sorted(PRIMARY_CITY_WINDOWS)]
        digest = __import__("hashlib").sha256(
            __import__("json").dumps(sorted(pass_ids), ensure_ascii=True, separators=(",", ":")).encode()
        ).hexdigest()
        for pass_id, (city, window) in zip(pass_ids, sorted(PRIMARY_CITY_WINDOWS), strict=True):
            rows.append(
                {
                    "threshold_deg": threshold, "city": city, "window_id": window,
                    "phenology_auto_eligible": True,
                    "eligible_city_window": threshold >= 15,
                    "archive_bounds_invariant": True,
                    "qualifying_pass_count": 4,
                    "qualifying_pass_set_sha256": digest,
                }
            )
        balance_rows.append(
            {
                "threshold_deg": threshold, "unique_cities": 4,
                "city_window_membership": __import__("json").dumps(
                    [f"{city}/{window}" for city, window in sorted(PRIMARY_CITY_WINDOWS)]
                ),
                "qualifying_pass_count": 4, "qualifying_pass_set_sha256": digest,
                "histogram_diagnostics_complete": threshold >= 15,
                "entropy_diagnostic_complete": threshold >= 15,
                "geometry_diagnostics_complete": threshold >= 15,
                "city_share_cap_pass": threshold >= 15,
                "am_pm_support_diagnostics_complete": threshold >= 15,
                "wet_dry_support_diagnostics_complete": threshold >= 15,
                "within_city_vpd_overlap_complete_and_positive": threshold >= 15,
                "season_overlap_diagnostics_complete": threshold >= 15,
                "weather_overlap_diagnostics_complete": threshold >= 15,
                "archive_bounds_invariant": True,
            }
        )
    result = selection_result(pd.DataFrame(rows), pd.DataFrame(balance_rows))
    assert result["primary_view_zenith_threshold_deg"] == 15


def test_cleanroom_recomputes_new_unavailable_from_raw_references() -> None:
    status = pd.DataFrame(
        [
            {
                "city": "denver_aurora", "window_id": "jun_sep", "orbit": 77,
                "acquisition_utc": "2020-07-01T00:30:00Z", "year": 2020,
                "time_stratum": "16-18", "archive_status": "RESOLVED_UNAVAILABLE",
            }
        ]
    )
    hourly = pd.DataFrame(
        {
            "city": ["denver_aurora", "denver_aurora"],
            "timestamp_utc": ["2020-07-01T00:00:00Z", "2020-07-01T01:00:00Z"],
            "vpd_kpa": [1.0, 3.0], "t2m_k": [290.0, 294.0],
            "wind_speed_m_s": [2.0, 4.0],
        }
    )
    dates = pd.date_range("2020-01-01", "2020-12-31", freq="D")
    daily = pd.DataFrame(
        {
            "city": "denver_aurora", "date": dates,
            "pr_mm": np.arange(len(dates), dtype=float) % 5,
            "vpd_kpa": np.linspace(0.0, 4.0, len(dates)),
        }
    )
    result = _derive_new_unavailable_values(
        status, {"denver_aurora": -104.99}, hourly, daily
    )
    assert len(result) == 1
    assert result.iloc[0]["local_solar_date"].isoformat() == "2020-06-30"
    assert np.isclose(result.iloc[0]["vpd_kpa_at_acquisition"], 2.0)
    assert np.isclose(result.iloc[0]["air_temperature_k_at_acquisition"], 292.0)
    assert np.isclose(result.iloc[0]["wind_speed_m_s_at_acquisition"], 3.0)
    # The June-30 precipitation aggregate ends June 29, never uses the focal day.
    expected_prior = daily.loc[
        (daily["date"] >= "2020-05-31") & (daily["date"] <= "2020-06-29"), "pr_mm"
    ].sum()
    assert np.isclose(result.iloc[0]["antecedent_precipitation_30d_mm"], expected_prior)
    assert result.iloc[0]["physical_pass_id"] == "denver_aurora|orbit_00077"
    assert result.iloc[0]["demand_level"] in {"low", "middle", "high"}
    assert result.iloc[0]["wetness_level"] in {"dry", "middle", "wet"}


def test_zero_observed_city_through_25_returns_revise() -> None:
    rows = []
    balance_rows = []
    for threshold in (10, 15, 20, 25):
        # Phoenix is absent at every threshold: this is a valid failed gate, not a crash.
        members = sorted(PRIMARY_CITY_WINDOWS - {("phoenix", "phoenix_apr_may")})
        pass_ids = [f"{city}|{threshold}" for city, _ in members]
        digest = __import__("hashlib").sha256(
            __import__("json").dumps(sorted(pass_ids), ensure_ascii=True, separators=(",", ":")).encode()
        ).hexdigest()
        for city, window in sorted(PRIMARY_CITY_WINDOWS):
            rows.append(
                {
                    "threshold_deg": threshold, "city": city, "window_id": window,
                    "phenology_auto_eligible": True,
                    "eligible_city_window": city != "phoenix",
                    "archive_bounds_invariant": True,
                    "qualifying_pass_count": 3,
                    "qualifying_pass_set_sha256": digest,
                }
            )
        balance_rows.append(
            {
                "threshold_deg": threshold, "unique_cities": 3,
                "city_window_membership": __import__("json").dumps(
                    [f"{city}/{window}" for city, window in members]
                ),
                "qualifying_pass_count": 3, "qualifying_pass_set_sha256": digest,
                **{
                    column: False
                    for column in (
                        "histogram_diagnostics_complete", "entropy_diagnostic_complete",
                        "geometry_diagnostics_complete", "city_share_cap_pass",
                        "am_pm_support_diagnostics_complete", "wet_dry_support_diagnostics_complete",
                        "within_city_vpd_overlap_complete_and_positive",
                        "season_overlap_diagnostics_complete", "weather_overlap_diagnostics_complete",
                    )
                },
                "archive_bounds_invariant": True,
            }
        )
    result = selection_result(pd.DataFrame(rows), pd.DataFrame(balance_rows))
    assert result["gate_status"] == "REVISE_REQUIRED"
    assert result["primary_view_zenith_threshold_deg"] is None


def test_packet_geometry_inventory_detects_missing_and_tampered_sources() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        reconstruction = root / "mapped.npz"
        evidence = root / "evidence.json"
        dmrpp = root / "source.dmrpp"
        locator = root / "locator.nc4"
        reconstruction.write_bytes(b"mapped geometry")
        preflight = root / "geometry_preflight.json"
        evidence.write_bytes(b"pass evidence")
        dmrpp.write_bytes(b"dmrpp bytes")
        locator.write_bytes(b"locator bytes")
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        preflight.write_text(
            __import__("json").dumps(
                {
                    "status": "PASS", "format_version": "d0069-mapped-domain-cells-v1",
                    "candidate_passes": 1, "raw_array_worst_case_bytes": 160,
                    "absolute_maximum_bytes": 8 * 1024**3,
                    "container_overhead_bytes": 1024**2,
                    "conservative_new_data_bytes": 160 + 1024**2,
                    "completed_passes": 0,
                    "completed_raw_array_worst_case_bytes": 0,
                    "completed_container_overhead_bytes": 0,
                    "completed_conservative_bytes": 0,
                    "remaining_passes": 1,
                    "remaining_raw_array_worst_case_bytes": 160,
                    "remaining_container_overhead_bytes": 1024**2,
                    "remaining_conservative_new_data_bytes": 160 + 1024**2,
                    "credited_completed_item_ids": [],
                    "credited_completed_validation_sha256_by_item_id": {},
                    "explicit_reserve_bytes": 100,
                    "required_free_bytes": 160 + 1024**2 + 100,
                    "observed_free_bytes": 160 + 1024**2 + 200,
                }
            ), encoding="utf-8"
        )
        record = {
            "city": "atlanta", "orbit": 1,
            "path": str(reconstruction), "sha256": digest(reconstruction),
            "size_bytes": reconstruction.stat().st_size,
            "pass_evidence_path": str(evidence), "pass_evidence_sha256": digest(evidence),
            "selected_compressed_chunk_count": 0,
            "selected_compressed_chunk_hash_inventory": [],
            "source_assets": [
                {
                    "dmrpp_path": str(dmrpp), "dmrpp_sha256": digest(dmrpp),
                    "locator_path": str(locator), "locator_sha256": digest(locator),
                }
            ],
        }
        augmentation = {
            "artifacts": {},
            "geometry_reconstruction_inventory": {
                "format_version": "d0069-mapped-domain-cells-v1",
                "pass_count": 1, "total_bytes": reconstruction.stat().st_size,
                "maximum_bytes": 1000, "storage_guard_pass": True,
                "raw_mapped_per_pixel_reconstruction_supported": True,
                "passes": [record],
            }
        }
        geometry = pd.DataFrame(
            [{"city": "atlanta", "orbit": 1, "n_domain_pixels": 10, "geometry_azimuth_status": "COMPLETE"}]
        )
        import run_v2_hitl_gate3_second_revision as packet
        old_preflight = packet.GEOMETRY_RECONSTRUCTION_PREFLIGHT
        old_root = packet.ROOT
        packet.GEOMETRY_RECONSTRUCTION_PREFLIGHT = preflight
        packet.ROOT = root
        augmentation["artifacts"]["geometry_preflight.json"] = digest(preflight)
        assert validate_geometry_reconstruction_inventory(augmentation, geometry)["pass_count"] == 1
        locator.write_bytes(b"tampered")
        try:
            validate_geometry_reconstruction_inventory(augmentation, geometry)
        except ValueError as exc:
            assert "metadata asset binding failed" in str(exc)
        else:
            raise AssertionError("Tampered locator did not fail packet validation")
        locator.unlink()
        try:
            validate_geometry_reconstruction_inventory(augmentation, geometry)
        except ValueError as exc:
            assert "metadata asset binding failed" in str(exc)
        else:
            raise AssertionError("Missing locator did not fail packet validation")
        packet.GEOMETRY_RECONSTRUCTION_PREFLIGHT = old_preflight
        packet.ROOT = old_root


def test_packet_hrrr_storage_binding_detects_tampering() -> None:
    import run_v2_hitl_gate3_second_revision as packet

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        estimate = root / "estimate.csv"
        preflight = root / "preflight.json"
        pd.DataFrame([{"conservative_new_data_bytes": 100}]).to_csv(estimate, index=False)
        estimate_sha = hashlib.sha256(estimate.read_bytes()).hexdigest()
        preflight.write_text(
            __import__("json").dumps(
                {
                    "status": "PASS", "weather_algorithm_version": packet.WEATHER_ALGORITHM_VERSION,
                    "conservative_new_data_bytes": 100, "explicit_reserve_bytes": 50,
                    "required_free_bytes": 150, "observed_free_bytes": 200,
                    "estimate_sha256": estimate_sha,
                }
            ),
            encoding="utf-8",
        )
        old_estimate, old_preflight = packet.HRRR_STORAGE_ESTIMATE, packet.HRRR_STORAGE_PREFLIGHT
        try:
            packet.HRRR_STORAGE_ESTIMATE, packet.HRRR_STORAGE_PREFLIGHT = estimate, preflight
            augmentation = {
                "artifacts": {
                    str(estimate.relative_to(packet.ROOT)) if estimate.is_relative_to(packet.ROOT) else str(estimate): estimate_sha,
                    str(preflight.relative_to(packet.ROOT)) if preflight.is_relative_to(packet.ROOT) else str(preflight): hashlib.sha256(preflight.read_bytes()).hexdigest(),
                }
            }
            # Temporary paths are outside ROOT; emulate source-binding keys used by the helper.
            estimate_name = str(estimate.relative_to(packet.ROOT)) if estimate.is_relative_to(packet.ROOT) else str(estimate)
            preflight_name = str(preflight.relative_to(packet.ROOT)) if preflight.is_relative_to(packet.ROOT) else str(preflight)
            # The helper requires ROOT-relative paths, so temporarily root it at the fixture.
            old_root = packet.ROOT
            packet.ROOT = root
            augmentation["artifacts"] = {
                "estimate.csv": estimate_sha,
                "preflight.json": hashlib.sha256(preflight.read_bytes()).hexdigest(),
            }
            assert validate_hrrr_storage_binding(augmentation)["conservative_new_data_bytes"] == 100
            preflight.write_text(preflight.read_text().replace('"PASS"', '"FAIL"'), encoding="utf-8")
            try:
                validate_hrrr_storage_binding(augmentation)
            except ValueError as exc:
                assert "storage estimate/preflight binding failed" in str(exc)
            else:
                raise AssertionError("Tampered HRRR preflight did not fail")
            packet.ROOT = old_root
        finally:
            packet.HRRR_STORAGE_ESTIMATE, packet.HRRR_STORAGE_PREFLIGHT = old_estimate, old_preflight
            if packet.ROOT != old_root:
                packet.ROOT = old_root


def test_cleanroom_full_hrrr_manifest_binding_detects_algorithm_and_domain_tamper() -> None:
    geometry = {"denver_aurora": "a" * 64}
    record = {
        "item_id": "hrrr_20200701T00_f00", "analysis_utc": "2020-07-01T00:00:00Z",
        "cities": "denver_aurora", "n_target_passes": 2, "model": "hrrr",
        "product": "sfc", "forecast_hour": 0, "object_key": "key",
        "product_resolution": "native", "weather_algorithm_version": WEATHER_ALGORITHM_VERSION,
        "analysis_geometry_sha256_by_city": __import__("json").dumps(geometry, separators=(",", ":")),
        "analysis_geometry_set_sha256": _canonical_sha(geometry),
    }
    request = {
        "item_id": record["item_id"], "analysis_utc": record["analysis_utc"],
        "cities": record["cities"], "n_target_passes": 2, "model": "hrrr",
        "product": "sfc", "forecast_hour": 0,
        "temperature_dewpoint_variable_search": TEMPERATURE_SEARCH,
        "wind_variable_search": WIND_SEARCH, "source": HRRR_SOURCE,
        "object_key": "key", "product_resolution": "native",
        "weather_algorithm_version": WEATHER_ALGORITHM_VERSION,
        "analysis_geometry_sha256_by_city": geometry,
        "analysis_geometry_set_sha256": _canonical_sha(geometry),
    }
    checkpoint = {
        "status": "complete", "request_binding": request,
        "request_binding_sha256": _canonical_sha(request), "sha256": "b" * 64,
        "size_bytes": 123, "weather_algorithm_version": WEATHER_ALGORITHM_VERSION,
        "analysis_geometry_sha256_by_city": geometry,
        "analysis_geometry_set_sha256": _canonical_sha(geometry),
    }
    shard = pd.DataFrame(
        [{
            "city": "denver_aurora", "weather_algorithm_version": WEATHER_ALGORITHM_VERSION,
            "analysis_geometry_sha256": "a" * 64,
        }]
    )
    _validate_hrrr_manifest_binding(
        record, checkpoint, shard, geometry, shard_sha256="b" * 64, shard_size_bytes=123
    )
    bad_record = dict(record)
    bad_record["weather_algorithm_version"] = "old"
    try:
        _validate_hrrr_manifest_binding(
            bad_record, checkpoint, shard, geometry,
            shard_sha256="b" * 64, shard_size_bytes=123,
        )
    except ValueError as exc:
        assert "binding failed" in str(exc)
    else:
        raise AssertionError("Tampered HRRR algorithm did not fail")
    bad_shard = shard.copy()
    bad_shard["analysis_geometry_sha256"] = "c" * 64
    try:
        _validate_hrrr_manifest_binding(
            record, checkpoint, bad_shard, geometry,
            shard_sha256="b" * 64, shard_size_bytes=123,
        )
    except ValueError as exc:
        assert "binding failed" in str(exc)
    else:
        raise AssertionError("Tampered repaired-domain cell digest did not fail")


def test_geometry_replay_audits_incomplete_azimuth_without_nan_failure() -> None:
    result = _replay_mapped_geometry_summary(
        np.asarray([1.0, 2.0, 3.0]),
        np.asarray([10.0, np.nan, 350.0]),
        np.asarray([40.0, 50.0, 20.0]),
        6,
    )
    assert result["geometry_azimuth_status"] == "AZIMUTH_INCOMPLETE"
    assert not result["geometry_azimuth_complete"]
    assert np.isclose(result["azimuth_valid_fraction_of_view_cells"], 2 / 3)
    assert np.isclose(result["l1b_geometry_coverage_fraction"], 0.5)
    assert np.isclose(result["relative_azimuth_median_deg"], 30.0)


def test_packet_and_cleanroom_strict_zero_mapped_proof_predicates() -> None:
    document = {
        "status": "complete",
        "decision_id": "D0047",
        "full_resolution": True,
        "boundary_verified": True,
        "summary": {
            "n_view_valid_pixels": 0,
            "n_l1b_geo_scenes": 1,
            "l1b_geometry_coverage_fraction": 0.0,
            "l1b_geometry_complete": True,
            "geometry_definitive": True,
            "quality_candidate_pre_cloud_geometry_only": False,
        },
        "scene_evidence": [{
            "granule_id": "known-scene",
            "proof_status": "near_domain_full_resolution_verified",
            "full_resolution_boundary_verified": True,
            "mapped_target_cell_count": 0,
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
        }],
    }
    for validator in (
        _packet_validate_zero_mapped_evidence,
        _cleanroom_validate_zero_mapped_document,
    ):
        validator(document, item_id="atlanta:17605")
        downgraded = __import__("copy").deepcopy(document)
        downgraded["scene_evidence"][0]["proof_status"] = "verified_no_domain_overlap"
        try:
            validator(downgraded, item_id="atlanta:17605")
        except ValueError as exc:
            assert "scene proof rejected" in str(exc)
        else:
            raise AssertionError("Near-domain proof status downgrade was accepted")
        for field, value in (
            ("mapped_target_cell_count", 1),
            ("full_resolution_boundary_verified", False),
            ("proof_status", "ordinary_near_domain_mapping"),
        ):
            bad = __import__("copy").deepcopy(document)
            bad["scene_evidence"][0][field] = value
            try:
                validator(bad, item_id="atlanta:17605")
            except ValueError as exc:
                assert "scene proof rejected" in str(exc)
            else:
                raise AssertionError(f"Tampered zero-map field was accepted: {field}")
        no_overlap = __import__("copy").deepcopy(document)
        no_overlap["scene_evidence"][0].update(
            {
                "proof_status": "verified_no_domain_overlap",
                "proof_mode": "verified_no_overlap",
                "proof_acceptance_status": "verified_no_overlap_mapped_zero",
                "verified_no_overlap_mapped_zero": True,
            }
        )
        validator(no_overlap, item_id="minneapolis_st_paul:40129")
        for field, value in (
            ("full_resolution_boundary_verified", False),
            ("verified_no_overlap_zero_imputed", True),
            ("range_evidence_sha256", ""),
        ):
            bad = __import__("copy").deepcopy(no_overlap)
            bad["scene_evidence"][0][field] = value
            try:
                validator(bad, item_id="minneapolis_st_paul:40129")
            except ValueError as exc:
                assert "scene proof rejected" in str(exc)
            else:
                raise AssertionError(f"Tampered no-overlap field was accepted: {field}")

    generated = __import__("copy").deepcopy(document)
    generated.pop("decision_id")
    generated.pop("full_resolution")
    generated.pop("boundary_verified")
    generated["zero_map_proof_schema_version"] = "d0079-generated-zero-map-proof-v1"
    generated["binding"] = {
        "decision_id": "D0069", "city": "atlanta", "orbit": 123
    }
    generated["temperature_or_lst_opened"] = False
    generated["record_2026_opened"] = False
    generated["summary"] = {
        "decision_id": "D0069",
        "city": "atlanta",
        "orbit": 123,
        "source_population": "new_d0069",
        "n_view_valid_pixels": 0,
        "n_l1b_geo_scenes": 1,
        "l1b_geometry_coverage_fraction": 0.0,
        "n_overlapping_valid_pixels": 0,
        "geometry_azimuth_complete": True,
        "geometry_azimuth_status": "RESOLVED_VERIFIED_ZERO_MAPPED_CELLS",
    }
    for validator in (
        _packet_validate_zero_mapped_evidence,
        _cleanroom_validate_zero_mapped_document,
    ):
        validator(generated, item_id="atlanta:00123")
        stale = __import__("copy").deepcopy(generated)
        stale["zero_map_proof_schema_version"] = "stale"
        try:
            validator(stale, item_id="atlanta:00123")
        except ValueError as exc:
            assert "evidence" in str(exc).casefold()
            assert "incomplete" in str(exc).casefold()
        else:
            raise AssertionError("Stale generated zero-map proof schema was accepted")


def test_packet_and_cleanroom_accept_real_atlanta_17605_proof() -> None:
    path = (
        ROOT
        / "data/raw/v2/ecostress/l1b_geo_geometry_D0047_archive_available"
        / "pass_evidence/atlanta/17605.json"
    )
    document = __import__("json").loads(path.read_text(encoding="utf-8"))
    assert document["summary"]["n_view_valid_pixels"] == 0
    _packet_validate_zero_mapped_evidence(document, item_id="atlanta:17605")
    _cleanroom_validate_zero_mapped_document(document, item_id="atlanta:17605")


def test_cleanroom_rejects_duplicate_or_wrong_zero_scene_identity() -> None:
    expected = [(16825, 1, "granule-a"), (16825, 2, "granule-b")]
    document = {
        "binding": {
            "scene_bindings": [
                {"orbit": 16825, "scene": 1, "granule_id": "granule-a"},
                {"orbit": 16825, "scene": 2, "granule_id": "granule-b"},
            ]
        },
        "scene_evidence": [
            {"orbit": 16825, "scene": 1, "granule_id": "granule-a"},
            {"orbit": 16825, "scene": 2, "granule_id": "granule-b"},
        ],
    }
    _cleanroom_compare_zero_scene_census(document, expected, item_id="atlanta:16825")
    duplicate = __import__("copy").deepcopy(document)
    duplicate["binding"]["scene_bindings"].append(
        {"orbit": 16825, "scene": 2, "granule_id": "granule-b"}
    )
    duplicate["scene_evidence"].append(
        {"orbit": 16825, "scene": 2, "granule_id": "granule-b"}
    )
    try:
        _cleanroom_compare_zero_scene_census(
            duplicate, expected, item_id="atlanta:16825"
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Duplicate zero-scene binding/evidence was accepted")
    wrong = __import__("copy").deepcopy(document)
    wrong["binding"]["scene_bindings"][1]["granule_id"] = "wrong-granule"
    wrong["scene_evidence"][1]["granule_id"] = "wrong-granule"
    try:
        _cleanroom_compare_zero_scene_census(wrong, expected, item_id="atlanta:16825")
    except ValueError:
        pass
    else:
        raise AssertionError("Wrong frozen granule identity was accepted")


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
    print("PASS test_v2_hitl_gate3_second_revision_packet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
