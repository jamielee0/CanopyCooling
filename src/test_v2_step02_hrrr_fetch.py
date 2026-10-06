#!/usr/bin/env python3
"""Network-free tests for exact-acquisition HRRR demand fetching."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from urban_cooling_v2 import step02_hrrr_fetch as hrrr


def test_manifest_uses_unique_floor_and_ceiling_noaa_aws_analyses() -> None:
    passes = pd.DataFrame(
        {
            "city": ["phoenix", "phoenix", "miami"],
            "acquisition_utc": pd.to_datetime(
                [
                    "2023-07-18T19:00:00Z",
                    "2023-07-18T19:15:00Z",
                    "2023-07-18T19:45:00Z",
                ],
                utc=True,
            ),
        }
    )
    manifest = hrrr.build_hrrr_request_manifest(passes)
    assert manifest["analysis_utc"].dt.strftime("%H:%M").tolist() == ["19:00", "20:00"]
    assert manifest["n_target_passes"].tolist() == [3, 2]
    assert manifest.loc[0, "cities"] == "miami|phoenix"
    assert manifest.loc[0, "object_key"] == (
        "hrrr.20230718/conus/hrrr.t19z.wrfsfcf00.grib2"
    )
    assert manifest.loc[0, "grib_url"].startswith(
        "https://noaa-hrrr-bdp-pds.s3.amazonaws.com/"
    )
    assert manifest.loc[0, "index_url"].endswith(".grib2.idx")
    assert (manifest["forecast_hour"] == 0).all()
    assert (manifest["variable_search"] == hrrr.HRRR_SEARCH_STRING).all()


def test_manifest_freezes_exact_prs_fallback_for_missing_sfc_objects() -> None:
    passes = pd.DataFrame(
        {
            "city": ["atlanta", "atlanta"],
            "acquisition_utc": pd.to_datetime(
                ["2018-07-28T22:00:00Z", "2018-07-28T23:00:00Z"], utc=True
            ),
        }
    )
    manifest = hrrr.build_hrrr_request_manifest(passes)
    primary = manifest.loc[manifest["analysis_utc"].dt.hour.eq(22)].iloc[0]
    fallback = manifest.loc[manifest["analysis_utc"].dt.hour.eq(23)].iloc[0]

    assert primary["product"] == "sfc"
    assert primary["product_resolution"] == hrrr.HRRR_PRIMARY_PRODUCT_RESOLUTION
    assert "wrfsfcf00.grib2" in primary["object_key"]
    assert fallback["item_id"] == "hrrr-prs-f00-20180728T23Z"
    assert fallback["product"] == hrrr.HRRR_FALLBACK_PRODUCT
    assert (
        fallback["product_resolution"]
        == hrrr.HRRR_FALLBACK_PRODUCT_RESOLUTION
    )
    assert "wrfprsf00.grib2" in fallback["object_key"]
    assert hrrr.official_hrrr_product("2018-07-28T23:00:00Z") == "prs"
    assert hrrr.official_hrrr_product("2018-07-28T22:00:00Z") == "sfc"

    altered = manifest.copy()
    altered.loc[altered["product"].eq("prs"), "product"] = "sfc"
    try:
        hrrr.canonical_hrrr_manifest_sha256(altered)
    except ValueError as exc:
        assert "not the frozen NOAA/AWS HRRR request" in str(exc)
    else:
        raise AssertionError("the frozen fallback product must be tamper-evident")


def test_manifest_accepts_mixed_fractional_and_whole_second_timestamps() -> None:
    passes = pd.DataFrame(
        {
            "city": ["atlanta", "atlanta"],
            "acquisition_utc": [
                "2024-08-03T23:15:32.833Z",
                "2024-08-04T23:16:58Z",
            ],
        }
    )
    manifest = hrrr.build_hrrr_request_manifest(passes)
    assert len(manifest) == 4
    assert manifest["analysis_utc"].notna().all()


def test_tetens_vpd_formula_and_nonnegative_guard() -> None:
    assert np.isclose(hrrr.saturation_vapour_pressure_kpa(0.0), 0.6108)
    hot_dry = hrrr.vpd_kpa(np.array([313.15]), np.array([283.15]))[0]
    expected = 0.6108 * np.exp(17.27 * 40 / (40 + 237.3)) - 0.6108 * np.exp(
        17.27 * 10 / (10 + 237.3)
    )
    assert np.isclose(hot_dry, expected)
    assert hrrr.vpd_kpa(np.array([290.0]), np.array([291.0]))[0] == 0


def _dataset(hour_offset: float = 0.0) -> xr.Dataset:
    latitude = np.array([[30.0, 30.0, 30.0], [31.0, 31.0, 31.0], [32.0, 32.0, 32.0]])
    # Exercise normalization from HRRR's common 0-360 longitude convention.
    longitude = np.array([[250.0, 251.0, 252.0]] * 3)
    temperature = np.array(
        [[300.0, 301.0, 302.0], [303.0, 304.0, 305.0], [306.0, 307.0, 308.0]]
    ) + hour_offset
    dewpoint = temperature - 10.0
    return xr.Dataset(
        {
            "t2m": (("y", "x"), temperature),
            "d2m": (("y", "x"), dewpoint),
        },
        coords={
            "latitude": (("y", "x"), latitude),
            "longitude": (("y", "x"), longitude),
        },
    )


def test_herbie_loader_uses_frozen_product_for_each_analysis_hour() -> None:
    calls: list[str] = []

    class FakeRequest:
        def xarray(self, *_args, **_kwargs):
            return _dataset()

    def factory(*_args, **kwargs):
        calls.append(str(kwargs["product"]))
        return FakeRequest()

    with tempfile.TemporaryDirectory(prefix="hrrr-loader-product-") as temporary:
        loader = hrrr.HerbieHrrrLoader(temporary, herbie_factory=factory)
        loader("2018-07-28T22:00:00Z").close()
        loader("2018-07-28T23:00:00Z").close()
    assert calls == ["sfc", "prs"]


PHOENIX_TEST_DOMAIN = {
    "type": "Polygon",
    "coordinates": [[
        [-110.1, 29.9],
        [-108.9, 29.9],
        [-108.9, 31.1],
        [-110.1, 31.1],
        [-110.1, 29.9],
    ]],
}


def test_domain_cell_extraction_preserves_cells_and_spatial_spread() -> None:
    cells = hrrr.extract_domain_cells(
        _dataset(),
        {"phoenix": PHOENIX_TEST_DOMAIN},
        analysis_utc="2023-07-18T19:00:00Z",
    )
    assert len(cells) == 4
    assert set(zip(cells["grid_y_index"], cells["grid_x_index"])) == {
        (0, 0),
        (0, 1),
        (1, 0),
        (1, 1),
    }
    assert cells["longitude"].between(-110, -109).all()
    assert (cells["vpd_kpa"] > 0).all()

    summary = hrrr.summarize_domain_cells(cells)
    assert len(summary) == 1
    assert summary.loc[0, "n_domain_cells"] == 4
    assert summary.loc[0, "vpd_kpa_min"] < summary.loc[0, "vpd_kpa_max"]
    assert summary.loc[0, "vpd_kpa_p10"] < summary.loc[0, "vpd_kpa_p90"]
    assert np.isclose(summary.loc[0, "vpd_kpa"], cells["vpd_kpa"].mean())


class FakeLoader:
    def __init__(self):
        self.calls: list[pd.Timestamp] = []

    def __call__(self, timestamp: pd.Timestamp) -> xr.Dataset:
        self.calls.append(timestamp)
        return _dataset(float(timestamp.hour - 19))


class NoCallLoader:
    def __init__(self):
        self.calls = 0

    def __call__(self, timestamp: pd.Timestamp):
        self.calls += 1
        raise AssertionError(f"loader should not run for {timestamp}")


def _two_hour_manifest() -> pd.DataFrame:
    return hrrr.build_hrrr_request_manifest(
        pd.DataFrame(
            {
                "city": ["phoenix"],
                "acquisition_utc": pd.to_datetime(["2023-07-18T19:30:00Z"], utc=True),
            }
        )
    )


def _fake_index() -> str:
    return "\n".join(
        [
            "1:0:d=2023071819:VIS:surface:anl:",
            "2:100:d=2023071819:TMP:2 m above ground:anl:",
            "3:1300:d=2023071819:POT:2 m above ground:anl:",
            "4:2500:d=2023071819:DPT:2 m above ground:anl:",
            "5:3600:d=2023071819:RH:2 m above ground:anl:",
        ]
    )


def test_index_storage_estimate_and_live_budget_guard() -> None:
    assert hrrr.hrrr_subset_bytes_from_index(_fake_index()) == 2300
    manifest = _two_hour_manifest()
    estimates = hrrr.estimate_hrrr_subset_downloads(
        manifest,
        index_reader=lambda _: _fake_index(),
        safety_factor=2.0,
        max_workers=2,
    )
    assert estimates["exact_subset_bytes"].tolist() == [2300, 2300]
    assert estimates["conservative_new_data_bytes"].tolist() == [4600, 4600]

    with tempfile.TemporaryDirectory(prefix="hrrr-storage-guard-") as temporary:
        try:
            hrrr.fetch_hrrr_domain_weather(
                manifest,
                {"phoenix": PHOENIX_TEST_DOMAIN},
                temporary,
                max_analysis_hours=2,
            )
        except hrrr.HrrrFetchError as exc:
            assert "requires a reviewed per-item storage estimate" in str(exc)
        else:
            raise AssertionError("live fetch should require a storage estimate")

        estimate_map = estimates.set_index("item_id")[
            "conservative_new_data_bytes"
        ].to_dict()
        try:
            hrrr.fetch_hrrr_domain_weather(
                manifest,
                {"phoenix": PHOENIX_TEST_DOMAIN},
                temporary,
                max_analysis_hours=2,
                conservative_download_bytes_by_item=estimate_map,
                max_new_data_bytes=9000,
            )
        except hrrr.HrrrFetchError as exc:
            assert "budget is 9000 bytes" in str(exc)
        else:
            raise AssertionError("live fetch should enforce the reviewed byte budget")


def test_hour_shards_checkpoint_resume_hash_and_tamper_recovery() -> None:
    manifest = _two_hour_manifest()
    domains = {"phoenix": PHOENIX_TEST_DOMAIN}
    with tempfile.TemporaryDirectory(prefix="hrrr-fetch-") as temporary:
        root = Path(temporary)
        loader = FakeLoader()
        first = hrrr.fetch_hrrr_domain_weather(
            manifest,
            domains,
            root,
            loader=loader,
            max_analysis_hours=2,
        )
        assert len(loader.calls) == 2
        assert len(first.summary) == 2
        assert (first.summary["n_domain_cells"] == 4).all()
        assert first.summary_path.is_file()
        assert first.shard_index_path.is_file()

        checkpoint = root / "hrrr_checkpoint.json"
        checkpoint_text = checkpoint.read_text(encoding="utf-8")
        payload = json.loads(checkpoint_text)
        assert len(payload["items"]) == 2
        assert "https://" not in checkpoint_text
        assert "grib_url" not in checkpoint_text
        assert all(item["sha256"] for item in payload["items"].values())

        no_call = NoCallLoader()
        second = hrrr.fetch_hrrr_domain_weather(
            manifest,
            domains,
            root,
            loader=no_call,
            max_analysis_hours=2,
        )
        assert no_call.calls == 0
        assert np.allclose(first.summary["vpd_kpa"], second.summary["vpd_kpa"])

        damaged = Path(first.shard_index.loc[0, "local_path"])
        damaged.write_bytes(b"damaged")
        recovery = FakeLoader()
        repaired = hrrr.fetch_hrrr_domain_weather(
            manifest,
            domains,
            root,
            loader=recovery,
            max_analysis_hours=2,
        )
        assert len(recovery.calls) == 1
        assert len(repaired.summary) == 2


def test_large_run_and_nonofficial_manifest_fail_before_loader() -> None:
    manifest = _two_hour_manifest()
    no_call = NoCallLoader()
    with tempfile.TemporaryDirectory(prefix="hrrr-guard-") as temporary:
        try:
            hrrr.fetch_hrrr_domain_weather(
                manifest,
                {"phoenix": PHOENIX_TEST_DOMAIN},
                temporary,
                loader=no_call,
                max_analysis_hours=1,
            )
        except hrrr.HrrrFetchError as exc:
            assert "Refusing 2 HRRR hours" in str(exc)
        else:
            raise AssertionError("large-run guard should stop before loading")
        assert no_call.calls == 0

        altered = manifest.copy()
        altered.loc[0, "grib_url"] = "https://example.test/not-official.grib2"
        try:
            hrrr.fetch_hrrr_domain_weather(
                altered,
                {"phoenix": PHOENIX_TEST_DOMAIN},
                temporary,
                loader=no_call,
                max_analysis_hours=2,
            )
        except ValueError as exc:
            assert "not the frozen NOAA/AWS HRRR request" in str(exc)
        else:
            raise AssertionError("nonofficial manifest should be rejected")
        assert no_call.calls == 0


def test_concurrent_fetch_preserves_manifest_order_and_checkpoint() -> None:
    manifest = _two_hour_manifest()
    with tempfile.TemporaryDirectory(prefix="hrrr-concurrent-") as temporary:
        loader = FakeLoader()
        result = hrrr.fetch_hrrr_domain_weather(
            manifest,
            {"phoenix": PHOENIX_TEST_DOMAIN},
            temporary,
            loader=loader,
            max_analysis_hours=2,
            max_workers=2,
        )
        assert len(loader.calls) == 2
        assert result.shard_index["item_id"].tolist() == manifest["item_id"].tolist()
        assert len(result.summary) == 2
        checkpoint = json.loads(
            (Path(temporary) / "hrrr_checkpoint.json").read_text(encoding="utf-8")
        )
        assert len(checkpoint["items"]) == 2


def test_d0047_profile_bound_run_seal_is_exact_and_tamper_evident() -> None:
    manifest = _two_hour_manifest()
    binding = {
        "decision_id": "D0047",
        "analysis_profile": "D0047_archive_available",
        "scientific_gate_scope": "archive_available_only",
        "geometry_passing_candidate_count": 1,
        "candidate_availability_ledger_sha256": "a" * 64,
    }
    status = "PASS_EXACT_HRRR_RUN_SEAL_D0047_ARCHIVE_AVAILABLE"
    with tempfile.TemporaryDirectory(prefix="hrrr-d0047-seal-") as temporary:
        result = hrrr.fetch_hrrr_domain_weather(
            manifest,
            {"phoenix": PHOENIX_TEST_DOMAIN},
            temporary,
            loader=FakeLoader(),
            max_analysis_hours=2,
            run_seal_status=status,
            profile_binding=binding,
        )
        document = json.loads(result.run_seal_path.read_text(encoding="utf-8"))
        assert document["status"] == status
        assert document["profile_binding"] == binding
        assert len(document["profile_binding_sha256"]) == 64
        validated = hrrr.validate_hrrr_run_seal(
            result.run_seal_path,
            manifest,
            {"phoenix": PHOENIX_TEST_DOMAIN},
            temporary,
            expected_status=status,
            expected_profile_binding=binding,
        )
        assert validated["profile_binding"] == binding
        altered = dict(binding)
        altered["geometry_passing_candidate_count"] = 2
        try:
            hrrr.validate_hrrr_run_seal(
                result.run_seal_path,
                manifest,
                {"phoenix": PHOENIX_TEST_DOMAIN},
                temporary,
                expected_status=status,
                expected_profile_binding=altered,
            )
        except hrrr.HrrrFetchError as exc:
            assert "profile binding" in str(exc)
        else:
            raise AssertionError("tampered D0047 profile binding should fail closed")


def test_checkpoint_request_and_frozen_domain_bindings_fail_closed() -> None:
    manifest = _two_hour_manifest()
    domains = {"phoenix": PHOENIX_TEST_DOMAIN}
    with tempfile.TemporaryDirectory(prefix="hrrr-binding-") as temporary:
        root = Path(temporary)
        hrrr.fetch_hrrr_domain_weather(
            manifest,
            domains,
            root,
            loader=FakeLoader(),
            max_analysis_hours=2,
        )
        checkpoint_path = root / "hrrr_checkpoint.json"
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        item_id = manifest.loc[0, "item_id"]
        checkpoint["items"][item_id]["request_binding"]["n_target_passes"] = 99
        checkpoint["items"][item_id]["request_sha256"] = hrrr._json_sha256(
            checkpoint["items"][item_id]["request_binding"]
        )
        checkpoint_path.write_text(
            json.dumps(checkpoint, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        recovery = FakeLoader()
        hrrr.fetch_hrrr_domain_weather(
            manifest,
            domains,
            root,
            loader=recovery,
            max_analysis_hours=2,
        )
        assert len(recovery.calls) == 1

        changed_domain = json.loads(json.dumps(PHOENIX_TEST_DOMAIN))
        changed_domain["coordinates"][0][0][0] -= 0.01
        changed_domain["coordinates"][0][-1][0] -= 0.01
        no_call = NoCallLoader()
        try:
            hrrr.fetch_hrrr_domain_weather(
                manifest,
                {"phoenix": changed_domain},
                root,
                loader=no_call,
                max_analysis_hours=2,
            )
        except hrrr.HrrrFetchError as exc:
            assert "manifest/domain binding is stale" in str(exc)
        else:
            raise AssertionError("a frozen-domain hash change must reject the checkpoint")
        assert no_call.calls == 0


def test_shard_content_and_run_seal_recomputation_detect_tampering() -> None:
    manifest = _two_hour_manifest()
    domains = {"phoenix": PHOENIX_TEST_DOMAIN}
    with tempfile.TemporaryDirectory(prefix="hrrr-content-seal-") as temporary:
        root = Path(temporary)
        manifest_path = root / "manifest.csv"
        manifest.to_csv(manifest_path, index=False)
        result = hrrr.fetch_hrrr_domain_weather(
            manifest,
            domains,
            root,
            manifest_path=manifest_path,
            loader=FakeLoader(),
            max_analysis_hours=2,
        )
        seal = json.loads(result.run_seal_path.read_text(encoding="utf-8"))
        assert seal["manifest_file_sha256"] == hrrr._sha256(manifest_path)

        checkpoint_path = result.checkpoint_path
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        item_id = manifest.loc[0, "item_id"]
        shard = Path(checkpoint["items"][item_id]["local_path"])
        cells = pd.read_csv(shard)
        cells.loc[0, "vpd_kpa"] += 1.0
        cells.to_csv(shard, index=False, compression="gzip")
        checkpoint["items"][item_id]["size_bytes"] = shard.stat().st_size
        checkpoint["items"][item_id]["sha256"] = hrrr._sha256(shard)
        checkpoint_path.write_text(
            json.dumps(checkpoint, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        recovery = FakeLoader()
        repaired = hrrr.fetch_hrrr_domain_weather(
            manifest,
            domains,
            root,
            manifest_path=manifest_path,
            loader=recovery,
            max_analysis_hours=2,
        )
        assert len(recovery.calls) == 1

        summary = pd.read_csv(repaired.summary_path)
        summary.loc[0, "vpd_kpa"] += 0.25
        summary.to_csv(repaired.summary_path, index=False)
        seal = json.loads(repaired.run_seal_path.read_text(encoding="utf-8"))
        seal["summary_sha256"] = hrrr._sha256(repaired.summary_path)
        repaired.run_seal_path.write_text(
            json.dumps(seal, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        try:
            hrrr.validate_hrrr_run_seal(
                repaired.run_seal_path,
                manifest,
                domains,
                root,
                manifest_path=manifest_path,
            )
        except hrrr.HrrrFetchError as exc:
            assert "differs from recomputation" in str(exc)
        else:
            raise AssertionError("a re-hashed but altered summary must fail recomputation")


def test_current_dependency_status_is_explicit() -> None:
    status = hrrr.dependency_status()
    assert set(status) == {"herbie", "cfgrib", "eccodes", "xarray", "live_ready"}
    assert status["live_ready"] == all(
        status[name] for name in ("herbie", "cfgrib", "eccodes", "xarray")
    )


def main() -> int:
    tests = [
        test_manifest_uses_unique_floor_and_ceiling_noaa_aws_analyses,
        test_manifest_freezes_exact_prs_fallback_for_missing_sfc_objects,
        test_manifest_accepts_mixed_fractional_and_whole_second_timestamps,
        test_tetens_vpd_formula_and_nonnegative_guard,
        test_herbie_loader_uses_frozen_product_for_each_analysis_hour,
        test_domain_cell_extraction_preserves_cells_and_spatial_spread,
        test_index_storage_estimate_and_live_budget_guard,
        test_hour_shards_checkpoint_resume_hash_and_tamper_recovery,
        test_large_run_and_nonofficial_manifest_fail_before_loader,
        test_concurrent_fetch_preserves_manifest_order_and_checkpoint,
        test_d0047_profile_bound_run_seal_is_exact_and_tamper_evident,
        test_checkpoint_request_and_frozen_domain_bindings_fail_closed,
        test_shard_content_and_run_seal_recomputation_detect_tampering,
        test_current_dependency_status_is_explicit,
    ]
    failures: list[tuple[str, Exception]] = []
    for test in tests:
        try:
            test()
        except Exception as exc:  # pragma: no cover - direct-run reporting
            failures.append((test.__name__, exc))
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
        else:
            print(f"PASS {test.__name__}")
    if failures:
        print(f"\n{len(failures)} of {len(tests)} HRRR-fetch tests failed")
        return 1
    print(f"\nAll {len(tests)} HRRR-fetch tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
